#!/usr/bin/env python3
"""Local weather analysis bridge for CEIBO."""

from __future__ import annotations

import argparse
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from metpy.calc import wind_components
from metpy.units import units
from pydantic import BaseModel, Field

FORECAST_API = 'https://api.open-meteo.com/v1/forecast'
MARINE_API = 'https://marine-api.open-meteo.com/v1/marine'
ARCHIVE_API = 'https://archive-api.open-meteo.com/v1/archive'
REQUEST_TIMEOUT_S = 14
MAX_WORKERS = 8
CLIMATOLOGY_YEARS = 5
CLIMATOLOGY_WINDOW_DAYS = 1
KNOTS_PER_MPS = 1.9438444924406048

ATMOSERIC_FIELD_ALIASES = {
    'temperature_2m': 'temperature_c',
    'pressure_msl': 'pressure_hpa',
    'wind_speed_10m': 'wind_speed_kn',
    'windspeed_10m': 'wind_speed_kn',
    'wind_direction_10m': 'wind_direction_deg',
    'winddirection_10m': 'wind_direction_deg',
    'wind_gusts_10m': 'wind_gust_kn',
    'windgusts_10m': 'wind_gust_kn',
    'precipitation': 'precip_mm',
    'surface_pressure': 'pressure_hpa',
    'weather_code': 'weather_code',
}

MARINE_FIELD_ALIASES = {
    'wave_height': 'wave_height_m',
    'wave_direction': 'wave_direction_deg',
    'wave_period': 'wave_period_s',
    'sea_surface_temperature': 'sea_surface_temperature_c',
    'ocean_current_velocity': 'current_speed_ms',
    'ocean_current_direction': 'current_direction_deg',
}

MEDITERRANEAN_REFERENCE_POINTS = {
    'golfe_du_lion': (43.2, 4.8),
    'balearic': (40.0, 3.2),
    'ebro': (41.5, 0.4),
    'genoa': (44.2, 9.2),
    'north_sardinia': (41.0, 10.4),
    'tyrrhenian': (42.2, 11.8),
    'biscay': (45.0, -5.0),
    'azores': (38.3, -28.0),
    'newfoundland': (47.5, -52.0),
}

app = FastAPI(title='CEIBO Weather Analysis', version='1.0.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=False,
    allow_methods=['*'],
    allow_headers=['*'],
)

session = requests.Session()


class WeatherAnalyzeRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    horizon_days: int = Field(3, ge=2, le=7)
    language: str = Field('fr')


def tr(language: str, fr_text: str, es_text: str, en_text: Optional[str] = None) -> str:
    lowered = (language or '').lower()
    if lowered.startswith('es'):
        return es_text
    if lowered.startswith('en'):
        return en_text or fr_text
    return fr_text


def safe_year_shift(value: date, target_year: int) -> date:
    day = value.day
    while day >= 28:
        try:
            return value.replace(year=target_year, day=day)
        except ValueError:
            day -= 1
    return value.replace(year=target_year, day=day)


def fetch_json(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    last_error: Optional[Exception] = None
    for attempt in range(3):
        try:
            response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_S)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.35 * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise RuntimeError('weather_request_failed')


def parse_hourly_payload(payload: Dict[str, Any], aliases: Dict[str, str]) -> pd.DataFrame:
    hourly = payload.get('hourly') or {}
    times = hourly.get('time') or []
    if not times:
        return pd.DataFrame()

    frame = pd.DataFrame({'time': pd.to_datetime(times, utc=True)})
    for source, target in aliases.items():
        if source in hourly and target not in frame.columns:
            frame[target] = pd.to_numeric(hourly.get(source), errors='coerce')
    return frame


def enrich_wind_vectors(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or 'wind_speed_kn' not in frame.columns or 'wind_direction_deg' not in frame.columns:
        return frame

    valid = frame['wind_speed_kn'].notna() & frame['wind_direction_deg'].notna()
    if not valid.any():
        return frame

    u_series = pd.Series(index=frame.index, dtype=float)
    v_series = pd.Series(index=frame.index, dtype=float)
    u_q, v_q = wind_components(
        frame.loc[valid, 'wind_speed_kn'].to_numpy() * units.knots,
        frame.loc[valid, 'wind_direction_deg'].to_numpy() * units.degrees,
    )
    u_series.loc[valid] = u_q.to('knots').magnitude
    v_series.loc[valid] = v_q.to('knots').magnitude
    frame['wind_u_kn'] = u_series
    frame['wind_v_kn'] = v_series
    return frame


def fetch_forecast_bundle(lat: float, lon: float, horizon_days: int) -> pd.DataFrame:
    forecast_payload = fetch_json(
        FORECAST_API,
        {
            'latitude': lat,
            'longitude': lon,
            'forecast_days': horizon_days,
            'hourly': ','.join([
                'temperature_2m',
                'wind_speed_10m',
                'wind_direction_10m',
                'wind_gusts_10m',
                'precipitation',
                'pressure_msl',
                'surface_pressure',
                'weather_code',
            ]),
            'wind_speed_unit': 'kn',
            'timezone': 'UTC',
        },
    )
    marine_payload = fetch_json(
        MARINE_API,
        {
            'latitude': lat,
            'longitude': lon,
            'forecast_days': horizon_days,
            'hourly': ','.join([
                'wave_height',
                'wave_direction',
                'wave_period',
                'sea_surface_temperature',
                'ocean_current_velocity',
                'ocean_current_direction',
            ]),
            'timezone': 'UTC',
        },
    )

    forecast_df = parse_hourly_payload(forecast_payload, ATMOSERIC_FIELD_ALIASES)
    marine_df = parse_hourly_payload(marine_payload, MARINE_FIELD_ALIASES)
    if forecast_df.empty:
        return forecast_df

    merged = forecast_df.merge(marine_df, on='time', how='left') if not marine_df.empty else forecast_df.copy()
    if 'current_speed_ms' in merged.columns:
        merged['current_speed_kn'] = merged['current_speed_ms'] * KNOTS_PER_MPS
    merged = enrich_wind_vectors(merged)
    merged['date'] = merged['time'].dt.date
    merged['hour'] = merged['time'].dt.hour
    return merged.sort_values('time').reset_index(drop=True)


def fetch_archive_window(lat: float, lon: float, start_date: date, end_date: date) -> pd.DataFrame:
    payload = fetch_json(
        ARCHIVE_API,
        {
            'latitude': lat,
            'longitude': lon,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'hourly': ','.join([
                'temperature_2m',
                'wind_speed_10m',
                'wind_direction_10m',
                'pressure_msl',
                'surface_pressure',
                'precipitation',
            ]),
            'wind_speed_unit': 'kn',
            'timezone': 'UTC',
        },
    )
    frame = parse_hourly_payload(payload, ATMOSERIC_FIELD_ALIASES)
    if frame.empty:
        return frame
    frame['month_day'] = frame['time'].dt.strftime('%m-%d')
    frame['hour'] = frame['time'].dt.hour
    return frame


def build_climatology_frame(lat: float, lon: float, anchor_date: date, horizon_days: int) -> pd.DataFrame:
    forecast_end = anchor_date + timedelta(days=horizon_days - 1)
    window_start = anchor_date - timedelta(days=CLIMATOLOGY_WINDOW_DAYS)
    window_end = forecast_end + timedelta(days=CLIMATOLOGY_WINDOW_DAYS)
    targets: List[Tuple[date, date]] = []
    for back_years in range(1, CLIMATOLOGY_YEARS + 1):
        target_year = anchor_date.year - back_years
        targets.append((safe_year_shift(window_start, target_year), safe_year_shift(window_end, target_year)))

    frames: List[pd.DataFrame] = []
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(targets) or 1)) as executor:
        futures = [executor.submit(fetch_archive_window, lat, lon, start, end) for start, end in targets]
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception:
                continue
            if not result.empty:
                frames.append(result)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def nearest_row(frame: pd.DataFrame, target_time: pd.Timestamp) -> pd.Series:
    if frame.empty:
        raise ValueError('empty frame')
    delta = (frame['time'] - target_time).abs()
    return frame.loc[delta.idxmin()]


