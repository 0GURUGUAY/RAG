// @ts-nocheck
import { serve } from 'https://deno.land/std@0.224.0/http/server.ts';

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS'
};

const AISTREAM_URL = 'wss://stream.aisstream.io/v0/stream';
const DEFAULT_SAMPLE_WINDOW_MS = 9000;
const DEFAULT_LIMIT = 320;

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, 'Content-Type': 'application/json' }
  });
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function firstFinite(values: unknown[]) {
  for (const value of values) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function cleanShipName(value: unknown) {
  return String(value || '').replace(/@+/g, ' ').replace(/\s+/g, ' ').trim();
}

function normalizeBounds(body: any) {
  const source = body?.bounds || body || {};
  const south = clamp(Number(source?.south), -90, 90);
  const west = clamp(Number(source?.west), -180, 180);
  const north = clamp(Number(source?.north), -90, 90);
  const east = clamp(Number(source?.east), -180, 180);

  if (![south, west, north, east].every(Number.isFinite)) {
    throw new Error('Invalid AIS bounds');
  }
  if (south === north || west === east) {
    throw new Error('AIS bounds too small');
  }

  return {
    south: Math.min(south, north),
    west: Math.min(west, east),
    north: Math.max(south, north),
    east: Math.max(west, east)
  };
}

function normalizeLimit(body: any) {
  const value = Number(body?.limit);
  if (!Number.isFinite(value)) return DEFAULT_LIMIT;
  return clamp(Math.round(value), 1, 500);
}

function normalizeSampleWindowMs(body: any) {
  const value = Number(body?.sampleWindowMs);
  if (!Number.isFinite(value)) return DEFAULT_SAMPLE_WINDOW_MS;
  return clamp(Math.round(value), 1500, 12000);
}

function expandBounds(bounds: { south: number; west: number; north: number; east: number }, deltaDeg: number) {
  const delta = Math.max(0, Number(deltaDeg) || 0);
  return {
    south: clamp(bounds.south - delta, -90, 90),
    west: clamp(bounds.west - delta, -180, 180),
    north: clamp(bounds.north + delta, -90, 90),
    east: clamp(bounds.east + delta, -180, 180)
  };
}

function mergeSnapshotVessels(primary: any, secondary: any, limit: number) {
  const byMmsi = new Map<string, any>();
  for (const vessel of Array.isArray(primary?.vessels) ? primary.vessels : []) {
    const mmsi = String(vessel?.mmsi || '').trim();
    if (!mmsi) continue;
    byMmsi.set(mmsi, vessel);
  }
  for (const vessel of Array.isArray(secondary?.vessels) ? secondary.vessels : []) {
    const mmsi = String(vessel?.mmsi || '').trim();
    if (!mmsi) continue;
    const existing = byMmsi.get(mmsi) || null;
    if (!existing) {
      byMmsi.set(mmsi, vessel);
      continue;
    }
    byMmsi.set(mmsi, {
      ...existing,
      ...Object.fromEntries(Object.entries(vessel).filter(([, value]) => value !== null && value !== '')),
      lat: Number.isFinite(Number(vessel?.lat)) ? Number(vessel.lat) : existing.lat,
      lon: Number.isFinite(Number(vessel?.lon)) ? Number(vessel.lon) : existing.lon
    });
  }

  const list = Array.from(byMmsi.values())
    .filter(item => Number.isFinite(item?.lat) && Number.isFinite(item?.lon))
    .sort((a, b) => {
      const timeA = Date.parse(String(a?.timestamp || '')) || 0;
      const timeB = Date.parse(String(b?.timestamp || '')) || 0;
      return timeB - timeA;
    })
    .slice(0, limit);

  return { ok: true, vessels: list, count: list.length };
}

function extractVesselData(payload: any) {
  const metadata = payload?.MetaData || payload?.Metadata || {};
  const messageType = String(payload?.MessageType || '').trim();
  const messageContainer = payload?.Message && typeof payload.Message === 'object' ? payload.Message : {};
  const message = messageContainer[messageType] || {};
  const mmsi = String(metadata?.MMSI || message?.UserID || '').trim();
  if (!mmsi) return null;

  const lat = firstFinite([message?.Latitude, metadata?.latitude, metadata?.Latitude]);
  const lon = firstFinite([message?.Longitude, metadata?.longitude, metadata?.Longitude]);
  const sog = firstFinite([message?.Sog]);
  const cog = firstFinite([message?.Cog]);
  const heading = firstFinite([message?.TrueHeading]);
  const timestamp = String(metadata?.time_utc || '').trim();
  const name = cleanShipName(
    metadata?.ShipName
    || message?.Name
    || message?.ReportA?.Name
    || message?.ReportB?.CallSign
  );

  return {
    mmsi,
    name,
    lat,
    lon,
    sog,
    cog,
    heading: Number.isFinite(heading) && heading <= 360 ? heading : null,
    timestamp,
    messageType
  };
}

async function readWebSocketMessageData(data: unknown) {
  if (typeof data === 'string') return data;
  if (data instanceof Blob) return await data.text();
  if (data instanceof ArrayBuffer) return new TextDecoder().decode(data);
  if (ArrayBuffer.isView(data)) {
    return new TextDecoder().decode(data);
  }
  return String(data ?? '');
}

async function collectSnapshot({ apiKey, bounds, limit, sampleWindowMs }: {
  apiKey: string;
  bounds: { south: number; west: number; north: number; east: number };
  limit: number;
  sampleWindowMs: number;
}) {
  return await new Promise<any>((resolve, reject) => {
    const vessels = new Map<string, any>();
    let settled = false;
    let ws: WebSocket | null = null;
    const deadlineMs = Date.now() + sampleWindowMs;
    let reconnectCount = 0;
    const maxReconnects = 1;

    const finish = (error?: Error) => {
      if (settled) return;
      settled = true;
      try {
        ws?.close();
      } catch {
        // ignore close failures
      }
      if (error) {
        reject(error);
        return;
      }

      const list = Array.from(vessels.values())
        .filter(item => Number.isFinite(item?.lat) && Number.isFinite(item?.lon))
        .sort((a, b) => {
          const timeA = Date.parse(String(a?.timestamp || '')) || 0;
          const timeB = Date.parse(String(b?.timestamp || '')) || 0;
          return timeB - timeA;
        })
        .slice(0, limit);
      resolve({ ok: true, vessels: list, count: list.length });
    };

    const timeoutId = setTimeout(() => finish(), sampleWindowMs);

    const openSocket = () => {
      if (settled) return;
      ws = new WebSocket(AISTREAM_URL);

      ws.addEventListener('open', () => {
        ws?.send(JSON.stringify({
          APIKey: apiKey,
          BoundingBoxes: [[[bounds.south, bounds.west], [bounds.north, bounds.east]]]
        }));
      });

      ws.addEventListener('message', async event => {
        try {
          const rawMessage = await readWebSocketMessageData(event.data);
          const payload = JSON.parse(rawMessage || '{}');
          if (payload?.error) {
            clearTimeout(timeoutId);
            finish(new Error(String(payload.error)));
            return;
          }

          const vessel = extractVesselData(payload);
          if (!vessel) return;

          const previous = vessels.get(vessel.mmsi) || null;
          if (!previous) {
            if (!Number.isFinite(vessel.lat) || !Number.isFinite(vessel.lon)) return;
            vessels.set(vessel.mmsi, vessel);
          } else {
            vessels.set(vessel.mmsi, {
              ...previous,
              ...Object.fromEntries(Object.entries(vessel).filter(([, value]) => value !== null && value !== '')),
              lat: Number.isFinite(vessel.lat) ? vessel.lat : previous.lat,
              lon: Number.isFinite(vessel.lon) ? vessel.lon : previous.lon
            });
          }

          if (vessels.size >= limit) {
            clearTimeout(timeoutId);
            finish();
          }
        } catch (error) {
          clearTimeout(timeoutId);
          finish(error instanceof Error ? error : new Error(String(error)));
        }
      });

      ws.addEventListener('error', () => {
        const stillTime = Date.now() < deadlineMs;
        if (!settled && stillTime && reconnectCount < maxReconnects) {
          reconnectCount += 1;
          try {
            ws?.close();
          } catch {
            // ignore close failures
          }
          openSocket();
          return;
        }
        clearTimeout(timeoutId);
        finish(new Error('AIS websocket error'));
      });

      ws.addEventListener('close', () => {
        if (settled) return;
        const stillTime = Date.now() < deadlineMs;
        if (stillTime && reconnectCount < maxReconnects) {
          reconnectCount += 1;
          openSocket();
          return;
        }
        if (!stillTime) {
          finish();
          return;
        }
        clearTimeout(timeoutId);
        finish();
      });
    };

    openSocket();
  });
}

serve(async req => {
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: corsHeaders });
  }

  if (req.method !== 'POST') {
    return jsonResponse({ error: 'Method not allowed' }, 405);
  }

  const apiKey = String(Deno.env.get('AISSTREAM_API_KEY') || '').trim();
  if (!apiKey) {
    return jsonResponse({ error: 'Missing AISSTREAM_API_KEY secret' }, 500);
  }

  try {
    const body = await req.json().catch(() => ({}));
    const bounds = normalizeBounds(body);
    const limit = normalizeLimit(body);
    const sampleWindowMs = normalizeSampleWindowMs(body);
    const snapshot = await collectSnapshot({ apiKey, bounds, limit, sampleWindowMs });

    if ((Number(snapshot?.count) || 0) > 0) {
      return jsonResponse(snapshot, 200);
    }

    const expandedBounds = expandBounds(bounds, 0.14);
    const fallbackSampleWindowMs = clamp(sampleWindowMs + 2500, 1500, 12000);
    const fallbackSnapshot = await collectSnapshot({
      apiKey,
      bounds: expandedBounds,
      limit,
      sampleWindowMs: fallbackSampleWindowMs
    });

    const merged = mergeSnapshotVessels(snapshot, fallbackSnapshot, limit);
    return jsonResponse(merged, 200);
  } catch (error) {
    return jsonResponse({ error: String(error?.message || error) }, 500);
  }
});