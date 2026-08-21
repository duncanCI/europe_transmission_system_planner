#!/usr/bin/env python3
# patch_v22.py - frequency separation + PyPSA-defect fixes (v21 -> v22). Stdlib only.
# Usage: python3 patch_v22.py <dir> <scrape_csv> [apply] [fast] [--classify-only]
# Reviewed design: see methodology review (NO_GO items) - all required changes implemented.
import sqlite3, sys, os, json, struct, math, time, hashlib
from collections import defaultdict, Counter

DIR, SCRAPE = sys.argv[1], sys.argv[2]
APPLY = "apply" in sys.argv[3:]; FAST = "fast" in sys.argv[3:]
NOW = "2026-08-18T03:30:00Z"; T0 = time.time()
def log(action, **kw): print(json.dumps({"t": round(time.time()-T0,1), "action": action, **kw}, ensure_ascii=False), flush=True)

# ---------- gpkg helpers ----------
def _env(b):
    fl = b[3]; e = (fl >> 1) & 7
    return e, (fl >> 4) & 1, 8 + {0:0,1:32,2:48,3:48,4:64}[e]
def _walk(b, o, xs, ys):
    fmt = "<" if b[o] == 1 else ">"
    gt = struct.unpack_from(fmt+"I", b, o+1)[0]; base = gt % 1000
    dims = 2 + (1 if 1000<gt<2000 or 3000<gt<4000 else 0) + (1 if 2000<gt<3000 or 3000<gt<4000 else 0)
    o += 5
    if base == 1:
        c = struct.unpack_from(fmt+f"{dims}d", b, o); o += 8*dims; xs.append(c[0]); ys.append(c[1])
    elif base == 2:
        n = struct.unpack_from(fmt+"I", b, o)[0]; o += 4
        for _ in range(n):
            c = struct.unpack_from(fmt+f"{dims}d", b, o); o += 8*dims; xs.append(c[0]); ys.append(c[1])
    elif base == 3:
        n = struct.unpack_from(fmt+"I", b, o)[0]; o += 4
        for _ in range(n):
            m = struct.unpack_from(fmt+"I", b, o)[0]; o += 4
            for _ in range(m):
                c = struct.unpack_from(fmt+f"{dims}d", b, o); o += 8*dims; xs.append(c[0]); ys.append(c[1])
    elif base in (4,5,6,7):
        n = struct.unpack_from(fmt+"I", b, o)[0]; o += 4
        for _ in range(n): o, _ = _walk(b, o, xs, ys)
    return o, 0
def bounds_of(b):
    e, empty, off = _env(b)
    if empty: return None
    if e >= 1:
        return struct.unpack_from("<4d", b, 8)  # minx,maxx,miny,maxy
    xs, ys = [], []; _walk(b, off, xs, ys)
    return (min(xs), max(xs), min(ys), max(ys)) if xs else None
def coords_of(b):
    xs, ys = [], []; _walk(b, _env(b)[2], xs, ys); return list(zip(xs, ys))
