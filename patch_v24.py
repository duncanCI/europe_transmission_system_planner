#!/usr/bin/env python3
"""v24: fuse NVE-only Norwegian network into the dataset.

Adds 189 lines (1,053 km, 50-420 kV), 63 substations and 72 junction nodes from
NVE Nettanlegg (NLOD 1.0) that have no counterpart in the OSM-built layers.
Everything added carries source and qa_flags markers; nothing existing is
modified or deleted. Evidence: v24_evidence_lines.csv / v24_evidence_stations.csv.

Run from the project folder, with nve_additions_v24.gpkg beside it:
    python3 patch_v24.py            # dry run - prints what it would do
    python3 patch_v24.py --apply    # backs up both GeoPackages, then applies

Stdlib only (sqlite3, shutil). Safe to re-run: refuses if v24 is already applied.
"""
import sqlite3
import shutil
import sys
import os

TOPO = "europe_grid_topology.gpkg"
GRAPH = "europe_grid_graph.gpkg"
ADDS = "nve_additions_v24.gpkg"
APPLY = "--apply" in sys.argv

for f in (TOPO, GRAPH, ADDS):
    if not os.path.exists(f):
        sys.exit(f"missing {f} - run from the project folder")

adds = sqlite3.connect(ADDS)
add_layers = [r[0] for r in adds.execute(
    "SELECT table_name FROM gpkg_contents WHERE data_type='features'")]
adds.close()

topo_targets = {l[len("add__"):]: l for l in add_layers
                if not l.startswith("add__graph_")}
graph_targets = {"ac_line_all": "add__graph_ac_line_all",
                 "site_all": "add__graph_site_all"}


def cols_of(con, table):
    return [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]


# --- GeoPackage geometry helpers -------------------------------------------
# The GeoPackages carry GDAL-created spatial-index triggers that call ST_*
# functions normally registered by GDAL/Spatialite. Plain sqlite3 lacks them,
# so register stdlib implementations that read the GPKG binary header
# (envelope if present, else compute bounds from the WKB - Point/LineString/
# MultiLineString are all v24 inserts).
import struct


def _gp_parse(blob):
    if blob is None or len(blob) < 8:
        return None
    flags = blob[3]
    empty = (flags >> 4) & 1
    env = (flags >> 1) & 7
    endian = "<" if (flags & 1) else ">"
    n_env = {0: 0, 1: 4, 2: 6, 3: 6, 4: 8}.get(env, 0)
    envelope = struct.unpack_from(f"{endian}{n_env}d", blob, 8) if n_env else None
    return empty, envelope, 8 + n_env * 8


def _wkb_bounds(b):
    xs, ys = [], []

    def read(off):
        little = b[off] == 1
        f = "<" if little else ">"
        t = struct.unpack_from(f + "I", b, off + 1)[0] & 0xFF
        off += 5
        if t == 1:                                   # Point
            x, y = struct.unpack_from(f + "2d", b, off)
            xs.append(x); ys.append(y)
            return off + 16
        if t == 2:                                   # LineString
            n = struct.unpack_from(f + "I", b, off)[0]
            off += 4
            for i in range(n):
                x, y = struct.unpack_from(f + "2d", b, off + i * 16)
                xs.append(x); ys.append(y)
            return off + 16 * n
        if t in (4, 5, 6, 7):                        # Multi*/collection
            n = struct.unpack_from(f + "I", b, off)[0]
            off += 4
            for _ in range(n):
                off = read(off)
            return off
        raise ValueError(f"wkb type {t}")

    read(0)
    return (min(xs), max(xs), min(ys), max(ys)) if xs else None


def _bounds(blob):
    p = _gp_parse(blob)
    if p is None:
        return None
    empty, envelope, hdr = p
    if empty:
        return None
    if envelope:
        return envelope[0], envelope[1], envelope[2], envelope[3]
    return _wkb_bounds(blob[hdr:])