def value_label(value: Any, unit: str = '', digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return 'n/a'
    if digits == 0:
        return f'{float(value):.0f}{unit}'
    return f'{float(value):.{digits}f}{unit}'


def degrees_to_cardinal(deg: Any) -> str:
    if deg is None or pd.isna(deg):
        return '?'
    directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
    return directions[int((float(deg) % 360.0) / 45.0 + 0.5) % 8]


def direction_in_sector(direction_deg: Any, start_deg: float, end_deg: float) -> bool:
    if direction_deg is None or pd.isna(direction_deg):
        return False
    value = float(direction_deg) % 360.0
    start = start_deg % 360.0
    end = end_deg % 360.0
    if start <= end:
        return start <= value <= end
    return value >= start or value <= end


def classify_focus_region(lat: float, lon: float, language: str) -> str:
    if 41.0 <= lat <= 43.4 and 8.2 <= lon <= 9.7:
        return tr(language, 'la Corse', 'Córcega', 'Corsica')
    if 39.3 <= lat <= 41.1 and 0.8 <= lon <= 4.6:
        return tr(language, 'les Baléares', 'Baleares', 'the Balearics')
    if 40.0 <= lat <= 43.1 and -0.2 <= lon <= 3.8:
        return tr(language, 'le secteur catalan', 'el sector catalán', 'the Catalan sector')
    if 42.0 <= lat <= 44.7 and 2.4 <= lon <= 6.5:
        return tr(language, 'le golfe du Lion', 'el golfo de León', 'the Gulf of Lion')
    if 42.0 <= lat <= 44.9 and 7.3 <= lon <= 10.6:
        return tr(language, 'la mer de Ligurie', 'el mar de Liguria', 'the Ligurian Sea')
    if 39.0 <= lat <= 41.8 and 8.0 <= lon <= 10.0:
        return tr(language, 'le nord de la Sardaigne', 'el norte de Cerdeña', 'northern Sardinia')
    return tr(language, 'la zone analysée', 'la zona analizada', 'the analyzed area')


def mean_direction_from_frame(frame: pd.DataFrame) -> float:
    if frame.empty or 'wind_u_kn' not in frame.columns or 'wind_v_kn' not in frame.columns:
        return float('nan')
    u_value = float(frame['wind_u_kn'].mean()) if not frame['wind_u_kn'].dropna().empty else float('nan')
    v_value = float(frame['wind_v_kn'].mean()) if not frame['wind_v_kn'].dropna().empty else float('nan')
    if not math.isfinite(u_value) or not math.isfinite(v_value):
        return float('nan')
    return prevailing_direction_from_components(u_value, v_value)


def prevailing_direction_from_components(u_value: float, v_value: float) -> float:
    return (270.0 - math.degrees(math.atan2(v_value, u_value))) % 360.0


def angular_distance_deg(a_deg: Any, b_deg: Any) -> float:
    if a_deg is None or b_deg is None or pd.isna(a_deg) or pd.isna(b_deg):
        return float('nan')
    return abs((float(a_deg) - float(b_deg) + 180.0) % 360.0 - 180.0)


def sea_state_signal(wind_dir: Any, wave_dir: Any, wave_height: Any, wave_period: Any, language: str) -> str:
    height_value = float(wave_height) if wave_height is not None and not pd.isna(wave_height) else float('nan')
    period_value = float(wave_period) if wave_period is not None and not pd.isna(wave_period) else float('nan')
    angle_gap = angular_distance_deg(wind_dir, wave_dir)
    if math.isfinite(height_value) and math.isfinite(period_value) and math.isfinite(angle_gap):
        if height_value >= 1.3 and period_value >= 5.5 and angle_gap >= 55:
            return tr(language, 'mer croisée / houle résiduelle marquée', 'mar cruzada / oleaje residual marcado', 'marked cross sea / residual swell')
        if height_value >= 1.0 and angle_gap >= 35:
            return tr(language, 'mer croisée modérée', 'mar cruzada moderada', 'moderate cross sea')
        if height_value >= 0.9 and period_value >= 5.0:
            return tr(language, 'houle résiduelle présente', 'oleaje residual presente', 'residual swell present')
        if height_value >= 0.8:
            return tr(language, 'mer du vent active', 'mar de viento activa', 'active wind sea')
    return tr(language, 'état de mer limité', 'estado de mar limitado', 'limited sea state')


def build_daily_outlook(frame: pd.DataFrame, now_ts: pd.Timestamp, language: str) -> List[str]:
    future = frame[frame['time'] >= now_ts.floor('h')].copy()
    if future.empty:
        return []

    lines: List[str] = []
    for day, group in future.groupby('date', sort=True):
        avg_speed = float(group['wind_speed_kn'].mean()) if 'wind_speed_kn' in group else float('nan')
        max_gust = float(group['wind_gust_kn'].max()) if 'wind_gust_kn' in group else float('nan')
        rain_total = float(group['precip_mm'].sum()) if 'precip_mm' in group else float('nan')
        pressure_start = float(group['pressure_hpa'].iloc[0]) if 'pressure_hpa' in group and not group['pressure_hpa'].dropna().empty else float('nan')
        pressure_end = float(group['pressure_hpa'].iloc[-1]) if 'pressure_hpa' in group and not group['pressure_hpa'].dropna().empty else float('nan')
        wave_max = float(group['wave_height_m'].max()) if 'wave_height_m' in group and not group['wave_height_m'].dropna().empty else float('nan')
        mean_u = float(group['wind_u_kn'].mean()) if 'wind_u_kn' in group and not group['wind_u_kn'].dropna().empty else float('nan')
        mean_v = float(group['wind_v_kn'].mean()) if 'wind_v_kn' in group and not group['wind_v_kn'].dropna().empty else float('nan')
        dir_deg = prevailing_direction_from_components(mean_u, mean_v) if math.isfinite(mean_u) and math.isfinite(mean_v) else float('nan')
        trend = pressure_end - pressure_start if math.isfinite(pressure_start) and math.isfinite(pressure_end) else float('nan')

        if math.isfinite(trend) and trend <= -3.0:
            regime = tr(language, 'signal plus perturbé', 'señal más perturbada', 'more disturbed signal')
        elif math.isfinite(trend) and trend >= 2.5:
            regime = tr(language, 'stabilisation anticyclonique', 'estabilización anticiclónica', 'anticyclonic stabilization')
        elif math.isfinite(rain_total) and rain_total >= 4.0:
            regime = tr(language, 'humide / instable', 'húmedo / inestable', 'wet / unstable')
        else:
            regime = tr(language, 'régime proche de l\'actuel', 'régimen cercano al actual', 'regime close to current')

        lines.append(
            tr(
                language,
                f"{day.isoformat()}: vent moyen {value_label(avg_speed, ' kn')} de {degrees_to_cardinal(dir_deg)}, rafales {value_label(max_gust, ' kn')}, pluie {value_label(rain_total, ' mm')}, houle max {value_label(wave_max, ' m')}, pression {value_label(pressure_start, ' hPa', 0)} → {value_label(pressure_end, ' hPa', 0)}. Lecture: {regime}.",
                f"{day.isoformat()}: viento medio {value_label(avg_speed, ' kn')} de {degrees_to_cardinal(dir_deg)}, rachas {value_label(max_gust, ' kn')}, lluvia {value_label(rain_total, ' mm')}, oleaje max {value_label(wave_max, ' m')}, presión {value_label(pressure_start, ' hPa', 0)} → {value_label(pressure_end, ' hPa', 0)}. Lectura: {regime}.",
                f"{day.isoformat()}: mean wind {value_label(avg_speed, ' kn')} from {degrees_to_cardinal(dir_deg)}, gusts {value_label(max_gust, ' kn')}, rain {value_label(rain_total, ' mm')}, max wave {value_label(wave_max, ' m')}, pressure {value_label(pressure_start, ' hPa', 0)} → {value_label(pressure_end, ' hPa', 0)}. Reading: {regime}."
            )
        )
    return lines


def build_climate_context(frame: pd.DataFrame, climatology: pd.DataFrame, language: str) -> List[str]:
    if frame.empty or climatology.empty:
        return [tr(language, 'Historique insuffisant pour qualifier l\'anomalie saisonnière.', 'Histórico insuficiente para calificar la anomalía estacional.', 'Not enough history to qualify the seasonal anomaly.')]

    lines: List[str] = []
    for current_date, group in frame.groupby('date', sort=True):
        month_day = pd.Timestamp(current_date).strftime('%m-%d')
        sample = climatology[climatology['month_day'] == month_day]
        if sample.empty:
            continue
        midday_index = (group['hour'] - 12).abs().idxmin()
        midday = group.loc[midday_index]
        wind_delta = float(midday.get('wind_speed_kn', float('nan'))) - float(sample['wind_speed_kn'].median())
        pressure_delta = float(midday.get('pressure_hpa', float('nan'))) - float(sample['pressure_hpa'].median())
        temp_delta = float(midday.get('temperature_c', float('nan'))) - float(sample['temperature_c'].median())
        lines.append(
            tr(
                language,
                f"{current_date.isoformat()} à midi UTC: vent {wind_delta:+.1f} kn vs médiane saisonnière, pression {pressure_delta:+.1f} hPa, température {temp_delta:+.1f}°C.",
                f"{current_date.isoformat()} a mediodía UTC: viento {wind_delta:+.1f} kn frente a la mediana estacional, presión {pressure_delta:+.1f} hPa, temperatura {temp_delta:+.1f}°C.",
                f"{current_date.isoformat()} at 12 UTC: wind {wind_delta:+.1f} kn vs seasonal median, pressure {pressure_delta:+.1f} hPa, temperature {temp_delta:+.1f}°C."
            )
        )

    return lines or [tr(language, 'Aucune comparaison climatologique exploitable sur la fenêtre demandée.', 'Sin comparación climatológica explotable en la ventana solicitada.', 'No usable climatology comparison for the requested window.')]


def build_ring_points(lat: float, lon: float) -> Dict[str, Tuple[float, float]]:
    lat_step = 2.0
    lon_step = max(2.0, 2.0 / max(0.35, math.cos(math.radians(lat))))
    return {
        'north': (max(-89.0, min(89.0, lat + lat_step)), lon),
        'south': (max(-89.0, min(89.0, lat - lat_step)), lon),
        'east': (lat, ((lon + lon_step + 180.0) % 360.0) - 180.0),
        'west': (lat, ((lon - lon_step + 180.0) % 360.0) - 180.0),
        'northwest': (max(-89.0, min(89.0, lat + lat_step)), ((lon - lon_step + 180.0) % 360.0) - 180.0),
        'southeast': (max(-89.0, min(89.0, lat - lat_step)), ((lon + lon_step + 180.0) % 360.0) - 180.0),
    }


def fetch_reference_snapshots(points: Dict[str, Tuple[float, float]], horizon_days: int, target_time: pd.Timestamp) -> Dict[str, pd.Series]:
    snapshots: Dict[str, pd.Series] = {}
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(points) or 1)) as executor:
        future_map = {
            executor.submit(fetch_forecast_bundle, point_lat, point_lon, max(4, horizon_days)): name
            for name, (point_lat, point_lon) in points.items()
        }
        for future in as_completed(future_map):
            name = future_map[future]
            try:
                frame = future.result()
                if frame.empty:
                    continue
                snapshots[name] = nearest_row(frame, target_time)
            except Exception:
                continue
    return snapshots


