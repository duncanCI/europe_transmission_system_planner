# European grid topology build - session brief for independent review

Prepared 17 August 2026. Written to be read cold by someone who was not present. The purpose is to expose shortfalls, so the open problems are stated as plainly as the successes.

---

## 1. The base ask

Build a topologically connected geospatial representation of the electricity **transmission and sub-transmission** network of Europe including UK and Ireland. Derive what is usable from PyPSA-Eur, and where necessary recreate the methodology of the attached paper: Xiong, Fioriti, Neumann, Riepin and Brown (2025), *Modelling the high-voltage grid using open data for Europe and beyond*, Scientific Data 12:277. Output as a multi-layer GeoPackage.

Requirements added during the first exchange:

- Voltage scope 110 kV and above, full recreation of the method rather than a download.
- One layer per major asset class, cut by voltage: voltage × line, voltage × site. Attributes must carry the linkage and topology information.
- Output to a named folder on the user's machine.

## 2. Constraints that shaped the approach

- **The container had no network route to Overpass, Zenodo or Geofabrik.** All OSM data was harvested through browser automation against `overpass-api.de`, using an injected JavaScript harvester that gated on `/api/status` to avoid rate limiting. Two passes per country (≥100 kV, then 50-99 kV) plus a Europe-wide DC relation sweep: 111 NDJSON files, 165 MB, roughly 4 hours.
- **The shell tool caps at 10 minutes.** Every build stage runs detached under `setsid nohup`.
- **File transfer to the user's machine caps at 20 MB per file.** Outputs are `xz` compressed, split into 19 MB parts, transferred, reassembled and md5-verified on the far side.

## 3. What was built

Five stages, chained by `run_all.sh`, roughly 12 minutes end to end:

| Stage | Does |
|---|---|
| `load_clean.py` | Loads the harvested NDJSON, cleans tags per the paper's Tables 1-3, derives circuit counts and construction type |
| `build_geometry.py` | Builds shapely geometry, resolves relation/way duplication, splits AC/DC |
| `build_topology.py` | Chain merging, end joining, snapping, site building, clipping, node assignment, junction clustering, bus placement, connectors, transformers, components |
| `export_gpkg.py` | Electrical parameters from PyPSA standard line types, route tracing, labelling, GeoPackage export |
| `validate.py` | Benchmarks against paper Table 8 (AC route-km ≥220 kV) and Table 7 (38 commissioned DC relations) |

Two output files. `europe_grid_topology.gpkg` (185 MB, 55 layers) for map work; `europe_grid_graph.gpkg` (130 MB, 2 layers) for network analysis.

## 4. Current state

| Measure | Value |
|---|---|
| Network route length (AC) | 750,631 km conductor + 5,582 km synthetic connectors; 734,107 km at 50 Hz, 16,524 km at 16.7 Hz railway traction |
| Circuit length | 936,251 km |
| AC spans | 91,094 |
| Buses (node × voltage × frequency) | 75,315: 33,963 substation, 41,352 junction |
| Transformers (inferred, as lines) | 4,753 |
| DC links | 72 |
| Connected components (AC+transformer, PyPSA-consistent) | 3,847 (3,837 counting DC links as ties) |
| Route-km by synchronous area | Continental 77.4%, Nordic 11.0%, GB 3.9%, Ireland 1.2%, Sardinia 0.4%, 16.7 Hz traction 2.2%, residual fragments 4.9% |
| ≥220 kV route-km in the Continental component | 81.8% (GB, Nordic and Ireland hold most of the rest; they are separate synchronous areas, not gaps) |
| vs published ≥220 kV dataset | **+3.0%** |
| DC interconnectors matched | 38 of 38 |
| Self-loops / unresolved bus refs / invalid geometries | 0 / 0 / 0 |

Validation against paper Table 8, by voltage:

| kV | This build (km) | Published (km) | Delta |
|---|---|---|---|
| 220 | 80,399 | 79,130 | +1.6% |
| 225 | 26,807 | 26,012 | +3.1% |
| 236 | 18 | 18 | +2.1% |
| 275 | 4,781 | 4,756 | +0.5% |
| 300 | 4,343 | 4,255 | +2.1% |
| 330 | 19,544 | 18,123 | **+7.8%** |
| 380 | 36,377 | 34,610 | **+5.1%** |
| 400 | 100,458 | 98,066 | +2.4% |
| 420 | 5,012 | 4,951 | +1.2% |
| 500 | 430 | 230 | **+86.9%** |
| 750 | 4,114 | 4,002 | +2.8% |
| **Total** | **282,283** | **274,153** | **+3.0%** |

