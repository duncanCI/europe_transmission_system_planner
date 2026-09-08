#!/usr/bin/env python3
"""OSM power lines in a planning lifecycle state -> one context GeoJSON.

Reads the NDJSON written by a lifecycle harvest (Overpass `out tags geom` of
ways/relations tagged proposed:power=*, power=proposed, power=construction +
construction:power=*, planned:power=*), and writes
webmap/osm_lifecycle_public.geojson: one LineString/MultiLineString per element
with the lifecycle state, kind, voltage, name/ref/operator, dates, countries
(nearest station of the v23 graph within 60 km - Natural Earth polygons are not
shipped with this repo), length and a stable feature id.

These features are CONTEXT ONLY. The v23 topology harvest asks for power=line/
cable/minor_line, so lifecycle-prefixed elements never enter the graph, and
neither viewer's model uses them. A reviewer can suggest one for the core model
from its popup ("Suggest for the core model" -> feedback), which lands in the
private promotions file; an accepted promotion enters the screen through the
external-plans loader with provenance "sourced:OpenStreetMap proposed (ODbL),
promoted by review".

Usage: 04_build_lifecycle_layer.py --harvest-dir DIR [--graph europe_grid_graph.gpkg]
       [--out webmap/osm_lifecycle_public.geojson]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIFE_KEYS = ("proposed:power", "construction:power", "planned:power")
KV_RE = re.compile(r"\d+(?:\.\d+)?")
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")

# The year slider needs a delivery year on every feature. OSM rarely tags one
# (6 opening_date and 72 start_date tags in 2,300 elements), so a line without
# a date gets a DEFAULT by lifecycle state, flagged inferred: - the same
# treatment as Norway's licensing register in the modelled plans. A tagged
# opening_date is taken as sourced; a start_date at or after the base year is
# read as the delivery year (inferred); a past start_date on an unfinished
# line is a construction start and is ignored.
BASE_YEAR = 2026
DEFAULT_LEAD_YEARS = {"under construction": 2, "planned": 4, "proposed": 6}
OPENING_KEYS = ("opening_date", "proposed:opening_date", "construction:opening_date", "planned:opening_date",
                "end_date", "construction:end_date")
START_KEYS = ("start_date", "proposed:start_date", "planned:start_date", "construction:start_date")


def year_of(v) -> int | None:
    m = YEAR_RE.search(str(v or ""))
    return int(m.group(1)) if m else None


def delivery_year(tags: dict, state: str) -> tuple[int, str]:
    """(service_year_min, year_basis) for the slider."""
    for k in OPENING_KEYS:
        y = year_of(tags.get(k))
        if y:
            if y < BASE_YEAR:
                return BASE_YEAR, f"inferred:OSM {k}={tags[k]} is in the past on an unfinished line; taken as due now ({BASE_YEAR})"
            return y, f"sourced:OSM {k}={tags[k]}"
    for k in START_KEYS:
        y = year_of(tags.get(k))
        if y and y >= BASE_YEAR:
            return y, f"inferred:OSM {k}={tags[k]} read as the delivery year"
    lead = DEFAULT_LEAD_YEARS.get(state, 6)
    return BASE_YEAR + lead, f"inferred:no date tagged; default for a line {state} ({BASE_YEAR} + {lead} years)"


def lifecycle_of(tags: dict) -> tuple[str, str]:
    """(state, kind) from OSM lifecycle tagging; kind is line/cable/minor_line."""
    p = tags.get("power", "")
    if tags.get("proposed:power") or p == "proposed":
        return "proposed", tags.get("proposed:power") or tags.get("proposed") or "line"
    if p == "construction" or tags.get("construction:power"):
        return "under construction", tags.get("construction:power") or "line"
    if tags.get("planned:power") or p == "planned":
        return "planned", tags.get("planned:power") or "line"
    return "proposed", p or "line"


def voltage_kv(tags: dict) -> float | None:
    for k in ("voltage", "proposed:voltage", "construction:voltage", "planned:voltage"):
        v = tags.get(k)
        if v:
            nums = [float(x) for x in KV_RE.findall(v.replace(",", ";"))]
            if nums:
                m = max(nums)
                return round(m / 1000.0, 1) if m > 1000 else m
    return None


def haversine_km(a, b) -> float:
    (lon1, lat1), (lon2, lat2) = a, b
    p = math.pi / 180
    d = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2
    return 12742 * math.asin(math.sqrt(max(0.0, d)))


def line_km(coords) -> float:
    return sum(haversine_km(coords[i], coords[i + 1]) for i in range(len(coords) - 1))


def way_coords(el: dict):
    g = el.get("geometry") or []
    return [[pt["lon"], pt["lat"]] for pt in g if pt and "lon" in pt]


def relation_parts(el: dict):
    parts = []
    for m in el.get("members") or []:
        if m.get("type") == "way" and m.get("geometry"):
            c = [[pt["lon"], pt["lat"]] for pt in m["geometry"] if pt and "lon" in pt]
            if len(c) >= 2:
                parts.append(c)
    return parts


def load_stations(graph: Path):
    """(lon, lat, countries) for every station bus with a country, from the v23 graph."""
    if not graph.exists():
        return []
    with sqlite3.connect(graph) as con:
        try:
            rows = con.execute(
                "SELECT station_name, countries, "
                "(SELECT AVG(v) FROM (SELECT ST_X(geom) v)) FROM site_all LIMIT 1").fetchall()
        except Exception:
            rows = None
    # Spatialite functions are usually unavailable: read via geopandas instead.
    import geopandas as gpd
    sites = gpd.read_file(graph, layer="site_all", columns=["station_name", "countries", "node_type"])
    sites = sites[sites.countries.notna() & (sites.countries.astype(str) != "")]
    return [(g.x, g.y, str(c)) for g, c in zip(sites.geometry, sites.countries) if g is not None and not g.is_empty]


def nearest_country(stations, coords, max_km=60.0) -> str:
    """Countries of the nearest stations to the line's two ends (coarse grid for speed)."""
    found = set()
    for pt in (coords[0], coords[-1]):
        best, best_d = None, max_km
        for x, y, c in stations:
            if abs(x - pt[0]) > 1.2 or abs(y - pt[1]) > 0.8:
                continue
            d = haversine_km((x, y), pt)
            if d < best_d:
                best, best_d = c, d
        if best:
            found.update(best.split(";"))
    return ";".join(sorted(found))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--harvest-dir", required=True, type=Path)
    ap.add_argument("--graph", type=Path, default=REPO / "europe_grid_graph.gpkg")
    ap.add_argument("--out", type=Path, default=REPO / "webmap" / "osm_lifecycle_public.geojson")
    ap.add_argument("--min-kv", type=float, default=50.0, help="drop lines below this voltage when stated")
    args = ap.parse_args()

    elements: dict[str, dict] = {}
    for f in sorted(args.harvest_dir.glob("*.ndjson")):
        for line in open(f):
            if not line.strip():
                continue
            el = json.loads(line)
            elements.setdefault(f"{el['type']}/{el['id']}", el)
    print(f"{len(elements)} distinct lifecycle elements")
    # a way that is a member of a harvested relation is drawn once, by the relation
    member_ways = set()
    for el in elements.values():
        if el["type"] == "relation":
            for m in el.get("members") or []:
                if m.get("type") == "way":
                    member_ways.add(f"way/{m.get('ref')}")
    stations = load_stations(args.graph)
    print(f"{len(stations)} stations with a country for the nearest-station country rule")

    feats, dropped_kv, dropped_geom, in_graph = [], 0, 0, 0
    for oid, el in elements.items():
        if oid in member_ways:
            continue
        tags = el.get("tags") or {}
        # an element that also carries power=line/cable is in the v23 graph
        # already (flagged under_construction there); drawing it again here
        # would double it
        if tags.get("power") in ("line", "cable", "minor_line"):
            in_graph += 1
            continue
        if el["type"] == "way":
            coords = way_coords(el)
            if len(coords) < 2:
                dropped_geom += 1
                continue
            geom = {"type": "LineString", "coordinates": coords}
            allc = coords
        else:
            parts = relation_parts(el)
            if not parts:
                dropped_geom += 1
                continue
            geom = {"type": "MultiLineString", "coordinates": parts}
            allc = [c for p in parts for c in p]
        kv = voltage_kv(tags)
        if kv is not None and kv < args.min_kv:
            dropped_kv += 1
            continue
        state, kind = lifecycle_of(tags)
        km = sum(line_km(p) for p in geom["coordinates"]) if geom["type"] == "MultiLineString" else line_km(coords)
        year, year_basis = delivery_year(tags, state)
        props = {
            "fid": oid,
            "osm_url": f"https://www.openstreetmap.org/{oid}",
            "lifecycle": state,
            "kind": kind,
            "voltage_kv": kv,
            "voltage_verbatim": tags.get("voltage") or tags.get("proposed:voltage") or tags.get("construction:voltage") or None,
            "name": tags.get("name") or tags.get("proposed:name") or None,
            "ref": tags.get("ref") or None,
            "operator": tags.get("operator") or None,
            "cables": tags.get("cables") or tags.get("proposed:cables") or None,
            "circuits": tags.get("circuits") or None,
            "frequency": tags.get("frequency") or None,
            "location": tags.get("location") or None,
            "start_date": tags.get("start_date") or tags.get("opening_date") or tags.get("proposed:start_date") or tags.get("construction:start_date") or None,
            "service_year_min": year,
            "year_basis": year_basis,
            "note": tags.get("note") or tags.get("description") or None,
            "website": tags.get("website") or tags.get("source:url") or None,
            "countries": nearest_country(stations, [allc[0], allc[-1]]) if stations else "",
            "countries_source": "inferred:nearest v23 station within 60 km of each end" if stations else "unknown",
            "length_km": round(km, 1),
            "source": "sourced:OpenStreetMap lifecycle tags (proposed:power / construction:power / planned:power), ODbL 1.0",
            "layer_status": "context only: not in the v23 graph and not modelled; suggest it for the core model from this popup",
        }
        # no top-level string id: vector tiles keep numeric ids only, so the
        # OSM id travels as the fid property instead
        feats.append({"type": "Feature", "properties": {k: v for k, v in props.items() if v is not None},
                      "geometry": geom})
    out = {"type": "FeatureCollection", "name": "osm_lifecycle_public",
           "note": ("OpenStreetMap power lines and cables tagged as proposed, under construction or planned, "
                    "harvested via Overpass. Context only: the v23 topology harvest asks for power=line/cable, "
                    "so lifecycle-prefixed elements never enter the graph or the flow model. © OpenStreetMap "
                    "contributors, ODbL 1.0."),
           "features": feats}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False))
    by_state = {}
    sourced_years = sum(1 for f in feats if str(f["properties"].get("year_basis", "")).startswith("sourced:"))
    for f in feats:
        by_state[f["properties"]["lifecycle"]] = by_state.get(f["properties"]["lifecycle"], 0) + 1
    print(f"delivery years: {sourced_years} sourced from OSM tags, {len(feats) - sourced_years} defaulted by state (flagged)")
    print(f"wrote {args.out} : {len(feats)} features {by_state}; dropped {dropped_kv} below {args.min_kv:.0f} kV, "
          f"{dropped_geom} without geometry; {in_graph} already in the v23 graph (power=line/cable); "
          f"{len(member_ways)} member ways folded into relations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
