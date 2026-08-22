# European Grid Topology Dataset

**Limits first: this is a screening-grade topological dataset - not survey-grade, not an asset register, not operational data, and not investment evidence.**

Topologically connected geospatial model of the electricity transmission **and sub-transmission** network across 36 ENTSO-E countries including UK and Ireland, at 50 kV and above, built from OpenStreetMap after the method of Xiong, Fioriti, Neumann, Riepin & Brown (2025), *Scientific Data* 12:277 - then corrected, frequency-separated, electrically parameterised and PyPSA-loadable over versions v20 to v23 (August 2026), where "PyPSA-loadable" means a scoped acid test: linear power flow solves on the largest >=220 kV 50 Hz backbone component only (9,955 buses, balanced synthetic injections). That is a structural check, not a validated electrical model.

> **Positioning, corrected 2026-08-19.** A prior-art check (`supporting/PRIOR_ART_FINDINGS.md`) found that two claimed differentiators did not survive scrutiny. The upstream PyPSA-Eur workflow already preserves conductor geometry and places buses inside substation polygons, and it has shipped a 63-750 kV configuration since August 2025. What is genuinely unpublished is this artefact: no open, pan-European, topologically connected grid model at 50-150 kV with preserved geometry and per-value provenance on its typed and derived attributes exists elsewhere, and every PyPSA-Eur prebuilt release to date is 220 kV and above. Claim that, and nothing more.

## What is in this folder

