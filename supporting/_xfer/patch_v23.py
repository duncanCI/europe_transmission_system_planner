#!/usr/bin/env python3
# patch_v23.py - v23: close the two PyPSA-readiness attribute gaps left at v22.
#   Gap 1: transformer layer carried no impedance or rating -> add s_nom_mva, x_pu, r_pu,
#           parameters_source (per-unit on own s_nom, per PyPSA Transformer convention).
#   Gap 2: dc_link carried no capacity -> add p_nom_mw, status, p_nom_source
#           (researched per link from public sources; unknown stays unknown).
# Attribute-only: no geometry, no row creation/deletion, no layer changes, graph gpkg untouched.
# Idempotent via patch_history 'v23'. Fail-closed: any invariant breach -> rollback, exit 2.
# Stdlib only. Usage: python3 patch_v23.py <path-to-europe_grid_topology.gpkg>
# Requires dc_link_ratings.csv and transformer_typing_rule.csv in the same directory
# as this script: the ratings CSV is cross-checked row-by-row against the embedded
# table (transcription guard), the typing-rule CSV is loaded verbatim into the gpkg
# as table v23_typing_rule so the parameter provenance travels with the data.
import sqlite3, sys, struct, csv, os

DB = sys.argv[1] if len(sys.argv) > 1 else 'europe_grid_topology.gpkg'
HERE = os.path.dirname(os.path.abspath(__file__))
DC_STATUS_VOCAB = {'operational', 'partially_operational', 'under_construction',
                   'planned', 'decommissioned', 'unknown'}

# ============================================================================
# EVIDENCE TABLES -- injected from the v23 research pass (see dc_link_ratings.csv
# and transformer_typing_rule.csv alongside this file for sources).
# ============================================================================

