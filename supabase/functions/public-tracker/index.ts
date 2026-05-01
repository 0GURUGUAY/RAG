// @ts-nocheck
import { serve } from 'https://deno.land/std@0.224.0/http/server.ts';
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS'
};

const SHARE_TABLE = 'public_tracking_shares';
const NAV_LOG_TABLE = 'nav_log_entries';
const DEFAULT_HISTORY_HOURS = 72;
const MAX_HISTORY_HOURS = 720;
const MAX_TRACK_POINTS = 2400;

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, 'Content-Type': 'application/json' }
  });
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function isUuidString(value: unknown) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(String(value || '').trim());
}

function normalizeEmail(value: unknown) {
  return String(value || '').trim().toLowerCase();
}

function normalizeToken(value: unknown) {
  const token = String(value || '').trim();
  if (!/^[A-Za-z0-9_-]{16,120}$/.test(token)) return '';
  return token;
}

function createShareToken() {
  const bytes = crypto.getRandomValues(new Uint8Array(24));
  let base64 = btoa(String.fromCharCode(...bytes));
  base64 = base64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
  return base64;
}

function toTimestampMs(value: unknown) {
  const ts = Date.parse(String(value || ''));
  return Number.isFinite(ts) ? ts : NaN;
}

function toFinite(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeHistoryHours(value: unknown) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return DEFAULT_HISTORY_HOURS;
  return clamp(Math.round(parsed), 1, MAX_HISTORY_HOURS);
}