def infer_western_mediterranean_regimes(
    lat: float,
    lon: float,
    current: pd.Series,
    forecast: pd.DataFrame,
    med_snapshots: Dict[str, pd.Series],
    language: str,
) -> List[str]:
    if not is_mediterranean_focus(lat, lon):
        return []

    lines: List[str] = []
    focus_region = classify_focus_region(lat, lon, language)
    wind_dir = float(current.get('wind_direction_deg', float('nan')))
    wind_speed = float(current.get('wind_speed_kn', float('nan')))
    pressure = float(current.get('pressure_hpa', float('nan')))

    golfe = med_snapshots.get('golfe_du_lion')
    ebro = med_snapshots.get('ebro')
    genoa = med_snapshots.get('genoa')
    balearic = med_snapshots.get('balearic')

    golfe_wind = float(golfe.get('wind_speed_kn', float('nan'))) if golfe is not None else float('nan')
    golfe_dir = float(golfe.get('wind_direction_deg', float('nan'))) if golfe is not None else float('nan')
    ebro_wind = float(ebro.get('wind_speed_kn', float('nan'))) if ebro is not None else float('nan')
    ebro_dir = float(ebro.get('wind_direction_deg', float('nan'))) if ebro is not None else float('nan')
    genoa_pressure = float(genoa.get('pressure_hpa', float('nan'))) if genoa is not None else float('nan')
    balearic_pressure = float(balearic.get('pressure_hpa', float('nan'))) if balearic is not None else float('nan')

    next_72h = forecast[forecast['time'] <= forecast['time'].min() + pd.Timedelta(hours=72)]
    afternoon = next_72h[next_72h['hour'].between(12, 18)]
    overnight = next_72h[(next_72h['hour'] <= 6) | (next_72h['hour'] >= 22)]
    afternoon_dir = mean_direction_from_frame(afternoon)
    overnight_dir = mean_direction_from_frame(overnight)
    thermal_delta = float(afternoon['wind_speed_kn'].mean() - overnight['wind_speed_kn'].mean()) if not afternoon.empty and not overnight.empty else float('nan')

    is_corsica = 'Corse' in focus_region or 'Córcega' in focus_region or 'Corsica' in focus_region
    is_catalan = 'catalan' in focus_region.lower() or 'Catalan' in focus_region
    is_balearic = 'Baléares' in focus_region or 'Baleares' in focus_region or 'Balearics' in focus_region

    if math.isfinite(golfe_wind) and math.isfinite(golfe_dir) and golfe_wind >= 18 and direction_in_sector(golfe_dir, 300, 40):
        if is_corsica:
            lines.append(
                tr(
                    language,
                    f"Signature compatible avec un épisode mistral / tramontane en sortie de golfe du Lion: {golfe_wind:.1f} kn de {degrees_to_cardinal(golfe_dir)} au golfe. Ce type de flux peut gagner la façade ouest de la Corse puis le canal de Corse en s'asséchant et en s'accélérant par endroits.",
                    f"Firma compatible con un episodio de mistral / tramontana saliendo del golfo de León: {golfe_wind:.1f} kn de {degrees_to_cardinal(golfe_dir)} en el golfo. Este tipo de flujo puede alcanzar la fachada oeste de Córcega y luego el canal de Córcega, secándose y acelerándose localmente.",
                    f"Pattern compatible with a mistral / tramontane event exiting the Gulf of Lion: {golfe_wind:.1f} kn from {degrees_to_cardinal(golfe_dir)} in the gulf. This type of flow can reach Corsica's west side and then the Corsica channel, drying out and accelerating locally."
                )
            )
        elif is_catalan or is_balearic:
            lines.append(
                tr(
                    language,
                    f"Signature compatible avec une tramontane active: {golfe_wind:.1f} kn de {degrees_to_cardinal(golfe_dir)} au golfe du Lion. Ce régime peut glisser vers le secteur catalan et les Baléares avec un vent plus sec et irrégulier près des caps et détroits.",
                    f"Firma compatible con tramontana activa: {golfe_wind:.1f} kn de {degrees_to_cardinal(golfe_dir)} en el golfo de León. Este régimen puede deslizarse hacia el sector catalán y Baleares con viento más seco e irregular cerca de cabos y estrechos.",
                    f"Pattern compatible with active tramontane: {golfe_wind:.1f} kn from {degrees_to_cardinal(golfe_dir)} in the Gulf of Lion. This regime can slide toward the Catalan sector and the Balearics with drier, more erratic wind near capes and straits."
                )
            )
        else:
            lines.append(
                tr(
                    language,
                    f"Mistral / tramontane plausible dans le bassin nord-occidental: {golfe_wind:.1f} kn de {degrees_to_cardinal(golfe_dir)} au golfe du Lion. Le rayonnement vers {focus_region} dépendra surtout de la distance au couloir principal et du relief côtier.",
                    f"Mistral / tramontana plausible en la cuenca noroccidental: {golfe_wind:.1f} kn de {degrees_to_cardinal(golfe_dir)} en el golfo de León. Su propagación hacia {focus_region} dependerá sobre todo de la distancia al corredor principal y del relieve costero.",
                    f"Mistral / tramontane is plausible in the northwestern basin: {golfe_wind:.1f} kn from {degrees_to_cardinal(golfe_dir)} in the Gulf of Lion. Propagation toward {focus_region} will mostly depend on distance from the main corridor and coastal terrain."
                )
            )

    if math.isfinite(ebro_wind) and math.isfinite(ebro_dir) and ebro_wind >= 16 and direction_in_sector(ebro_dir, 290, 40):
        lines.append(
            tr(
                language,
                f"Effet vallée de l'Ebre plausible: {ebro_wind:.1f} kn de {degrees_to_cardinal(ebro_dir)} sur le point de référence Ebre. Ce couloir peut exporter un NW plus nerveux vers le sud de la Catalogne puis la mer d'Alboran / les Baléares occidentales selon l'axe du flux.",
                f"Efecto valle del Ebro plausible: {ebro_wind:.1f} kn de {degrees_to_cardinal(ebro_dir)} en el punto de referencia Ebro. Este corredor puede exportar un NW más nervioso hacia el sur de Cataluña y luego hacia las Baleares occidentales según el eje del flujo.",
                f"Ebro valley effect is plausible: {ebro_wind:.1f} kn from {degrees_to_cardinal(ebro_dir)} at the Ebro reference point. This corridor can export a sharper NW flow toward southern Catalonia and then the western Balearics depending on the flow axis."
            )
        )

    if math.isfinite(wind_dir) and math.isfinite(wind_speed) and wind_speed >= 10 and direction_in_sector(wind_dir, 95, 165):
        lines.append(
            tr(
                language,
                f"Signature compatible avec un marin / flux humide d'est à sud-est sur {focus_region}: {wind_speed:.1f} kn de {degrees_to_cardinal(wind_dir)}. Ce type de régime apporte souvent humidité, mer qui se forme plus vite et visibilité plus chargée près de la côte.",
                f"Firma compatible con marin / flujo húmedo de este a sudeste sobre {focus_region}: {wind_speed:.1f} kn de {degrees_to_cardinal(wind_dir)}. Este régimen suele aportar humedad, mar que se forma más rápido y visibilidad más cargada cerca de costa.",
                f"Pattern compatible with marin / moist east-to-southeast flow over {focus_region}: {wind_speed:.1f} kn from {degrees_to_cardinal(wind_dir)}. This regime often brings humidity, faster sea-state build-up, and hazier visibility near the coast."
            )
        )

    if is_catalan and math.isfinite(thermal_delta) and thermal_delta >= 3.0 and math.isfinite(afternoon_dir) and direction_in_sector(afternoon_dir, 190, 260):
        lines.append(
            tr(
                language,
                f"Signature compatible avec un garbí / sud-ouest thermique sur le littoral catalan: renforcement diurne moyen de {thermal_delta:.1f} kn et direction d'après-midi {degrees_to_cardinal(afternoon_dir)}. Ce type de vent est souvent plus maniable le matin puis plus établi après midi.",
                f"Firma compatible con garbí / sudoeste térmico en el litoral catalán: refuerzo diurno medio de {thermal_delta:.1f} kn y dirección de tarde {degrees_to_cardinal(afternoon_dir)}. Este viento suele ser más manejable por la mañana y más establecido por la tarde.",
                f"Pattern compatible with garbi / thermal southwesterly on the Catalan coast: mean daytime reinforcement of {thermal_delta:.1f} kn and afternoon direction {degrees_to_cardinal(afternoon_dir)}. This wind is often lighter in the morning and more established in the afternoon."
            )
        )

    if is_corsica and math.isfinite(wind_dir) and math.isfinite(wind_speed) and wind_speed >= 12 and direction_in_sector(wind_dir, 220, 290):
        lines.append(
            tr(
                language,
                f"Sur la Corse, la composante {degrees_to_cardinal(wind_dir)} actuelle peut aussi prendre une couleur de libeccio local selon l'exposition de côte. À surveiller surtout si Gênes reste plus basse en pression ({value_label(genoa_pressure, ' hPa', 0)}) que le bassin occidental.",
                f"En Córcega, la componente actual {degrees_to_cardinal(wind_dir)} también puede tomar un carácter de libeccio local según la exposición de costa. Conviene vigilarlo sobre todo si Génova sigue más baja de presión ({value_label(genoa_pressure, ' hPa', 0)}) que la cuenca occidental.",
                f"Over Corsica, the current {degrees_to_cardinal(wind_dir)} component can also take on a local libeccio character depending on coastal exposure. Watch it especially if Genoa remains lower in pressure ({value_label(genoa_pressure, ' hPa', 0)}) than the western basin."
            )
        )

    if math.isfinite(balearic_pressure) and math.isfinite(pressure) and balearic_pressure <= pressure - 1.5 and math.isfinite(wind_dir) and direction_in_sector(wind_dir, 40, 120):
        lines.append(
            tr(
                language,
                f"Le minimum relatif vers les Baléares ({value_label(balearic_pressure, ' hPa', 0)} contre {value_label(pressure, ' hPa', 0)} au point) rend crédible une alimentation est / nord-est vers {focus_region}.",
                f"El mínimo relativo hacia Baleares ({value_label(balearic_pressure, ' hPa', 0)} frente a {value_label(pressure, ' hPa', 0)} en el punto) hace creíble una alimentación este / nordeste hacia {focus_region}.",
                f"A relative minimum toward the Balearics ({value_label(balearic_pressure, ' hPa', 0)} versus {value_label(pressure, ' hPa', 0)} at the point) makes an east / northeast feed toward {focus_region} credible."
            )
        )

    if lines:
        return lines

    return [
        tr(
            language,
            f"Aucune signature franche de mistral, tramontane, marin ou garbí n'apparaît sur {focus_region} avec les seuils actuels. Le régime semble plutôt piloté par un gradient faible à modéré et par les effets locaux.",
            f"No aparece una firma clara de mistral, tramontana, marin o garbí sobre {focus_region} con los umbrales actuales. El régimen parece más bien pilotado por un gradiente débil a moderado y por efectos locales.",
            f"No strong mistral, tramontane, marin, or garbi signature appears over {focus_region} with the current thresholds. The regime looks more driven by a weak to moderate gradient and local effects."
        )
    ]