The comparison is on `length_conductor_m`, which excludes the synthetic perimeter-to-bus connectors, 5,582 km across the build, since the published dataset has no equivalent of those. The published column comes from the November 2024 OSM snapshot the paper used, 21 months older than this build's 2026-08-14 harvest, so part of the excess is OSM growth rather than a difference in method. This build also carries 682 under-construction spans, 3,165 km, in its totals; whether the published dataset does the same has not been checked.

Sub-transmission (50 Hz, below 220 kV) adds 451,780 route-km with **no published benchmark of any kind**, beyond a single cross-check that France comes to 101,039 km against RTE's published ~105,000 km. That cross-check is not like-for-like: 101,039 km is route length, whereas RTE's ~105,000 km is circuit length. RTE publishes the route measure separately as files de pylônes, about 81,000 km, so compared on the same basis this build sits well above RTE rather than slightly below it.

---

## 5. The follow-ups, in order, and what each turned up

Items 5.1 to 5.8 are defects the user found by eye in QGIS; 5.9 was a question that turned up a further defect in how construction type was represented, and 5.10 a simplification request. The pattern is worth noting for the review: **every one came out of the user's own inspection, none out of the validation suite.**

### 5.1 "Losing lots and lots of connectedness"

The paper's workflow truncates lines 500 m from a substation. Reproducing it left 535 m gaps with only 14.7% of line ends touching their bus. Abandoned truncation entirely: conductors are clipped only at real substation perimeters, with a straight connector from the perimeter to the bus point. Also added `start_point` / `end_point` substation names plus separate lat/lon fields, as requested. Coverage limit: 29.6% of spans resolve a named substation at both ends; 55% of buses are junctions, and a junction sits a median 2.5 km from the nearest substation.

### 5.2 "France is looking strangely sparse"

The 110 kV floor was wrong for western Europe. Sub-transmission is 110 kV in Germany, Poland and Austria, but 63/90 kV in France, 60 kV in Portugal and Denmark, 66 kV in Spain and Norway, 70 kV in Belgium, 50/65 kV in Switzerland. A 110 kV floor silently deleted those countries' entire regional networks - France came to 50,115 km against RTE's ~105,000. Floor lowered to 50 kV and both harvest passes re-run. France became 101,039 km.

### 5.3 "Bus points in the wrong place, substations fused"

Clustering on a 500 m buffer and taking the pole of inaccessibility of the union put 9.2% of bus points in open ground between substations, median 44 m out, worst 417 m, and fused up to 20 distinct substations into one node. Replaced with per-site buses placed inside the polygon, positioned on busbar centroids where OSM maps them. 100% of substation buses now sit inside their own site.

### 5.4 "Lines with many junctions on them - I think they're towers"

Snapping cut long lines at every contact point. `relation/6077873` came out as 172 spans of median 260 m with all 169 junctions at degree 2. Added two dissolves: spans of one element meeting at a degree-2 junction re-merge, and a node rule that dissolves a junction where every span meeting there is the same OSM element, it is not a terminus and it is not a substation. Elements producing more than 20 spans fell from 146 to 0 over the course of the session.

### 5.5 "Ends of the same line should snap together - prioritise connectedness"

Two findings. First, the 25° anti-parallel guard, added earlier to stop a duplicate circuit shredding the line beside it, ran *before* the end-to-end test. Two ends of one circuit meet collinear by nature, so the guard refused every genuine end-to-end join. Reordering took snapping from 18,986 ends to 62,659 and cross-component same-voltage bus pairs within 25 m from **848 to 0**.

Second, a dedicated end-to-end pass before clipping. Measured first: of 115,942 dangling ends, 55,578 of the 57,930 same-voltage pairs within 25 m lie within 250 m of a substation where the site catchment already resolves them. Away from substations there are 2,352 at 25 m and 5,672 at 150 m. Ceiling set at 150 m, below one tower span of 200-400 m.

A first attempt at extended junction clustering made things worse: it chained clusters past the 600 m width limit, the existing burst rule split each into one node per endpoint, and components went from 3,820 to 7,731. Fixed by refusing unions that would exceed 250 m cluster width and re-clustering over-wide clusters at 10 m instead of exploding them.

### 5.6 "Still random splits mid-line"