# fid -> (p_nom_mw | None, status, source_label, note_suffix_for_qa)
DC_RATINGS = {
    1: (500, 'operational', 'https://en.wikipedia.org/wiki/HVDC_Italy%E2%80%93Greece', None),
    2: (1000, 'operational', 'https://en.wikipedia.org/wiki/Nemo_Link', None),
    3: (1000, 'operational', 'https://www.elia.be/-/media/project/elia/shared/documents/press-releases/2020/20201109_cp-alegro-inauguration_en.pdf', None),
    4: (600, 'operational', 'https://en.wikipedia.org/wiki/Kontek', None),
    5: (600, 'operational', 'https://en.wikipedia.org/wiki/Baltic_Cable', None),
    6: (400, 'operational', 'https://en.wikipedia.org/wiki/BorWin1', None),
    7: (800, 'operational', 'https://www.tennet.eu/de-en/projects/borwin2', None),
    8: (916, 'operational', 'https://www.tennet.eu/de-en/projects/dolwin2', None),
    9: (700, 'operational', 'https://en.wikipedia.org/wiki/COBRAcable', None),
    10: (700, 'operational', 'https://en.wikipedia.org/wiki/NorNed', None),
    11: (900, 'operational', 'https://en.wikipedia.org/wiki/HVDC_DolWin3', None),
    12: (800, 'operational', 'https://en.wikipedia.org/wiki/HVDC_DolWin1', None),
    13: (1400, 'operational', 'https://en.wikipedia.org/wiki/NordLink', None),
    14: (2000, 'under_construction', 'https://www.bundesnetzagentur.de/SharedDocs/Pressemitteilungen/EN/2025/20251031_Ultranet.html', 'series_section_carries_full_2000MW_scheme_rating'),
    15: (600, 'operational', 'https://en.wikipedia.org/wiki/Great_Belt_Power_Link', None),
    16: (700, 'operational', 'https://en.wikipedia.org/wiki/Skagerrak_(power_transmission_system)', 'skagerrak_pole_4;system_total_1700MW_exceeds_sum_of_pole_nameplates_1640MW_fids_70_71_72'),
    17: (1400, 'operational', 'https://www.nationalgrid.com/national-grid-ventures/viking-link', None),
    18: (650, 'operational', 'https://www.fingrid.fi/en/grid/development/part-of-the-nordic-power-system/', None),
    19: (350, 'operational', 'https://www.fingrid.fi/en/grid/development/part-of-the-nordic-power-system/', None),
    20: (1000, 'operational', 'https://www.inelfe.eu/en/projects/baixas-santa-llogaia', None),
    21: (1000, 'operational', 'https://www.inelfe.eu/en/projects/baixas-santa-llogaia', None),
    22: (400, 'operational', 'https://en.wikipedia.org/wiki/Cometa_(HVDC)', None),
    23: (800, 'operational', 'https://www.fingrid.fi/en/grid/development/part-of-the-nordic-power-system/', None),
    24: (400, 'operational', 'https://www.fingrid.fi/en/grid/development/part-of-the-nordic-power-system/', None),
    25: (333, 'operational', 'inferred: equal split of the 1000 MW Vyborg back-to-back scheme across its three border circuits; https://en.wikipedia.org/wiki/Vyborg_HVDC_scheme', 'inferred_equal_split_of_vyborg_btb_1000MW_across_3_rows;ru_trade_suspended_2022'),
    26: (333, 'operational', 'inferred: equal split of the 1000 MW Vyborg back-to-back scheme across its three border circuits; https://en.wikipedia.org/wiki/Vyborg_HVDC_scheme', 'inferred_equal_split_of_vyborg_btb_1000MW_across_3_rows;ru_trade_suspended_2022'),
    27: (334, 'operational', 'inferred: equal split of the 1000 MW Vyborg back-to-back scheme across its three border circuits; https://en.wikipedia.org/wiki/Vyborg_HVDC_scheme', 'inferred_equal_split_of_vyborg_btb_1000MW_across_3_rows;ru_trade_suspended_2022'),
    28: (2000, 'operational', 'https://www.gevernova.com/grid-solutions/sites/default/files/resources/products/applications/hvdc/hvdc-ifa2000renovation-casestudy-en-2018-04-grid-pea-0572.pdf', 'umbrella_relation_of_ifa2000;duplicates_fids_30_31_32_33;exclude_from_capacity_sums'),
    29: (300, 'operational', 'inferred: series-section capability equal to the 300 MW scheme rating; https://en.wikipedia.org/wiki/HVDC_Italy%E2%80%93Corsica%E2%80%93Sardinia', 'series_section_of_sacoi2_300MW;do_not_sum_sections;exclude_from_capacity_sums'),
    30: (500, 'operational', 'https://www.gevernova.com/grid-solutions/sites/default/files/resources/products/applications/hvdc/hvdc-ifa2000renovation-casestudy-en-2018-04-grid-pea-0572.pdf', 'ifa2000_member_cable_pair;umbrella_row_fid_28'),
    31: (500, 'operational', 'https://www.gevernova.com/grid-solutions/sites/default/files/resources/products/applications/hvdc/hvdc-ifa2000renovation-casestudy-en-2018-04-grid-pea-0572.pdf', 'ifa2000_member_cable_pair;umbrella_row_fid_28'),
    32: (500, 'operational', 'https://www.gevernova.com/grid-solutions/sites/default/files/resources/products/applications/hvdc/hvdc-ifa2000renovation-casestudy-en-2018-04-grid-pea-0572.pdf', 'ifa2000_member_cable_pair;umbrella_row_fid_28'),
    33: (500, 'operational', 'https://www.gevernova.com/grid-solutions/sites/default/files/resources/products/applications/hvdc/hvdc-ifa2000renovation-casestudy-en-2018-04-grid-pea-0572.pdf', 'ifa2000_member_cable_pair;umbrella_row_fid_28'),
    34: (1000, 'operational', 'https://en.wikipedia.org/wiki/SAPEI', None),
    35: (600, 'operational', 'https://www.rte-france.com/actualites/interconnexion-electrique-france-italie-savoie-piemont-pleinement-operationnelle', None),
    36: (300, 'operational', 'inferred: series-section capability equal to the 300 MW scheme rating; https://en.wikipedia.org/wiki/HVDC_Italy%E2%80%93Corsica%E2%80%93Sardinia', 'series_section_of_sacoi2_300MW;do_not_sum_sections;canonical_sacoi2_row_for_capacity_sums'),
    37: (1000, 'operational', 'https://en.wikipedia.org/wiki/IFA-2', None),
    38: (600, 'operational', 'https://www.gevernova.com/grid-solutions/sites/default/files/resources/products/applications/hvdc/france-italy-hvdc-link-casestudy-en-2018-02-grid-pea-1641.pdf', None),
    39: (1000, 'operational', 'https://en.wikipedia.org/wiki/ElecLink', None),
    40: (500, 'operational', 'https://en.wikipedia.org/wiki/Moyle_Interconnector', 'voltage_tag_500kV_vs_published_250kV_dual_monopole'),
    41: (1200, 'operational', 'https://en.wikipedia.org/wiki/Caithness_-_Moray_Link', None),
    42: (500, 'operational', 'https://en.wikipedia.org/wiki/East%E2%80%93West_Interconnector', None),
    43: (1400, 'operational', 'https://en.wikipedia.org/wiki/North_Sea_Link', None),
    44: (1000, 'operational', 'https://en.wikipedia.org/wiki/BritNed', None),
    45: (500, 'operational', 'https://en.wikipedia.org/wiki/Greenlink', None),
    46: (2250, 'operational', 'https://en.wikipedia.org/wiki/Western_HVDC_Link', None),
    47: (600, 'operational', 'https://en.wikipedia.org/wiki/Shetland_HVDC_Connection', None),
    48: (2000, 'under_construction', 'https://en.wikipedia.org/wiki/Eastern_Green_Links', None),
    49: (2000, 'under_construction', 'https://en.wikipedia.org/wiki/Eastern_Green_Links', None),
    50: (1200, 'operational', 'https://www.hitachienergy.com/news-and-events/customer-stories/dogger-bank', None),
    51: (1200, 'operational', 'https://www.hitachienergy.com/news-and-events/customer-stories/dogger-bank', None),
    52: (800, 'operational', 'https://www.hitachienergy.com/us/en/news-and-events/customer-stories/cms-hvdc-links-the-first-regional-dc-grid-in-europe', 'inferred_identification_spittal_dc_tail;overlaps_fids_41_47;exclude_from_capacity_sums'),
    53: (1400, 'under_construction', 'https://www.offshorewind.biz/2026/08/17/all-foundations-in-at-east-anglia-three/', None),
    54: (1000, 'operational', 'https://www.admie.gr/en/erga/erga-diasyndeseis/ilektriki-diasyndesi-kritis-attikis', None),
    55: (600, 'partially_operational', 'https://balkangreenenergynews.com/italy-montenegro-undersea-power-interconnector-put-in-operation/', 'second_pole_not_built_design_1200MW'),
    56: (700, 'operational', 'https://www.hitachienergy.com/news-and-events/customer-stories/nordbalt', None),
    57: (2000, 'under_construction', 'https://www.hvdcworld.com/news/dutch-2gw-offshore-wind-farm-pushed-back-by-three-years', None),
    58: (600, 'operational', 'https://en.wikipedia.org/wiki/SwePol', None),
    59: (260, 'operational', 'https://www.hitachienergy.com/us/en/news-and-events/customer-stories/the-gotland-hvdc-link', None),
    60: (1200, 'operational', 'https://www.svk.se/utveckling-av-kraftsystemet/transmissionsnatet/avslutade-transmissionsnatsprojekt/sydvastlanken/byggnation/sydvastlankens-likstromsforbindelse-ar-nu-i-drift-och-en-del-av-transmissionsnatet/', None),
    61: (750, 'unknown', 'https://en.wikipedia.org/wiki/HVDC_Volgograd%E2%80%93Donbass', 'reported_degraded_war_damage'),
    62: (None, 'operational', 'unknown; context: https://de.wikipedia.org/wiki/380-kV-Leitung_Wesel%E2%80%93D%C3%B6rpen', 'probable_ac_misclassification_frequency0_tag;published_380kV_ac_wesel_doerpen'),
    63: (None, 'unknown', 'unknown; context: https://www.tennet.eu/de/projekte/wilhelmshaven2-conneforde', 'degenerate_zero_length_relation;unidentified_probable_ac'),
    64: (None, 'operational', 'unknown; context: https://de.wikipedia.org/wiki/Ostbayernring', 'probable_ac_misclassification_frequency0_tag;published_380kV_ac_ostbayernring'),
    65: (None, 'unknown', 'unknown; context: https://en.wikipedia.org/wiki/Swissgrid', 'degenerate_relation_unidentified;probable_ac_swiss_grid_has_no_hvdc'),
    68: (350, 'operational', 'https://en.wikipedia.org/wiki/Konti%E2%80%93Skan', 'inferred_pole_identity_konti_skan;svk_system_capability_715MW_exceeds_sum_of_pole_nameplates'),
    69: (300, 'operational', 'https://en.wikipedia.org/wiki/Konti%E2%80%93Skan', 'inferred_pole_identity_konti_skan;svk_system_capability_715MW_exceeds_sum_of_pole_nameplates'),
    70: (250, 'operational', 'https://en.wikipedia.org/wiki/Skagerrak_(power_transmission_system)', 'inferred_pole_identity_skagerrak_1_2'),
    71: (250, 'operational', 'https://www.hvdcworld.com/news/skagerrak-2-cable-fault-cuts-norway-denmark-capacity-by-245-mw', 'inferred_pole_identity_skagerrak_1_2;out_of_service_2026-06-02_cable_fault_repair_due_2026-09-02;retirement_under_consideration'),
    72: (440, 'operational', 'https://en.wikipedia.org/wiki/Skagerrak_(power_transmission_system)', 'skagerrak_pole_3'),
    73: (1400, 'under_construction', 'https://norfolkzone.rwe.com/about-norfolk', 'shared_corridor_capacity_attributed_to_vanguard_west'),
    74: (None, 'planned', 'unknown; context: https://en.wikipedia.org/wiki/Berwick_Bank_Wind_Farm', 'status_planned_no_fid;osm_under_construction_tag_unsupported'),
}

