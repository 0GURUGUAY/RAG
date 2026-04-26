import base64
import json
import pathlib
import time
import urllib.parse
import urllib.request

import websocket


ROOT = pathlib.Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / 'docs' / 'screenshots'
APP_URL = 'http://127.0.0.1:8000/index.html'
DEBUG_BASE = 'http://127.0.0.1:9222'


class DevToolsClient:
    def __init__(self, ws_url):
        self._ws = websocket.create_connection(ws_url, timeout=20, suppress_origin=True)
        self._next_id = 1

    def close(self):
        try:
            self._ws.close()
        except Exception:
            pass

    def send(self, method, params=None):
        message_id = self._next_id
        self._next_id += 1
        payload = {'id': message_id, 'method': method, 'params': params or {}}
        self._ws.send(json.dumps(payload))
        while True:
            response = json.loads(self._ws.recv())
            if response.get('id') == message_id:
                if 'error' in response:
                    raise RuntimeError(f"{method} failed: {response['error']}")
                return response.get('result', {})


def http_json(url, method='GET'):
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode('utf-8'))


def wait_for_debugger(max_wait_seconds=15):
    last_error = None
    for _ in range(max_wait_seconds * 5):
        try:
            return http_json(f'{DEBUG_BASE}/json/version')
        except Exception as error:
            last_error = error
            time.sleep(0.2)
    raise RuntimeError(f'Chrome remote debugger unavailable: {last_error}')


def create_target(url):
    encoded = urllib.parse.quote(url, safe='')
    return http_json(f'{DEBUG_BASE}/json/new?{encoded}', method='PUT')


def eval_js(client, expression):
    return client.send(
        'Runtime.evaluate',
        {
            'expression': expression,
            'awaitPromise': True,
            'returnByValue': True,
        },
    )


def wait_ms(milliseconds):
    time.sleep(milliseconds / 1000)


def click(client, selector, delay_ms=700):
    escaped = selector.replace('\\', '\\\\').replace("'", "\\'")
    eval_js(
        client,
        f"(() => {{ const node = document.querySelector('{escaped}'); if (!node) throw new Error('Missing selector: {escaped}'); node.click(); return true; }})()",
    )
    wait_ms(delay_ms)


def set_active_view(client, tab_button_id, tab_panel_id, sub_button_id=None, sub_panel_id=None, maintenance_sub_button_id=None, maintenance_sub_panel_id=None):
        expression = f"""
(() => {{
    document.querySelectorAll('.tab-btn').forEach(node => node.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(node => node.classList.remove('active'));
    document.querySelectorAll('.page-subtab-btn').forEach(node => node.classList.remove('active'));
    document.querySelectorAll('.page-subpanel').forEach(node => node.classList.remove('active'));
    document.querySelectorAll('.maintenance-subtab-btn').forEach(node => node.classList.remove('active'));
    document.querySelectorAll('.maintenance-subpanel').forEach(node => node.classList.remove('active'));

    const topBtn = document.getElementById({json.dumps(tab_button_id)});
    const topPanel = document.getElementById({json.dumps(tab_panel_id)});
    if (!topBtn || !topPanel) throw new Error('Missing top-level tab nodes');
    topBtn.classList.add('active');
    topPanel.classList.add('active');

    const subBtnId = {json.dumps(sub_button_id)};
    const subPanelId = {json.dumps(sub_panel_id)};
    if (subBtnId && subPanelId) {{
        const subBtn = document.getElementById(subBtnId);
        const subPanel = document.getElementById(subPanelId);
        if (subBtn) subBtn.classList.add('active');
        if (subPanel) subPanel.classList.add('active');
    }}

    const maintenanceSubBtnId = {json.dumps(maintenance_sub_button_id)};
    const maintenanceSubPanelId = {json.dumps(maintenance_sub_panel_id)};
    if (maintenanceSubBtnId && maintenanceSubPanelId) {{
        const subBtn = document.getElementById(maintenanceSubBtnId);
        const subPanel = document.getElementById(maintenanceSubPanelId);
        if (subBtn) subBtn.classList.add('active');
        if (subPanel) subPanel.classList.add('active');
    }}

    const sidebar = document.getElementById('sidebar');
    if (sidebar) sidebar.scrollTop = 0;
    window.scrollTo(0, 0);
    return true;
}})()
"""
        eval_js(client, expression)
        wait_ms(900)


def screenshot(client, path):
    result = client.send('Page.captureScreenshot', {'format': 'png', 'fromSurface': True})
    path.write_bytes(base64.b64decode(result['data']))


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    wait_for_debugger()
    target = create_target(APP_URL)
    client = DevToolsClient(target['webSocketDebuggerUrl'])
    try:
        client.send('Page.enable')
        client.send('Runtime.enable')
        client.send('Emulation.setDeviceMetricsOverride', {
            'width': 1600,
            'height': 1000,
            'deviceScaleFactor': 1,
            'mobile': False,
        })
        client.send('Page.bringToFront')
        wait_ms(6000)

        # Force French UI when available.
        eval_js(client, "(() => { const btn = document.getElementById('langFrBtn'); if (btn) btn.click(); return document.documentElement.lang || 'fr'; })()")
        wait_ms(1200)

        captures = [
            ('01-cloud.png', {
                'tab_button_id': 'cloudTabBtn',
                'tab_panel_id': 'cloudTab',
                'sub_button_id': 'cloudAccountSubtabBtn',
                'sub_panel_id': 'cloudAccountPanel',
            }),
            ('02-routage.png', {
                'tab_button_id': 'routingTabBtn',
                'tab_panel_id': 'routingTab',
                'sub_button_id': 'routingMainSubtabBtn',
                'sub_panel_id': 'routingMainPanel',
            }),
            ('03-journal-nav.png', {
                'tab_button_id': 'navLogTabBtn',
                'tab_panel_id': 'navLogTab',
            }),
            ('04-documents-ia.png', {
                'tab_button_id': 'documentTabBtn',
                'tab_panel_id': 'documentTab',
                'sub_button_id': 'documentIaSubtabBtn',
                'sub_panel_id': 'documentIaPanel',
            }),
            ('05-maintenance-signalk.png', {
                'tab_button_id': 'maintenanceTabBtn',
                'tab_panel_id': 'maintenanceTab',
                'maintenance_sub_button_id': 'maintenanceSignalKSubtabBtn',
                'maintenance_sub_panel_id': 'maintenanceSignalKPanel',
            }),
            ('06-waypoint.png', {
                'tab_button_id': 'waypointTabBtn',
                'tab_panel_id': 'waypointTab',
            }),
        ]

        for filename, view in captures:
            set_active_view(client, **view)
            wait_ms(1400)
            screenshot(client, OUTPUT_DIR / filename)

    finally:
        client.close()


if __name__ == '__main__':
    main()