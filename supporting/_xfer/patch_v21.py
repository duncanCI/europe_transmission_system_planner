#!/usr/bin/env python3
# patch_v21.py - surgical corrections to the Europe grid GeoPackages (v20 -> v21).
# Runs identically on the container scratch copies and on the device files.
# Usage: python3 patch_v21.py <dir containing europe_grid_topology.gpkg + europe_grid_graph.gpkg>
# Every change is driven by the SWITCHES block and logged to stdout as JSON lines.
import sqlite3, sys, os, json, datetime

DIR = sys.argv[1]
APPLY = len(sys.argv) > 2 and sys.argv[2] == "apply"  # without "apply": dry-run (rollback at end)

# ---------------- SWITCHES (set from verified ground truth) ----------------
NORFOLK_DC = True   # Vattenfall contract award: 320 kV DC XLPE export cables, HVDC onshore route; converter to 400 kV AC at Necton
BERWICK_DC = True   # Cambois Connection Marine Scheme ES Table 5.3: HVDC export cables, max operating 525 kV (design envelope)
ITALY_KV   = 132    # OSM voltage=500000 keystroke error; sibling ways of same line tagged 50000; Terna operates no 500 kV AC
HORNSEA_KV = 220    # Ofgem OFTO asset list: all three Hornsea One export circuits are 220 kV AC
# ---------------------------------------------------------------------------

# ---- GPKG spatial functions required by the rtree triggers (pure stdlib) ----
import struct
def _gpkg_env(b):
    if b is None: return None
    flags = b[3]; env = (flags >> 1) & 0x07; empty = (flags >> 4) & 1
    envlen = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[env]
    return env, empty, 8 + envlen
def _wkb_bounds(b, off):
    # minimal WKB walker for (Multi)LineString / Point, XY(+Z/M ignored via type code)
    def parse(o):
        little = b[o] == 1; fmt = "<" if little else ">"
        gtype = struct.unpack_from(fmt + "I", b, o + 1)[0]
        base = gtype % 1000
        dims = 2 + (1 if gtype in range(1001, 1008) or gtype in range(3001, 3008) else 0) + (2 if gtype in range(3001, 3008) else 0) + (1 if gtype in range(2001, 2008) else 0)
        o += 5
        xs, ys = [], []
        if base == 1:
            c = struct.unpack_from(fmt + f"{dims}d", b, o); o += 8 * dims
            xs.append(c[0]); ys.append(c[1])
        elif base == 2:
            n = struct.unpack_from(fmt + "I", b, o)[0]; o += 4
            for i in range(n):
                c = struct.unpack_from(fmt + f"{dims}d", b, o); o += 8 * dims
                xs.append(c[0]); ys.append(c[1])
        elif base in (4, 5, 6, 7):
            n = struct.unpack_from(fmt + "I", b, o)[0]; o += 4
            for i in range(n):
                sx, sy, o = parse(o)
                xs += sx; ys += sy
        else:
            raise ValueError(f"wkb type {gtype}")
        return xs, ys, o
    xs, ys, _ = parse(off)
    return min(xs), max(xs), min(ys), max(ys)
def _bounds(b):
    env, empty, off = _gpkg_env(b)
    if empty: return None
    if env >= 1:
        minx, maxx, miny, maxy = struct.unpack_from("<4d", b, 8)
        return minx, maxx, miny, maxy
    return _wkb_bounds(b, off)
def _st(idx):
    def f(b):
        r = _bounds(b)
        return None if r is None else r[idx]
    return f
def register_gpkg_functions(con):
    con.create_function("ST_IsEmpty", 1, lambda b: None if b is None else _gpkg_env(b)[1])
    con.create_function("ST_MinX", 1, _st(0)); con.create_function("ST_MaxX", 1, _st(1))
    con.create_function("ST_MinY", 1, _st(2)); con.create_function("ST_MaxY", 1, _st(3))
