#!/usr/bin/env python3
"""Convert GRIB/GRIB2 to JSON usable by CEIBO weather import.

Output format is intentionally close to a simplified grib2json payload:
{
  "records": [
    {
      "header": { ... },
      "data": [ ... flattened values ... ]
    }
  ]
}

Usage examples:
  python3 extract_grib.py --input Riviera_SKIRON_080326.grb
  python3 extract_grib.py --input Riviera_SKIRON_080326.grb --var msl --output Riviera_SKIRON_080326.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import numpy as np
import xarray as xr


def _infer_output_path(input_path: Path, output: str | None) -> Path:
    if output:
        return Path(output).expanduser().resolve()
    return input_path.with_suffix(".json").resolve()


def _normalize_longitude(value: float) -> float:
    lon = float(value)
    while lon > 180.0:
        lon -= 360.0
    while lon < -180.0:
        lon += 360.0
    return lon


def _find_coord_name(candidates: Iterable[str], available: Iterable[str]) -> str | None:
    available_set = set(available)
    for name in candidates:
        if name in available_set:
            return name
    return None


def _pick_data_variable(dataset: xr.Dataset, requested_var: str | None) -> str:
    data_vars = [name for name in dataset.data_vars]
    if not data_vars:
        raise ValueError("Aucune variable de données trouvée dans le GRIB.")

    if requested_var:
        if requested_var not in dataset.data_vars:
            raise ValueError(
                f"Variable '{requested_var}' introuvable. Variables disponibles: {', '.join(data_vars)}"
            )
        return requested_var

    # Prefer common pressure/wind/temp names when available.
    preferred = ["msl", "prmsl", "sp", "u10", "v10", "t2m", "tp"]
    for name in preferred:
        if name in dataset.data_vars:
            return name

    return data_vars[0]


def _extract_grid(
    array2d: xr.DataArray,
    lat_name: str,
    lon_name: str,
    scale: float,
) -> Tuple[Dict[str, Any], List[float]]:
    lats = np.asarray(array2d.coords[lat_name].values, dtype=float)
    lons = np.asarray(array2d.coords[lon_name].values, dtype=float)
    values = np.asarray(array2d.values, dtype=float)

    if values.ndim != 2:
        raise ValueError(f"La variable n'est pas 2D après sélection: shape={values.shape}")

    ny, nx = values.shape
    if ny < 1 or nx < 1:
        raise ValueError("Grille vide détectée.")

    # Convert longitudes to [-180, 180] to align with map display.
    lons_norm = np.array([_normalize_longitude(v) for v in lons], dtype=float)

    lo1 = float(lons_norm[0])
    lo2 = float(lons_norm[-1])
    la1 = float(lats[0])
    la2 = float(lats[-1])

    dx = abs(float(lons_norm[1] - lons_norm[0])) if nx > 1 else 0.0
    dy = abs(float(lats[1] - lats[0])) if ny > 1 else 0.0

    flat = (values * scale).reshape(-1)
    sanitized = [float(v) if np.isfinite(v) else None for v in flat]

    header = {
        "nx": int(nx),
        "ny": int(ny),
        "lo1": lo1,
        "lo2": lo2,
        "la1": la1,
        "la2": la2,
        "dx": dx,
        "dy": dy,
    }
    return header, sanitized


def convert_grib_to_json(
    input_path: Path,
    output_path: Path,
    requested_var: str | None = None,
    scale: float = 1.0,
) -> Path:
    dataset = xr.open_dataset(str(input_path), engine="cfgrib")

    var_name = _pick_data_variable(dataset, requested_var)
    data_var = dataset[var_name]

    lat_name = _find_coord_name(["latitude", "lat"], data_var.coords)
    lon_name = _find_coord_name(["longitude", "lon"], data_var.coords)
    if not lat_name or not lon_name:
        raise ValueError(
            f"Coordonnées lat/lon introuvables pour '{var_name}'. Coords: {list(data_var.coords)}"
        )

    # Reduce extra dims (time, level, step, number, etc.) by selecting first index.
    squeeze_dims = [dim for dim in data_var.dims if dim not in (lat_name, lon_name)]
    reduced = data_var
    for dim in squeeze_dims:
        reduced = reduced.isel({dim: 0})

    if reduced.dims != (lat_name, lon_name):
        reduced = reduced.transpose(lat_name, lon_name)

    grid_header, data = _extract_grid(reduced, lat_name, lon_name, scale)

    units = str(data_var.attrs.get("units") or "").strip()
    long_name = str(data_var.attrs.get("long_name") or data_var.attrs.get("GRIB_name") or var_name).strip()

    payload = {
        "source": input_path.name,
        "records": [
            {
                "header": {
                    **grid_header,
                    "parameterNumberName": long_name,
                    "parameterUnits": units,
                    "shortName": var_name,
                },
                "data": data,
            }
        ],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    return output_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convertit un GRIB/GRIB2 en JSON (format CEIBO).")
    parser.add_argument("--input", "-i", required=True, help="Chemin du fichier .grib/.grib2/.grb/.grb2")
    parser.add_argument("--output", "-o", help="Chemin du fichier JSON de sortie (optionnel)")
    parser.add_argument("--var", help="Nom de variable GRIB (optionnel, ex: msl, u10, v10, t2m)")
    parser.add_argument("--scale", type=float, default=1.0, help="Facteur multiplicatif sur les valeurs")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        parser.error(f"Fichier introuvable: {input_path}")

    output_path = _infer_output_path(input_path, args.output)

    try:
        written = convert_grib_to_json(
            input_path=input_path,
            output_path=output_path,
            requested_var=args.var,
            scale=args.scale,
        )
        print(f"Conversion OK: {input_path.name} -> {written}")
        return 0
    except Exception as exc:
        print(f"Erreur conversion GRIB: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())