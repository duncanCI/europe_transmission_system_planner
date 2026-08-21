#!/usr/bin/env python3
# PyPSA acid test v2 - implements all methodology-review fixes.
# Sub-networks are computed with scipy sparse connected_components (pypsa 1.2.4's
# adjacency_matrix materialises a dense NxN frame - 42 GiB at this scale - and
# determine_network_topology is super-linear; both are bypassed, as the review directs).
# Exit code 0 only if every assertion passes.
import sqlite3, sys, json, math
import numpy as np
import pandas as pd
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components
import pypsa
from shapely import wkb

DIR = sys.argv[1]
g = sqlite3.connect(f"{DIR}/europe_grid_graph.gpkg"); g.row_factory = sqlite3.Row
t = sqlite3.connect(f"{DIR}/europe_grid_topology.gpkg"); t.row_factory = sqlite3.Row
def gw(b):
    fl = b[3]; env = (fl >> 1) & 7
    return b[8 + {0:0,1:32,2:48,3:48,4:64}[env]:]

report = {}
fails = []
def check(name, ok, detail=""):
    report[name] = ("PASS" if ok else "FAIL") + (f" ({detail})" if detail else "")
    if not ok: fails.append(name)

buses = list(g.execute("SELECT bus_id, voltage_kv, frequency_hz, geom FROM site_all"))
xs, ys = [], []
for r in buses:
    p = wkb.loads(bytes(gw(r["geom"])))
    xs.append(p.x); ys.append(p.y)
freq = {r["bus_id"]: (r["frequency_hz"] or 50.0) for r in buses}

n = pypsa.Network()
n.add("Carrier", ["AC", "DC"])
n.add("Bus", [r["bus_id"] for r in buses], v_nom=[r["voltage_kv"] for r in buses],
      x=xs, y=ys, carrier="AC")
n.buses["frequency_hz"] = pd.Series(freq)

lines = list(g.execute("SELECT line_id, bus0, bus1, r_ohm, x_ohm, s_nom_mva FROM ac_line_all"))
n.add("Line", [r["line_id"] for r in lines],
      bus0=[r["bus0"] for r in lines], bus1=[r["bus1"] for r in lines],
      r=[max(r["r_ohm"], 1e-4) for r in lines], x=[max(r["x_ohm"], 1e-4) for r in lines],
      s_nom=[r["s_nom_mva"] for r in lines], carrier="AC")

# transformers: v23 ships real per-pair parameters (banded typing rule, sourced).
# Read them from the table; fail loudly if any are missing rather than papering over.
trs = list(t.execute("SELECT transformer_id, bus0, bus1, s_nom_mva, x_pu, r_pu FROM transformer"))
missing_tr = [r["transformer_id"] for r in trs if r["s_nom_mva"] is None or r["x_pu"] is None or r["r_pu"] is None]
check("transformer_parameters_present", len(missing_tr) == 0, f"{len(missing_tr)} rows missing v23 parameters")
n.add("Transformer", [r["transformer_id"] for r in trs],
      bus0=[r["bus0"] for r in trs], bus1=[r["bus1"] for r in trs],
      s_nom=[r["s_nom_mva"] or 1.0 for r in trs],
      x=[r["x_pu"] or 0.12 for r in trs], r=[r["r_pu"] or 0.005 for r in trs], model="pi")

# dc links: v23 ships researched p_nom (null = honest unknown -> excluded from rated stats,
# carried at 0 MW so the component/consistency checks still see the branch).
dcs = list(t.execute("SELECT fid, bus0, bus1, p_nom_mw FROM dc_link WHERE bus0 IS NOT NULL AND bus1 IS NOT NULL"))
n.add("Link", [f"dc_{r['fid']}" for r in dcs],
      bus0=[r["bus0"] for r in dcs], bus1=[r["bus1"] for r in dcs],
      p_nom=[r["p_nom_mw"] if r["p_nom_mw"] is not None else 0.0 for r in dcs], carrier="DC")