def build_regime_matrix(
    lat: float,
    lon: float,
    current: pd.Series,
    forecast: pd.DataFrame,
    med_snapshots: Dict[str, pd.Series],
    language: str,
) -> List[Dict[str, str]]:
    if not is_mediterranean_focus(lat, lon):
        return []

    focus_region = classify_focus_region(lat, lon, language)
    wind_dir = float(current.get('wind_direction_deg', float('nan')))
    wind_speed = float(current.get('wind_speed_kn', float('nan')))
    gust = float(current.get('wind_gust_kn', float('nan')))
    current_pressure = float(current.get('pressure_hpa', float('nan')))
    golfe = med_snapshots.get('golfe_du_lion')
    ebro = med_snapshots.get('ebro')
    genoa = med_snapshots.get('genoa')
    balearic = med_snapshots.get('balearic')
    golfe_wind = float(golfe.get('wind_speed_kn', float('nan'))) if golfe is not None else float('nan')
    golfe_dir = float(golfe.get('wind_direction_deg', float('nan'))) if golfe is not None else float('nan')
    ebro_wind = float(ebro.get('wind_speed_kn', float('nan'))) if ebro is not None else float('nan')
    ebro_dir = float(ebro.get('wind_direction_deg', float('nan'))) if ebro is not None else float('nan')
    genoa_pressure = float(genoa.get('pressure_hpa', float('nan'))) if genoa is not None else float('nan')
    balearic_pressure = float(balearic.get('pressure_hpa', float('nan'))) if balearic is not None else float('nan')
    next_72h = forecast[forecast['time'] <= forecast['time'].min() + pd.Timedelta(hours=72)]
    next_24h = forecast[forecast['time'] <= forecast['time'].min() + pd.Timedelta(hours=24)]
    afternoon = next_72h[next_72h['hour'].between(12, 18)]
    overnight = next_72h[(next_72h['hour'] <= 6) | (next_72h['hour'] >= 22)]
    thermal_delta = float(afternoon['wind_speed_kn'].mean() - overnight['wind_speed_kn'].mean()) if not afternoon.empty and not overnight.empty else float('nan')
    afternoon_dir = mean_direction_from_frame(afternoon)
    pressure_trend_24h = float(next_24h['pressure_hpa'].iloc[-1] - next_24h['pressure_hpa'].iloc[0]) if not next_24h.empty and 'pressure_hpa' in next_24h else float('nan')
    wave_max_72h = float(next_72h['wave_height_m'].max()) if 'wave_height_m' in next_72h and not next_72h['wave_height_m'].dropna().empty else float('nan')
    is_corsica = classify_focus_region(lat, lon, 'fr') == 'la Corse'
    is_catalan = classify_focus_region(lat, lon, 'fr') == 'le secteur catalan'

    matrix: List[Dict[str, str]] = []

    def add_entry(label: str, status: str, summary: str, confidence: str, indicators: List[str]) -> None:
        matrix.append({
            'label': label,
            'status': status,
            'summary': summary,
            'confidence': confidence,
            'indicators': indicators,
        })

    if math.isfinite(golfe_wind) and math.isfinite(golfe_dir) and golfe_wind >= 18 and direction_in_sector(golfe_dir, 300, 40):
        add_entry(
            tr(language, 'Mistral / Tramontane', 'Mistral / Tramontana', 'Mistral / Tramontane'),
            'active',
            tr(language, f"Couloir actif au golfe du Lion ({golfe_wind:.1f} kn) avec propagation possible vers {focus_region}.", f"Corredor activo en el golfo de León ({golfe_wind:.1f} kn) con propagación posible hacia {focus_region}.", f"Active Gulf of Lion corridor ({golfe_wind:.1f} kn) with possible propagation toward {focus_region}."),
            tr(language, 'bonne', 'buena', 'good'),
            [
                f"Golfe du Lion: {value_label(golfe_wind, ' kn')} {degrees_to_cardinal(golfe_dir)}",
                f"Pression 24h: {pressure_trend_24h:+.1f} hPa" if math.isfinite(pressure_trend_24h) else 'Pression 24h: n/a',
                f"Houle 72h max: {value_label(wave_max_72h, ' m')}",
            ]
        )
    elif math.isfinite(golfe_wind) and golfe_wind >= 12:
        add_entry(
            tr(language, 'Mistral / Tramontane', 'Mistral / Tramontana', 'Mistral / Tramontane'),
            'watch',
            tr(language, f"Signal partiel au golfe du Lion ({golfe_wind:.1f} kn), à surveiller si le gradient se resserre.", f"Señal parcial en el golfo de León ({golfe_wind:.1f} kn), a vigilar si el gradiente se aprieta.", f"Partial Gulf of Lion signal ({golfe_wind:.1f} kn), worth watching if the gradient tightens."),
            tr(language, 'modérée', 'moderada', 'moderate'),
            [
                f"Golfe du Lion: {value_label(golfe_wind, ' kn')}",
                f"Point analysé: {value_label(wind_speed, ' kn')} {degrees_to_cardinal(wind_dir)}",
            ]
        )
    else:
        add_entry(
            tr(language, 'Mistral / Tramontane', 'Mistral / Tramontana', 'Mistral / Tramontane'),
            'quiet',
            tr(language, 'Pas de couloir nord-ouest marqué au golfe du Lion.', 'Sin corredor noroeste marcado en el golfo de León.', 'No marked northwesterly corridor in the Gulf of Lion.'),
            tr(language, 'faible', 'baja', 'low'),
            [f"Golfe du Lion: {value_label(golfe_wind, ' kn')}"]
        )

    if math.isfinite(ebro_wind) and math.isfinite(ebro_dir) and ebro_wind >= 16 and direction_in_sector(ebro_dir, 290, 40):
        add_entry(
            tr(language, 'Couloir de l\'Ebre', 'Corredor del Ebro', 'Ebro corridor'),
            'active',
            tr(language, f"Vent canalisé plausible sur l'Ebre ({ebro_wind:.1f} kn), export possible vers le large catalan.", f"Viento canalizado plausible en el Ebro ({ebro_wind:.1f} kn), exportación posible hacia el mar catalán.", f"Channeled Ebro flow looks plausible ({ebro_wind:.1f} kn), with possible export toward offshore Catalonia."),
            tr(language, 'bonne', 'buena', 'good'),
            [
                f"Ebre: {value_label(ebro_wind, ' kn')} {degrees_to_cardinal(ebro_dir)}",
                f"Thermique jour/nuit: {thermal_delta:+.1f} kn" if math.isfinite(thermal_delta) else 'Thermique jour/nuit: n/a',
            ]
        )
    elif math.isfinite(ebro_wind) and ebro_wind >= 10:
        add_entry(tr(language, 'Couloir de l\'Ebre', 'Corredor del Ebro', 'Ebro corridor'), 'watch', tr(language, 'Le couloir de l\'Ebre existe mais ne domine pas encore le bassin.', 'El corredor del Ebro existe pero aún no domina la cuenca.', 'The Ebro corridor exists but does not yet dominate the basin.'), tr(language, 'modérée', 'moderada', 'moderate'), [f"Ebre: {value_label(ebro_wind, ' kn')} {degrees_to_cardinal(ebro_dir)}"])
    else:
        add_entry(tr(language, 'Couloir de l\'Ebre', 'Corredor del Ebro', 'Ebro corridor'), 'quiet', tr(language, 'Pas de drainage Ebre significatif.', 'Sin drenaje Ebro significativo.', 'No significant Ebro drainage.'), tr(language, 'faible', 'baja', 'low'), [f"Ebre: {value_label(ebro_wind, ' kn')}"])

    if math.isfinite(wind_dir) and math.isfinite(wind_speed) and wind_speed >= 10 and direction_in_sector(wind_dir, 95, 165):
        add_entry(tr(language, 'Marin / Est-Sud-Est', 'Marin / Este-Sudeste', 'Marin / East-Southeast'), 'active', tr(language, f"Flux humide en place sur {focus_region} ({wind_speed:.1f} kn de {degrees_to_cardinal(wind_dir)}).", f"Flujo húmedo establecido sobre {focus_region} ({wind_speed:.1f} kn de {degrees_to_cardinal(wind_dir)}).", f"Moist flow is established over {focus_region} ({wind_speed:.1f} kn from {degrees_to_cardinal(wind_dir)})."), tr(language, 'bonne', 'buena', 'good'), [f"Vent: {value_label(wind_speed, ' kn')} {degrees_to_cardinal(wind_dir)}", f"Baléares: {value_label(balearic_pressure, ' hPa', 0)}", f"Rafales: {value_label(gust, ' kn')} "])
    elif math.isfinite(wind_dir) and direction_in_sector(wind_dir, 80, 170):
        add_entry(tr(language, 'Marin / Est-Sud-Est', 'Marin / Este-Sudeste', 'Marin / East-Southeast'), 'watch', tr(language, 'Composante humide présente mais encore modérée.', 'Componente húmeda presente pero aún moderada.', 'Moist component is present but still moderate.'), tr(language, 'modérée', 'moderada', 'moderate'), [f"Vent: {value_label(wind_speed, ' kn')} {degrees_to_cardinal(wind_dir)}"])
    else:
        add_entry(tr(language, 'Marin / Est-Sud-Est', 'Marin / Este-Sudeste', 'Marin / East-Southeast'), 'quiet', tr(language, 'Pas de marin significatif au point analysé.', 'Sin marin significativo en el punto analizado.', 'No significant marin regime at the analyzed point.'), tr(language, 'faible', 'baja', 'low'), [f"Vent: {value_label(wind_speed, ' kn')} {degrees_to_cardinal(wind_dir)}"])

    if is_catalan and math.isfinite(thermal_delta) and thermal_delta >= 3.0 and math.isfinite(afternoon_dir) and direction_in_sector(afternoon_dir, 190, 260):
        add_entry(tr(language, 'Garbí thermique', 'Garbí térmico', 'Thermal garbi'), 'active', tr(language, f"Renfort thermique diurne de {thermal_delta:.1f} kn avec rotation SW l'après-midi.", f"Refuerzo térmico diurno de {thermal_delta:.1f} kn con giro SW por la tarde.", f"Daytime thermal reinforcement of {thermal_delta:.1f} kn with SW rotation in the afternoon."), tr(language, 'bonne', 'buena', 'good'), [f"Delta thermique: {thermal_delta:+.1f} kn", f"Après-midi: {degrees_to_cardinal(afternoon_dir)}"])
    elif is_catalan and math.isfinite(thermal_delta) and thermal_delta >= 1.8:
        add_entry(tr(language, 'Garbí thermique', 'Garbí térmico', 'Thermal garbi'), 'watch', tr(language, 'Cycle thermique présent mais sans signature complète de garbí.', 'Ciclo térmico presente pero sin firma completa de garbí.', 'Thermal cycle is present but without a full garbi signature.'), tr(language, 'modérée', 'moderada', 'moderate'), [f"Delta thermique: {thermal_delta:+.1f} kn"])
    else:
        add_entry(tr(language, 'Garbí thermique', 'Garbí térmico', 'Thermal garbi'), 'quiet', tr(language, 'Pas de garbí net sur cette fenêtre.', 'Sin garbí claro en esta ventana.', 'No clear garbi in this window.'), tr(language, 'faible', 'baja', 'low'), [f"Delta thermique: {thermal_delta:+.1f} kn" if math.isfinite(thermal_delta) else 'Delta thermique: n/a'])

    if is_corsica and math.isfinite(wind_dir) and math.isfinite(wind_speed) and wind_speed >= 12 and direction_in_sector(wind_dir, 220, 290):
        add_entry(tr(language, 'Libeccio corse', 'Libeccio corso', 'Corsican libeccio'), 'active', tr(language, f"Composante WSW à W marquée sur la Corse ({wind_speed:.1f} kn).", f"Componente WSW a W marcada sobre Córcega ({wind_speed:.1f} kn).", f"Marked WSW to W component over Corsica ({wind_speed:.1f} kn)."), tr(language, 'bonne', 'buena', 'good'), [f"Vent: {value_label(wind_speed, ' kn')} {degrees_to_cardinal(wind_dir)}", f"Gênes: {value_label(genoa_pressure, ' hPa', 0)}", f"Houle 72h max: {value_label(wave_max_72h, ' m')}"])
    elif is_corsica and math.isfinite(wind_dir) and direction_in_sector(wind_dir, 210, 300):
        add_entry(tr(language, 'Libeccio corse', 'Libeccio corso', 'Corsican libeccio'), 'watch', tr(language, 'Composante ouest présente en Corse, à confirmer selon le gradient.', 'Componente oeste presente en Córcega, a confirmar según el gradiente.', 'A westerly Corsican component is present and should be checked against the gradient.'), tr(language, 'modérée', 'moderada', 'moderate'), [f"Vent: {value_label(wind_speed, ' kn')} {degrees_to_cardinal(wind_dir)}", f"Gênes: {value_label(genoa_pressure, ' hPa', 0)}", f"Point: {value_label(current_pressure, ' hPa', 0)}"])
    elif is_corsica:
        add_entry(tr(language, 'Libeccio corse', 'Libeccio corso', 'Corsican libeccio'), 'quiet', tr(language, 'Pas de signature libeccio dominante sur la Corse.', 'Sin firma dominante de libeccio en Córcega.', 'No dominant libeccio signature over Corsica.'), tr(language, 'faible', 'baja', 'low'), [f"Vent: {value_label(wind_speed, ' kn')} {degrees_to_cardinal(wind_dir)}"])

    return matrix