def register_st_functions(con):
    def st_isempty(blob):
        p = _gp_parse(blob)
        return 1 if (p is None or p[0]) else 0

    def mk(idx):
        def f(blob):
            bb = _bounds(blob)
            return bb[idx] if bb else None
        return f

    con.create_function("ST_IsEmpty", 1, st_isempty)
    con.create_function("ST_MinX", 1, mk(0))
    con.create_function("ST_MaxX", 1, mk(1))
    con.create_function("ST_MinY", 1, mk(2))
    con.create_function("ST_MaxY", 1, mk(3))
    con.create_function("ST_GeometryType", 1, lambda b: None)
    con.create_function("GPKG_IsAssignable", 2, lambda a, b: 1)
    con.create_function("ST_SRID", 1, lambda b: struct.unpack_from(
        "<i" if (b[3] & 1) else ">i", b, 4)[0] if b and len(b) >= 8 else None)


def apply_into(dbpath, targets, label):
    con = sqlite3.connect(dbpath)
    register_st_functions(con)
    cur = con.cursor()
    # guard: already applied?
    probe = "ac_line_all" if label == "graph" else "line_66kV"
    if cur.execute(f"SELECT COUNT(*) FROM {probe} WHERE qa_flags LIKE '%nve_fused_v24%'").fetchone()[0]:
        print(f"  {label}: v24 already applied - skipping")
        con.close()
        return
    cur.execute(f"ATTACH DATABASE '{ADDS}' AS aux")
    total = 0
    for target, src in sorted(targets.items()):
        tcols = cols_of(con, target)
        scols = cols_of(con, f"aux.{src}") if False else [
            r[1] for r in cur.execute(f'PRAGMA aux.table_info("{src}")')]
        common = [c for c in tcols if c in scols and c != "fid"]
        n_src = cur.execute(f'SELECT COUNT(*) FROM aux."{src}"').fetchone()[0]
        missing = [c for c in tcols if c not in scols and c != "fid"]
        collist = ", ".join(f'"{c}"' for c in common)
        if APPLY:
            before = cur.execute(f'SELECT COUNT(*) FROM "{target}"').fetchone()[0]
            cur.execute(f'INSERT INTO "{target}" ({collist}) SELECT {collist} FROM aux."{src}"')
            after = cur.execute(f'SELECT COUNT(*) FROM "{target}"').fetchone()[0]
            assert after - before == n_src, f"{target}: inserted {after-before}, expected {n_src}"
            print(f"  {target}: +{n_src}" + (f"  (defaults for: {','.join(missing)})" if missing else ""))
        else:
            print(f"  would insert {n_src} rows into {target}" +
                  (f"  (target-only cols left NULL: {','.join(missing)})" if missing else ""))
        total += n_src
        # warn if a spatial index exists but its insert trigger is missing
        has_rtree = cur.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name=?", (f"rtree_{target}_geom",)).fetchone()[0]
        has_trig = cur.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE ?",
            (f"rtree_{target}_geom_insert%",)).fetchone()[0]
        if has_rtree and not has_trig:
            print(f"    WARNING {target}: spatial index present but no insert trigger - "
                  f"recreate the spatial index in QGIS after applying")
    if APPLY:
        con.commit()
    con.close()
    print(f"  {label}: {total} rows {'inserted' if APPLY else 'pending'}")


if APPLY:
    for f in (TOPO, GRAPH):
        bak = f.replace(".gpkg", ".v23.bak.gpkg")
        if not os.path.exists(bak):
            print(f"backing up {f} -> {bak} ...")
            shutil.copyfile(f, bak)
        else:
            print(f"backup {bak} already exists - keeping it")

print(("APPLYING" if APPLY else "DRY RUN") + " v24 NVE fusion")
print(f"topology ({TOPO}):")
apply_into(TOPO, topo_targets, "topology")
print(f"graph ({GRAPH}):")
apply_into(GRAPH, graph_targets, "graph")
if not APPLY:
    print("\nnothing changed. Re-run with --apply to fuse.")
else:
    print("\ndone. Revert = restore the two .v23.bak.gpkg files.")