A 225 kV RTE circuit in Normandy appeared as hundreds of tower-length fragments lying on top of the route. Cause: `merge_chains` fused `relation/16861592` with `relation/16861593` - the two circuits of one double-circuit line, on the same pylons, with identical voltage, circuit count and location, both terminating at the same substation. The merged geometry ran out 49 km and back along the same coordinates. Every later set operation then noded that self-overlapping line at each shared vertex, producing 529 fragments in the internal layer.

2,892 of 11,460 candidate chain nodes had this shape. Fix: the two conductors' outward directions at the shared node must be roughly opposite, a turn of 60° or less. The angle distribution has two modes, 6,424 nodes under 26° and 556 above 154°, but the other 4,480 of the 11,460 sit between them, and the 60° cut falls inside that band, so its position is a judgement call rather than a natural break. Worst element fragmentation fell from 757 fragments to 13.

### 5.7 "Loose ends where there should be a node at the branch and at its end"

At Poste électrique d'Écrainville both 90 kV circuits stop 159 m short of the fence, and two 159 m conductors carry on from that common point into the yard. The 250 m site catchment pulled all four ends onto the site, which made both short conductors self-loops. They were deleted from the network and left in the internal layer as orphans, while two synthetic 174 m connectors were drawn straight over the top of them. Across the build this had deleted 16,882 spans and 2,233 km, including a 1.5 km 400 kV run.

Two rules. A point where several conductors end outside the fence becomes a junction rather than the substation, provided one of the spans meeting there has its other end *at* the fence so it provably carries the connection into the yard. And a span still landing both ends on one site keeps its far end freed when that end is 50 m or more out.

The first version of the anchoring condition required only that the site keep one attachment. That was too weak: a site with three lines each stopping short at a different point had all three diverted and only one restored, pushing components from 3,345 to 3,850.

### 5.8 "Routes pass through a sub and straight-line to another nearby one"

`build_sites` fused two substation polygons whenever a conductor under 1 km merely *touched* both. Every real link between neighbouring substations does exactly that. Poste électrique de Levallois and Poste électrique de Perret, 397 m apart and differently named, became one site, so the 225 kV route from Cormeilles ended at the Levallois compound and was drawn to the Perret bus with a 476 m straight connector, on top of the three real 225 kV cables between them. 1,235 of 2,805 multi-polygon sites had spread past 300 m, 99th percentile 1,075 m.

Fix: the conductor must run no more than 50 m outside the two polygons, and the polygons must be within 250 m. Connectors over 400 m fell from 880 to 348, over 1 km from 44 to 8.

A name-conflict test was also tried on the 150 m proximity merge and **reverted**: it blocked 1,488 merges, 983 of them with no conductor between the two polygons, so those sites came apart and their transformers with them, costing 0.28 points of ≥220 kV route-km in the largest component. It now applies only on the conductor path.

### 5.9 "Why is there a split here, and is overhead vs cable in the data?"

The split was correct. At West Boldon a 273 m underground cable runs from the substation to a junction, and 1,418 m of overhead line continues from there. The node is the cable sealing end.

Construction type was present but badly represented. `underground` was a boolean derived from the `location` and `tunnel` tags alone, ignoring `power=cable`, so 1,525 km of cable read as overhead. Worse, 205,188 route-km carrying `power=circuit` or no power tag at all were reported as not-underground, which reads as overhead for a quarter of the network.

Replaced with `construction_type` (five states) and `construction_source` (which tag decided it). Route relations carry no power tag of their own but their member ways do, so type is taken from the members for 10,540 elements. A route that is part cable and part overhead is `mixed` rather than forced to one answer. Unknown fell from 205,188 km to **2,116 km, 0.3%**.

### 5.10 "As simple as possible, no duplication in fields"

Line fields cut from 48 to 36, site fields from 17 to 15, file from 208 MB to 185 MB. Removed only what is exactly recoverable from another field: `voltage_v`, `station0`/`station1`, `underground`/`submarine`, `length_m`, `s_nom_n1_mva`, `is_cross_border`, `elem_id`, `name`, `cables`/`wires`, `internal_to_station`.

---

## 6. Where to look for shortfalls

This section is the point of the brief. Everything below is either unresolved, weakly evidenced, or a judgement call that a reviewer should challenge.

### 6.1 Validation drift