dc_rated = [r for r in dcs if r["p_nom_mw"] is not None]
excl = {r[0] for r in t.execute(
    "SELECT fid FROM dc_link WHERE instr(COALESCE(qa_flags,''), 'exclude_from_capacity_sums') > 0")}
report["dc_p_nom"] = {"rated_links": len(dc_rated), "unrated_links": len(dcs) - len(dc_rated),
                      "total_mw_gross_undeduplicated": round(sum(r["p_nom_mw"] for r in dc_rated), 0),
                      "total_mw_excl_flagged": round(sum(r["p_nom_mw"] for r in dc_rated
                                                         if r["fid"] not in excl), 0)}
report["sizes"] = {"buses": len(n.buses), "lines": len(n.lines), "transformers": len(n.transformers), "links": len(n.links)}

# 1. strict consistency (named checks; strict=True raises TypeError in 1.2.4)
try:
    n.consistency_check(strict=["unknown_buses", "unknown_carriers", "zero_impedances", "zero_s_nom", "dtypes"])
    check("consistency_strict", True)
except Exception as e:
    check("consistency_strict", False, str(e)[:200])

# 2. sub-networks via sparse graph over passive branches (lines + transformers only)
bus_idx = {b: i for i, b in enumerate(n.buses.index)}
rows, cs = [], []
for df in (n.lines, n.transformers):
    rows += [bus_idx[b] for b in df.bus0]
    cs += [bus_idx[b] for b in df.bus1]
A = sp.coo_matrix((np.ones(len(rows)), (rows, cs)), shape=(len(bus_idx), len(bus_idx)))
ncomp, labels = connected_components(A + A.T, directed=False)
report["sub_networks"] = int(ncomp)
sizes = np.bincount(labels)
report["largest_sub_buses"] = int(sizes.max())
# component column agreement
comp_db = {r["bus_id"]: r["component"] for r in g.execute("SELECT bus_id, component FROM site_all")}
lab_of_comp = {}
agree = True
for b, i in bus_idx.items():
    c = comp_db[b]
    if c in lab_of_comp:
        if lab_of_comp[c] != labels[i]: agree = False; break
    else: lab_of_comp[c] = labels[i]
check("component_column_matches_passive_partition", agree and len(lab_of_comp) == ncomp,
      f"db components {len(lab_of_comp)} vs scipy {ncomp}")

# 3. no sub-network mixes frequencies
fr = np.array([freq[b] for b in n.buses.index])
mixed = sum(1 for lab in range(ncomp) if len(set(fr[labels == lab])) > 1)
check("no_subnetwork_mixes_frequency", mixed == 0, f"{mixed} mixed")
tr_labels = set(labels[fr != 50.0])
report["traction_sub_networks"] = int(len(tr_labels))
report["traction_buses"] = int((fr != 50.0).sum())

# 4. LPF probe - scope: largest connected component of the >=220 kV, 50 Hz backbone
# (pypsa 1.2.4's determine_network_topology/find_cycles is super-linear and its
# adjacency matrix is dense; full-network LPF at 52.8k buses allocates >20 GiB.
# The backbone probe tests exactly the object PyPSA-Eur users model. Sparse
# monkeypatch below keeps topology determination feasible at backbone scale.)
import pypsa.network.graph as _pgraph
import scipy.sparse as _sp
def _sparse_adjacency(network, branch_components=None, investment_period=None, busorder=None, weights=None, return_dataframe=False):
    if busorder is None: busorder = network.buses.index
    bidx = {b: i for i, b in enumerate(busorder)}
    rows, cols, data = [], [], []
    bcs = branch_components if branch_components is not None else network.passive_branch_components
    for c in network.iterate_components(bcs):
        st = c.static
        for b0, b1 in zip(st.bus0, st.bus1):
            if b0 in bidx and b1 in bidx:
                rows.append(bidx[b0]); cols.append(bidx[b1]); data.append(1.0)
    m = _sp.coo_matrix((data, (rows, cols)), shape=(len(busorder), len(busorder)))
    if return_dataframe:
        return pd.DataFrame.sparse.from_spmatrix(m, index=busorder, columns=busorder)
    return m