# ------------------------------------------------------------------------------

NOW = "2026-08-18T00:30:00Z"
LOG = []
def log(action, **kw):
    entry = {"action": action, **kw}
    LOG.append(entry)
    print(json.dumps(entry, ensure_ascii=False))

t = sqlite3.connect(os.path.join(DIR, "europe_grid_topology.gpkg"))
g = sqlite3.connect(os.path.join(DIR, "europe_grid_graph.gpkg"))
t.row_factory = sqlite3.Row
g.row_factory = sqlite3.Row
register_gpkg_functions(t)
register_gpkg_functions(g)

def cols(con, tb):
    return [r[1] for r in con.execute(f'PRAGMA table_info("{tb}")')]

def bump_counts(con, *tables):
    for tb in set(tables):
        n = con.execute(f'SELECT COUNT(*) FROM "{tb}"').fetchone()[0]
        con.execute("UPDATE gpkg_ogr_contents SET feature_count=? WHERE table_name=?", (n, tb))
        con.execute("UPDATE gpkg_contents SET last_change=? WHERE table_name=?", (NOW, tb))

def add_flag(con, tb, keycol, keyval, flag, flagcol="qa_flags"):
    cur = con.execute(f'SELECT "{flagcol}" FROM "{tb}" WHERE "{keycol}"=?', (keyval,)).fetchone()
    if cur is None: raise SystemExit(f"add_flag: no row {tb}.{keycol}={keyval}")
    old = cur[0] or ""
    parts = [p for p in old.split(";") if p]
    if flag not in parts: parts.append(flag)
    con.execute(f'UPDATE "{tb}" SET "{flagcol}"=? WHERE "{keycol}"=?', (";".join(parts), keyval))

# ---------- PART A1: dc_link qa_flags column ----------
if "qa_flags" not in cols(t, "dc_link"):
    t.execute("ALTER TABLE dc_link ADD COLUMN qa_flags TEXT")
    log("dc_link.add_column", column="qa_flags")

# ---------- PART A2: delete out-of-scope dc rows ----------
for name, why in [
    ("HVDC Saudi Arabia-Egypt", "outside coverage area (Red Sea; bbox 24.4-36.0N, 27.9-39.8E); countries tag EU only; both ends unattached"),
    ("Чарняны - Днепрабугская", "Belarus-Ukraine 110 kV line mis-tagged as DC in OSM; Belarus outside the 36-country scope; no 110 kV HVDC exists; both ends unattached"),
]:
    row = t.execute("SELECT fid, osm_id, voltage_kv FROM dc_link WHERE name=?", (name,)).fetchone()
    if row:
        t.execute("DELETE FROM dc_link WHERE fid=?", (row["fid"],))
        log("dc_link.delete", name=name, osm_id=row["osm_id"], voltage_kv=row["voltage_kv"], why=why)

# ---------- PART A3: attach the two Spittal-area converter ends ----------
# Caithness-Moray Link: bus0=Blackhillock 400 kV attached; geometry's other end terminates
# in the Spittal converter area (3.8 km from the Spittal 275 kV bus, within the build's own
# 10 km DC_MAX_CONVERTER rule). SSEN's Caithness-Moray converters are at Spittal and Blackhillock.
row = t.execute("SELECT fid,bus0,bus1 FROM dc_link WHERE name='Caithness-Moray Link'").fetchone()
if row and row["bus1"] is None:
    t.execute("UPDATE dc_link SET bus1='st0007811_275kV' WHERE fid=?", (row["fid"],))
    add_flag(t, "dc_link", "fid", row["fid"], "dc_attach_manual_spittal_converter")
    log("dc_link.attach", name="Caithness-Moray Link", side="bus1", bus="st0007811_275kV",
        why="mainland converter is Spittal (SSEN); geometry end 3.8 km from Spittal bus, inside the 10 km converter rule")
