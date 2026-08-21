# Rebuild pipeline - OSM to a multi-layer grid topology GeoPackage

Three scripts recreate the dataset in `..` from a fresh OpenStreetMap harvest, for
Europe or any other region. Everything region-specific is config: voltage floor,
scope, projection, country attribution, traction handling, Overpass endpoints.

```
python 01_harvest_overpass.py --config config_europe.yaml     # OSM  -> NDJSON
python 02_build_topology.py   --config config_europe.yaml     # NDJSON -> GeoPackage pair
python 03_validate.py         --config config_europe.yaml     # GeoPackage -> metrics + diagnostics
```

## Read this first

**This is a reimplementation, not the original code.** The scripts that built the
shipped v20 dataset were never persisted. These were written against
`../supporting/README_methodology.md` - all fourteen numbered design decisions,
every documented threshold, the pitfalls table - and reviewed clause by clause
against it. A rebuild is therefore **methodologically equivalent, not
byte-identical**: thresholds match the documentation, but tie-breaking order,
cluster medoid selection and floating-point accumulation differ, so span counts
and route-km will land close to but not exactly on the published figures.

Acceptance test is external, not self-comparison. `benchmark_europe_ge220kv.csv`
ships the published per-voltage >=220 kV route-km (paper Table 8) and
`config_europe.yaml` wires it in, so `03_validate.py` prints a per-voltage and
total `delta_pct` on every run. Against the accepted v23 artefact it reproduces
the documented +3.0% exactly. A fresh Europe build within roughly +/-5% overall,
with no single voltage past about +10%, reproduces the reference; the benchmark
file carries those criteria and the two expected outliers (330 kV +7.8%, 500 kV
+86.9% on 236 absolute km) in its own header. For a new region, point
`benchmark_csv` at the local TSO's published circuit lengths - every other check
in the package is internal, so this is the only one that says a build is RIGHT
rather than merely self-consistent.

What the pipeline does and does not carry. It builds v23-shaped output directly:
the six-band transformer typing rule with its provenance labels and the
`v23_typing_rule` table, the DC rating columns (`p_nom_mw`, `status`,
`p_nom_source`, filled from `dc_ratings_csv` where you supply one and left
`unknown` where you do not), the v22 scope clip, the v22 duplicate-corridor
collapse, and the two v21 DC reclassifications listed in `config_europe.yaml`.
Do **not** re-run `patch_v23.py` on a fresh build - those columns are already
there.

Genuinely not attempted here, and still living in `../supporting/_xfer/`: the
other three v21 corrections (the Italian 500 kV keystroke error, the Hornsea 254
kV retag, the two out-of-scope DC deletions), and the researched per-link DC
rating evidence itself - the pipeline joins a ratings CSV, it does not do the
research. Frequency classification is part of the normal harvest (the OSM
`frequency` tag), not the separate CSV scrape v22 used.

## Dependencies

Python 3.11+, plus `geopandas`, `pyogrio`, `shapely` (2.x), `pyproj`, `pandas`,
`pyyaml`. Harvest and build use nothing else - no PyPSA, no network access at
build time.

```
pip install geopandas pyogrio shapely pyproj pandas pyyaml
```

The harvest needs ordinary internet access to Overpass mirrors. It will not run
inside a sandbox that blocks OSM hosts; harvest on a normal machine and copy the
NDJSON directory across if that is your situation.

## The three stages

**`01_harvest_overpass.py`** - chunked, resumable harvest to NDJSON. Two voltage
passes per scope (`>=high_pass_floor_kv`, then `voltage_floor_kv`..floor-1), a
substation pass and a DC sweep. `areas` harvests one admin area per query;
`bboxes` splits into `chunk_deg` tiles. Mirrors rotate on failure with capped
exponential backoff and a polite gap between queries. Chunks already on disk are
skipped, so an interrupted harvest resumes. `--dry-run` prints the query plan
without touching the network; `--only hv|sub|substation|dc` runs one pass.

Europe is roughly 4 hours and ~165 MB of NDJSON. Be a good Overpass citizen: keep
`polite_gap_s` at 8 or higher, and do not raise `max_attempts` to hammer a mirror
that is refusing you.

