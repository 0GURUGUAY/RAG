#!/usr/bin/env python3

import argparse
import asyncio
import json
import math
import signal
import sys
import time
from http import HTTPStatus

import serial
from websockets.asyncio.server import serve


def build_discovery(host, port):
    return {
        "endpoints": {
            "v1": {
                "version": "1.0.0",
                "signalk-http": f"http://{host}:{port}/signalk/v1/api/",
                "signalk-ws": f"ws://{host}:{port}/signalk/v1/stream",
            }
        },
        "server": {
            "id": "ceibo-fake-signalk-bridge",
            "version": "0.1.0",
        },
    }


class FakeSignalKBridge:
    def __init__(self, serial_port, baudrate, host, port):
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.host = host
        self.port = port
        self.discovery = build_discovery(host, port)
        self.clients = set()
        self.latest_delta = None
        self.latest_snapshot = {
            "self": "vessels.self",
            "vessels": {"self": {"environment": {"outside": {}, "weather": {}}}},
        }
        self.serial_reader = None
        self.stop_event = asyncio.Event()
        self.started_at = time.time()

    def build_delta(self, payload):
        temperature_c = payload.get("temperature_c")
        humidity_pct = payload.get("humidity_pct")
        joystick = payload.get("joystick") or {}
        joystick_x = joystick.get("x")
        joystick_y = joystick.get("y")
        joystick_pressed = joystick.get("pressed")
        joystick_direction = joystick.get("direction")
        joystick_button_event = joystick.get("button_event")
        values = []

        if isinstance(temperature_c, (int, float)) and math.isfinite(temperature_c):
            temperature_k = round(float(temperature_c) + 273.15, 2)
            values.append({"path": "environment.outside.temperature", "value": temperature_k})
            values.append({"path": "environment.weather.temperature", "value": temperature_k})
            self.latest_snapshot["vessels"]["self"]["environment"]["outside"]["temperature"] = {
                "value": temperature_k,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "$source": "ceibo-bench.fake",
            }
            self.latest_snapshot["vessels"]["self"]["environment"]["weather"] = self.latest_snapshot["vessels"]["self"]["environment"]["weather"] or {}
            self.latest_snapshot["vessels"]["self"]["environment"]["weather"]["temperature"] = {
                "value": temperature_k,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "$source": "ceibo-bench.fake",
            }

        if isinstance(humidity_pct, (int, float)) and math.isfinite(humidity_pct):
            ratio = round(max(0.0, min(1.0, float(humidity_pct) / 100.0)), 4)
            values.append({"path": "environment.outside.relativeHumidity", "value": ratio})
            values.append({"path": "environment.weather.relativeHumidity", "value": ratio})
            self.latest_snapshot["vessels"]["self"]["environment"]["outside"]["relativeHumidity"] = {
                "value": ratio,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "$source": "ceibo-bench.fake",
            }
            self.latest_snapshot["vessels"]["self"]["environment"]["weather"]["relativeHumidity"] = {
                "value": ratio,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "$source": "ceibo-bench.fake",
            }

        if joystick:
            fake_joystick_snapshot = self.latest_snapshot["vessels"]["self"]["environment"]["outside"].setdefault("fakeJoystick", {})

            if isinstance(joystick_x, (int, float)) and math.isfinite(joystick_x):
                values.append({"path": "environment.outside.fakeJoystick.x", "value": joystick_x})
                fake_joystick_snapshot["x"] = joystick_x

            if isinstance(joystick_y, (int, float)) and math.isfinite(joystick_y):
                values.append({"path": "environment.outside.fakeJoystick.y", "value": joystick_y})
                fake_joystick_snapshot["y"] = joystick_y

            if isinstance(joystick_pressed, bool):
                values.append({"path": "environment.outside.fakeJoystick.pressed", "value": joystick_pressed})
                fake_joystick_snapshot["pressed"] = joystick_pressed

            if isinstance(joystick_direction, str) and joystick_direction:
                values.append({"path": "environment.outside.fakeJoystick.direction", "value": joystick_direction})
                fake_joystick_snapshot["direction"] = joystick_direction

            if joystick_button_event is True:
                values.append({"path": "environment.outside.fakeJoystick.buttonEvent", "value": True})

        if not values:
            return None

        return {
            "context": "vessels.self",
            "updates": [
                {
                    "$source": "ceibo-bench.fake",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "values": values,
                }
            ],
        }

    async def broadcast_delta(self, delta):
        if not self.clients:
            return
        message = json.dumps(delta)
        dead_clients = []
        for websocket in self.clients:
            try:
                await websocket.send(message)
            except Exception:
                dead_clients.append(websocket)
        for websocket in dead_clients:
            self.clients.discard(websocket)

    async def serial_loop(self):
        loop = asyncio.get_running_loop()
        self.serial_reader = serial.Serial(self.serial_port, self.baudrate, timeout=1)
        print(f"[bridge] listening to serial {self.serial_port} @ {self.baudrate}")

        while not self.stop_event.is_set():
            line = await loop.run_in_executor(None, self.serial_reader.readline)
            if not line:
                continue
            try:
                payload = json.loads(line.decode("utf-8", errors="ignore").strip())
            except json.JSONDecodeError:
                continue
            delta = self.build_delta(payload)
            if delta is None:
                continue
            self.latest_delta = delta
            print(
                "[bridge] frame",
                payload.get("frame"),
                "temp_c=",
                payload.get("temperature_c"),
                "humidity_pct=",
                payload.get("humidity_pct"),
            )
            await self.broadcast_delta(delta)

    async def ws_handler(self, websocket):
        self.clients.add(websocket)
        try:
            if self.latest_delta is not None:
                await websocket.send(json.dumps(self.latest_delta))
            async for message in websocket:
                try:
                    payload = json.loads(message)
                except json.JSONDecodeError:
                    continue
                if payload.get("type") == "ping":
                    await websocket.send(json.dumps({"type": "pong"}))
        finally:
            self.clients.discard(websocket)

    async def process_request(self, connection, request):
        path = request.path
        if path == "/signalk":
            body = json.dumps(self.discovery)
            return connection.respond(HTTPStatus.OK, body)
        if path in {"/signalk/v1/api", "/signalk/v1/api/"}:
            body = json.dumps(self.latest_snapshot)
            return connection.respond(HTTPStatus.OK, body)
        if path == "/health":
            body = json.dumps({"ok": True, "uptime_s": round(time.time() - self.started_at, 1)})
            return connection.respond(HTTPStatus.OK, body)
        return None

    async def run(self):
        async with serve(
            self.ws_handler,
            self.host,
            self.port,
            process_request=self.process_request,
        ):
            print(f"[bridge] fake SignalK server ready on ws://{self.host}:{self.port}/signalk/v1/stream")
            await self.serial_loop()

    async def shutdown(self):
        self.stop_event.set()
        if self.serial_reader is not None and self.serial_reader.is_open:
            self.serial_reader.close()


def parse_args():
    parser = argparse.ArgumentParser(description="Fake SignalK bridge for CEIBO bench testing")
    parser.add_argument("--serial-port", required=True, help="Serial device, e.g. /dev/ttyACM0 or /dev/cu.usbmodem123")
    parser.add_argument("--baudrate", type=int, default=115200, help="Serial baudrate")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host for fake SignalK websocket server")
    parser.add_argument("--port", type=int, default=3000, help="Bind port for fake SignalK websocket server")
    return parser.parse_args()


async def main_async():
    args = parse_args()
    bridge = FakeSignalKBridge(args.serial_port, args.baudrate, args.host, args.port)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(bridge.shutdown()))
        except NotImplementedError:
            pass

    try:
        await bridge.run()
    finally:
        await bridge.shutdown()


def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()