#!/usr/bin/env python3
"""Validator tests - prove each hard check FIRES on a dataset that violates it.

A review found two of the three diagnostic hard checks were inert: one read a key
the diagnostic never returns, the other resolved its span count from two keys that
do not exist, so both guards evaluated to False on a 91,094-span dataset. Nothing
noticed, because the only validator test asserted that a CLEAN build passes.

This module does the opposite: it takes a clean build, injects one specific defect
into a copy, and requires 03_validate.py to exit non-zero naming that check. A
disabled or misspelled guard therefore fails the suite.

Run: python3 tests/validator_test.py
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def clean_build() -> str:
    """Build the fixture once; return the out dir."""
    d = tempfile.mkdtemp(prefix="valbuild_")
    cfg = os.path.join(d, "c.yaml")
    with open(os.path.join(HERE, "fixture_config.yaml")) as fh:
        text = fh.read()
    text = text.replace("harvest_dir: tests/fixture_harvest", f"harvest_dir: {d}/h")
    text = text.replace("out_dir: tests/fixture_out", f"out_dir: {d}/out")
    os.makedirs(os.path.join(d, "h"))
    shutil.copy(os.path.join(HERE, "fixture.ndjson"), os.path.join(d, "h", "fixture.ndjson"))
    with open(cfg, "w") as fh:
        fh.write(text)
    r = subprocess.run([sys.executable, os.path.join(PKG, "02_build_topology.py"),
                        "--config", cfg], capture_output=True, text=True)
    assert os.path.exists(os.path.join(d, "out", "build_stats.json")), r.stderr[-900:]
    return d, cfg


def validate(cfg: str, out_dir: str):
    r = subprocess.run([sys.executable, os.path.join(PKG, "03_validate.py"),
                        "--config", cfg, "--out-dir", out_dir],
                       capture_output=True, text=True)
    return r.returncode, r.stdout


BASE, BASE_CFG = clean_build()
BASE_OUT = os.path.join(BASE, "out")
rc, out = validate(BASE_CFG, BASE_OUT)
check("clean_build_passes", rc == 0, f"exit {rc}")


def _register_st(con: sqlite3.Connection) -> None:
    """Minimal ST_* shims so a GeoPackage rtree trigger can fire on a plain
    sqlite3 connection (the same trick the patch scripts use)."""
    import struct

    def envelope(blob):
        if blob is None or len(blob) < 8:
            return None
        flags = blob[3]
        env = (flags >> 1) & 7
        if env == 0:
            return None
        fmt = "<" if flags & 1 else ">"
        n = {1: 4, 2: 6, 3: 6, 4: 8}[env]
        v = struct.unpack_from(f"{fmt}{n}d", blob, 8)
        return v[0], v[1], v[2], v[3]

    con.create_function("ST_IsEmpty", 1, lambda b: 1 if b is None else 0)
    for i, fn in enumerate(("ST_MinX", "ST_MaxX", "ST_MinY", "ST_MaxY")):
        con.create_function(fn, 1, (lambda idx: lambda b: (envelope(b) or (None,) * 4)[idx])(i))


def with_defect(mutate) -> tuple:
    """Copy the clean build, apply `mutate(topo_conn)`, run the validator."""
    d = tempfile.mkdtemp(prefix="valdefect_")
    out = os.path.join(d, "out")
    shutil.copytree(BASE_OUT, out)
    cfg = os.path.join(d, "c.yaml")
    with open(BASE_CFG) as fh:
        text = fh.read().replace(BASE_OUT, out)
    with open(cfg, "w") as fh:
        fh.write(text)
    topo = [f for f in os.listdir(out) if f.endswith("_topology.gpkg")][0]
    graph = [f for f in os.listdir(out) if f.endswith("_graph.gpkg")][0]
    con = sqlite3.connect(os.path.join(out, topo))
    gcon = sqlite3.connect(os.path.join(out, graph))
    _register_st(con)          # gpkg rtree triggers call ST_* on insert/update
    _register_st(gcon)
    try:
        mutate(con, gcon)
    except TypeError:
        mutate(con)            # single-argument mutators still work
    con.commit(); gcon.commit()
    con.close(); gcon.close()
    return validate(cfg, out)


def fired(stdout: str, needle: str) -> bool:
    try:
        rep = json.loads(stdout[stdout.index("{"):])
    except Exception:
        return False
    return any(needle in f for f in rep.get("hard_check_failures", []))


# --- diagnostic 1: one element producing more than 20 network spans -------------
def inject_fragments(con, gcon=None):
    row = con.execute("SELECT * FROM line_132kV LIMIT 1").fetchone()
    cols = [c[1] for c in con.execute("PRAGMA table_info(line_132kV)")]
    oid = cols.index("osm_id")
    lid = cols.index("line_id")
    fid = cols.index("fid")
    for i in range(30):
        vals = list(row)
        vals[fid] = 900000 + i
        vals[oid] = "way/999999"
        vals[lid] = f"way/999999:{i}"
        con.execute(f"INSERT INTO line_132kV ({','.join(cols)}) VALUES "
                    f"({','.join('?' * len(cols))})", vals)


rc1, out1 = with_defect(inject_fragments)
check("diagnostic1_fires_on_fragmentation", rc1 != 0 and fired(out1, "diagnostic 1"),
      f"exit {rc1}")


# --- diagnostic 3: internal segments dragged far from any site ------------------
def move_internals(con, gcon=None):
    # push every internal segment 5 km east: their ends are then nowhere near a site
    rows = con.execute("SELECT fid, geom FROM line_internal_to_station").fetchall()
    from shapely import wkb
    from shapely.affinity import translate
    for fid, blob in rows * 40:                     # repeat to clear the 1,000-end guard
        b = bytes(blob)
        env = (b[3] >> 1) & 7
        head = b[:8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[env]]
        g = wkb.loads(b[8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[env]:])
        moved = translate(g, xoff=0.06)
        con.execute("UPDATE line_internal_to_station SET geom=? WHERE fid=?",
                    (head + moved.wkb, fid))
    # and multiply the population so the sample guard is satisfied
    cols = [c[1] for c in con.execute("PRAGMA table_info(line_internal_to_station)")]
    base = con.execute("SELECT * FROM line_internal_to_station").fetchall()
    fidx = cols.index("fid")
    n = 0
    for r in base:
        for i in range(120):
            vals = list(r)
            vals[fidx] = 500000 + n
            n += 1
            con.execute(f"INSERT INTO line_internal_to_station ({','.join(cols)}) VALUES "
                        f"({','.join('?' * len(cols))})", vals)


rc3, out3 = with_defect(move_internals)
check("diagnostic3_fires_on_far_internal_ends", rc3 != 0 and fired(out3, "diagnostic 3"),
      f"exit {rc3}")


# --- diagnostic 4: many wide multi-polygon sites --------------------------------
def widen_sites(con, gcon=None):
    cols = [c[1] for c in con.execute("PRAGMA table_info(station_cluster)")]
    row = con.execute("SELECT * FROM station_cluster LIMIT 1").fetchone()
    from shapely import wkb
    from shapely.geometry import box
    b = bytes(row[cols.index("geom")])
    env = (b[3] >> 1) & 7
    head = b[:8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[env]]
    wide = box(1.0, 51.0, 1.03, 51.02)              # ~2 km across
    fidx, nidx, sidx = cols.index("fid"), cols.index("n_sub_polygons"), cols.index("station_id")
    for i in range(150):
        vals = list(row)
        vals[fidx] = 700000 + i
        vals[nidx] = 2
        vals[sidx] = f"stX{i:05d}"
        vals[cols.index("geom")] = head + wide.wkb
        con.execute(f"INSERT INTO station_cluster ({','.join(cols)}) VALUES "
                    f"({','.join('?' * len(cols))})", vals)


rc4, out4 = with_defect(widen_sites)
check("diagnostic4_fires_on_fused_sites", rc4 != 0 and fired(out4, "diagnostic 4"),
      f"exit {rc4}")


# --- diagnostic 2 and integrity: a bus reference that resolves to nothing -------
def break_bus_ref(con, gcon):
    # the integrity check resolves bus references in the GRAPH file, so the defect
    # has to be injected there
    gcon.execute("UPDATE ac_line_all SET bus0='st9999999_132kV' "
                 "WHERE fid=(SELECT MIN(fid) FROM ac_line_all)")


rc2, out2 = with_defect(break_bus_ref)
check("integrity_fires_on_unresolved_bus", rc2 != 0 and fired(out2, "unresolved bus"),
      f"exit {rc2}")

# --- diagnostic 4, connector branch. This one needs scale: the guard only applies
# above 5,000 spans (a fraction of a tiny build means nothing), and the span count
# comes from ac_line_all in the GRAPH file while the connector lengths come from the
# line layers in the TOPOLOGY file. Both were once resolved from keys that do not
# exist, so the guard was dead on a 91,094-span dataset; this reaches it.
def inject_long_connectors(con, gcon):
    lcols = [c[1] for c in con.execute("PRAGMA table_info(line_132kV)")]
    lrow = list(con.execute("SELECT * FROM line_132kV LIMIT 1").fetchone())
    lf, lid, c0 = lcols.index("fid"), lcols.index("line_id"), lcols.index("connector0_m")
    batch = []
    for i in range(6000):
        v = list(lrow)
        v[lf] = 800000 + i
        v[lid] = f"way/800000:{i}"
        v[c0] = 2500.0 if i < 60 else 5.0       # 60 connectors over 1 km, 1% of 6,000
        batch.append(v)
    con.executemany(f"INSERT INTO line_132kV ({','.join(lcols)}) VALUES "
                    f"({','.join('?' * len(lcols))})", batch)
    gcols = [c[1] for c in gcon.execute("PRAGMA table_info(ac_line_all)")]
    grow = list(gcon.execute("SELECT * FROM ac_line_all LIMIT 1").fetchone())
    gf, glid = gcols.index("fid"), gcols.index("line_id")
    gbatch = []
    for i in range(6000):
        v = list(grow)
        v[gf] = 800000 + i
        v[glid] = f"way/800000:{i}"
        gbatch.append(v)
    gcon.executemany(f"INSERT INTO ac_line_all ({','.join(gcols)}) VALUES "
                     f"({','.join('?' * len(gcols))})", gbatch)


rc5, out5 = with_defect(inject_long_connectors)
check("diagnostic4_connector_branch_fires",
      rc5 != 0 and fired(out5, "connectors over 1 km"), f"exit {rc5}")

print()
print(f"{'ALL CHECKS PASSED' if not FAILS else str(len(FAILS)) + ' FAILED: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
