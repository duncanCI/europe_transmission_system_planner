# Parity audit: this dataset against PyPSA-Eur and openTYNDP

2026-08-19. Purpose: establish, dimension by dimension, whether this dataset is
aligned with or ahead of the published state of the art, so its outputs stand up
when reviewing plans in front of technically literate counterparties. Upstream
evidence is cited against PyPSA-Eur commit `a5408e9` (checked locally) and the
method paper (Xiong, Fioriti, Neumann, Riepin & Brown 2025, Sci Data 12:277,
doi:10.1038/s41597-025-04550-7). Claims corrected on 2026-08-19 (the 500 m
truncation attribution) are not repeated here.

## Dimension table

| # | Dimension | PyPSA-Eur (evidence) | This dataset | Standing |
|---|---|---|---|---|
| 1 | Voltage scope | Default 220-750 kV; a 63-750 kV config exists since 2025-08 (PR #1740, `config.distribution-grid-experimental.yaml`) but **every prebuilt release v0.1-v0.7 is 220 kV+** | 50-750 kV built, shipped and validated; 750,631 route-km vs 282,283 at 220+ | **Ahead on shipped artefact**; method itself is not novel and is not claimed as such |
| 2 | Geometry and bus placement | Conductor geometry preserved; buses placed inside station polygons (polylabel) | Same properties | Parity |
| 3 | Topology below 220 kV | Deferred by upstream's own code: `# TODO: In first draft, skip line splitting for lower voltage levels` / `lines.query("voltage >= 220000")` - `build_osm_network.py:263-264` | Line splitting, junction nodes and duplicate-circuit collapse applied at every voltage down to 50 kV; components are real synchronous areas | **Ahead**, citable to their own TODO |
| 4 | Railway traction (16.7 Hz) | Coerced to 50 Hz in `clean_osm_data.py` (normalisation L267-268; reassignment L884-1014, L1905; frequency column not released) - 16,524 km welded to the public grid | Separated into `_16_7Hz` layers, validated against SBB (1,764 vs published ~1,800 km) and Trafikverket | **Ahead**; upstream issue drafted (`upstream_issue_draft.md`) - **file it**, the finding gains its public record and priority date |
| 5 | Line electrical parameters | Per-voltage standard types, `config.default.yaml:434-443` (63/66 -> 94-AL1/15-ST1A; 132/150 -> 243-AL1/39-ST1A; 220/300/380 -> Al/St 240/40 bundles) | Identical types and s_nom convention (checked value for value); typing table shipped as data | Parity by construction - our per-voltage line parameters are upstream's own |
| 6 | Transformer parameters | Heuristic s_nom from incident capacity | That heuristic **kept as a column** (`s_nom_pypsa_eur_mva`) plus a six-band typed rule with per-band source citations for s_nom/x/r | Ahead on provenance; both lenses preserved so results are comparable either way |
| 7 | DC links | From OSM tags with manual fixes | 67 of 72 links carry a per-link sourced rating (source URL + review notes per row); 5 say unknown; double-count rows flagged | Ahead on provenance |
| 8 | Validation | Compared against ENTSO-E factsheet lengths (paper Table 8) | Reproduces that same benchmark (+3.0% at 220 kV+); **plus** PyPSA end-to-end solve test; **plus** independent government-geometry validation in six countries (93-98% mutual coverage at 250 m); **plus** substation spot-check vs RTE (24/28 within 250 m, median 29 m); **plus** circuit-km reconciliation vs RTE within 5% per voltage level | **Ahead** - the six-country authoritative validation has no upstream equivalent |
| 9 | Reproducibility | Snakemake workflow, Zenodo releases | Region-agnostic 3-stage pipeline + 4 test suites (31/31 mutations caught), acceptance benchmark; declared honestly as a reimplementation of the documented method, not the original build code | Parity with a declared caveat |
| 10 | Licensing and citation | ODbL, citable via paper + Zenodo DOI | ODbL 1.0, CITATION.cff citing the method paper, Zenodo deposit prepared | Parity once the deposit is published |
| 11 | openTYNDP | A scenario/planning model on the TYNDP reference grid (capacity expansion, PECD, market nodes) | A different object: an asset-level spatial model. Points of contact: all 38 TYNDP-relevant DC interconnectors present; corridors cross-matched to public national development plans | Aligned by scope, not competing. When reviewing plans: capacity-expansion arguments cite openTYNDP-class models; spatial/routeing evidence cites this |

## The definitional finding every reviewer would catch first

Route-km is not comparable across mapping conventions. OSM France maps most
400 kV circuits as separate ways, so our summed "route-km" behaves like
circuit-km there. Computed both ways on both sides from RTE's own file:

| kV | RTE route-km | RTE circuit-km | Ours route-km | Ours circuit-km |
|---|---|---|---|---|
| 90 | 15,009 | 17,634 | 16,075 | 18,554 |
| 225 | 23,294 | 28,203 | 26,461 | 27,256 |
| 400 | 13,691 | 22,558 | 21,580 | 21,955 |

**Circuit-km agrees with RTE's asset register within 3-5% at every level.** The
defensible public statement is circuit-km; route-km comparisons across datasets
must state the mapping convention. README updated accordingly.

## Declared weaknesses (say these before a reviewer does)

Electrical parameters are typed, not asset-register values - fit for
connectivity and screening, not defended load flow (stated in the README and
every outbound draft). The rebuild pipeline is a reimplementation; equivalence
is demonstrated through the benchmark, not byte-identity. n_circuits on v24
fused rows is inferred (NVE publishes traces, not circuits). Five DC links are
honest unknowns. Luxembourg shows 15% mutual disagreement with the national
cadastre, unresolved. OSM currency varies by country while several authoritative
sources refresh weekly - the validation is a 2026-08 snapshot. Sub-50 kV
network is out of scope by design, including 4,725 km of Norwegian <50 kV
regional network the fusion deliberately left out.

## Actions that convert this audit into standing

1. **File the upstream traction issue** (draft ready; your GitHub click) - the
   16.7 Hz finding becomes a public, dated record instead of a private claim.
2. README route-km/circuit-km definition - applied in this session.
3. NLOD attribution line on v24 apply (in `V24_REVIEW.md`).
4. Zenodo DOI publishes the artefact citation path (`ZENODO_DEPOSIT.md`).

## Reviewer FAQ (the five hard questions)

**"Isn't this just PyPSA-Eur at a lower floor?"** The method is theirs, cited;
the artefact is not - no released open dataset covers 50-150 kV connected
topology, and their own code defers sub-220 topology (build_osm_network.py:263).

**"Why should I trust OSM geometry?"** Six governments' own published geometry
agrees with it to 93-98% at 250 m; RTE's substations match ours at a 29 m
median offset.

**"Your French 400 kV total is 58% above RTE's."** It is circuit-km by mapping
convention; on like-for-like circuit-km we are within 3% of RTE at 400 kV.

**"Can I run load flow on it?"** Structural screening yes (typed parameters,
PyPSA-proven solvable); defended load flow no - stated on every artefact.

**"What did you change in the data and can I audit it?"** Every manual
correction, rating and fused feature carries a row-level evidence file
(manual_corrections.csv, dc_link_ratings.csv, v24_evidence_*.csv), and every
inferred or unknown value is labelled as such in-cell.