# Banded transformer typing rule: list of (name, predicate on (vlo, vhi), s_nom_mva, x_pu, r_pu, source_label)
TR_RULE = [
    ('R1', lambda lo, hi: lo >= 200, 2000.0, 0.1, 0.0025,
     'typing_rule_v23:R1 (x: pypsa-eur config default, applied unconditionally in base_network.py; s_nom inferred: config fallback value never applied to transformers in the cited osm workflow, assumed aggregate EHV bank capacity; r inferred: pandapower HV family)'),
    ('R2', lambda lo, hi: 100 <= lo < 200 and hi >= 330, 500.0, 0.122, 0.0025,
     'typing_rule_v23:R2 (x from vk 12.2% (impedance magnitude; reactance correction <3e-5 pu), r from vkr 0.25%: pandapower 160 MVA 380/110 kV; s_nom inferred: parallel banks)'),
    ('R3', lambda lo, hi: 100 <= lo < 200 and 200 <= hi < 330, 300.0, 0.12, 0.0026,
     'typing_rule_v23:R3 (x from vk 12.0% (impedance magnitude; reactance correction <3e-5 pu), r from vkr 0.26%: pandapower 100 MVA 220/110 kV; s_nom inferred: parallel banks)'),
    ('R4', lambda lo, hi: 100 <= lo < 200 and hi < 200, 300.0, 0.1, 0.0025,
     'typing_rule_v23:R4 (x: pypsa-eur config default; r,s_nom inferred: no matching standard type at near-unity ratio)'),
    ('R5', lambda lo, hi: lo < 100 and hi >= 200, 200.0, 0.16, 0.004,
     'typing_rule_v23:R5 (inferred: extrapolated from pandapower 110/20 kV family, no standard type with 50-100 kV LV side exists)'),
    ('R6', lambda lo, hi: lo < 100 and hi < 200, 120.0, 0.16, 0.004,
     'typing_rule_v23:R6 (inferred: extrapolated from pandapower 110/20 kV family, no standard type with 50-100 kV LV side exists)'),
]