def build_corsica_subregion_outlook(lat: float, lon: float, current: pd.Series, med_snapshots: Dict[str, pd.Series], language: str) -> List[Dict[str, Any]]:
    focus_region = classify_focus_region(lat, lon, language)
    if 'Corse' not in focus_region and 'Córcega' not in focus_region and 'Corsica' not in focus_region:
        return []

    wind_dir = float(current.get('wind_direction_deg', float('nan')))
    wind_speed = float(current.get('wind_speed_kn', float('nan')))
    gust = float(current.get('wind_gust_kn', float('nan')))
    wave_dir = float(current.get('wave_direction_deg', float('nan')))
    wave_height = float(current.get('wave_height_m', float('nan')))
    wave_period = float(current.get('wave_period_s', float('nan')))
    golfe = med_snapshots.get('golfe_du_lion')
    genoa = med_snapshots.get('genoa')
    golfe_wind = float(golfe.get('wind_speed_kn', float('nan'))) if golfe is not None else float('nan')
    golfe_dir = float(golfe.get('wind_direction_deg', float('nan'))) if golfe is not None else float('nan')
    genoa_pressure = float(genoa.get('pressure_hpa', float('nan'))) if genoa is not None else float('nan')
    sea_signal = sea_state_signal(wind_dir, wave_dir, wave_height, wave_period, language)
    sea_indicator = tr(language, 'Mer', 'Mar', 'Sea') + f": {sea_signal}"
    wave_indicator = f"Houle: {value_label(wave_height, ' m')} {degrees_to_cardinal(wave_dir)} / {value_label(wave_period, ' s')}"

    def zone_confidence(status: str) -> str:
        if status == 'active':
            return tr(language, 'bonne', 'buena', 'good')
        if status == 'watch':
            return tr(language, 'modérée', 'moderada', 'moderate')
        return tr(language, 'faible', 'baja', 'low')

    def build_zone(zone_label: str, status: str, summary: str, indicators: List[str]) -> Dict[str, Any]:
        return {
            'label': zone_label,
            'status': status,
            'summary': summary,
            'confidence': zone_confidence(status),
            'indicators': indicators,
        }

    ajaccio_status = 'quiet'
    ajaccio_text = tr(language, 'Golfe d\'Ajaccio et façade sud-ouest sans signal dominant pour le moment.', 'Golfo de Ajaccio y fachada sudoeste sin señal dominante por ahora.', 'Ajaccio gulf and southwest coast show no dominant signal for now.')
    if math.isfinite(wind_dir) and direction_in_sector(wind_dir, 220, 320) and wind_speed >= 12:
        ajaccio_status = 'active'
        ajaccio_text = tr(language, f"Golfe d'Ajaccio et façade sud-ouest exposés sous {degrees_to_cardinal(wind_dir)} {wind_speed:.1f} kn: mer en hausse rapide et rafales sur les pointes.", f"Golfo de Ajaccio y fachada sudoeste expuestos con {degrees_to_cardinal(wind_dir)} {wind_speed:.1f} kn: mar subiendo rápido y rachas en los cabos.", f"Ajaccio gulf and southwest coast are exposed under {degrees_to_cardinal(wind_dir)} {wind_speed:.1f} kn: sea state builds quickly and headlands can accelerate gusts.")
    elif math.isfinite(wind_dir) and direction_in_sector(wind_dir, 70, 150) and wind_speed >= 10:
        ajaccio_text = tr(language, 'Golfe d\'Ajaccio plutôt sous le vent avec composante est à sud-est.', 'Golfo de Ajaccio más bien a sotavento con componente este a sudeste.', 'Ajaccio gulf is relatively sheltered under an east to southeast component.')

    calvi_status = 'quiet'
    calvi_text = tr(language, 'Calvi / Balagne sans accélération nette détectée.', 'Calvi / Balagne sin aceleración clara detectada.', 'Calvi / Balagne show no clear acceleration signal.')
    if math.isfinite(golfe_wind) and math.isfinite(golfe_dir) and golfe_wind >= 18 and direction_in_sector(golfe_dir, 300, 40):
        calvi_status = 'active'
        calvi_text = tr(language, f"Calvi / Balagne au premier plan du débordement du golfe du Lion ({golfe_wind:.1f} kn): mer courte et accélérations probables près des caps.", f"Calvi / Balagne en primera línea del desbordamiento del golfo de León ({golfe_wind:.1f} kn): mar corta y aceleraciones probables cerca de los cabos.", f"Calvi / Balagne are first in line for Gulf of Lion spillover ({golfe_wind:.1f} kn): short seas and cape accelerations are likely.")
    elif math.isfinite(wind_dir) and direction_in_sector(wind_dir, 250, 320) and wind_speed >= 11:
        calvi_status = 'watch'
        calvi_text = tr(language, 'Calvi / Balagne voient une composante ouest à nord-ouest qui peut encore se renforcer localement.', 'Calvi / Balagne ven una componente oeste a noroeste que aún puede reforzarse localmente.', 'Calvi / Balagne show a west to northwest component that can still strengthen locally.')

    cap_status = 'quiet'
    cap_text = tr(language, 'Cap Corse sans accélération marquée détectée.', 'Cap Corse sin aceleración marcada detectada.', 'Cap Corse shows no marked acceleration signal.')
    if math.isfinite(golfe_wind) and math.isfinite(golfe_dir) and golfe_wind >= 18 and direction_in_sector(golfe_dir, 300, 40):
        cap_status = 'active'
        cap_text = tr(language, f"Cap Corse: accélérations probables si le couloir golfe du Lion reste actif ({golfe_wind:.1f} kn).", f"Cap Corse: aceleraciones probables si el corredor del golfo de León sigue activo ({golfe_wind:.1f} kn).", f"Cap Corse: local accelerations are likely if the Gulf of Lion corridor stays active ({golfe_wind:.1f} kn).")
    elif math.isfinite(wind_dir) and direction_in_sector(wind_dir, 20, 90) and wind_speed >= 12:
        cap_status = 'watch'
        cap_text = tr(language, 'Cap Corse exposé côté est / nord-est avec mer croisée possible.', 'Cap Corse expuesto por el lado este / nordeste con posible mar cruzada.', 'Cap Corse is exposed on its east / northeast side with possible crossed seas.')

    bastia_status = 'quiet'
    bastia_text = tr(language, 'Bastia et façade nord-est sans exposition dominante détectée.', 'Bastia y fachada nordeste sin exposición dominante detectada.', 'Bastia and the northeast coast show no dominant exposure right now.')
    if math.isfinite(wind_dir) and direction_in_sector(wind_dir, 40, 160) and wind_speed >= 10:
        bastia_status = 'active'
        bastia_text = tr(language, f"Bastia et façade nord-est exposées sous {degrees_to_cardinal(wind_dir)} {wind_speed:.1f} kn, avec humidité et mer courte plus probables.", f"Bastia y fachada nordeste expuestas con {degrees_to_cardinal(wind_dir)} {wind_speed:.1f} kn, con mayor probabilidad de humedad y mar corta.", f"Bastia and the northeast coast are exposed under {degrees_to_cardinal(wind_dir)} {wind_speed:.1f} kn, with higher odds of humidity and short seas.")
    elif math.isfinite(wind_dir) and direction_in_sector(wind_dir, 290, 360) and wind_speed >= 12:
        bastia_text = tr(language, 'Bastia et façade nord-est plutôt sous le vent en flux de NW à N.', 'Bastia y fachada nordeste más bien a sotavento con flujo de NW a N.', 'Bastia and the northeast coast are more sheltered in a NW to N flow.')

    east_south_status = 'quiet'
    east_south_text = tr(language, 'Plaine orientale sud / Porto-Vecchio sans contrainte dominante détectée.', 'Llanura oriental sur / Porto-Vecchio sin forzamiento dominante detectado.', 'Southern east coast / Porto-Vecchio show no dominant forcing right now.')
    if math.isfinite(wind_dir) and direction_in_sector(wind_dir, 70, 150) and wind_speed >= 10:
        east_south_status = 'active'
        east_south_text = tr(language, f"Plaine orientale sud / Porto-Vecchio directement exposés au flux {degrees_to_cardinal(wind_dir)}: humidité, mer courte et tenue du vent plus durables.", f"Llanura oriental sur / Porto-Vecchio expuestos directamente al flujo {degrees_to_cardinal(wind_dir)}: humedad, mar corta y persistencia del viento más duraderas.", f"Southern east coast / Porto-Vecchio are directly exposed to the {degrees_to_cardinal(wind_dir)} flow: humidity, short seas, and wind persistence should last longer.")
    elif math.isfinite(wind_dir) and direction_in_sector(wind_dir, 220, 300) and wind_speed >= 11:
        east_south_status = 'watch'
        east_south_text = tr(language, 'Plaine orientale sud / Porto-Vecchio restent plus abrités mais des retours de mer restent possibles autour des caps.', 'Llanura oriental sur / Porto-Vecchio quedan más resguardados pero siguen siendo posibles retornos de mar cerca de los cabos.', 'Southern east coast / Porto-Vecchio stay more sheltered but sea wrap-around remains possible near the headlands.')

    bonifacio_status = 'watch'
    bonifacio_text = tr(language, 'Bouches de Bonifacio: surveiller les accélérations locales, même en régime moyen.', 'Bocas de Bonifacio: vigilar aceleraciones locales, incluso en régimen medio.', 'Bonifacio Strait: watch local accelerations even in a moderate regime.')
    if math.isfinite(wind_dir) and math.isfinite(wind_speed) and wind_speed >= 12 and (direction_in_sector(wind_dir, 40, 90) or direction_in_sector(wind_dir, 240, 290)):
        bonifacio_status = 'active'
        bonifacio_text = tr(language, f"Bouches de Bonifacio: effet venturi plausible sous {degrees_to_cardinal(wind_dir)} {wind_speed:.1f} kn, avec accélérations au détroit.", f"Bocas de Bonifacio: efecto venturi plausible con {degrees_to_cardinal(wind_dir)} {wind_speed:.1f} kn, con aceleraciones en el estrecho.", f"Bonifacio Strait: venturi effect is plausible under {degrees_to_cardinal(wind_dir)} {wind_speed:.1f} kn, with accelerations in the strait.")
    elif math.isfinite(gust) and math.isfinite(wind_speed) and gust >= wind_speed + 8:
        bonifacio_text = tr(language, 'Bouches de Bonifacio: le différentiel rafale / vent moyen suggère déjà des accélérations locales dans l\'axe du détroit.', 'Bocas de Bonifacio: la diferencia entre racha y viento medio ya sugiere aceleraciones locales en el eje del estrecho.', 'Bonifacio Strait: the gust-to-mean wind gap already suggests local accelerations along the strait axis.')

    return [
        build_zone(tr(language, 'Ajaccio / façade sud-ouest', 'Ajaccio / fachada sudoeste', 'Ajaccio / southwest coast'), ajaccio_status, ajaccio_text, [f"Vent: {value_label(wind_speed, ' kn')} {degrees_to_cardinal(wind_dir)}", f"Rafales: {value_label(gust, ' kn')}", sea_indicator, wave_indicator]),
        build_zone(tr(language, 'Calvi / Balagne', 'Calvi / Balagne', 'Calvi / Balagne'), calvi_status, calvi_text, [f"Golfe du Lion: {value_label(golfe_wind, ' kn')} {degrees_to_cardinal(golfe_dir)}", sea_indicator, wave_indicator]),
        build_zone(tr(language, 'Cap Corse', 'Cap Corse', 'Cap Corse'), cap_status, cap_text, [f"Golfe du Lion: {value_label(golfe_wind, ' kn')}", f"Vent local: {value_label(wind_speed, ' kn')} {degrees_to_cardinal(wind_dir)}", sea_indicator, wave_indicator]),
        build_zone(tr(language, 'Bastia / façade nord-est', 'Bastia / fachada nordeste', 'Bastia / northeast coast'), bastia_status, bastia_text, [f"Vent: {value_label(wind_speed, ' kn')} {degrees_to_cardinal(wind_dir)}", f"Gênes: {value_label(genoa_pressure, ' hPa', 0)}", sea_indicator, wave_indicator]),
        build_zone(tr(language, 'Plaine orientale sud / Porto-Vecchio', 'Llanura oriental sur / Porto-Vecchio', 'South east coast / Porto-Vecchio'), east_south_status, east_south_text, [f"Vent: {value_label(wind_speed, ' kn')} {degrees_to_cardinal(wind_dir)}", f"Rafales: {value_label(gust, ' kn')}", sea_indicator, wave_indicator]),
        build_zone(tr(language, 'Bouches de Bonifacio', 'Bocas de Bonifacio', 'Bonifacio Strait'), bonifacio_status, bonifacio_text, [f"Vent: {value_label(wind_speed, ' kn')} {degrees_to_cardinal(wind_dir)}", f"Rafales: {value_label(gust, ' kn')}", sea_indicator, wave_indicator]),
    ]