The ≥220 kV total moved **+2.3% → +3.0% → +3.2% → +3.3%** across the session. Each step was justified as reinstating conductor that earlier versions were deleting, and the internal (deleted) layer did fall from 7,055 km at v14, the earliest figure recorded, to 4,336 km at v20. But nothing independently confirms the reinstated geometry is real conductor rather than accumulated synthetic length. **A reviewer should test whether the drift is recovery or inflation**, for example by comparing `length_conductor_m` against raw OSM way length per element on a sample.

Snapping and bridging deliberately add geometry OSM does not carry: up to 150 m per end-to-end join, 3,321 joins. That is bounded but not zero.

### 6.2 Unexplained per-voltage deltas

330 kV runs **+7.8%** and 380 kV **+5.8%** against the published dataset, well outside the +3.3% total. Neither has been investigated. 500 kV runs **+86.9%** on 6 spans, all in eastern Ukraine, and they are real: Ukrenergo commissioned the 500 kV Kreminska substation into the Donbaska-Donska 500 kV line in 2020, and the Donbaska-Peremoha 500 kV line is named in the grid development plan. The level is marginal there (~375 route-km, secondary-sourced) and the assets sit in Donetsk/Luhansk oblast, war-affected since 2022, so treat operational status as unknown. The two Italian spans previously at this level were an OSM keystroke error (132 kV lines tagged 500000); the v21 patch corrects them.

### 6.3 Sub-transmission has no benchmark

451,780 route-km, 60% of the network, is validated against nothing: the one country-level cross-check on France is not like-for-like, and on the same basis the build runs well above RTE. There is no published inventory to test the 110 kV or 132 kV layers against. Any claim about sub-transmission completeness is unsupported.

### 6.4 Thresholds are measured but arguable

Every threshold below was chosen from a measured distribution and documented, but each is a judgement call, and several were tuned while watching the same metrics they affect. That is a real risk of overfitting to the specific defects the user happened to notice.

| Constant | Value | What it decides |
|---|---|---|
| `SITE_MERGE_TOL` | 150 m | Two polygons are one site |
| `SITE_CATCHMENT` | 250 m | An end terminates at a site |
| `SITE_FENCE_TOL` | 30 m | An end is "at the fence" |
| `FREE_END_MIN` | 50 m | Approach conductor vs switchyard jumper |
| `BRIDGE_OUTSIDE_MAX` | 50 m | Conductor length allowed outside two compounds |
| `BRIDGE_GAP_MAX` | 250 m | Two compounds can still be one site |
| `JUNCTION_TOL` | 25 m | Endpoints merge into a junction |
| `JUNCTION_EXT` | 150 m | Extended junction reach |
| `EE_TOL_FREE` | 150 m | End-to-end gap closed away from a substation |
| `EE_MOVE_MAX` | 50 m | Tips moved rather than bridged |
| `EE_COS_MIN` / `CHAIN_COS_MAX` | ±0.5 (60°) | Two conductors are continuing rather than folding back |
| `MAX_CLUSTER` / `EXT_MAX_CLUSTER` | 600 m / 250 m | Junction cluster width limits |
| `DC_MAX_CONVERTER` | 10 km | Converter left unattached |

The 60° angle cut appears in three separate places with the same value. That consistency is by design, but nobody has tested whether one of the three wants a different number.

### 6.5 Metrics that were traded against each other

Connectivity and completeness pull in opposite directions, and the session repeatedly chose completeness. Components rose from 3,345 (v14) to 3,741 (v20) as ~20,000 previously-deleted spans came back. The argument is that most of the new components are substations that had nothing attached before, so they contributed neither components nor route-km, and route-km in the largest component held flat at 95.9%. **That argument was asserted rather than proven**; a reviewer should check whether the extra components are genuinely new content or genuine fragmentation.

The name-conflict test was reverted on the proximity path for the same reason. Most of its calls looked correct on inspection (an Umspannwerk beside an Umformerwerk, two operators sharing a fence), so the revert may have preserved 983 fusions that are physically wrong, in exchange for connectivity.

### 6.6 Things that are inferred and never observed

- **Transformers.** 4,816 of them, created between each adjacent voltage pair at a site on a cascade assumption. A direct 400/132 bank at a three-voltage site is missed. A voltage pair present without a transformer between them is invented. OSM carries no usable transformer data.
- **Electrical parameters.** `r_ohm`, `x_ohm`, `s_nom_mva`, `i_nom_ka` come from PyPSA standard line types matched by voltage, not from asset registers. Never validated against anything.
- **Circuit counts.** Frequently derived from `cables`/3 or `wires`/3, or assumed 1. `circuits_source` records which, but the derived values are unverified.
- **The `mixed` construction type.** 1,602 spans, 19,467 km. Newly introduced this session and not checked against any ground truth.

