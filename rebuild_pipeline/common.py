"""Shared helpers for the OSM transmission-topology rebuild pipeline.

Deliberately small: config loading, the length convention, NDJSON I/O and the
projection helper. Every documented threshold lives in 02_build_topology.py so
that a reader can find all of them in one place, next to the README citation.

README_methodology_v23.md section 8 fixes the CRS convention: EPSG:4326 for
storage. Section 12(c) fixes the length convention: haversine with
R = 6371.0088 km. Geometric predicates (distance, buffer, clip) need a metric
CRS, which is a per-region choice and therefore config (`metric_crs`).
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

import yaml

# Mean Earth radius used for every length in this pipeline.
# README_methodology_v23.md s12(c): "haversine, R=6371.0088 km".
EARTH_RADIUS_KM = 6371.0088


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #

def load_config(path: str) -> Dict[str, Any]:
    """Read a YAML config and apply the documented defaults.

    Nothing region-specific is defaulted here: a missing region or voltage floor
    is an error, not a guess (README s1 - the floor is the single most
    consequential parameter in the build).
    """
    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}

    if "voltage_floor_kv" not in cfg:
        raise SystemExit(f"{path}: voltage_floor_kv is required (README s1)")
    if not (cfg.get("bboxes") or cfg.get("areas")):
        raise SystemExit(f"{path}: one of bboxes / areas is required")

    cfg.setdefault("region_name", "region")
    # The public-network frequency. Top level, not under `traction`, because a
    # region can have no traction system and still not be 50 Hz (the Americas,
    # Saudi, western Japan, parts of Brazil are 60 Hz). Legacy configs that put
    # it under traction still work.
    if "grid_frequency_hz" not in cfg:
        legacy = (cfg.get("traction") or {}).get("grid_frequency_hz")
        cfg["grid_frequency_hz"] = float(legacy) if legacy is not None else 50.0
    cfg["grid_frequency_hz"] = float(cfg["grid_frequency_hz"])
    if "metric_crs" not in cfg:
        # No default. EPSG:3857 used to be the fallback, which is conformal: every
        # metre gate (150/250/30/50/25 m) would be inflated by 1/cos(latitude), so
        # at 60 deg N a nominal 250 m catchment is ~125 m of ground distance.
        raise SystemExit(f"{path}: metric_crs is required - give an equal-area metre "
                         "CRS for the region (EPSG:3035 Europe, 3577 Australia, 5070 CONUS)")
    cfg.setdefault("high_pass_floor_kv", 100.0)      # README s6.1 two-pass banding
    cfg.setdefault("harvest_dir", "harvest")
    cfg.setdefault("out_dir", "out")
    cfg.setdefault("traction", {})
    cfg["traction"].setdefault("enabled", False)
    cfg["traction"].setdefault("frequency_hz", 16.7)
    cfg["traction"].setdefault("frequency_tags", ["16.7", "16.67"])
    cfg["traction"].setdefault("max_voltage_kv", 132.0)
    cfg["traction"].setdefault("countries", [])
    cfg["traction"].setdefault("operators", [])
    cfg.setdefault("country_source", "none")          # none | polygons | osm_tag
    cfg.setdefault("country_polygons", None)
    cfg.setdefault("country_field", "ISO_A2")
    cfg.setdefault("standard_voltages_kv", [])
    cfg.setdefault("layer_voltages_kv", [])
    cfg.setdefault("layer_min_spans", 50)
    cfg.setdefault("overpass", {})
    cfg["overpass"].setdefault("endpoints", ["https://overpass-api.de/api/interpreter"])
    cfg["overpass"].setdefault("timeout_s", 900)
    cfg["overpass"].setdefault("max_attempts", 6)
    cfg["overpass"].setdefault("backoff_base_s", 20)
    cfg["overpass"].setdefault("backoff_max_s", 600)
    cfg["overpass"].setdefault("polite_gap_s", 8)
    cfg["overpass"].setdefault("chunk_deg", 2.0)
    cfg["overpass"].setdefault("harvest_substations", True)
    cfg["overpass"].setdefault("harvest_dc_sweep", True)
    cfg.setdefault("dc_reclassify_osm_ids", [])
    cfg.setdefault("scope_bbox", None)                # README s12(a) study-area clip
    return cfg


def log(msg: str) -> None:
    """Timestamped progress line on stderr, so stdout stays machine-readable."""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# lengths
# --------------------------------------------------------------------------- #

def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in metres, R = 6371.0088 km (README s12(c))."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * 1000.0 * math.asin(min(1.0, math.sqrt(a)))


def geodesic_length_m(coords: Sequence[Sequence[float]]) -> float:
    """Haversine length of a lon/lat vertex list. The authoritative length."""
    total = 0.0
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        total += haversine_m(x1, y1, x2, y2)
    return total


def line_length_m(geom) -> float:
    """Haversine length of a shapely LineString / MultiLineString in EPSG:4326."""
    if geom is None or geom.is_empty:
        return 0.0
    if geom.geom_type == "LineString":
        return geodesic_length_m(list(geom.coords))
    if geom.geom_type in ("MultiLineString", "GeometryCollection"):
        return sum(line_length_m(g) for g in geom.geoms if g.geom_type == "LineString")
    return 0.0


# --------------------------------------------------------------------------- #
# NDJSON
# --------------------------------------------------------------------------- #

def iter_ndjson(paths: Iterable[str]) -> Iterator[Dict[str, Any]]:
    """Yield every JSON object from a set of NDJSON files, skipping blanks."""
    for path in paths:
        with open(path, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise SystemExit(f"{path}:{lineno}: bad NDJSON ({exc})")


def write_ndjson(path: str, records: Iterable[Dict[str, Any]]) -> int:
    """Write records as NDJSON via a temp file, so a killed run leaves no
    half-written chunk that the resume logic would then skip."""
    tmp = path + ".part"
    n = 0
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")
            n += 1
    os.replace(tmp, path)
    return n


def ndjson_files(harvest_dir: str) -> List[str]:
    """Every harvested chunk, in a stable order (build determinism)."""
    out = []
    for root, _dirs, files in os.walk(harvest_dir):
        for f in sorted(files):
            if f.endswith(".ndjson"):
                out.append(os.path.join(root, f))
    return sorted(out)


# --------------------------------------------------------------------------- #
# tag parsing shared by harvest (sanity checks) and build
# --------------------------------------------------------------------------- #

def split_semicolon(value: Optional[str]) -> List[str]:
    """OSM multi-value tags are semicolon separated (paper Tables 2-3)."""
    if value is None:
        return []
    return [p.strip() for p in str(value).split(";") if p.strip() != ""]


def parse_float(value: Optional[str]) -> Optional[float]:
    """Tolerant numeric parse: strips units and thousands spaces, keeps sign.

    OSM carries '400000', '400 000', '400000 V', '110kV'. Anything that still
    fails to parse returns None and the caller records that as unknown rather
    than guessing (project rule: never replace unknown with a plausible guess).
    """
    if value is None:
        return None
    s = str(value).strip().lower().replace(" ", "").replace("_", "")
    mult = 1.0
    for suffix, factor in (("kv", 1000.0), ("mv", 1_000_000.0), ("v", 1.0)):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            mult = factor
            break
    try:
        return float(s) * mult
    except ValueError:
        return None
