#!/usr/bin/env python3
"""Per-country comparison harness: authoritative TSO/state grid geometry vs the
v23 OSM-built layers. Comparison only - it never modifies the dataset.

Metrics per (country, authoritative source):
  1. Route-km by voltage class, authoritative vs OSM (50 Hz; OSM in-service and
     under-construction reported separately). Lengths are geodesic on drawn
     geometry on BOTH sides, so they are like-for-like (the shipped
     length_conductor_m is conductor length and is NOT used here).
  2. Two-way spatial coverage: fraction of each side's length lying within
     100 m / 250 m of the other side (any voltage, and voltage-class-matched).
     Buffering in EPSG:3035; identical projection both sides so distortion cancels.
  3. Substation matching: authoritative sites vs OSM stations (node_type=
     'substation', deduped by station_id) within 250 m / 500 m; voltage
     agreement on matched pairs where both sides carry a voltage.

Verdict is NOT computed automatically into the dataset - the harness emits the
numbers plus a suggested verdict for Duncan to review:
  fuse / partial / keep-osm / blocked-licence / metadata-only
"""
import json
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
from pyproj import Geod
from shapely import wkb as shapely_wkb

GRAPH = "/root/work/v22_test/europe_grid_graph.gpkg"   # line geometry (v22 == v23 lines)
CACHE = Path("/root/work/compare/osm_cache")
OUTD = Path("/root/work/compare/out")
GEOD = Geod(ellps="WGS84")
METRIC_CRS = "EPSG:3035"   # ETRS89-LAEA: same distortion both sides, differences cancel

# ---------------------------------------------------------------- OSM side ---

def _gpkg_geom(blob):
    """GeoPackage binary -> shapely (skip GP header)."""
    if blob is None:
        return None
    flags = blob[3]
    env = (flags >> 1) & 7
    hdr = 8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[env]
    return shapely_wkb.loads(bytes(blob[hdr:]))


def load_osm_country(cc: str, refresh: bool = False):
    """Return (lines_gdf, sites_gdf) for one ISO code, from parquet cache."""
    CACHE.mkdir(parents=True, exist_ok=True)
    lf, sf = CACHE / f"{cc}_lines.parquet", CACHE / f"{cc}_sites.parquet"
    if lf.exists() and sf.exists() and not refresh:
        return gpd.read_parquet(lf), gpd.read_parquet(sf)

    g = sqlite3.connect(f"file:{GRAPH}?mode=ro", uri=True)
    g.row_factory = sqlite3.Row
    like = f"%{cc}%"
    lrows, geoms = [], []
    for r in g.execute(
        "SELECT line_id, geom, voltage_kv, n_circuits, frequency_hz, "
        "under_construction, countries, line_label, operator "
        "FROM ac_line_all WHERE countries LIKE ?", (like,)):
        toks = (r["countries"] or "").split(";")
        if cc not in toks:            # LIKE '%IE%' would catch nothing wrong, but e.g. 'SI' in 'SI;IT' fine; guard exact-token
            continue
        geoms.append(_gpkg_geom(r["geom"]))
        lrows.append({k: r[k] for k in r.keys() if k != "geom"})
    lines = gpd.GeoDataFrame(lrows, geometry=geoms, crs="EPSG:4326")
    lines["frequency_hz"] = lines.get("frequency_hz", pd.Series(dtype=float)).fillna(50.0)
    lines = lines[lines.frequency_hz == 50.0].reset_index(drop=True)   # public grid only
    lines["geod_km"] = [geod_len_km(geom) for geom in lines.geometry]

    srows, sgeoms = [], []
    for r in g.execute(
        "SELECT station_id, bus_id, geom, node_type, voltage_kv, station_name, "
        "operator, countries, frequency_hz FROM site_all "
        "WHERE node_type='substation' AND countries LIKE ?", (like,)):
        toks = (r["countries"] or "").split(";")
        if cc not in toks:
            continue
        sgeoms.append(_gpkg_geom(r["geom"]))
        srows.append({k: r[k] for k in r.keys() if k != "geom"})
    sites = gpd.GeoDataFrame(srows, geometry=sgeoms, crs="EPSG:4326")
    if len(sites):
        sites["frequency_hz"] = sites.frequency_hz.fillna(50.0)
        sites = sites[sites.frequency_hz == 50.0]
        # bus -> station: keep one row per station, max voltage, centroid of buses
        sites["geometry"] = sites.geometry.centroid
        agg = sites.sort_values("voltage_kv", ascending=False).groupby("station_id").first()
        sites = gpd.GeoDataFrame(agg.reset_index(), geometry="geometry", crs="EPSG:4326")
    g.close()
    lines.to_parquet(lf)
    sites.to_parquet(sf)
    return lines, sites


def geod_len_km(geom):
    if geom is None or geom.is_empty:
        return 0.0
    total = 0.0
    parts = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
    for p in parts:
        total += GEOD.geometry_length(p)
    return total / 1000.0