**`02_build_topology.py`** - the substance. Stage order:

```
load/clean -> geometry -> chain merge -> end-to-end join -> snap/split -> sites
-> clip -> end assignment -> junction clustering -> buses -> self-loop sweep
-> dissolve -> self-loop sweep -> connectors -> transformers -> components
-> electrical parameters -> export
```

Every documented threshold is a named constant at the top of the file with the
section it came from, so they can be audited in one screen: `SITE_MERGE_TOL_M`,
`SITE_CATCHMENT_M`, `SITE_FENCE_TOL_M`, `FREE_END_MIN_M`, `BRIDGE_OUTSIDE_MAX_M`,
`BRIDGE_GAP_MAX_M`, `JUNCTION_TOL_M`, `EE_TOL_FREE_M`, `MAX_CLUSTER_M`,
`PARALLEL_REJECT_DEG`, `LENGTH_RETENTION_MIN` and the rest.
Each of the fourteen design decisions is cited by number at its implementation
site - `grep -n "decision 4" 02_build_topology.py` lands on the fold-back gate.

Output is the same pair the dataset ships: `<region>_grid_topology.gpkg` (per
voltage `line_<kV>` and `site_<kV>` layers, `line_<kV>_16_7Hz` where traction is
enabled, `junction_node`, `line_internal_to_station`, `dc_link`, `transformer`,
`station_cluster`, `substation_footprint`) and `<region>_grid_graph.gpkg`
(`ac_line_all`, `site_all`), plus `build_stats.json`.

**`03_validate.py`** - integrity checks plus the four diagnostics that caught
nearly every historical defect:

1. per-element fragment count (>20 spans from one OSM element means the geometry
   was fused or self-overlapped upstream - this found the fold-back bug)
2. cross-component same-voltage bus pairs within 25 m, which must be zero (above
   zero means a gate is refusing a real connection)
3. distance from each internal segment's ends to its site polygon (a systemic
   shift outward is network being deleted, not switchyard jumpers)
4. multi-polygon site extent and long connectors (a site wider than ~300 m is
   usually two substations wrongly fused; the long connector is the symptom)

It exits non-zero on any of them, plus length retention and the integrity group
(unresolved bus references, self-loops, null geometries, transformers without
parameters, non-positive line parameters).

Two of these quantities are legitimately non-zero in a good dataset, so their
limits are **calibrated against the accepted Europe v23 build** rather than set to
zero - failing at zero would reject the reference itself - and deliberately set
*below* the magnitude of the historical defect, so the regression they exist to catch
fails the build instead of shipping green:

| Check | v23 reference | Pre-fix defect | Limit |
|---|---|---|---|
| d1 elements over 20 spans | 0 | 146 | 0 |
| d3 p95 internal-end distance | 20.3 m (225,846 ends) | - | 50 m |
| d4 multi-polygon sites over 1 km | 22 of 2,321 = 0.95% | 48 of 2,805 = 1.71% | 1.4% |
| d4 connectors over 1 km | 8 of 91,094 = 0.009% | 44 = 0.048% | 0.015% |

The 300 m site-extent share is **reported, not hard-checked**: 41.7% in the accepted
build against 44.0% pre-fix, which do not separate, so any limit between them would
be knife-edge and would fail honest builds. The two distribution limits apply only
once the sample is large enough to mean something, so a small adversarial fixture is
reported rather than judged.

**One thing the shipped artefact itself fails.** Run `03_validate.py` against the
shipped v23 GeoPackages and the length-retention check fails: 73,404 of 91,094 spans
have drawn geometry disagreeing with their stored lengths by more than 0.1%, worst
64.4%. That is not a fault in this pipeline - its own output passes - it is a
property of the shipped data, because the v22 patch only recomputed a span's length
where the mismatch exceeded 10%. Expect that one failure when validating the shipped
files, and none when validating a fresh build.

## Config reference