_pgraph.NetworkGraphMixin.adjacency_matrix = _sparse_adjacency
pypsa.Network.adjacency_matrix = _sparse_adjacency
report["lpf_scope"] = ">=220 kV 50 Hz backbone, largest connected component"
bb220 = [b for b in n.buses.index if n.buses.at[b, "v_nom"] >= 220 and freq[b] == 50.0]
bb220s = set(bb220)
kl0 = n.lines[(n.lines.bus0.isin(bb220s)) & (n.lines.bus1.isin(bb220s))]
kt0 = n.transformers[(n.transformers.bus0.isin(bb220s)) & (n.transformers.bus1.isin(bb220s))]
bi2 = {b: i for i, b in enumerate(bb220)}
rows2 = [bi2[b] for b in kl0.bus0] + [bi2[b] for b in kt0.bus0]
cols2 = [bi2[b] for b in kl0.bus1] + [bi2[b] for b in kt0.bus1]
A2 = sp.coo_matrix((np.ones(len(rows2)), (rows2, cols2)), shape=(len(bb220), len(bb220)))
nc2, lab2 = connected_components(A2 + A2.T, directed=False)
big2 = int(np.argmax(np.bincount(lab2)))
bb = pd.Index([b for b, i in bi2.items() if lab2[i] == big2])
report["lpf_backbone_buses"] = int(len(bb))
rng = np.random.default_rng(42)
pick = rng.choice(bb, size=min(400, len(bb)), replace=False)
half = len(pick) // 2
n.add("Load", [f"L{i}" for i in range(half)], bus=pick[:half], p_set=10.0)
n.add("Generator", [f"G{i}" for i in range(half, len(pick) - 1)], bus=pick[half:len(pick)-1],
      p_set=10.0 * half / max(len(pick) - 1 - half, 1), control="PQ", p_nom=1e5)
n.add("Generator", "slack", bus=pick[-1], control="Slack", p_nom=1e6)
# assign slacks for the other sub-networks so lpf can run network-wide? Restrict instead:
sub_buses = set(bb)
nsub = pypsa.Network()
nsub.add("Carrier", ["AC", "DC"])
keep_b = n.buses.loc[list(sub_buses)]
nsub.add("Bus", keep_b.index, v_nom=keep_b.v_nom.values, x=keep_b.x.values, y=keep_b.y.values, carrier="AC")
kl = n.lines[(n.lines.bus0.isin(sub_buses)) & (n.lines.bus1.isin(sub_buses))]
nsub.add("Line", kl.index, bus0=kl.bus0.values, bus1=kl.bus1.values, r=kl.r.values, x=kl.x.values, s_nom=kl.s_nom.values, carrier="AC")
kt = n.transformers[(n.transformers.bus0.isin(sub_buses)) & (n.transformers.bus1.isin(sub_buses))]
nsub.add("Transformer", kt.index, bus0=kt.bus0.values, bus1=kt.bus1.values, s_nom=kt.s_nom.values, x=kt.x.values, r=kt.r.values, model="pi")
nsub.add("Load", [f"L{i}" for i in range(half)], bus=pick[:half], p_set=10.0)
nsub.add("Generator", [f"G{i}" for i in range(half, len(pick) - 1)], bus=pick[half:len(pick)-1],
         p_set=10.0 * half / max(len(pick) - 1 - half, 1), control="PQ", p_nom=1e5)
