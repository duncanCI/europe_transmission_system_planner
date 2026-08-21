#!/usr/bin/env python3
"""Stage 2 - harvested NDJSON to a multi-layer GeoPackage pair.

Faithful reimplementation of the method documented in
README_methodology_v23.md (sections 4, 5, 6, 7, 11-13) and of the fourteen
numbered "design decisions that must not be reverted" recorded in the dataset
build record. Every threshold below is a named constant carrying the section it
comes from; nothing is tuned in place.

Stage order (README s6.4, and the stage table in the session review brief):

    load/clean -> geometry -> chain merge -> end-to-end join -> snap/split
    -> sites -> clip -> end assignment -> junction clustering -> buses
    -> connectors -> dissolve -> self-loop sweep -> transformers
    -> components -> electrical parameters -> export

Usage:
    python 02_build_topology.py --config config_europe.yaml
    python 02_build_topology.py --config config_europe.yaml \
        --harvest-dir harvest --out-dir out
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import geopandas as gpd
import pandas as pd
from pyproj import Transformer
from shapely.geometry import (LineString, MultiLineString, MultiPolygon, Point,
                              Polygon, box)
from shapely.ops import linemerge, polylabel, transform as shp_transform, unary_union
from shapely.strtree import STRtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (line_length_m, load_config, log, ndjson_files, iter_ndjson,  # noqa: E402
                    parse_float, split_semicolon)

# ===========================================================================
# 1. DOCUMENTED THRESHOLDS
# Every value here is quoted in the README or in the constants table of the
# session review brief (s6.4). The citation is the comment; do not retune.
# ===========================================================================

SITE_MERGE_TOL_M = 150.0        # brief s6.4 SITE_MERGE_TOL - two polygons are one site
SITE_CATCHMENT_M = 250.0        # brief s6.4 SITE_CATCHMENT - an end terminates at a site
SITE_FENCE_TOL_M = 30.0         # brief s6.4 SITE_FENCE_TOL - an end is "at the fence" (decision 7)
FREE_END_MIN_M = 50.0           # brief s6.4 FREE_END_MIN - approach conductor vs switchyard jumper (decision 8)
BRIDGE_OUTSIDE_MAX_M = 50.0     # brief s6.4 BRIDGE_OUTSIDE_MAX - conductor length allowed outside two compounds (decision 5)
BRIDGE_GAP_MAX_M = 250.0        # brief s6.4 BRIDGE_GAP_MAX - two compounds can still be one site (decision 5)
JUNCTION_TOL_M = 25.0           # brief s6.4 JUNCTION_TOL - endpoints merge into a junction (README s6 deviation 3)
JUNCTION_EXT_M = 150.0          # brief s6.4 JUNCTION_EXT - extended junction reach (pitfall 23)
EE_TOL_FREE_M = 150.0           # brief s6.4 EE_TOL_FREE - end-to-end gap closed away from a substation (pitfall 22, decision 10)
EE_MOVE_MAX_M = 50.0            # brief s6.4 EE_MOVE_MAX - tips moved rather than bridged (pitfall 22)
COS_CONTINUE_MAX = -0.5         # brief s6.4 EE_COS_MIN / CHAIN_COS_MAX, +/-0.5 = 60 deg (decision 4, pitfall 25)
MAX_CLUSTER_M = 600.0           # brief s6.4 MAX_CLUSTER - junction cluster width limit (pitfall 16b)
EXT_MAX_CLUSTER_M = 250.0       # brief s6.4 EXT_MAX_CLUSTER - extended-union width limit (pitfall 23, decision 13)
JUNCTION_MOVE_MAX_M = 50.0      # pitfall 18 - endpoint moved onto the medoid only within 50 m
CROSS_COMPONENT_MERGE_M = 300.0 # pitfall 23 - two junctions merge at 300 m only across components
PARALLEL_REJECT_DEG = 25.0      # pitfall 14 / decision 9 - contact within 25 deg of parallel is rejected (mid-conductor only)
DC_MAX_CONVERTER_M = 10_000.0   # brief s6.4 DC_MAX_CONVERTER - converter left unattached beyond 10 km (pitfall 3)
DC_FAR_CONVERTER_M = 2_000.0    # pitfall 3 - converter over 2 km out is flagged converter_far
LENGTH_RETENTION_MIN = 0.999    # decision 14 / pitfall 16 - every geometry rebuild is length-checked at 99.9%
FRAGMENT_FLAG_COUNT = 20        # pitfall 13 / diagnostic 1 - an element producing >20 spans is a fragmentation flag
LONG_CONNECTOR_M = 1_000.0      # pitfall 19 - connectors over 1 km are flagged long_connector
SELF_LOOP_KEEP_FLAG_M = 1_000.0 # pitfall 2 - "33 genuine long loops are kept and flagged"; the length that makes a
                                # loop "genuine" is not stated in the README, so it is a named constant here and
                                # listed as a tie-break in README_pipeline.md. All self-loops leave the network
                                # layers either way (the acid test requires zero self-loops in ac_line_all).
PROXY_TOL_KV = 5.0              # reconstructed from the shipped dataset's line_type_proxy_* flags (README s5):
                                # a voltage within 5 kV of a type anchor uses that type without a proxy flag.
OUTWARD_SAMPLE_M = 50.0         # direction sampling distance for the 60 deg tests. Not stated in the README;
                                # tie-break, documented in README_pipeline.md.
CLUSTER_PAIR_LIMIT = 200        # guard against the quadratic-loop failure mode the brief warns about

# ---------------------------------------------------------------------------
# Standard conductor types (README s6.5: "Standard line types from PyPSA-Eur
# config.default.yaml"). Anchor voltage -> (type name, r ohm/km, x ohm/km,
# i_nom kA). Reconstructed from the shipped v23 dataset: every span's
# r_ohm * n_circuits / length_km equals the r below for its band, and the
# line_type_proxy_<anchor>kV flags identify the anchor set exactly.
# ---------------------------------------------------------------------------
LINE_TYPES: Dict[float, Tuple[str, float, float, float]] = {
    50.0:  ("94-AL1/15-ST1A 20.0", 0.306, 0.35, 0.35),
    63.0:  ("94-AL1/15-ST1A 20.0", 0.306, 0.35, 0.35),
    66.0:  ("94-AL1/15-ST1A 20.0", 0.306, 0.35, 0.35),
    90.0:  ("184-AL1/30-ST1A 110.0", 0.1571, 0.4, 0.535),
    110.0: ("184-AL1/30-ST1A 110.0", 0.1571, 0.4, 0.535),
    132.0: ("243-AL1/39-ST1A 110.0", 0.1188, 0.39, 0.645),
    150.0: ("243-AL1/39-ST1A 110.0", 0.1188, 0.39, 0.645),
    220.0: ("Al/St 240/40 2-bundle 220.0", 0.06, 0.301, 1.29),
    300.0: ("Al/St 240/40 3-bundle 300.0", 0.04, 0.265, 1.935),
    330.0: ("Al/St 240/40 3-bundle 300.0", 0.04, 0.265, 1.935),
    380.0: ("Al/St 240/40 4-bundle 380.0", 0.03, 0.246, 2.58),
    400.0: ("Al/St 240/40 4-bundle 380.0", 0.03, 0.246, 2.58),
    500.0: ("Al/St 240/40 4-bundle 380.0", 0.03, 0.246, 2.58),
    750.0: ("Al/St 560/50 4-bundle 750.0", 0.013, 0.276, 4.16),
}

# ---------------------------------------------------------------------------
# v23 banded transformer typing rule (README s13.1 table, with its provenance
# labels verbatim). band -> (selector test, s_nom MVA, x_pu, r_pu, basis text).
# x_pu / r_pu are per-unit on the transformer's own s_nom (PyPSA convention).
# ---------------------------------------------------------------------------
PYPSA_EUR_CFG_URL = ("https://github.com/PyPSA/pypsa-eur/blob/"
                     "8119040524b17f379d3ca0826b4c868a09c3fe2f/config/config.default.yaml#L485-L489")
PANDAPOWER_URL = "https://github.com/e2nIEE/pandapower/blob/v3.1.2/pandapower/std_types.py"
PYPSA_COMPONENTS_URL = "https://pypsa.readthedocs.io/en/latest/user-guide/components.html"
PYPSA_EUR_SNOM_URL = ("https://github.com/PyPSA/pypsa-eur/blob/"
                      "8119040524b17f379d3ca0826b4c868a09c3fe2f/scripts/build_osm_network.py#L1238-L1248")

TRANSFORMER_BANDS: List[Tuple[str, str, float, float, float, str, str]] = [
    ("R1", "lo>=200", 2000.0, 0.100, 0.0025,
     "x: pypsa-eur config default, applied unconditionally in base_network.py; "
     "s_nom inferred: config fallback value never applied to transformers in the cited osm "
     "workflow, assumed aggregate EHV bank capacity; r inferred: pandapower HV family",
     PYPSA_EUR_CFG_URL),
    ("R2", "100<=lo<200 and hi>=330", 500.0, 0.122, 0.0025,
     "x from vk 12.2% (impedance magnitude; reactance correction <3e-5 pu), r from vkr 0.25%: "
     "pandapower 160 MVA 380/110 kV; s_nom inferred: parallel banks",
     PANDAPOWER_URL + "#L998-L1015"),
    ("R3", "100<=lo<200 and 200<=hi<330", 300.0, 0.120, 0.0026,
     "x from vk 12.0% (impedance magnitude; reactance correction <3e-5 pu), r from vkr 0.26%: "
     "pandapower 100 MVA 220/110 kV; s_nom inferred: parallel banks",
     PANDAPOWER_URL + "#L1016-L1033"),
    ("R4", "100<=lo<200 and hi<200", 300.0, 0.100, 0.0025,
     "x: pypsa-eur default; r, s_nom inferred: no standard type exists at these ratios",
     PYPSA_EUR_CFG_URL),
    ("R5", "lo<100 and hi>=200", 200.0, 0.160, 0.0040,
     "inferred: extrapolated from pandapower 110/20 kV family (vk 16.2%, vkr 0.34%)",
     PANDAPOWER_URL + "#L1054-L1071"),
    ("R6", "lo<100 and hi<200", 120.0, 0.160, 0.0040,
     "inferred: same extrapolation as R5",
     PANDAPOWER_URL + "#L1054-L1071"),
]
TRANSFORMER_RATIO_ARTEFACT = 1.095   # README s13.1 - ratio below 1.095 is probably a voltage-tagging artefact

# Relation member roles that are not conductor geometry. README s6 deviation 6:
# an exclusion list, never an allow-list, because an allow-list drops every HVDC
# project that uses the `section` role.
EXCLUDED_MEMBER_ROLES = {
    "substation", "station", "converter", "terminal", "portal", "pylon", "tower",
    "support", "label", "transformer", "switch", "compensator", "plant", "generator",
}

INTERNAL_POWER_TAGS = {"busbar", "bay"}   # README s6.2 - dropped as internal substation elements
CONDUCTOR_POWER_TAGS = {"line", "cable", "minor_line"}


# ===========================================================================
# 2. SMALL GEOMETRY / BOOKKEEPING HELPERS
# ===========================================================================

class Ctx:
    """Everything a stage needs: config, projections, counters, stats."""

    def __init__(self, cfg: Dict[str, Any]) -> None:
        self.cfg = cfg
        self.to_m = Transformer.from_crs("EPSG:4326", cfg["metric_crs"], always_xy=True)
        self.to_deg = Transformer.from_crs(cfg["metric_crs"], "EPSG:4326", always_xy=True)
        self.stats: Dict[str, Any] = {}
        self.traction_hz = float(cfg["traction"]["frequency_hz"])
        self.traction_on = bool(cfg["traction"]["enabled"])
        # decision 1 - the voltage floor is config, never hardcoded: sub-transmission
        # is 110 kV in DE/PL/AT but 63/90 kV in FR, 60 in PT/DK, 66 in ES/NO, 70 in BE.
        self.floor_kv = float(cfg["voltage_floor_kv"])
        # duplicate multi-circuit relation collapse (README s12(b)); filled by
        # load_elements, consumed when the surviving record's circuits are set.
        self.dup_circuits: Dict[str, int] = {}
        self.dup_absorbed: Dict[str, List[str]] = {}
        self.dup_ambiguous: Set[str] = set()

    def m(self, geom):
        return shp_transform(lambda x, y, z=None: self.to_m.transform(x, y), geom)

    def deg(self, geom):
        return shp_transform(lambda x, y, z=None: self.to_deg.transform(x, y), geom)

    def hav(self, metric_geom) -> float:
        """Stored lengths are haversine on EPSG:4326 (README s12(c))."""
        return line_length_m(self.deg(metric_geom))


def plen(geom) -> float:
    """Planar length in the working metric CRS. Used only for ratio gates and
    thresholds, never for a stored length field."""
    return 0.0 if geom is None or geom.is_empty else geom.length


def outward_unit(coords: Sequence[Sequence[float]], at_start: bool) -> Tuple[float, float]:
    """Unit vector pointing away from one end of a conductor, sampled over the
    first OUTWARD_SAMPLE_M so a single short first segment cannot dominate.

    Used by the three 60 degree tests (decision 4 / pitfalls 21, 22, 25), which
    all compare the outward directions of two conductors at a shared point: a
    line running *through* the point has dot < -0.5, a pair folding back has dot
    near +1.
    """
    pts = list(coords) if at_start else list(reversed(coords))
    x0, y0 = pts[0]
    for x, y in pts[1:]:
        dx, dy = x - x0, y - y0
        d = math.hypot(dx, dy)
        if d >= OUTWARD_SAMPLE_M:
            return dx / d, dy / d
    x1, y1 = pts[-1]
    dx, dy = x1 - x0, y1 - y0
    d = math.hypot(dx, dy)
    return (0.0, 0.0) if d == 0 else (dx / d, dy / d)


def dot(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1]


def tangent_at(line: LineString, pt: Point) -> Tuple[float, float]:
    """Local direction of `line` at its nearest point to `pt`."""
    s = line.project(pt)
    a = line.interpolate(max(0.0, s - OUTWARD_SAMPLE_M / 2.0))
    b = line.interpolate(min(line.length, s + OUTWARD_SAMPLE_M / 2.0))
    dx, dy = b.x - a.x, b.y - a.y
    d = math.hypot(dx, dy)
    return (0.0, 0.0) if d == 0 else (dx / d, dy / d)


class UnionFind:
    def __init__(self, n: int) -> None:
        self.p = list(range(n))

    def find(self, a: int) -> int:
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a: int, b: int) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        # deterministic: smaller root wins, so numbering does not depend on order
        if rb < ra:
            ra, rb = rb, ra
        self.p[rb] = ra
        return True

    def groups(self) -> Dict[int, List[int]]:
        out: Dict[int, List[int]] = defaultdict(list)
        for i in range(len(self.p)):
            out[self.find(i)].append(i)
        return out


def osm_key(osm_id: str) -> Tuple[str, int]:
    """Sort key that orders way/relation ids numerically, not lexically. The
    primary element of a merged conductor is the numerically smallest id."""
    kind, _, num = osm_id.partition("/")
    return (kind, int(num) if num.isdigit() else 0)


def cluster_width(points: Sequence[Point]) -> float:
    """Cluster width = bounding-box diagonal. The metric the 600 m / 250 m caps
    are applied to (pitfalls 16b, 23)."""
    if len(points) < 2:
        return 0.0
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys))


def medoid(points: Sequence[Point]) -> Point:
    """Cluster representative = the member minimising total distance to the
    others. Always a real endpoint, so a chained cluster cannot place the node
    away from every member (pitfall 18)."""
    if len(points) == 1:
        return points[0]
    if len(points) > CLUSTER_PAIR_LIMIT:          # keep it linear-ish on pathological clusters
        cx = sum(p.x for p in points) / len(points)
        cy = sum(p.y for p in points) / len(points)
        return min(points, key=lambda p: (p.x - cx) ** 2 + (p.y - cy) ** 2)
    best, best_cost = points[0], float("inf")
    for p in points:
        cost = sum(p.distance(q) for q in points)
        if cost < best_cost:
            best, best_cost = p, cost
    return best


def single_linkage(points: Sequence[Point], tol: float, max_width: float,
                   seed: Optional[UnionFind] = None) -> UnionFind:
    """Single-linkage clustering with a width cap.

    Pairs are considered closest-first and a union is refused when the merged
    cluster would exceed `max_width` (pitfalls 16b and 23). Refusing a union is
    always safe; bursting a cluster into singletons is not, and is never done
    here (decision 13).
    """
    uf = seed or UnionFind(len(points))
    if not points:
        return uf
    tree = STRtree(points)
    pairs: List[Tuple[float, int, int]] = []
    for i, p in enumerate(points):
        for j in tree.query(p, predicate="dwithin", distance=tol):
            j = int(j)
            if j <= i:
                continue
            pairs.append((p.distance(points[j]), i, j))
    pairs.sort()
    # Membership must come from the SEED, not from singletons. Seeding with a
    # UnionFind and then assuming every point is its own cluster made the width
    # test measure the two root points instead of the merged cluster, so on the
    # extended pass a chain of endpoints could exceed max_width unchecked and
    # then fall to the post-hoc re-cluster - which is the bursting outcome
    # decision 13 exists to forbid (pitfall 23: components 3,820 -> 7,731).
    members: Dict[int, List[int]] = {r: list(m) for r, m in uf.groups().items()}
    for _d, i, j in pairs:
        ri, rj = uf.find(i), uf.find(j)
        if ri == rj:
            continue
        merged = members.get(ri, [ri]) + members.get(rj, [rj])
        if cluster_width([points[k] for k in merged]) > max_width:
            continue
        uf.union(i, j)
        root = uf.find(i)
        members.pop(ri, None)
        members.pop(rj, None)
        members[root] = merged
    return uf


# ===========================================================================
# 3. LOAD AND CLEAN  (README s6.2, s5, s7 pitfall 28, s12 frequency)
# ===========================================================================

def voltages_from_tags(tags: Dict[str, str], floor_kv: float) -> List[Tuple[float, int]]:
    """Every distinct voltage at or above the floor, with its index in the tag.

    Records carrying several semicolon-separated values are split into one
    record per voltage (paper Tables 2 and 3, README s6.2). The index is kept so
    circuits / cables / wires / frequency can be read positionally when the tag
    has the same arity.
    """
    out: List[Tuple[float, int]] = []
    seen: Set[float] = set()
    for idx, part in enumerate(split_semicolon(tags.get("voltage"))):
        v = parse_float(part)
        if v is None:
            continue
        kv = v / 1000.0
        if kv + 1e-9 < floor_kv or kv in seen:
            continue
        seen.add(kv)
        out.append((kv, idx))
    return out


def positional(tags: Dict[str, str], key: str, n_volt: int, idx: int) -> Optional[str]:
    """Read a possibly multi-value tag positionally against the voltage list.

    'circuits=2;1' on 'voltage=400000;110000' means 2 circuits at 400 kV and 1
    at 110 kV. Where the arities differ the tag cannot be split safely, so the
    whole value is returned and the caller treats it as applying to every
    voltage - the same choice the paper's Table 3 describes.
    """
    parts = split_semicolon(tags.get(key))
    if not parts:
        return None
    if len(parts) == n_volt and n_volt > 1:
        return parts[idx]
    return parts[0] if len(parts) == 1 else tags.get(key)


def circuits_from_tags(tags: Dict[str, str], n_volt: int, idx: int) -> Tuple[int, str]:
    """n_circuits and circuits_source (README s5 table).

    circuits tag -> tagged; else floor(cables/3); else floor(wires/3); else 1.
    Three cables make a three-phase circuit.
    """
    c = parse_float(positional(tags, "circuits", n_volt, idx))
    if c is not None and c >= 1:
        return int(c), "tagged"
    cab = parse_float(positional(tags, "cables", n_volt, idx))
    if cab is not None and cab >= 3:
        return max(1, int(cab // 3)), "derived_from_cables_tag"
    wir = parse_float(positional(tags, "wires", n_volt, idx))
    if wir is not None and wir >= 3:
        return max(1, int(wir // 3)), "derived_from_wires_tag"
    return 1, "assumed_single_circuit"


def construction_from_tags(tags: Dict[str, str],
                           member_types: Optional[List[str]] = None) -> Tuple[str, str]:
    """construction_type (5 states) and construction_source (README s4, pitfall 28).

    Precedence, most specific tag first: an explicit `location`, then `tunnel`,
    then `power=cable`, then `power=line`, then - for a route relation with no
    conductor tag of its own - the types of its member ways, which is what took
    unknown from 205,188 km to 2,116 km. `unknown` is a real answer and is never
    replaced by a guess.
    """
    loc = (tags.get("location") or "").strip().lower()
    if loc in ("underground", "underwater", "submarine", "overhead", "surface"):
        if loc == "underground":
            return "underground_cable", "osm_location_tag"
        if loc in ("underwater", "submarine"):
            return "submarine_cable", "osm_location_tag"
        return "overhead_line", "osm_location_tag"
    if (tags.get("tunnel") or "").strip().lower() in ("yes", "building_passage", "culvert"):
        return "underground_cable", "osm_tunnel_tag"
    power = (tags.get("power") or "").strip().lower()
    if power == "cable":
        return "underground_cable", "osm_power_cable"
    if power in ("line", "minor_line"):
        return "overhead_line", "osm_power_line"
    if member_types:
        kinds = set(member_types)
        kinds.discard("unknown")
        if not kinds:
            return "unknown", "not_tagged"
        if len(kinds) == 1:
            return kinds.pop(), "derived_from_member_ways"
        return "mixed", "derived_from_member_ways"
    return "unknown", "not_tagged"


def frequency_from_tags(ctx: Ctx, tags: Dict[str, str], kv: float, n_volt: int, idx: int,
                        countries: str) -> Tuple[float, str, List[str]]:
    """frequency_hz, frequency_source and any qa flags (README s12).

    Precedence, exactly as v22 applied it: a pure OSM frequency tag first, then
    operator inference, which is gated to <= traction.max_voltage_kv in the
    configured traction countries with a known traction operator token; an
    explicit frequency=50 vetoes inference. A shared-tower tag such as
    '50;16.7' is kept wholly at the public-grid frequency and flagged, because
    its traction circuits are not separable.
    """
    tcfg = ctx.cfg["traction"]
    grid_hz = float(ctx.cfg["grid_frequency_hz"])
    traction_tags = {str(t) for t in tcfg["frequency_tags"]}
    raw = positional(tags, "frequency", n_volt, idx)
    parts = split_semicolon(raw)
    flags: List[str] = []

    if not parts:
        # No tag at all. AC is assumed and the assumption is flagged: over half
        # the reference network carries frequency_assumed_ac (README s6.9).
        return grid_hz, "no_frequency_tag", ["frequency_assumed_ac"]

    norm = [p.strip() for p in parts]
    is_traction = [p in traction_tags for p in norm]
    if len(norm) > 1 and any(is_traction):
        return grid_hz, f"osm_mixed_{';'.join(norm)}_kept_{grid_hz:g}", \
            ["shared_tower_mixed_frequency_kept_grid"]
    if all(is_traction) and ctx.traction_on:
        if kv > float(tcfg["max_voltage_kv"]):
            # An EHV traction tag is not credible: traction networks do not run
            # above the configured ceiling (README s12, the 170 kV Swedish row).
            return grid_hz, "osm_frequency_tag_traction_overridden_ehv_gate", \
                ["frequency_tag_conflict_ehv"]
        return ctx.traction_hz, "osm_frequency_tag", flags
    if all(is_traction) and not ctx.traction_on:
        return grid_hz, "traction_disabled_in_config_kept_grid", [f"nonstandard_frequency_tag_kept_{grid_hz:g}"]

    val = parse_float(norm[0])
    if val is not None and abs(val - grid_hz) < 1e-6:
        return grid_hz, f"osm_frequency_tag_{int(grid_hz)}", flags
    if val is not None and val == 0.0:
        return 0.0, "osm_frequency_tag_0_dc", flags        # handled as DC upstream
    # Any other tagged value (60 Hz in a 50 Hz region, an unparseable string):
    # kept at the grid frequency and flagged rather than trusted.
    return grid_hz, "nonstandard_frequency_tag_kept_grid", [f"nonstandard_frequency_tag_kept_{grid_hz:g}"]


def operator_traction_override(ctx: Ctx, rec: Dict[str, Any]) -> None:
    """Operator inference for traction, applied only where OSM is silent.

    Gate (README s12): <= traction.max_voltage_kv, country in the configured
    traction list, and every operator token a known traction system. An explicit
    frequency tag has already decided the row and is never overridden here.
    """
    tcfg = ctx.cfg["traction"]
    if not ctx.traction_on or rec["frequency_source"] != "no_frequency_tag":
        return
    if rec["voltage_kv"] > float(tcfg["max_voltage_kv"]):
        return
    countries = set(split_semicolon(rec.get("countries")))
    allowed = set(tcfg["countries"])
    if allowed and (not countries or not countries.issubset(allowed)):
        return
    ops = [o.strip().lower() for o in split_semicolon(rec.get("operator")) if o.strip()]
    if not ops:
        return
    known = [str(o).lower() for o in tcfg["operators"]]
    if not known or not all(any(k in o for k in known) for o in ops):
        return
    rec["frequency_hz"] = ctx.traction_hz
    rec["frequency_source"] = "operator_inferred"
    rec["qa"].discard("frequency_assumed_ac")


def is_under_construction(tags: Dict[str, str]) -> bool:
    """README s7 pitfall 8 - under-construction spans stay in the totals, flagged."""
    if (tags.get("power") or "") == "construction":
        return True
    for key in ("construction", "construction:power", "proposed", "proposed:power"):
        if tags.get(key):
            return True
    return (tags.get("location:transition") or "") == "construction"


def load_elements(ctx: Ctx, paths: List[str]) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """NDJSON -> (conductor records, substation records, dc records).

    One record per (element, voltage). Relations replace their member ways only
    where the members merge into one continuous LineString (README s6.3);
    otherwise the relation is dropped in favour of the ways, unless no member way
    survived the voltage filter, in which case the relation's parts are kept so
    geometry is not silently lost.
    """
    raw: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for el in iter_ndjson(paths):
        oid = f"{el['type']}/{el['id']}"
        if oid in raw:                      # a chunk overlap, or the same element in both passes
            prev = raw[oid]
            if len(json.dumps(el)) > len(json.dumps(prev)):
                raw[oid] = el               # keep the richer copy (full geometry)
            continue
        raw[oid] = el
        order.append(oid)
    log(f"  {len(order)} distinct OSM elements harvested")

    scope = None
    if ctx.cfg.get("scope_bbox"):
        s, w, n, e = [float(v) for v in ctx.cfg["scope_bbox"]]
        scope = box(w, s, e, n)             # README s12(a): study-area clip, config-driven

    # --- geometry per element, in EPSG:4326 first so the scope test is cheap
    way_geom: Dict[str, LineString] = {}
    substations: List[Dict] = []
    rel_parts: Dict[str, List[LineString]] = {}
    rel_member_ways: Dict[str, List[str]] = {}
    poly_members: Dict[str, List[Sequence[Sequence[float]]]] = {}

    for oid in order:
        el = raw[oid]
        tags = el.get("tags") or {}
        power = (tags.get("power") or "").strip().lower()
        if power in INTERNAL_POWER_TAGS:
            continue                        # README s6.2 - busbars and bays dropped
        if el["type"] == "way":
            coords = el.get("geometry") or []
            if len(coords) < 2:
                continue
            if power == "substation":
                poly_members[oid] = [coords]
                continue
            way_geom[oid] = LineString(coords)
        else:
            parts: List[LineString] = []
            members: List[str] = []
            for m in el.get("members") or []:
                if (m.get("role") or "").strip().lower() in EXCLUDED_MEMBER_ROLES:
                    continue
                g = m.get("geometry")
                if m.get("type") == "way" and m.get("ref") is not None:
                    members.append(f"way/{m['ref']}")
                if g and len(g) >= 2:
                    parts.append(LineString(g))
            if power == "substation":
                if parts:
                    poly_members[oid] = [list(p.coords) for p in parts]
                continue
            if parts:
                rel_parts[oid] = parts
                rel_member_ways[oid] = members

    # --- substation polygons (README s7 pitfall 9: convex hull where no ring)
    hull_count = 0
    for oid, rings in poly_members.items():
        tags = raw[oid].get("tags") or {}
        poly, used_hull = build_polygon(rings)
        if poly is None:
            continue
        if used_hull:
            hull_count += 1
        if scope is not None and not scope.intersects(poly):
            continue
        substations.append({
            "osm_id": oid,
            "name": tags.get("name"),
            "operator": tags.get("operator"),
            "voltage_kv": _first_voltage_kv(tags),
            "under_construction": is_under_construction(tags),
            "geom_deg": poly,
            "used_hull": used_hull,
        })
    ctx.stats["substation_convex_hulls"] = hull_count

    # --- relations replace their member ways where they merge cleanly
    superseded: Set[str] = set()
    rel_geoms: Dict[str, List[LineString]] = {}
    merged_rel = dropped_rel = 0
    for oid, parts in rel_parts.items():
        merged = linemerge(parts) if len(parts) > 1 else parts[0]
        if merged.geom_type == "LineString":
            rel_geoms[oid] = [merged]
            superseded.update(rel_member_ways[oid])
            merged_rel += 1
        else:
            present = [w for w in rel_member_ways[oid] if w in way_geom]
            if present:
                dropped_rel += 1            # keep the ways, drop the relation (README s6.3)
                continue
            # No member way survived the voltage filter: keep the relation's
            # strands rather than lose the geometry. Tie-break, documented.
            rel_geoms[oid] = [g for g in merged.geoms if g.geom_type == "LineString"]
            merged_rel += 1
    ctx.stats["relations_merged"] = merged_rel
    ctx.stats["relations_dropped_for_ways"] = dropped_rel

    # --- collapse duplicate multi-circuit relations (README s12(b))
    # A multi-circuit corridor is routinely mapped as one route=power relation per
    # circuit over the SAME member ways. Left alone, each relation ships as a
    # full-length span on identical geometry, double-counting route-km and
    # under-stating impedance - the v22 defect (489 groups, 505 rows, ~2,894 km
    # removed). Collapse to one survivor per member-way set and carry the circuit
    # count; where the duplicates disagree on parameters, keep the survivor and
    # flag it rather than silently picking one.
    # The key includes the VOLTAGE tag. Keying on member ways alone collapsed a
    # mixed-voltage shared-pylon line - two relations over the same towers at, say,
    # 400 and 220 kV, which is standard OSM mapping - into a single 400 kV row,
    # deleting the entire 220 kV circuit, its buses and its layer. Two relations are
    # duplicates only if they are the same corridor at the same voltage.
    by_members: Dict[Tuple[Any, ...], List[str]] = defaultdict(list)
    for oid in list(rel_geoms):
        ways = tuple(sorted(rel_member_ways.get(oid, [])))
        if ways:                                 # a relation with no member ways cannot duplicate
            volt = (raw.get(oid, {}).get("tags") or {}).get("voltage")
            by_members[(ways, volt)].append(oid)
    collapsed_groups = collapsed_rows = ambiguous = 0
    dup_circuits: Dict[str, int] = {}
    dup_absorbed: Dict[str, List[str]] = {}
    dup_ambiguous: Set[str] = set()
    for key, oids in by_members.items():
        if len(oids) < 2:
            continue
        oids = sorted(oids, key=osm_key)         # deterministic survivor: smallest id
        keep, drop = oids[0], oids[1:]
        # Voltage is already equal by construction; disagreement on circuits or
        # operator means the group is not cleanly one corridor, so the survivor is
        # flagged rather than silently standing in for the others.
        tagsets = [(raw.get(o, {}).get("tags") or {}) for o in oids]
        disagree = (len({t.get("circuits") for t in tagsets}) > 1 or
                    len({t.get("cables") for t in tagsets}) > 1 or
                    len({t.get("operator") for t in tagsets}) > 1)
        collapsed_groups += 1
        collapsed_rows += len(drop)
        dup_circuits[keep] = len(oids)
        dup_absorbed[keep] = drop
        if disagree:
            ambiguous += 1
            dup_ambiguous.add(keep)
        for o in drop:
            rel_geoms.pop(o, None)
            superseded.add(o)
    ctx.stats["duplicate_relation_groups_collapsed"] = collapsed_groups
    ctx.stats["duplicate_relation_rows_removed"] = collapsed_rows
    ctx.stats["duplicate_relation_groups_ambiguous"] = ambiguous
    ctx.dup_circuits = dup_circuits
    ctx.dup_absorbed = dup_absorbed
    ctx.dup_ambiguous = dup_ambiguous

    # --- member-way construction types, for relations with no tag of their own
    member_ctype: Dict[str, List[str]] = {}
    for oid in rel_geoms:
        kinds = []
        for w in rel_member_ways.get(oid, []):
            wt = (raw.get(w, {}).get("tags") or {})
            if wt:
                kinds.append(construction_from_tags(wt)[0])
        member_ctype[oid] = kinds

    # --- one record per (element, voltage)
    conductors: List[Dict] = []
    dc_records: List[Dict] = []
    for oid in order:
        if oid in superseded or oid not in raw:
            continue
        geoms = rel_geoms.get(oid) or ([way_geom[oid]] if oid in way_geom else None)
        if not geoms:
            continue
        el = raw[oid]
        tags = el.get("tags") or {}
        if scope is not None:
            geoms = [g for g in geoms if scope.intersects(g)]
            if not geoms:
                continue
        ctype, csrc = construction_from_tags(tags, member_ctype.get(oid))
        freq_raw = split_semicolon(tags.get("frequency"))
        is_dc = bool(freq_raw) and all(parse_float(f) == 0.0 for f in freq_raw)
        is_dc = is_dc or oid in set(ctx.cfg.get("dc_reclassify_osm_ids") or [])
        if is_dc:
            for gi, g in enumerate(geoms):
                dc_records.append({
                    "osm_id": oid, "part": gi, "name": tags.get("name"),
                    "voltage_kv": _first_voltage_kv(tags),
                    "geom_deg": g, "operator": tags.get("operator"),
                    "qa": set(), "under_construction": is_under_construction(tags),
                })
            continue
        vlist = voltages_from_tags(tags, ctx.floor_kv)
        if not vlist:
            continue                        # README s6 deviation 5: no voltage tag, no record
        for kv, idx in vlist:
            for gi, g in enumerate(geoms):
                ncirc, csrc_c = circuits_from_tags(tags, len(vlist), idx)
                dupn = ctx.dup_circuits.get(oid)
                if dupn:
                    # This relation is the survivor of a duplicate group over the
                    # same member ways: one physical corridor, dupn mapped circuits.
                    ncirc = max(ncirc, dupn)
                    csrc_c = "duplicate_relation_group_collapsed"
                hz, hsrc, hflags = frequency_from_tags(ctx, tags, kv, len(vlist), idx, "")
                if dupn and oid in ctx.dup_ambiguous:
                    # After the frequency call, not before: appending to hflags first
                    # discarded the flag on the next line and left hflags unbound when
                    # the ambiguous survivor was the first record reached.
                    hflags = list(hflags) + ["circuit_count_element_level_ambiguous"]
                if hz == 0.0:               # frequency=0 on one value of a multi-value tag
                    continue
                rec = {
                    "elem_id": oid, "part": gi, "osm_id": oid,
                    "contains": [oid] + ctx.dup_absorbed.get(oid, []),
                    "n_ways_merged": 1,
                    "voltage_kv": kv, "n_circuits": ncirc, "circuits_source": csrc_c,
                    "construction_type": ctype, "construction_source": csrc,
                    "under_construction": is_under_construction(tags),
                    "frequency_hz": hz, "frequency_source": hsrc,
                    "name": tags.get("name"), "ref": tags.get("ref"),
                    "operator": tags.get("operator"),
                    "geom_deg": g, "qa": set(hflags),
                }
                conductors.append(rec)
    log(f"  {len(conductors)} conductor records, {len(substations)} substation polygons, "
        f"{len(dc_records)} dc records")
    return conductors, substations, dc_records


def _first_voltage_kv(tags: Dict[str, str]) -> Optional[int]:
    vals = [parse_float(p) for p in split_semicolon(tags.get("voltage"))]
    vals = [v for v in vals if v]
    return int(round(max(vals) / 1000.0)) if vals else None


def build_polygon(rings: List[Sequence[Sequence[float]]]) -> Tuple[Optional[Polygon], bool]:
    """Substation footprint from way rings or relation members.

    A closed ring becomes the polygon. Members that do not form a ring get a
    convex hull, which over-covers concave sites - README s7 pitfall 9 records
    1,526 of 37,729 records doing this, and notes it affects site extent only,
    because bus placement uses busbar centroids.
    """
    best: Optional[Polygon] = None
    for coords in rings:
        if len(coords) >= 4 and coords[0] == coords[-1]:
            try:
                p = Polygon(coords)
                if p.is_valid and p.area > 0:
                    if best is None or p.area > best.area:
                        best = p
            except Exception:               # noqa: BLE001 - degenerate ring, fall through to hull
                pass
    if best is not None:
        return best, False
    pts = [tuple(c) for coords in rings for c in coords]
    if len(pts) < 3:
        return None, False
    hull = MultiLineString([LineString(coords) for coords in rings if len(coords) >= 2]).convex_hull
    if hull.geom_type != "Polygon" or hull.area <= 0:
        return None, False
    return hull, True


# ===========================================================================
# 4. COUNTRY ASSIGNMENT (config-driven; no region assumptions)
# ===========================================================================

def assign_countries(ctx: Ctx, records: List[Dict], geom_key: str = "geom_deg") -> None:
    """Fill `countries` from the configured source.

    polygons: a spatial join against a config polygon file, semicolon-joined and
    sorted where a conductor crosses a border (which is also how
    `is_cross_border` is recovered - README s4 field list).
    osm_tag:  the element's own addr:country / country tag.
    none:     empty, which is honest for a region with no boundary file.
    """
    src = ctx.cfg["country_source"]
    if src == "none" or not records:
        for r in records:
            r.setdefault("countries", "")
        return
    if src == "osm_tag":
        for r in records:
            r["countries"] = r.get("osm_country") or ""
        return
    path = ctx.cfg["country_polygons"]
    if not path or not os.path.exists(path):
        raise SystemExit(f"country_source=polygons but country_polygons missing: {path}")
    field = ctx.cfg["country_field"]
    cdf = gpd.read_file(path).to_crs("EPSG:4326")
    if field not in cdf.columns:
        raise SystemExit(f"{path}: country_field '{field}' not in {list(cdf.columns)}")
    tree = STRtree(list(cdf.geometry.values))
    names = list(cdf[field].astype(str).values)
    for r in records:
        g = r[geom_key]
        hits = tree.query(g, predicate="intersects")
        got = sorted({names[int(i)] for i in hits})
        r["countries"] = ";".join(got)


# ===========================================================================
# 5. CHAIN MERGE  (decision 4 / README s7 pitfall 25 - the fold-back trap)
# ===========================================================================

def endpoint_key(pt: Tuple[float, float]) -> Tuple[int, int]:
    """Coincidence key at 1 cm in the working CRS. Ways that genuinely connect in
    OSM share a node exactly (README s6 deviation 3)."""
    return (int(round(pt[0] * 100)), int(round(pt[1] * 100)))


def chain_params(rec: Dict) -> Tuple:
    """The parameter tuple that must match for two conductors to be one chain."""
    return (rec["voltage_kv"], rec["n_circuits"], rec["frequency_hz"],
            rec["construction_type"], rec["under_construction"])


def merge_chains(ctx: Ctx, conductors: List[Dict]) -> List[Dict]:
    """Merge conductor chains across pass-through nodes with matching parameters.

    THE GATE (decision 4, pitfall 25): the two conductors' outward directions at
    the shared node must be roughly opposite - dot < -0.5, a turn of 60 degrees
    or less. A double-circuit route mapped as two relations on the same pylons
    leaves the node in the *same* direction (dot near +1) and must not be
    merged; merging it produced a 97.85 km out-and-back conductor that later set
    operations shredded into 529 tower-length fragments.
    """
    ends: Dict[Tuple[int, int], List[Tuple[int, int]]] = defaultdict(list)
    for i, rec in enumerate(conductors):
        coords = list(rec["geom"].coords)
        ends[endpoint_key(coords[0])].append((i, 0))
        ends[endpoint_key(coords[-1])].append((i, 1))

    link: Dict[Tuple[int, int], Tuple[int, int]] = {}
    refused_foldback = 0
    candidates = 0
    for key, items in ends.items():
        if len(items) != 2:
            continue                     # a real tap (3+) is not a pass-through node
        (i, ei), (j, ej) = items
        if i == j:
            continue                     # closed ring; left alone
        if chain_params(conductors[i]) != chain_params(conductors[j]):
            continue
        candidates += 1
        di = outward_unit(list(conductors[i]["geom"].coords), at_start=(ei == 0))
        dj = outward_unit(list(conductors[j]["geom"].coords), at_start=(ej == 0))
        if dot(di, dj) >= COS_CONTINUE_MAX:
            refused_foldback += 1        # fold-back pair: refuse, cost is one extra span
            continue
        link[(i, ei)] = (j, ej)
        link[(j, ej)] = (i, ei)
    ctx.stats["chain_candidate_nodes"] = candidates
    ctx.stats["chain_refused_foldback"] = refused_foldback

    # walk maximal chains
    used: Set[int] = set()
    out: List[Dict] = []
    for start in range(len(conductors)):
        if start in used:
            continue
        # find a chain terminus by walking backwards from the start conductor
        head, head_end = start, 0
        seen = {start}
        while (head, head_end) in link:
            nxt, nxt_end = link[(head, head_end)]
            if nxt in seen:
                break
            seen.add(nxt)
            head, head_end = nxt, 1 - nxt_end
        # Walk forward collecting the chain in order. cur_end is the end we
        # LEAVE by, so the conductor is traversed in its own direction exactly
        # when that end is its end 1.
        chain: List[Tuple[int, bool]] = []
        cur, cur_end = head, 1 - head_end
        while True:
            chain.append((cur, cur_end == 1))
            used.add(cur)
            if (cur, cur_end) not in link:
                break
            nxt, nxt_end = link[(cur, cur_end)]
            if nxt in used:
                break
            cur, cur_end = nxt, 1 - nxt_end
        out.append(_fuse(ctx, conductors, chain))
    log(f"  chain merge: {len(conductors)} -> {len(out)} conductors "
        f"({refused_foldback} fold-back merges refused of {candidates} candidate nodes)")
    return out


def _fuse(ctx: Ctx, conductors: List[Dict], chain: List[Tuple[int, bool]]) -> Dict:
    """Concatenate a chain into one conductor, with a length check (decision 14).

    The check is two-sided. A rebuild that GAINS length is the fold-back
    signature - two circuits fused into one out-and-back conductor - and is as
    much a defect as one that loses length (pitfall 25).
    """
    if len(chain) == 1:
        return conductors[chain[0][0]]
    coords: List[Tuple[float, float]] = []
    before = 0.0
    members: List[str] = []
    qa: Set[str] = set()
    for ci, forward in chain:
        rec = conductors[ci]
        before += plen(rec["geom"])
        members.extend(rec["contains"])
        qa |= rec["qa"]
        cs = list(rec["geom"].coords)
        if not forward:
            cs = list(reversed(cs))
        if coords:
            if endpoint_key(coords[-1]) != endpoint_key(cs[0]):
                raise SystemExit(f"chain merge misordered at {rec['osm_id']}: "
                                 f"{coords[-1]} -> {cs[0]}")
            cs = cs[1:]
        coords.extend(cs)
    geom = LineString(coords)
    if not (before * LENGTH_RETENTION_MIN <= plen(geom) <= before / LENGTH_RETENTION_MIN):
        raise SystemExit(f"chain merge changed length: {plen(geom):.1f} vs {before:.1f} m")
    primary = min((conductors[ci] for ci, _f in chain), key=lambda r: osm_key(r["osm_id"]))
    out = dict(primary)
    out["geom"] = geom
    out["contains"] = sorted(set(members))
    out["n_ways_merged"] = len(out["contains"])
    out["qa"] = qa
    return out


# ===========================================================================
# 6. END-TO-END JOIN  (decision 10 / pitfall 22) then SNAP/SPLIT (pitfalls 11, 14)
# ===========================================================================

def end_to_end_pass(ctx: Ctx, conductors: List[Dict], site_union) -> None:
    """Close head-on gaps between two conductor tips, before clipping.

    Gates, all documented (pitfall 22): same voltage and frequency; both tips
    more than SITE_CATCHMENT_M from any substation, because nearer than that the
    site catchment already resolves the pair; the two stubs pointing at each
    other within 60 degrees; one join per end, closest first, so nothing chains.
    Under EE_MOVE_MAX_M both tips move to the midpoint; above it an explicit
    vertex bridges the gap, up to the EE_TOL_FREE_M ceiling - which sits below
    one tower span, past which bridging would invent a conductor.
    """
    pts: List[Point] = []
    owner: List[Tuple[int, int]] = []
    for i, rec in enumerate(conductors):
        cs = list(rec["geom"].coords)
        pts.append(Point(cs[0]))
        owner.append((i, 0))
        pts.append(Point(cs[-1]))
        owner.append((i, 1))
    if not pts:
        return
    near_site: List[bool] = [False] * len(pts)
    if site_union is not None and not site_union.is_empty:
        stree = STRtree(list(site_union.geoms) if site_union.geom_type.startswith("Multi")
                        else [site_union])
        for k, p in enumerate(pts):
            near_site[k] = len(stree.query(p, predicate="dwithin",
                                           distance=SITE_CATCHMENT_M)) > 0

    tree = STRtree(pts)
    cand: List[Tuple[float, int, int]] = []
    for k, p in enumerate(pts):
        if near_site[k]:
            continue
        for l in tree.query(p, predicate="dwithin", distance=EE_TOL_FREE_M):
            l = int(l)
            if l <= k or near_site[l]:
                continue
            i, ei = owner[k]
            j, ej = owner[l]
            if i == j:
                continue
            a, b = conductors[i], conductors[j]
            if (a["voltage_kv"], a["frequency_hz"]) != (b["voltage_kv"], b["frequency_hz"]):
                continue
            gap = p.distance(pts[l])
            if gap <= 0.01:
                continue                # already a shared node; chain merge dealt with it
            di = outward_unit(list(a["geom"].coords), at_start=(ei == 0))
            dj = outward_unit(list(b["geom"].coords), at_start=(ej == 0))
            if dot(di, dj) >= COS_CONTINUE_MAX:
                continue                # not head-on: joining would fabricate a connection
            cand.append((gap, k, l))
    cand.sort()

    consumed: Set[int] = set()
    moved = bridged = 0
    for gap, k, l in cand:
        if k in consumed or l in consumed:
            continue
        i, ei = owner[k]
        j, ej = owner[l]
        pi, pj = pts[k], pts[l]
        if gap <= EE_MOVE_MAX_M:
            mid = ((pi.x + pj.x) / 2.0, (pi.y + pj.y) / 2.0)
            _set_endpoint(conductors[i], ei, mid)
            _set_endpoint(conductors[j], ej, mid)
            moved += 1
        else:
            _append_endpoint(conductors[i], ei, (pj.x, pj.y))
            conductors[i]["qa"].add("end_bridged_synthetic_vertex")
            bridged += 1
        pts[k] = Point(list(conductors[i]["geom"].coords)[0 if ei == 0 else -1])
        pts[l] = Point(list(conductors[j]["geom"].coords)[0 if ej == 0 else -1])
        consumed.add(k)
        consumed.add(l)
    ctx.stats["ee_moved"] = moved
    ctx.stats["ee_bridged"] = bridged
    # cand already passed the head-on test, so this is the one-join-per-end drop
    # count, not the head-on rejection count. Named for what it measures.
    ctx.stats["ee_dropped_one_join_per_end"] = max(0, len(cand) - moved - bridged)
    log(f"  end-to-end pass: {moved} tips moved to midpoint, {bridged} bridged with a vertex")


def _set_endpoint(rec: Dict, end: int, xy: Tuple[float, float]) -> None:
    cs = list(rec["geom"].coords)
    cs[0 if end == 0 else -1] = xy
    rec["geom"] = LineString(cs)


def _append_endpoint(rec: Dict, end: int, xy: Tuple[float, float]) -> None:
    cs = list(rec["geom"].coords)
    if end == 0:
        cs.insert(0, xy)
    else:
        cs.append(xy)
    rec["geom"] = LineString(cs)


def snap_split_pass(ctx: Ctx, conductors: List[Dict]) -> List[Dict]:
    """Snap a dangling end onto the interior of another same-voltage conductor
    and split that conductor there, creating a real T-junction.

    THE ORDER MATTERS (decision 9 / pitfall 21): the end-to-end case has already
    run and is exempt. The 25-degree parallel rejection applies ONLY here, to a
    contact landing in the *middle* of a conductor, because a real tap arrives at
    an angle whereas a duplicate circuit runs alongside. Applied to end-to-end
    contacts it refused every genuine join.
    Only same-voltage conductors are joined (pitfall 11).
    """
    geoms = [r["geom"] for r in conductors]
    tree = STRtree(geoms)
    cuts: Dict[int, List[float]] = defaultdict(list)
    snapped = rejected_parallel = 0
    for i, rec in enumerate(conductors):
        cs = list(rec["geom"].coords)
        for ei, pt in ((0, Point(cs[0])), (1, Point(cs[-1]))):
            best: Optional[Tuple[float, int, float]] = None
            for j in tree.query(pt, predicate="dwithin", distance=JUNCTION_TOL_M):
                j = int(j)
                if j == i:
                    continue
                other = conductors[j]
                if (other["voltage_kv"], other["frequency_hz"]) != \
                        (rec["voltage_kv"], rec["frequency_hz"]):
                    continue
                s = geoms[j].project(pt)
                if s <= JUNCTION_TOL_M or s >= geoms[j].length - JUNCTION_TOL_M:
                    continue            # an end-to-end contact, already handled
                d = geoms[j].interpolate(s).distance(pt)
                if best is None or d < best[0]:
                    best = (d, j, s)
            if best is None:
                continue
            _d, j, s = best
            arrival = outward_unit(list(rec["geom"].coords), at_start=(ei == 0))
            arrival = (-arrival[0], -arrival[1])
            tan = tangent_at(geoms[j], Point(cs[0] if ei == 0 else cs[-1]))
            # Angle between the arriving conductor and the target's local
            # direction, folded to 0-90 deg. Near 0 the two run alongside each
            # other, which is a duplicate circuit, not a tap: reject. A real tap
            # arrives at an angle (pitfall 14).
            ang = math.degrees(math.acos(max(-1.0, min(1.0, abs(dot(arrival, tan))))))
            if ang < PARALLEL_REJECT_DEG:
                rejected_parallel += 1
                continue
            target = geoms[j].interpolate(s)
            _set_endpoint(rec, ei, (target.x, target.y))
            cuts[j].append(s)
            snapped += 1
    ctx.stats["snapped_ends"] = snapped
    ctx.stats["snap_rejected_parallel"] = rejected_parallel

    out: List[Dict] = []
    for j, rec in enumerate(conductors):
        if j not in cuts:
            out.append(rec)
            continue
        parts = split_line_at(rec["geom"], sorted(set(cuts[j])))
        before = plen(rec["geom"])
        after = sum(plen(p) for p in parts)
        if after < before * LENGTH_RETENTION_MIN:
            raise SystemExit(f"snap split lost length on {rec['osm_id']}: {after} < {before}")
        for p in parts:
            child = dict(rec)
            child["geom"] = p
            child["qa"] = set(rec["qa"])
            out.append(child)
    log(f"  snap/split: {snapped} ends snapped, {rejected_parallel} rejected as parallel, "
        f"{len(cuts)} conductors split")
    return out


def split_line_at(line: LineString, dists: List[float]) -> List[LineString]:
    """Split a LineString at a sorted list of distances along it."""
    coords = list(line.coords)
    out: List[LineString] = []
    cur = [coords[0]]
    run = 0.0
    di = 0
    for a, b in zip(coords, coords[1:]):
        seg = math.dist(a, b)
        while di < len(dists) and run < dists[di] <= run + seg + 1e-9:
            t = (dists[di] - run) / seg if seg else 0.0
            pt = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            if math.dist(cur[-1], pt) > 1e-9:
                cur.append(pt)
            if len(cur) >= 2:
                out.append(LineString(cur))
            cur = [pt]
            di += 1
        run += seg
        if math.dist(cur[-1], b) > 1e-9:
            cur.append(b)
    if len(cur) >= 2:
        out.append(LineString(cur))
    return out or [line]


# ===========================================================================
# 7. SITES  (decisions 3, 5, 6 / pitfalls 1, 27)
# ===========================================================================

def build_sites(ctx: Ctx, substations: List[Dict], conductors: List[Dict]) -> List[Dict]:
    """Fuse substation polygons into physical sites.

    Two merge paths, and the difference between them is decision 6:
      * proximity - polygons within SITE_MERGE_TOL_M are one site. No name test:
        applying one here blocked 1,488 merges, 983 with no conductor between the
        polygons, and took working sites apart.
      * conductor path - a conductor touching both polygons merges them only if
        it runs no more than BRIDGE_OUTSIDE_MAX_M outside the two polygons AND
        the polygons are within BRIDGE_GAP_MAX_M of each other (decision 5), and
        only if the name test passes: refuse where both are named and neither
        name contains the other. Without this, every real link between two
        neighbouring substations fused them (Levallois/Perret).
    """
    n = len(substations)
    uf = UnionFind(n)
    polys = [s["geom"] for s in substations]
    if n:
        tree = STRtree(polys)
        for i, p in enumerate(polys):
            for j in tree.query(p, predicate="dwithin", distance=SITE_MERGE_TOL_M):
                j = int(j)
                if j > i:
                    uf.union(i, j)
        merged_by_conductor = refused_name = refused_geom = 0
        for rec in conductors:
            g = rec["geom"]
            hits = [int(k) for k in tree.query(g, predicate="intersects")]
            if len(hits) < 2:
                continue
            for a in range(len(hits)):
                for b in range(a + 1, len(hits)):
                    i, j = hits[a], hits[b]
                    if uf.find(i) == uf.find(j):
                        continue
                    pair = unary_union([polys[i], polys[j]])
                    outside = plen(g.difference(pair))
                    if outside > BRIDGE_OUTSIDE_MAX_M or \
                            polys[i].distance(polys[j]) > BRIDGE_GAP_MAX_M:
                        refused_geom += 1
                        continue
                    if _name_conflict(substations[i].get("name"), substations[j].get("name")):
                        refused_name += 1
                        continue
                    uf.union(i, j)
                    merged_by_conductor += 1
        ctx.stats["site_merged_by_conductor"] = merged_by_conductor
        ctx.stats["site_conductor_merge_refused_geometry"] = refused_geom
        ctx.stats["site_conductor_merge_refused_name"] = refused_name

    groups = uf.groups()
    sites: List[Dict] = []
    for members in sorted(groups.values(),
                          key=lambda ms: osm_key(min((substations[m]["osm_id"] for m in ms),
                                                     key=osm_key))):
        subs = [substations[m] for m in members]
        named = sorted([s for s in subs if s.get("name")],
                       key=lambda s: -s["geom"].area)
        polys_m = [s["geom"] for s in subs]
        sites.append({
            "members": subs,
            "geom": unary_union(polys_m),
            "polys": polys_m,
            "name": named[0]["name"] if named else None,
            "operator": next((s["operator"] for s in subs if s.get("operator")), None),
            "n_sub_polygons": len(subs),
            "osm_substation_ids": ";".join(sorted(s["osm_id"] for s in subs)),
            "under_construction": all(s["under_construction"] for s in subs),
        })
    for i, s in enumerate(sites, 1):
        s["station_id"] = f"st{i:07d}"
    log(f"  sites: {len(substations)} polygons -> {len(sites)} physical sites "
        f"({sum(1 for s in sites if s['n_sub_polygons'] > 1)} multi-polygon)")
    return sites


def _name_conflict(a: Optional[str], b: Optional[str]) -> bool:
    """Decision 6 name test: refuse a merge where both polygons are named and
    neither name contains the other."""
    if not a or not b:
        return False
    la, lb = a.strip().lower(), b.strip().lower()
    return not (la in lb or lb in la)


# ===========================================================================
# 8. CLIP  (decision 2 - conductor geometry is preserved)
# ===========================================================================

def clip_conductors(ctx: Ctx, conductors: List[Dict], sites: List[Dict]
                    ) -> Tuple[List[Dict], List[Dict]]:
    """Cut each conductor at real substation perimeters only.

    Nothing is truncated at a buffer and nothing is discarded (decision 2). Parts
    inside a site polygon go to `line_internal_to_station`, tagged with the site;
    parts outside are network spans. Every rebuild is length-checked at
    LENGTH_RETENTION_MIN and fails loudly (decision 14).
    """
    spans: List[Dict] = []
    internals: List[Dict] = []
    if sites:
        tree = STRtree([s["geom"] for s in sites])
    else:
        tree = None
    for rec in conductors:
        g = rec["geom"]
        hits = [int(i) for i in tree.query(g, predicate="intersects")] if tree else []
        if not hits:
            spans.append(_span_from(rec, g, order=0.0))
            continue
        cover = unary_union([sites[i]["geom"] for i in hits])
        inside = g.intersection(cover)
        outside = g.difference(cover)
        total = plen(g)
        got = plen(inside) + plen(outside)
        if total > 0 and got < total * LENGTH_RETENTION_MIN:
            raise SystemExit(f"clip lost length on {rec['osm_id']}: {got:.1f} < {total:.1f} m")
        for part in _as_lines(outside):
            spans.append(_span_from(rec, part, order=g.project(Point(part.coords[0]))))
        for part in _as_lines(inside):
            mid = part.interpolate(0.5, normalized=True)
            site_i = min(hits, key=lambda i: sites[i]["geom"].distance(mid))
            internals.append(_span_from(rec, part, order=g.project(Point(part.coords[0])),
                                        station_id=sites[site_i]["station_id"]))
    log(f"  clip: {len(spans)} network spans, {len(internals)} in-substation segments")
    return spans, internals


def _as_lines(geom) -> List[LineString]:
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [geom] if geom.length > 0 else []
    if geom.geom_type in ("MultiLineString", "GeometryCollection"):
        out = []
        for g in geom.geoms:
            out.extend(_as_lines(g))
        return out
    return []


def _span_from(rec: Dict, geom: LineString, order: float,
               station_id: Optional[str] = None) -> Dict:
    out = dict(rec)
    out["geom"] = geom
    out["qa"] = set(rec["qa"])
    out["order"] = order
    out["station_id"] = station_id
    return out


# ===========================================================================
# 9. END ASSIGNMENT  (decisions 7, 8 / pitfalls 2, 26)
# ===========================================================================

def assign_ends(ctx: Ctx, spans: List[Dict], internals: List[Dict], sites: List[Dict]
                ) -> List[Dict]:
    """Decide, for each span end, whether it belongs to a site or is a free end.

    Three documented rules:
      * an end within SITE_FENCE_TOL_M of the polygon is AT THE FENCE and takes
        the site;
      * an end between the fence and SITE_CATCHMENT_M is a candidate, but where
        several conductors end together at one point outside the fence, that
        point becomes a junction instead - and only when one of the spans meeting
        there has its other end AT the fence, so the connection is provably
        carried into the yard (decision 7; requiring merely that the site keep
        one attachment pushed components from 3,345 to 3,850);
      * a span landing both ends on one site keeps its far end freed when that
        end is FREE_END_MIN_M or more out, because it is an approach conductor,
        not a switchyard jumper (decision 8). Otherwise the span is a jumper and
        moves to the internal layer.
    """
    if sites:
        tree = STRtree([s["geom"] for s in sites])
    else:
        tree = None
    for sp in spans:
        cs = list(sp["geom"].coords)
        for ei, pt in ((0, Point(cs[0])), (1, Point(cs[-1]))):
            site_i, dist = None, float("inf")
            if tree is not None:
                for i in tree.query(pt, predicate="dwithin", distance=SITE_CATCHMENT_M):
                    d = sites[int(i)]["geom"].distance(pt)
                    if d < dist:
                        site_i, dist = int(i), d
            sp[f"site{ei}"] = site_i
            sp[f"dist{ei}"] = dist
            sp[f"fence{ei}"] = site_i is not None and dist <= SITE_FENCE_TOL_M
            sp[f"free{ei}"] = site_i is None

    # --- decision 7: groups of ends meeting outside the fence
    group_pts: List[Point] = []
    group_owner: List[Tuple[int, int]] = []
    for si, sp in enumerate(spans):
        cs = list(sp["geom"].coords)
        for ei in (0, 1):
            if sp[f"fence{ei}"] or sp[f"site{ei}"] is None:
                continue
            group_pts.append(Point(cs[0] if ei == 0 else cs[-1]))
            group_owner.append((si, ei))
    diverted = 0
    if group_pts:
        uf = single_linkage(group_pts, JUNCTION_TOL_M, MAX_CLUSTER_M)
        for members in uf.groups().values():
            if len(members) < 2:
                continue
            anchored = False
            for k in members:
                si, ei = group_owner[k]
                if spans[si][f"fence{1 - ei}"]:
                    anchored = True
                    break
            if not anchored:
                continue
            for k in members:
                si, ei = group_owner[k]
                spans[si][f"site{ei}"] = None
                spans[si][f"free{ei}"] = True
                spans[si]["qa"].add("end_freed_to_junction_outside_fence")
                diverted += 1
    ctx.stats["ends_diverted_to_junction"] = diverted

    # --- decision 8: both ends on one site
    jumpers = 0
    freed_far = 0
    keep: List[Dict] = []
    for sp in spans:
        s0, s1 = sp["site0"], sp["site1"]
        if s0 is not None and s0 == s1:
            far = 0 if sp["dist0"] >= sp["dist1"] else 1
            if sp[f"dist{far}"] >= FREE_END_MIN_M:
                sp[f"site{far}"] = None
                sp[f"free{far}"] = True
                sp["qa"].add("approach_conductor_end_freed")
                freed_far += 1
            else:
                sp["station_id"] = sites[s0]["station_id"]
                sp["qa"].add("switchyard_jumper_self_loop")
                internals.append(sp)
                jumpers += 1
                continue
        keep.append(sp)
    ctx.stats["self_loop_spans_to_internal"] = jumpers
    ctx.stats["approach_conductor_ends_freed"] = freed_far
    log(f"  end assignment: {diverted} ends diverted to a junction, {freed_far} approach "
        f"ends freed, {jumpers} switchyard jumpers moved to the internal layer")
    return keep


# ===========================================================================
# 10. JUNCTION CLUSTERING  (decision 13 / pitfalls 16b, 18, 23)
# ===========================================================================

def cluster_junctions(ctx: Ctx, spans: List[Dict]) -> List[Dict]:
    """Cluster free conductor ends into junction nodes.

    JUNCTION_TOL_M first, then an extended reach at JUNCTION_EXT_M whose unions
    are refused above EXT_MAX_CLUSTER_M of width. A cluster wider than
    MAX_CLUSTER_M is re-clustered at JUNCTION_TOL_M - the tolerance that formed
    it - never burst into singletons: bursting took components from 3,820 to
    7,731 (decision 13). With both passes respecting their caps this branch is
    unreachable in practice; it is a backstop, not a routine step. The node point is the medoid,
    a real endpoint, and an end within JUNCTION_MOVE_MAX_M is moved onto it
    rather than given a connector (pitfall 18).
    """
    pts: List[Point] = []
    owner: List[Tuple[int, int]] = []
    for si, sp in enumerate(spans):
        cs = list(sp["geom"].coords)
        for ei in (0, 1):
            if not sp[f"free{ei}"]:
                continue
            pts.append(Point(cs[0] if ei == 0 else cs[-1]))
            owner.append((si, ei))
    if not pts:
        return []
    uf = single_linkage(pts, JUNCTION_TOL_M, MAX_CLUSTER_M)
    uf = single_linkage(pts, JUNCTION_EXT_M, EXT_MAX_CLUSTER_M, seed=uf)

    clusters: List[List[int]] = []
    for members in uf.groups().values():
        # The post-hoc gate is MAX_CLUSTER_M, not EXT_MAX_CLUSTER_M. The two caps
        # govern different passes: pass 1 (JUNCTION_TOL_M reach) may legally chain
        # endpoints up to MAX_CLUSTER_M, while the extended pass may not create a
        # cluster over EXT_MAX_CLUSTER_M. Applying the extended cap here re-clustered
        # legally-formed pass-1 clusters - a 275 m chain of ends at 25 m spacing came
        # back as 12 singleton junctions, which is the bursting outcome decision 13
        # forbids. Re-clustering also happens at JUNCTION_TOL_M, the tolerance that
        # formed the cluster, so the worst case is a split into legal chains rather
        # than singletons.
        if cluster_width([pts[k] for k in members]) <= MAX_CLUSTER_M or len(members) < 2:
            clusters.append(members)
            continue
        sub = single_linkage([pts[k] for k in members], JUNCTION_TOL_M, MAX_CLUSTER_M)
        for grp in sub.groups().values():
            clusters.append([members[g] for g in grp])
        ctx.stats["reclustered_wide_clusters"] = ctx.stats.get("reclustered_wide_clusters", 0) + 1

    junctions: List[Dict] = []
    moved = 0
    clusters.sort(key=lambda ms: (round(pts[min(ms)].x, 2), round(pts[min(ms)].y, 2)))
    for ci, members in enumerate(clusters, 1):
        pt = medoid([pts[k] for k in members])
        jn = {"node_id": f"jn{ci:07d}", "point": pt, "node_type": "junction",
              "station_id": f"jn{ci:07d}", "name": None, "operator": None,
              "n_sub_polygons": 0, "osm_substation_ids": None, "is_site": False}
        for k in members:
            si, ei = owner[k]
            spans[si][f"node{ei}"] = jn["node_id"]
            if pts[k].distance(pt) <= JUNCTION_MOVE_MAX_M:
                _set_endpoint(spans[si], ei, (pt.x, pt.y))
                moved += 1
        junctions.append(jn)
    ctx.stats["junction_endpoints_moved_onto_medoid"] = moved
    log(f"  junctions: {len(junctions)} nodes from {len(pts)} free ends "
        f"({moved} endpoints moved onto the medoid)")
    return junctions


# ===========================================================================
# 11. NODES, BUSES, CONNECTORS  (decision 3 / pitfalls 1, 7)
# ===========================================================================

def build_nodes(ctx: Ctx, sites: List[Dict], junctions: List[Dict], spans: List[Dict],
                internals: List[Dict]) -> Dict[str, Dict]:
    """Assemble the node table and place one bus per (node, voltage, frequency).

    A substation bus sits at the centroid of that voltage's busbar conductors
    inside the site where OSM maps them, and otherwise at the site's pole of
    inaccessibility - inside the polygon either way (decision 3). A junction bus
    sits on the medoid.
    """
    nodes: Dict[str, Dict] = {}
    for s in sites:
        nodes[s["station_id"]] = {
            "node_id": s["station_id"], "node_type": "substation",
            "station_id": s["station_id"], "name": s["name"], "operator": s["operator"],
            "n_sub_polygons": s["n_sub_polygons"],
            "osm_substation_ids": s["osm_substation_ids"],
            "geom": s["geom"], "polys": s["polys"], "is_site": True,
            "point": None, "countries": s.get("countries", ""),
        }
    for j in junctions:
        j = dict(j)
        j["countries"] = ""
        nodes[j["node_id"]] = j

    # site end -> node id
    for sp in spans:
        for ei in (0, 1):
            if sp.get(f"node{ei}"):
                continue
            si = sp[f"site{ei}"]
            sp[f"node{ei}"] = sites[si]["station_id"] if si is not None else None

    # busbar evidence per (site, voltage): the in-substation segments themselves
    busbar: Dict[Tuple[str, float], List[LineString]] = defaultdict(list)
    for seg in internals:
        if seg.get("station_id"):
            busbar[(seg["station_id"], seg["voltage_kv"])].append(seg["geom"])

    # bus per (node, voltage, frequency)
    buses: Dict[str, Dict] = {}
    for sp in spans:
        for ei in (0, 1):
            nid = sp[f"node{ei}"]
            if nid is None:
                continue
            key = bus_id(nid, sp["voltage_kv"], sp["frequency_hz"], ctx)
            if key in buses:
                continue
            node = nodes[nid]
            if node["is_site"]:
                segs = busbar.get((nid, sp["voltage_kv"]))
                if segs:
                    pt = unary_union(segs).centroid
                    src = "busbar_centroid"
                    if not node["geom"].contains(pt):
                        pt = _pia(node)
                        src = "pole_of_inaccessibility"
                else:
                    pt = _pia(node)
                    src = "pole_of_inaccessibility"
            else:
                pt = node["point"]
                src = "junction_medoid"
            buses[key] = {
                "bus_id": key, "node_id": nid, "station_id": node["station_id"],
                "node_type": node["node_type"], "voltage_kv": sp["voltage_kv"],
                "frequency_hz": sp["frequency_hz"], "station_name": node["name"],
                "operator": node["operator"], "n_sub_polygons": node["n_sub_polygons"],
                "osm_substation_ids": node["osm_substation_ids"],
                "point": pt, "bus_point_source": src, "countries": node.get("countries", ""),
            }
    # severed_from: a traction bus that shares a node and voltage with a grid bus
    for b in buses.values():
        if b["frequency_hz"] != ctx.traction_hz:
            b["severed_from"] = None
            continue
        grid = bus_id(b["node_id"], b["voltage_kv"],
                      float(ctx.cfg["grid_frequency_hz"]), ctx)
        b["severed_from"] = grid if grid in buses else None
    log(f"  buses: {len(buses)} over {len(nodes)} nodes")
    return {"nodes": nodes, "buses": buses}


def bus_id(node_id: str, kv: float, hz: float, ctx: Ctx) -> str:
    """`<node_id>_<voltage>kV`, with the traction frequency as a suffix so the
    two synchronous families never share a bus (README s4, s12)."""
    base = f"{node_id}_{fmt_kv(kv)}kV"
    if ctx.traction_on and abs(hz - ctx.traction_hz) < 1e-6:
        return base + "_" + str(ctx.traction_hz).replace(".", "_") + "Hz"
    return base


def fmt_kv(kv: float) -> str:
    return str(int(round(kv))) if abs(kv - round(kv)) < 1e-6 else f"{kv:g}"


def _pia(node: Dict) -> Point:
    """Pole of inaccessibility of the largest polygon of a site: the point
    furthest from any edge, so it is always inside (decision 3)."""
    poly = max(node["polys"], key=lambda p: p.area)
    try:
        return polylabel(poly, tolerance=max(0.5, math.sqrt(poly.area) / 100.0))
    except Exception:                       # noqa: BLE001 - degenerate polygon
        return poly.representative_point()


def attach_connectors(ctx: Ctx, spans: List[Dict], buses: Dict[str, Dict]) -> None:
    """Straight connector from each conductor end to its bus point.

    Stored separately (`connector0_m`, `connector1_m`) so the conductor length is
    never inflated by synthetic geometry - the published-dataset comparison uses
    `length_conductor_m` (pitfall 7). The drawn geometry does include the
    connectors, which is why a residual few read as spikes and are flagged
    `long_connector` (pitfall 19).
    """
    for sp in spans:
        cs = list(sp["geom"].coords)
        sp["length_conductor_m"] = ctx.hav(sp["geom"])
        for ei in (0, 1):
            nid = sp[f"node{ei}"]
            if nid is None:
                sp[f"connector{ei}_m"] = 0.0
                sp[f"bus{ei}"] = None
                continue
            key = bus_id(nid, sp["voltage_kv"], sp["frequency_hz"], ctx)
            sp[f"bus{ei}"] = key
            bp = buses[key]["point"]
            end = Point(cs[0] if ei == 0 else cs[-1])
            d = end.distance(bp)
            if d <= 0.01:
                sp[f"connector{ei}_m"] = 0.0
                continue
            seg = LineString([(end.x, end.y), (bp.x, bp.y)])
            sp[f"connector{ei}_m"] = ctx.hav(seg)
            if ei == 0:
                cs = [(bp.x, bp.y)] + cs
            else:
                cs = cs + [(bp.x, bp.y)]
            if sp[f"connector{ei}_m"] > LONG_CONNECTOR_M:
                sp["qa"].add("long_connector")
        sp["geom_drawn"] = LineString(cs)


# ===========================================================================
# 12. DISSOLVE  (decisions 12, 14 / pitfalls 13, 15, 16, 17)
# ===========================================================================

def dissolve_junctions(ctx: Ctx, spans: List[Dict], nodes: Dict[str, Dict]) -> List[Dict]:
    """Re-merge spans that one OSM element was needlessly split into.

    The node rule (decision 12): a junction dissolves when every span meeting
    there is the same OSM element, it is not a terminus, and it is not a
    substation. A degree-2 rule alone cannot reach the case where junction
    clustering chained along a line and produced degrees of 4, 6, 8 and up to 22.
    Where a dissolvable node has more than two incident spans, spans are paired
    by the same 60-degree continuation test used everywhere else.

    EVERY REBUILD IS LENGTH-CHECKED PER ELEMENT and reverted on any shortfall
    (decision 14): one earlier version of this dissolve looked tidy on a map and
    dropped 60,000 route-km.
    """
    incident: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
    for si, sp in enumerate(spans):
        for ei in (0, 1):
            nid = sp[f"node{ei}"]
            if nid is not None:
                incident[nid].append((si, ei))

    dissolvable: Set[str] = set()
    for nid, items in incident.items():
        if nodes[nid]["is_site"] or len(items) < 2:
            continue
        # "every span meeting there is the same OSM element" - and the same line
        # within it, since a multi-value voltage tag yields several records off
        # one element and those are physically different circuits.
        elems = {(spans[si]["osm_id"], spans[si]["voltage_kv"], spans[si]["frequency_hz"])
                 for si, _ei in items}
        if len(elems) == 1:
            dissolvable.add(nid)
    ctx.stats["dissolvable_junctions"] = len(dissolvable)

    by_elem: Dict[Tuple[str, float, float], List[int]] = defaultdict(list)
    for si, sp in enumerate(spans):
        if sp["node0"] in dissolvable or sp["node1"] in dissolvable:
            by_elem[(sp["osm_id"], sp["voltage_kv"], sp["frequency_hz"])].append(si)

    replaced: Set[int] = set()
    new_spans: List[Dict] = []
    rebuilt = reverted = 0
    for elem, sids in by_elem.items():
        chains = _pair_through_nodes(spans, sids, dissolvable)
        before = sum(plen(spans[si]["geom"]) for si in sids)
        built: List[Dict] = []
        ok = True
        for chain in chains:
            if len(chain) == 1:
                built.append(spans[chain[0][0]])
                continue
            fused = _fuse_spans(ctx, spans, chain)
            if fused is None:
                ok = False
                break
            built.append(fused)
        after = sum(plen(b["geom"]) for b in built)
        if not ok or (before > 0 and not (before * LENGTH_RETENTION_MIN <= after
                                          <= before / LENGTH_RETENTION_MIN)):
            reverted += 1                   # revert to the original spans (decision 14)
            continue
        rebuilt += 1
        replaced.update(sids)
        new_spans.extend(built)
    ctx.stats["elements_rebuilt"] = rebuilt
    ctx.stats["elements_reverted_on_length_check"] = reverted
    out = [sp for si, sp in enumerate(spans) if si not in replaced] + new_spans
    log(f"  dissolve: {rebuilt} elements rebuilt, {reverted} reverted on the length check, "
        f"{len(spans)} -> {len(out)} spans")
    return out


def _pair_through_nodes(spans: List[Dict], sids: List[int], dissolvable: Set[str]
                        ) -> List[List[Tuple[int, bool]]]:
    """Group an element's spans into chains that run through dissolvable nodes.

    At a dissolvable node each span end is paired with the end whose outward
    direction is most nearly opposite, and only if dot < COS_CONTINUE_MAX - the
    same test that stops a fold-back merge (decision 4).
    """
    at_node: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
    for si in sids:
        for ei in (0, 1):
            nid = spans[si][f"node{ei}"]
            if nid in dissolvable:
                at_node[nid].append((si, ei))
    partner: Dict[Tuple[int, int], Tuple[int, int]] = {}
    for nid, items in at_node.items():
        free = list(items)
        while len(free) >= 2:
            (si, ei) = free.pop(0)
            di = outward_unit(list(spans[si]["geom"].coords), at_start=(ei == 0))
            best, best_dot = None, 1.0
            for cand in free:
                sj, ej = cand
                dj = outward_unit(list(spans[sj]["geom"].coords), at_start=(ej == 0))
                d = dot(di, dj)
                if d < best_dot:
                    best, best_dot = cand, d
            if best is None or best_dot >= COS_CONTINUE_MAX:
                continue
            free.remove(best)
            partner[(si, ei)] = best
            partner[best] = (si, ei)

    chains: List[List[Tuple[int, int]]] = []
    used: Set[int] = set()
    for si in sids:
        if si in used:
            continue
        head, head_end = si, 0
        seen = {si}
        while (head, head_end) in partner:
            nj, ej = partner[(head, head_end)]
            if nj in seen:
                break
            seen.add(nj)
            head, head_end = nj, 1 - ej
        chain: List[Tuple[int, bool]] = []
        cur, cur_end = head, 1 - head_end
        while True:
            chain.append((cur, cur_end == 1))
            used.add(cur)
            if (cur, cur_end) not in partner:
                break
            nj, ej = partner[(cur, cur_end)]
            if nj in used:
                break
            cur, cur_end = nj, 1 - ej
        chains.append(chain)
    return chains


def _fuse_spans(ctx: Ctx, spans: List[Dict], chain: List[Tuple[int, int]]) -> Optional[Dict]:
    """Concatenate a chain of spans of one element into a single span."""
    coords: List[Tuple[float, float]] = []
    for si, forward in chain:
        cs = list(spans[si]["geom"].coords)
        if not forward:
            cs = list(reversed(cs))
        if coords and math.dist(coords[-1], cs[0]) < 1.0:
            cs = cs[1:]
        elif coords:
            return None                 # not actually contiguous; refuse the rebuild
        coords.extend(cs)
    if len(coords) < 2:
        return None
    first_si, first_fwd = chain[0]
    last_si, last_fwd = chain[-1]
    out = dict(spans[first_si])
    out["geom"] = LineString(coords)
    out["qa"] = set()
    for si, _f in chain:
        out["qa"] |= spans[si]["qa"]
    out["node0"] = spans[first_si]["node0" if first_fwd else "node1"]
    out["node1"] = spans[last_si]["node1" if last_fwd else "node0"]
    out["free0"] = spans[first_si]["free0" if first_fwd else "free1"]
    out["free1"] = spans[last_si]["free1" if last_fwd else "free0"]
    out["site0"] = spans[first_si]["site0" if first_fwd else "site1"]
    out["site1"] = spans[last_si]["site1" if last_fwd else "site0"]
    out["order"] = min(spans[si]["order"] for si, _f in chain)
    return out


def sweep_self_loops(ctx: Ctx, spans: List[Dict], internals: List[Dict]) -> List[Dict]:
    """Move every span that returns to the node it left into the internal layer.

    Repeated after the dissolve, because the dissolve creates fresh ones
    (pitfall 17). A self-loop cannot be a graph edge, so leaving one in the
    network layer silently loses the conductor; long ones are kept and flagged
    (pitfall 2) but still out of the network layers.
    """
    keep: List[Dict] = []
    moved = 0
    for sp in spans:
        if sp["node0"] is not None and sp["node0"] == sp["node1"]:
            if ctx.hav(sp["geom"]) >= SELF_LOOP_KEEP_FLAG_M:
                sp["qa"].add("self_loop_long_retained_internal")
            else:
                sp["qa"].add("self_loop_micro")
            sp["station_id"] = sp.get("station_id")
            internals.append(sp)
            moved += 1
            continue
        keep.append(sp)
    ctx.stats["self_loops_swept_after_dissolve"] = moved
    if moved:
        log(f"  self-loop sweep: {moved} spans moved to the internal layer")
    return keep


# ===========================================================================
# 13. ELECTRICAL PARAMETERS  (README s5, s6.5)
# ===========================================================================

def line_type_for(kv: float) -> Tuple[str, float, float, float, Optional[float]]:
    """Standard type for a voltage: the nearest anchor in LINE_TYPES.

    A voltage within PROXY_TOL_KV of an anchor uses that anchor's type outright;
    anything further away also uses the nearest anchor but is flagged
    `line_type_proxy_<anchor>kV`, which is how the shipped dataset records that
    275 kV runs on the 300 kV type and 420 kV on the 380 kV type.
    """
    anchor = min(LINE_TYPES, key=lambda a: (abs(a - kv), a))
    name, r, x, i = LINE_TYPES[anchor]
    proxy = None if abs(anchor - kv) <= PROXY_TOL_KV else anchor
    return name, r, x, i, proxy


def electrical_parameters(ctx: Ctx, spans: List[Dict]) -> None:
    """Per-span line type, impedances and rating.

    r_ohm = r_type * L_km / n_circuits (parallel circuits), likewise x_ohm;
    s_nom_mva = sqrt(3) * U_kV * I_nom_kA * n_circuits (README s5). L is the
    drawn length, conductor plus both connectors, matching the shipped dataset.
    """
    standard = {float(v) for v in ctx.cfg["standard_voltages_kv"]}
    for sp in spans:
        kv = sp["voltage_kv"]
        name, r_km, x_km, i_nom, proxy = line_type_for(kv)
        L_km = (sp["length_conductor_m"] + sp["connector0_m"] + sp["connector1_m"]) / 1000.0
        nc = max(1, int(sp["n_circuits"]))
        sp["line_type"] = name
        sp["i_nom_ka"] = i_nom
        sp["r_ohm"] = r_km * L_km / nc
        sp["x_ohm"] = x_km * L_km / nc
        sp["s_nom_mva"] = math.sqrt(3.0) * kv * i_nom * nc
        if proxy is not None:
            sp["qa"].add(f"line_type_proxy_{fmt_kv(proxy)}kV")
        if standard and kv not in standard:
            sp["qa"].add("nonstandard_voltage")
        if sp["circuits_source"] == "assumed_single_circuit":
            sp["qa"].add("circuits_assumed")
        if sp["under_construction"]:
            sp["qa"].add("under_construction")


def transformer_band(lo: float, hi: float) -> Tuple[str, float, float, float, str]:
    """The v23 banded typing rule (README s13.1). The six bands partition every
    voltage pair with no gaps or overlaps."""
    if lo >= 200:
        b = TRANSFORMER_BANDS[0]
    elif 100 <= lo < 200 and hi >= 330:
        b = TRANSFORMER_BANDS[1]
    elif 100 <= lo < 200 and 200 <= hi < 330:
        b = TRANSFORMER_BANDS[2]
    elif 100 <= lo < 200:
        b = TRANSFORMER_BANDS[3]
    elif lo < 100 and hi >= 200:
        b = TRANSFORMER_BANDS[4]
    else:
        b = TRANSFORMER_BANDS[5]
    return b[0], b[2], b[3], b[4], b[5]


def build_transformers(ctx: Ctx, buses: Dict[str, Dict], spans: List[Dict]) -> List[Dict]:
    """One transformer per adjacent voltage pair per site, same frequency.

    Inference, never observation (README s7 pitfall 4): a site with 400/275/132
    gets 400-275 and 275-132 on a cascade assumption, so a direct 400/132 bank is
    missed and a pair with no bank between them is invented. Flagged
    `inferred = voltage_pair_at_site` on every row. Cross-frequency pairs are NOT
    created: a traction interface is a converter, not a transformer (README s12).
    """
    by_node: Dict[Tuple[str, float], List[Dict]] = defaultdict(list)
    for b in buses.values():
        if b["node_type"] != "substation":
            continue
        by_node[(b["node_id"], b["frequency_hz"])].append(b)

    incident: Dict[str, float] = defaultdict(float)
    for sp in spans:
        if sp["frequency_hz"] != float(ctx.cfg["grid_frequency_hz"]):
            continue
        for ei in (0, 1):
            if sp[f"bus{ei}"]:
                incident[sp[f"bus{ei}"]] += float(sp["s_nom_mva"])

    out: List[Dict] = []
    for (node_id, hz), bl in sorted(by_node.items()):
        bl.sort(key=lambda b: b["voltage_kv"])
        for a, b in zip(bl, bl[1:]):
            lo, hi = a["voltage_kv"], b["voltage_kv"]
            band, s_nom, x_pu, r_pu, basis = transformer_band(lo, hi)
            src = f"typing_rule_v23:{band} ({basis})"
            alt = max(incident.get(a["bus_id"], 0.0), incident.get(b["bus_id"], 0.0))
            if alt <= 0:
                alt = s_nom
                src += ";alt_snom_fallback_banded_no_incident_ac_lines"
            else:
                alt = float(math.ceil(alt))
            if hi / lo < TRANSFORMER_RATIO_ARTEFACT:
                src += ";ratio_lt_1p095_probable_voltage_tagging_artifact"
            out.append({
                "transformer_id": f"{node_id}_{fmt_kv(lo)}_{fmt_kv(hi)}",
                "station_id": a["station_id"], "station_name": a["station_name"],
                "bus0": a["bus_id"], "bus1": b["bus_id"],
                "voltage0_v": int(round(lo * 1000)), "voltage1_v": int(round(hi * 1000)),
                "voltage0_kv": int(round(lo)), "voltage1_kv": int(round(hi)),
                "inferred": "voltage_pair_at_site",
                "frequency_hz": hz, "frequency_source": "inherited_from_buses",
                "s_nom_mva": s_nom, "x_pu": x_pu, "r_pu": r_pu,
                "s_nom_pypsa_eur_mva": alt, "parameters_source": src,
                "geom": LineString([(a["point"].x, a["point"].y),
                                    (b["point"].x, b["point"].y)])
                if a["point"].distance(b["point"]) > 1e-6 else
                LineString([(a["point"].x, a["point"].y),
                            (b["point"].x + 1e-3, b["point"].y + 1e-3)]),
            })
    log(f"  transformers: {len(out)} inferred voltage pairs")
    return out


# ===========================================================================
# 14. DC LINKS  (README s7 pitfall 3, s13.2)
# ===========================================================================

def build_dc_links(ctx: Ctx, dc_records: List[Dict], buses: Dict[str, Dict]) -> List[Dict]:
    """Attach each DC terminal to the nearest AC bus within DC_MAX_CONVERTER_M.

    Beyond that the terminal is left unattached and flagged rather than forging a
    1,664 km edge (pitfall 3). Ratings come from an optional config CSV; with no
    CSV every rating stays `unknown`, which is a real value and is never replaced
    by a plausible guess (README s13.2).
    """
    ratings = _load_dc_ratings(ctx)
    bus_list = [b for b in buses.values()]
    pts = [b["point"] for b in bus_list]
    tree = STRtree(pts) if pts else None
    out: List[Dict] = []
    for i, rec in enumerate(sorted(dc_records, key=lambda r: (osm_key(r["osm_id"]), r["part"])), 1):
        g = rec["geom"]
        cs = list(g.coords)
        attach: List[Optional[str]] = [None, None]
        for ei, pt in ((0, Point(cs[0])), (1, Point(cs[-1]))):
            if tree is None:
                continue
            j = tree.nearest(pt)
            if j is None:
                continue
            d = pts[int(j)].distance(pt)
            if d > DC_MAX_CONVERTER_M:
                rec["qa"].add("converter_unattached")
                continue
            if d > DC_FAR_CONVERTER_M:
                rec["qa"].add("converter_far")
            attach[ei] = bus_list[int(j)]["bus_id"]
        r = ratings.get(rec["osm_id"], {})
        out.append({
            "fid": i, "osm_id": rec["osm_id"], "name": rec.get("name"),
            "voltage_kv": rec.get("voltage_kv"),
            "bus0": attach[0], "bus1": attach[1],
            "geom": g, "countries": rec.get("countries", ""),
            "qa": set(rec["qa"]) | set(split_semicolon(r.get("qa_flags"))),
            "frequency_hz": 0.0, "frequency_source": "dc_link_layer",
            "p_nom_mw": r.get("p_nom_mw"),
            "status": r.get("status") or "unknown",
            "p_nom_source": r.get("p_nom_source") or "unknown",
        })
    log(f"  dc links: {len(out)}")
    return out


def _load_dc_ratings(ctx: Ctx) -> Dict[str, Dict[str, Any]]:
    """Optional per-link rating CSV, keyed by osm_id (README s13.2 conventions:
    a series section carries the full scheme rating, parallel poles split it, and
    an umbrella row is flagged exclude_from_capacity_sums)."""
    path = ctx.cfg.get("dc_ratings_csv")
    if not path:
        return {}
    if not os.path.exists(path):
        raise SystemExit(f"dc_ratings_csv missing: {path}")
    df = pd.read_csv(path)
    if "osm_id" not in df.columns:
        raise SystemExit(f"{path}: needs an osm_id column to join on")
    out: Dict[str, Dict[str, Any]] = {}
    for row in df.to_dict("records"):
        p = row.get("p_nom_mw")
        out[str(row["osm_id"])] = {
            "p_nom_mw": None if p is None or (isinstance(p, float) and math.isnan(p)) else float(p),
            "status": row.get("status"), "p_nom_source": row.get("p_nom_source"),
            "qa_flags": row.get("qa_flags"),
        }
    return out


# ===========================================================================
# 15. COMPONENTS, LABELS, ROUTE TRACING
# ===========================================================================

def components(ctx: Ctx, buses: Dict[str, Dict], spans: List[Dict],
               transformers: List[Dict], dc_links: List[Dict]) -> None:
    """Connected components over lines + transformers - PyPSA's passive-branch
    partition (README s12(d)) - numbered deterministically by route-km then by
    lowest bus id, so component 0 is the largest. `component_incl_dc` is the same
    partition with DC links added, kept as a separate bus column.
    """
    ids = sorted(buses)
    idx = {b: i for i, b in enumerate(ids)}

    def partition(edges: List[Tuple[str, str, float]]) -> Dict[str, int]:
        uf = UnionFind(len(ids))
        for b0, b1, _w in edges:
            if b0 in idx and b1 in idx:
                uf.union(idx[b0], idx[b1])
        weight: Dict[int, float] = defaultdict(float)
        for b0, b1, w in edges:
            if b0 in idx and b1 in idx:
                weight[uf.find(idx[b0])] += w
        groups = uf.groups()
        order = sorted(groups, key=lambda r: (-weight.get(r, 0.0), ids[min(groups[r])]))
        return {ids[m]: rank for rank, r in enumerate(order) for m in groups[r]}

    line_edges = [(sp["bus0"], sp["bus1"], sp["length_conductor_m"] / 1000.0)
                  for sp in spans if sp["bus0"] and sp["bus1"]]
    tr_edges = [(t["bus0"], t["bus1"], 0.0) for t in transformers]
    comp = partition(line_edges + tr_edges)
    comp_dc = partition(line_edges + tr_edges +
                        [(d["bus0"], d["bus1"], 0.0) for d in dc_links
                         if d["bus0"] and d["bus1"]])
    for b, c in comp.items():
        buses[b]["component"] = c
        buses[b]["component_incl_dc"] = comp_dc[b]
    for sp in spans:
        sp["component"] = comp.get(sp["bus0"], comp.get(sp["bus1"], -1))
        if sp["component"] != 0:
            sp["qa"].add("not_in_main_component")
    for t in transformers:
        t["component"] = comp.get(t["bus0"], -1)
    for d in dc_links:
        d["component"] = comp.get(d["bus0"], comp.get(d["bus1"], -1))
    ctx.stats["components"] = len(set(comp.values()))
    ctx.stats["components_incl_dc"] = len(set(comp_dc.values()))


def bookkeeping(ctx: Ctx, buses: Dict[str, Dict], spans: List[Dict],
                transformers: List[Dict], dc_links: List[Dict]) -> None:
    """degree, n_lines and connected_line_ids per bus (README s12(e)).

    degree counts distinct neighbours over lines + transformers + dc links;
    n_lines counts incident AC ends; connected_line_ids lists the AC lines.
    """
    nb: Dict[str, Set[str]] = defaultdict(set)
    lines: Dict[str, Set[str]] = defaultdict(set)
    nlines: Dict[str, int] = defaultdict(int)
    for sp in spans:
        b0, b1 = sp["bus0"], sp["bus1"]
        for a, b in ((b0, b1), (b1, b0)):
            if a:
                nlines[a] += 1
                lines[a].add(sp["line_id"])
                if b:
                    nb[a].add(b)
    for coll in (transformers, dc_links):
        for e in coll:
            b0, b1 = e.get("bus0"), e.get("bus1")
            if b0 and b1:
                nb[b0].add(b1)
                nb[b1].add(b0)
    for b in buses.values():
        bid = b["bus_id"]
        b["degree"] = len(nb.get(bid, ()))
        b["n_lines"] = nlines.get(bid, 0)
        b["connected_line_ids"] = ";".join(sorted(lines.get(bid, ()))) or None
    voltages: Dict[str, Set[float]] = defaultdict(set)
    for b in buses.values():
        voltages[b["node_id"]].add(b["voltage_kv"])
    for b in buses.values():
        b["station_voltages_kv"] = ";".join(fmt_kv(v) for v in sorted(voltages[b["node_id"]]))


def assign_line_ids(spans: List[Dict]) -> None:
    """`line_id` = osm_id, suffixed `:<idx>` only where one element yields more
    than one network span (README s4: `elem_id` is recoverable as the part
    before the colon)."""
    by_elem: Dict[str, List[Dict]] = defaultdict(list)
    for sp in spans:
        by_elem[sp["osm_id"]].append(sp)
    for elem, group in by_elem.items():
        if len(group) == 1:
            group[0]["line_id"] = elem
            continue
        for i, sp in enumerate(sorted(group, key=lambda s: s["order"])):
            sp["line_id"] = f"{elem}:{i}"


def endpoint_labels(ctx: Ctx, spans: List[Dict], buses: Dict[str, Dict],
                    nodes: Dict[str, Dict]) -> None:
    """start_point / end_point, the traced route substations, and line_label.

    `junction` means the line genuinely does not terminate at a mapped
    substation, which is a different statement from a substation whose name is
    missing in OSM - hence `unnamed substation` as a third value (README s4).
    Route tracing walks through pass-through junctions to the substation the
    route actually reaches (pitfall 6).
    """
    # Incidence is per BUS, not per node: a route traced through a node must stay
    # at its own voltage and frequency, or a 132 kV line would be traced through
    # the 400 kV span that happens to share the tower.
    incident: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
    for si, sp in enumerate(spans):
        for ei in (0, 1):
            if sp[f"bus{ei}"]:
                incident[sp[f"bus{ei}"]].append((si, ei))

    def label_of(node_id: Optional[str]) -> str:
        if node_id is None:
            return "junction"
        node = nodes[node_id]
        if not node["is_site"]:
            return "junction"
        return node["name"] or "unnamed substation"

    def trace(si: int, ei: int) -> str:
        """Walk out of span si at end ei through pass-through (degree-2) buses to
        the substation the route actually reaches (pitfall 6)."""
        bus = spans[si][f"bus{ei}"]
        seen: Set[str] = set()
        cur_si, cur_ei = si, ei
        while bus is not None and bus not in seen:
            node = nodes[spans[cur_si][f"node{cur_ei}"]]
            if node["is_site"]:
                return node["name"] or "unnamed substation"
            seen.add(bus)
            items = incident.get(bus, [])
            if len(items) != 2:
                return "unknown"
            nxt = [it for it in items if it != (cur_si, cur_ei)]
            if not nxt:
                return "unknown"
            cur_si, cur_ei = nxt[0]
            cur_ei = 1 - cur_ei                 # continue out of the far end
            bus = spans[cur_si][f"bus{cur_ei}"]
        return "unknown"

    for si, sp in enumerate(spans):
        for ei, tag in ((0, "start"), (1, "end")):
            sp[f"{tag}_point"] = label_of(sp[f"node{ei}"])
            sp[f"route_{tag}_substation"] = (
                sp[f"{tag}_point"] if sp[f"{tag}_point"] != "junction" else trace(si, ei))
            bus = buses.get(sp[f"bus{ei}"]) if sp[f"bus{ei}"] else None
            pt = ctx.deg(bus["point"]) if bus else None
            sp[f"{tag}_lat"] = round(pt.y, 6) if pt else None
            sp[f"{tag}_lon"] = round(pt.x, 6) if pt else None
        # line_label: OSM name, else OSM ref, else derived from route endpoints
        if sp.get("name"):
            sp["line_label"], sp["line_label_source"] = sp["name"], "osm_name_tag"
        elif sp.get("ref"):
            sp["line_label"], sp["line_label_source"] = sp["ref"], "osm_ref_tag"
        elif (sp["route_start_substation"] not in ("unknown", "junction")
              and sp["route_end_substation"] not in ("unknown", "junction")):
            sp["line_label"] = (f"{sp['route_start_substation']} - "
                                f"{sp['route_end_substation']} {fmt_kv(sp['voltage_kv'])}kV")
            sp["line_label_source"] = "derived_from_route_endpoints"
        else:
            sp["line_label"], sp["line_label_source"] = None, "none_available"


# ===========================================================================
# 16. EXPORT  (README s4 - layer structure and field lists)
# ===========================================================================

LINE_FIELDS = [
    "line_id", "osm_id", "contains", "line_label", "line_label_source", "ref", "operator",
    "bus0", "bus1", "start_point", "end_point", "start_lat", "start_lon", "end_lat", "end_lon",
    "route_start_substation", "route_end_substation", "component", "voltage_kv", "n_circuits",
    "circuits_source", "line_type", "i_nom_ka", "s_nom_mva", "r_ohm", "x_ohm",
    "construction_type", "construction_source", "under_construction", "length_conductor_m",
    "connector0_m", "connector1_m", "countries", "n_ways_merged", "qa_flags",
    "frequency_hz", "frequency_source",
]
SITE_FIELDS = [
    "bus_id", "station_id", "node_type", "voltage_kv", "station_name", "operator", "countries",
    "degree", "n_lines", "connected_line_ids", "station_voltages_kv", "n_sub_polygons",
    "osm_substation_ids", "component", "frequency_hz", "frequency_source",
]
GRAPH_SITE_EXTRA = ["severed_from", "component_incl_dc"]
INTERNAL_FIELDS = [
    "line_id", "osm_id", "contains", "ref", "operator", "voltage_kv", "n_circuits",
    "construction_type", "construction_source", "under_construction", "countries",
]
DC_FIELDS = [
    "osm_id", "name", "voltage_kv", "bus0", "bus1", "start_point", "end_point",
    "start_lat", "start_lon", "end_lat", "end_lon", "countries", "qa_flags",
    "frequency_hz", "frequency_source", "component", "p_nom_mw", "status", "p_nom_source",
]
TRANSFORMER_FIELDS = [
    "transformer_id", "station_id", "station_name", "bus0", "bus1", "voltage0_v",
    "voltage1_v", "inferred", "component", "voltage0_kv", "voltage1_kv", "frequency_hz",
    "frequency_source", "s_nom_mva", "x_pu", "r_pu", "s_nom_pypsa_eur_mva",
    "parameters_source",
]
CLUSTER_FIELDS = [
    "station_id", "station_name", "operator", "countries", "n_buses", "voltages_kv",
    "n_lines", "n_sub_polygons", "osm_substation_ids", "component",
]
FOOTPRINT_FIELDS = ["osm_id", "name", "operator", "voltage_kv", "countries", "area_m2",
                    "under_construction"]

# Fields deliberately ABSENT because they are exactly recoverable (README s4):
# voltage_v, station0/station1, underground/submarine, length_m, s_nom_n1_mva,
# is_cross_border, elem_id, name, cables/wires, internal_to_station. Adding any
# of them back is a schema regression, not an improvement.


def layer_name(ctx: Ctx, kv: float, hz: float, prefix: str) -> str:
    """`line_<kV>` / `site_<kV>`, with `_16_7Hz` for the traction family and
    `_other_kV` for a voltage with no layer of its own (README s4)."""
    layers = {float(v) for v in ctx.cfg["layer_voltages_kv"]}
    base = f"{prefix}_{fmt_kv(kv)}kV" if kv in layers else f"{prefix}_other_kV"
    if ctx.traction_on and abs(hz - ctx.traction_hz) < 1e-6:
        base += "_" + str(ctx.traction_hz).replace(".", "_") + "Hz"
    return base


def promote_layer_voltages(ctx: Ctx, spans: List[Dict]) -> None:
    """`layer_voltages_kv` is authoritative; a voltage outside it is promoted only
    if it carries at least `layer_min_spans` spans (README s4). Promoting every
    standard voltage unconditionally defeated the config's own purpose - a single
    stray 236 kV tag then created a one-span line_236kV layer instead of falling
    into line_other_kV."""
    layers = {float(v) for v in ctx.cfg["layer_voltages_kv"]}
    counts: Dict[float, int] = defaultdict(int)
    for sp in spans:
        counts[sp["voltage_kv"]] += 1
    for kv, n in counts.items():
        if n >= int(ctx.cfg["layer_min_spans"]):
            layers.add(kv)
    ctx.cfg["layer_voltages_kv"] = sorted(layers)


def _gdf(ctx: Ctx, rows: List[Dict], fields: List[str], geom_key: str = "geom"
         ) -> gpd.GeoDataFrame:
    """Rows -> GeoDataFrame in EPSG:4326 with exactly `fields` plus geometry."""
    recs = []
    geoms = []
    for r in rows:
        recs.append({f: r.get(f) for f in fields})
        geoms.append(ctx.deg(r[geom_key]))
    gdf = gpd.GeoDataFrame(pd.DataFrame(recs, columns=fields), geometry=geoms,
                           crs="EPSG:4326")
    return gdf


def export(ctx: Ctx, spans: List[Dict], internals: List[Dict], buses: Dict[str, Dict],
           nodes: Dict[str, Dict], sites: List[Dict], substations: List[Dict],
           transformers: List[Dict], dc_links: List[Dict], out_dir: str) -> Dict[str, int]:
    """Write the two GeoPackages and the non-spatial provenance tables."""
    os.makedirs(out_dir, exist_ok=True)
    region = ctx.cfg["region_name"]
    topo_path = os.path.join(out_dir, f"{region}_grid_topology.gpkg")
    graph_path = os.path.join(out_dir, f"{region}_grid_graph.gpkg")
    for p in (topo_path, graph_path):
        if os.path.exists(p):
            os.remove(p)

    # Flatten the set/list working values into the stored string form: qa_flags
    # and contains are both semicolon-joined (README s4).
    for coll in (spans, internals):
        for row in coll:
            row["qa_flags"] = ";".join(sorted(row["qa"]))
            if isinstance(row["contains"], list):
                row["contains"] = ";".join(sorted(row["contains"]))
    for d in dc_links:
        d["qa_flags"] = ";".join(sorted(d["qa"]))

    counts: Dict[str, int] = {}
    # --- line layers, one per voltage (and per frequency family)
    groups: Dict[str, List[Dict]] = defaultdict(list)
    for sp in spans:
        groups[layer_name(ctx, sp["voltage_kv"], sp["frequency_hz"], "line")].append(sp)
    for name in sorted(groups):
        gdf = _gdf(ctx, groups[name], LINE_FIELDS, geom_key="geom_drawn")
        gdf.to_file(topo_path, layer=name, driver="GPKG", engine="pyogrio")
        counts[name] = len(gdf)

    # --- site layers (substation buses only) and junction_node (pitfall 12)
    # decision 11 - junctions are NOT sites: junction_node is its own layer and
    # never merges into site_<kV>, so a tee on a tower cannot become a substation.
    site_rows: Dict[str, List[Dict]] = defaultdict(list)
    junction_rows: List[Dict] = []
    for b in buses.values():
        row = dict(b)
        row["geom"] = b["point"]
        row["frequency_source"] = "inherited_from_lines"
        if b["node_type"] == "substation":
            site_rows[layer_name(ctx, b["voltage_kv"], b["frequency_hz"], "site")].append(row)
        else:
            junction_rows.append(row)
    for name in sorted(site_rows):
        gdf = _gdf(ctx, site_rows[name], SITE_FIELDS)
        gdf.to_file(topo_path, layer=name, driver="GPKG", engine="pyogrio")
        counts[name] = len(gdf)
    if junction_rows:
        gdf = _gdf(ctx, junction_rows, SITE_FIELDS)
        gdf.to_file(topo_path, layer="junction_node", driver="GPKG", engine="pyogrio")
        counts["junction_node"] = len(gdf)

    # --- internal segments, kept rather than deleted (README s4, s6 deviation 3)
    if internals:
        seen: Dict[str, int] = defaultdict(int)
        for seg in sorted(internals, key=lambda s: (s["osm_id"], s["order"])):
            seg["line_id"] = f"{seg['osm_id']}~in{seen[seg['osm_id']]}"
            seen[seg["osm_id"]] += 1
        gdf = _gdf(ctx, internals, INTERNAL_FIELDS)
        gdf.to_file(topo_path, layer="line_internal_to_station", driver="GPKG",
                    engine="pyogrio")
        counts["line_internal_to_station"] = len(gdf)

    # --- dc_link, transformer, station_cluster, substation_footprint
    if dc_links:
        for d in dc_links:
            for ei, tag in ((0, "start"), (1, "end")):
                bus = buses.get(d[f"bus{ei}"]) if d[f"bus{ei}"] else None
                d[f"{tag}_point"] = (bus["station_name"] or "unnamed substation") if bus and \
                    bus["node_type"] == "substation" else ("junction" if bus else None)
                pt = ctx.deg(bus["point"]) if bus else None
                d[f"{tag}_lat"] = round(pt.y, 6) if pt else None
                d[f"{tag}_lon"] = round(pt.x, 6) if pt else None
        gdf = _gdf(ctx, dc_links, DC_FIELDS)
        gdf.to_file(topo_path, layer="dc_link", driver="GPKG", engine="pyogrio")
        counts["dc_link"] = len(gdf)
    if transformers:
        gdf = _gdf(ctx, transformers, TRANSFORMER_FIELDS)
        gdf.to_file(topo_path, layer="transformer", driver="GPKG", engine="pyogrio")
        counts["transformer"] = len(gdf)

    cluster_rows = []
    for s in sites:
        node_buses = [b for b in buses.values() if b["node_id"] == s["station_id"]]
        geom = s["geom"]
        cluster_rows.append({
            "station_id": s["station_id"], "station_name": s["name"],
            "operator": s["operator"], "countries": s.get("countries", ""),
            "n_buses": len(node_buses),
            "voltages_kv": ";".join(fmt_kv(v) for v in
                                    sorted({b["voltage_kv"] for b in node_buses})),
            "n_lines": sum(b["n_lines"] for b in node_buses),
            "n_sub_polygons": s["n_sub_polygons"],
            "osm_substation_ids": s["osm_substation_ids"],
            "component": min((b.get("component", -1) for b in node_buses), default=-1),
            "geom": geom if geom.geom_type == "MultiPolygon" else MultiPolygon([geom]),
        })
    if cluster_rows:
        gdf = _gdf(ctx, cluster_rows, CLUSTER_FIELDS)
        gdf.to_file(topo_path, layer="station_cluster", driver="GPKG", engine="pyogrio")
        counts["station_cluster"] = len(gdf)
    if substations:
        fp_rows = [{
            "osm_id": s["osm_id"], "name": s["name"], "operator": s["operator"],
            "voltage_kv": s["voltage_kv"], "countries": s.get("countries", ""),
            "area_m2": round(s["geom"].area, 1),
            "under_construction": s["under_construction"], "geom": s["geom"],
        } for s in substations]
        gdf = _gdf(ctx, fp_rows, FOOTPRINT_FIELDS)
        gdf.to_file(topo_path, layer="substation_footprint", driver="GPKG", engine="pyogrio")
        counts["substation_footprint"] = len(gdf)

    # --- graph pair: one line layer, one bus layer, for network analysis
    if spans:
        gdf = _gdf(ctx, spans, LINE_FIELDS, geom_key="geom_drawn")
        gdf.to_file(graph_path, layer="ac_line_all", driver="GPKG", engine="pyogrio")
        counts["ac_line_all"] = len(gdf)
    all_bus_rows = []
    for b in buses.values():
        row = dict(b)
        row["geom"] = b["point"]
        row["frequency_source"] = "inherited_from_lines"
        all_bus_rows.append(row)
    gdf = _gdf(ctx, all_bus_rows, SITE_FIELDS + GRAPH_SITE_EXTRA)
    gdf.to_file(graph_path, layer="site_all", driver="GPKG", engine="pyogrio")
    counts["site_all"] = len(gdf)

    write_attribute_tables(ctx, topo_path, counts)
    log(f"  export: {topo_path} ({len(counts)} layers), {graph_path}")
    return counts


def write_attribute_tables(ctx: Ctx, gpkg_path: str, counts: Dict[str, int]) -> None:
    """Ship the transformer typing rule and the build parameters *inside* the
    GeoPackage as registered attributes tables, so QGIS and ogrinfo list them
    (README s13.1 does this for `v23_typing_rule`)."""
    import sqlite3
    con = sqlite3.connect(gpkg_path)
    cur = con.cursor()
    # Same 8 rows and 7 columns as the shipped transformer_typing_rule.csv: the
    # six bands plus the ALT row (the alternative rating column) and the NOTE row
    # (per-unit basis and pinned source commits). Dropping either loses the
    # s_nom/x_pu coupling warning README s13.1 says travels with the data.
    cur.execute("CREATE TABLE v23_typing_rule (band TEXT, selector TEXT, s_nom_mva TEXT, "
                "x_pu TEXT, r_pu TEXT, basis TEXT, source_url TEXT)")
    for band, sel, s_nom, x_pu, r_pu, basis, url in TRANSFORMER_BANDS:
        cur.execute("INSERT INTO v23_typing_rule VALUES (?,?,?,?,?,?,?)",
                    (band, sel, f"{s_nom:g}", f"{x_pu:g}", f"{r_pu:g}", basis, url))
    cur.execute("INSERT INTO v23_typing_rule VALUES (?,?,?,?,?,?,?)", (
        "ALT", "s_nom_pypsa_eur_mva (separate column, all rows)", "", "", "",
        "computed: ceil(max(total incident AC line s_nom at bus0, at bus1)) per PyPSA-Eur "
        "build_osm_network.py - the convention the reference workflow actually ships "
        "(config s_nom=2000 is dead code for the osm base network). Deliberately non-binding. "
        "WARNING: x_pu/r_pu are per-unit on s_nom_mva - mapping this column onto PyPSA s_nom "
        "while keeping x_pu rescales every impedance by the column ratio; recompute or drop "
        "x_pu if you swap.", PYPSA_EUR_SNOM_URL))
    cur.execute("INSERT INTO v23_typing_rule VALUES (?,?,?,?,?,?,?)", (
        "NOTE", "x,r are per-unit on the transformer own s_nom (PyPSA Transformer convention)",
        "", "", "",
        "PyPSA components doc + pypsa/data/component_attrs/transformers.csv. Sources pinned: "
        "pypsa-eur commit 8119040, pandapower tag v3.1.2 (vk/vkr per Oswald teaching text, not "
        "a TSO survey). PyPSA-Eur never sets transformer r (stays 0); this dataset departs "
        "deliberately and sources r from vkr.", PYPSA_COMPONENTS_URL))
    cur.execute("CREATE TABLE build_metadata (key TEXT, value TEXT)")
    meta = {
        "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "region_name": ctx.cfg["region_name"],
        "voltage_floor_kv": str(ctx.cfg["voltage_floor_kv"]),
        "metric_crs": ctx.cfg["metric_crs"],
        "traction_enabled": str(ctx.traction_on),
        "length_method": "haversine R=6371.0088 km",
        "method_reference": "README_methodology_v23.md (rebuild, not the original code)",
        "layer_counts": json.dumps(counts, sort_keys=True),
        "stats": json.dumps(ctx.stats, sort_keys=True, default=str),
    }
    for k, v in meta.items():
        cur.execute("INSERT INTO build_metadata VALUES (?,?)", (k, v))
    for name in ("v23_typing_rule", "build_metadata"):
        cur.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, "
                    "description, last_change) VALUES (?, 'attributes', ?, '', "
                    "strftime('%Y-%m-%dT%H:%M:%fZ','now'))", (name, name))
    con.commit()
    con.close()


# ===========================================================================
# 17. DRIVER
# ===========================================================================

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--harvest-dir")
    ap.add_argument("--out-dir")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.harvest_dir:
        cfg["harvest_dir"] = args.harvest_dir
    if args.out_dir:
        cfg["out_dir"] = args.out_dir
    ctx = Ctx(cfg)
    t0 = time.time()

    paths = ndjson_files(cfg["harvest_dir"])
    if not paths:
        raise SystemExit(f"no NDJSON in {cfg['harvest_dir']} - run 01_harvest_overpass.py first")
    log(f"load/clean: {len(paths)} harvest files")
    conductors, substations, dc_records = load_elements(ctx, paths)
    if not conductors:
        raise SystemExit("no conductors survived cleaning - check voltage_floor_kv")

    assign_countries(ctx, conductors)
    assign_countries(ctx, substations)
    assign_countries(ctx, dc_records)
    for rec in conductors:
        operator_traction_override(ctx, rec)

    # project once into the working metric CRS
    for coll in (conductors, substations, dc_records):
        for rec in coll:
            rec["geom"] = ctx.m(rec["geom_deg"])
            del rec["geom_deg"]

    log("topology:")
    conductors = merge_chains(ctx, conductors)
    site_union = unary_union([s["geom"] for s in substations]) if substations else None
    end_to_end_pass(ctx, conductors, site_union)
    conductors = snap_split_pass(ctx, conductors)

    sites = build_sites(ctx, substations, conductors)
    for s in sites:
        s["countries"] = ";".join(sorted({c for m in s["members"]
                                          for c in split_semicolon(m.get("countries"))}))
    spans, internals = clip_conductors(ctx, conductors, sites)
    spans = assign_ends(ctx, spans, internals, sites)
    junctions = cluster_junctions(ctx, spans)
    tables = build_nodes(ctx, sites, junctions, spans, internals)
    nodes, buses = tables["nodes"], tables["buses"]

    # Pitfall 17: sweep self-loops, dissolve, then sweep again - the dissolve
    # creates fresh loops, and an earlier version of this only swept once.
    spans = sweep_self_loops(ctx, spans, internals)
    spans = dissolve_junctions(ctx, spans, nodes)
    spans = sweep_self_loops(ctx, spans, internals)

    # buses can only shrink after the dissolve; drop any that lost every line
    attach_connectors(ctx, spans, buses)
    used = {sp[f"bus{ei}"] for sp in spans for ei in (0, 1) if sp[f"bus{ei}"]}
    buses = {k: v for k, v in buses.items() if k in used}
    log(f"  buses after dissolve: {len(buses)}")

    assign_line_ids(spans)
    electrical_parameters(ctx, spans)
    transformers = build_transformers(ctx, buses, spans)
    transformers = [t for t in transformers if t["bus0"] in buses and t["bus1"] in buses]
    dc_links = build_dc_links(ctx, dc_records, buses)
    components(ctx, buses, spans, transformers, dc_links)
    bookkeeping(ctx, buses, spans, transformers, dc_links)
    endpoint_labels(ctx, spans, buses, nodes)
    promote_layer_voltages(ctx, spans)

    ctx.stats["spans"] = len(spans)
    ctx.stats["internal_segments"] = len(internals)
    ctx.stats["buses"] = len(buses)
    ctx.stats["route_km"] = round(sum(sp["length_conductor_m"] for sp in spans) / 1000.0, 1)
    ctx.stats["circuit_km"] = round(sum(sp["length_conductor_m"] * sp["n_circuits"]
                                        for sp in spans) / 1000.0, 1)
    ctx.stats["connector_km"] = round(sum(sp["connector0_m"] + sp["connector1_m"]
                                          for sp in spans) / 1000.0, 1)
    counts = export(ctx, spans, internals, buses, nodes, sites, substations,
                    transformers, dc_links, cfg["out_dir"])
    ctx.stats["layer_counts"] = counts
    with open(os.path.join(cfg["out_dir"], "build_stats.json"), "w", encoding="utf-8") as fh:
        json.dump(ctx.stats, fh, indent=1, sort_keys=True, default=str)
    log(f"done in {time.time() - t0:.1f}s: {len(spans)} spans, {len(buses)} buses, "
        f"{ctx.stats['route_km']:.0f} route-km")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