| Key | Meaning |
|---|---|
| `region_name` | Prefix for output filenames |
| `voltage_floor_kv` | **The most consequential parameter.** Lowest voltage kept. No default - a missing floor is an error, not a guess |
| `high_pass_floor_kv` | Boundary between harvest pass 1 and pass 2 (default 100) |
| `areas` / `bboxes` | Scope. `areas` = ISO codes resolved to admin areas; `bboxes` = `[south, west, north, east]` lists, tiled at `chunk_deg` |
| `scope_bbox` | Post-harvest clip. Use it when an area harvest pulls in overseas territory |
| `standard_voltages_kv` | Voltages a raw tag snaps to |
| `layer_voltages_kv` / `layer_min_spans` | Which voltages get their own layer; the rest go to `line_other_kV` |
| `metric_crs` | Metre CRS for every distance gate. EPSG:3035 Europe, 3577 Australia, 5070 CONUS. Storage stays EPSG:4326 and lengths stay haversine (R = 6371.0088 km) regardless |
| `country_source` | `polygons` (spatial join, the only one that makes cross-border attribution trustworthy), `osm_tag`, or `none` |
| `country_polygons` / `country_field` | Polygon file and its label column. The field is opaque - a state or NEM-region column works exactly like ISO_A2 |
| `traction.*` | 16.7 Hz separation. `enabled: false` for any region without a separate-frequency railway system. Classification is OSM `frequency` tag first, operator inference second, and the operator inference is gated to `max_voltage_kv` and `countries` because an EHV line owned by a railway is a supply line, not traction |
| `grid_frequency_hz` | Public-network frequency, default 50. Top level, because a region can have no traction system and still not be 50 Hz |
| `dc_ratings_csv` | Optional CSV of per-link DC ratings to join (`fid`/`osm_id`, `p_nom_mw`, `status`, `p_nom_source`). Absent means every link ships `unknown` |
| `benchmark_csv` | Per-voltage published route-km for the acceptance test. `benchmark_europe_ge220kv.csv` ships for Europe; supply the local TSO figures for a new region |
| `contact` | Your email, sent in the harvest User-Agent. Overpass etiquette |
| `overpass.*` | Endpoints, tiling, timeout, retry, politeness |
| `dc_reclassify_osm_ids` | Elements to force onto the DC layer where OSM tags an HVDC cable as AC |

`config_europe.yaml` reproduces the shipped build. `config_australia_example.yaml`
is a worked non-Europe example - a documented starting point, with the two
decisions that need local judgement (voltage floor, layer voltage list) called out
in its comments.

## Porting to a new region - the five questions

1. **What is sub-transmission here?** Set `voltage_floor_kv` to the level below
   which you do not care. Getting this wrong silently deletes whole networks; it
   is the one parameter worth researching before running anything.
2. **What is the right metre CRS?** An equal-area projection for the region. All
   the distance gates (150 m, 250 m, 30 m, 50 m) are metres in this CRS.
3. **Is there a separate-frequency railway system?** Europe has 16.7 Hz in
   DE/AT/CH/SE/NO. Most of the world does not - set `traction.enabled: false`.
4. **Is the public network 50 Hz?** Set `grid_frequency_hz` (60 for the
   Americas, Saudi, western Japan, parts of Brazil). This is independent of
   whether traction separation is on.
5. **Do you need country or state attribution?** If yes, supply polygons; if no,
   `country_source: none` is the honest answer and `is_cross_border` becomes
   meaningless rather than wrong.

## Tests

```
python3 tests/fixture_test.py     # 20 end-to-end checks on a synthetic fixture
python3 tests/gate_test.py        # 22 threshold values + 20 isolated gate fixtures (43 checks)
python3 tests/validator_test.py   # proves each validator hard check FIRES on bad data
python3 tests/mutation_test.py    # proves the three suites above actually bite
```

`fixture_test.py` builds a 35-element synthetic fixture through stages 2 and 3 and
asserts the fold-back trap refused, head-on chain merge still accepted, junction tee
survives, sites not over-fused, Ecrainville fence rules, approach conductors
retained, end-to-end join, cable-overhead transition, traction separated, DC link
handled, transformer typing rule (bands, sources, coupling warning), PyPSA parameter
conventions, the exact shipped field-name lists, layer set, length retained, and
connectors stored separately.