def hav_m(cs):
    R = 6371008.8; L = 0.0
    for (x1,y1),(x2,y2) in zip(cs[:-1], cs[1:]):
        p1, p2 = math.radians(y1), math.radians(y2)
        a = math.sin((p2-p1)/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(math.radians(x2-x1)/2)**2
        L += 2*R*math.asin(math.sqrt(a))
    return L
def _st(i):
    return lambda b: None if b is None or bounds_of(b) is None else bounds_of(b)[i]
def reg(con):
    con.create_function("ST_IsEmpty", 1, lambda b: None if b is None else _env(b)[1])
    for i, nm in enumerate(("ST_MinX","ST_MaxX","ST_MinY","ST_MaxY")): con.create_function(nm, 1, _st(i))

t = sqlite3.connect(os.path.join(DIR, "europe_grid_topology.gpkg")); t.row_factory = sqlite3.Row; reg(t)
g = sqlite3.connect(os.path.join(DIR, "europe_grid_graph.gpkg")); g.row_factory = sqlite3.Row; reg(g)

# ---------- R5: idempotency guard ----------
if t.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='patch_history'").fetchone():
    if t.execute("SELECT 1 FROM patch_history WHERE version='v22'").fetchone():
        log("abort", reason="v22 already applied to this file pair"); sys.exit(3)
else:
    t.execute("CREATE TABLE patch_history (version TEXT PRIMARY KEY, applied_at TEXT, notes TEXT)")

def cols(con, tb): return [r[1] for r in con.execute(f'PRAGMA table_info("{tb}")')]
def bump(con, *tables):
    for tb in set(tables):
        n = con.execute(f'SELECT COUNT(*) FROM "{tb}"').fetchone()[0]
        con.execute("UPDATE gpkg_ogr_contents SET feature_count=? WHERE table_name=?", (n, tb))
        con.execute("UPDATE gpkg_contents SET last_change=? WHERE table_name=?", (NOW, tb))
# R6: never re-glob the traction layers into the 50 Hz layer lists
LINE_LAYERS = [r[0] for r in t.execute("SELECT table_name FROM gpkg_contents WHERE table_name LIKE 'line_%' AND table_name NOT LIKE '%internal%' AND table_name NOT LIKE '%16_7Hz%'")]
SITE_LAYERS = [r[0] for r in t.execute("SELECT table_name FROM gpkg_contents WHERE (table_name LIKE 'site_%' OR table_name='junction_node') AND table_name NOT LIKE '%16_7Hz%'")]
def line_layer_of(kv):
    return f"line_{kv}kV" if f"line_{kv}kV" in LINE_LAYERS else "line_other_kV"

for sql in ["CREATE INDEX IF NOT EXISTS idx_ac_osm ON ac_line_all(osm_id)",
            "CREATE INDEX IF NOT EXISTS idx_ac_lid ON ac_line_all(line_id)",
            "CREATE INDEX IF NOT EXISTS idx_ac_b0 ON ac_line_all(bus0)",
            "CREATE INDEX IF NOT EXISTS idx_ac_b1 ON ac_line_all(bus1)",
            "CREATE INDEX IF NOT EXISTS idx_sa_bid ON site_all(bus_id)"]:
    g.execute(sql)
for lay in LINE_LAYERS: t.execute(f'CREATE INDEX IF NOT EXISTS "idx_{lay}_lid" ON "{lay}"(line_id)')
for lay in SITE_LAYERS:
    if "bus_id" in cols(t, lay): t.execute(f'CREATE INDEX IF NOT EXISTS "idx_{lay}_bid" ON "{lay}"(bus_id)')
t.execute("CREATE INDEX IF NOT EXISTS idx_tr_b0 ON transformer(bus0)")
t.execute("CREATE INDEX IF NOT EXISTS idx_tr_b1 ON transformer(bus1)")
log("indexes.ready")

def clone_layer(con, src, dst):
    if con.execute("SELECT 1 FROM gpkg_contents WHERE table_name=?", (dst,)).fetchone(): return
    ddl = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (src,)).fetchone()[0]
    con.execute(ddl.replace(f'"{src}"', f'"{dst}"', 1) if f'"{src}"' in ddl else ddl.replace(src, dst, 1))
    gc = con.execute("SELECT * FROM gpkg_contents WHERE table_name=?", (src,)).fetchone()
    con.execute("INSERT INTO gpkg_contents (table_name,data_type,identifier,description,last_change,min_x,min_y,max_x,max_y,srs_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (dst, gc["data_type"], dst, gc["description"], NOW, gc["min_x"], gc["min_y"], gc["max_x"], gc["max_y"], gc["srs_id"]))
    gg = con.execute("SELECT * FROM gpkg_geometry_columns WHERE table_name=?", (src,)).fetchone()
    con.execute("INSERT INTO gpkg_geometry_columns VALUES (?,?,?,?,?,?)", (dst, gg[1], gg[2], gg[3], gg[4], gg[5]))
    con.execute("INSERT INTO gpkg_ogr_contents (table_name, feature_count) VALUES (?,0)", (dst,))
    con.execute(f'CREATE VIRTUAL TABLE "rtree_{dst}_geom" USING rtree(id, minx, maxx, miny, maxy)')
    for (tsql,) in con.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name LIKE ?", (f"rtree_{src}_geom%",)).fetchall():
        con.execute(tsql.replace(f"rtree_{src}_geom", f"rtree_{dst}_geom").replace(f'"{src}"', f'"{dst}"'))
    con.execute(f'CREATE INDEX IF NOT EXISTS "idx_{dst}_lid" ON "{dst}"(line_id)')
    log("layer.cloned", src=src, dst=dst)

# ---------- R14: repoint v21's dangling topology bus refs ----------
V21_REPOINT = {"jn0015246_254kV": "jn0015246_220kV", "jn0015295_254kV": "jn0015295_220kV",
               "st0018390_500kV": "st0018390_132kV", "st0029658_500kV": "st0029658_132kV",
               "st0027981_500kV": "st0027981_132kV", "jn0018695_500kV": "jn0018695_132kV"}
fixed14 = 0
for lay in LINE_LAYERS:
    lc = cols(t, lay)
    if "bus0" not in lc: continue
    for old, new in V21_REPOINT.items():
        cur = t.execute(f'SELECT COUNT(*) FROM "{lay}" WHERE bus0=? OR bus1=?', (old, old)).fetchone()[0]
        if cur:
            t.execute(f'UPDATE "{lay}" SET bus0=CASE WHEN bus0=? THEN ? ELSE bus0 END, bus1=CASE WHEN bus1=? THEN ? ELSE bus1 END WHERE bus0=? OR bus1=?',
                      (old, new, old, new, old, old))
            fixed14 += cur
log("v21_danglers.repointed", rows=fixed14)

# ---------- scrape classification ----------
OSM_167, OSM_0, OSM_MIXED, OSM_50, OSM_JUNK = set(), set(), set(), set(), {}
TRACTION_OPS = ("db energie","öbb","oebb","obb infrastruktur","sbb","cff","ffs","trafikverket","banverket","bane nor","jernbaneverket","bane energi","rhb","rhätische")
def is167(f): f = f.replace(",", "."); return any(s in f for s in ("16.7","16.67","16.6"))
n_rows = 0
with open(SCRAPE, encoding="utf-8") as fh:
    for ln in fh:
        p = ln.rstrip("\n").split("|")
        if len(p) < 5 or p[0] not in ("way", "relation"): continue
        key = f"{p[0]}/{p[1]}"; f = p[2].strip(); n_rows += 1
        if f and is167(f):
            (OSM_MIXED if "50" in f else OSM_167).add(key)
        elif f == "0": OSM_0.add(key)
        elif f == "50": OSM_50.add(key)
        elif f: OSM_JUNK[key] = f
log("scrape.loaded", rows=n_rows, tag_16_7=len(OSM_167), tag_mixed=len(OSM_MIXED), tag_0=len(OSM_0),
    tag_50_explicit=len(OSM_50), tag_junk=len(OSM_JUNK))

def base_id(lid):
    for sep in (":", "-"):
        q = lid.rsplit(sep, 1)
        if len(q) == 2 and q[1].isdigit(): return q[0]
    return lid
span_class = {}; mixed_kept = []; tag50_spans = []; junk_spans = []; op_joint = []; ehv_conflicts = []; geo_flag = []
TR_CC = ("DE", "AT", "CH", "SE", "NO")
SHORT_OPS = {"sbb", "cff", "ffs", "rhb", "öbb", "oebb"}  # short tokens matched exactly, never as substrings
def tok_is_traction_g(tk):
    for op in TRACTION_OPS:
        if op in SHORT_OPS:
            if tk == op or tk.startswith(op + " ") or tk.startswith(op + "-"): return True
        elif op in tk: return True
    return False
def all_traction_str(oper):
    toks = [tk.strip().lower() for tk in oper.replace("/", ";").replace(",", ";").split(";") if tk.strip()]
    return bool(toks) and all(tok_is_traction_g(tk) for tk in toks)
def set167(lid, kv, src):
    if kv <= 132: span_class[lid] = (16.7, src)
    else: ehv_conflicts.append(lid)
for r in g.execute("SELECT line_id, osm_id, contains, operator, voltage_kv, countries FROM ac_line_all"):
    keys = {r["osm_id"], base_id(r["line_id"])} | set((r["contains"] or "").split(";")); keys.discard("")
    oper = (r["operator"] or "").lower(); is_top = any(op in oper for op in TRACTION_OPS)
    in_tr_cc = any(c in TR_CC for c in (r["countries"] or "").split(";"))
    if keys & OSM_167:
        set167(r["line_id"], r["voltage_kv"], "osm_frequency_tag")
        # tag is primary evidence and wins, but a 16.7 Hz tag outside the five traction
        # geographies is anomalous - keep it, flag it (review delta, non-blocking 2)
        if r["line_id"] in span_class and not in_tr_cc:
            geo_flag.append(r["line_id"])
    elif keys & OSM_MIXED:
        # explicit 50;16.7 tag = shared-tower corridor carrying BOTH systems.
        # Uniform conservative treatment (review delta, blocking 1): the span stays
        # wholly 50 Hz and flagged - moving it would delete its 50 Hz circuits.
        mixed_kept.append(r["line_id"])
    elif keys & OSM_0: span_class[r["line_id"]] = (0.0, "osm_frequency_tag_dc")
    elif keys & OSM_50: tag50_spans.append(r["line_id"])
    elif keys & set(OSM_JUNK): junk_spans.append(r["line_id"])
    elif is_top:
        toks = [tk.strip().lower() for tk in (r["operator"] or "").replace("/", ";").replace(",", ";").split(";") if tk.strip()]
        def tok_is_traction(tk):
            for op in TRACTION_OPS:
                if op in SHORT_OPS:
                    if tk == op or tk.startswith(op + " ") or tk.startswith(op + "-"): return True
                elif op in tk: return True
            return False
        all_traction = bool(toks) and all(tok_is_traction(tk) for tk in toks)
        if r["voltage_kv"] <= 132 and in_tr_cc and all_traction:
            set167(r["line_id"], r["voltage_kv"], "operator_inferred")
        else:
            op_joint.append(r["line_id"])
tr_ids = [k for k, v in span_class.items() if v[0] == 16.7]
dc_ids = [k for k, v in span_class.items() if v[0] == 0.0]
log("classify", traction_spans=len(tr_ids), dc_tagged_in_ac=len(dc_ids), mixed_kept_50=len(mixed_kept),
    tag50_explicit_spans=len(tag50_spans), junk_tag_spans=len(junk_spans), operator_joint_kept_50=len(op_joint),
    ehv_tag_conflicts_kept_50=len(ehv_conflicts), by_source=dict(Counter(v[1] for v in span_class.values())))
for i in dc_ids:
    r = g.execute("SELECT voltage_kv, length_conductor_m, line_label, countries, construction_type FROM ac_line_all WHERE line_id=?", (i,)).fetchone()
    log("dc_in_ac_candidate", line_id=i, kv=r["voltage_kv"], km=round(r["length_conductor_m"]/1000,1), label=r["line_label"], cc=r["countries"], ct=r["construction_type"])
if "--classify-only" in sys.argv:
    sys.exit(0)
FLAGSQL = "COALESCE(qa_flags,'')||CASE WHEN COALESCE(qa_flags,'')='' THEN '' ELSE ';' END"
for lst, flag in [(ehv_conflicts, "frequency_tag_conflict_ehv"), (junk_spans, "nonstandard_frequency_tag_kept_50"),
                  (geo_flag, "traction_tag_outside_expected_geography")]:
    g.executemany(f"UPDATE ac_line_all SET qa_flags={FLAGSQL}||'{flag}' WHERE line_id=?", [(l,) for l in lst])

# ---------- F6 scope prune ----------
def inbox(x, y): return -12 <= x <= 45 and 34 <= y <= 72
out_spans = [r["line_id"] for r in g.execute("SELECT line_id,start_lon,start_lat,end_lon,end_lat FROM ac_line_all")
             if not (inbox(r["start_lon"], r["start_lat"]) and inbox(r["end_lon"], r["end_lat"]))]
out_buses = [r["bus_id"] for r in g.execute("SELECT bus_id, geom FROM site_all")
             if (lambda bb: bb and not inbox(bb[0], bb[2]))(bounds_of(bytes(r["geom"])))]
qs = lambda ids: ",".join("?"*len(ids))
if out_spans:
    kv_of = dict(g.execute(f"SELECT line_id, voltage_kv FROM ac_line_all WHERE line_id IN ({qs(out_spans)})", out_spans))
    g.execute(f"DELETE FROM ac_line_all WHERE line_id IN ({qs(out_spans)})", out_spans)
    per_layer = defaultdict(list)
    for lid, kv in kv_of.items(): per_layer[line_layer_of(kv)].append(lid)
    for lay, ids in per_layer.items():
        t.execute(f'DELETE FROM "{lay}" WHERE line_id IN ({qs(ids)})', ids); bump(t, lay)
if out_buses:
    # safety: no surviving edge may reference a bus we are about to delete
    surv = g.execute(f"SELECT COUNT(*) FROM ac_line_all WHERE bus0 IN ({qs(out_buses)}) OR bus1 IN ({qs(out_buses)})", out_buses+out_buses).fetchone()[0]
    if surv: log("abort", reason=f"{surv} surviving spans reference out-of-box buses"); sys.exit(2)
    g.execute(f"DELETE FROM site_all WHERE bus_id IN ({qs(out_buses)})", out_buses)
    for lay in SITE_LAYERS:
        if "bus_id" in cols(t, lay):
            t.execute(f'DELETE FROM "{lay}" WHERE bus_id IN ({qs(out_buses)})', out_buses); bump(t, lay)
    t.execute(f"DELETE FROM transformer WHERE bus0 IN ({qs(out_buses)}) OR bus1 IN ({qs(out_buses)})", out_buses+out_buses)
for lay in ("substation_footprint", "station_cluster", "line_internal_to_station"):
    dead = [r[0] for r in t.execute(f'SELECT fid, geom FROM "{lay}"') if (lambda bb: bb and not inbox(bb[0], bb[2]))(bounds_of(bytes(r[1])))]
    if dead:
        t.executemany(f'DELETE FROM "{lay}" WHERE fid=?', [(d,) for d in dead]); bump(t, lay)
        log("scope.layer_pruned", layer=lay, removed=len(dead))
dcdead = [r[0] for r in t.execute("SELECT fid, geom FROM dc_link") if (lambda bb: bb and not inbox(bb[0], bb[2]))(bounds_of(bytes(r[1])))]
if dcdead:
    t.executemany("DELETE FROM dc_link WHERE fid=?", [(d,) for d in dcdead]); log("scope.dc_pruned", removed=len(dcdead))
bump(g, "ac_line_all", "site_all"); bump(t, "transformer", "dc_link")
log("scope.pruned", spans=len(out_spans), buses=len(out_buses))

# ---------- F2: collapse duplicate circuit rows (reviewer's exact fix) ----------
groups = list(g.execute("""SELECT osm_id, bus0, bus1, COUNT(*) c, MAX(n_circuits) n, MIN(n_circuits) nmin
FROM ac_line_all GROUP BY osm_id, bus0, bus1 HAVING COUNT(*)>1"""))
collapsed = ambiguous = 0
for gr in groups:
    where = (gr["osm_id"], gr["bus0"], gr["bus1"])
    rows = list(g.execute("SELECT line_id, geom, s_nom_mva FROM ac_line_all WHERE osm_id=? AND bus0=? AND bus1=? ORDER BY line_id", where))
    geoms = {hashlib.md5(bytes(r["geom"])).hexdigest() for r in rows}
    if len(geoms) == 1 and gr["n"] == gr["nmin"]:
        # identical duplicates: one row already carries the full element (r=r_type*L/n, s_nom=sqrt3*V*I*n)
        keep = rows[0]["line_id"]; drop = [r["line_id"] for r in rows[1:]]
        g.execute(f"DELETE FROM ac_line_all WHERE line_id IN ({qs(drop)})", drop)
        g.execute(f"UPDATE ac_line_all SET qa_flags={FLAGSQL}||'duplicate_circuit_rows_collapsed_{gr['c']}to1' WHERE line_id=?", (keep,))
        kv = g.execute("SELECT voltage_kv FROM ac_line_all WHERE line_id=?", (keep,)).fetchone()[0]
        lay = line_layer_of(kv)
        t.execute(f'DELETE FROM "{lay}" WHERE line_id IN ({qs(drop)})', drop)
        collapsed += len(drop)
    else:
        g.execute(f"UPDATE ac_line_all SET qa_flags={FLAGSQL}||'circuit_count_element_level_ambiguous' WHERE osm_id=? AND bus0=? AND bus1=?", where)
        ambiguous += gr["c"]
bump(g, "ac_line_all")
for lay in LINE_LAYERS: bump(t, lay)
log("circuits.collapsed", rows_removed=collapsed, rows_flagged_ambiguous=ambiguous, groups=len(groups))

# ---------- F3: length recompute (no floor - R11) ----------
relen = conflicts = 0
mis = []
for r in g.execute("SELECT line_id, voltage_kv, length_conductor_m, connector0_m, connector1_m, geom FROM ac_line_all"):
    exp = r["length_conductor_m"] + (r["connector0_m"] or 0) + (r["connector1_m"] or 0)
    if exp <= 200: continue
    gl = hav_m(coords_of(bytes(r["geom"])))
    if abs(gl - exp) / exp > 0.10:
        mis.append((r["line_id"], r["voltage_kv"], r["length_conductor_m"], gl, (r["connector0_m"] or 0) + (r["connector1_m"] or 0)))
for lid, kv, oldlen, gl, conn in mis:
    newlen = gl - conn
    if newlen < max(0.05 * gl, 5.0):
        g.execute(f"UPDATE ac_line_all SET qa_flags={FLAGSQL}||'length_geometry_conflict_unresolved' WHERE line_id=?", (lid,))
        conflicts += 1; continue
    ratio = newlen / oldlen
    g.execute(f"UPDATE ac_line_all SET length_conductor_m=?, r_ohm=r_ohm*?, x_ohm=x_ohm*?, qa_flags={FLAGSQL}||'length_recomputed_from_geometry' WHERE line_id=?",
              (round(newlen,1), ratio, ratio, lid))
    lay = line_layer_of(kv)
    if "length_conductor_m" in cols(t, lay):
        t.execute(f'UPDATE "{lay}" SET length_conductor_m=?, r_ohm=r_ohm*?, x_ohm=x_ohm*? WHERE line_id=?', (round(newlen,1), ratio, ratio, lid))
    relen += 1
log("lengths.recomputed", spans=relen, conflicts_flagged=conflicts)

# ---------- F1: frequency columns (R9/R10 honest labels) ----------
for con, tbs in [(g, ["ac_line_all", "site_all"]), (t, LINE_LAYERS + SITE_LAYERS + ["transformer", "dc_link"])]:
    for tb in tbs:
        if "frequency_hz" not in cols(con, tb):
            con.execute(f'ALTER TABLE "{tb}" ADD COLUMN frequency_hz REAL')
            con.execute(f'ALTER TABLE "{tb}" ADD COLUMN frequency_source TEXT')
if "severed_from" not in cols(g, "site_all"):
    g.execute("ALTER TABLE site_all ADD COLUMN severed_from TEXT")
g.execute("UPDATE ac_line_all SET frequency_hz=50.0, frequency_source='no_nonstandard_frequency_tag_in_scrape'")
g.executemany("UPDATE ac_line_all SET frequency_source='osm_frequency_tag_50' WHERE line_id=?", [(l,) for l in tag50_spans])
g.executemany("UPDATE ac_line_all SET frequency_source='osm_mixed_50_16.7_kept_50' WHERE line_id=?", [(l,) for l in mixed_kept])
g.executemany("UPDATE ac_line_all SET frequency_source='nonstandard_frequency_tag_kept_50' WHERE line_id=?", [(l,) for l in junk_spans])
g.executemany("UPDATE ac_line_all SET frequency_source='operator_railway_joint_kept_50' WHERE line_id=?", [(l,) for l in op_joint])
# review delta blocking 2: an overridden tag must never claim there was no tag
g.executemany("UPDATE ac_line_all SET frequency_source='osm_frequency_tag_16_7_overridden_ehv_gate' WHERE line_id=?", [(l,) for l in ehv_conflicts])
# review obligation 3: pure 16.7 tag + joint operator list = shared-tower possibility made visible
joint_tag = [k for k, v in span_class.items() if v[0] == 16.7 and v[1] == "osm_frequency_tag"
             and (lambda o: ";" in o or "," in o or "/" in o)((g.execute("SELECT COALESCE(operator,'') FROM ac_line_all WHERE line_id=?", (k,)).fetchone() or [""])[0])
             and not all_traction_str((g.execute("SELECT COALESCE(operator,'') FROM ac_line_all WHERE line_id=?", (k,)).fetchone() or [""])[0])]
g.executemany(f"UPDATE ac_line_all SET qa_flags={FLAGSQL}||'joint_operator_traction_tag' WHERE line_id=?", [(l,) for l in joint_tag])
log("frequency.joint_tag_flagged", spans=len(joint_tag))
g.executemany("UPDATE ac_line_all SET frequency_hz=16.7, frequency_source=? WHERE line_id=?",
              [(v[1], k) for k, v in span_class.items() if v[0] == 16.7 and g.execute("SELECT 1 FROM ac_line_all WHERE line_id=?", (k,)).fetchone()])
# R10: DC-tagged rows in the AC layer keep their true tag and a review flag; they are NOT auto-moved
dc_live = [l for l in dc_ids if g.execute("SELECT 1 FROM ac_line_all WHERE line_id=?", (l,)).fetchone()]
g.executemany(f"UPDATE ac_line_all SET frequency_hz=0.0, frequency_source='osm_frequency_tag_dc', qa_flags={FLAGSQL}||'dc_tagged_in_ac_layer' WHERE line_id=?", [(l,) for l in dc_live])
t.execute("UPDATE dc_link SET frequency_hz=0.0, frequency_source='dc_link_layer'")
log("frequency.columns_set", dc_flagged_in_ac=len(dc_live))

# ---------- F1: sever mixed buses ----------
bus_tr = defaultdict(list); bus_other = Counter()
for r in g.execute("SELECT line_id, bus0, bus1, frequency_hz FROM ac_line_all"):
    for b in (r["bus0"], r["bus1"]):
        if r["frequency_hz"] == 16.7: bus_tr[b].append(r["line_id"])
        else: bus_other[b] += 1
mixed_buses = [b for b in bus_tr if bus_other[b] > 0]
severed = 0
sc_g = cols(g, "site_all")
for b in sorted(mixed_buses):
    nb = b + "_16_7Hz"
    row = g.execute("SELECT * FROM site_all WHERE bus_id=?", (b,)).fetchone()
    if row is None: continue
    vals = {c: row[c] for c in sc_g}; vals["fid"] = None; vals["bus_id"] = nb
    vals["connected_line_ids"] = ";".join(sorted(bus_tr[b]))
    vals["frequency_hz"] = 16.7; vals["frequency_source"] = "severed_traction"; vals["severed_from"] = b
    g.execute(f'INSERT INTO site_all ({",".join(chr(34)+c+chr(34) for c in vals)}) VALUES ({",".join("?"*len(vals))})', list(vals.values()))
    g.executemany("UPDATE ac_line_all SET bus0=CASE WHEN bus0=? THEN ? ELSE bus0 END, bus1=CASE WHEN bus1=? THEN ? ELSE bus1 END WHERE line_id=?",
                  [(b, nb, b, nb, lid) for lid in bus_tr[b]])
    for lay in SITE_LAYERS:
        lc = cols(t, lay)
        if "bus_id" not in lc: continue
        rr = t.execute(f'SELECT * FROM "{lay}" WHERE bus_id=?', (b,)).fetchone()
        if rr is None: continue
        v2 = {c: rr[c] for c in lc}; v2["fid"] = None; v2["bus_id"] = nb
        v2["frequency_hz"] = 16.7; v2["frequency_source"] = "severed_traction"
        t.execute(f'INSERT INTO "{lay}" ({",".join(chr(34)+c+chr(34) for c in v2)}) VALUES ({",".join("?"*len(v2))})', list(v2.values()))
    severed += 1
for lay in SITE_LAYERS: bump(t, lay)
bump(g, "site_all")
pure = [b for b in bus_tr if bus_other[b] == 0]
g.executemany("UPDATE site_all SET frequency_hz=16.7, frequency_source='incident_spans' WHERE bus_id=? AND frequency_hz IS NULL", [(b,) for b in pure])
for lay in SITE_LAYERS:
    if "bus_id" in cols(t, lay):
        t.executemany(f'UPDATE "{lay}" SET frequency_hz=16.7, frequency_source=? WHERE bus_id=? AND frequency_hz IS NULL', [("incident_spans", b) for b in pure])
g.execute("UPDATE site_all SET frequency_hz=50.0, frequency_source=COALESCE(frequency_source,'default_50') WHERE frequency_hz IS NULL")
for lay in SITE_LAYERS + ["junction_node"] if "junction_node" not in SITE_LAYERS else SITE_LAYERS:
    if "frequency_hz" in cols(t, lay):
        t.execute(f'UPDATE "{lay}" SET frequency_hz=50.0, frequency_source=COALESCE(frequency_source,"default_50") WHERE frequency_hz IS NULL')
log("frequency.severed", mixed_buses=severed, pure_traction_buses=len(pure))

# ---------- R4: transformers/dc_links must not bridge frequencies ----------
bus_hz = dict(g.execute("SELECT bus_id, frequency_hz FROM site_all"))
weld_tr = [r for r in t.execute("SELECT transformer_id, bus0, bus1, inferred FROM transformer")
           if bus_hz.get(r["bus0"], 50.0) != bus_hz.get(r["bus1"], 50.0)]
deleted_tr = 0
for r in weld_tr:
    if (r["inferred"] or "") != "":
        t.execute("DELETE FROM transformer WHERE transformer_id=?", (r["transformer_id"],))
        deleted_tr += 1
        log("transformer.deleted_frequency_weld", transformer_id=r["transformer_id"], inferred=r["inferred"])
    else:
        log("transformer.frequency_conflict_manual_review", transformer_id=r["transformer_id"])
t.execute("UPDATE transformer SET frequency_hz=50.0, frequency_source='both_buses_50hz'")
tr167 = [r["transformer_id"] for r in t.execute("SELECT transformer_id, bus0, bus1 FROM transformer")
         if bus_hz.get(r["bus0"]) == 16.7 and bus_hz.get(r["bus1"]) == 16.7]
t.executemany("UPDATE transformer SET frequency_hz=16.7, frequency_source='both_buses_16_7hz' WHERE transformer_id=?", [(x,) for x in tr167])
weld_dc = [r["fid"] for r in t.execute("SELECT fid, bus0, bus1 FROM dc_link WHERE bus0 IS NOT NULL AND bus1 IS NOT NULL")
           if bus_hz.get(r["bus0"], 50.0) != bus_hz.get(r["bus1"], 50.0)]
for f in weld_dc: log("dc_link.frequency_conflict_manual_review", fid=f)
bump(t, "transformer")
log("frequency.welds_removed", transformers_deleted=deleted_tr, transformer_conflicts_kept=len(weld_tr)-deleted_tr, dc_conflicts=len(weld_dc))

# ---------- F1: traction layers ----------
moved = Counter()
tr_rows = list(g.execute("SELECT line_id, voltage_kv, bus0, bus1, frequency_source, qa_flags, component FROM ac_line_all WHERE frequency_hz=16.7"))
for r in tr_rows:
    src = line_layer_of(r["voltage_kv"]); dst = f"line_{r['voltage_kv']}kV_16_7Hz"
    clone_layer(t, dst if False else src, dst)
    sc = [c for c in cols(t, src) if c != "fid"]
    row = t.execute(f'SELECT {",".join(chr(34)+c+chr(34) for c in sc)} FROM "{src}" WHERE line_id=?', (r["line_id"],)).fetchone()
    if row is None: continue
    vals = dict(zip(sc, row))
    vals["frequency_hz"] = 16.7; vals["frequency_source"] = r["frequency_source"]
    vals["bus0"], vals["bus1"] = r["bus0"], r["bus1"]
    t.execute(f'INSERT INTO "{dst}" ({",".join(chr(34)+c+chr(34) for c in vals)}) VALUES ({",".join("?"*len(vals))})', list(vals.values()))
    t.execute(f'DELETE FROM "{src}" WHERE line_id=?', (r["line_id"],))
    moved[dst] += 1
for dst in moved: bump(t, dst)
for src in {line_layer_of(r["voltage_kv"]) for r in tr_rows}: bump(t, src)
log("frequency.layers", moved=dict(moved))

# ---------- components: R7 deterministic, R8 AC+transformer only ----------
if "component_incl_dc" not in cols(g, "site_all"):
    g.execute("ALTER TABLE site_all ADD COLUMN component_incl_dc INTEGER")
def components(edge_tables):
    parent = {}
    def find(x):
        while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for (b,) in g.execute("SELECT bus_id FROM site_all"): parent[b] = b
    for tb, con in edge_tables:
        for a, b in con.execute(f"SELECT bus0,bus1 FROM {tb} WHERE bus0 IS NOT NULL AND bus1 IS NOT NULL AND bus0!=bus1"):
            if a in parent and b in parent:
                ra, rb = find(a), find(b)
                if ra != rb: parent[ra] = rb
    km = defaultdict(float)
    for b0, L in g.execute("SELECT bus0, length_conductor_m FROM ac_line_all"):
        km[find(b0)] += L
    order = sorted({find(x) for x in parent}, key=lambda c: (-km.get(c, 0.0), c))
    cid = {c: i for i, c in enumerate(order)}
    return {b: cid[find(b)] for b in parent}, len(order)
comp, n_comp = components([("ac_line_all", g), ("transformer", t)])
comp_dc, n_comp_dc = components([("ac_line_all", g), ("transformer", t), ("dc_link", t)])
g.executemany("UPDATE site_all SET component=?, component_incl_dc=? WHERE bus_id=?", [(comp[b], comp_dc[b], b) for b in comp])
g.executemany("UPDATE ac_line_all SET component=? WHERE line_id=?",
              [(comp[r[1]], r[0]) for r in g.execute("SELECT line_id, bus0 FROM ac_line_all")])
g.execute("UPDATE ac_line_all SET qa_flags=REPLACE(REPLACE(COALESCE(qa_flags,''),';not_in_main_component',''),'not_in_main_component','')")
g.execute(f"UPDATE ac_line_all SET qa_flags={FLAGSQL}||'not_in_main_component' WHERE component!=0")
log("components.recomputed", components_ac_tr=n_comp, components_incl_dc=n_comp_dc)

# ---------- R12/R13: global bookkeeping recompute + propagation ----------
n_lines = Counter(); nbrs = defaultdict(set); conn_ids = defaultdict(list)
for lid, a, b in g.execute("SELECT line_id, bus0, bus1 FROM ac_line_all"):
    n_lines[a] += 1; n_lines[b] += 1
    nbrs[a].add(b); nbrs[b].add(a)
    conn_ids[a].append(lid); conn_ids[b].append(lid)
for tb in ("transformer", "dc_link"):
    for a, b in t.execute(f"SELECT bus0, bus1 FROM {tb} WHERE bus0 IS NOT NULL AND bus1 IS NOT NULL"):
        if a != b: nbrs[a].add(b); nbrs[b].add(a)
g.executemany("UPDATE site_all SET degree=?, n_lines=?, connected_line_ids=? WHERE bus_id=?",
              [(len(nbrs.get(b, ())), n_lines.get(b, 0), ";".join(sorted(conn_ids.get(b, []))), b)
               for (b,) in g.execute("SELECT bus_id FROM site_all")])
# propagate to topology gpkg
graph_line = {r["line_id"]: r for r in g.execute("SELECT line_id, component, qa_flags, frequency_hz, frequency_source FROM ac_line_all")}
ALL_LINE_LAYERS = LINE_LAYERS + [r[0] for r in t.execute("SELECT table_name FROM gpkg_contents WHERE table_name LIKE 'line_%16_7Hz'")]
for lay in ALL_LINE_LAYERS:
    lc = cols(t, lay)
    if "line_id" not in lc: continue
    ups = []
    for (lid,) in t.execute(f'SELECT line_id FROM "{lay}"'):
        gr = graph_line.get(lid)
        if gr: ups.append((gr["component"], gr["qa_flags"], gr["frequency_hz"], gr["frequency_source"], lid))
    if ups:
        t.executemany(f'UPDATE "{lay}" SET component=?, qa_flags=?, frequency_hz=?, frequency_source=? WHERE line_id=?', ups)
graph_bus = {r["bus_id"]: r for r in g.execute("SELECT bus_id, component, degree, n_lines, connected_line_ids, frequency_hz, frequency_source FROM site_all")}
ALL_SITE_LAYERS = SITE_LAYERS + [r[0] for r in t.execute("SELECT table_name FROM gpkg_contents WHERE table_name LIKE 'site_%16_7Hz'")]
for lay in ALL_SITE_LAYERS:
    lc = cols(t, lay)
    if "bus_id" not in lc: continue
    ups = []
    for (bid,) in t.execute(f'SELECT bus_id FROM "{lay}"'):
        gb = graph_bus.get(bid)
        if gb:
            ups.append((gb["component"], gb["degree"], gb["n_lines"], gb["connected_line_ids"], gb["frequency_hz"], gb["frequency_source"], bid))
    if ups:
        sets = 'component=?, degree=?, n_lines=?, connected_line_ids=?, frequency_hz=?, frequency_source=?'
        t.executemany(f'UPDATE "{lay}" SET {sets} WHERE bus_id=?', ups)
if "component" not in cols(t, "dc_link"): t.execute("ALTER TABLE dc_link ADD COLUMN component INTEGER")
t.executemany("UPDATE dc_link SET component=? WHERE fid=?",
              [(graph_bus[r["bus0"]]["component"] if r["bus0"] in graph_bus else None, r["fid"])
               for r in t.execute("SELECT fid, bus0 FROM dc_link")])
tr_ups = [(graph_bus[r["bus0"]]["component"] if r["bus0"] in graph_bus else None, r["transformer_id"])
          for r in t.execute("SELECT transformer_id, bus0 FROM transformer")]
t.executemany("UPDATE transformer SET component=? WHERE transformer_id=?", tr_ups) if "component" in cols(t, "transformer") else \
    (t.execute("ALTER TABLE transformer ADD COLUMN component INTEGER"), t.executemany("UPDATE transformer SET component=? WHERE transformer_id=?", tr_ups))
log("bookkeeping.propagated")

# ---------- R15: recompute gpkg_contents extents from rtrees ----------
for con in (t, g):
    for (tb,) in con.execute("SELECT table_name FROM gpkg_contents"):
        try:
            mm = con.execute(f'SELECT MIN(minx), MIN(miny), MAX(maxx), MAX(maxy) FROM "rtree_{tb}_geom"').fetchone()
            if mm and mm[0] is not None:
                con.execute("UPDATE gpkg_contents SET min_x=?, min_y=?, max_x=?, max_y=?, last_change=? WHERE table_name=?",
                            (mm[0], mm[1], mm[2], mm[3], NOW, tb))
        except sqlite3.OperationalError:
            pass
log("extents.recomputed")

# ---------- invariants (fail-closed) ----------
violations = []
bus_ids = {r[0] for r in g.execute("SELECT bus_id FROM site_all")}
dang = sum(1 for a, b in g.execute("SELECT bus0,bus1 FROM ac_line_all") if a not in bus_ids or b not in bus_ids)
if dang: violations.append(f"graph dangling refs: {dang}")
for lay in ALL_LINE_LAYERS:
    if "bus0" not in cols(t, lay): continue
    d = sum(1 for a, b in t.execute(f'SELECT bus0,bus1 FROM "{lay}"') if a not in bus_ids or b not in bus_ids)
    if d: violations.append(f"{lay} dangling refs: {d}")
for tb in ("transformer", "dc_link"):
    d = sum(1 for a, b in t.execute(f"SELECT bus0,bus1 FROM {tb}") for x in [0] if (a is not None and a not in bus_ids) or (b is not None and b not in bus_ids))
    if d: violations.append(f"{tb} dangling refs: {d}")
bus_hz = dict(g.execute("SELECT bus_id, frequency_hz FROM site_all"))
mixed = set()
for tb, con in [("ac_line_all", g), ("transformer", t)]:
    for a, b in con.execute(f"SELECT bus0,bus1 FROM {tb} WHERE bus0 IS NOT NULL AND bus1 IS NOT NULL"):
        if bus_hz.get(a) != bus_hz.get(b): mixed.add((a, b))
if mixed: violations.append(f"frequency-bridging passive branches: {len(mixed)}")
n_mismatch = 0
for lay in ALL_LINE_LAYERS:
    if "component" not in cols(t, lay): continue
    for lid, c in t.execute(f'SELECT line_id, component FROM "{lay}"'):
        gr = graph_line.get(lid)
        if gr and gr["component"] != c: n_mismatch += 1
if n_mismatch: violations.append(f"cross-gpkg component mismatches: {n_mismatch}")
inv = {"violations": violations}
if not FAST:
    inv["ac_spans"] = g.execute("SELECT COUNT(*) FROM ac_line_all").fetchone()[0]
    inv["buses"] = g.execute("SELECT COUNT(*) FROM site_all").fetchone()[0]
    inv["route_km"] = round(g.execute("SELECT SUM(length_conductor_m)/1000.0 FROM ac_line_all").fetchone()[0], 1)
    inv["route_km_50hz"] = round(g.execute("SELECT SUM(length_conductor_m)/1000.0 FROM ac_line_all WHERE frequency_hz=50").fetchone()[0], 1)
    inv["route_km_16_7hz"] = round(g.execute("SELECT COALESCE(SUM(length_conductor_m),0)/1000.0 FROM ac_line_all WHERE frequency_hz=16.7").fetchone()[0], 1)
    inv["route_km_dc_flagged"] = round(g.execute("SELECT COALESCE(SUM(length_conductor_m),0)/1000.0 FROM ac_line_all WHERE frequency_hz=0").fetchone()[0], 1)
    inv["components_ac_tr"] = n_comp; inv["components_incl_dc"] = n_comp_dc
    inv["ge220_50hz_km"] = round(g.execute("SELECT SUM(length_conductor_m)/1000.0 FROM ac_line_all WHERE voltage_kv IN (220,225,236,275,300,330,380,400,420,500,750) AND frequency_hz=50").fetchone()[0], 1)
    tr_by_cc = Counter()
    for cc, L in g.execute("SELECT countries, length_conductor_m FROM ac_line_all WHERE frequency_hz=16.7"):
        tr_by_cc[cc] += L / 1000.0
    inv["traction_km_by_country"] = {k: round(v, 1) for k, v in tr_by_cc.most_common(8)}
log("invariants", **inv)

if violations:
    t.rollback(); g.rollback(); log("rolled_back", reason="invariant violations"); sys.exit(2)
if APPLY:
    t.execute("INSERT INTO patch_history VALUES ('v22', ?, 'frequency separation; scope prune; circuit collapse; length recompute; component redefinition (AC+transformer); bookkeeping propagation')", (NOW,))
    t.commit(); g.commit(); log("committed", apply=True)
else:
    t.rollback(); g.rollback(); log("rolled_back", apply=False)