def tr_params(vlo, vhi):
    for name, pred, s, x, r, src in TR_RULE:
        if pred(vlo, vhi):
            return s, x, r, src
    raise AssertionError(f"typing rule does not cover pair {vlo}/{vhi}")


# ---------------------------------------------------------------------------
# gpkg ST_* shims so rtree triggers cannot fail if they fire (defensive; v23
# never touches geom so they should not fire at all).
# ---------------------------------------------------------------------------
def _envelope(blob):
    if blob is None or len(blob) < 8 or blob[:2] != b'GP':
        return None
    flags = blob[3]
    env = (flags >> 1) & 7
    if env == 0:
        return None
    little = flags & 1
    fmt = '<' if little else '>'
    n = {1: 4, 2: 6, 3: 6, 4: 8}.get(env)
    if n is None:
        return None
    vals = struct.unpack_from(f'{fmt}{n}d', blob, 8)
    return vals[0], vals[1], vals[2], vals[3]  # minx maxx miny maxy


def register_st(conn):
    conn.create_function('ST_IsEmpty', 1, lambda b: 1 if b is None else 0)
    for i, fn in enumerate(['ST_MinX', 'ST_MaxX', 'ST_MinY', 'ST_MaxY']):
        conn.create_function(fn, 1, (lambda idx: lambda b: (_envelope(b) or (None,) * 4)[idx])(i))