# --------------------------------------------------------- voltage classes ---

def volt_class(v):
    """Nominal class key. Two voltages are the same class when close enough
    that no European network operates them as distinct levels (225~220 handled
    by exact values on both sides; the class key is the rounded value itself)."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return int(round(float(v)))


def classes_match(a, b):
    if a is None or b is None:
        return False
    return abs(a - b) <= max(10.0, 0.08 * max(a, b))

# ---------------------------------------------------------------- metrics ---

def route_km_by_class(gdf, vcol="voltage_kv", lcol="geod_km"):
    out = {}
    for v, s in gdf.groupby(gdf[vcol].map(volt_class))[lcol].sum().items():
        if v is not None and s > 0.05:
            out[int(v)] = round(float(s), 1)
    return dict(sorted(out.items()))


def coverage(src: gpd.GeoDataFrame, tgt: gpd.GeoDataFrame, buf_m: float,
             src_v="voltage_kv", tgt_v="voltage_kv", match_voltage=False):
    """Fraction of src length within buf_m of tgt (projected EPSG:3035).
    match_voltage=True restricts the target to lines whose class matches each
    src line's class."""
    if not len(src) or not len(tgt):
        return 0.0
    s = src.to_crs(METRIC_CRS)
    t = tgt.to_crs(METRIC_CRS)
    total = s.geometry.length.sum()
    if total == 0:
        return 0.0
    covered = 0.0
    if match_voltage:
        t_classes = t[tgt_v].map(volt_class)
        for sc in sorted(set(s[src_v].map(volt_class).dropna())):
            s_sub = s[s[src_v].map(volt_class) == sc]
            t_sub = t[[classes_match(sc, tc) for tc in t_classes]]
            covered += _covered_len(s_sub, t_sub, buf_m)
        # src rows with no voltage: compare against everything
        s_nov = s[s[src_v].map(volt_class).isna()]
        if len(s_nov):
            covered += _covered_len(s_nov, t, buf_m)
    else:
        covered = _covered_len(s, t, buf_m)
    return round(float(covered / total), 4)


def _covered_len(s, t, buf_m):
    if not len(s) or not len(t):
        return 0.0
    tu = t.geometry.union_all()
    buf = tu.buffer(buf_m)
    inter = s.geometry.intersection(buf)
    return float(inter.length.sum())


def substation_match(auth: gpd.GeoDataFrame, osm: gpd.GeoDataFrame,
                     auth_v="voltage_kv", radius_m=250.0):
    """Greedy nearest matching within radius. Returns counts + voltage agreement."""
    if not len(auth) or not len(osm):
        return {"auth_n": len(auth), "osm_n": len(osm), "matched": 0,
                "auth_only": len(auth), "osm_only": len(osm),
                "voltage_pairs": 0, "voltage_agree": 0}
    a = auth.to_crs(METRIC_CRS).copy()
    o = osm.to_crs(METRIC_CRS).copy()
    a["geometry"] = a.geometry.centroid
    a = a.reset_index(drop=True)
    right = o[["station_id", "voltage_kv", "geometry"]].rename(
        columns={"station_id": "_osm_sid", "voltage_kv": "osm_kv"})
    # avoid any column collision with the auth frame's own columns
    a_cols = [c for c in a.columns if c in ("_osm_sid", "osm_kv")]
    if a_cols:
        a = a.drop(columns=a_cols)
    joined = gpd.sjoin_nearest(a, right, how="left",
                               max_distance=radius_m, distance_col="d_m")
    # one auth row can join multiple equidistant osm rows; keep nearest, then
    # enforce one-to-one greedily by distance
    joined = joined.sort_values("d_m").reset_index()
    seen_a, seen_o, pairs = set(), set(), []
    for _, r in joined.iterrows():
        if pd.isna(r.get("d_m")):
            continue
        ai, oi = r["index"], r["_osm_sid"]
        if ai in seen_a or oi in seen_o:
            continue
        seen_a.add(ai); seen_o.add(oi)
        pairs.append(r)
    vp = va = 0
    for r in pairs:
        av, ov = volt_class(r.get(auth_v)), volt_class(r.get("osm_kv"))
        if av is not None and ov is not None:
            vp += 1
            if classes_match(av, ov):
                va += 1
    return {"auth_n": int(len(a)), "osm_n": int(len(o)), "matched": len(pairs),
            "auth_only": int(len(a) - len(pairs)), "osm_only": int(len(o) - len(pairs)),
            "voltage_pairs": vp, "voltage_agree": va,
            "median_offset_m": round(float(np.median([r["d_m"] for r in pairs])), 1) if pairs else None}

# ---------------------------------------------------------------- verdict ---