function sanitizeTrackPoint(point: any, fallback: any = {}) {
  const lat = toFinite(point?.lat ?? fallback?.lat);
  const lng = toFinite(point?.lng ?? point?.lon ?? fallback?.lng ?? fallback?.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;

  const timestamp = String(point?.timestamp || point?.watchTimeIso || point?.watch_time_iso || fallback?.timestamp || fallback?.watch_time_iso || fallback?.created_at || '').trim();
  return {
    lat,
    lng,
    timestamp: timestamp || new Date().toISOString(),
    speedKn: toFinite(point?.speedKn ?? point?.speed_kn ?? fallback?.speed_kn),
    headingDeg: toFinite(point?.headingDeg ?? point?.heading_deg ?? fallback?.heading_deg),
    heelDeg: toFinite(point?.heelDeg ?? point?.heel_deg ?? fallback?.heel_deg),
    windDirectionDeg: toFinite(point?.windDirectionDeg ?? point?.wind_direction_deg ?? fallback?.wind_direction_deg),
    windSpeedKn: toFinite(point?.windSpeedKn ?? point?.wind_speed_kn ?? fallback?.wind_speed_kn)
  };
}

function thinTrack(points: any[]) {
  if (points.length <= MAX_TRACK_POINTS) return points;
  const step = (points.length - 1) / (MAX_TRACK_POINTS - 1);
  const reduced = [];
  for (let index = 0; index < MAX_TRACK_POINTS; index += 1) {
    reduced.push(points[Math.round(index * step)]);
  }
  return reduced;
}

function buildTrackFromRows(rows: any[], historyHours: number) {
  const sinceMs = Date.now() - (historyHours * 60 * 60 * 1000);
  const rawPoints = [];
  const recentLogs = [];

  for (const row of Array.isArray(rows) ? rows : []) {
    const rowTimestamp = toTimestampMs(row?.watch_time_iso || row?.created_at || row?.updated_at);
    const traceSamples = Array.isArray(row?.trace_samples) ? row.trace_samples : [];

    if (traceSamples.length > 0) {
      for (const sample of traceSamples) {
        const point = sanitizeTrackPoint(sample, row);
        const pointTs = toTimestampMs(point?.timestamp);
        if (!point || (Number.isFinite(pointTs) && pointTs < sinceMs)) continue;
        rawPoints.push(point);
      }
    } else {
      const fallbackPoint = sanitizeTrackPoint(row, row);
      if (fallbackPoint && (!Number.isFinite(rowTimestamp) || rowTimestamp >= sinceMs)) {
        rawPoints.push(fallbackPoint);
      }
    }

    if (!Number.isFinite(rowTimestamp) || rowTimestamp < sinceMs) continue;
    recentLogs.push({
      timestamp: String(row?.watch_time_iso || row?.created_at || row?.updated_at || '').trim(),
      creatorName: String(row?.creator_name || '').trim(),
      watchCrew: String(row?.watch_crew || '').trim(),
      events: String(row?.events || '').trim(),
      lat: toFinite(row?.lat),
      lng: toFinite(row?.lng),
      speedKn: toFinite(row?.speed_kn),
      headingDeg: toFinite(row?.heading_deg),
      source: String(row?.source || '').trim()
    });
  }

  const sorted = rawPoints
    .filter(Boolean)
    .sort((a, b) => toTimestampMs(a?.timestamp) - toTimestampMs(b?.timestamp));

  const deduped = [];
  let lastKey = '';
  for (const point of sorted) {
    const key = `${point.timestamp}|${point.lat.toFixed(6)}|${point.lng.toFixed(6)}`;
    if (key === lastKey) continue;
    lastKey = key;
    deduped.push(point);
  }

  const track = thinTrack(deduped);
  const latestPoint = track.length ? track[track.length - 1] : null;
  const filteredLogs = recentLogs
    .sort((a, b) => toTimestampMs(b?.timestamp) - toTimestampMs(a?.timestamp))
    .slice(0, 12);

  return {
    track,
    latestPoint,
    recentLogs: filteredLogs,
    summary: {
      pointCount: track.length,
      lastSeenAt: latestPoint?.timestamp || '',
      lat: latestPoint?.lat ?? null,
      lng: latestPoint?.lng ?? null,
      speedKn: latestPoint?.speedKn ?? null,
      headingDeg: latestPoint?.headingDeg ?? null
    }
  };
}

function createServiceClient() {
  const supabaseUrl = String(Deno.env.get('SUPABASE_URL') || '').trim();
  const serviceRoleKey = String(Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') || '').trim();
  if (!supabaseUrl || !serviceRoleKey) {
    throw new Error('Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY');
  }
  return createClient(supabaseUrl, serviceRoleKey, { auth: { persistSession: false } });
}

async function getAuthenticatedUser(req: Request) {
  const supabaseUrl = String(Deno.env.get('SUPABASE_URL') || '').trim();
  const anonKey = String(Deno.env.get('SUPABASE_ANON_KEY') || '').trim();
  const authorization = String(req.headers.get('Authorization') || '').trim();
  if (!supabaseUrl || !anonKey || !authorization) return null;

  const authClient = createClient(supabaseUrl, anonKey, {
    auth: { persistSession: false },
    global: { headers: { Authorization: authorization } }
  });

  const { data, error } = await authClient.auth.getUser();
  if (error || !data?.user) return null;
  return data.user;
}

async function getShareRow(serviceClient: any, projectId: string, creatorEmail: string) {
  const { data, error } = await serviceClient
    .from(SHARE_TABLE)
    .select('*')
    .eq('project_id', projectId)
    .eq('creator_email', creatorEmail)
    .maybeSingle();

  if (error) throw error;
  return data || null;
}

function serializeShare(row: any) {
  if (!row || row.is_active === false || !normalizeToken(row.share_token)) return null;
  return {
    id: String(row.id || '').trim(),
    projectId: String(row.project_id || '').trim(),
    creatorEmail: normalizeEmail(row.creator_email),
    creatorName: String(row.creator_name || '').trim(),
    title: String(row.title || 'CEIBO live tracker').trim(),
    shareToken: String(row.share_token || '').trim(),
    historyHours: normalizeHistoryHours(row.history_hours),
    isActive: row.is_active !== false,
    updatedAt: String(row.updated_at || '').trim(),
    lastAccessedAt: String(row.last_accessed_at || '').trim()
  };
}

async function handleManagementRequest(req: Request) {
  const user = await getAuthenticatedUser(req);
  if (!user?.email) {
    return jsonResponse({ error: 'Unauthorized' }, 401);
  }

  const body = await req.json().catch(() => ({}));
  const action = String(body?.action || '').trim().toLowerCase();
  const projectId = String(body?.projectId || '').trim();
  if (!isUuidString(projectId)) {
    return jsonResponse({ error: 'Invalid projectId' }, 400);
  }

  const serviceClient = createServiceClient();
  const creatorEmail = normalizeEmail(user.email);

  if (action === 'status') {
    const shareRow = await getShareRow(serviceClient, projectId, creatorEmail);
    return jsonResponse({ ok: true, share: serializeShare(shareRow) });
  }

  if (action === 'disable') {
    const { error } = await serviceClient
      .from(SHARE_TABLE)
      .update({ is_active: false, updated_at: new Date().toISOString() })
      .eq('project_id', projectId)
      .eq('creator_email', creatorEmail);

    if (error) return jsonResponse({ error: String(error.message || error) }, 500);
    return jsonResponse({ ok: true, share: null });
  }

  if (action === 'create') {
    const existingShare = await getShareRow(serviceClient, projectId, creatorEmail);
    const rotateToken = body?.rotateToken === true;
    const title = String(body?.title || existingShare?.title || 'CEIBO live tracker').trim() || 'CEIBO live tracker';
    const historyHours = normalizeHistoryHours(body?.historyHours || existingShare?.history_hours);
    const shareToken = rotateToken || !normalizeToken(existingShare?.share_token)
      ? createShareToken()
      : String(existingShare.share_token).trim();

    const payload = {
      project_id: projectId,
      creator_email: creatorEmail,
      creator_name: String(body?.creatorName || user.user_metadata?.full_name || '').trim() || null,
      title,
      share_token: shareToken,
      history_hours: historyHours,
      is_active: true,
      updated_at: new Date().toISOString()
    };

    const { data, error } = await serviceClient
      .from(SHARE_TABLE)
      .upsert(payload, { onConflict: 'project_id,creator_email' })
      .select('*')
      .single();

    if (error) return jsonResponse({ error: String(error.message || error) }, 500);
    return jsonResponse({ ok: true, share: serializeShare(data) });
  }

  return jsonResponse({ error: 'Unsupported action' }, 400);
}

async function handlePublicRead(req: Request) {
  const requestUrl = new URL(req.url);
  const shareToken = normalizeToken(requestUrl.searchParams.get('token'));
  if (!shareToken) {
    return jsonResponse({ error: 'Missing token' }, 400);
  }

  const serviceClient = createServiceClient();
  const { data: shareRow, error: shareError } = await serviceClient
    .from(SHARE_TABLE)
    .select('*')
    .eq('share_token', shareToken)
    .eq('is_active', true)
    .maybeSingle();

  if (shareError) return jsonResponse({ error: String(shareError.message || shareError) }, 500);
  if (!shareRow?.project_id) return jsonResponse({ error: 'Share not found' }, 404);

  const historyHours = normalizeHistoryHours(requestUrl.searchParams.get('hours') || shareRow.history_hours);
  const { data: navRows, error: navError } = await serviceClient
    .from(NAV_LOG_TABLE)
    .select('watch_time_iso, watch_end_time_iso, trace_samples, lat, lng, speed_kn, heel_deg, heading_deg, wind_direction_deg, wind_speed_kn, source, watch_crew, events, creator_name, created_at, updated_at')
    .eq('project_id', String(shareRow.project_id))
    .order('created_at', { ascending: true });

  if (navError) return jsonResponse({ error: String(navError.message || navError) }, 500);

  const trackerPayload = buildTrackFromRows(navRows || [], historyHours);
  await serviceClient
    .from(SHARE_TABLE)
    .update({ last_accessed_at: new Date().toISOString() })
    .eq('id', String(shareRow.id));

  return jsonResponse({
    ok: true,
    title: String(shareRow.title || 'CEIBO live tracker').trim(),
    projectId: String(shareRow.project_id || '').trim(),
    historyHours,
    generatedAt: new Date().toISOString(),
    summary: trackerPayload.summary,
    latestPoint: trackerPayload.latestPoint,
    track: trackerPayload.track,
    recentLogs: trackerPayload.recentLogs
  });
}

serve(async req => {
  try {
    if (req.method === 'OPTIONS') {
      return new Response('ok', { headers: corsHeaders });
    }

    if (req.method === 'GET') {
      return await handlePublicRead(req);
    }

    if (req.method === 'POST') {
      return await handleManagementRequest(req);
    }

    return jsonResponse({ error: 'Method not allowed' }, 405);
  } catch (error) {
    return jsonResponse({ error: String(error?.message || error) }, 500);
  }
});