def check_csv_matches_embedded():
    """Transcription guard: the shipped provenance CSV and the embedded table must agree."""
    path = os.path.join(HERE, 'dc_link_ratings.csv')
    assert os.path.exists(path), f'dc_link_ratings.csv not found beside the patch ({path})'
    seen = {}
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            try:
                fid = int(row['fid'])
                p = None if row['p_nom_mw'] == 'unknown' else float(row['p_nom_mw'])
            except (ValueError, TypeError) as e:
                raise AssertionError(
                    f"malformed CSV cell at fid={row.get('fid')!r} p_nom_mw={row.get('p_nom_mw')!r}: {e}")
            seen[fid] = (p, row['status'], row['p_nom_source_shipped'], row['qa_flag_added'] or None)
    assert set(seen) == set(DC_RATINGS), 'CSV/embedded fid sets differ'
    for fid, (p, st, src, note) in DC_RATINGS.items():
        pe = None if p is None else float(p)
        assert seen[fid] == (pe, st, src, note), \
            f'CSV/embedded mismatch at fid {fid}: {seen[fid]} != {(pe, st, src, note)}'


def load_typing_rule_rows():
    path = os.path.join(HERE, 'transformer_typing_rule.csv')
    assert os.path.exists(path), f'transformer_typing_rule.csv not found beside the patch ({path})'
    with open(path, newline='', encoding='utf-8') as f:
        rows = [tuple(r[c] for c in ('band', 'selector', 's_nom_mva', 'x_pu', 'r_pu',
                                     'basis', 'source_url')) for r in csv.DictReader(f)]
    assert len(rows) == 8, f'typing rule CSV has {len(rows)} rows, expected 8'
    # the six R-bands in the CSV must match the embedded TR_RULE numerically
    csv_bands = {r[0]: (float(r[2]), float(r[3]), float(r[4])) for r in rows if r[0].startswith('R')}
    for name, _pred, s, x, rr, _src in TR_RULE:
        assert csv_bands[name] == (s, x, rr), f'typing-rule CSV/embedded mismatch at {name}'
    return rows