| Item | What it is |
|---|---|
| `europe_grid_topology.gpkg` | **The output.** 60 feature layers: `line_<kV>` 50-750 kV (+ `line_<kV>_16_7Hz` railway traction), `site_<kV>`, `junction_node`, `line_internal_to_station`, `dc_link`, `transformer`, `station_cluster`, `substation_footprint`; plus the `v23_typing_rule` provenance table and `patch_history`. v23, md5 `cb05c4108b0cb47d2fd22b81d5003daf`, 203.0 MB. Published: DOI [10.5281/zenodo.22043867](https://doi.org/10.5281/zenodo.22043867) |
| `europe_grid_graph.gpkg` | Companion flat graph for analysis: `ac_line_all`, `site_all`. v22 (untouched by v23), md5 `55ed89203d0dcfd5b8beaac1e272578b`. In the same Zenodo deposit as above |
| `rebuild_pipeline/` | Script runner to recreate the topology from scratch for any region: harvest, build, validate, plus the acceptance benchmark. `config_europe.yaml` reproduces this build; `config_australia_example.yaml` is a worked non-Europe example. Reimplementation of the documented method - the original build scripts were not persisted. Start at `README_pipeline.md` |
| `supporting/` | Everything else - methodology, evidence, validation, patches, backups. Index below |

## Headline numbers (v23)

750,631 route-km of AC network (734,107 km at 50 Hz + 16,524 km at 16.7 Hz traction, in separate layers); 936,251 circuit-km. 91,094 spans, 75,315 buses (bus = station x voltage x frequency), 4,753 transformers, 72 DC links. Transmission (>=220 kV, 50 Hz) 282,283 route-km, +3.0% against the published PyPSA-Eur dataset; 38 of 38 DC interconnectors. Components are real synchronous areas: Continental 77.4% of route-km, Nordic 11.0%, GB 3.9%, all-island Ireland 1.2%. Every transformer carries `s_nom_mva`/`x_pu`/`r_pu` (banded typing rule, per-band provenance) plus `s_nom_pypsa_eur_mva`; 67 of 72 DC links carry a sourced `p_nom_mw` (52,966 MW after excluding three flagged double-count rows), 5 honest unknowns.

## Interactive map

`docs/` is a static web viewer for the dataset (MapLibre + PMTiles, no
server-side anything; the page loads the MapLibre and PMTiles libraries from a
CDN and its basemap from OpenFreeMap, so it needs network access): AC lines by voltage class, DC links, substations,
transformers and the 16.7 Hz traction network, with every popup showing the
`*_source` provenance columns verbatim. Serve it locally with
`python webmap/serve_local.py` (plain `http.server` won't work - PMTiles needs
byte-range requests), or enable GitHub Pages (main branch, `/docs` folder) to
publish it. `webmap/build_tiles.py` regenerates the tiles from the two
GeoPackages whenever the dataset versions forward. Line tiles stop at zoom
10 and their geometry is simplified for size at every level, including z10;
the viewer overzooms above that, so no further detail appears. The
GeoPackages hold full geometry.

The viewer also carries a development-and-scenario context layer
(`webmap/build_context_tiles.py`): planned grid developments compiled from
public national and TSO network development plans (NESO
"Beyond 2030", Terna PdS 2025, RTE's project catalogue, MITECO's 2024
planning modification, and the plan cited on each feature) behind a
development-year slider, plus TYNDP 2026 scenario demand and generation
(NT+ National Trends+, LEV/HEV Low/High Economy Variant; ENTSO-E, CC BY 4.0)
shared out to OSM populated places and OSM power plants - and to >=220 kV
backbone stations in the tiles - by population and plant patterns. Limits
first: service years are
promoter-stated, not forecasts; project lines are straight schematics between
matched public endpoints unless marked as sourced plan geometry - never route
alignments; scenario circles are `inferred:` visualization weights, and the
map computes no power flows.

## Quick start

QGIS: open `europe_grid_topology.gpkg`, layers are per voltage; filter `frequency_hz = 50` for the public grid. PyPSA: load `ac_line_all` + `site_all` from the graph file as Lines/Buses, `transformer` and `dc_link` from the topology file (transformer `x_pu`/`r_pu` are per-unit on `s_nom_mva` - do not pair `x_pu` with `s_nom_pypsa_eur_mva` without recomputing); `supporting/_xfer/acid_test_pypsa.py` is a working end-to-end example (all checks PASS, `supporting/acid_report_v23.json`).

Licensing in one line: the **data** is derived from OpenStreetMap and carries **ODbL 1.0**; the **code** in this repository is **MIT** (`LICENSE`). `LICENCE_AND_ATTRIBUTION.md` is the full statement, including the third-party sources and how to credit them.

Three habits keep results honest: check `*_source` columns before quoting any value (`inferred:` and `unknown` mean what they say); never `SUM(p_nom_mw)` over `dc_link` without excluding rows flagged `exclude_from_capacity_sums`; quote lengths from `length_conductor_m`, not drawn geometry.

> **Which length to quote against a TSO's own figures: circuit-km.** Route-km is
> not comparable across mapping conventions - where OSM maps parallel circuits as
> separate ways (France at 225/400 kV, for example), summed route-km behaves like
> circuit-km. Reconciled against RTE's published asset file (2026-08-19), our
> circuit-km per voltage level agrees within 3-5%; route-km differs by up to 58%
> at 400 kV, by convention rather than error
> (`supporting/authoritative_survey/ACADEMIC_PARITY_AUDIT.md` has the table).
> State the convention whenever quoting lengths.

## How it got here

| Version | Date | What changed |
|---|---|---|
| v20 | 2026-08-17 | Full build from a 2026-08-14 OSM harvest: geometry-preserving topology, 50 kV floor, bus-in-site placement (see `supporting/README_methodology.md`, the deep method document - 12 sections, design decisions and a pitfalls table) |
| v21 | 2026-08-18 | Five provable misclassifications fixed against primary sources (`supporting/manual_corrections.csv`) |
| v22 | 2026-08-18 | Frequency separation (16.7 Hz traction split out, validated against SBB/Trafikverket lengths), scope prune, duplicate-circuit collapse, PyPSA-consistent components; acid test passes end to end |
| v23 | 2026-08-18 | Transformer electrical parameters + per-link DC ratings, every value sourced or labelled inferred/unknown; twice adversarially reviewed (README_methodology section 13) |

## `supporting/` index

| File | Purpose |
|---|---|
| `README_methodology.md` | The deep method document: how every layer was built, all thresholds, deviations from the paper, corrections v21-v23 |
| `SESSION_REVIEW_BRIEF.md` | Reviewer-oriented brief: where to look for shortfalls, open questions |
| `validation_report.csv` | Machine-readable metric sheet (schema v23) |
| `manual_corrections.csv` | Row-level log of every manual data correction, with evidence and sources |
| `dc_link_ratings.csv` | Per-DC-link rating evidence: source URL, research notes, review revisions, qa flags |
| `transformer_typing_rule.csv` | The 6-band transformer parameter rule with citations (also embedded in the gpkg as `v23_typing_rule`) |
| `v22_stats_sidecar.json`, `v23_stats_sidecar.json` | Machine-generated statistics per version |
| `acid_report_v22.json`, `acid_report_v23.json` | PyPSA 1.2.4 acid-test results (all PASS) |
| `scrape_PROVENANCE.md` | Provenance of the live OSM frequency scrape behind v22 |
| `network_overview.png` | Static render of the network |
| `_xfer/` | The applied patch scripts (v21/v22/v23), their evidence CSVs, and the acid test. `patch_v23.py` needs the two CSVs beside it |
| `_backup_v20/`, `_backup_v21/` | Pre-patch copies of both GeoPackages - local only, not in this repository |
| _(internal working material)_ | Some working material behind this build is internal, is not part of this repository or the published dataset, and is kept out of the tracked tree by `.gitignore` |

## Rebuilding

`rebuild_pipeline/` recreates the dataset from a fresh OSM harvest - for Europe or any other region (voltage floor, scope, projection, country handling, traction and grid frequency are all config).

```
python3 01_harvest_overpass.py --config config_europe.yaml   # ~4 h, 144 jobs, ~165 MB NDJSON
python3 02_build_topology.py   --config config_europe.yaml   # NDJSON -> GeoPackage pair
python3 03_validate.py         --config config_europe.yaml   # metrics, diagnostics, benchmark
```

Honesty note: it is a reimplementation of the documented method, not the original code - those scripts were never persisted - so a rebuild is methodologically equivalent rather than byte-identical. It was adversarially reviewed over four rounds, each of which found and fixed real defects. What makes it trustworthy is external, not internal: `benchmark_europe_ge220kv.csv` carries the published per-voltage >=220 kV route-km, and validating the shipped artefact against it reproduces the documented +3.0% exactly. Point `benchmark_csv` at the local TSO's published lengths for a new region.

The test suites are part of the deliverable: `fixture_test.py` (20 end-to-end checks), `gate_test.py` (22 threshold values plus 20 isolated gate fixtures), `validator_test.py` (each hard check proven to fire on bad data) and `mutation_test.py`, which breaks one gate at a time and requires a failure - 31 mutations, 31 caught. `README_pipeline.md` publishes the measured coverage gap rather than implying it away. One thing to know: run the validator against the shipped GeoPackages and the length-retention check fails on 73,404 of 91,094 spans, because v22 only recomputed lengths where the mismatch exceeded 10%. That is a property of the shipped data, not a pipeline fault; a fresh build passes.

## Licence and provenance

OpenStreetMap data, **ODbL 1.0**: attribution required, and share-alike propagates to derived databases - satisfied here by publishing the database itself under ODbL 1.0 (DOI [10.5281/zenodo.22043867](https://doi.org/10.5281/zenodo.22043867)). Method after Xiong et al. (2025), https://doi.org/10.1038/s41597-025-04550-7. Electrical parameters are typed or researched, never asset-register values: use for connectivity and screening, not for load flow you intend to defend.
