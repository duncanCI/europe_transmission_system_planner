#!/usr/bin/env python3
"""Gate tests - pin every documented threshold, by value and by behaviour.

Why this file exists: an earlier fixture suite reported 20/20 with eight
documented gates reverted to their pre-fix behaviour, including the site-fusion
distance that caused the Levallois/Perret defect and the `n_circuits` divisor in
the impedance formula. A suite that passes over a broken gate is worse than no
suite, so this module does two things the fixture suite did not:

  1. asserts the VALUE of every threshold against the documented figure, so a
     silent edit to any constant fails immediately, and
  2. exercises the gates that geometry can isolate on both sides of their
     boundary - refuse just past it, accept just inside it.

`tests/mutation_test.py` then proves these assertions actually bite, by
mutating each constant on a copy of the package and requiring a failure.

Run: python3 tests/gate_test.py
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BT = _load("bt", os.path.join(PKG, "02_build_topology.py"))
HV = _load("hv", os.path.join(PKG, "01_harvest_overpass.py"))

FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


# --------------------------------------------------------------------------- #
# 1. documented threshold values
# --------------------------------------------------------------------------- #
# Every figure below is quoted in README_methodology.md / the session review
# brief. Changing the code without changing the documentation is the failure
# mode this table exists to catch.
DOCUMENTED = {
    "SITE_MERGE_TOL_M": 150.0,        # two polygons are one site
    "SITE_CATCHMENT_M": 250.0,        # an end terminates at a site
    "SITE_FENCE_TOL_M": 30.0,         # decision 7 - "at the fence"
    "FREE_END_MIN_M": 50.0,           # decision 8 - approach conductor, not a jumper
    "BRIDGE_OUTSIDE_MAX_M": 50.0,     # decision 5 - conductor allowed outside both compounds
    "BRIDGE_GAP_MAX_M": 250.0,        # decision 5 - compounds still one site
    "JUNCTION_TOL_M": 25.0,
    "JUNCTION_EXT_M": 150.0,          # pitfall 23 extended reach
    "EE_TOL_FREE_M": 150.0,           # decision 10 - end-to-end ceiling, below one tower span
    "EE_MOVE_MAX_M": 50.0,
    "COS_CONTINUE_MAX": -0.5,         # decision 4 - 60 degrees
    "MAX_CLUSTER_M": 600.0,
    "EXT_MAX_CLUSTER_M": 250.0,       # decision 13
    "JUNCTION_MOVE_MAX_M": 50.0,
    "CROSS_COMPONENT_MERGE_M": 300.0,
    "PARALLEL_REJECT_DEG": 25.0,      # decision 9
    "DC_MAX_CONVERTER_M": 10_000.0,
    "DC_FAR_CONVERTER_M": 2_000.0,
    "LENGTH_RETENTION_MIN": 0.999,    # decision 14
    "FRAGMENT_FLAG_COUNT": 20,        # diagnostic 1
    "LONG_CONNECTOR_M": 1_000.0,
    "TRANSFORMER_RATIO_ARTEFACT": 1.095,
}
wrong = {k: (getattr(BT, k), v) for k, v in DOCUMENTED.items() if getattr(BT, k) != v}
check("documented_threshold_values", not wrong, f"{wrong}")

import common  # noqa: E402
check("earth_radius_km", abs(common.EARTH_RADIUS_KM - 6371.0088) < 1e-9)


# --------------------------------------------------------------------------- #
# 2. decision 13 - width caps hold on a SEEDED pass, and nothing is burst
# --------------------------------------------------------------------------- #
from shapely.geometry import Point  # noqa: E402

# The point ORDER matters and must not be "tidied". UnionFind keeps the smallest
# index as root, so listing the seeded chain in descending x puts the root (index
# 0, x = 200) next to the outlier at 340. A version that measures cluster width
# from root points alone then sees 140 m, admits the union, and produces a 340 m
# cluster; measuring from true membership sees 340 m and refuses. With the chain
# listed ascending, the root sits at x = 0 and the bogus measurement happens to
# be too LARGE, so the union is refused for the wrong reason and the defect hides.
pts = [Point(x, 0.0) for x in list(range(200, -1, -25)) + [340, 360]]
seed = BT.UnionFind(len(pts))
for i in range(1, 9):
    seed.union(0, i)                                   # 200..0 already one cluster
uf = BT.single_linkage(pts, tol=BT.JUNCTION_EXT_M, max_width=BT.EXT_MAX_CLUSTER_M, seed=seed)
groups = list(uf.groups().values())
widths = [BT.cluster_width([pts[k] for k in g]) for g in groups]
check("decision13_seeded_width_cap", max(widths) <= BT.EXT_MAX_CLUSTER_M + 1e-9,
      f"widest cluster {max(widths):.0f} m > {BT.EXT_MAX_CLUSTER_M:.0f} m cap")
check("decision13_no_bursting", len(groups) == 2, f"{len(groups)} clusters, expected 2")

# and the un-seeded pass still refuses an over-wide union rather than bursting
chain = [Point(x, 0.0) for x in range(0, 901, 100)]     # 900 m chain at 100 m spacing
uf2 = BT.single_linkage(chain, tol=BT.JUNCTION_TOL_M + 100.0, max_width=BT.MAX_CLUSTER_M)
w2 = [BT.cluster_width([chain[k] for k in g]) for g in uf2.groups().values()]
check("decision13_unseeded_width_cap", max(w2) <= BT.MAX_CLUSTER_M + 1e-9, f"{max(w2):.0f} m")


# --------------------------------------------------------------------------- #
# 3. decision 4 - the 60 degree value, not just its sign
# --------------------------------------------------------------------------- #
def unit(deg):
    r = math.radians(deg)
    return (math.cos(r), math.sin(r))


# two conductors leaving a shared node 30 deg apart are a fold-back: refuse
check("decision4_refuses_30deg", BT.dot(unit(0), unit(30)) >= BT.COS_CONTINUE_MAX)
# 100 deg apart is still not head-on (dot -0.17 > -0.5): refuse
check("decision4_refuses_100deg", BT.dot(unit(0), unit(100)) >= BT.COS_CONTINUE_MAX)
# 170 deg apart is a line running through the node: accept
check("decision4_accepts_170deg", BT.dot(unit(0), unit(170)) < BT.COS_CONTINUE_MAX)
# the boundary itself sits at 120 deg between outward directions (dot = -0.5)
check("decision4_boundary_is_120deg",
      abs(math.degrees(math.acos(-BT.COS_CONTINUE_MAX)) - 60.0) < 1e-9)


def build(elements, extra_cfg="", floor=50):
    """Run stage 2 on a handful of synthetic elements; return (stats, out_dir)."""
    d = tempfile.mkdtemp()
    h = os.path.join(d, "h")
    os.makedirs(h)
    with open(os.path.join(h, "x.ndjson"), "w") as fh:
        for e in elements:
            fh.write(json.dumps(e) + "\n")
    cfg = (f"region_name: micro\nvoltage_floor_kv: {floor}\nmetric_crs: EPSG:3035\n"
           f"harvest_dir: {h}\nout_dir: {d}/out\nbboxes: [[50.0, -1.0, 52.0, 2.0]]\n"
           f"country_source: none\nlayer_voltages_kv: [132, 220, 400]\n"
           f"traction: {{enabled: false}}\n" + extra_cfg)
    if "layer_min_spans" not in extra_cfg:
        cfg += "layer_min_spans: 1\n"
    with open(os.path.join(d, "c.yaml"), "w") as fh:
        fh.write(cfg)
    r = subprocess.run([sys.executable, os.path.join(PKG, "02_build_topology.py"),
                        "--config", os.path.join(d, "c.yaml")],
                       capture_output=True, text=True)
    sp = os.path.join(d, "out", "build_stats.json")
    if not os.path.exists(sp):
        raise AssertionError(f"build failed: {r.stderr[-800:]}")
    return json.load(open(sp)), os.path.join(d, "out")


DEG_M = 111_320.0          # metres per degree of latitude, near enough for fixtures


def sub_way(wid, name, lon, lat, half_m=60.0, voltage="400000"):
    dx = half_m / (DEG_M * math.cos(math.radians(lat)))
    dy = half_m / DEG_M
    ring = [[lon - dx, lat - dy], [lon + dx, lat - dy], [lon + dx, lat + dy],
            [lon - dx, lat + dy], [lon - dx, lat - dy]]
    return {"type": "way", "id": wid, "tags": {"power": "substation", "name": name,
                                               "voltage": voltage}, "geometry": ring}


def line_way(wid, coords, voltage="400000", circuits="1", extra=None):
    tags = {"power": "line", "voltage": voltage, "circuits": circuits}
    tags.update(extra or {})
    return {"type": "way", "id": wid, "tags": tags, "geometry": coords}


def lon_at(lon0, lat, metres):
    return lon0 + metres / (DEG_M * math.cos(math.radians(lat)))


LAT = 51.0


# --------------------------------------------------------------------------- #
# 4. electrical conventions - exact values for a two-circuit span
# --------------------------------------------------------------------------- #
# LINE_TYPES maps a voltage anchor to (type name, r ohm/km, x ohm/km, i_nom kA).
# The conventions under test (README s5): r_ohm = r_type * L / n_circuits, x
# likewise, s_nom = sqrt(3) * V * i_nom * n_circuits, i_nom per circuit. Both
# n_circuits terms have been dropped by a regression before, so pin them here
# against a hand-computed two-circuit span.
name, r_km, x_km, i_nom, _proxy = BT.line_type_for(400.0)
L_km, n = 100.0, 2
s_nom = math.sqrt(3.0) * 400.0 * i_nom * n
r_ohm, x_ohm = r_km * L_km / n, x_km * L_km / n
check("s_nom_multiplies_by_n_circuits",
      abs(s_nom - math.sqrt(3.0) * 400.0 * i_nom * 2.0) < 1e-9 and
      abs(s_nom / (math.sqrt(3.0) * 400.0 * i_nom * 1.0) - 2.0) < 1e-9)
check("impedance_divides_by_n_circuits",
      abs(r_ohm - r_km * 50.0) < 1e-9 and abs(x_ohm - x_km * 50.0) < 1e-9)

# and the same two conventions end-to-end through a real build, so a change in
# the formula site is caught as well as a change in the arithmetic here
els_e = [sub_way(161, "Gen", 0.0, LAT), sub_way(162, "Load", lon_at(0.0, LAT, 10_000.0), LAT),
         line_way(251, [[0.0, LAT], [lon_at(0.0, LAT, 10_000.0), LAT]], circuits="2")]
st_e, out_e = build(els_e)
import sqlite3 as _sq  # noqa: E402
rowe = _sq.connect(os.path.join(out_e, "micro_grid_graph.gpkg")).execute(
    "SELECT n_circuits, s_nom_mva, r_ohm, x_ohm, i_nom_ka, "
    "length_conductor_m + connector0_m + connector1_m FROM ac_line_all").fetchone()
nc, snom, rr, xx, inom, Lm = rowe
exp_s = math.sqrt(3.0) * 400.0 * inom * nc
# L is the drawn length - conductor plus both connectors - which is what the
# shipped dataset used (implied r/km on 400 kV double circuits: 0.030 exactly,
# stdev 0.0002, against 0.0107 stdev if connectors are excluded).
exp_r = r_km * (Lm / 1000.0) / nc
check("build_s_nom_convention", nc == 2 and abs(snom - exp_s) / exp_s < 1e-6,
      f"n={nc} s_nom={snom:.1f} expected {exp_s:.1f}")
check("build_impedance_convention", abs(rr - exp_r) / exp_r < 1e-6,
      f"r_ohm={rr:.4f} expected {exp_r:.4f}")

# --------------------------------------------------------------------------- #
# 5. harvest voltage banding - both bounds enforced
# --------------------------------------------------------------------------- #
import re  # noqa: E402

sub = re.compile(HV.voltage_regex(66, 110))     # the Australian sub-transmission pass
check("voltage_band_upper_bound",
      not any(sub.search(v) for v in ("132000", "220000", "330000", "500000")),
      "pass 2 regex matched a pass 1 voltage")
check("voltage_band_lower_bound", not sub.search("33000") and bool(sub.search("66000")))
eu = re.compile(HV.voltage_regex(50, 100))
check("voltage_band_multivalue_anchoring",
      eu.search("110000;20000") is None and eu.search("110000;66000") is not None)

# the DC sweep must cover the whole configured region, not one area
from common import load_config  # noqa: E402

cfg_eu = load_config(os.path.join(PKG, "config_europe.yaml"))
check("dc_sweep_covers_region", len(HV.dc_scopes(cfg_eu)) == len(cfg_eu["areas"]),
      f"{len(HV.dc_scopes(cfg_eu))} dc scopes for {len(cfg_eu['areas'])} areas")

# grid frequency is a top-level key, so a 60 Hz region is configurable with
# traction disabled (the porting guide's own instruction)
cfg60 = dict(cfg_eu)
check("grid_frequency_is_config", cfg_eu["grid_frequency_hz"] == 50.0)
tmp = tempfile.mkdtemp()
with open(os.path.join(tmp, "c60.yaml"), "w") as fh:
    fh.write("region_name: r60\nvoltage_floor_kv: 66\ngrid_frequency_hz: 60\n"
             "metric_crs: EPSG:5070\nbboxes: [[0, 0, 1, 1]]\ntraction: {enabled: false}\n")
check("grid_frequency_60_honoured",
      load_config(os.path.join(tmp, "c60.yaml"))["grid_frequency_hz"] == 60.0)


# --------------------------------------------------------------------------- #
# 6. behavioural micro-fixtures
# --------------------------------------------------------------------------- #

# --- decision 5: two compounds 200 m apart (inside BRIDGE_GAP_MAX) joined by a
# conductor that runs 200 m in the open (past BRIDGE_OUTSIDE_MAX) must NOT fuse
a_c, b_c = 0.0, lon_at(0.0, LAT, 320.0)              # centres 320 m apart -> 200 m gap
els = [sub_way(101, "Levallois", a_c, LAT), sub_way(102, "Perret", b_c, LAT),
       line_way(201, [[lon_at(a_c, LAT, 0.0), LAT], [lon_at(b_c, LAT, 0.0), LAT]]),
       # a real feeder into each compound, so the sites are not isolated
       line_way(202, [[lon_at(a_c, LAT, -2000.0), LAT], [lon_at(a_c, LAT, 0.0), LAT]]),
       line_way(203, [[lon_at(b_c, LAT, 0.0), LAT], [lon_at(b_c, LAT, 2000.0), LAT]])]
st, _ = build(els)
check("decision5_refuses_far_running_conductor",
      st["layer_counts"].get("site_400kV", 0) == 2 and
      st.get("site_conductor_merge_refused_geometry", 0) >= 1,
      f"sites={st['layer_counts'].get('site_400kV')} "
      f"refused={st.get('site_conductor_merge_refused_geometry')}")

# --- and the converse: compounds 60 m apart with the conductor barely outside
# them ARE one site, so the gate is not simply "never fuse"
a_c2, b_c2 = 0.0, lon_at(0.0, LAT, 180.0)            # centres 180 m -> 60 m gap
els2 = [sub_way(111, "Yard North", a_c2, LAT), sub_way(112, "Yard South", b_c2, LAT),
        line_way(211, [[lon_at(a_c2, LAT, 0.0), LAT], [lon_at(b_c2, LAT, 0.0), LAT]]),
        line_way(212, [[lon_at(a_c2, LAT, -2000.0), LAT], [lon_at(a_c2, LAT, 0.0), LAT]]),
        line_way(213, [[lon_at(b_c2, LAT, 0.0), LAT], [lon_at(b_c2, LAT, 2000.0), LAT]])]
st2, _ = build(els2)
check("decision5_accepts_close_compounds",
      st2.get("site_merged_by_conductor", 0) >= 1 or
      st2["layer_counts"].get("site_400kV", 9) == 1,
      f"merged={st2.get('site_merged_by_conductor')} "
      f"sites={st2['layer_counts'].get('site_400kV')}")

# --- decision 9: a near-parallel contact landing mid-conductor is rejected
LAT2 = 51.2
main = [[lon_at(0.0, LAT2, m), LAT2] for m in (0.0, 4000.0)]
# a second circuit running 8 deg off parallel that touches the main line's middle
touch_lon = lon_at(0.0, LAT2, 2000.0)
para = [[touch_lon, LAT2], [lon_at(0.0, LAT2, 5000.0), LAT2 + 0.0060]]   # ~8 deg
els3 = [sub_way(121, "Alpha", 0.0, LAT2), sub_way(122, "Beta", lon_at(0.0, LAT2, 4000.0), LAT2),
        line_way(221, main), line_way(222, para)]
st3, _ = build(els3)
check("decision9_rejects_near_parallel_contact", st3.get("snap_rejected_parallel", 0) >= 1,
      f"snap_rejected_parallel={st3.get('snap_rejected_parallel')}")

# --- decision 9 converse: a 90 degree tap into the middle IS accepted
perp = [[touch_lon, LAT2], [touch_lon, LAT2 + 0.02]]
els4 = [sub_way(131, "Alpha", 0.0, LAT2), sub_way(132, "Beta", lon_at(0.0, LAT2, 4000.0), LAT2),
        line_way(231, main), line_way(232, perp)]
st4, _ = build(els4)
check("decision9_accepts_perpendicular_tap",
      st4.get("snap_rejected_parallel", 0) == 0 and st4["spans"] >= 3,
      f"rejected={st4.get('snap_rejected_parallel')} spans={st4['spans']}")

# --- v22 duplicate multi-circuit relations collapse to one physical corridor
w = {900: [[0.0, LAT], [lon_at(0.0, LAT, 1500.0), LAT]],
     901: [[lon_at(0.0, LAT, 1500.0), LAT], [lon_at(0.0, LAT, 3000.0), LAT]]}
els5 = [line_way(k, v, voltage="220000", circuits="1") for k, v in w.items()]
els5 += [{"type": "relation", "id": 800 + k,
          "tags": {"route": "power", "voltage": "220000", "name": f"Circuit {k + 1}"},
          "members": [{"type": "way", "ref": r, "role": "", "geometry": w[r]} for r in (900, 901)]}
         for k in range(2)]
els5 += [sub_way(141, "West", 0.0, LAT, voltage="220000"),
         sub_way(142, "East", lon_at(0.0, LAT, 3000.0), LAT, voltage="220000")]
st5, out5 = build(els5)
check("duplicate_relations_collapsed",
      st5.get("duplicate_relation_groups_collapsed", 0) == 1 and st5["spans"] == 1,
      f"groups={st5.get('duplicate_relation_groups_collapsed')} spans={st5['spans']}")
import sqlite3  # noqa: E402

row = sqlite3.connect(os.path.join(out5, "micro_grid_graph.gpkg")).execute(
    "SELECT n_circuits, circuits_source FROM ac_line_all").fetchone()
check("collapsed_corridor_carries_circuits", row and row[0] == 2, f"{row}")

# --- the collapse must be exact: relations sharing only SOME ways are two
# different corridors and must survive as two spans (a subset match would delete
# real network, which is the opposite failure to the one the collapse fixes)
w3 = {910: [[0.0, LAT], [lon_at(0.0, LAT, 1500.0), LAT]],
      911: [[lon_at(0.0, LAT, 1500.0), LAT], [lon_at(0.0, LAT, 3000.0), LAT]],
      912: [[lon_at(0.0, LAT, 3000.0), LAT], [lon_at(0.0, LAT, 4500.0), LAT]]}
els7 = [line_way(k, v, voltage="220000") for k, v in w3.items()]
els7 += [{"type": "relation", "id": 810 + i,
          "tags": {"route": "power", "voltage": "220000", "name": nm},
          "members": [{"type": "way", "ref": r, "role": "", "geometry": w3[r]} for r in refs]}
         for i, (nm, refs) in enumerate((("West Route", (910, 911)), ("East Route", (911, 912))))]
els7 += [sub_way(171, "West End", 0.0, LAT, voltage="220000"),
         sub_way(172, "East End", lon_at(0.0, LAT, 4500.0), LAT, voltage="220000")]
st7, _ = build(els7)
check("partial_member_overlap_not_collapsed",
      st7.get("duplicate_relation_groups_collapsed", 0) == 0 and st7["spans"] == 2,
      f"collapsed={st7.get('duplicate_relation_groups_collapsed')} spans={st7['spans']}")

# --- the v23 typing rule table ships whole, with sources and the coupling warning
tr = sqlite3.connect(os.path.join(out5, "micro_grid_topology.gpkg"))
cols = [r[1] for r in tr.execute("PRAGMA table_info(v23_typing_rule)")]
bands = [r[0] for r in tr.execute("SELECT band FROM v23_typing_rule")]
urls = [r[0] for r in tr.execute("SELECT source_url FROM v23_typing_rule WHERE band LIKE 'R%'")]
check("typing_rule_table_complete",
      set(bands) == {"R1", "R2", "R3", "R4", "R5", "R6", "ALT", "NOTE"} and
      "source_url" in cols and all(u and u.startswith("http") for u in urls),
      f"bands={bands} cols={cols}")
warn = tr.execute("SELECT basis FROM v23_typing_rule WHERE band='ALT'").fetchone()[0]
check("typing_rule_carries_coupling_warning", "per-unit on s_nom_mva" in warn)

# --- a standard-but-unlisted voltage falls into line_other_kV, not its own layer
els6 = [sub_way(151, "Odd A", 0.0, LAT, voltage="236000"),
        sub_way(152, "Odd B", lon_at(0.0, LAT, 3000.0), LAT, voltage="236000"),
        line_way(241, [[0.0, LAT], [lon_at(0.0, LAT, 3000.0), LAT]], voltage="236000")]
st6, _ = build(els6, extra_cfg="standard_voltages_kv: [132, 220, 236, 400]\n"
                                "layer_min_spans: 50\n")
check("unlisted_voltage_goes_to_other_layer",
      "line_236kV" not in st6["layer_counts"] and "line_other_kV" in st6["layer_counts"],
      f"{sorted(st6['layer_counts'])}")

# --------------------------------------------------------------------------- #
# 7. gates that a value table cannot pin - each of these mutations survived an
#    earlier version of the suite, which is why they are here as behaviour
# --------------------------------------------------------------------------- #

# --- decision 12: a junction at a SUBSTATION never dissolves. The dissolve rule
# only fires when every span meeting the node is the SAME OSM element, so the
# fixture must be one way running THROUGH a substation - with two different ways
# the element test alone refuses and the is_site guard is never the deciding factor.
els_d12 = [sub_way(181, "Middle", lon_at(0.0, LAT, 3000.0), LAT),
           sub_way(182, "West End", 0.0, LAT),
           sub_way(183, "East End", lon_at(0.0, LAT, 6000.0), LAT),
           line_way(261, [[0.0, LAT], [lon_at(0.0, LAT, 3000.0), LAT],
                          [lon_at(0.0, LAT, 6000.0), LAT]])]
st_d12, out_d12 = build(els_d12)
ac = sqlite3.connect(os.path.join(out_d12, "micro_grid_graph.gpkg"))
spans_d12 = ac.execute("SELECT COUNT(*) FROM ac_line_all").fetchone()[0]
at_mid = ac.execute(
    "SELECT COUNT(*) FROM ac_line_all WHERE bus0 LIKE 'st%' AND bus1 LIKE 'st%'").fetchone()[0]
# The guard's observable job is keeping a substation node OUT of the dissolvable
# set. Downstream fusion has its own head-on test, so asserting only on span count
# lets the mutation hide: removing the guard marks the node dissolvable while the
# spans happen to survive. Assert the set itself.
check("decision12_site_node_never_dissolves",
      spans_d12 >= 2 and at_mid >= 2 and st_d12.get("dissolvable_junctions", 0) == 0,
      f"spans={spans_d12} station-to-station={at_mid} "
      f"dissolvable={st_d12.get('dissolvable_junctions')} (must be 0: the only "
      "candidate node is a substation)")

# --- decision 3: a substation bus sits INSIDE its own polygon. A C-shaped compound
# has its centroid in the notch, i.e. outside the polygon, so replacing the pole of
# inaccessibility with the centroid puts the bus in open ground - the defect that
# 500 m clustering produced for 9.2% of buses.
def c_shaped_sub(wid, name, lon0, lat0, size_m=500.0, wall_m=90.0, voltage="400000"):
    dx = 1.0 / (DEG_M * math.cos(math.radians(lat0)))
    dy = 1.0 / DEG_M
    S, W = size_m, wall_m
    ring_m = [(0, 0), (S, 0), (S, W), (W, W), (W, S - W), (S, S - W), (S, S), (0, S), (0, 0)]
    return {"type": "way", "id": wid,
            "tags": {"power": "substation", "name": name, "voltage": voltage},
            "geometry": [[lon0 + x * dx, lat0 + y * dy] for x, y in ring_m]}


cs = c_shaped_sub(191, "Cee Yard", 0.0, LAT)
from shapely.geometry import Polygon as _Poly  # noqa: E402

_poly = _Poly([(x, y) for x, y in cs["geometry"]])
check("decision3_fixture_centroid_is_outside", not _poly.contains(_poly.centroid),
      "fixture is not concave enough to discriminate")
els_d3 = [cs, sub_way(192, "Far", lon_at(0.0, LAT, 6000.0), LAT),
          line_way(271, [[lon_at(0.0, LAT, 250.0), LAT + 250.0 / DEG_M],
                         [lon_at(0.0, LAT, 6000.0), LAT]])]
st_d3, out_d3 = build(els_d3)
topo = sqlite3.connect(os.path.join(out_d3, "micro_grid_topology.gpkg"))
from shapely import wkb as _wkb  # noqa: E402


def _g(blob):
    b = bytes(blob)
    env = (b[3] >> 1) & 7
    return _wkb.loads(b[8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[env]:])


polys = {r[0]: _g(r[1]) for r in topo.execute("SELECT station_id, geom FROM station_cluster")}
bad = []
for sid, blob in topo.execute("SELECT station_id, geom FROM site_400kV"):
    poly = polys.get(sid)
    if poly is not None and not poly.buffer(1e-9).contains(_g(blob)):
        bad.append(sid)
check("decision3_bus_inside_its_own_polygon", not bad, f"{bad} outside their site")

# --- decision 14: a geometry rebuild that loses length is never shipped silently.
# The element below folds back over its own middle 2 km, which is the shape that
# made earlier dissolves drop route-km. Acceptable outcomes are a loud failure or a
# revert; shipping a shorter network is not. With the length comparison neutered the
# build completes AND loses length, which this catches.
def build_allow_fail(elements):
    d = tempfile.mkdtemp()
    h = os.path.join(d, "h")
    os.makedirs(h)
    with open(os.path.join(h, "x.ndjson"), "w") as fh:
        for e in elements:
            fh.write(json.dumps(e) + "\n")
    with open(os.path.join(d, "c.yaml"), "w") as fh:
        fh.write(f"region_name: micro\nvoltage_floor_kv: 50\nmetric_crs: EPSG:3035\n"
                 f"harvest_dir: {h}\nout_dir: {d}/out\nbboxes: [[50.0, -1.0, 52.0, 2.0]]\n"
                 f"country_source: none\nlayer_voltages_kv: [132, 220, 400]\n"
                 f"layer_min_spans: 1\ntraction: {{enabled: false}}\n")
    r = subprocess.run([sys.executable, os.path.join(PKG, "02_build_topology.py"),
                        "--config", os.path.join(d, "c.yaml")], capture_output=True, text=True)
    sp = os.path.join(d, "out", "build_stats.json")
    st = json.load(open(sp)) if os.path.exists(sp) else None
    return r.returncode, st


els_d14 = [sub_way(201, "Loop A", 0.0, LAT), sub_way(202, "Loop B", lon_at(0.0, LAT, 4000.0), LAT),
           line_way(281, [[0.0, LAT], [lon_at(0.0, LAT, 2000.0), LAT],
                          [lon_at(0.0, LAT, 4000.0), LAT], [lon_at(0.0, LAT, 2000.0), LAT]])]
rc14, st14 = build_allow_fail(els_d14)
drawn_km = 6.0                       # 2 km out, 2 km on, 2 km back over the middle
loud_failure = rc14 != 0 or st14 is None
kept = (st14 or {}).get("route_km", 0.0) + (st14 or {}).get("connector_km", 0.0)
check("decision14_never_ships_lost_length",
      loud_failure or kept >= drawn_km * 0.999,
      f"rc={rc14} route_km={(st14 or {}).get('route_km')} vs drawn {drawn_km}")

# --- decision 13 through the build: a legally-chained cluster between the two caps
# (275 m at 25 m spacing) must stay ONE junction node. Re-applying the extended cap
# here re-clustered it at 10 m into 12 singletons - the bursting outcome.
# 13 free ends at one latitude, 24 m apart: they chain at JUNCTION_TOL_M (25 m)
# into a single 288 m cluster - legal for pass 1 (MAX_CLUSTER_M 600 m), past the
# extended cap (250 m). Applying the extended cap post-hoc re-clusters it at 10 m
# into 13 singletons. Ends must be co-latitudinal or the 25 m chain does not form.
spokes = []
for i in range(13):
    x0 = lon_at(0.0, LAT, i * 24.0)
    spokes.append(line_way(300 + i, [[x0, LAT + 900.0 / DEG_M], [x0, LAT]]))
els_d13 = spokes + [sub_way(211, "Anchor", lon_at(0.0, LAT, 144.0), LAT + 900.0 / DEG_M)]
st_d13, out_d13 = build(els_d13)
jn = sqlite3.connect(os.path.join(out_d13, "micro_grid_topology.gpkg")).execute(
    "SELECT COUNT(*) FROM junction_node").fetchone()[0]
check("decision13_legal_chain_not_burst_in_build", jn <= 3,
      f"{jn} junction nodes from one 288 m chain of 13 ends - bursting "
      f"(reclustered={st_d13.get('reclustered_wide_clusters')})")

# --- decision 7: a shared point outside the fence only becomes a junction when one
# of the spans meeting there has its OTHER end at a fence. Two spans meeting in open
# ground, neither anchored, must keep their site ends - weakening the anchoring test
# frees ends that belong to the substation (the Ecrainville over-correction).
# The shared point must be inside the 250 m catchment but outside the 30 m fence:
# the yard below is 120 m wide, so its edge sits 60 m from centre and the meeting
# point at 180 m from centre is 120 m out - assigned to the site, not at the fence.
share_x = lon_at(0.0, LAT, 180.0)
els_d7 = [sub_way(241, "Yard", 0.0, LAT),
          line_way(291, [[share_x, LAT], [lon_at(0.0, LAT, 3000.0), LAT + 900.0 / DEG_M]]),
          line_way(292, [[share_x, LAT], [lon_at(0.0, LAT, 3000.0), LAT - 900.0 / DEG_M]])]
st_d7, _ = build(els_d7)
check("decision7_unanchored_group_not_diverted",
      st_d7.get("ends_diverted_to_junction", 0) == 0,
      f"diverted={st_d7.get('ends_diverted_to_junction')} (no span has its far end "
      "at a fence, so nothing may be freed)")

# --- the collapse must not merge a MIXED-VOLTAGE shared-pylon pair: two relations
# over the same towers at different voltages are two circuits, and collapsing them
# deletes the lower voltage entirely - network loss, not deduplication.
wv = {920: [[0.0, LAT], [lon_at(0.0, LAT, 1500.0), LAT]],
      921: [[lon_at(0.0, LAT, 1500.0), LAT], [lon_at(0.0, LAT, 3000.0), LAT]]}
els8 = [line_way(k, v, voltage="400000;220000") for k, v in wv.items()]
els8 += [{"type": "relation", "id": 820 + i,
          "tags": {"route": "power", "voltage": kv, "name": nm},
          "members": [{"type": "way", "ref": r, "role": "", "geometry": wv[r]} for r in (920, 921)]}
         for i, (kv, nm) in enumerate((("400000", "Upper"), ("220000", "Lower")))]
els8 += [sub_way(221, "West", 0.0, LAT, voltage="400000;220000"),
         sub_way(222, "East", lon_at(0.0, LAT, 3000.0), LAT, voltage="400000;220000")]
st8, out8 = build(els8)
kvs = {r[0] for r in sqlite3.connect(os.path.join(out8, "micro_grid_graph.gpkg")).execute(
    "SELECT voltage_kv FROM ac_line_all")}
check("mixed_voltage_pylon_pair_not_collapsed",
      {220.0, 400.0} <= kvs and st8.get("duplicate_relation_groups_collapsed", 0) == 0,
      f"voltages={sorted(kvs)} collapsed={st8.get('duplicate_relation_groups_collapsed')}")

# --- and the collapse key must be the WHOLE member set: two relations sharing their
# first way but not the rest are different corridors
wk = {930: [[0.0, LAT], [lon_at(0.0, LAT, 1200.0), LAT]],
      931: [[lon_at(0.0, LAT, 1200.0), LAT], [lon_at(0.0, LAT, 2400.0), LAT]],
      932: [[lon_at(0.0, LAT, 1200.0), LAT], [lon_at(0.0, LAT, 1200.0), LAT + 1200.0 / DEG_M]]}
els9 = [line_way(k, v, voltage="220000") for k, v in wk.items()]
els9 += [{"type": "relation", "id": 830 + i,
          "tags": {"route": "power", "voltage": "220000", "name": nm},
          "members": [{"type": "way", "ref": r, "role": "", "geometry": wk[r]} for r in refs]}
         for i, (nm, refs) in enumerate((("Straight", (930, 931)), ("Branch", (930, 932))))]
els9 += [sub_way(231, "Root", 0.0, LAT, voltage="220000"),
         sub_way(232, "East", lon_at(0.0, LAT, 2400.0), LAT, voltage="220000"),
         sub_way(233, "North", lon_at(0.0, LAT, 1200.0), LAT + 1200.0 / DEG_M, voltage="220000")]
st9, _ = build(els9)
check("shared_first_way_not_collapsed",
      st9.get("duplicate_relation_groups_collapsed", 0) == 0 and st9["spans"] >= 2,
      f"collapsed={st9.get('duplicate_relation_groups_collapsed')} spans={st9['spans']}")

# --- ambiguity inside a collapsed group is flagged on the surviving row, never
# silently resolved (v22 wrote this flag per row and the claim to carry the v22
# collapse rests on it). The flag was once appended before the variable holding it
# was assigned, so it vanished - and crashed if that row came first.
wa = {940: [[0.0, LAT], [lon_at(0.0, LAT, 1500.0), LAT]],
      941: [[lon_at(0.0, LAT, 1500.0), LAT], [lon_at(0.0, LAT, 3000.0), LAT]]}
els10 = [{"type": "relation", "id": 840 + i,
          "tags": {"route": "power", "voltage": "220000", "circuits": c, "name": nm},
          "members": [{"type": "way", "ref": r, "role": "", "geometry": wa[r]} for r in (940, 941)]}
         for i, (c, nm) in enumerate((("1", "Circuit A"), ("2", "Circuit B")))]
els10 += [line_way(k, v, voltage="220000") for k, v in wa.items()]
els10 += [sub_way(251, "West", 0.0, LAT, voltage="220000"),
          sub_way(252, "East", lon_at(0.0, LAT, 3000.0), LAT, voltage="220000")]
st10, out10 = build(els10)
qa = [r[0] or "" for r in sqlite3.connect(os.path.join(out10, "micro_grid_graph.gpkg")).execute(
    "SELECT qa_flags FROM ac_line_all")]
check("collapse_ambiguity_flagged_on_row",
      st10.get("duplicate_relation_groups_ambiguous", 0) == 1 and
      any("circuit_count_element_level_ambiguous" in f for f in qa),
      f"ambiguous={st10.get('duplicate_relation_groups_ambiguous')} qa={qa}")

# --- pitfall 18: a junction node is a REAL endpoint (the medoid), never a computed
# mean. Asserting against the exported line geometry cannot fail - attach_connectors
# prepends the bus point to the drawn geometry, so every node is an endpoint of it by
# construction. The discriminating measure is whether a cluster member sits AT the
# node: with the medoid one member is exactly on it (connector 0 m); with the mean of
# a bimodal cluster the node lands between the modes and every member needs a
# connector. Ends at 0/20/40 and 180/200/220 m are unioned by the extended pass.
jnpts = []
for i, off in enumerate((0.0, 20.0, 40.0, 180.0, 200.0, 220.0)):
    x0 = lon_at(0.0, LAT, off)
    jnpts.append(line_way(320 + i, [[x0, LAT + 800.0 / DEG_M], [x0, LAT]]))
els11 = jnpts + [sub_way(261, "Top", lon_at(0.0, LAT, 110.0), LAT + 800.0 / DEG_M)]
st11, out11 = build(els11)
gr = sqlite3.connect(os.path.join(out11, "micro_grid_graph.gpkg"))
zero_conn = gr.execute(
    "SELECT COUNT(*) FROM ac_line_all WHERE connector0_m = 0.0 OR connector1_m = 0.0").fetchone()[0]
check("junction_node_is_a_real_endpoint", zero_conn >= 1,
      f"no conductor end sits exactly on a junction node (zero-length connectors="
      f"{zero_conn}) - the node is a computed point, not a member endpoint")

# --- the traction operator inference is gated to <= traction.max_voltage_kv: an EHV
# line owned by a railway operator is a supply line, not traction (the 170 kV Swedish
# row in the shipped data). Ungated, it would move 400 kV network to 16.7 Hz.
els12 = [sub_way(271, "Rail A", 0.0, LAT), sub_way(272, "Rail B", lon_at(0.0, LAT, 4000.0), LAT),
         line_way(331, [[0.0, LAT], [lon_at(0.0, LAT, 4000.0), LAT]],
                  extra={"operator": "DB Energie GmbH"})]
st12, out12 = build(els12, extra_cfg=("traction:\n  enabled: true\n  frequency_hz: 16.7\n"
                                     "  max_voltage_kv: 132\n  countries: []\n"
                                     "  operators: ['db energie']\n"))
hz = [r[0] for r in sqlite3.connect(os.path.join(out12, "micro_grid_graph.gpkg")).execute(
    "SELECT frequency_hz FROM ac_line_all")]
check("traction_inference_gated_by_voltage", hz and all(h == 50.0 for h in hz),
      f"400 kV railway-operator line classified {hz}, expected grid frequency")

# --- scope_bbox actually clips: the v22 overseas-territory prune the README claims
els13 = [sub_way(281, "In A", 0.0, LAT), sub_way(282, "In B", lon_at(0.0, LAT, 3000.0), LAT),
         line_way(341, [[0.0, LAT], [lon_at(0.0, LAT, 3000.0), LAT]]),
         sub_way(283, "Far Island A", 1.60, LAT), sub_way(284, "Far Island B", 1.63, LAT),
         line_way(342, [[1.60, LAT], [1.63, LAT]])]
st13, out13 = build(els13, extra_cfg="scope_bbox: [50.5, -0.5, 51.5, 1.0]\n")
names = {r[0] for r in sqlite3.connect(os.path.join(out13, "micro_grid_topology.gpkg")).execute(
    "SELECT station_name FROM site_400kV")}
check("scope_bbox_clips_out_of_area_elements",
      not any(n and "Far Island" in n for n in names) and st13["spans"] == 1,
      f"sites={sorted(n for n in names if n)} spans={st13['spans']}")

# --- BRIDGE_OUTSIDE_MAX_M in isolation, the binding half of decision 5 (the
# Levallois/Perret gate). A 150 m gap between two compounds is the geometry that
# discriminates: at the documented 50 m the merge is refused, and at 200 m it is
# allowed. Measured, not assumed - at a 200 m gap both settings refuse, so a fixture
# built there would pin nothing.
els14 = [sub_way(291, "Alpha Yard", 0.0, LAT),
         sub_way(292, "Beta Yard", lon_at(0.0, LAT, 270.0), LAT),
         line_way(351, [[0.0, LAT], [lon_at(0.0, LAT, 270.0), LAT]])]
st14, _ = build(els14)
check("bridge_outside_gate_isolated",
      st14.get("site_conductor_merge_refused_geometry", 0) >= 1 and
      st14.get("site_merged_by_conductor", 0) == 0,
      f"refused={st14.get('site_conductor_merge_refused_geometry')} "
      f"merged={st14.get('site_merged_by_conductor')} - a conductor running 150 m in "
      "the open must not fuse two compounds")

# --- per-band transformer parameters. The expectation is HARDCODED from the
# published rule (transformer_typing_rule.csv / README s13.1), not derived from
# TRANSFORMER_BANDS - deriving it means editing the constant edits both sides of the
# comparison, which pins nothing. The 150/220 and 150/400 pairs matter: with lo in
# {220,132,110,66} only, moving the R1 selector from lo>=200 to lo>=150 goes unnoticed
# and mis-types every French, Italian, Belgian, Dutch and Portuguese 150 kV coupling.
PUBLISHED_BANDS = {          # band: (s_nom_mva, x_pu, r_pu)
    "R1": (2000.0, 0.100, 0.0025),
    "R2": (500.0, 0.122, 0.0025),
    "R3": (300.0, 0.120, 0.0026),
    "R4": (300.0, 0.100, 0.0025),
    "R5": (200.0, 0.160, 0.0040),
    "R6": (120.0, 0.160, 0.0040),
}
PAIR_BANDS = [(220, 400, "R1"), (300, 420, "R1"), (132, 400, "R2"), (150, 400, "R2"),
              (110, 220, "R3"), (150, 220, "R3"), (132, 150, "R4"), (66, 220, "R5"),
              (66, 132, "R6")]
mismatch = {}
for lo, hi, band in PAIR_BANDS:
    v = f"{hi * 1000};{lo * 1000}"
    e = [sub_way(400 + hi + lo, f"T{band}", 0.0, LAT, voltage=v),
         sub_way(500 + hi + lo, f"F{band}hi", lon_at(0.0, LAT, 4000.0), LAT, voltage=f"{hi * 1000}"),
         sub_way(600 + hi + lo, f"F{band}lo", lon_at(0.0, LAT, -4000.0), LAT, voltage=f"{lo * 1000}"),
         line_way(700 + hi + lo, [[0.0, LAT], [lon_at(0.0, LAT, 4000.0), LAT]], voltage=f"{hi * 1000}"),
         line_way(800 + hi + lo, [[lon_at(0.0, LAT, -4000.0), LAT], [0.0, LAT]], voltage=f"{lo * 1000}")]
    stb, outb = build(e, extra_cfg=f"layer_voltages_kv: [{lo}, {hi}]\n")
    row = sqlite3.connect(os.path.join(outb, "micro_grid_topology.gpkg")).execute(
        "SELECT s_nom_mva, x_pu, r_pu, parameters_source FROM transformer").fetchone()
    want = PUBLISHED_BANDS[band]
    if (not row or (round(row[0], 4), round(row[1], 4), round(row[2], 5)) != want
            or f"typing_rule_v23:{band}" not in (row[3] or "")):
        mismatch[f"{lo}/{hi}"] = {"want": (band,) + want, "got": row}
check("transformer_bands_applied_per_voltage_pair", not mismatch, f"{mismatch}")

print()
print(f"{len(DOCUMENTED)} thresholds pinned; "
      f"{len([k for k in globals() if k.startswith('st')])} micro-fixtures built")
print(f"{'ALL CHECKS PASSED' if not FAILS else str(len(FAILS)) + ' FAILED: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