def infer_mechanisms(
    current: pd.Series,
    forecast: pd.DataFrame,
    ring_snapshots: Dict[str, pd.Series],
    med_snapshots: Dict[str, pd.Series],
    language: str,
) -> Tuple[str, str, List[str], str]:
    mechanisms: List[str] = []
    confidence = tr(language, 'modérée', 'moderada', 'moderate')
    wind_dir = float(current.get('wind_direction_deg', float('nan')))
    wind_speed = float(current.get('wind_speed_kn', float('nan')))
    gust = float(current.get('wind_gust_kn', float('nan')))
    pressure = float(current.get('pressure_hpa', float('nan')))
    wave = float(current.get('wave_height_m', float('nan')))

    north_pressures = [float(series.get('pressure_hpa', float('nan'))) for key, series in ring_snapshots.items() if key in {'north', 'northwest'}]
    south_pressures = [float(series.get('pressure_hpa', float('nan'))) for key, series in ring_snapshots.items() if key in {'south', 'southeast'}]
    valid_north = [value for value in north_pressures if math.isfinite(value)]
    valid_south = [value for value in south_pressures if math.isfinite(value)]
    north_mean = sum(valid_north) / len(valid_north) if valid_north else float('nan')
    south_mean = sum(valid_south) / len(valid_south) if valid_south else float('nan')
    north_south_gradient = north_mean - south_mean if math.isfinite(north_mean) and math.isfinite(south_mean) else float('nan')

    next_24h = forecast[forecast['time'] <= forecast['time'].min() + pd.Timedelta(hours=24)]
    next_72h = forecast[forecast['time'] <= forecast['time'].min() + pd.Timedelta(hours=72)]
    pressure_24h = float(next_24h['pressure_hpa'].iloc[-1] - next_24h['pressure_hpa'].iloc[0]) if not next_24h.empty and 'pressure_hpa' in next_24h else float('nan')
    afternoon = next_72h[next_72h['hour'].between(12, 17)]
    overnight = next_72h[(next_72h['hour'] <= 6) | (next_72h['hour'] >= 22)]
    thermal_delta = float(afternoon['wind_speed_kn'].mean() - overnight['wind_speed_kn'].mean()) if not afternoon.empty and not overnight.empty else float('nan')

    if math.isfinite(north_south_gradient) and north_south_gradient >= 0.8:
        mechanisms.append(
            tr(
                language,
                f"Gradient régional nord → sud d'environ {north_south_gradient:+.1f} hPa autour du point. Cela favorise une composante de nord à nord-est si le relief côtier ne la perturbe pas trop.",
                f"Gradiente regional norte → sur de unos {north_south_gradient:+.1f} hPa alrededor del punto. Favorece una componente de norte a nordeste si el relieve costero no la perturba demasiado.",
                f"North → south regional gradient of about {north_south_gradient:+.1f} hPa around the point. That favors a northerly to northeasterly component if coastal terrain does not distort it too much."
            )
        )
    elif math.isfinite(north_south_gradient) and north_south_gradient <= -0.8:
        mechanisms.append(
            tr(
                language,
                f"Gradient régional sud → nord d'environ {abs(north_south_gradient):.1f} hPa autour du point. Cela rend plus probable une composante méridionale ou sud-ouest que du vrai NE synoptique.",
                f"Gradiente regional sur → norte de unos {abs(north_south_gradient):.1f} hPa alrededor del punto. Hace más probable una componente meridional o sudoeste que un verdadero NE sinóptico.",
                f"South → north regional gradient of about {abs(north_south_gradient):.1f} hPa around the point. That makes a southerly or southwesterly component more likely than a truly synoptic NE flow."
            )
        )
    elif math.isfinite(north_south_gradient):
        mechanisms.append(
            tr(
                language,
                f"Le gradient nord-sud reste faible ({north_south_gradient:+.1f} hPa). À cette échelle, les contrôles locaux et thermiques peuvent dominer le vent ressenti.",
                f"El gradiente norte-sur sigue débil ({north_south_gradient:+.1f} hPa). A esta escala, los controles locales y térmicos pueden dominar el viento percibido.",
                f"The north-south gradient stays weak ({north_south_gradient:+.1f} hPa). At this scale, local and thermal controls can dominate the felt wind."
            )
        )

    if math.isfinite(wind_dir) and 20 <= wind_dir <= 90 and math.isfinite(wind_speed) and wind_speed <= 16 and math.isfinite(north_south_gradient) and north_south_gradient >= 1.5:
        mechanisms.append(
            tr(
                language,
                "Le flux observé ressemble à une advection de NE/E sous dorsale relative au nord et pressions un peu plus basses vers le bassin méditerranéen occidental. Ce n'est pas seulement un vent local aléatoire.",
                "El flujo observado se parece a una advección de NE/E bajo dorsal relativa al norte y presiones algo más bajas hacia el Mediterráneo occidental. No es solo un viento local aleatorio.",
                "The observed flow looks like a NE/E advection under a ridge to the north and slightly lower pressure toward the western Mediterranean basin. It is not just a random local wind."
            )
        )

    golfe = med_snapshots.get('golfe_du_lion')
    if golfe is not None:
        golfe_wind = float(golfe.get('wind_speed_kn', float('nan')))
        golfe_pressure = float(golfe.get('pressure_hpa', float('nan')))
        if math.isfinite(golfe_wind) and math.isfinite(wind_speed) and golfe_wind >= wind_speed + 5:
            mechanisms.append(
                tr(
                    language,
                    f"Le golfe du Lion ventile plus fort ({golfe_wind:.1f} kn) que le point analysé ({wind_speed:.1f} kn). Cela suggère un réservoir de flux continental / tramontane qui alimente d'abord le bassin régional avant de se détendre vers le point étudié.",
                    f"El golfo de León ventila más fuerte ({golfe_wind:.1f} kn) que el punto analizado ({wind_speed:.1f} kn). Esto sugiere una reserva de flujo continental / tramontana que primero alimenta la cuenca regional antes de relajarse hacia el punto estudiado.",
                    f"The Gulf of Lion is blowing harder ({golfe_wind:.1f} kn) than the analyzed point ({wind_speed:.1f} kn). That suggests a continental / tramontane reservoir first feeding the regional basin before relaxing toward the analyzed point."
                )
            )
        if math.isfinite(golfe_pressure) and math.isfinite(pressure) and golfe_pressure >= pressure + 1.0:
            mechanisms.append(
                tr(
                    language,
                    f"La pression est plus forte dans le golfe du Lion ({golfe_pressure:.0f} hPa) qu'au point étudié ({pressure:.0f} hPa), compatible avec un drainage vers le sud-ouest du bassin.",
                    f"La presión es más alta en el golfo de León ({golfe_pressure:.0f} hPa) que en el punto estudiado ({pressure:.0f} hPa), compatible con un drenaje hacia el sudoeste de la cuenca.",
                    f"Pressure is higher in the Gulf of Lion ({golfe_pressure:.0f} hPa) than at the analyzed point ({pressure:.0f} hPa), consistent with drainage toward the southwest part of the basin."
                )
            )

    if math.isfinite(pressure_24h):
        if pressure_24h <= -3.0:
            mechanisms.append(tr(language, "La pression baisse nettement sur 24 h: signal d'approche d'un talweg ou d'une perturbation, avec augmentation probable de l'instabilité et des rafales.", "La presión cae claramente en 24 h: señal de aproximación de vaguada o perturbación, con aumento probable de inestabilidad y rachas.", "Pressure drops sharply over 24 h: sign of an approaching trough or disturbance, with likely increases in instability and gusts."))
            confidence = tr(language, 'assez bonne', 'bastante buena', 'fairly good')
        elif pressure_24h >= 2.5:
            mechanisms.append(tr(language, "La pression remonte sur 24 h: la masse d'air tend à se stabiliser, avec un risque frontal immédiat plus faible.", "La presión sube en 24 h: la masa de aire tiende a estabilizarse, con menor riesgo frontal inmediato.", "Pressure rises over 24 h: the air mass tends to stabilize, with a lower immediate frontal risk."))

    if math.isfinite(thermal_delta) and thermal_delta >= 3.0:
        mechanisms.append(tr(language, f"Le vent se renforce en moyenne de {thermal_delta:.1f} kn l'après-midi par rapport à la nuit: signature compatible avec un renfort thermique côtier ou une brise canalisée.", f"El viento se refuerza de media {thermal_delta:.1f} kn por la tarde frente a la noche: firma compatible con refuerzo térmico costero o brisa canalizada.", f"The wind strengthens by about {thermal_delta:.1f} kn in the afternoon versus overnight: signature compatible with coastal thermal reinforcement or a channeled breeze."))

    if math.isfinite(gust) and math.isfinite(wind_speed) and wind_speed > 0 and (gust / wind_speed) >= 1.45:
        mechanisms.append(tr(language, "Le rapport rafale / vent moyen est élevé: même si le flux moyen reste modéré, la turbulence et les accélérations locales doivent être surveillées.", "La relación racha / viento medio es alta: aunque el flujo medio siga moderado, conviene vigilar turbulencia y aceleraciones locales.", "The gust / mean wind ratio is high: even if the mean flow stays moderate, turbulence and local accelerations deserve attention."))

    if not mechanisms:
        mechanisms.append(tr(language, "Le signal ressemble surtout à un gradient faible à modéré avec contrôle local dominant. L'évolution dépendra surtout des petites variations de pression et du cycle diurne.", "La señal se parece sobre todo a un gradiente débil a moderado con control local dominante. La evolución dependerá sobre todo de pequeñas variaciones de presión y del ciclo diurno.", "The signal mostly looks like a weak to moderate gradient with dominant local control. Evolution will depend mainly on small pressure changes and the diurnal cycle."))

    headline = tr(language, 'Analyse synoptique locale', 'Análisis sinóptico local', 'Local synoptic analysis')
    if math.isfinite(wind_dir) and 20 <= wind_dir <= 90:
        headline = tr(language, f"Flux de {degrees_to_cardinal(wind_dir)} plausible par gradient régional", f"Flujo de {degrees_to_cardinal(wind_dir)} plausible por gradiente regional", f"{degrees_to_cardinal(wind_dir)} flow consistent with the regional gradient")
    elif math.isfinite(pressure_24h) and pressure_24h <= -3.0:
        headline = tr(language, 'Signal de dégradation progressive', 'Señal de degradación progresiva', 'Signal of gradual deterioration')
    elif math.isfinite(pressure_24h) and pressure_24h >= 2.5:
        headline = tr(language, 'Régime plutôt stable / anticyclonique', 'Régimen bastante estable / anticiclónico', 'Rather stable / anticyclonic regime')

    summary = tr(
        language,
        f"Vent actuel {value_label(wind_speed, ' kn')} de {degrees_to_cardinal(wind_dir)}, pression {value_label(pressure, ' hPa', 0)}, houle {value_label(wave, ' m')}. L'analyse combine prévision horaire, historique saisonnier et lecture régionale autour du point.",
        f"Viento actual {value_label(wind_speed, ' kn')} de {degrees_to_cardinal(wind_dir)}, presión {value_label(pressure, ' hPa', 0)}, oleaje {value_label(wave, ' m')}. El análisis combina previsión horaria, histórico estacional y lectura regional alrededor del punto.",
        f"Current wind {value_label(wind_speed, ' kn')} from {degrees_to_cardinal(wind_dir)}, pressure {value_label(pressure, ' hPa', 0)}, wave {value_label(wave, ' m')}. The analysis combines hourly forecast, seasonal history, and a regional reading around the point."
    )
    return headline, summary, mechanisms, confidence


def build_remote_signals(lat: float, lon: float, med_snapshots: Dict[str, pd.Series], current: pd.Series, language: str) -> List[str]:
    lines: List[str] = []
    focus_region = classify_focus_region(lat, lon, language)
    if 25 <= lat <= 55 and -80 <= lon <= 20:
        newfoundland = med_snapshots.get('newfoundland')
        azores = med_snapshots.get('azores')
        biscay = med_snapshots.get('biscay')
        if newfoundland is not None and azores is not None:
            p_newf = float(newfoundland.get('pressure_hpa', float('nan')))
            p_azores = float(azores.get('pressure_hpa', float('nan')))
            p_biscay = float(biscay.get('pressure_hpa', float('nan'))) if biscay is not None else float('nan')
            p_focus = float(current.get('pressure_hpa', float('nan')))
            lines.append(
                tr(
                    language,
                    f"Chaîne Atlantique: Terre-Neuve {value_label(p_newf, ' hPa', 0)}, Açores {value_label(p_azores, ' hPa', 0)}, Gascogne {value_label(p_biscay, ' hPa', 0)}, point étudié {value_label(p_focus, ' hPa', 0)}. Cela décrit l'état instantané de l'onde barocline d'ouest en est.",
                    f"Cadena Atlántica: Terranova {value_label(p_newf, ' hPa', 0)}, Azores {value_label(p_azores, ' hPa', 0)}, Vizcaya {value_label(p_biscay, ' hPa', 0)}, punto estudiado {value_label(p_focus, ' hPa', 0)}. Esto describe el estado instantáneo de la onda baroclina de oeste a este.",
                    f"Atlantic chain: Newfoundland {value_label(p_newf, ' hPa', 0)}, Azores {value_label(p_azores, ' hPa', 0)}, Biscay {value_label(p_biscay, ' hPa', 0)}, analyzed point {value_label(p_focus, ' hPa', 0)}. This describes the instantaneous state of the west-to-east baroclinic wave train."
                )
            )
            lines.append(
                tr(
                    language,
                    f"Une dépression canadienne n'agit pas mécaniquement à J+7 sur {focus_region}. Ce que l'on peut lire, c'est la propagation d'une onde et la succession des creusements / dorsales sur l'Atlantique nord. Si le signal se transmet via Açores puis Gascogne, un impact sur {focus_region} devient plausible quelques jours plus tard.",
                    f"Una depresión canadiense no actúa mecánicamente a D+7 sobre {focus_region}. Lo que se puede leer es la propagación de una onda y la sucesión de profundizaciones / dorsales en el Atlántico norte. Si la señal se transmite vía Azores y luego Vizcaya, un impacto sobre {focus_region} se vuelve plausible unos días después.",
                    f"A Canadian low does not mechanically act on {focus_region} at D+7. What can be read is wave propagation and the succession of cyclogenesis / ridges across the North Atlantic. If the signal propagates via the Azores and then Biscay, an impact on {focus_region} becomes plausible a few days later."
                )
            )

    return lines or [tr(language, 'Pas de lecture lointaine robuste sur cette zone avec les seuls échantillons utilisés.', 'No hay lectura lejana robusta en esta zona con las muestras utilizadas.', 'No robust remote reading for this area with the sampled points only.')]