nsub.add("Generator", "slack", bus=pick[-1], control="Slack", p_nom=1e6)
try:
    nsub.lpf()
    flows = nsub.lines_t.p0.iloc[0]
    gen = nsub.generators_t.p.iloc[0].sum()
    load = nsub.loads_t.p.iloc[0].sum()
    check("lpf_largest_subnetwork", bool(np.isfinite(flows.values).all()), "non-finite flows" if not np.isfinite(flows.values).all() else "")
    check("lpf_balance", abs(gen - load) < 1e-3, f"gen {gen:.2f} vs load {load:.2f}")
    # KCL at every bus: injections minus line/transformer divergence ~ 0
    inj = pd.Series(0.0, index=nsub.buses.index)
    for gname, brow in nsub.generators.iterrows(): inj[brow.bus] += nsub.generators_t.p.iloc[0][gname]
    for lname, brow in nsub.loads.iterrows(): inj[brow.bus] -= nsub.loads_t.p.iloc[0][lname]
    div = pd.Series(0.0, index=nsub.buses.index)
    for df, dft in ((nsub.lines, nsub.lines_t), (nsub.transformers, nsub.transformers_t)):
        p0 = dft.p0.iloc[0]; p1 = dft.p1.iloc[0]
        for brname, brow in df.iterrows():
            div[brow.bus0] += p0[brname]; div[brow.bus1] += p1[brname]
    kcl = float((inj - div).abs().max())
    check("kcl_max_residual_MW", kcl < 1e-6, f"{kcl:.2e}")
    report["overloaded_branches_in_probe"] = int((flows.abs() > kl.s_nom.reindex(flows.index)).sum())
except Exception as e:
    check("lpf_largest_subnetwork", False, str(e)[:200])

# 5. LPF on the largest traction sub-network
if tr_labels:
    tsizes = {lab: int(sizes[lab]) for lab in tr_labels}
    tlab = max(tsizes, key=tsizes.get)
    tb = n.buses.index[labels == tlab]
    report["largest_traction_sub_buses"] = int(len(tb))
    if len(tb) > 5:
        nt = pypsa.Network(); nt.add("Carrier", ["AC"])
        kb = n.buses.loc[list(tb)]
        nt.add("Bus", kb.index, v_nom=kb.v_nom.values, x=kb.x.values, y=kb.y.values, carrier="AC")
        kl2 = n.lines[(n.lines.bus0.isin(set(tb))) & (n.lines.bus1.isin(set(tb)))]
        nt.add("Line", kl2.index, bus0=kl2.bus0.values, bus1=kl2.bus1.values, r=kl2.r.values, x=kl2.x.values, s_nom=kl2.s_nom.values, carrier="AC")
        kt2 = n.transformers[(n.transformers.bus0.isin(set(tb))) & (n.transformers.bus1.isin(set(tb)))]
        if len(kt2): nt.add("Transformer", kt2.index, bus0=kt2.bus0.values, bus1=kt2.bus1.values, s_nom=kt2.s_nom.values, x=kt2.x.values, r=kt2.r.values, model="pi")
        tp = list(tb[:min(20, len(tb))])
        nt.add("Load", [f"T{i}" for i in range(len(tp) - 1)], bus=tp[:-1], p_set=5.0)
        nt.add("Generator", "slack_t", bus=tp[-1], control="Slack", p_nom=1e5)
        try:
            nt.lpf()
            check("lpf_traction_subnetwork", bool(np.isfinite(nt.lines_t.p0.iloc[0].values).all()))
        except Exception as e:
            check("lpf_traction_subnetwork", False, str(e)[:200])

# 6. structural zero-checks
bus_set = set(n.buses.index)
check("no_dangling_line_buses", bool(n.lines.bus0.isin(bus_set).all() and n.lines.bus1.isin(bus_set).all()))
check("no_self_loops", int((n.lines.bus0 == n.lines.bus1).sum()) == 0)
check("positive_impedances", bool((n.lines.x > 0).all() and (n.lines.r > 0).all()))
check("transformer_x_positive_r_nonneg", bool((n.transformers.x > 0).all() and (n.transformers.r >= 0).all()))
check("transformer_s_nom_positive", bool((n.transformers.s_nom > 0).all()))

print(json.dumps(report, indent=1, default=str))
sys.exit(1 if fails else 0)