### 6.7 Process weaknesses

- **Every defect was surfaced by the user, none by the test suite.** `validate.py` checks two published tables plus integrity invariants. It never once caught a defect the user later reported. The four diagnostics that did find things (per-element internal-fragment count, cross-component bus pairs, internal-segment distance to its site polygon, multi-polygon site extent) were written ad hoc during debugging and are not part of the automated run.
- **No unit tests.** Geometry rebuilds are guarded by a per-element length check, which was added only after one version silently dropped 60,000 route-km and swung validation from +2.4% to -6.7%.
- **Three earlier geometry rebuilds silently lost network** and looked fine on a map. The length guard now catches that class, but the incident rate suggests other silent-loss paths may remain.
- **The build depends on a single Overpass snapshot taken 2026-08-14** through browser automation. It is not reproducible from the container, and re-harvesting takes about 4 hours.
- **One delivery failed silently.** The device bridge dropped mid-transfer, two rebuilds' worth of fixes never reached the user's disk, and the next round of review was conducted against a stale file before anyone noticed.

### 6.8 Licence

ODbL 1.0, and two obligations rather than one. Attribution (s4.3): anything published from this data - screening study, map, carousel, post - must carry a notice that the content came from OpenStreetMap and is available under the ODbL. (C) OpenStreetMap contributors, with a link to openstreetmap.org/copyright, is the accepted form. Share-alike (s4.4) does propagate to the .gpkg files, which are derivative databases. A produced work built from them is not itself a derivative database (s4.5), but publicly using that produced work counts as publicly using the derivative database behind it (s4.4c), and s4.6 then requires offering recipients the database or a file of all alterations. Publishing a study rather than shipping the .gpkg does not sidestep that. Unresolved, and it wants a legal answer before any commercial use. (Since resolved for the dataset itself: the derivative databases publish under ODbL 1.0 on Zenodo, which satisfies s4.4/s4.6 for produced works built on them.)

### 6.9 Corrected in the data, 2026-08-18 (v21)

The figures in this brief now describe v21. A post-review patch fixed five provable misclassifications in the shipped GeoPackages: the Norfolk Vanguard/Boreas onshore connection (61 km, +/-320 kV HVDC per Vattenfall's contract award) and the Berwick Bank Cambois export cable (HVDC, 525 kV design-envelope max) moved from the AC layers to `dc_link`; the two Italian "500 kV" spans were re-tagged 132 kV (OSM keystroke error - sibling ways of the same line are tagged 50 kV, and Terna operates no 500 kV AC); the Hornsea One offshore export span was re-tagged from 254 kV to 220 kV (Ofgem's OFTO asset schedule), which reconnected it to its own onshore cable in the main component. Two out-of-scope `dc_link` rows were deleted (a Saudi Arabia-Egypt link and a Belarusian 110 kV line mis-tagged as DC), the Caithness-Moray and Shetland links were attached to the Spittal converter bus (their geometry already ended there), and the remaining 16 legitimately unattached DC ends now carry explanatory `qa_flags`. Full row-level evidence in `manual_corrections.csv`; pre-patch files in `_backup_v20/`; patch script in `_xfer/patch_v21.py`. Not fixed, because it cannot be from here: 55.9% of spans (380,306 km) carry `frequency_assumed_ac` - the AC/DC split is untagged in OSM for over half the network, and the two reclassified cables above were caught by name, not by tag.

### 6.10 Corrected in the data, 2026-08-18 (v22) - frequency separation and PyPSA fixes