# Shetland HVDC Connection: bus1=Kergord 132 kV (Shetland) attached; mainland end integrates
# at the Spittal switching/converter site.
row = t.execute("SELECT fid,bus0,bus1 FROM dc_link WHERE name='Shetland HVDC Connection'").fetchone()
if row and row["bus0"] is None:
    t.execute("UPDATE dc_link SET bus0='st0007811_275kV' WHERE fid=?", (row["fid"],))
    add_flag(t, "dc_link", "fid", row["fid"], "dc_attach_manual_spittal_converter")
    log("dc_link.attach", name="Shetland HVDC Connection", side="bus0", bus="st0007811_275kV",
        why="Shetland link integrates with Caithness-Moray at Spittal; geometry end in the Spittal area")

# ---------- PART A4: flag remaining unattached / third-country / disused dc rows ----------
FLAGS = {
    "Borwin 1": "unattached_end_offshore_platform_unmapped",
    "Borwin 2": "unattached_end_offshore_platform_unmapped",
    "Dolwin 1": "unattached_end_offshore_platform_unmapped",
    "Dolwin 2": "unattached_end_offshore_platform_unmapped",
    "HVDC DolWin 3": "unattached_end_offshore_platform_unmapped",
    "Dogger Bank A Export Cable": "unattached_end_offshore_platform_unmapped",
    "Dogger Bank B HVDC export cable": "unattached_end_offshore_platform_unmapped",
    "East Anglia THREE Grid Connection": "unattached_end_offshore_platform_unmapped",
    "IJmuiden Ver Beta Exportkabel": "unattached_end_offshore_platform_unmapped",
    "Выборгская - Юлликкяля": "third_country_link_RU;unattached_end_outside_coverage",
    "Выборгская - Кюми": "third_country_link_RU;unattached_end_outside_coverage",
    "Волгоград — Донбасс / Волгоград — Донбас": "third_country_link_RU;non_operational",
    "Caithness/Spittal": "partial_mapping_unattached_end",
}
for name, flags in FLAGS.items():
    for row in t.execute("SELECT fid FROM dc_link WHERE name=?", (name,)).fetchall():
        for f in flags.split(";"):
            add_flag(t, "dc_link", "fid", row["fid"], f)
    log("dc_link.flag", name=name, flags=flags)

# ---------- helpers for span moves / retags ----------
LINE_COLS_SHARED = None
def move_line_layer(line_id, src, dst, new_kv=None, extra_flag=None):
    """Move a span between same-schema line layers in the topology gpkg."""
    global LINE_COLS_SHARED
    c_src = cols(t, src); c_dst = cols(t, dst)
    shared = [c for c in c_src if c in c_dst and c != "fid"]
    sel = ",".join(f'"{c}"' for c in shared)
    row = t.execute(f'SELECT {sel} FROM "{src}" WHERE line_id=?', (line_id,)).fetchone()
    if row is None: raise SystemExit(f"move_line_layer: {line_id} not in {src}")
    vals = dict(zip(shared, row))
    if new_kv is not None: vals["voltage_kv"] = new_kv
    if extra_flag:
        parts = [p for p in (vals.get("qa_flags") or "").split(";") if p and p != "nonstandard_voltage"]
        parts.append(extra_flag); vals["qa_flags"] = ";".join(parts)
    t.execute(f'INSERT INTO "{dst}" ({",".join(chr(34)+c+chr(34) for c in vals)}) VALUES ({",".join("?"*len(vals))})',
              list(vals.values()))
    t.execute(f'DELETE FROM "{src}" WHERE line_id=?', (line_id,))
    bump_counts(t, src, dst)
    log("topo.move_span", line_id=line_id, src=src, dst=dst, new_kv=new_kv)