`gate_test.py` exists because an earlier version of this suite reported 20/20 with
eight documented gates reverted - including the site-fusion distance behind the
Levallois/Perret defect and both `n_circuits` terms in the electrical formulas. It
pins the **value** of all 23 documented thresholds and exercises the gates on both
sides of their boundary: fusion refused when a conductor runs past 50 m in the open
and accepted when compounds are close; a near-parallel mid-conductor contact
rejected while a perpendicular tap is accepted; a substation node never entering the
dissolvable set; a bus staying inside a C-shaped compound whose centroid is outside
it; an unanchored group outside a fence not diverted; a legally-chained 288 m cluster
staying one junction; duplicate corridors collapsing while mixed-voltage
shared-pylon pairs and partial member overlaps do not; and both electrical
conventions end-to-end.

`validator_test.py` injects one defect at a time into a clean build - 30 spans from
one element, internal segments dragged 5 km from any site, 150 fused wide sites, 6,000
spans carrying 60 long connectors, a dangling bus reference - and requires the validator to exit non-zero naming that
check. Two hard checks were once inert (one read a key the diagnostic never returned,
the other resolved its span count from two non-existent keys); this is what stops
that recurring.

`mutation_test.py` makes "the suite catches a reverted gate" a tested property: it
copies the package, mutates one constant or block, runs the suites, and requires a
failure. **31 mutations, 31 caught**, including all fourteen design decisions'
load-bearing logic, the duplicate-collapse key, the schema field names, the harvest
voltage banding, the DC sweep scope, grid frequency, and all three validator hard
checks. Run it after touching any threshold.

**Measured coverage limit, with the measurement's own limits stated.** Each
threshold was tested by editing the constant **and** its entry in `gate_test.py`'s
documented-value table together, then running all three suites - only behaviour can
catch that. Cover is **direction- and magnitude-dependent**, so read the lists with
the perturbation in mind rather than as a binary property.

Behaviourally pinned in both directions tested: `SITE_MERGE_TOL_M`,
`SITE_CATCHMENT_M`, `SITE_FENCE_TOL_M`, `BRIDGE_OUTSIDE_MAX_M`, `COS_CONTINUE_MAX`,
`EXT_MAX_CLUSTER_M`, `EE_TOL_FREE_M`, `LENGTH_RETENTION_MIN`.

Pinned in one direction only - the fixture catches a large move but not a small one,
and for these two the *un*caught direction is the one the harness calls the defect:
`FREE_END_MIN_M` (50 -> 200 caught, 50 -> 5 survives) and `PARALLEL_REJECT_DEG`
(25 -> 100 caught because it crosses the perpendicular-tap fixture, 25 -> 60 and
25 -> 89 survive).

Value-table cover only - a coordinated edit of constant and table would pass:
`BRIDGE_GAP_MAX_M`, `JUNCTION_TOL_M`, `JUNCTION_EXT_M`, `JUNCTION_MOVE_MAX_M`,
`MAX_CLUSTER_M` (600 -> 60 is caught, 600 -> 2000 is not),
`CROSS_COMPONENT_MERGE_M`, `EE_MOVE_MAX_M`, `DC_MAX_CONVERTER_M`,
`DC_FAR_CONVERTER_M`, `FRAGMENT_FLAG_COUNT`, `LONG_CONNECTOR_M`,
`TRANSFORMER_RATIO_ARTEFACT`.

Two earlier versions of this section were wrong in opposite ways: the first listed
eleven names from judgement rather than measurement, and the second measured with a
single x4 upward perturbation and reported the result as binary. The lists above
merge both measurement passes. Re-measure after adding a fixture; do not edit the
lists by hand. Closing the rest is one fixture each, in rough order of consequence:
`BRIDGE_GAP_MAX_M` (the other half of decision 5), the small-move direction of
`FREE_END_MIN_M` and `PARALLEL_REJECT_DEG`, the clustering reach constants, then the
reporting-only flags, which change what is flagged rather than what is built.

## Schema note

The output carries **37 line fields and 16 site fields** (`site_all` adds
`severed_from` and `component_incl_dc`, so 18), matching the shipped v23 files
column for column. `../supporting/README_methodology.md` says "36 line fields, 15
site fields": that figure is wrong and has been since v20, whose files carry 35
and 14 - v22 added `frequency_hz` and `frequency_source` to both. The tests
assert the shipped 37/16, not the documented figure.
