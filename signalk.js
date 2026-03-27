// ===============================
// CEIBO — SignalK WebSocket Client
// ===============================
// Connects to a SignalK server (e.g. on a Raspberry Pi 3) and streams
// navigation data into CEIBO variables. Designed to coexist safely with the
// autonomous mode (browser GPS + DeviceOrientation): all callbacks are
// optional and the module never throws if the server is unreachable.
//
// Usage:
//   import { SignalKClient } from './signalk.js';
//   const sk = new SignalKClient();
//   sk.onUpdate = ({ lat, lng, speedKn, courseDeg, heelDeg, twsDeg, twdDeg,
//                    baroPa, engineRunning, engineRpm }) => { … };
//   sk.connect('192.168.1.50');   // host only, port defaults to 3000
//   sk.disconnect();
//   sk.getStatus();               // 'disconnected' | 'connecting' | 'connected' | 'error'

// ---- CONSTANTS ----
const SK_DEFAULT_PORT = 3000;
const SK_RECONNECT_DELAY_MIN_MS = 3000;
const SK_RECONNECT_DELAY_MAX_MS = 30000;
const SK_HEARTBEAT_INTERVAL_MS = 10000; // send keepalive ping
const SK_HEARTBEAT_TIMEOUT_MS  = 15000; // max wait for pong

// SignalK paths we are interested in.
const SK_PATHS = [
    'navigation.position',
    'navigation.speedOverGround',
    'navigation.courseOverGroundTrue',
    'navigation.attitude',
    'navigation.log',
    'environment.wind.speedTrue',
    'environment.wind.angleTrueWater',
    'environment.wind.speedOverGround',
    'environment.wind.speedApparent',
    'environment.wind.angleApparent',
    'environment.wind.angleTrueGround',
    'environment.wind.directionTrue',
    'environment.wind.directionMagnetic',
    'environment.outside.pressure',
    'environment.outside.temperature',
    'environment.outside.humidity',
    'environment.outside.relativeHumidity',
    'environment.outside.absoluteHumidity',
    'environment.outside.cloudCover',
    'environment.outside.precipitation',
    'propulsion.main.state',
    'propulsion.main.revolutions',
    // common plugin variants (including openweather)
    'environment.weather.temperature',
    'environment.weather.pressure',
    'environment.weather.humidity',
    'environment.weather.relativeHumidity',
    'environment.weather.absoluteHumidity',
    'environment.weather.cloudCover',
    'environment.weather.precipitation',
    // common OpenWeather plugin path variants
    'environment.openweather.temperature',
    'environment.openweather.pressure',
    'environment.openweather.humidity',
    'environment.openweather.cloudCover',
    'environment.openweather.precipitation',
    'environment.openweathermap.temperature',
    'environment.openweathermap.pressure',
    'environment.openweathermap.humidity',
    'environment.openweathermap.cloudCover',
    'environment.openweathermap.precipitation',
    // fallback props for multi-engine boats
    'propulsion.port.state',
    'propulsion.starboard.state',
];

// ---- HELPER ----
function buildSubscribeMessages() {
    const baseSubscribe = SK_PATHS.map(path => ({ path, period: 1000, policy: 'ideal' }));
    const weatherWildcardSubscribe = [
        { path: 'environment.*', period: 2000, policy: 'instant' },
        { path: 'environment.outside.*', period: 2000, policy: 'instant' },
        { path: 'environment.weather.*', period: 2000, policy: 'instant' },
        { path: 'environment.openweather.*', period: 2000, policy: 'instant' },
        { path: 'environment.openweathermap.*', period: 2000, policy: 'instant' }
    ];

    return [
        JSON.stringify({
            context: 'vessels.self',
            subscribe: baseSubscribe
        }),
        JSON.stringify({
            context: '*',
            subscribe: weatherWildcardSubscribe
        })
    ];
}

function extractNumericValue(value) {
    if (Number.isFinite(value)) return Number(value);
    if (!value || typeof value !== 'object') return null;

    const candidates = [
        value.value,
        value.current,
        value.rate,
        value.amount,
        value.intensity,
        value.mm,
        value.mmh,
        value.hpa,
        value.kelvin,
        value.celsius,
        value.percent,
        value.ratio
    ];

    for (const candidate of candidates) {
        const n = Number(candidate);
        if (Number.isFinite(n)) return n;
    }

    // Recursive fallback for nested plugin payloads, depth-limited.
    const stack = [{ node: value, depth: 0 }];
    while (stack.length) {
        const { node, depth } = stack.pop();
        if (!node || typeof node !== 'object' || depth > 3) continue;
        for (const nested of Object.values(node)) {
            const n = Number(nested);
            if (Number.isFinite(n)) return n;
            if (nested && typeof nested === 'object') {
                stack.push({ node: nested, depth: depth + 1 });
            }
        }
    }

    return null;
}