def delete_bus(bus_id):
    """Remove a bus everywhere: graph site_all + topo junction_node / site_<kV> / site_other_kV."""
    n = g.execute("SELECT COUNT(*) FROM ac_line_all WHERE bus0=? OR bus1=?", (bus_id, bus_id)).fetchone()[0]
    n += t.execute("SELECT COUNT(*) FROM transformer WHERE bus0=? OR bus1=?", (bus_id, bus_id)).fetchone()[0]
    n += t.execute("SELECT COUNT(*) FROM dc_link WHERE bus0=? OR bus1=?", (bus_id, bus_id)).fetchone()[0]
    if n: raise SystemExit(f"delete_bus: {bus_id} still referenced {n}x")
    g.execute("DELETE FROM site_all WHERE bus_id=?", (bus_id,))
    touched = ["site_all"]
    for lay in [r[0] for r in t.execute("SELECT table_name FROM gpkg_contents WHERE table_name LIKE 'site_%' OR table_name='junction_node'")]:
        if "bus_id" in cols(t, lay):
            c = t.execute(f'SELECT COUNT(*) FROM "{lay}" WHERE bus_id=?', (bus_id,)).fetchone()[0]
            if c:
                t.execute(f'DELETE FROM "{lay}" WHERE bus_id=?', (bus_id,))
                bump_counts(t, lay)
    bump_counts(g, "site_all")
    log("bus.delete", bus_id=bus_id)

def retag_bus(old_id, new_kv):
    """Rename a bus to a new voltage. If the target id already exists, merge into it."""
    new_id = old_id.rsplit("_", 1)[0] + f"_{new_kv}kV"
    exists = g.execute("SELECT 1 FROM site_all WHERE bus_id=?", (new_id,)).fetchone() is not None
    for con, tb, cs in [(g, "ac_line_all", ("bus0", "bus1")), (t, "transformer", ("bus0", "bus1")), (t, "dc_link", ("bus0", "bus1"))]:
        for c in cs:
            con.execute(f'UPDATE "{tb}" SET "{c}"=? WHERE "{c}"=?', (new_id, old_id))
    if exists:
        # merge: recompute degree / n_lines / connected ids on the surviving bus
        old = g.execute("SELECT connected_line_ids FROM site_all WHERE bus_id=?", (old_id,)).fetchone()
        g.execute("DELETE FROM site_all WHERE bus_id=?", (old_id,))
        ids = g.execute("SELECT connected_line_ids FROM site_all WHERE bus_id=?", (new_id,)).fetchone()[0] or ""
        merged = ";".join(sorted(set(filter(None, (ids + ";" + (old[0] or "")).split(";")))))
        deg = g.execute("SELECT COUNT(*) FROM ac_line_all WHERE bus0=? OR bus1=?", (new_id, new_id)).fetchone()[0]
        g.execute("UPDATE site_all SET connected_line_ids=?, degree=?, n_lines=? WHERE bus_id=?", (merged, deg, deg, new_id))
        for lay in [r[0] for r in t.execute("SELECT table_name FROM gpkg_contents WHERE table_name LIKE 'site_%' OR table_name='junction_node'")]:
            if "bus_id" in cols(t, lay):
                if t.execute(f'SELECT 1 FROM "{lay}" WHERE bus_id=?', (old_id,)).fetchone():
                    t.execute(f'DELETE FROM "{lay}" WHERE bus_id=?', (old_id,))
                    bump_counts(t, lay)
        bump_counts(g, "site_all")
        log("bus.merge", old=old_id, into=new_id)
    else:
        g.execute("UPDATE site_all SET bus_id=?, voltage_kv=? WHERE bus_id=?", (new_id, new_kv, old_id))
        for lay in [r[0] for r in t.execute("SELECT table_name FROM gpkg_contents WHERE table_name LIKE 'site_%' OR table_name='junction_node'")]:
            lc = cols(t, lay)
            if "bus_id" in lc and t.execute(f'SELECT 1 FROM "{lay}" WHERE bus_id=?', (old_id,)).fetchone():
                if lay.startswith("site_") and lay not in (f"site_{new_kv}kV", "site_all"):
                    # move the record to the right per-voltage site layer if it exists, else site_other_kV
                    dst = f"site_{new_kv}kV"
                    if not t.execute("SELECT 1 FROM gpkg_contents WHERE table_name=?", (dst,)).fetchone():
                        dst = "site_other_kV"
                    shared = [c for c in lc if c in cols(t, dst) and c != "fid"]
                    sel = ",".join(f'"{c}"' for c in shared)
                    row = t.execute(f'SELECT {sel} FROM "{lay}" WHERE bus_id=?', (old_id,)).fetchone()
                    vals = dict(zip(shared, row)); vals["bus_id"] = new_id; vals["voltage_kv"] = new_kv
                    t.execute(f'INSERT INTO "{dst}" ({",".join(chr(34)+c+chr(34) for c in vals)}) VALUES ({",".join("?"*len(vals))})', list(vals.values()))
                    t.execute(f'DELETE FROM "{lay}" WHERE bus_id=?', (old_id,))
                    bump_counts(t, lay, dst)
                else:
                    t.execute(f'UPDATE "{lay}" SET bus_id=?, voltage_kv=? WHERE bus_id=?', (new_id, new_kv, old_id))
                    bump_counts(t, lay)
        bump_counts(g, "site_all")
        log("bus.rename", old=old_id, new=new_id)
    return new_id