def suggest_verdict(m, licence_mixable):
    if licence_mixable == "no":
        return "blocked-licence", "geometry unusable for fusion under ODbL share-alike mixing rules; validation-only"
    if licence_mixable == "unclear":
        return "blocked-licence", "licence unresolved - treat as blocked until read; validation-only"
    a_in_o = m["coverage"]["auth_in_osm_250m"]
    o_in_a = m["coverage"]["osm_in_auth_250m"]
    floor_ok = m["auth_route_km_total"] > 0
    if not floor_ok:
        return "metadata-only", "no usable geometry acquired"
    if a_in_o >= 0.97 and o_in_a >= 0.97:
        return "keep-osm", "datasets agree; fusion adds licence complexity for no coverage gain - use authoritative for validation and attributes only"
    if a_in_o >= 0.90 and o_in_a < 0.95:
        return "fuse", "authoritative carries network OSM lacks; OSM geometry it confirms is sound"
    if a_in_o < 0.90 and o_in_a < 0.95:
        return "partial", "both sides carry unique network - fuse the authoritative-only extent, keep OSM elsewhere"
    if o_in_a >= 0.97 and a_in_o < 0.90:
        return "partial", "authoritative is a subset (likely voltage floor or TSO-only scope); useful for attribute enrichment on its extent"
    return "partial", "mixed coverage - inspect per-voltage table"

# ------------------------------------------------------------------- main ---

def compare_country(cc, auth_lines=None, auth_sites=None, source_meta=None,
                    auth_vcol="voltage_kv", label=""):
    """auth_lines/auth_sites: GeoDataFrames in EPSG:4326 with auth_vcol in kV
    (None where unknown). source_meta: dict from the survey row (licence etc.)."""
    osm_l, osm_s = load_osm_country(cc)
    osm_in = osm_l[osm_l.under_construction != 1]
    osm_uc = osm_l[osm_l.under_construction == 1]
    meta = source_meta or {}
    m = {
        "country": cc, "source": label or meta.get("dataset_name", ""),
        "publisher": meta.get("publisher", ""),
        "licence": meta.get("licence_name", ""),
        "licence_odbl_mixable": meta.get("licence_odbl_mixable", "unclear"),
        "auth_voltage_floor_kv": meta.get("voltage_floor_kv"),
        "osm_route_km_by_class_in_service": route_km_by_class(osm_in),
        "osm_route_km_under_construction": round(float(osm_uc.geod_km.sum()), 1),
    }
    if auth_lines is not None and len(auth_lines):
        al = auth_lines.copy()
        if "geod_km" not in al:
            al["geod_km"] = [geod_len_km(geom) for geom in al.geometry]
        m["auth_route_km_by_class"] = route_km_by_class(al, vcol=auth_vcol)
        m["auth_route_km_total"] = round(float(al.geod_km.sum()), 1)
        m["osm_route_km_total_in_service"] = round(float(osm_in.geod_km.sum()), 1)
        # scope-fair OSM slice: restrict to >= authoritative floor when known
        floor = meta.get("voltage_floor_kv")
        osm_scope = osm_in if not floor else osm_in[osm_in.voltage_kv >= float(floor) * 0.92]
        m["osm_route_km_at_or_above_auth_floor"] = round(float(osm_scope.geod_km.sum()), 1)
        m["coverage"] = {
            "auth_in_osm_100m": coverage(al, osm_scope, 100),
            "auth_in_osm_250m": coverage(al, osm_scope, 250),
            "osm_in_auth_100m": coverage(osm_scope, al, 100),
            "osm_in_auth_250m": coverage(osm_scope, al, 250),
            "auth_in_osm_250m_voltage_matched": coverage(al, osm_scope, 250, src_v=auth_vcol, match_voltage=True),
        }
    else:
        m["auth_route_km_total"] = 0.0
        m["coverage"] = {"auth_in_osm_250m": 0.0, "osm_in_auth_250m": 0.0}
    if auth_sites is not None and len(auth_sites):
        m["substations"] = substation_match(auth_sites, osm_s, auth_v=auth_vcol)
        m["substations_500m"] = substation_match(auth_sites, osm_s, auth_v=auth_vcol, radius_m=500)
    v, why = suggest_verdict(m, m["licence_odbl_mixable"])
    m["suggested_verdict"] = v
    m["verdict_rationale"] = why
    OUTD.mkdir(parents=True, exist_ok=True)
    slug = (label or "auth").lower().replace(" ", "_")[:40]
    with open(OUTD / f"{cc}_{slug}.json", "w") as f:
        json.dump(m, f, indent=1, default=str)
    return m


if __name__ == "__main__":
    # smoke: build cache for one country and print its OSM-side numbers
    cc = sys.argv[1] if len(sys.argv) > 1 else "LU"
    l, s = load_osm_country(cc, refresh="--refresh" in sys.argv)
    print(cc, "lines:", len(l), "route-km:", round(l.geod_km.sum(), 1),
          "| stations:", len(s))
    print("by class:", route_km_by_class(l[l.under_construction != 1]))