function isWeatherLikePath(path) {
    const p = String(path || '').toLowerCase();
    return /(weather|meteo|temp|humid|cloud|rain|precip|pressure|openweather)/.test(p);
}

// ---- CLASS ----
export class SignalKClient {
    constructor() {
        this._ws        = null;
        this._host      = '';
        this._status    = 'disconnected';
        this._reconnectDelay = SK_RECONNECT_DELAY_MIN_MS;
        this._reconnectTimer = null;
        this._heartbeatTimer = null;
        this._heartbeatWatchdog = null;
        this._destroyed  = false;
        this._lastValues = {};

        // Public callbacks — assign from outside
        this.onUpdate      = null;  // (data) => {}
        this.onStatusChange = null; // (status) => {}
    }

    // ---- PUBLIC API ----

    connect(host) {
        this._destroyed = false;
        const rawHost   = String(host || '').trim();
        // Accept "host", "host:port", "ws://host:port"
        let finalHost = rawHost;
        if (/^wss?:\/\//i.test(finalHost)) {
            // strip scheme so we can re-add with explicit port handling
            finalHost = finalHost.replace(/^wss?:\/\//i, '');
        }
        this._host = finalHost || 'localhost';
        this._clearTimers();
        this._reconnectDelay = SK_RECONNECT_DELAY_MIN_MS;
        this._doConnect();
    }

    disconnect() {
        this._destroyed = true;
        this._clearTimers();
        this._setStatus('disconnected');
        if (this._ws) {
            try { this._ws.close(); } catch (_) { /* ignore */ }
            this._ws = null;
        }
        this._lastValues = {};
    }

    getStatus() {
        return this._status;
    }

    getLastValues() {
        return { ...this._lastValues };
    }

    // ---- PRIVATE ----

    _setStatus(status) {
        if (this._status === status) return;
        this._status = status;
        if (typeof this.onStatusChange === 'function') {
            try { this.onStatusChange(status); } catch (_) { /* ignore */ }
        }
    }

    _buildWsUrl() {
        const h = this._host;
        if (h.includes(':')) {
            // host:port supplied
            return `ws://${h}/signalk/v1/stream?subscribe=none`;
        }
        return `ws://${h}:${SK_DEFAULT_PORT}/signalk/v1/stream?subscribe=none`;
    }

    _doConnect() {
        if (this._destroyed) return;
        this._setStatus('connecting');

        const url = this._buildWsUrl();
        let ws;
        try {
            ws = new WebSocket(url);
        } catch (err) {
            console.warn('[SignalK] WebSocket creation failed:', err.message);
            this._setStatus('error');
            this._scheduleReconnect();
            return;
        }

        this._ws = ws;

        ws.onopen = () => {
            if (ws !== this._ws) return;
            this._reconnectDelay = SK_RECONNECT_DELAY_MIN_MS;
            this._setStatus('connected');
            // Subscribe to primary and wildcard weather paths.
            for (const message of buildSubscribeMessages()) {
                try { ws.send(message); } catch (_) { /* ignore */ }
            }
            this._startHeartbeat();
        };

        ws.onmessage = (event) => {
            if (ws !== this._ws) return;
            try {
                this._handleMessage(JSON.parse(event.data));
            } catch (_) { /* ignore malformed messages */ }
        };

        ws.onerror = () => {
            if (ws !== this._ws) return;
            this._setStatus('error');
        };

        ws.onclose = () => {
            if (ws !== this._ws) return;
            this._clearHeartbeat();
            const prev = this._status;
            this._setStatus('disconnected');
            if (!this._destroyed) {
                if (prev !== 'error') this._setStatus('error');
                this._scheduleReconnect();
            }
        };
    }

    _handleMessage(msg) {
        // Heartbeat pong
        if (msg.name === 'pong' || msg.type === 'pong') {
            this._resetHeartbeatWatchdog();
            return;
        }

        // SignalK delta format: { updates: [{ values: [{ path, value }] }] }
        const updates = msg.updates;
        if (!Array.isArray(updates)) return;

        const prev = { ...this._lastValues };
        let changed = false;

        for (const update of updates) {
            const values = update?.values;
            if (!Array.isArray(values)) continue;
            for (const item of values) {
                const { path, value } = item;
                if (typeof path !== 'string') continue;
                if (isWeatherLikePath(path)) {
                    this._lastValues.weatherFrameTick = Date.now();
                    const cleaned = String(path || '').trim();
                    if (cleaned && cleaned.toLowerCase() !== 'null') {
                        this._lastValues.weatherPathLast = cleaned;
                    }
                }
                this._processPathValue(path, value);
                changed = true;
            }
        }

        if (changed && typeof this.onUpdate === 'function') {
            try { this.onUpdate(this.getLastValues()); } catch (_) { /* ignore */ }
        }
    }

    _processPathValue(path, value) {
        const v = this._lastValues;

        switch (path) {
            case 'navigation.position':
                if (value && Number.isFinite(value.latitude) && Number.isFinite(value.longitude)) {
                    v.lat = value.latitude;
                    v.lng = value.longitude;
                }
                break;

            case 'navigation.speedOverGround':
                // SignalK uses m/s
                if (Number.isFinite(value)) v.speedKn = value * 1.943844;
                break;

            case 'navigation.courseOverGroundTrue':
                // SignalK uses radians
                if (Number.isFinite(value)) v.courseDeg = (value * 180 / Math.PI + 360) % 360;
                break;

            case 'navigation.attitude':
                // roll = heel in radians (positive = starboard heel = negative gamma on iPad convention)
                if (value && Number.isFinite(value.roll)) {
                    v.heelDeg = value.roll * 180 / Math.PI;
                }
                break;

            case 'navigation.log':
                // Distance in meters
                if (Number.isFinite(value)) v.logNm = value / 1852;
                break;

            case 'environment.wind.speedTrue':
                if (Number.isFinite(value)) v.twsKn = value * 1.943844;
                break;

            case 'environment.wind.speedOverGround':
            case 'environment.wind.speedApparent':
                if (Number.isFinite(value)) v.twsKn = value * 1.943844;
                break;

            case 'environment.wind.angleTrueWater':
                // radians, signed (negative = port tack)
                if (Number.isFinite(value)) v.twaDeg = (value * 180 / Math.PI + 360) % 360;
                break;

            case 'environment.wind.angleApparent':
            case 'environment.wind.angleTrueGround':
                if (Number.isFinite(value)) v.twaDeg = (value * 180 / Math.PI + 360) % 360;
                break;

            case 'environment.wind.directionTrue':
            case 'environment.wind.directionMagnetic':
                if (Number.isFinite(value)) {
                    // direction may be in radians depending on source
                    v.twdDeg = value <= (2 * Math.PI + 0.01)
                        ? ((value * 180 / Math.PI + 360) % 360)
                        : ((value % 360) + 360) % 360;
                }
                break;

            case 'environment.outside.pressure':
                // Pascals (or already hPa) -> normalized hPa + legacy Pa key.
                {
                    const n = extractNumericValue(value);
                    if (Number.isFinite(n)) {
                        v.baroPa = n;
                        v.baroHpa = n > 2000 ? n / 100 : n;
                        v.weatherFrameTick = Date.now();
                    }
                }
                break;

            case 'environment.outside.temperature':
            case 'environment.weather.temperature':
                // SignalK commonly reports Kelvin. Keep Celsius for UI/logs.
                {
                    const n = extractNumericValue(value);
                    if (Number.isFinite(n)) {
                        v.airTempC = n > 150 ? (n - 273.15) : n;
                        v.weatherFrameTick = Date.now();
                    }
                }
                break;

            case 'environment.outside.humidity':
            case 'environment.weather.humidity':
            case 'environment.outside.relativeHumidity':
            case 'environment.weather.relativeHumidity':
                // SignalK may provide ratio (0-1) or percentage (0-100).
                {
                    const n = extractNumericValue(value);
                    if (Number.isFinite(n)) {
                        v.humidityPct = n <= 1 ? (n * 100) : n;
                        v.weatherFrameTick = Date.now();
                    }
                }
                break;

            case 'environment.outside.absoluteHumidity':
            case 'environment.weather.absoluteHumidity':
                // Usually expressed in g/m3.
                {
                    const n = extractNumericValue(value);
                    if (Number.isFinite(n)) {
                        v.absHumidityGm3 = n;
                        v.weatherFrameTick = Date.now();
                    }
                }
                break;

            case 'environment.outside.cloudCover':
            case 'environment.weather.cloudCover':
                {
                    const n = extractNumericValue(value);
                    if (Number.isFinite(n)) {
                        v.cloudCoverPct = n <= 1 ? (n * 100) : n;
                        v.weatherFrameTick = Date.now();
                    }
                }
                break;

            case 'environment.outside.precipitation':
            case 'environment.weather.precipitation':
                {
                    const n = extractNumericValue(value);
                    if (Number.isFinite(n)) {
                        v.rainRateMmH = n;
                        v.weatherFrameTick = Date.now();
                    }
                }
                break;

            case 'propulsion.main.state':
            case 'propulsion.port.state':
            case 'propulsion.starboard.state':
                if (typeof value === 'string') {
                    v.engineRunning = (value === 'started');
                }
                break;

            case 'propulsion.main.revolutions':
                // rev/s → RPM
                if (Number.isFinite(value)) v.engineRpm = Math.round(value * 60);
                break;

            default:
                // Generic fallback for plugin-specific weather paths.
                this._processWeatherFallback(path, value);
                break;
        }
    }

    _processWeatherFallback(path, value) {
        const p = String(path || '').toLowerCase();
        const weatherLike = isWeatherLikePath(p);
        if (weatherLike) {
            // Count weather-like frames even when payload shape is non-standard.
            this._lastValues.weatherFrameTick = Date.now();
            const cleaned = String(path || '').trim();
            if (cleaned && cleaned.toLowerCase() !== 'null') {
                this._lastValues.weatherPathLast = cleaned;
            }
        }

        const n = extractNumericValue(value);
        if (!Number.isFinite(n)) return;

        if (p.includes('temperature')) {
            this._lastValues.airTempC = n > 150 ? (n - 273.15) : n;
            return;
        }
        if (p.includes('humidity')) {
            this._lastValues.humidityPct = n <= 1 ? (n * 100) : n;
            return;
        }
        if (p.includes('cloud') && p.includes('cover')) {
            this._lastValues.cloudCoverPct = n <= 1 ? (n * 100) : n;
            return;
        }
        if (p.includes('precipitation') || p.includes('rain')) {
            this._lastValues.rainRateMmH = n;
            return;
        }
        if (p.includes('pressure')) {
            this._lastValues.baroHpa = n > 2000 ? (n / 100) : n;
        }
    }

    _startHeartbeat() {
        this._clearHeartbeat();
        this._heartbeatTimer = window.setInterval(() => {
            if (this._ws && this._ws.readyState === WebSocket.OPEN) {
                try {
                    this._ws.send(JSON.stringify({ type: 'ping' }));
                    // Start watchdog
                    if (this._heartbeatWatchdog !== null) {
                        window.clearTimeout(this._heartbeatWatchdog);
                    }
                    this._heartbeatWatchdog = window.setTimeout(() => {
                        // No pong received — reconnect
                        if (this._ws) {
                            try { this._ws.close(); } catch (_) { /* ignore */ }
                        }
                    }, SK_HEARTBEAT_TIMEOUT_MS);
                } catch (_) { /* ignore */ }
            }
        }, SK_HEARTBEAT_INTERVAL_MS);
    }

    _resetHeartbeatWatchdog() {
        if (this._heartbeatWatchdog !== null) {
            window.clearTimeout(this._heartbeatWatchdog);
            this._heartbeatWatchdog = null;
        }
    }

    _clearHeartbeat() {
        if (this._heartbeatTimer !== null) {
            window.clearInterval(this._heartbeatTimer);
            this._heartbeatTimer = null;
        }
        this._resetHeartbeatWatchdog();
    }

    _scheduleReconnect() {
        if (this._destroyed) return;
        if (this._reconnectTimer !== null) return;
        this._reconnectTimer = window.setTimeout(() => {
            this._reconnectTimer = null;
            if (!this._destroyed) this._doConnect();
        }, this._reconnectDelay);
        // Exponential backoff capped at max
        this._reconnectDelay = Math.min(this._reconnectDelay * 1.5, SK_RECONNECT_DELAY_MAX_MS);
    }

    _clearTimers() {
        if (this._reconnectTimer !== null) {
            window.clearTimeout(this._reconnectTimer);
            this._reconnectTimer = null;
        }
        this._clearHeartbeat();
    }
}
