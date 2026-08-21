#!/usr/bin/env python3
"""End-to-end test: run stages 02 and 03 over the synthetic fixture and assert
the documented behaviour of every rule the fixture was built to exercise.

Run it either way:

    python tests/fixture_test.py          # standalone, prints PASS/FAIL per check
    pytest tests/fixture_test.py -q       # same checks as pytest cases

The build runs once and is cached for every check. Nothing here reaches the
network: the fixture is committed NDJSON, so stage 01 is not exercised beyond its
import (its query builder is unit-tested separately below).
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

EARTH_R_M = 6371.0088 * 1000.0
_BUILD: Optional[Dict[str, Any]] = None


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def hav(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_R_M * math.asin(min(1.0, math.sqrt(a)))


def gpkg_wkb(blob: bytes) -> bytes:
    flags = blob[3]
    env = (flags >> 1) & 7
    return blob[8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[env]:]


def build_once() -> Dict[str, Any]:
    """Regenerate the fixture, run stage 02 then stage 03, and open the results."""
    global _BUILD
    if _BUILD is not None:
        return _BUILD

    subprocess.run([sys.executable, os.path.join(HERE, "make_fixture.py")],
                   check=True, capture_output=True)
    tmp = tempfile.mkdtemp(prefix="gridfixture_")
    harvest = os.path.join(tmp, "harvest")
    out = os.path.join(tmp, "out")
    os.makedirs(harvest)
    shutil.copy(os.path.join(HERE, "fixture.ndjson"),
                os.path.join(harvest, "fixture__hv.ndjson"))

    cfg = os.path.join(HERE, "fixture_config.yaml")
    build = subprocess.run(
        [sys.executable, os.path.join(PKG, "02_build_topology.py"),
         "--config", cfg, "--harvest-dir", harvest, "--out-dir", out],
        capture_output=True, text=True)
    if build.returncode != 0:
        raise AssertionError(f"02_build_topology.py failed:\n{build.stderr[-4000:]}")

    report_path = os.path.join(out, "validate_report.json")
    val = subprocess.run(
        [sys.executable, os.path.join(PKG, "03_validate.py"),
         "--config", cfg, "--out-dir", out, "--json", report_path],
        capture_output=True, text=True)
    with open(report_path, "r", encoding="utf-8") as fh:
        report = json.load(fh)

    topo = sqlite3.connect(os.path.join(out, "fixture_grid_topology.gpkg"))
    graph = sqlite3.connect(os.path.join(out, "fixture_grid_graph.gpkg"))
    topo.row_factory = sqlite3.Row
    graph.row_factory = sqlite3.Row
    with open(os.path.join(out, "build_stats.json"), "r", encoding="utf-8") as fh:
        stats = json.load(fh)

    _BUILD = {"tmp": tmp, "out": out, "topo": topo, "graph": graph,
              "report": report, "validate_rc": val.returncode, "stats": stats,
              "build_log": build.stderr}
    return _BUILD


def lines(b: Dict[str, Any]) -> Dict[str, sqlite3.Row]:
    """Every network span, keyed by line_id, across all voltage layers."""
    out: Dict[str, sqlite3.Row] = {}
    for (lyr,) in b["topo"].execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type='features' "
            "AND table_name LIKE 'line_%' AND table_name != 'line_internal_to_station'"):
        for row in b["topo"].execute(f"SELECT *, '{lyr}' AS layer FROM {lyr}"):
            out[row["line_id"]] = row
    return out


def layer_names(con: sqlite3.Connection, kind: str = "features") -> List[str]:
    return sorted(r[0] for r in con.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type=?", (kind,)))


def geom_len(row: sqlite3.Row) -> float:
    from shapely import wkb
    g = wkb.loads(gpkg_wkb(bytes(row["geom"])))
    cs = list(g.coords)
    return sum(hav(cs[i][0], cs[i][1], cs[i + 1][0], cs[i + 1][1])
               for i in range(len(cs) - 1))


def expected_input_length_m() -> float:
    """Total conductor length the fixture presents to the build.

    Applies the two documented relation rules by hand: relation/301 merges and
    supersedes ways 303 and 304; relation/302 does not merge and is discarded in
    favour of ways 305 and 306. way/271 carries two voltages and therefore two
    records off one geometry (paper Tables 2-3). way/251 is DC and is not part of
    the AC totals.
    """
    superseded = {"way/303", "way/304"}
    dropped = {"relation/302"}
    dc = {"way/251"}
    substation_ids = {"way/101", "way/102", "way/103", "way/104", "way/105", "way/106"}
    multiplicity = {"way/271": 2}
    total = 0.0
    with open(os.path.join(HERE, "fixture.ndjson"), "r", encoding="utf-8") as fh:
        for line in fh:
            el = json.loads(line)
            oid = f"{el['type']}/{el['id']}"
            if oid in superseded or oid in dropped or oid in dc or oid in substation_ids:
                continue
            if el["type"] == "way":
                cs = el["geometry"]
            else:
                cs = [c for m in el["members"] for c in m.get("geometry", [])]
                cs = el["members"][0]["geometry"] + el["members"][1]["geometry"][1:]
            L = sum(hav(cs[i][0], cs[i][1], cs[i + 1][0], cs[i + 1][1])
                    for i in range(len(cs) - 1))
            total += L * multiplicity.get(oid, 1)
    return total


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #

def test_layer_set() -> None:
    """The documented layer set is present, and nothing unexpected is."""
    b = build_once()
    feats = set(layer_names(b["topo"]))
    required = {
        "line_110kV", "line_110kV_16_7Hz", "line_132kV", "line_220kV", "line_400kV",
        "line_internal_to_station", "site_132kV", "site_400kV", "junction_node",
        "dc_link", "transformer", "station_cluster", "substation_footprint",
    }
    missing = required - feats
    assert not missing, f"missing layers: {sorted(missing)}"
    unexpected = {l for l in feats if not (
        l.startswith("line_") or l.startswith("site_") or l in required)}
    assert not unexpected, f"unexpected layers: {sorted(unexpected)}"
    # the two non-spatial tables ship inside the GeoPackage, registered so that
    # ogrinfo and QGIS list them (README s13.1)
    attrs = set(layer_names(b["topo"], "attributes"))
    assert {"v23_typing_rule", "build_metadata"} <= attrs, attrs
    assert set(layer_names(b["graph"])) == {"ac_line_all", "site_all"}


def test_schema_field_lists() -> None:
    """Line and site layers carry exactly the documented fields, and the
    deliberately-absent ones stay absent (README s4)."""
    b = build_once()
    line_cols = [c[1] for c in b["topo"].execute("PRAGMA table_info('line_400kV')")]
    site_cols = [c[1] for c in b["topo"].execute("PRAGMA table_info('site_400kV')")]
    # fid + geom + the documented attribute fields
    assert line_cols[:2] == ["fid", "geom"], line_cols[:2]
    # Exact NAME lists, taken from the shipped v23 files. A count-only assertion let
    # a rename through (line_label_source -> label_src kept both suites green), and a
    # renamed column silently breaks every downstream consumer.
    SHIPPED_LINE_FIELDS = ['line_id', 'osm_id', 'contains', 'line_label', 'line_label_source', 'ref', 'operator', 'bus0', 'bus1', 'start_point', 'end_point', 'start_lat', 'start_lon', 'end_lat', 'end_lon', 'route_start_substation', 'route_end_substation', 'component', 'voltage_kv', 'n_circuits', 'circuits_source', 'line_type', 'i_nom_ka', 's_nom_mva', 'r_ohm', 'x_ohm', 'construction_type', 'construction_source', 'under_construction', 'length_conductor_m', 'connector0_m', 'connector1_m', 'countries', 'n_ways_merged', 'qa_flags', 'frequency_hz', 'frequency_source']
    SHIPPED_SITE_FIELDS = ['bus_id', 'station_id', 'node_type', 'voltage_kv', 'station_name', 'operator', 'countries', 'degree', 'n_lines', 'connected_line_ids', 'station_voltages_kv', 'n_sub_polygons', 'osm_substation_ids', 'component', 'frequency_hz', 'frequency_source']
    SHIPPED_SITE_ALL_FIELDS = ['bus_id', 'station_id', 'node_type', 'voltage_kv', 'station_name', 'operator', 'countries', 'degree', 'n_lines', 'connected_line_ids', 'station_voltages_kv', 'n_sub_polygons', 'osm_substation_ids', 'component', 'frequency_hz', 'frequency_source', 'severed_from', 'component_incl_dc']
    assert line_cols[2:] == SHIPPED_LINE_FIELDS, (
        f"line schema drift: extra {set(line_cols[2:]) - set(SHIPPED_LINE_FIELDS)} "
        f"missing {set(SHIPPED_LINE_FIELDS) - set(line_cols[2:])}")
    assert site_cols[2:] == SHIPPED_SITE_FIELDS, (
        f"site schema drift: extra {set(site_cols[2:]) - set(SHIPPED_SITE_FIELDS)} "
        f"missing {set(SHIPPED_SITE_FIELDS) - set(site_cols[2:])}")
    absent = {"voltage_v", "station0", "station1", "underground", "submarine",
              "length_m", "s_nom_n1_mva", "is_cross_border", "elem_id", "name",
              "cables", "wires", "internal_to_station"}
    assert not (absent & set(line_cols)), absent & set(line_cols)
    graph_cols = [c[1] for c in b["graph"].execute("PRAGMA table_info('site_all')")]
    assert graph_cols[2:] == SHIPPED_SITE_ALL_FIELDS, (
        f"site_all schema drift: extra {set(graph_cols[2:]) - set(SHIPPED_SITE_ALL_FIELDS)} "
        f"missing {set(SHIPPED_SITE_ALL_FIELDS) - set(graph_cols[2:])}")


def test_no_foldback_fragmentation() -> None:
    """Decision 4 / pitfall 25: the two circuits of the double-circuit line stay
    separate, and neither is an out-and-back conductor."""
    b = build_once()
    ls = lines(b)
    assert "way/201" in ls and "way/202" in ls, sorted(ls)
    for lid in ("way/201", "way/202"):
        L = ls[lid]["length_conductor_m"]
        assert 4700 < L < 5100, f"{lid} is {L:.0f} m, expected ~4.9 km"
    # both terminate at Bravo, and both start at the shared junction
    assert ls["way/201"]["bus1"] == ls["way/202"]["bus1"]
    assert ls["way/201"]["bus0"] == ls["way/202"]["bus0"]
    assert ls["way/201"]["end_point"] == "Bravo Substation"
    # the merger refused exactly the fold-back pair and accepted the head-on one
    assert b["stats"]["chain_refused_foldback"] == 1, b["stats"]["chain_refused_foldback"]
    # no element shredded into tower-length fragments (diagnostic 1)
    d1 = b["report"]["diagnostic_1_fragmentation"]
    assert d1["elements_over_20_network_spans"] == 0
    assert d1["elements_over_20_internal_fragments"] == 0
    worst = max(n for _oid, n in d1["worst_network"])
    assert worst <= 2, f"worst element produces {worst} spans"


def test_chain_merge_accepts_head_on() -> None:
    """The same 60 degree gate must still merge a genuine through-node: ways 211
    and 212 become one conductor, later split only by the real tee."""
    b = build_once()
    ls = lines(b)
    parts = [r for lid, r in ls.items() if r["osm_id"] == "way/211"]
    assert parts, "merged 220 kV chain missing"
    assert all(r["n_ways_merged"] == 2 for r in parts)
    assert all(set(r["contains"].split(";")) == {"way/211", "way/212"} for r in parts)
    total = sum(r["length_conductor_m"] for r in parts)
    assert 3700 < total < 3900, f"merged chain is {total:.0f} m, expected ~3.8 km"
    assert "way/212" not in ls, "the absorbed way should not ship as its own span"


def test_junction_tee_survives() -> None:
    """Pitfall 14 / decision 9: a perpendicular tap is accepted, splits the
    target, and the resulting junction keeps degree 3 rather than being dissolved."""
    b = build_once()
    ls = lines(b)
    assert "way/221" in ls
    shared = ls["way/221"]["bus1"]
    deg = next(b["graph"].execute(
        "SELECT degree, n_lines FROM site_all WHERE bus_id=?", (shared,)))
    assert deg["degree"] == 3, f"tee junction degree {deg['degree']}, expected 3"
    assert b["stats"]["snapped_ends"] >= 1
    assert b["stats"]["snap_rejected_parallel"] == 0


def test_length_retained() -> None:
    """Decision 14: no stage silently loses (or invents) conductor."""
    b = build_once()
    lr = b["report"]["length_retention"]
    kept = (lr["conductor_km"] + lr["internal_to_station_km"]) * 1000.0
    expected = expected_input_length_m()
    ratio = kept / expected
    assert 0.999 <= ratio <= 1.01, (
        f"retained {kept:.0f} m of {expected:.0f} m ({ratio:.4%}) - "
        "the end-to-end pass may add up to 150 m per join but nothing may be lost")
    # the drawn geometry must equal conductor + both connectors, every row
    assert lr["spans_geometry_vs_fields_mismatch_over_0p1pct"] == 0
    assert b["stats"]["elements_reverted_on_length_check"] == 0


def test_traction_separated() -> None:
    """README s12: 16.7 Hz traction is its own layer, its own buses, and never
    shares a bus or a transformer with the 50 Hz grid."""
    b = build_once()
    ls = lines(b)
    tr = {lid: r for lid, r in ls.items() if r["layer"].endswith("_16_7Hz")}
    assert set(tr) == {"way/241", "way/243"}, sorted(tr)
    assert all(abs(r["frequency_hz"] - 16.7) < 1e-9 for r in tr.values())
    assert tr["way/241"]["frequency_source"] == "osm_frequency_tag"
    assert tr["way/243"]["frequency_source"] == "operator_inferred"
    # the 50 Hz line on the same node stays at 50 Hz in its own layer
    assert ls["way/242"]["frequency_hz"] == 50.0
    assert ls["way/242"]["layer"] == "line_110kV"
    # the shared node carries two buses, and the traction one records the sever
    grid_bus = ls["way/242"]["bus0"]
    tract_bus = tr["way/241"]["bus0"]
    assert grid_bus != tract_bus
    row = next(b["graph"].execute(
        "SELECT severed_from, component FROM site_all WHERE bus_id=?", (tract_bus,)))
    assert row["severed_from"] == grid_bus, row["severed_from"]
    other = next(b["graph"].execute(
        "SELECT component FROM site_all WHERE bus_id=?", (grid_bus,)))
    assert row["component"] != other["component"], "traction must be its own sub-network"
    # no transformer joins two frequencies
    for t in b["topo"].execute("SELECT bus0, bus1 FROM transformer"):
        f0 = next(b["graph"].execute("SELECT frequency_hz FROM site_all WHERE bus_id=?",
                                     (t["bus0"],)))[0]
        f1 = next(b["graph"].execute("SELECT frequency_hz FROM site_all WHERE bus_id=?",
                                     (t["bus1"],)))[0]
        assert f0 == f1, "a transformer bridges two frequencies"


def test_connectors_stored_separately() -> None:
    """Pitfall 7: the connector is drawn but its length is stored separately, so
    length_conductor_m never includes synthetic geometry."""
    b = build_once()
    ls = lines(b)
    withconn = [r for r in ls.values() if (r["connector0_m"] or 0) > 0
                or (r["connector1_m"] or 0) > 0]
    assert withconn, "no connectors stored at all"
    for r in withconn:
        drawn = geom_len(r)
        stored = r["length_conductor_m"] + r["connector0_m"] + r["connector1_m"]
        assert abs(drawn - stored) < max(1.0, 0.001 * stored), (r["line_id"], drawn, stored)
    # the cable leaving Alpha has a connector from the fence to the bus point
    assert ls["way/231"]["connector0_m"] > 10.0
    assert ls["way/231"]["length_conductor_m"] > 400.0
    assert b["report"]["diagnostic_4_site_extent_and_connectors"]["connectors_over_1km"] == 0


def test_cable_overhead_transition() -> None:
    """README s4: the cable-to-overhead node is the sealing end, and the five-state
    construction_type with its source records which tag decided each."""
    b = build_once()
    ls = lines(b)
    assert ls["way/231"]["construction_type"] == "underground_cable"
    assert ls["way/231"]["construction_source"] == "osm_location_tag"
    assert ls["way/232"]["construction_type"] == "overhead_line"
    assert ls["way/232"]["construction_source"] == "osm_power_line"
    assert ls["way/231"]["bus1"] == ls["way/232"]["bus0"], "transition node not shared"
    assert ls["way/231"]["end_point"] == "junction"
    # the relation with no power tag of its own takes its type from its members
    assert ls["relation/301"]["construction_source"] == "derived_from_member_ways"


def test_relation_handling() -> None:
    """README s6.3: a relation that merges replaces its ways; one that does not is
    discarded in favour of them."""
    b = build_once()
    ls = lines(b)
    assert "relation/301" in ls
    assert 3900 < ls["relation/301"]["length_conductor_m"] < 4100
    assert "way/303" not in ls and "way/304" not in ls
    assert "relation/302" not in ls
    assert "way/305" in ls and "way/306" in ls


def test_end_to_end_join() -> None:
    """Decision 10: a 30 m head-on gap away from any substation is closed by
    moving both tips, so the two ways end up on one bus."""
    b = build_once()
    ls = lines(b)
    assert ls["way/311"]["bus1"] == ls["way/312"]["bus0"], "end-to-end join missing"
    assert b["stats"]["ee_moved"] == 1
    assert b["stats"]["ee_bridged"] == 0
    c311 = next(b["graph"].execute("SELECT component FROM site_all WHERE bus_id=?",
                                   (ls["way/311"]["bus0"],)))[0]
    c312 = next(b["graph"].execute("SELECT component FROM site_all WHERE bus_id=?",
                                   (ls["way/312"]["bus1"],)))[0]
    assert c311 == c312, "the joined ways should be one component"


def test_ecrainville_rules() -> None:
    """Decisions 7 and 8: conductors stopping short of the fence are retained, the
    shared point becomes a junction with no synthetic connector, and an approach
    conductor keeps its far end freed instead of being deleted."""
    b = build_once()
    ls = lines(b)
    for lid in ("way/321", "way/322", "way/323", "way/324"):
        assert lid in ls, f"{lid} was deleted from the network layers"
    q = ls["way/323"]["bus0"]
    assert ls["way/321"]["bus1"] == q and ls["way/322"]["bus1"] == q, "tee not shared"
    deg = next(b["graph"].execute("SELECT degree FROM site_all WHERE bus_id=?", (q,)))[0]
    assert deg == 3, f"Ecrainville junction degree {deg}, expected 3"
    assert ls["way/323"]["connector0_m"] == 0.0, "synthetic connector drawn at the tee"
    assert ls["way/323"]["end_point"] == "Echo Substation"
    assert 150 < ls["way/323"]["length_conductor_m"] < 170
    # the approach conductor keeps one end on the site and one freed
    assert ls["way/324"]["start_point"] == "Echo Substation"
    assert ls["way/324"]["end_point"] == "junction"
    assert "approach_conductor_end_freed" in ls["way/324"]["qa_flags"]
    assert b["stats"]["ends_diverted_to_junction"] == 3
    assert b["stats"]["approach_conductor_ends_freed"] == 1


def test_sites_not_over_fused() -> None:
    """Decisions 5 and 6: two compounds 120 m apart are one site; two substations
    520 m apart joined by a cable are not."""
    b = build_once()
    clusters = {r["station_name"]: r for r in
                b["topo"].execute("SELECT * FROM station_cluster")}
    assert len(clusters) == 5, sorted(clusters)
    charlie = clusters["Charlie Substation A"]
    assert charlie["n_sub_polygons"] == 2
    assert set(charlie["osm_substation_ids"].split(";")) == {"way/103", "way/104"}
    assert "Delta Substation" in clusters
    assert clusters["Delta Substation"]["n_sub_polygons"] == 1
    ls = lines(b)
    assert ls["way/341"]["bus0"] != ls["way/341"]["bus1"], "Charlie and Delta were fused"
    assert b["stats"]["site_conductor_merge_refused_geometry"] >= 1
    d4 = b["report"]["diagnostic_4_site_extent_and_connectors"]
    assert d4["multi_polygon_sites_wider_than_300m"] == 0


def test_internal_layer_and_self_loops() -> None:
    """Pitfalls 2 and 17: in-substation conductor is retained in its own layer and
    every self-loop leaves the network layers."""
    b = build_once()
    internal = list(b["topo"].execute("SELECT * FROM line_internal_to_station"))
    ids = {r["osm_id"] for r in internal}
    assert "way/325" in ids, "the busbar jumper inside Echo was dropped"
    assert "way/332" in ids, "the U-shaped jumper should be swept to the internal layer"
    assert b["report"]["integrity"]["self_loops"] == 0
    # the dissolve re-merged the target after the loops were swept (decision 12)
    ls = lines(b)
    target = [r for r in ls.values() if r["osm_id"] == "way/331"]
    assert len(target) == 1, f"way/331 shipped as {len(target)} spans, expected 1"
    assert 3900 < target[0]["length_conductor_m"] < 4100
    assert b["stats"]["elements_rebuilt"] >= 1


def test_electrical_parameters() -> None:
    """README s5: per-voltage standard types, r/x scaled by circuits, s_nom from
    sqrt(3) * U * I * n_circuits."""
    b = build_once()
    ls = lines(b)
    r = ls["way/201"]
    assert r["line_type"] == "Al/St 240/40 4-bundle 380.0"
    assert abs(r["i_nom_ka"] - 2.58) < 1e-9
    L_km = (r["length_conductor_m"] + r["connector0_m"] + r["connector1_m"]) / 1000.0
    assert abs(r["r_ohm"] - 0.03 * L_km) < 1e-6
    assert abs(r["x_ohm"] - 0.246 * L_km) < 1e-6
    assert abs(r["s_nom_mva"] - math.sqrt(3) * 400 * 2.58) < 1e-6
    # multi-value voltage: two records off one element, circuits from cables/3
    m = [x for x in ls.values() if x["osm_id"] == "way/271"]
    assert len(m) == 2 and {x["voltage_kv"] for x in m} == {400, 132}
    assert all(x["n_circuits"] == 2 for x in m)
    assert all(x["circuits_source"] == "derived_from_cables_tag" for x in m)
    # the 132 kV record must scale impedance down by the circuit count
    m132 = next(x for x in m if x["voltage_kv"] == 132)
    L132 = (m132["length_conductor_m"] + m132["connector0_m"] + m132["connector1_m"]) / 1000.0
    assert abs(m132["r_ohm"] - 0.1188 * L132 / 2) < 1e-6
    # under-construction is in the totals and flagged
    assert ls["way/261"]["under_construction"] == 1
    assert "under_construction" in ls["way/261"]["qa_flags"]


def test_transformer_typing_rule() -> None:
    """README s13.1: one transformer per adjacent voltage pair per site, banded
    parameters with their provenance label, and the second rating column."""
    b = build_once()
    rows = list(b["topo"].execute("SELECT * FROM transformer"))
    assert len(rows) == 1, f"{len(rows)} transformers, expected 1 (Alpha 132/400)"
    t = rows[0]
    assert t["transformer_id"].endswith("_132_400")
    assert t["inferred"] == "voltage_pair_at_site"
    assert abs(t["s_nom_mva"] - 500.0) < 1e-9      # band R2
    assert abs(t["x_pu"] - 0.122) < 1e-9
    assert abs(t["r_pu"] - 0.0025) < 1e-9
    assert t["parameters_source"].startswith("typing_rule_v23:R2")
    assert t["s_nom_pypsa_eur_mva"] and t["s_nom_pypsa_eur_mva"] > 0
    # The in-GeoPackage rule table must be the whole shipped table, not just the
    # bands: README s13.1 says the source citations and the s_nom/x_pu coupling
    # warning travel with the data, which is the ALT and NOTE rows.
    bands = [r[0] for r in b["topo"].execute("SELECT band FROM v23_typing_rule ORDER BY band")]
    assert bands == ["ALT", "NOTE", "R1", "R2", "R3", "R4", "R5", "R6"], bands
    cols = [r[1] for r in b["topo"].execute("PRAGMA table_info(v23_typing_rule)")]
    assert "source_url" in cols, cols
    urls = [r[0] for r in b["topo"].execute(
        "SELECT source_url FROM v23_typing_rule WHERE band LIKE 'R%'")]
    assert all(u and u.startswith("http") for u in urls), urls
    alt = b["topo"].execute("SELECT basis FROM v23_typing_rule WHERE band='ALT'").fetchone()[0]
    assert "per-unit on s_nom_mva" in alt, alt


def test_dc_link() -> None:
    """Pitfall 3 / README s13.2: converters attach to the nearest bus within
    10 km, and an unresearched rating stays unknown rather than being guessed."""
    b = build_once()
    rows = list(b["topo"].execute("SELECT * FROM dc_link"))
    assert len(rows) == 1
    d = rows[0]
    assert d["bus0"] and d["bus1"] and d["bus0"] != d["bus1"]
    assert d["frequency_hz"] == 0.0
    assert d["p_nom_mw"] is None, "no ratings CSV was supplied, so this must be null"
    assert d["status"] == "unknown" and d["p_nom_source"] == "unknown"


def test_validation_hard_checks() -> None:
    """Stage 03 must pass its own hard checks on the fixture."""
    b = build_once()
    assert b["report"]["hard_check_failures"] == [], b["report"]["hard_check_failures"]
    assert b["validate_rc"] == 0
    d2 = b["report"]["diagnostic_2_cross_component_bus_pairs"]
    assert d2["cross_component_same_voltage_pairs_within_25m"] == 0
    integ = b["report"]["integrity"]
    for k, v in integ.items():
        assert v == 0, f"{k} = {v}"


def test_pypsa_conventions() -> None:
    """The output must satisfy the conventions acid_test_pypsa.py checks: buses
    load with v_nom, lines with positive r/x/s_nom, transformers with per-unit
    parameters, the component column matching the passive-branch partition, and no
    sub-network mixing frequency."""
    b = build_once()
    try:
        import numpy as np
        import pypsa
        import scipy.sparse as sp
        from scipy.sparse.csgraph import connected_components
    except ImportError:                       # pypsa is optional for this test
        print("  (skipped: pypsa not installed)")
        return
    from shapely import wkb
    buses = list(b["graph"].execute(
        "SELECT bus_id, voltage_kv, frequency_hz, component, geom FROM site_all"))
    pts = [wkb.loads(gpkg_wkb(bytes(r["geom"]))) for r in buses]
    n = pypsa.Network()
    n.add("Carrier", ["AC", "DC"])
    n.add("Bus", [r["bus_id"] for r in buses], v_nom=[r["voltage_kv"] for r in buses],
          x=[p.x for p in pts], y=[p.y for p in pts], carrier="AC")
    ln = list(b["graph"].execute(
        "SELECT line_id, bus0, bus1, r_ohm, x_ohm, s_nom_mva FROM ac_line_all"))
    n.add("Line", [r["line_id"] for r in ln], bus0=[r["bus0"] for r in ln],
          bus1=[r["bus1"] for r in ln], r=[r["r_ohm"] for r in ln],
          x=[r["x_ohm"] for r in ln], s_nom=[r["s_nom_mva"] for r in ln], carrier="AC")
    tr = list(b["topo"].execute(
        "SELECT transformer_id, bus0, bus1, s_nom_mva, x_pu, r_pu FROM transformer"))
    assert not [r for r in tr if r["s_nom_mva"] is None or r["x_pu"] is None
                or r["r_pu"] is None], "transformer parameters missing"
    n.add("Transformer", [r["transformer_id"] for r in tr],
          bus0=[r["bus0"] for r in tr], bus1=[r["bus1"] for r in tr],
          s_nom=[r["s_nom_mva"] for r in tr], x=[r["x_pu"] for r in tr],
          r=[r["r_pu"] for r in tr], model="pi")
    n.consistency_check(strict=["unknown_buses", "unknown_carriers", "zero_impedances",
                                "zero_s_nom", "dtypes"])

    idx = {bid: i for i, bid in enumerate(n.buses.index)}
    rows = [idx[x] for x in list(n.lines.bus0) + list(n.transformers.bus0)]
    cols = [idx[x] for x in list(n.lines.bus1) + list(n.transformers.bus1)]
    A = sp.coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(idx), len(idx)))
    ncomp, labels = connected_components(A + A.T, directed=False)
    db = {r["bus_id"]: r["component"] for r in buses}
    mapping: Dict[int, int] = {}
    for bid, i in idx.items():
        c = db[bid]
        if c in mapping:
            assert mapping[c] == labels[i], "component column disagrees with the partition"
        else:
            mapping[c] = labels[i]
    assert len(mapping) == ncomp, f"db components {len(mapping)} vs scipy {ncomp}"
    freq = np.array([r["frequency_hz"] or 50.0 for r in buses])
    mixed = sum(1 for lab in range(ncomp) if len(set(freq[labels == lab])) > 1)
    assert mixed == 0, f"{mixed} sub-networks mix frequency"
    assert int((n.lines.bus0 == n.lines.bus1).sum()) == 0
    assert bool((n.lines.x > 0).all() and (n.lines.r > 0).all())


def test_harvest_query_builder() -> None:
    """Stage 01 needs no network to check the part that decides what is fetched:
    the voltage-band regex and the two-pass banding."""
    spec = importlib.util.spec_from_file_location(
        "harvest", os.path.join(PKG, "01_harvest_overpass.py"))
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    import re
    hi = re.compile(h.voltage_regex(100.0, None))
    lo = re.compile(h.voltage_regex(50.0, 100.0))
    assert hi.search("400000") and hi.search("110000") and hi.search("400000;110000")
    assert not hi.search("66000") and not hi.search("20000")
    assert lo.search("66000") and lo.search("90000") and lo.search("50000")
    assert not lo.search("110000") and not lo.search("20000")
    au = re.compile(h.voltage_regex(66.0, 100.0))
    assert au.search("66000") and au.search("88000")
    assert not au.search("33000") and not au.search("22000")
    cfg = {"voltage_floor_kv": 50, "high_pass_floor_kv": 100}
    assert h.passes_for(cfg) == [("hv", 100.0, None), ("sub", 50.0, 100.0)]
    assert h.passes_for({"voltage_floor_kv": 100, "high_pass_floor_kv": 100}) == \
        [("hv", 100.0, None)]
    q = h.build_conductor_query({"kind": "bbox", "bbox": [50, 0, 51, 1], "name": "t"},
                                100.0, None, 900)
    assert "out tags geom;" in q and "power" in q and "(50,0,51,1)" in q
    q2 = h.build_conductor_query({"kind": "area", "iso": "FR", "name": "area_FR"},
                                 100.0, None, 900)
    assert 'area["ISO3166-1"="FR"]' in q2 and "(area.a)" in q2


CHECKS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main() -> int:
    failed: List[Tuple[str, str]] = []
    for fn in CHECKS:
        name = fn.__name__
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            print(f"FAIL {name}: {exc}")
            failed.append((name, str(exc)))
        except Exception as exc:                          # noqa: BLE001
            print(f"ERROR {name}: {type(exc).__name__}: {exc}")
            failed.append((name, f"{type(exc).__name__}: {exc}"))
    b = _BUILD
    if b:
        s = b["report"]["summary"]
        print(f"\nfixture build: {s['ac_spans_network']} spans, {s['buses']} buses, "
              f"{s['total_route_km_network']} route-km, {s['in_substation_segments']} "
              f"internal segments, {s['transformers']} transformer, {s['dc_links']} dc link")
        shutil.rmtree(b["tmp"], ignore_errors=True)
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
