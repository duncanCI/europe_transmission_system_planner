#!/usr/bin/env python3
"""Stage 3 - validation and diagnostics.

Runs the four diagnostics that actually found defects in the reference build
(dataset build record, "Reproducing and debugging"), plus component statistics,
a length-retention report and the summary metrics table the README quotes.

The four diagnostics, and what each one caught:

  1. Per-element internal-fragment count. More than ~20 tower-length fragments
     from one OSM element means the geometry was fused or self-overlapped
     upstream. This surfaced the fold-back trap (pitfall 25).
  2. Cross-component same-voltage bus pairs within 25 m. MUST BE ZERO. Above
     zero means a gate is refusing a real connection (pitfall 21).
  3. Distance from each internal segment's ends to its site polygon. An end well
     outside a polygon is network being deleted, not a switchyard jumper. This
     surfaced the Ecrainville bug (pitfall 26).
  4. Multi-polygon site extent, plus connectors over 400 m. A site wider than
     ~300 m is usually two substations fused, and the long connector is the
     symptom. This surfaced the Levallois/Perret bug (pitfall 27).

Usage:
    python 03_validate.py --config config_europe.yaml
    python 03_validate.py --config config_europe.yaml --out-dir out --json report.json
Exit code 0 when every hard check passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, log  # noqa: E402

# Thresholds, all from the documented diagnostics.
FRAGMENT_FLAG_COUNT = 20        # diagnostic 1 - pitfall 13
BUS_PAIR_TOL_M = 25.0           # diagnostic 2 - pitfall 21, must be 0
INTERNAL_END_FLAG_M = 50.0      # diagnostic 3 - FREE_END_MIN, pitfall 26
SITE_EXTENT_FLAG_M = 300.0      # diagnostic 4 - pitfall 27
LONG_CONNECTOR_FLAG_M = 400.0   # diagnostic 4 - pitfall 27 ("connectors over 400 m")
EARTH_R_M = 6371.0088 * 1000.0


def hav(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_R_M * math.asin(min(1.0, math.sqrt(a)))


# --------------------------------------------------------------------------- #
# GeoPackage reading without geopandas, so validation stays cheap on a big file
# --------------------------------------------------------------------------- #

def gpkg_wkb(blob: bytes) -> bytes:
    """Strip the GeoPackage binary header to leave plain WKB."""
    flags = blob[3]
    env = (flags >> 1) & 7
    return blob[8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[env]:]


def layers(con: sqlite3.Connection, kind: str = "features") -> List[str]:
    return [r[0] for r in con.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type=? ORDER BY table_name", (kind,))]


def line_layers(con: sqlite3.Connection) -> List[str]:
    return [l for l in layers(con)
            if l.startswith("line_") and l != "line_internal_to_station"]


# --------------------------------------------------------------------------- #
# diagnostics
# --------------------------------------------------------------------------- #

def diagnostic_1_fragments(topo: sqlite3.Connection) -> Dict[str, Any]:
    """Per-element fragment counts, network and internal (pitfall 13, 25)."""
    internal = Counter()
    for (oid,) in topo.execute("SELECT osm_id FROM line_internal_to_station"):
        internal[oid] += 1
    network = Counter()
    for lyr in line_layers(topo):
        for (oid,) in topo.execute(f"SELECT osm_id FROM {lyr}"):
            network[oid] += 1
    worst_i = internal.most_common(5)
    worst_n = network.most_common(5)
    return {
        "elements_over_20_internal_fragments":
            sum(1 for v in internal.values() if v > FRAGMENT_FLAG_COUNT),
        "elements_over_20_network_spans":
            sum(1 for v in network.values() if v > FRAGMENT_FLAG_COUNT),
        "worst_internal": worst_i,
        "worst_network": worst_n,
    }


def diagnostic_2_bus_pairs(graph: sqlite3.Connection) -> Dict[str, Any]:
    """Cross-component same-voltage bus pairs within 25 m. Must be zero.

    A pair this close in two different components is a connection the build
    refused: 848 of them were the symptom of the angle test running before the
    end-to-end test (pitfall 21).
    """
    rows = []
    for bus_id, kv, hz, comp, blob in graph.execute(
            "SELECT bus_id, voltage_kv, frequency_hz, component, geom FROM site_all"):
        from shapely import wkb
        p = wkb.loads(gpkg_wkb(bytes(blob)))
        rows.append((bus_id, kv, hz or 50.0, comp, p.x, p.y))
    # grid-bucket by voltage+frequency so this stays linear, not quadratic
    deg = BUS_PAIR_TOL_M / 111_320.0
    cell = max(deg, 1e-6)
    buckets: Dict[Tuple, List] = defaultdict(list)
    for r in rows:
        buckets[(r[1], r[2], int(r[4] / cell), int(r[5] / cell))].append(r)
    bad: List[Tuple[str, str, float]] = []
    for (kv, hz, cx, cy), items in buckets.items():
        near = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                near.extend(buckets.get((kv, hz, cx + dx, cy + dy), ()))
        for a in items:
            for b in near:
                if a[0] >= b[0] or a[3] == b[3]:
                    continue
                d = hav(a[4], a[5], b[4], b[5])
                if d <= BUS_PAIR_TOL_M:
                    bad.append((a[0], b[0], round(d, 1)))
    return {"cross_component_same_voltage_pairs_within_25m": len(bad),
            "examples": sorted(bad)[:10]}


def diagnostic_3_internal_ends(topo: sqlite3.Connection) -> Dict[str, Any]:
    """How far each internal segment's ends sit from any site polygon.

    An internal segment is meant to be conductor inside a switchyard. An end
    tens or hundreds of metres outside every polygon means network was deleted
    into this layer, which is what the Ecrainville rules fixed (pitfall 26).
    """
    from shapely import wkb
    from shapely.geometry import Point
    from shapely.ops import nearest_points
    from shapely.strtree import STRtree
    polys = []
    for (blob,) in topo.execute("SELECT geom FROM station_cluster"):
        polys.append(wkb.loads(gpkg_wkb(bytes(blob))))
    if not polys:
        return {"internal_segments": 0, "note": "no station_cluster layer"}
    tree = STRtree(polys)
    dists: List[float] = []
    for (blob,) in topo.execute("SELECT geom FROM line_internal_to_station"):
        g = wkb.loads(gpkg_wkb(bytes(blob)))
        cs = list(g.coords) if g.geom_type == "LineString" else []
        if not cs:
            continue
        for xy in (cs[0], cs[-1]):
            p = Point(xy)
            near = polys[int(tree.nearest(p))]
            if near.covers(p):
                dists.append(0.0)
                continue
            # nearest_points handles Polygon and MultiPolygon alike; the site
            # geometry is a MultiPolygon wherever a site has several compounds.
            _a, bpt = nearest_points(p, near)
            dists.append(hav(p.x, p.y, bpt.x, bpt.y))
    dists.sort()
    n = len(dists)
    return {
        "internal_segment_ends": n,
        "ends_beyond_50m_from_any_site": sum(1 for d in dists if d > INTERNAL_END_FLAG_M),
        "median_m": round(dists[n // 2], 1) if n else None,
        "p95_m": round(dists[int(n * 0.95)], 1) if n else None,
        "max_m": round(dists[-1], 1) if n else None,
    }


def diagnostic_4_site_extent(topo: sqlite3.Connection) -> Dict[str, Any]:
    """Multi-polygon site extent and long connectors (pitfall 27)."""
    from shapely import wkb
    wide = 0
    over_1km = 0
    extents: List[float] = []
    for nsub, blob in topo.execute(
            "SELECT n_sub_polygons, geom FROM station_cluster WHERE n_sub_polygons > 1"):
        g = wkb.loads(gpkg_wkb(bytes(blob)))
        minx, miny, maxx, maxy = g.bounds
        ext = hav(minx, miny, maxx, maxy)
        extents.append(ext)
        if ext > SITE_EXTENT_FLAG_M:
            wide += 1
        if ext > 1000.0:
            over_1km += 1
    conn_400 = conn_1km = 0
    for lyr in line_layers(topo):
        for c0, c1 in topo.execute(f"SELECT connector0_m, connector1_m FROM {lyr}"):
            for c in (c0 or 0.0, c1 or 0.0):
                if c > LONG_CONNECTOR_FLAG_M:
                    conn_400 += 1
                if c > 1000.0:
                    conn_1km += 1
    extents.sort()
    return {
        "multi_polygon_sites": len(extents),
        "multi_polygon_sites_wider_than_300m": wide,
        "multi_polygon_sites_wider_than_1km": over_1km,
        "site_extent_p99_m": round(extents[int(len(extents) * 0.99)], 1) if extents else None,
        "connectors_over_400m": conn_400,
        "connectors_over_1km": conn_1km,
    }


# --------------------------------------------------------------------------- #
# stats and summary
# --------------------------------------------------------------------------- #

def component_stats(graph: sqlite3.Connection) -> Dict[str, Any]:
    """Route-km per component, which is how connectivity is quoted (README s2:
    counting nodes weights a 200 m spur the same as the 400 kV backbone)."""
    km: Dict[int, float] = defaultdict(float)
    km220: Dict[int, float] = defaultdict(float)
    total = total220 = 0.0
    for comp, kv, L in graph.execute(
            "SELECT component, voltage_kv, length_conductor_m FROM ac_line_all"):
        L = (L or 0.0) / 1000.0
        km[comp] += L
        total += L
        if kv and kv >= 220:
            km220[comp] += L
            total220 += L
    buses = Counter(r[0] for r in graph.execute("SELECT component FROM site_all"))
    top = sorted(km.items(), key=lambda kv_: -kv_[1])[:5]
    return {
        "components": len(buses),
        "route_km": round(total, 1),
        "route_km_largest_component_pct":
            round(100.0 * max(km.values()) / total, 2) if total else None,
        "ge220kv_route_km": round(total220, 1),
        "ge220kv_in_largest_component_pct":
            round(100.0 * km220.get(top[0][0], 0.0) / total220, 2) if total220 else None,
        "top5_components_route_km": [(c, round(v, 1)) for c, v in top],
        "buses": sum(buses.values()),
    }


def length_report(topo: sqlite3.Connection, graph: sqlite3.Connection) -> Dict[str, Any]:
    """Length retention: drawn geometry against the stored decomposition.

    Every span's geometry is connector0 + conductor + connector1, so the
    haversine length of the drawn line must equal the three stored numbers. A
    mismatch means a rebuild changed geometry without updating the fields - the
    silent-loss class that cost 60,000 route-km once (pitfall 16).
    """
    from shapely import wkb
    worst = 0.0
    bad = 0
    n = 0
    cond_km = conn_km = 0.0
    for L, c0, c1, blob in graph.execute(
            "SELECT length_conductor_m, connector0_m, connector1_m, geom FROM ac_line_all"):
        g = wkb.loads(gpkg_wkb(bytes(blob)))
        cs = list(g.coords)
        drawn = sum(hav(cs[i][0], cs[i][1], cs[i + 1][0], cs[i + 1][1])
                    for i in range(len(cs) - 1))
        stored = (L or 0.0) + (c0 or 0.0) + (c1 or 0.0)
        n += 1
        cond_km += (L or 0.0) / 1000.0
        conn_km += ((c0 or 0.0) + (c1 or 0.0)) / 1000.0
        if stored > 0:
            rel = abs(drawn - stored) / stored
            worst = max(worst, rel)
            if rel > 0.001:
                bad += 1
    internal_km = 0.0
    for (blob,) in topo.execute("SELECT geom FROM line_internal_to_station"):
        g = wkb.loads(gpkg_wkb(bytes(blob)))
        cs = list(g.coords) if g.geom_type == "LineString" else []
        internal_km += sum(hav(cs[i][0], cs[i][1], cs[i + 1][0], cs[i + 1][1])
                           for i in range(len(cs) - 1)) / 1000.0
    return {
        "spans_checked": n,
        "spans_geometry_vs_fields_mismatch_over_0p1pct": bad,
        "worst_relative_mismatch": round(worst, 6),
        "conductor_km": round(cond_km, 1),
        "connector_km": round(conn_km, 1),
        "internal_to_station_km": round(internal_km, 1),
    }


def integrity(topo: sqlite3.Connection, graph: sqlite3.Connection) -> Dict[str, Any]:
    """The zero-checks the README quotes: no unresolved bus references, no
    self-loops, no null or invalid geometries."""
    buses = {r[0] for r in graph.execute("SELECT bus_id FROM site_all")}
    unresolved = self_loops = null_geom = 0
    for b0, b1, blob in graph.execute("SELECT bus0, bus1, geom FROM ac_line_all"):
        if b0 not in buses or b1 not in buses:
            unresolved += 1
        if b0 == b1:
            self_loops += 1
        if blob is None:
            null_geom += 1
    for lyr in layers(topo):
        null_geom += next(topo.execute(f"SELECT count(*) FROM {lyr} WHERE geom IS NULL"))[0]
    tr_missing = next(topo.execute(
        "SELECT count(*) FROM transformer WHERE s_nom_mva IS NULL OR x_pu IS NULL "
        "OR r_pu IS NULL"))[0] if "transformer" in layers(topo) else 0
    zero_imp = next(graph.execute(
        "SELECT count(*) FROM ac_line_all WHERE r_ohm <= 0 OR x_ohm <= 0 "
        "OR s_nom_mva <= 0"))[0]
    return {"unresolved_bus_references": unresolved, "self_loops": self_loops,
            "null_geometries": null_geom, "transformers_missing_parameters": tr_missing,
            "lines_with_nonpositive_parameters": zero_imp}


def summary_table(topo: sqlite3.Connection, graph: sqlite3.Connection,
                  comp: Dict[str, Any], lengths: Dict[str, Any]) -> Dict[str, Any]:
    """The metrics table the README quotes in section 2."""
    def one(sql: str) -> int:
        return next(graph.execute(sql) if "ac_line_all" in sql or "site_all" in sql
                    else topo.execute(sql))[0]
    circuit_km = next(graph.execute(
        "SELECT sum(length_conductor_m * n_circuits)/1000.0 FROM ac_line_all"))[0] or 0.0
    subs = one("SELECT count(*) FROM site_all WHERE node_type='substation'")
    junc = one("SELECT count(*) FROM site_all WHERE node_type='junction'")
    traction = [l for l in line_layers(topo) if "Hz" in l]
    traction_km = 0.0
    for l in traction:
        traction_km += (next(topo.execute(
            f"SELECT sum(length_conductor_m)/1000.0 FROM {l}"))[0] or 0.0)
    return {
        "total_route_km_network": comp["route_km"],
        "total_circuit_km": round(circuit_km, 1),
        "in_substation_conductor_km": lengths["internal_to_station_km"],
        "ac_spans_network": one("SELECT count(*) FROM ac_line_all"),
        "in_substation_segments": one("SELECT count(*) FROM line_internal_to_station"),
        "buses": comp["buses"],
        "substation_buses": subs,
        "junction_buses": junc,
        "transformers": one("SELECT count(*) FROM transformer")
        if "transformer" in layers(topo) else 0,
        "dc_links": one("SELECT count(*) FROM dc_link") if "dc_link" in layers(topo) else 0,
        "connected_components": comp["components"],
        "route_km_in_largest_component_pct": comp["route_km_largest_component_pct"],
        "ge220kv_route_km_in_largest_component_pct": comp["ge220kv_in_largest_component_pct"],
        "traction_route_km": round(traction_km, 1),
        "layers": len(layers(topo)) + len(layers(topo, "attributes")),
    }


def voltage_table(topo: sqlite3.Connection, benchmark: Optional[str]) -> Dict[str, Any]:
    """Route-km by voltage, compared against a published benchmark CSV if the
    config supplies one (README s3: the >=220 kV comparison is the acceptance
    test, on `length_conductor_m`, which excludes synthetic connectors)."""
    km: Dict[int, float] = defaultdict(float)
    for lyr in line_layers(topo):
        if "Hz" in lyr:
            continue                        # traction is not in the published comparison
        for kv, L in topo.execute(f"SELECT voltage_kv, length_conductor_m FROM {lyr}"):
            km[int(kv)] += (L or 0.0) / 1000.0
    out: Dict[str, Any] = {"route_km_by_kv": {k: round(v, 1) for k, v in sorted(km.items())}}
    if not benchmark:
        return out
    if not os.path.exists(benchmark):
        out["benchmark_error"] = f"missing {benchmark}"
        return out
    import csv
    rows = []
    tb = tp = 0.0
    with open(benchmark, newline="", encoding="utf-8") as fh:
        # skip comment lines so a benchmark file can carry its own provenance and
        # its pass criteria in-band (DictReader would otherwise read the first
        # comment as the header row)
        lines = [ln for ln in fh if not ln.lstrip().startswith("#") and ln.strip()]
        for row in csv.DictReader(lines):
            kv = int(float(row["voltage_kv"]))
            pub = float(row["published_km"])
            mine = km.get(kv, 0.0)
            tb += mine
            tp += pub
            rows.append({"kv": kv, "build_km": round(mine, 1), "published_km": pub,
                         "delta_pct": round(100.0 * (mine - pub) / pub, 1) if pub else None})
    out["benchmark"] = rows
    out["benchmark_total"] = {"build_km": round(tb, 1), "published_km": round(tp, 1),
                              "delta_pct": round(100.0 * (tb - tp) / tp, 1) if tp else None}
    return out


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--out-dir")
    ap.add_argument("--json", help="write the report here as well as to stdout")
    args = ap.parse_args()

    cfg = load_config(args.config)
    out_dir = args.out_dir or cfg["out_dir"]
    region = cfg["region_name"]
    topo_path = os.path.join(out_dir, f"{region}_grid_topology.gpkg")
    graph_path = os.path.join(out_dir, f"{region}_grid_graph.gpkg")
    for p in (topo_path, graph_path):
        if not os.path.exists(p):
            raise SystemExit(f"missing {p} - run 02_build_topology.py first")
    topo = sqlite3.connect(topo_path)
    graph = sqlite3.connect(graph_path)

    log("diagnostics 1-4")
    report: Dict[str, Any] = {
        "diagnostic_1_fragmentation": diagnostic_1_fragments(topo),
        "diagnostic_2_cross_component_bus_pairs": diagnostic_2_bus_pairs(graph),
        "diagnostic_3_internal_segment_ends": diagnostic_3_internal_ends(topo),
        "diagnostic_4_site_extent_and_connectors": diagnostic_4_site_extent(topo),
    }
    log("component and length statistics")
    comp = component_stats(graph)
    lengths = length_report(topo, graph)
    report["components"] = comp
    report["length_retention"] = lengths
    report["integrity"] = integrity(topo, graph)
    report["summary"] = summary_table(topo, graph, comp, lengths)
    report["voltages"] = voltage_table(topo, cfg.get("benchmark_csv"))
    report["layers"] = {"features": layers(topo), "attributes": layers(topo, "attributes"),
                        "graph": layers(graph)}

    # Hard checks. These are the ones that must hold in any region.
    fails: List[str] = []
    if report["diagnostic_2_cross_component_bus_pairs"][
            "cross_component_same_voltage_pairs_within_25m"] != 0:
        fails.append("diagnostic 2: same-voltage bus pairs within 25 m in different components")
    if report["integrity"]["unresolved_bus_references"]:
        fails.append("integrity: unresolved bus references")
    if report["integrity"]["self_loops"]:
        fails.append("integrity: self-loops in ac_line_all")
    if report["integrity"]["null_geometries"]:
        fails.append("integrity: null geometries")
    if report["integrity"]["transformers_missing_parameters"]:
        fails.append("integrity: transformers without v23 parameters")
    if report["integrity"]["lines_with_nonpositive_parameters"]:
        fails.append("integrity: lines with non-positive r/x/s_nom")
    if lengths["spans_geometry_vs_fields_mismatch_over_0p1pct"]:
        fails.append("length retention: drawn geometry disagrees with the stored lengths")
    # Diagnostics 1, 3 and 4 are hard checks too - reporting them without ever
    # failing meant the three defect classes they were written to catch (fold-back
    # fragmentation, the Ecrainville deletion, the Levallois fusion) would ship
    # green. Limits are CALIBRATED against the accepted Europe v23 build, whose
    # figures are quoted below, because two of these quantities are legitimately
    # non-zero in a good dataset: failing at zero would reject the reference
    # itself. Distribution limits apply only once the sample is big enough to
    # mean anything; a small adversarial fixture is reported, not judged.
    d1 = report["diagnostic_1_fragmentation"]
    if d1["elements_over_20_network_spans"]:                 # v23 reference: 0
        fails.append(f"diagnostic 1: {d1['elements_over_20_network_spans']} elements produce "
                     f">{FRAGMENT_FLAG_COUNT} network spans (fused or self-overlapped geometry)")
    if d1["elements_over_20_internal_fragments"]:            # v23 reference: 0
        fails.append(f"diagnostic 1: {d1['elements_over_20_internal_fragments']} elements produce "
                     f">{FRAGMENT_FLAG_COUNT} internal fragments")
    d3 = report["diagnostic_3_internal_segment_ends"]
    # v23 reference: 225,846 ends, p95 20.3 m, 2.5% beyond 50 m. The shape of the
    # distribution is the signal - a systemic deletion into the internal layer
    # pushes p95 out, individual long tails do not.
    n_ends = d3.get("internal_segment_ends", d3.get("internal_segments", 0))
    if n_ends >= 1000 and (d3.get("p95_m") or 0) > INTERNAL_END_FLAG_M:
        fails.append(f"diagnostic 3: p95 internal-segment end distance {d3['p95_m']} m exceeds "
                     f"{INTERNAL_END_FLAG_M:.0f} m (v23 reference 20.3 m) - network is being "
                     "deleted into the internal layer")
    d4 = report["diagnostic_4_site_extent_and_connectors"]
    # v23 reference: 22 of 2,321 multi-polygon sites over 1 km (0.9%), 8 connectors
    # over 1 km of 91,094 spans (0.009%). Limits are ~2x and ~10x the reference.
    mp = d4["multi_polygon_sites"]
    # v23 reference 22/2,321 = 0.95%; pitfall 27 pre-fix 48/2,805 = 1.71%. The limit
    # is reference x 1.5 = 1.4%, which sits BELOW the historical defect magnitude, so
    # the Levallois/Perret regression fails the build instead of shipping green.
    if mp >= 100 and d4["multi_polygon_sites_wider_than_1km"] > 0.014 * mp:
        fails.append(f"diagnostic 4: {d4['multi_polygon_sites_wider_than_1km']} of {mp} "
                     "multi-polygon sites are wider than 1 km (>1.4%, v23 reference 0.95%, "
                     "pre-fix defect 1.71%) - substations are being fused")
    # The 300 m extent share is REPORTED, not hard-checked: measured on the accepted
    # v23 build it is 969/2,321 = 41.7% against 1,235/2,805 = 44.0% pre-fix (pitfall
    # 27). Those do not separate, so any limit between them would be knife-edge and
    # would fail honest builds. The 1 km share and the connector count do separate,
    # and carry the check.
    nspans = int(report["summary"].get("ac_spans_network") or 0)
    # v23 reference 8/91,094 = 0.009%; pitfall 27 pre-fix 44 = 0.048%. Limit 0.015%,
    # again below the historical defect magnitude.
    if nspans >= 5000 and d4["connectors_over_1km"] > 0.00015 * nspans:
        fails.append(f"diagnostic 4: {d4['connectors_over_1km']} connectors over 1 km on "
                     f"{nspans} spans (>0.015%, v23 reference 0.009%, pre-fix defect 0.048%) - "
                     "synthetic conductor is standing in for missing joins")
    report["hard_check_failures"] = fails

    print(json.dumps(report, indent=1, default=str))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1, default=str)
    if fails:
        log(f"FAIL: {len(fails)} hard checks failed")
        return 1
    log("all hard checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