The figures in this brief now describe v22. Frequency is a first-class dimension like voltage: a live OSM scrape (6,346 elements, run through the owner's browser; `scrape_PROVENANCE.md`) classified 1,397 spans / 16,524 km as 16.7 Hz railway traction (DE 10,199, AT 2,382, SE 1,914, CH incl. border spans 1,764, NO 185 km), moved them to `line_<kV>_16_7Hz` layers, severed 235 shared buses, and deleted 56 inferred transformers that welded the two synchronous systems. CH and SE totals agree with SBB's ~1,800 km and Trafikverket's ~1,700-2,000 km - external validation; DE and AT run above DB's ~7,800 and OBB's ~1,000 km because ours is route-km over every mapped way including joint corridors. Every frequency value carries `frequency_source`; 291 shared-tower spans tagged 50;16.7 are kept wholly at 50 Hz and flagged (their traction circuits are absent from the traction layers and their 50 Hz capacity is overstated by the shared circuits - documented residual). Also in v22: 314 overseas-territory spans removed (New Caledonia, Reunion, Antilles, Guiana, Canaries, Madeira, Azores - administrative-area harvest leak); 489 duplicate circuit-row groups collapsed (505 rows, ~2,894 km of double-counted route; 14 rows remain flagged ambiguous); 125 span lengths recomputed from geometry with impedances rescaled (5 conflicts flagged, not forced); `component` redefined over lines+transformers only, matching PyPSA's passive partition exactly and deterministic across runs, with `component_incl_dc` kept separately. `not_in_main_component` now means "outside the Continental synchronous area" - GB, the Nordic area, Ireland, Sardinia and all traction are correctly outside it, so the flag covers 22,241 spans where v21 had 7,529; that is a definition change, not a regression. A PyPSA 1.2.4 acid test passes end to end: strict consistency, 3,847 sub-networks matching the component column exactly, zero sub-networks mixing frequency, linear power flow solved on the 9,955-bus >=220 kV backbone (KCL residual 4e-10 MW) and on the largest traction island. Adversarially reviewed twice (one NO_GO enforced, then GO); artefacts: `_xfer/patch_v22.py`, `_xfer/freq_nonstd_real.csv`, `v22_stats_sidecar.json`, `_xfer/acid_test_pypsa.py`, `acid_report_v22.json`, pre-patch pair in `_backup_v21/`.

### 6.11 Corrected in the data, 2026-08-18 (v23) - transformer parameters and DC ratings

Attribute-only closure of the two PyPSA-readiness gaps (geometry, rows, layers and the graph
GeoPackage untouched). All 4,753 transformers carry `s_nom_mva`/`x_pu`/`r_pu` (per-unit on own
s_nom) from a 6-band typing rule - x and r sourced from pandapower v3.1.2 standard types and the
PyPSA-Eur default where matched, `inferred:` labelled where extrapolated; s_nom is inferred
throughout (assumed bank counts) and says so. A second column `s_nom_pypsa_eur_mva` ships the
convention PyPSA-Eur actually uses (incident-line-capacity rule; their 2,000 MVA config default is
dead code in the OSM workflow) - swapping columns without recomputing x_pu rescales impedances
(median 5x, max 187x), warned in `v23_typing_rule` inside the gpkg. 99 near-unity-ratio rows
(380/400, 130/132...) flagged as probable voltage-tagging artefacts, bus-merge deferred to v24.
All 72 DC links researched per-link: 67 rated with a public source (gross 56,066 MW; 52,966 MW
excluding the three rows flagged `exclude_from_capacity_sums` - the IFA-2000 umbrella, one SACOI2
series section, the inferred Spittal tail), 5 honest unknowns of which two are sourced AC lines
mis-tagged frequency=0 in OSM (reclassification deferred to v24, they touch geometry). Series
sections carry full scheme rating; parallel poles split published nameplates; underivable splits
are `inferred:` in `p_nom_source` itself (Vyborg, SACOI2 sections, pole identities). `status` is
commissioning state, not availability (Skagerrak 2's live cable outage sits in `qa_flags`).
Adversarially reviewed twice (round 1 NO_GO: Konti-Skan pro-rata 385/330 exceeded published pole
nameplates - now 350/300 sourced; an EHV s_nom presented as sourced - relabelled inferred; SACOI
double-counting - one row excluded; 23 of 25 independent rating spot-checks agreed). Artefacts:
`_xfer/patch_v23.py`, `dc_link_ratings.csv`, `transformer_typing_rule.csv`, `v23_stats_sidecar.json`,
README section 13.

---

## 7. Questions worth putting to a reviewer

1. Is the +3.3% drift recovery of real conductor, or accumulated synthetic length? What would prove it either way?
2. What explains 330 kV at +7.8% and 380 kV at +5.8% when the total is +3.3%?
3. Are the extra components from v14 to v20 new content or new fragmentation?
4. Which of the 13 thresholds is most likely overfitted to the specific cases the user happened to look at?
5. Was reverting the name-conflict test on the proximity merge the right trade, given 983 probable mis-fusions were preserved to protect 0.28 points of connectivity?
6. What would a validation suite need to contain to have caught any of the nine defects in 5.1 to 5.9 before the user saw them?
7. Is a 250 m site catchment defensible at all, given it caused two separate classes of defect?