def build_generating_factors(
    lat: float,
    lon: float,
    current: pd.Series,
    forecast: pd.DataFrame,
    med_snapshots: Dict[str, pd.Series],
    language: str,
) -> List[str]:
    lines: List[str] = []
    focus_region = classify_focus_region(lat, lon, language)
    wind_dir = float(current.get('wind_direction_deg', float('nan')))
    wind_speed = float(current.get('wind_speed_kn', float('nan')))
    gust = float(current.get('wind_gust_kn', float('nan')))
    pressure = float(current.get('pressure_hpa', float('nan')))
    next_24h = forecast[forecast['time'] <= forecast['time'].min() + pd.Timedelta(hours=24)]
    pressure_trend_24h = float(next_24h['pressure_hpa'].iloc[-1] - next_24h['pressure_hpa'].iloc[0]) if not next_24h.empty and 'pressure_hpa' in next_24h else float('nan')
    near_48h = forecast[forecast['time'] <= forecast['time'].min() + pd.Timedelta(hours=48)]
    afternoon = near_48h[near_48h['hour'].between(12, 18)]
    overnight = near_48h[(near_48h['hour'] <= 6) | (near_48h['hour'] >= 22)]
    thermal_delta = float(afternoon['wind_speed_kn'].mean() - overnight['wind_speed_kn'].mean()) if not afternoon.empty and not overnight.empty else float('nan')

    golfe = med_snapshots.get('golfe_du_lion')
    genoa = med_snapshots.get('genoa')
    balearic = med_snapshots.get('balearic')
    azores = med_snapshots.get('azores')
    biscay = med_snapshots.get('biscay')
    newfoundland = med_snapshots.get('newfoundland')

    golfe_pressure = float(golfe.get('pressure_hpa', float('nan'))) if golfe is not None else float('nan')
    golfe_wind = float(golfe.get('wind_speed_kn', float('nan'))) if golfe is not None else float('nan')
    genoa_pressure = float(genoa.get('pressure_hpa', float('nan'))) if genoa is not None else float('nan')
    balearic_pressure = float(balearic.get('pressure_hpa', float('nan'))) if balearic is not None else float('nan')
    azores_pressure = float(azores.get('pressure_hpa', float('nan'))) if azores is not None else float('nan')
    biscay_pressure = float(biscay.get('pressure_hpa', float('nan'))) if biscay is not None else float('nan')
    newfoundland_pressure = float(newfoundland.get('pressure_hpa', float('nan'))) if newfoundland is not None else float('nan')

    if math.isfinite(golfe_pressure) or math.isfinite(genoa_pressure) or math.isfinite(balearic_pressure):
        lines.append(
            tr(
                language,
                f"Fait générateur bassin: point {value_label(pressure, ' hPa', 0)}, golfe du Lion {value_label(golfe_pressure, ' hPa', 0)}, Gênes {value_label(genoa_pressure, ' hPa', 0)}, Baléares {value_label(balearic_pressure, ' hPa', 0)}. C'est la géométrie de ces centres de pression, plus que le vent local seul, qui prépare ensuite le régime sur {focus_region}.",
                f"Hecho generador de cuenca: punto {value_label(pressure, ' hPa', 0)}, golfo de León {value_label(golfe_pressure, ' hPa', 0)}, Génova {value_label(genoa_pressure, ' hPa', 0)}, Baleares {value_label(balearic_pressure, ' hPa', 0)}. Es la geometría de estos centros de presión, más que el viento local aislado, la que prepara después el régimen sobre {focus_region}.",
                f"Basin-scale generating factor: point {value_label(pressure, ' hPa', 0)}, Gulf of Lion {value_label(golfe_pressure, ' hPa', 0)}, Genoa {value_label(genoa_pressure, ' hPa', 0)}, Balearics {value_label(balearic_pressure, ' hPa', 0)}. The geometry of these pressure centers, more than the local wind alone, is what sets up the next regime over {focus_region}."
            )
        )

    if math.isfinite(golfe_wind):
        lines.append(
            tr(
                language,
                f"Fait générateur régional: le réservoir du golfe du Lion souffle à {value_label(golfe_wind, ' kn')}. S'il reste plus fort que le point étudié ({value_label(wind_speed, ' kn')}), il peut injecter ou entretenir un signal de mistral / tramontane, ou au minimum fournir la masse d'air sèche et rafaleuse en amont.",
                f"Hecho generador regional: el reservorio del golfo de León sopla a {value_label(golfe_wind, ' kn')}. Si sigue más fuerte que el punto estudiado ({value_label(wind_speed, ' kn')}), puede inyectar o mantener una señal de mistral / tramontana, o al menos aportar la masa de aire seca y con rachas aguas arriba.",
                f"Regional generating factor: the Gulf of Lion reservoir is blowing at {value_label(golfe_wind, ' kn')}. If it stays stronger than the analyzed point ({value_label(wind_speed, ' kn')}), it can inject or maintain a mistral / tramontane signal, or at least supply the dry, gusty upstream air mass."
            )
        )

    if math.isfinite(pressure_trend_24h):
        trend_text = tr(language, 'baisse', 'bajada', 'fall') if pressure_trend_24h < 0 else tr(language, 'hausse', 'subida', 'rise')
        lines.append(
            tr(
                language,
                f"Fait générateur temporel: la pression montre une {trend_text} de {pressure_trend_24h:+.1f} hPa sur 24 h. Une baisse prépare plutôt creusement, convergence et rafales; une hausse prépare plutôt stabilisation et assèchement du champ local.",
                f"Hecho generador temporal: la presión muestra una {trend_text} de {pressure_trend_24h:+.1f} hPa en 24 h. Una bajada prepara más bien profundización, convergencia y rachas; una subida prepara estabilización y secado del campo local.",
                f"Time-evolving generating factor: pressure shows a {trend_text} of {pressure_trend_24h:+.1f} hPa over 24 h. A fall tends to precondition deepening, convergence, and gusts; a rise tends to precondition stabilization and drying of the local field."
            )
        )

    if math.isfinite(thermal_delta) and abs(thermal_delta) >= 1.5:
        lines.append(
            tr(
                language,
                f"Fait générateur local: le cycle diurne ajoute {thermal_delta:+.1f} kn entre nuit et après-midi. Même avec un gradient synoptique moyen, cette pompe thermique peut déclencher la bascule réellement ressentie sur les côtes, baies et détroits.",
                f"Hecho generador local: el ciclo diurno añade {thermal_delta:+.1f} kn entre noche y tarde. Incluso con un gradiente sinóptico medio, esta bomba térmica puede disparar el giro realmente sentido en costas, bahías y estrechos.",
                f"Local generating factor: the diurnal cycle adds {thermal_delta:+.1f} kn between night and afternoon. Even with only a moderate synoptic gradient, this thermal pump can trigger the actual shift felt along coasts, bays, and straits."
            )
        )

    if math.isfinite(gust) and math.isfinite(wind_speed) and gust >= wind_speed + 7:
        lines.append(
            tr(
                language,
                f"Fait générateur d'exposition: l'écart vent moyen / rafales ({value_label(wind_speed, ' kn')} / {value_label(gust, ' kn')}) indique déjà une couche basse turbulente. C'est souvent le signe que le relief, les caps ou les détroits transforment un signal régional moyen en phénomène local plus brutal.",
                f"Hecho generador de exposición: la diferencia entre viento medio y rachas ({value_label(wind_speed, ' kn')} / {value_label(gust, ' kn')}) ya indica una capa baja turbulenta. Suele ser la señal de que el relieve, los cabos o los estrechos transforman una señal regional media en un fenómeno local más brusco.",
                f"Exposure generating factor: the mean wind / gust gap ({value_label(wind_speed, ' kn')} / {value_label(gust, ' kn')}) already points to a turbulent low layer. That often means terrain, headlands, or straits are transforming a moderate regional signal into a sharper local phenomenon."
            )
        )

    if math.isfinite(newfoundland_pressure) or math.isfinite(azores_pressure) or math.isfinite(biscay_pressure):
        lines.append(
            tr(
                language,
                f"Amont Atlantique utile: Terre-Neuve {value_label(newfoundland_pressure, ' hPa', 0)}, Açores {value_label(azores_pressure, ' hPa', 0)}, Gascogne {value_label(biscay_pressure, ' hPa', 0)}. Le bon réflexe n'est pas d'attribuer directement le temps local à Terre-Neuve, mais de suivre si le signal se retransmet réellement jusqu'à Gascogne puis au golfe du Lion / Gênes.",
                f"Señal atlántica útil: Terranova {value_label(newfoundland_pressure, ' hPa', 0)}, Azores {value_label(azores_pressure, ' hPa', 0)}, Vizcaya {value_label(biscay_pressure, ' hPa', 0)}. La buena lectura no es atribuir directamente el tiempo local a Terranova, sino seguir si la señal se retransmite realmente hasta Vizcaya y luego al golfo de León / Génova.",
                f"Useful Atlantic upstream factor: Newfoundland {value_label(newfoundland_pressure, ' hPa', 0)}, Azores {value_label(azores_pressure, ' hPa', 0)}, Biscay {value_label(biscay_pressure, ' hPa', 0)}. The right reading is not to attribute local weather directly to Newfoundland, but to track whether the signal is actually relayed into Biscay and then into the Gulf of Lion / Genoa."
            )
        )

    if math.isfinite(wind_dir):
        lines.append(
            tr(
                language,
                f"Conséquence locale attendue: avec un flux dominant {degrees_to_cardinal(wind_dir)}, les zones au vent et les détroits de {focus_region} deviennent les premiers amplificateurs du signal synoptique.",
                f"Consecuencia local esperada: con un flujo dominante {degrees_to_cardinal(wind_dir)}, las zonas a barlovento y los estrechos de {focus_region} se convierten en los primeros amplificadores de la señal sinóptica.",
                f"Expected local consequence: with a dominant {degrees_to_cardinal(wind_dir)} flow, windward coasts and straits in {focus_region} become the first amplifiers of the synoptic signal."
            )
        )

    return lines or [tr(language, 'Pas de fait générateur robuste isolé: on reste sur un régime faible à modéré dominé par les ajustements locaux.', 'No se aísla un hecho generador robusto: seguimos en un régimen débil a moderado dominado por ajustes locales.', 'No single robust generating factor stands out: the regime remains weak to moderate and mostly governed by local adjustments.')]