def main():
    assert DC_RATINGS and TR_RULE, 'evidence tables not injected - refusing to run'
    check_csv_matches_embedded()
    rule_rows = load_typing_rule_rows()
    conn = sqlite3.connect(DB)
    conn.isolation_level = None  # manual transaction control
    register_st(conn)
    cur = conn.cursor()

    if cur.execute("SELECT 1 FROM patch_history WHERE version='v23'").fetchone():
        print('v23 already applied - no-op')
        return 0

    # ---- pre-state capture ------------------------------------------------
    pre = {}
    for t in ('transformer', 'dc_link'):
        pre[t] = cur.execute(
            f"SELECT COUNT(*), COALESCE(SUM(LENGTH(geom)),0) FROM {t}").fetchone()
    n_tr, n_dc = pre['transformer'][0], pre['dc_link'][0]
    print(f'pre: {n_tr} transformers, {n_dc} dc links')

    dc_fids = {r[0] for r in cur.execute('SELECT fid FROM dc_link')}
    assert dc_fids == set(DC_RATINGS), (
        f'dc fid mismatch: db-only={sorted(dc_fids - set(DC_RATINGS))} '
        f'table-only={sorted(set(DC_RATINGS) - dc_fids)}')

    # ---- column adds (no-op guarded) --------------------------------------
    def addcol(table, col, typ):
        cols = [r[1] for r in cur.execute(f'PRAGMA table_info({table})')]
        if col not in cols:
            cur.execute(f'ALTER TABLE {table} ADD COLUMN {col} {typ}')

    for c, t in (('s_nom_mva', 'REAL'), ('x_pu', 'REAL'), ('r_pu', 'REAL'),
                 ('s_nom_pypsa_eur_mva', 'REAL'), ('parameters_source', 'TEXT')):
        addcol('transformer', c, t)
    for c, t in (('p_nom_mw', 'REAL'), ('status', 'TEXT'), ('p_nom_source', 'TEXT')):
        addcol('dc_link', c, t)

    cur.execute('BEGIN')
    try:
        # ---- transformer fill: one UPDATE per voltage pair ----------------
        pairs = cur.execute(
            'SELECT MIN(voltage0_kv,voltage1_kv), MAX(voltage0_kv,voltage1_kv), COUNT(*) '
            'FROM transformer GROUP BY 1, 2').fetchall()
        filled = 0
        for vlo, vhi, n in pairs:
            s, x, r, src = tr_params(vlo, vhi)
            cur.execute(
                'UPDATE transformer SET s_nom_mva=?, x_pu=?, r_pu=?, parameters_source=? '
                'WHERE MIN(voltage0_kv,voltage1_kv)=? AND MAX(voltage0_kv,voltage1_kv)=?',
                (s, x, r, src, vlo, vhi))
            filled += cur.rowcount
        assert filled == n_tr, f'transformer fill covered {filled}/{n_tr}'

        # near-unity voltage ratios are probably OSM tagging artefacts, not real plant
        cur.execute(
            "UPDATE transformer SET parameters_source = parameters_source || "
            "';ratio_lt_1p095_probable_voltage_tagging_artifact' "
            "WHERE MAX(voltage0_kv,voltage1_kv) < 1.095 * MIN(voltage0_kv,voltage1_kv) "
            "AND instr(parameters_source, 'ratio_lt_1p095') = 0")
        print(f'  ratio<1.095 flagged: {cur.rowcount}')

        # ---- alternative rating column: the convention PyPSA-Eur actually ships
        # (build_osm_network.py L1238-1248): s_nom = ceil(max(total incident AC line
        # s_nom at bus0, at bus1)). Traction and internal-to-station layers excluded.
        import math
        from collections import defaultdict
        sums = defaultdict(float)
        layers = [r[0] for r in cur.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type='features' "
            "AND table_name LIKE 'line_%' AND table_name != 'line_internal_to_station' "
            "AND table_name NOT LIKE '%16_7Hz'")]
        assert len(layers) >= 20, f'only {len(layers)} line layers found - wrong file?'
        for lay in layers:
            for b0, b1, s in cur.execute(f'SELECT bus0, bus1, s_nom_mva FROM {lay}'):
                if s:
                    if b0: sums[b0] += s
                    if b1: sums[b1] += s
        alt_rows, fallback = [], 0
        for fid, b0, b1, s_band in cur.execute(
                'SELECT fid, bus0, bus1, s_nom_mva FROM transformer').fetchall():
            alt = math.ceil(max(sums.get(b0, 0.0), sums.get(b1, 0.0)))
            if alt <= 0:
                alt, fb = s_band, 1
            else:
                fb = 0
            fallback += fb
            alt_rows.append((float(alt), fb, fid))
        cur.executemany(
            "UPDATE transformer SET s_nom_pypsa_eur_mva=?, parameters_source = parameters_source || "
            "CASE WHEN ?=1 AND instr(parameters_source,'alt_snom_fallback')=0 "
            "THEN ';alt_snom_fallback_banded_no_incident_ac_lines' ELSE '' END WHERE fid=?", alt_rows)
        print(f'  alt s_nom (pypsa-eur incident-capacity rule) filled from {len(layers)} layers; '
              f'fallback rows: {fallback}')

        # ---- dc_link fill --------------------------------------------------
        for fid, (p, status, src, note) in DC_RATINGS.items():
            cur.execute('UPDATE dc_link SET p_nom_mw=?, status=?, p_nom_source=? WHERE fid=?',
                        (p, status, src, fid))
            if note:
                cur.execute(
                    "UPDATE dc_link SET qa_flags = CASE WHEN qa_flags IS NULL OR qa_flags='' "
                    "THEN ? ELSE qa_flags || ';' || ? END WHERE fid=? AND (qa_flags IS NULL OR instr(qa_flags, ?) = 0)",
                    (note, note, fid, note))

        # ---- invariants (fail closed) --------------------------------------
        for t in ('transformer', 'dc_link'):
            post = cur.execute(
                f"SELECT COUNT(*), COALESCE(SUM(LENGTH(geom)),0) FROM {t}").fetchone()
            assert post == pre[t], f'{t} rows or geometry changed: {pre[t]} -> {post}'
        bad_tr = cur.execute(
            'SELECT COUNT(*) FROM transformer WHERE s_nom_mva IS NULL OR x_pu IS NULL '
            'OR r_pu IS NULL OR parameters_source IS NULL OR s_nom_pypsa_eur_mva IS NULL '
            'OR s_nom_pypsa_eur_mva <= 0').fetchone()[0]
        assert bad_tr == 0, f'{bad_tr} transformers left unparameterised'
        bad_dc = cur.execute(
            "SELECT COUNT(*) FROM dc_link WHERE p_nom_source IS NULL OR status IS NULL").fetchone()[0]
        assert bad_dc == 0, f'{bad_dc} dc links left unsourced'
        bad_pair = cur.execute(
            "SELECT COUNT(*) FROM dc_link WHERE p_nom_mw IS NULL AND p_nom_source NOT LIKE 'unknown%'").fetchone()[0]
        assert bad_pair == 0, f'{bad_pair} dc links have null rating but a non-unknown source'
        bad_rev = cur.execute(
            "SELECT COUNT(*) FROM dc_link WHERE p_nom_mw IS NOT NULL AND p_nom_source LIKE 'unknown%'").fetchone()[0]
        assert bad_rev == 0, f'{bad_rev} dc links carry a rating on an unknown source'
        bad_range = cur.execute(
            'SELECT COUNT(*) FROM dc_link WHERE p_nom_mw IS NOT NULL '
            'AND (p_nom_mw <= 0 OR p_nom_mw > 4000)').fetchone()[0]
        assert bad_range == 0, f'{bad_range} dc links with out-of-range rating'
        vocab = ','.join(f"'{v}'" for v in sorted(DC_STATUS_VOCAB))
        bad_vocab = cur.execute(
            f'SELECT COUNT(*) FROM dc_link WHERE status NOT IN ({vocab})').fetchone()[0]
        assert bad_vocab == 0, f'{bad_vocab} dc links with status outside the controlled vocabulary'
        neg = cur.execute(
            'SELECT COUNT(*) FROM transformer WHERE s_nom_mva <= 0 OR x_pu <= 0 OR r_pu < 0').fetchone()[0]
        assert neg == 0, f'{neg} transformers with non-physical parameters'

        # provenance table travels with the data, registered as a gpkg attributes table
        # so spec-following readers (QGIS, ogrinfo) list it
        cur.execute('DROP TABLE IF EXISTS v23_typing_rule')
        cur.execute('CREATE TABLE v23_typing_rule (fid INTEGER PRIMARY KEY, band TEXT, '
                    'selector TEXT, s_nom_mva TEXT, x_pu TEXT, r_pu TEXT, basis TEXT, source_url TEXT)')
        cur.executemany('INSERT INTO v23_typing_rule (band, selector, s_nom_mva, x_pu, r_pu, '
                        'basis, source_url) VALUES (?,?,?,?,?,?,?)', rule_rows)
        assert cur.execute('SELECT COUNT(*) FROM v23_typing_rule').fetchone()[0] == 8
        cur.execute("DELETE FROM gpkg_contents WHERE table_name='v23_typing_rule'")
        cur.execute(
            "INSERT INTO gpkg_contents (table_name, data_type, identifier, description, "
            "last_change, srs_id) VALUES ('v23_typing_rule', 'attributes', 'v23_typing_rule', "
            "'v23 transformer parameter typing rule with per-band sources (see README section 13)', "
            "'2026-08-18T12:00:00.000Z', NULL)")
        has_ogr = cur.execute(
            "SELECT 1 FROM sqlite_master WHERE name='gpkg_ogr_contents'").fetchone()
        if has_ogr:
            cur.execute("DELETE FROM gpkg_ogr_contents WHERE table_name='v23_typing_rule'")
            cur.execute("INSERT INTO gpkg_ogr_contents VALUES ('v23_typing_rule', 8)")

        cur.execute(
            "UPDATE gpkg_contents SET last_change = '2026-08-18T12:00:00.000Z' "
            "WHERE table_name IN ('transformer','dc_link')")
        cur.execute(
            "INSERT INTO patch_history VALUES ('v23', '2026-08-18T12:00:00Z', "
            "'transformer s_nom/x/r per banded typing rule + s_nom_pypsa_eur_mva; dc_link p_nom/status per-link research; typing rule embedded as v23_typing_rule; attribute-only')")
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    # ---- report -------------------------------------------------------------
    print('post: transformer parameter coverage 100%')
    for row in cur.execute(
            "SELECT substr(parameters_source, 1, 18), COUNT(*), ROUND(SUM(s_nom_mva)) "
            'FROM transformer GROUP BY 1 ORDER BY 2 DESC'):
        print('  tr', row)
    alt = cur.execute(
        'SELECT ROUND(MIN(s_nom_pypsa_eur_mva)), ROUND(AVG(s_nom_pypsa_eur_mva)), '
        'ROUND(MAX(s_nom_pypsa_eur_mva)) FROM transformer').fetchone()
    print(f'  alt s_nom min/mean/max: {alt}')
    known = cur.execute(
        'SELECT COUNT(*), ROUND(SUM(p_nom_mw)) FROM dc_link WHERE p_nom_mw IS NOT NULL').fetchone()
    cleaned = cur.execute(
        "SELECT ROUND(SUM(p_nom_mw)) FROM dc_link WHERE p_nom_mw IS NOT NULL "
        "AND instr(COALESCE(qa_flags,''), 'exclude_from_capacity_sums') = 0").fetchone()[0]
    print(f'  dc rated: {known[0]}/{n_dc} links; gross {known[1]} MW; '
          f'excluding exclude_from_capacity_sums rows {cleaned} MW; unknown: {n_dc - known[0]}')
    for row in cur.execute('SELECT status, COUNT(*) FROM dc_link GROUP BY 1 ORDER BY 2 DESC'):
        print('  dc status', row)
    conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    conn.close()
    print('v23 applied OK')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except AssertionError as e:
        print(f'INVARIANT FAILED - rolled back: {e}', file=sys.stderr)
        sys.exit(2)
