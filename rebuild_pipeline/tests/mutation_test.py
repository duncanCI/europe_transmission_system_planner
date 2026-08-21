#!/usr/bin/env python3
"""Mutation harness - proves the test suites actually pin the documented gates.

A review of an earlier version of this package mutated eight documented
thresholds (including the site-fusion distance behind the Levallois/Perret
defect and both `n_circuits` terms in the electrical formulas) and the fixture
suite still reported 20/20. Passing tests over a broken gate are worse than no
tests, so "the suite catches a reverted gate" is itself made a tested property
here.

For each mutation: copy the package to a temp dir, rewrite one constant or one
line, run the suites, and require a FAILURE. A mutation that survives is
reported as SURVIVED and fails this harness.

Run: python3 tests/mutation_test.py            # all mutations (slow, ~10 min)
     python3 tests/mutation_test.py --quick    # gate_test only (~4 min)
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)

# (label, file, find, replace) - each reverts one documented behaviour.
MUTATIONS = [
    # decision 5 - the Levallois/Perret gate, both halves independently
    ("decision5_outside_50m_to_1km", "02_build_topology.py",
     "BRIDGE_OUTSIDE_MAX_M = 50.0", "BRIDGE_OUTSIDE_MAX_M = 1000.0"),
    ("decision5_gap_250m_to_2km", "02_build_topology.py",
     "BRIDGE_GAP_MAX_M = 250.0", "BRIDGE_GAP_MAX_M = 2000.0"),
    # decision 4 - the 60 degree value, not just its sign
    ("decision4_cos_minus05_to_plus05", "02_build_topology.py",
     "COS_CONTINUE_MAX = -0.5", "COS_CONTINUE_MAX = 0.5"),
    ("decision4_cos_minus05_to_minus095", "02_build_topology.py",
     "COS_CONTINUE_MAX = -0.5", "COS_CONTINUE_MAX = -0.95"),
    # decision 9 - the parallel-rejection angle
    ("decision9_parallel_25deg_to_89deg", "02_build_topology.py",
     "PARALLEL_REJECT_DEG = 25.0", "PARALLEL_REJECT_DEG = 89.0"),
    ("decision9_parallel_25deg_to_1deg", "02_build_topology.py",
     "PARALLEL_REJECT_DEG = 25.0", "PARALLEL_REJECT_DEG = 1.0"),
    # decision 13 - the width caps and the never-burst rule
    ("decision13_ext_cap_250m_to_25m", "02_build_topology.py",
     "EXT_MAX_CLUSTER_M = 250.0", "EXT_MAX_CLUSTER_M = 25.0"),
    ("decision13_seeded_membership_reverted", "02_build_topology.py",
     "members: Dict[int, List[int]] = {r: list(m) for r, m in uf.groups().items()}",
     "members: Dict[int, List[int]] = {i: [i] for i in range(len(points))}"),
    # decision 8 / decision 7 distances
    ("decision8_free_end_50m_to_5m", "02_build_topology.py",
     "FREE_END_MIN_M = 50.0", "FREE_END_MIN_M = 5.0"),
    ("decision7_fence_30m_to_300m", "02_build_topology.py",
     "SITE_FENCE_TOL_M = 30.0", "SITE_FENCE_TOL_M = 300.0"),
    # decision 10 / decision 14
    ("decision10_ee_ceiling_150m_to_5km", "02_build_topology.py",
     "EE_TOL_FREE_M = 150.0", "EE_TOL_FREE_M = 5000.0"),
    ("decision14_length_check_disabled", "02_build_topology.py",
     "LENGTH_RETENTION_MIN = 0.999", "LENGTH_RETENTION_MIN = 0.0"),
    # electrical conventions - both n_circuits terms
    ("s_nom_drops_n_circuits", "02_build_topology.py",
     'sp["s_nom_mva"] = math.sqrt(3.0) * kv * i_nom * nc',
     'sp["s_nom_mva"] = math.sqrt(3.0) * kv * i_nom'),
    ("impedance_drops_n_circuits", "02_build_topology.py",
     'sp["r_ohm"] = r_km * L_km / nc', 'sp["r_ohm"] = r_km * L_km'),
    ("transformer_artefact_ratio", "02_build_topology.py",
     "TRANSFORMER_RATIO_ARTEFACT = 1.095", "TRANSFORMER_RATIO_ARTEFACT = 2.0"),
    # v22 duplicate-corridor collapse
    ("duplicate_collapse_disabled", "02_build_topology.py",
     "        if len(oids) < 2:", "        if True:"),
    # harvest banding and the region-wide DC sweep
    ("voltage_band_upper_bound_dropped", "01_harvest_overpass.py",
     "        alts.extend(_fixed_width_alts(band_lo, band_hi, width))",
     "        alts.extend(_fixed_width_alts(band_lo, 10 ** width - 1, width))"),
    ("dc_sweep_back_to_one_area", "01_harvest_overpass.py",
     '    return [sc for sc in chunk_scopes(cfg) if sc["kind"] == "area"]',
     "    return [chunk_scopes(cfg)[0]]"),
    # grid frequency hardcoded again
    # logic mutations a value table cannot catch - each of these survived an earlier
    # version of the suite and is now covered behaviourally
    ("decision12_site_condition_removed", "02_build_topology.py",
     '        if nodes[nid]["is_site"] or len(items) < 2:', "        if len(items) < 2:"),
    ("decision7_anchoring_weakened", "02_build_topology.py",
     "            anchored = False", "            anchored = True"),
    ("decision3_bus_placement_centroid", "02_build_topology.py",
     "def _pia(node: Dict) -> Point:", "def _pia(node: Dict) -> Point:\n    return node[\"geom\"].centroid"),
    # The post-hoc gate and the re-cluster tolerance are redundant defences against
    # bursting: reverting either alone is harmless, so the mutation reverts BOTH,
    # reconstructing the pre-fix state that turned one legal cluster into singletons.
    ("decision13_bursting_fully_reverted", "02_build_topology.py",
     "        if cluster_width([pts[k] for k in members]) <= MAX_CLUSTER_M or len(members) < 2:\n"
     "            clusters.append(members)\n"
     "            continue\n"
     "        sub = single_linkage([pts[k] for k in members], JUNCTION_TOL_M, MAX_CLUSTER_M)",
     "        if cluster_width([pts[k] for k in members]) <= EXT_MAX_CLUSTER_M or len(members) < 2:\n"
     "            clusters.append(members)\n"
     "            continue\n"
     "        sub = single_linkage([pts[k] for k in members], 10.0, EXT_MAX_CLUSTER_M)"),
    ("duplicate_collapse_ignores_voltage", "02_build_topology.py",
     "            by_members[(ways, volt)].append(oid)", "            by_members[(ways,)].append(oid)"),
    ("duplicate_collapse_key_narrowed", "02_build_topology.py",
     "        ways = tuple(sorted(rel_member_ways.get(oid, [])))",
     "        ways = tuple(sorted(rel_member_ways.get(oid, []))[:1])"),
    # schema drift a count-only assertion missed
    ("schema_field_renamed", "02_build_topology.py",
     '"line_label_source", "ref", "operator"', '"label_src", "ref", "operator"'),
    # validator hard-check wiring - all three were inert once
    ("validator_d3_limit_disabled", "03_validate.py",
     "    if n_ends >= 1000 and (d3.get(\"p95_m\") or 0) > INTERNAL_END_FLAG_M:",
     "    if False:"),
    ("validator_d1_check_removed", "03_validate.py",
     '    if d1["elements_over_20_network_spans"]:                 # v23 reference: 0',
     "    if False:"),
    ("validator_d4_nspans_resolution_reverted", "03_validate.py",
     '    nspans = int(report["summary"].get("ac_spans_network") or 0)',
     '    nspans = int(report.get("layer_counts", {}).get("ac_line_all") or 0)'),
    ("validator_d4_connector_limit_disabled", "03_validate.py",
     '    if nspans >= 5000 and d4["connectors_over_1km"] > 0.00015 * nspans:',
     "    if False:"),
    ("validator_d4_limit_loosened", "03_validate.py",
     '    if mp >= 100 and d4["multi_polygon_sites_wider_than_1km"] > 0.014 * mp:',
     "    if mp >= 100 and False:"),
    ("grid_frequency_hardcoded_50", "common.py",
     '    cfg["grid_frequency_hz"] = float(cfg["grid_frequency_hz"])',
     '    cfg["grid_frequency_hz"] = 50.0'),
]


def run_suite(root: str, suite: str, timeout: int = 900) -> int:
    r = subprocess.run([sys.executable, os.path.join(root, "tests", suite)],
                       capture_output=True, text=True, timeout=timeout, cwd=root)
    return r.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="gate_test only")
    ap.add_argument("--only", help="run one mutation by label")
    args = ap.parse_args()
    suites = (["gate_test.py", "validator_test.py"] if args.quick
              else ["gate_test.py", "validator_test.py", "fixture_test.py"])

    muts = [m for m in MUTATIONS if not args.only or m[0] == args.only]
    survived, caught = [], []
    for label, fname, find, repl in muts:
        work = tempfile.mkdtemp(prefix="mut_")
        root = os.path.join(work, "pkg")
        shutil.copytree(PKG, root, ignore=shutil.ignore_patterns("__pycache__", "*.pyc",
                                                                "fixture_out", "harvest*", "out"))
        path = os.path.join(root, fname)
        with open(path) as fh:
            src = fh.read()
        if src.count(find) != 1:
            print(f"SKIP  {label}: anchor not unique in {fname} ({src.count(find)} matches)")
            survived.append(label + " (anchor missing)")
            continue
        with open(path, "w") as fh:
            fh.write(src.replace(find, repl))
        rc = 0
        for suite in suites:
            try:
                rc = run_suite(root, suite)
            except subprocess.TimeoutExpired:
                rc = 99
            if rc != 0:
                break
        if rc == 0:
            print(f"SURVIVED  {label}  <- no suite noticed this")
            survived.append(label)
        else:
            print(f"caught    {label}  (exit {rc})")
            caught.append(label)
        shutil.rmtree(work, ignore_errors=True)

    print()
    print(f"{len(caught)}/{len(muts)} mutations caught")
    if survived:
        print("SURVIVED: " + ", ".join(survived))
        return 1
    # Deliberately measured, not a slogan: this says the mutations IN THIS LIST are
    # caught. Constants whose only cover is the documented-value table (a coordinated
    # edit of constant plus table would pass) are listed in README_pipeline.md so the
    # coverage gap is visible rather than implied away.
    print(f"all {len(muts)} listed mutations are caught by the suite "
          "(see README_pipeline.md for the constants that carry value-table cover only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