def fix_station_voltages(station_id, old_kv, new_kv):
    """Rewrite the station_voltages_kv string on every bus of a station (old level -> new or removed)."""
    for con, tb in [(g, "site_all")] + [(t, r[0]) for r in t.execute(
            "SELECT table_name FROM gpkg_contents WHERE table_name LIKE 'site_%' OR table_name='junction_node'")]:
        if "station_voltages_kv" not in cols(con, tb): continue
        for row in con.execute(f'SELECT bus_id, station_voltages_kv FROM "{tb}" WHERE station_id=?', (station_id,)).fetchall():
            lv = [v for v in (row["station_voltages_kv"] or "").split(";") if v]
            if new_kv is None:
                lv = [v for v in lv if v != str(old_kv)]
            else:
                lv = [str(new_kv) if v == str(old_kv) else v for v in lv]
            lv = sorted(set(lv), key=lambda x: int(x))
            con.execute(f'UPDATE "{tb}" SET station_voltages_kv=? WHERE bus_id=?', (";".join(lv), row["bus_id"]))
    log("station.voltages_fixed", station_id=station_id, old=old_kv, new=new_kv)

def ac_span_to_dc(line_id, src_layer, ac_bus=None, dc_flags=""):
    """Move an AC span (graph + topo) into dc_link. ac_bus attaches the AC-side end if known."""
    row = g.execute("SELECT * FROM ac_line_all WHERE line_id=?", (line_id,)).fetchone()
    if row is None: raise SystemExit(f"ac_span_to_dc: {line_id} missing")
    trow = t.execute(f'SELECT geom FROM "{src_layer}" WHERE line_id=?', (line_id,)).fetchone()
    t.execute("""INSERT INTO dc_link (geom, osm_id, name, voltage_kv, bus0, bus1, start_point, end_point,
                 start_lat, start_lon, end_lat, end_lon, countries, qa_flags)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (trow["geom"], row["osm_id"], row["line_label"], row["voltage_kv"], ac_bus, None,
               row["start_point"], row["end_point"], row["start_lat"], row["start_lon"],
               row["end_lat"], row["end_lon"], row["countries"], dc_flags))
    old_buses = [row["bus0"], row["bus1"]]
    g.execute("DELETE FROM ac_line_all WHERE line_id=?", (line_id,))
    t.execute(f'DELETE FROM "{src_layer}" WHERE line_id=?', (line_id,))
    bump_counts(g, "ac_line_all"); bump_counts(t, src_layer, "dc_link")
    log("ac_span_to_dc", line_id=line_id, name=row["line_label"], kv=row["voltage_kv"], ac_bus=ac_bus, flags=dc_flags)
    return old_buses

# ---------- PART B: verdict-gated fixes ----------
if NORFOLK_DC:
    buses = ac_span_to_dc("way/1385048215", "line_other_kV", ac_bus="st0022516_400kV",
                          dc_flags="reclassified_from_ac_manual;under_construction")
    tr = t.execute("SELECT transformer_id FROM transformer WHERE transformer_id='st0022516_320_400'").fetchone()
    if tr:
        t.execute("DELETE FROM transformer WHERE transformer_id='st0022516_320_400'")
        bump_counts(t, "transformer")
        log("transformer.delete", transformer_id="st0022516_320_400",
            why="the 320/400 pair at Norfolk Vanguard West is a converter, not a transformer; DC side removed from AC model")
    for b in buses: delete_bus(b)
    fix_station_voltages("st0022516", 320, None)

if BERWICK_DC:
    buses = ac_span_to_dc("way/1389754043", "line_other_kV", ac_bus=None,
                          dc_flags="reclassified_from_ac_manual;under_construction;unattached_end_offshore;voltage_design_envelope_max_525kV")
    for b in buses: delete_bus(b)

if HORNSEA_KV:
    lid = "way/635947176"
    move_line_layer(lid, "line_other_kV", f"line_{HORNSEA_KV}kV", new_kv=HORNSEA_KV,
                    extra_flag=f"voltage_corrected_manual_{HORNSEA_KV}kV_was_254kV")
    row = g.execute("SELECT bus0,bus1 FROM ac_line_all WHERE line_id=?", (lid,)).fetchone()
    g.execute("UPDATE ac_line_all SET voltage_kv=?, qa_flags=REPLACE(REPLACE(qa_flags,'nonstandard_voltage;',''),'line_type_proxy_220kV','voltage_corrected_manual_220kV_was_254kV') WHERE line_id=?", (HORNSEA_KV, lid))
    for b in (row["bus0"], row["bus1"]):
        st = g.execute("SELECT station_id FROM site_all WHERE bus_id=?", (b,)).fetchone()
        retag_bus(b, HORNSEA_KV)
        if st: fix_station_voltages(st["station_id"], 254, HORNSEA_KV)
    # unify component ids across the now-joined pieces and drop a stale isolation flag
    surv = g.execute("SELECT component FROM site_all WHERE bus_id='jn0015246_220kV'").fetchone()
    if surv is not None:
        comp = surv["component"]
        g.execute("UPDATE site_all SET component=? WHERE bus_id='jn0015295_220kV'", (comp,))
        g.execute("UPDATE ac_line_all SET component=? WHERE line_id=?", (comp, lid))
        t.execute(f'UPDATE "line_{HORNSEA_KV}kV" SET component=? WHERE line_id=?', (comp, lid))
        t.execute("UPDATE junction_node SET component=? WHERE bus_id='jn0015295_220kV'", (comp,))
        main = g.execute("SELECT component, COUNT(*) c FROM site_all GROUP BY component ORDER BY c DESC LIMIT 1").fetchone()["component"]
        if comp == main:
            for con, tb, key, val in [(g, "ac_line_all", "line_id", lid), (t, f"line_{HORNSEA_KV}kV", "line_id", lid)]:
                con.execute(f'UPDATE "{tb}" SET qa_flags=REPLACE(REPLACE(qa_flags,";not_in_main_component",""),"not_in_main_component","") WHERE "{key}"=?', (val,))
        log("hornsea.component_unified", component=comp, main_component=comp == main)

if ITALY_KV:
    for lid in ("way/429525108", "way/1176529836"):
        move_line_layer(lid, "line_500kV", f"line_{ITALY_KV}kV", new_kv=ITALY_KV,
                        extra_flag=f"voltage_corrected_manual_{ITALY_KV}kV_was_500kV")
        row = g.execute("SELECT bus0,bus1 FROM ac_line_all WHERE line_id=?", (lid,)).fetchone()
        g.execute("UPDATE ac_line_all SET voltage_kv=?, qa_flags=qa_flags||';voltage_corrected_manual_was_500kV' WHERE line_id=?", (ITALY_KV, lid))
        for b in (row["bus0"], row["bus1"]):
            if not g.execute("SELECT 1 FROM site_all WHERE bus_id=?", (b,)).fetchone(): continue  # already retagged via shared bus
            st = g.execute("SELECT station_id FROM site_all WHERE bus_id=?", (b,)).fetchone()
            retag_bus(b, ITALY_KV)
            if st: fix_station_voltages(st["station_id"], 500, ITALY_KV)
    # retag the two inferred transformers that used the fake 500 level
    for tid, st_, lo in [("st0018390_60_500", "st0018390", 60), ("st0029658_50_500", "st0029658", 50)]:
        if t.execute("SELECT 1 FROM transformer WHERE transformer_id=?", (tid,)).fetchone():
            t.execute("""UPDATE transformer SET transformer_id=?, bus1=?, voltage1_v=?, voltage1_kv=? WHERE transformer_id=?""",
                      (f"{st_}_{lo}_{ITALY_KV}", f"{st_}_{ITALY_KV}kV", ITALY_KV*1000, ITALY_KV, tid))
            log("transformer.retag", old=tid, new=f"{st_}_{lo}_{ITALY_KV}")
    bump_counts(t, "transformer")

# ---------- final invariants ----------
FAST = "fast" in sys.argv
def invariants():
    inv = {}
    inv["ac_spans"] = g.execute("SELECT COUNT(*) FROM ac_line_all").fetchone()[0]
    inv["buses"] = g.execute("SELECT COUNT(*) FROM site_all").fetchone()[0]
    inv["route_km"] = round(g.execute("SELECT SUM(length_conductor_m)/1000.0 FROM ac_line_all").fetchone()[0], 1)
    inv["dc_links"] = t.execute("SELECT COUNT(*) FROM dc_link").fetchone()[0]
    inv["dc_null_ends"] = t.execute("SELECT COUNT(*) FROM dc_link WHERE bus0 IS NULL OR bus1 IS NULL").fetchone()[0]
    inv["transformers"] = t.execute("SELECT COUNT(*) FROM transformer").fetchone()[0]
    inv["ge220_named_km"] = round(g.execute("SELECT SUM(length_conductor_m)/1000.0 FROM ac_line_all WHERE voltage_kv IN (220,225,236,275,300,330,380,400,420,500,750)").fetchone()[0], 1)
    # dangling refs / self-loops
    bus_ids = {r[0] for r in g.execute("SELECT bus_id FROM site_all")}
    dang = 0; sl = 0
    for a, b in g.execute("SELECT bus0,bus1 FROM ac_line_all"):
        if a == b: sl += 1
        if a not in bus_ids or b not in bus_ids: dang += 1
    inv["ac_self_loops"] = sl; inv["ac_dangling_refs"] = dang
    # components
    parent = {}
    def find(x):
        while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for b in bus_ids: parent[b] = b
    for tb, con in [("ac_line_all", g), ("transformer", t), ("dc_link", t)]:
        for a, b in con.execute(f"SELECT bus0,bus1 FROM {tb} WHERE bus0 IS NOT NULL AND bus1 IS NOT NULL AND bus0!=bus1"):
            if a in parent and b in parent:
                ra, rb = find(a), find(b)
                if ra != rb: parent[ra] = rb
        # noqa
    inv["components"] = len({find(x) for x in parent})
    return inv

if not FAST:
    inv = invariants()
    log("invariants", **inv)
else:
    log("invariants_skipped", fast=True)

if APPLY:
    t.commit(); g.commit()
    log("committed", apply=True)
else:
    t.rollback(); g.rollback()
    log("rolled_back", apply=False)