def build_corsica_regional_relays(
    lat: float,
    lon: float,
    current: pd.Series,
    med_snapshots: Dict[str, pd.Series],
    language: str,
) -> List[str]:
    focus_region = classify_focus_region(lat, lon, language)
    if 'Corse' not in focus_region and 'Córcega' not in focus_region and 'Corsica' not in focus_region:
        return []

    lines: List[str] = []
    genoa = med_snapshots.get('genoa')
    sardinia = med_snapshots.get('north_sardinia')
    tyrrhenian = med_snapshots.get('tyrrhenian')
    balearic = med_snapshots.get('balearic')
    current_pressure = float(current.get('pressure_hpa', float('nan')))
    wave_dir = float(current.get('wave_direction_deg', float('nan')))
    wave_height = float(current.get('wave_height_m', float('nan')))
    wave_period = float(current.get('wave_period_s', float('nan')))
    wind_dir = float(current.get('wind_direction_deg', float('nan')))

    genoa_pressure = float(genoa.get('pressure_hpa', float('nan'))) if genoa is not None else float('nan')
    genoa_wind = float(genoa.get('wind_speed_kn', float('nan'))) if genoa is not None else float('nan')
    sardinia_pressure = float(sardinia.get('pressure_hpa', float('nan'))) if sardinia is not None else float('nan')
    sardinia_wind = float(sardinia.get('wind_speed_kn', float('nan'))) if sardinia is not None else float('nan')
    tyrrhenian_pressure = float(tyrrhenian.get('pressure_hpa', float('nan'))) if tyrrhenian is not None else float('nan')
    tyrrhenian_wind = float(tyrrhenian.get('wind_speed_kn', float('nan'))) if tyrrhenian is not None else float('nan')
    balearic_pressure = float(balearic.get('pressure_hpa', float('nan'))) if balearic is not None else float('nan')

    lines.append(
        tr(
            language,
            f"Relais Corse: Gênes {value_label(genoa_pressure, ' hPa', 0)} / {value_label(genoa_wind, ' kn')}, nord Sardaigne {value_label(sardinia_pressure, ' hPa', 0)} / {value_label(sardinia_wind, ' kn')}, Tyrrhénienne {value_label(tyrrhenian_pressure, ' hPa', 0)} / {value_label(tyrrhenian_wind, ' kn')}, point {value_label(current_pressure, ' hPa', 0)}. Cette chaîne explique souvent mieux les bascules corses que le seul point local.",
            f"Relés Córcega: Génova {value_label(genoa_pressure, ' hPa', 0)} / {value_label(genoa_wind, ' kn')}, norte de Cerdeña {value_label(sardinia_pressure, ' hPa', 0)} / {value_label(sardinia_wind, ' kn')}, Tirreno {value_label(tyrrhenian_pressure, ' hPa', 0)} / {value_label(tyrrhenian_wind, ' kn')}, punto {value_label(current_pressure, ' hPa', 0)}. Esta cadena explica a menudo mejor los giros corsos que el solo punto local.",
            f"Corsica relays: Genoa {value_label(genoa_pressure, ' hPa', 0)} / {value_label(genoa_wind, ' kn')}, north Sardinia {value_label(sardinia_pressure, ' hPa', 0)} / {value_label(sardinia_wind, ' kn')}, Tyrrhenian {value_label(tyrrhenian_pressure, ' hPa', 0)} / {value_label(tyrrhenian_wind, ' kn')}, point {value_label(current_pressure, ' hPa', 0)}. This chain often explains Corsican shifts better than the local point alone."
        )
    )

    if math.isfinite(genoa_pressure) and math.isfinite(current_pressure) and genoa_pressure <= current_pressure - 1.0:
        lines.append(
            tr(
                language,
                f"Lecture ligurienne: Gênes plus basse que le point de {abs(genoa_pressure - current_pressure):.1f} hPa. Cela favorise un appel vers le NE / E sur Bastia, Cap Corse puis la côte orientale.",
                f"Lectura liguria: Génova más baja que el punto en {abs(genoa_pressure - current_pressure):.1f} hPa. Favorece una aspiración hacia NE / E sobre Bastia, Cap Corse y luego la costa oriental.",
                f"Ligurian reading: Genoa is lower than the point by {abs(genoa_pressure - current_pressure):.1f} hPa. That favors a pull toward NE / E over Bastia, Cap Corse, and then the east coast."
            )
        )

    if math.isfinite(sardinia_pressure) and math.isfinite(current_pressure) and sardinia_pressure <= current_pressure - 1.0:
        lines.append(
            tr(
                language,
                f"Lecture sarde: le nord de la Sardaigne reste plus bas de {abs(sardinia_pressure - current_pressure):.1f} hPa. Cela entretient volontiers le couloir de Bonifacio et les accélérations entre sud Corse et Maddalena.",
                f"Lectura sarda: el norte de Cerdeña permanece más bajo en {abs(sardinia_pressure - current_pressure):.1f} hPa. Esto sostiene a menudo el corredor de Bonifacio y las aceleraciones entre sur de Córcega y Maddalena.",
                f"Sardinian reading: northern Sardinia stays lower by {abs(sardinia_pressure - current_pressure):.1f} hPa. That often sustains the Bonifacio corridor and accelerations between southern Corsica and La Maddalena."
            )
        )

    if math.isfinite(tyrrhenian_pressure) and math.isfinite(current_pressure) and tyrrhenian_pressure <= current_pressure - 1.0:
        lines.append(
            tr(
                language,
                f"Lecture tyrrhénienne: pression plus basse à l'est ({value_label(tyrrhenian_pressure, ' hPa', 0)}). Une bascule d'est à sud-est peut alors tenir plus longtemps sur la façade orientale, même si l'ouest de l'île redevient plus calme.",
                f"Lectura tirrena: presión más baja al este ({value_label(tyrrhenian_pressure, ' hPa', 0)}). Un giro de este a sudeste puede entonces durar más sobre la fachada oriental, aunque el oeste de la isla vuelva antes a la calma.",
                f"Tyrrhenian reading: lower pressure to the east ({value_label(tyrrhenian_pressure, ' hPa', 0)}). An east to southeast shift can then last longer over the east coast even if western Corsica settles earlier."
            )
        )

    if math.isfinite(wave_height) and math.isfinite(wave_period) and math.isfinite(wave_dir):
        lines.append(
            tr(
                language,
                f"Relais mer: houle {value_label(wave_height, ' m')} de {degrees_to_cardinal(wave_dir)} sur {value_label(wave_period, ' s')}. Si cette direction diffère du vent local {degrees_to_cardinal(wind_dir)}, la Corse peut garder de la mer résiduelle alors même que le vent tourne déjà.",
                f"Relé de mar: oleaje {value_label(wave_height, ' m')} de {degrees_to_cardinal(wave_dir)} en {value_label(wave_period, ' s')}. Si esta dirección difiere del viento local {degrees_to_cardinal(wind_dir)}, Córcega puede conservar mar residual aunque el viento ya haya rolado.",
                f"Sea relay: swell {value_label(wave_height, ' m')} from {degrees_to_cardinal(wave_dir)} at {value_label(wave_period, ' s')}. If that direction differs from the local wind {degrees_to_cardinal(wind_dir)}, Corsica can keep residual sea even after the wind has already shifted."
            )
        )

    if math.isfinite(balearic_pressure) and math.isfinite(current_pressure):
        lines.append(
            tr(
                language,
                f"Relais ouest: Baléares {value_label(balearic_pressure, ' hPa', 0)}. Ce point sert de témoin de l'ouest du bassin: s'il diverge de Gênes et de la Tyrrhénienne, on entre souvent dans une Corse coupée en deux entre façade ouest et façade est.",
                f"Relé oeste: Baleares {value_label(balearic_pressure, ' hPa', 0)}. Este punto actúa como testigo del oeste de la cuenca: si diverge de Génova y del Tirreno, a menudo aparece una Córcega partida entre fachada oeste y este.",
                f"Western relay: Balearics {value_label(balearic_pressure, ' hPa', 0)}. This point acts as a west-basin witness: when it diverges from Genoa and the Tyrrhenian, Corsica often ends up split between west and east coasts."
            )
        )

    return lines


def build_limitations(language: str) -> List[str]:
    return [
        tr(language, "Diagnostic basé sur des points d'échantillonnage et non sur un champ de pression complet haute résolution.", "Diagnóstico basado en puntos de muestreo y no en un campo completo de presión de alta resolución.", "Diagnosis is based on sampled points rather than a full high-resolution pressure field."),
        tr(language, "Les mécanismes locaux complexes (relief, canalisation de vallées, effets thermiques fins) restent partiellement résolus.", "Los mecanismos locales complejos (relieve, canalización de valles, efectos térmicos finos) siguen solo parcialmente resueltos.", "Complex local mechanisms (terrain, valley channeling, fine thermal effects) remain only partially resolved."),
        tr(language, "Le niveau de confiance doit être relu avec les cartes et l'observation réelle avant décision de navigation.", "El nivel de confianza debe releerse con mapas y observación real antes de decidir la navegación.", "Confidence should be checked against charts and real observations before a navigation decision."),
    ]


def is_mediterranean_focus(lat: float, lon: float) -> bool:
    return classify_focus_region(lat, lon, 'en') in {
        'Corsica',
        'the Balearics',
        'the Catalan sector',
        'the Gulf of Lion',
        'the Ligurian Sea',
        'northern Sardinia',
    }


def run_analysis(lat: float, lon: float, horizon_days: int, language: str) -> Dict[str, Any]:
    forecast = fetch_forecast_bundle(lat, lon, horizon_days)
    if forecast.empty:
        raise HTTPException(status_code=502, detail='Aucune donnée météo récupérée.')

    now_ts = pd.Timestamp(datetime.now(timezone.utc))
    focus_region = classify_focus_region(lat, lon, language)
    current = nearest_row(forecast, now_ts)
    climatology = build_climatology_frame(lat, lon, now_ts.date(), horizon_days)
    ring_snapshots = fetch_reference_snapshots(build_ring_points(lat, lon), horizon_days, now_ts)
    med_snapshots = fetch_reference_snapshots(MEDITERRANEAN_REFERENCE_POINTS, horizon_days, now_ts) if is_mediterranean_focus(lat, lon) else {}
    headline, summary, mechanisms, confidence = infer_mechanisms(current, forecast, ring_snapshots, med_snapshots, language)
    regional_regimes = infer_western_mediterranean_regimes(lat, lon, current, forecast, med_snapshots, language)
    regime_matrix = build_regime_matrix(lat, lon, current, forecast, med_snapshots, language)
    corsica_subregions = build_corsica_subregion_outlook(lat, lon, current, med_snapshots, language)
    generating_factors = build_generating_factors(lat, lon, current, forecast, med_snapshots, language)
    corsica_regional_relays = build_corsica_regional_relays(lat, lon, current, med_snapshots, language)

    generated_at = datetime.now(timezone.utc)
    return {
        'headline': headline,
        'summary': summary,
        'focus_region': focus_region,
        'confidence': confidence,
        'generated_at': generated_at.isoformat(),
        'generated_at_label': generated_at.strftime('%Y-%m-%d %H:%M UTC'),
        'mechanisms': mechanisms,
        'generating_factors': generating_factors,
        'regional_regimes': regional_regimes,
        'regime_matrix': regime_matrix,
        'corsica_subregions': corsica_subregions,
        'corsica_regional_relays': corsica_regional_relays,
        'day_outlook': build_daily_outlook(forecast, now_ts, language),
        'climate_context': build_climate_context(forecast, climatology, language),
        'remote_signals': build_remote_signals(lat, lon, med_snapshots, current, language),
        'limitations': build_limitations(language),
        'metrics': {
            'current_wind': f"{value_label(current.get('wind_speed_kn'), ' kn')} {degrees_to_cardinal(current.get('wind_direction_deg'))}",
            'current_pressure': value_label(current.get('pressure_hpa'), ' hPa', 0),
            'current_wave': value_label(current.get('wave_height_m'), ' m'),
            'current_temp': value_label(current.get('temperature_c'), '°C'),
        },
        'sources': ['Open-Meteo forecast', 'Open-Meteo archive', 'Open-Meteo marine', 'MetPy', 'Pandas'],
        'command_hint': 'python weather/server.py --host 127.0.0.1 --port 8777',
    }


@app.get('/weather/health')
def weather_health() -> Dict[str, Any]:
    return {'ok': True, 'service': 'ceibo-weather-analysis'}


@app.post('/weather/analyze')
def weather_analyze(payload: WeatherAnalyzeRequest) -> Dict[str, Any]:
    try:
        return run_analysis(payload.lat, payload.lon, payload.horizon_days, payload.language)
    except HTTPException:
        raise
    except requests.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f'API météo distante en erreur: {exc}') from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'Analyse météo impossible: {exc}') from exc


def main() -> None:
    parser = argparse.ArgumentParser(description='Serveur local d\'analyse météo CEIBO')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8777)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level='info')


if __name__ == '__main__':
    main()