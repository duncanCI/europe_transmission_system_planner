# European Transmission and Sub-Transmission Network

Topologically connected geospatial model of the electricity network of Europe including UK and Ireland, at 50 kV and above.

Built 17 August 2026 from OpenStreetMap (v21+v22 corrections and v23 electrical parameters applied 18 August 2026 - sections 11-13, `manual_corrections.csv`, `v23_stats_sidecar.json`, `dc_link_ratings.csv`, `transformer_typing_rule.csv`), using the methodology of Xiong, Fioriti, Neumann, Riepin and Brown (2025), *Modelling the high-voltage grid using open data for Europe and beyond*, Scientific Data 12:277, and the PyPSA-Eur workflow it documents.

---

## 1. What this is, and what it is not

The published PyPSA-Eur dataset covers AC 220 to 750 kV plus DC. It excludes sub-transmission. This build lowers the floor to 50 kV and re-runs the methodology.

The floor is 50 kV rather than 110 kV because sub-transmission is not one voltage across Europe. It is 110 kV in Germany, Poland, Austria and most of central and eastern Europe, but **63 and 90 kV in France, 60 kV in Portugal and Denmark, 66 kV in Spain and Norway, 70 kV in Belgium, and 50/65 kV in Switzerland**. A 110 kV floor captures those countries' transmission networks and silently deletes their entire regional networks: France came out at 50,115 km against RTE's published ~105,000 km. At 50 kV France is 101,039 km.

So the 132 kV networks of England and Wales, the 110 kV networks of Germany, Poland and the Nordics, the 150 kV networks of Italy and Greece, and the 63/90 kV network of France are all present.

**It does not do these things:**

- It is not survey grade. Geometry is OSM way geometry, typically accurate to tens of metres, not centimetres.
- It is not a validated electrical model. Line impedances come from standard conductor types matched by voltage, transformer parameters from a banded typing rule and DC ratings from per-link public sources (section 13) - not from asset registers. Use it for connectivity and screening, not for load flow you intend to defend.
- It is not complete. OSM coverage of sub-transmission varies by country, and there is no published inventory to check the 110 kV layer against.
- Circuit counts are frequently derived rather than tagged. See section 5.

## 2. Coverage

36 ENTSO-E countries: AL, AT, BA, BE, BG, CH, CZ, DE, DK, EE, ES, FI, FR, GB, GR, HR, HU, IE, IT, LT, LU, LV, MD, ME, MK, NL, NO, PL, PT, RO, RS, SE, SI, SK, UA, XK. Cyprus, Iceland and Turkey are excluded, matching the source paper.

| Measure | Value |
|---|---|
| Total route length (network) | 762,346 km |
| Total circuit length | 947,386 km |
| In-substation conductor, held separately | 4,336 km |
| AC spans (network) | 91,915 |
| In-substation segments | 113,213 |
| Buses (node x voltage) | 75,411 |
| Substation buses / junction buses | 33,979 / 41,432 |
| Transformers (lines between voltage buses) | 4,816 |
| DC links | 72 |
| Connected components | 3,741 |
| **Route-km in largest connected component** | **95.9%** |
| **>=220 kV route-km in largest component** | **98.9%** |

Transmission (>=220 kV, 50 Hz) is 282,283 route-km. Sub-transmission (50 Hz, below 220 kV) is 451,780 route-km, and is the part with no published benchmark.

Connectivity is quoted by route-km. Counting nodes instead gives 86%, but that weights a 200 m dead-end spur the same as the entire 400 kV backbone, so it understates how connected the network is. The second-largest component is 719 km.

The residual 4.1%, some 31,000 km, is sub-transmission at 63, 90, 110 and 150 kV scattered across Spain, France, Germany, Romania and Ukraine. These are not island systems. They are regional networks whose connecting substation or feeder OSM has not mapped, so no amount of geometric repair will join them. At transmission voltage the figure is 98.9%.

### Sub-transmission by country, where it sits below 110 kV

| Country | Level | Route-km below 110 kV | National total in this build |
|---|---|---|---|
| France | 63 / 90 kV | 50,617 | 101,039 (RTE publishes ~105,000) |
| Spain | 66 kV | 13,994 | 65,625 |
| Portugal | 60 kV | 9,453 | 18,078 |
| Norway | 66 kV | 8,326 | 30,003 |
| Denmark | 60 kV | 5,441 | 11,156 |
| Belgium | 70 kV | 2,956 | 6,771 |
| Switzerland | 50 / 65 kV | 1,626 | 11,152 |

Poland, Czechia and Ireland return nothing in the 50 to 99 kV band, and Germany only 240 elements, because they use 110 kV as sub-transmission. Those countries were already complete at the earlier floor.

## 3. Validation

### Against the published dataset (paper Table 8, >=220 kV)

| kV | This build (km) | Published (km) | Delta |
|---|---|---|---|
| 220 | 80,399 | 79,130 | +1.6% |
| 225 | 26,807 | 26,012 | +3.1% |
| 236 | 18 | 18 | +2.1% |
| 275 | 4,781 | 4,756 | +0.5% |
| 300 | 4,343 | 4,255 | +2.1% |
| 330 | 19,544 | 18,123 | +7.8% |
| 380 | 36,377 | 34,610 | +5.1% |
| 400 | 100,458 | 98,066 | +2.4% |
| 420 | 5,012 | 4,951 | +1.2% |
| 500 | 430 | 230 | +86.9% |
| 750 | 4,114 | 4,002 | +2.8% |
| **Total** | **282,283** | **274,153** | **+3.0%** |

Within 3.3% overall. Compared on `length_conductor_m`, which excludes the synthetic connectors between the substation perimeter and the bus point, since the published dataset has no equivalent of those. OSM has also grown since the November 2024 snapshot the paper used. The 500 kV excess is 236 km in absolute terms, mostly Western Balkans additions.

### DC interconnectors (paper Table 7)

All 38 published DC relations are present. A further 34 DC conductors appear, being projects commissioned after the paper and multi-segment relations.

### Integrity

Zero unresolved bus references, zero self-loops, zero null or invalid geometries.

## 4. Layer structure

Two files. Neither duplicates the other's geometry.

**`europe_grid_topology.gpkg`** (185 MB, 55 layers) for map work:

- `line_50kV`, `line_55kV`, `line_60kV`, `line_63kV`, `line_65kV`, `line_66kV`, `line_70kV`, `line_90kV`, `line_110kV`, `line_130kV`, `line_132kV`, `line_150kV`, `line_154kV`, `line_220kV`, `line_225kV`, `line_275kV`, `line_300kV`, `line_330kV`, `line_380kV`, `line_400kV`, `line_420kV`, `line_500kV`, `line_750kV`, `line_other_kV`
- a recognised voltage always gets its own layer however few spans it has, so Ukraine's 750 kV (28 spans) is not buried in `line_other_kV`
- `site_*kV` on the same voltage cuts, **substation buses only**
- `junction_node` holds the 41,432 taps, line ends and attribute boundaries, kept out of the site layers so they do not read as substations
- `line_internal_to_station` holds the 113,213 conductor segments inside switchyards, kept rather than deleted but separated so the voltage layers stay legible
- `dc_link`, `transformer`, `station_cluster`, `substation_footprint`

**`europe_grid_graph.gpkg`** (2 layers) for network analysis:

- `ac_line_all`, `site_all`

### Endpoints

Every line and DC link carries the identity of both ends:

| Field | Meaning |
|---|---|
| `start_point`, `end_point` | substation name, or `unnamed substation`, or `junction` |
| `start_lat`, `start_lon`, `end_lat`, `end_lon` | node coordinates, EPSG:4326, 6 dp |
| `bus0`, `bus1` | join key to `site.bus_id`; the prefix is `st` for a substation and `jn` for a junction |

`junction` means the line genuinely does not terminate at a mapped substation, which is a different statement from a substation whose name is missing in OSM. 21,825 of 91,915 network spans (23.7%) have a named substation at both ends once each end is traced through pass-through junctions to the substation its route reaches. 84% of substation buses carry a name; the shortfall is that 59% of buses are junctions, not substations.

Junctions are line ends, attribute boundaries where circuit count or underground status changes mid-route, and real taps with three or more conductors. The median junction sits about 2.5 km from the nearest substation, so these are not substations that narrowly missed the catchment.

### Fields

Every field is either primary or carries provenance. Nothing that is exactly recoverable from another field is stored twice, so these are **not** present: `voltage_v` (use `voltage_kv`), `station0`/`station1` (the prefix of `bus0`/`bus1`), `underground`/`submarine` (see `construction_type`), `length_m` (`length_conductor_m` + `connector0_m` + `connector1_m`), `s_nom_n1_mva` (0.7 x `s_nom_mva`), `is_cross_border` (`countries` holding a semicolon), `elem_id` (`line_id` before the colon), `name` (`line_label` where `line_label_source` is `osm_name_tag`), `cables`/`wires` (see `n_circuits` and `circuits_source`), and `internal_to_station` (the layer says it). Lines carry 36 fields, sites 15.

### Construction type

`construction_type` says what the asset physically is, and `construction_source` says which tag decided it. Four states plus `mixed`, because a boolean would report everything OSM does not describe as overhead.

| Value | Spans | Route-km |
|---|---|---|
| `overhead_line` | 80,863 | 710,111 |
| `underground_cable` | 8,727 | 26,144 |
| `mixed` (part cable, part overhead) | 1,602 | 19,467 |
| `submarine_cable` | 275 | 4,509 |
| `unknown` | 448 | 2,116 |

| `construction_source` | Spans | Meaning |
|---|---|---|
| `osm_power_line` | 72,593 | tagged `power=line` |
| `derived_from_member_ways` | 10,540 | route relation with no tag of its own; taken from its member ways |
| `osm_location_tag` | 7,928 | `location=underground` / `underwater` / `overhead` |
| `not_tagged` | 448 | OSM does not say |
| `osm_power_cable` | 368 | tagged `power=cable`, no location tag |
| `osm_tunnel_tag` | 38 | `tunnel=yes` |

A cable-to-overhead transition is a real junction in the topology, which is what you want: at West Boldon a 273 m cable runs from the substation to `jn0035113`, and 1,418 m of overhead line continues from there. The node is the sealing end.

### Line naming

OSM frequently leaves `name` empty even where both endpoint substations are named. `line_label` fills that gap without touching the OSM tag, and `line_label_source` records which was used:

| Source | Spans |
|---|---|
| `osm_name_tag` | 34,517 |
| `derived_from_route_endpoints` (e.g. `Iver - West Weybridge 132kV`) | 10,598 |
| `osm_ref_tag` | 6,397 |
| `none_available` | 40,378 |

44,020 of 72,963 spans (60%) carry a label, against 28,741 from the OSM tag alone.

### Topology is carried in attributes

Every line has `bus0` and `bus1` referencing `site.bus_id`. Every site has `connected_line_ids`, `n_lines`, `degree`, `node_type` and `station_voltages_kv`. Every feature has `component`, where the largest is the main synchronous network. Two lines are connected if and only if they share a bus id, so the graph loads directly:

```python
import geopandas as gpd, networkx as nx
l = gpd.read_file('europe_grid_graph.gpkg', layer='ac_line_all')
G = nx.from_pandas_edgelist(l, 'bus0', 'bus1', edge_attr=['length_m','s_nom_mva','voltage_kv'])
```

Bus ids are `<node_id>_<voltage>kV`, so all voltages at one site share a node id and are linked by transformer records.

## 5. Provenance, and where to be careful

Every line carries `circuits_source`, which is one of:

| Value | Meaning |
|---|---|
| `tagged` | circuit count came from the OSM `circuits` tag |
| `derived_from_cables_tag` | floor(cables / 3), three cables to a three-phase circuit |
| `derived_from_wires_tag` | floor(wires / 3) |
| `assumed_single_circuit` | nothing available, one circuit assumed |

`qa_flags` marks only what needs checking before you rely on a record: `circuits_assumed`, `nonstandard_voltage`, `line_type_proxy_*`, `under_construction`, `not_in_main_component`. 40,146 of 64,810 network spans carry at least one flag, most commonly `circuits_assumed`.

Ratings are computed, not measured: `s_nom_mva = n_circuits * sqrt(3) * U_nom * I_nom`, with `I_nom` from the PyPSA-Eur standard type for that voltage, and `s_nom_n1_mva = 0.7 * s_nom_mva`. Where the circuit count was assumed, the rating inherits that assumption. Do not quote a rating to a customer without checking `circuits_source` first.

28.0% of buses have degree 1. Most are genuine sub-transmission spurs to a single load or generator. Some are artefacts where OSM stops mapping at a country edge or a line ends at an unmapped substation.

## 6. Method, and where it departs from the paper

Steps follow the paper: retrieve, clean, build network, parameterise.

1. **Retrieve.** Overpass area query per country in two passes, filtered to voltage >= 100 kV and then 50 to 99 kV at query time. The paper pulls all power features and filters afterwards; at a 110 kV floor that payload is unmanageable, so the filter is pushed into the query. DC relations are swept separately Europe-wide with no voltage filter, because DC relations are not reliably voltage tagged.
2. **Clean.** Voltage, circuits, cables, wires and frequency normalised. Records carrying several semicolon-separated values are split into one record per voltage, as in Tables 2 and 3 of the paper. Busbars and bays are dropped as internal substation elements.
3. **Relations over ways.** A route relation whose members merge into one continuous LineString replaces its member ways. One that does not is discarded in favour of the ways.
4. **Build.** Conductor chains are merged across pass-through nodes with matching parameters. Substation polygons within 150 m of each other, or bridged by a short conductor, form one physical site. Each conductor is clipped to the outside of the site polygons; every remaining part is a span, and a straight connector joins each end to its bus. A bus is (site x voltage), placed at the centroid of that voltage's busbar conductors inside the site where OSM maps them (29,722 of 30,518 buses) and otherwise at the site's pole of inaccessibility. Conductor ends beyond any site are clustered at 25 m into junction nodes. Transformers are lines between the voltage buses of a site. DC terminals attach to the nearest AC bus within 10 km.
5. **Parameterise.** Standard line types from PyPSA-Eur `config.default.yaml`, which already defines conductors down to 63 kV, so sub-transmission uses published types rather than our invention.

**Deviations, all deliberate:**

- Voltage floor 50 kV rather than 220 kV. This is the point of the exercise. A 110 kV floor was tried first and produced a France missing half its network, because RTE runs 63 and 90 kV.
- **Substation aggregation is declined.** CORRECTED 2026-08-19: an earlier version of this section claimed the published workflow truncates every line at a 500 m station buffer and represents the station as a point. That is false. Verified against PyPSA-Eur at commit `a5408e9`: `_map_endpoints_to_buses` takes `shape="station_polygon"` as its default and only call site, `geometry` is in `LINES_COLUMNS` so the published release carries full-resolution LineStrings, and buses are placed by `polylabel` inside the real substation polygon. The geometry treatment is materially the same as ours and the claim should never have been made.
  The real difference is narrower and is a design choice rather than a defect in their work. `BUS_TOL = 500` governs substation **aggregation**: upstream buffers substations by 500 m, unions the buffers and keeps one bus per merged group, which is correct for a power-flow model wanting one node per electrical station, and which their documentation states plainly ("Close substations within a radius of 500 m are aggregated to single buses, exact locations of underlying substations is preserved"). This build declines that aggregation, because a routeing model must keep two neighbouring compounds apart: a conductor between them is a real asset, not an internal jumper. That, plus keeping every clipped piece, is why the >=220 kV totals run about 2.5% above the published figures.
- Conductors wholly inside a substation are flagged and moved to their own layer rather than deleted. There are 130,674 segments, 6,757 km in total, median 21 m.
- Junction nodes use a 25 m clustering tolerance. Applying the 500 m substation-aggregation tolerance to conductor endpoints creates blobs that swallow short conductors whole; ways that genuinely connect in OSM share a node exactly. Upstream does not do this - the comparison is to our own earlier attempt.
- Voltage filter applied in the Overpass query rather than in post-processing, for payload reasons. Elements without a voltage tag are therefore absent.
- Non-conductor relation members are excluded by an exclusion list rather than an allow-list. An allow-list drops every HVDC project that uses the `section` role, which is most of them, including BritNed, Nemo Link, Viking Link and North Sea Link.

## 7. Known pitfalls, and how each is handled

Every one of these is a modelling choice that can mislead if you do not know about it.

| # | Pitfall | Status |
|---|---|---|
| 1 | **Bus points landing outside the substation.** OUR OWN DEFECT, not the paper's: an early version of this build clustered on a 500 m buffer and took the pole of inaccessibility of the *union*, putting 9.2% of bus points in open ground between substations, median 44 m out, worst 417 m, and fusing up to 20 distinct substations into one node. Upstream avoids this by taking the PoI of the real polygon where one exists. | **Fixed.** Buses are per site, placed inside the polygon. 100% of substation buses now fall within their own site. |
| 2 | **Self-loop spans.** 34,888 spans had both ends on the same site, because a 250 m catchment grabs both ends of a short stub. A self-loop cannot be a graph edge, so the conductor would have been silently lost. | **Fixed.** Median 57 m, so they are switchyard approach stubs. Moved to the internal layer, retained, and used as busbar evidence. 33 genuine long loops are kept and flagged. |
| 3 | **DC converters snapped to a distant bus.** Five links have one end outside the modelled area (HVDC Saudi Arabia-Egypt, Volgograd-Donbass, Dogger Bank A and B, East Anglia THREE). Nearest-bus attachment forged an edge 1,664 km long. | **Fixed.** A converter more than 10 km from any bus is left unattached and flagged `converter_unattached`. 27 links have a converter over 2 km out, flagged `converter_far`. |
| 4 | **Transformers are inferred, never observed.** OSM does not carry usable transformer data, so one is created between each adjacent voltage pair at a site: 4,731 in total. A site with 400/275/132 kV gets 400-275 and 275-132, assuming a cascade. A direct 400/132 bank would be missed, and a voltage pair present without a transformer between them would be invented. | **Flagged**, `inferred = voltage_pair_at_site`. 3,261 sites have two voltages and 773 have three or more. |
| 5 | **Bus voltage comes from the line, not the substation tag.** A bus is created at whatever voltage the connecting conductor carries, so a site can show a level its OSM substation record does not list. | **Deliberate** (the line must terminate somewhere) but it is inference. |
| 6 | **Only 29.4% of spans name a substation at both ends.** Routes fragment at attribute boundaries, and 59% of buses are junctions. | **Partly mitigated** by tracing each end through pass-through junctions to the substation the route reaches. The residue is genuine: junctions sit a median 2.5 km from the nearest substation, so they are real taps and line ends, not near-misses. |
| 7 | **Synthetic connector geometry.** 5,612 km of straight connectors join the substation perimeter to the bus point, median 36 m, worst 7,082 m. | **Separated.** `length_m` includes them, `length_conductor_m` does not, and the published-dataset comparison uses the latter. |
| 8 | **Under-construction lines are included.** 694 spans, 3,238 km. | **Flagged** `under_construction`. They are in the totals. Filter them out for an as-built view. |
| 9 | **Substation relations use a convex hull** when their members do not form a ring, over-covering concave sites. 1,526 of 37,729 records. | **Affects site extent only.** Bus placement uses busbar centroids, so it is not displaced. |
| 10 | **500 kV runs 87% above the published figure**, 430 km against 230 km, across 6 spans in eastern Ukraine. Verified real (Kreminska 500 kV commissioned 2020; Donbaska-Peremoha named in the grid development plan) but war-affected since 2022. The two Italian spans previously here were a 132 kV keystroke error, corrected in v21. | **Resolved in v21** for classification; operational status in Donbas remains unknown. |
| 11 | **Conductor ends OSM never joined.** 6,640 dangling ends (52% of all dead ends) sat within 25 m of a different conductor with no shared node, reading as spurious breaks in the network. | **Fixed.** 71,693 ends snapped and 4,758 target conductors split, creating real T-junctions. Only same-voltage conductors are joined: a 400 kV line ending 20 m from a 132 kV line is not connected to it. 4,399 same-voltage cases remain unsnapped, mostly parallel circuits running alongside each other where joining them would fabricate a connection. |
| 12 | **Junction nodes rendered as substations.** 47,487 junctions sat in the `site_*kV` layers alongside 32,668 real substations, so a map read as if every tower were a site. | **Fixed.** `site_*kV` now holds substation buses only; junctions moved to `junction_node`. 20,514 of them are degree-2 attribute boundaries, not electrical nodes. |
| 13 | **One OSM element split at every tower.** Snapping other conductors onto a long line cut it at each contact: `relation/6077873` came out as 172 spans of median 260 m with all 169 junctions at degree 2. Those junctions are tower positions, not electrical nodes. | **Fixed.** Spans of the same `elem_id` meeting at a degree-2 junction are re-merged. That relation is now 5 spans; elements producing more than 20 spans fell from 146 to 27. A node where a third conductor genuinely attaches has degree 3 and survives. |
| 14 | **Parallel circuits shredding the line beside them.** A duplicate circuit mapped tower-by-tower snapped every one of its way-ends onto its neighbour. | **Fixed** with an angle test: a contact within 25 degrees of parallel is rejected, since a real tap arrives at an angle. The test applies only to a contact landing in the *middle* of a conductor. Applying it to end-to-end contacts as well was itself a defect - see row 21. |
| 15 | **Elements split at every tower where the node degree exceeded 2.** `relation/18555112` arrived as 160 spans across 53 nodes with degrees of 4, 6, 8 and up to 22, because junction clustering chained along it. A degree-2 rule cannot reach that. | **Fixed** by a node rule: a junction is dissolved when every span meeting there is the same OSM element, it is not a terminus, and it is not a substation. That case is now 13 spans; a 225 kV French line went 528 to 55, another 491 to 15. Elements producing more than 20 spans fell from 27 to 12. Nodes are retained wherever a different element attaches, so specificity is kept. |
| 16 | **Rebuilding an element can silently lose geometry.** A first version of the dissolve looked tidy and dropped 60,000 route-km, swinging validation from +2.4% to -6.7%. A second rejected any element whose rebuilt part looped back to one node, throwing out 2,415 of 2,757. A third matched rebuilt endpoints against one stored coordinate per node, but junction clustering places endpoints up to 25 m apart at the same node, so 265 elements failed to match. | **Fixed and guarded.** Every span endpoint is indexed with its node id, and every rebuild is length-checked per element with a revert to the original spans on any shortfall. Current run: 306 elements rebuilt, 0 reverted, **100.00% length retained**. |
| 16b | **Junction clusters can chain.** Single-linkage at 25 m along a densely split line merges endpoints in a row into one node whose centroid sits far from any of them. | **Bounded** at 600 m cluster width. A 100 m setting was tried and reverted: it broke 84 clusters but pushed the component count from 3,714 to 5,099, because splitting a cluster disconnects everything meeting there. |
| 17 | **Micro self-loops drew a twirl.** A span returning to the node it left, 14-19 m long with a connector at each end, renders as a spike. The earlier sweep only caught loops on a *site*, and the dissolve created fresh ones afterwards. | **Fixed.** Self-loops at any node type are moved to the internal layer, and the sweep is repeated after the dissolve. **0 remain**, against 78 before. |
| 18 | **Junction connectors drew spikes.** The junction point was the cluster *mean*, which in a chained cluster sits away from every member and drags a connector back along the line. | **Fixed.** The point is now the medoid, always a real endpoint, and at a junction the endpoint is moved onto it rather than a connector being drawn - but only within 50 m, so geometry is never distorted. Junction connectors are now median 0 m, 95th percentile 0 m. |
| 19 | **A residual 136 connectors exceed 1 km** and will read as straight spikes. | **Flagged** `long_connector` in `qa_flags`. 0.19% of spans. |
| 20 | **Crossing conductors are not connected**, which is correct, but a genuine tap that OSM never split into separate ways is missed. | **Open**, not quantified. |
| 21 | **The angle test rejected the joins it was most needed for.** Two ends of one circuit meet head-on, so they are collinear, so the 25-degree parallel rejection in row 14 refused every genuine end-to-end join. It ran before the end-to-end test rather than after it. Result: 848 same-voltage bus pairs still sat under 25 m apart in different components. | **Fixed.** The end-to-end case is tested first and exempted; the angle test now guards only contacts into the middle of a conductor. Snapping rose from 18,986 ends to 62,659, and **cross-component same-voltage bus pairs within 25 m fell from 848 to 0**. |
| 22 | **Ends that stop short of each other are the dominant break away from substations.** One mapper's way ends at the last tower surveyed and the next begins tens of metres on, with no shared node. Of 115,942 dangling ends, 55,578 of the 57,930 same-voltage pairs within 25 m lie within 250 m of a substation, where the site catchment already resolves them. Away from substations there are 2,352 at 25 m and 5,672 at 150 m. | **Fixed** by a dedicated end-to-end pass before clipping. Gated on same voltage, on the two stubs pointing at each other within 60 degrees, and on one join per end taken closest first, so nothing chains. 3,342 ends joined: 3,189 by moving both tips to the midpoint where the gap is under 50 m, 153 bridged with an explicit vertex above it. 53,173 candidates were rejected as not head-on. The 150 m ceiling sits below one tower span of 200 to 400 m, past which bridging a gap would invent a conductor rather than repair a break. |
| 23 | **Bursting an over-wide junction cluster into singletons destroys connectivity.** Extending the junction reach to 150 m chained clusters past the 600 m width limit; the burst rule then split each into one node per endpoint, disconnecting everything that met there. Components went from 3,820 to 7,731 - the opposite of the intent. | **Fixed twice over.** An extended union is refused if the merged cluster would exceed 250 m wide (12,847 refused on that basis), and an over-wide cluster is now re-clustered at 10 m instead of exploded. A further pass merges two junctions within 300 m only when they sit in **different components**, which cannot chain because each merge removes a component: 76 merged. Net: components 3,820 to **3,326**, route-km in the largest 95.2% to **95.9%**, and cross-component same-voltage bus pairs within 300 m from 13,397 to 576. |
| 24 | **Snapping and bridging add length that OSM does not carry.** Closing a gap between two tips inserts up to 150 m of conductor that no one surveyed. | **Bounded and visible.** Total route-km moved 755,265 to 755,225, within 0.01%. Connectors over 1 km stay flagged `long_connector`. |
| 25 | **Two circuits of one double-circuit line fused into an out-and-back conductor.** A double-circuit route is mapped as two relations on the same pylons carrying the same voltage, circuit count and location, and both terminate at the same substation. The chain merger saw a degree-2 node with matching attributes and joined them: `relation/16861592` and `relation/16861593` (RTE 225 kV, Normandy) became one 97.85 km conductor running out 49 km and back along the same coordinates. Every later set operation then noded that self-overlapping line at each shared vertex. It left the build as **529 tower-length fragments** in `line_internal_to_station` drawn on top of the route, which is what a user sees as random splits mid-line. 2,892 of 11,460 candidate nodes had this shape. | **Fixed** with a continuation test: the two conductors merge only where the line runs *through* the node. Their outward directions at the shared node must be roughly opposite - a line running through turns by 60 degrees or less, a pair folding back leaves in the same direction (dot near +1). The angle distribution is bimodal, 6,424 nodes under 26 degrees against 556 above 154, so the cut is not arbitrary. Worst element fragmentation fell **757 segments to 13**; that relation is now **1 clean span of 48.88 km with 3 internal segments**, and its twin exists separately rather than being swallowed. **Elements producing more than 20 spans fell from 6 to 0**, worst 49 to 9. Refusing a merge costs one extra span and one junction node; the conductors stay connected. |
| 26 | **Conductors that stop short of the fence together were deleted.** At Poste electrique d'Ecrainville both 90 kV circuits stop 159 m short of the substation and two 159 m conductors carry on from that common point into the yard. The 250 m site catchment pulled all four ends onto the site, which made both short conductors self-loops - so they were deleted from the network and left in `line_internal_to_station` as loose ends - and then drew two synthetic 174 m connectors straight over the top of them. Across the build this deleted 16,882 spans and 2,233 km, including a 1.5 km 400 kV run and a 1.2 km 110 kV one. | **Fixed** with two rules. Where several conductors end at the same point outside the fence, that point becomes a junction, not the substation: 29,387 ends across 9,279 such points. An end within 30 m of the polygon is at the fence and still takes the site. A group only moves off the site when one of the spans meeting there has its other end AT the fence, so it provably carries the connection into the yard - requiring merely that the site keep one attachment was not enough and pushed components from 3,345 to 3,850. Second, a span still landing both ends on one site keeps its far end freed when that end is 50 m or more out (1,960 cases), because it is an approach conductor, not a switchyard jumper. Ecrainville now has a node at the tee and at the substation, both 159 m conductors are back in the network, and both long lines terminate at the junction with **zero** synthetic connector. Internal layer 7,055 km to 4,822 km; connector 95th percentile 193 m to 150 m. |
| 27 | **A route passing one substation drawn as a straight line to the next.** The site builder fused two polygons whenever a conductor under 1 km merely TOUCHED both - and every real link between two neighbouring substations does exactly that. Poste electrique de Levallois and Poste electrique de Perret, 397 m apart and differently named, became one site: the 225 kV route from Cormeilles ended at the Levallois compound and was drawn to the Perret bus with a **476 m straight connector**, on top of the three real 225 kV cables that run between them. 1,235 of 2,805 multi-polygon sites had spread past 300 m, with a 99th percentile of 1,075 m. | **Fixed.** The conductor must now run no more than 50 m outside the two polygons and they must be within 250 m of each other, which is what "one switchyard in two compounds" actually looks like. That case is now two sites, the connector is **17 m**, and the three real cables (670, 731, 729 m) carry the connection. Connectors over 400 m fell 880 to 348 and over 1 km 44 to 8; multi-polygon sites wider than 300 m fell 1,235 to 740 and wider than 1 km 48 to 7. A name test also refuses a merge where both polygons are named and neither name contains the other, but **only on the conductor path**: applied to the 150 m proximity merge as well it blocked 1,488 merges, 983 with no conductor between the two polygons, taking those sites apart and their transformers with them, at a cost of 0.28 points of >=220 kV route-km in the largest component. |
| 28 | **A boolean cannot say "OSM does not know".** `underground` came from the `location` and `tunnel` tags alone and ignored `power=cable`, so 316 spans and 1,525 km of cable read as overhead line. Worse, 10,988 spans and 205,188 route-km carrying `power=circuit` or no power tag at all were reported as not-underground, which reads as overhead for a quarter of the network. | **Fixed.** `construction_type` has five states and `construction_source` records which tag decided each one. Route relations usually carry no power tag of their own, so their type is taken from their member ways (10,540 elements), and a route that is part cable and part overhead is `mixed` (1,602 spans) rather than forced to one answer. **Unknown fell from 205,188 km to 2,116 km, 0.3%.** |


## 8. Reproducing

`src/` holds four scripts run in order: `load_clean.py`, `build_geometry.py`, `build_topology.py`, `export_gpkg.py`, then `validate.py`. The 110 kV floor is `MIN_V` in `load_clean.py`. Raw harvest is 111 NDJSON files, 165 MB: two passes per country plus the DC sweep.

CRS is EPSG:4326 throughout. Lengths and areas are computed in EPSG:3035.

## 9. Licence

OpenStreetMap data, ODbL 1.0. Attribution: (C) OpenStreetMap contributors. Derived databases carry the same share-alike obligation, which matters if any of this reaches a customer deliverable.

## 11. v21 manual corrections (2026-08-18)

Five misclassifications fixed against primary sources, two out-of-scope DC rows deleted, two DC ends attached at Spittal, and explanatory `qa_flags` added to the 16 legitimately unattached DC ends. Row-level evidence: `manual_corrections.csv`. Pre-patch files: `_backup_v20/`. Script: `_xfer/patch_v21.py`.

| Change | Detail |
|---|---|
| Norfolk Vanguard/Boreas onshore connection | AC layer -> `dc_link`. +/-320 kV HVDC (Vattenfall contract award); the inferred 320/400 "transformer" at Norfolk Vanguard West was the converter and is deleted |
| Berwick Bank Cambois export cable | AC layer -> `dc_link`. HVDC; 525 kV is the design-envelope maximum |
| Arsiero-Caldonazzo, Arsiero-Asiago (IT) | 500 kV -> 132 kV. OSM keystroke error; Terna operates no 500 kV AC |
| Hornsea One offshore export span | 254 kV -> 220 kV (Ofgem OFTO asset schedule); now joined to its onshore cable in the main component |
| HVDC Saudi Arabia-Egypt; Charnyany-Dneprobugskaya | Deleted from `dc_link` (outside coverage; the latter is a Belarusian 110 kV AC line mis-tagged as DC) |
| Caithness-Moray, Shetland HVDC | Attached to the Spittal converter bus their geometry already terminates at; Shetland now joins the main component |

Post-patch state: 91,913 AC spans; 75,406 buses; 3,738 components; 95.87% of route-km in the largest component (98.87% at >=220 kV); 72 DC links, 16 with a legitimately unattached end (offshore platforms and third-country ends), each flagged.

## 12. v22: frequency separation and PyPSA-modelling fixes (2026-08-18)

v22 makes the file pair a defensible PyPSA base network. Applied by `_xfer/patch_v22.py` against a
live OSM scrape (`_xfer/freq_nonstd_real.csv`, provenance in `scrape_PROVENANCE.md`); adversarially
reviewed twice (one NO_GO enforced, then GO); headline numbers are generated from the shipped files
(`v22_stats_sidecar.json`), not transcribed.

**Frequency separation.** Europe operates two AC synchronous families: the 50 Hz public grid and
the 16.7 Hz railway traction networks of DE/AT/CH/SE/NO. v21 pooled both. v22 adds `frequency_hz`
and `frequency_source` to every line, bus, transformer and dc_link; classifies 1,397 spans /
16,524.2 km as 16.7 Hz (precedence: pure OSM frequency tag 1,380 > operator inference 17, the
latter only at <=132 kV in the five traction countries with every operator token a known 16.7 Hz
system; an explicit frequency=50 tag vetoes inference); moves them to `line_<kV>_16_7Hz` layers
(110 kV: 971, 132: 334, 66: 76, 55: 15, 130: 1 - the single 130 kV row is one 25.1 km Swedish span
at a nonstandard mapped voltage, not a 130 kV traction system); severs the 235 buses where both
systems met (clones carry `severed_from`); and deletes 56 inferred voltage-pair "transformers"
that were physically converter interfaces. Converter stations (DB Umformer-/Umrichterwerke, SBB,
OeBB) exist in operator registers and could be added as links - bounded future work; until then
the two systems are galvanically separate here, which matches reality.

**Traction coverage vs operator-published lengths.** CH 1,764 km incl. border spans (SBB: ~1,800)
and SE 1,914 km (Trafikverket: ~1,700-2,000) agree with the operators - external validation.
DE 10,199 km (DB Energie: ~7,800 km of 110 kV Bahnstromleitung) and AT 2,382 km (OeBB: ~1,000 km)
run above because ours counts route-km of every mapped way, including 15 kV-class feeders that
reach >=50 kV, joint corridors and station approaches; all 237 AT rows and nearly all DE rows rest
on explicit OSM frequency tags. Residual: 291 shared-tower spans tagged `50;16.7` are kept wholly
at 50 Hz (`osm_mixed_50_16.7_kept_50`, 2,988.7 km) - their traction circuits are absent from the
traction layers and their 50 Hz circuit counts are overstated by the shared circuits. Two
pure-16.7-tag spans with joint operator lists carry `joint_operator_traction_tag`; one
Italian-side SBB feeder span carries `traction_tag_outside_expected_geography`; one 170 kV Swedish
row's 16.67 tag was overridden by the <=132 kV gate and its provenance says so
(`osm_frequency_tag_16_7_overridden_ehv_gate`).

**Other v22 fixes.** (a) Scope: 314 spans / 326 buses in overseas territories (New Caledonia,
Reunion, Antilles, Guiana, Canaries, Madeira, Azores) removed; study area lon -12..45, lat 34..72;
gpkg_contents extents recomputed. (b) Circuit duplicates: 489 groups where one OSM element claimed
by n circuit-relations shipped as n identical rows, each carrying the full element parameters - a
6-circuit corridor counted as 36 circuit-equivalents at 1/36th impedance; collapsed to one row per
element (505 rows and ~2,894 km of double-counted route removed; parameters were already
element-correct; 14 rows in 7 groups with differing geometry remain flagged
`circuit_count_element_level_ambiguous`). (c) Lengths: 125 spans whose stored length disagreed
>10% with their own geometry recomputed (haversine, R=6371.0088 km), r/x rescaled; 5 spans where
connectors exceed geometry are flagged unresolved, not forced. (d) `component` REDEFINED over
lines+transformers only - PyPSA's passive-branch partition - deterministic (route-km then root-id
ordering), with `component_incl_dc` a separate bus column. The top components are the real
synchronous areas: Continental 77.4% of route-km, Nordic 11.0%, GB 3.9%, all-island Ireland 1.2%,
Sardinia 0.4% (DC-linked only, correctly separate), largest traction island 1.2%; residual
fragments 4.9%. **`not_in_main_component` now means "outside the Continental synchronous area"**
and covers 22,241 spans (v21: 7,529) - a definition change, not a regression. (e) Bookkeeping:
degree (distinct neighbours over lines+transformers+dc_links), n_lines (incident AC ends) and
connected_line_ids recomputed for every bus and propagated to every layer; the two GeoPackages are
column-identical on all shared fields. (f) Idempotent: `patch_history` table; re-application
refuses with exit 3.

**PyPSA acid test** (`_xfer/acid_test_pypsa.py`, report `acid_report_v22.json`, pypsa 1.2.4):
strict named consistency checks pass; sub-networks computed sparsely = 3,847, matching the
`component` column exactly; zero sub-networks mix frequency; linear power flow solves on the
largest >=220 kV 50 Hz backbone component (9,955 buses; balanced 2,000 MW injections; max KCL
residual 4e-10 MW; scope stated because pypsa 1.2.4's dense adjacency cannot handle 52,929 buses)
and on the largest traction island (438 buses). Scrape note: 6,345 ways + 1 relation - OSM carries
frequency on ways, so the near-empty relation arm is expected, not a failed query.

Ambiguous circuit rows kept (7 groups): relation/9964535:1, relation/9964535:3, relation/9964536:0, relation/9964536:2, way/114446733, way/178413346, way/467834292:0, way/467834292:2, way/576502850, way/741770435.

## 13. v23 - transformer parameters and DC link ratings (2026-08-18)

v22 left two attribute gaps between this dataset and direct PyPSA use: the transformer layer carried no electrical parameters, and `dc_link` carried no capacity. v23 closes both. It is attribute-only: no geometry, no row creation or deletion, no layer changes, and `europe_grid_graph.gpkg` is untouched (still v22, byte-identical). Idempotent via `patch_history` version `v23`; fail-closed invariants (any breach rolls back the transaction). Evidence gathered 2026-08-18 by a researched pass over public sources, then adversarially reviewed twice; the review corrected three findings before release (Konti-Skan pole ratings, an over-claimed source label on EHV transformer ratings, SACOI capacity accounting - details below and in the provenance CSVs). The patch cross-checks its embedded tables row-by-row against `dc_link_ratings.csv` before opening the transaction, so the shipped CSV and the shipped attributes cannot drift.

### 13.1 Transformer parameters (4,753 rows, 100% coverage)

New columns: `s_nom_mva`, `x_pu`, `r_pu`, `s_nom_pypsa_eur_mva`, `parameters_source`. Per the PyPSA Transformer convention, `x_pu` and `r_pu` are per-unit **on the transformer's own `s_nom`** (PyPSA components doc; `pypsa/data/component_attrs/transformers.csv`). The full typing rule with citations ships inside the GeoPackage as `v23_typing_rule` - registered in `gpkg_contents` as an attributes table, so QGIS and ogrinfo list it - and alongside as `transformer_typing_rule.csv`.

Banded typing rule (lo/hi = lower/higher side kV):

| Band | Selector | Rows | s_nom (MVA) | x_pu | r_pu | Basis |
|---|---|---|---|---|---|---|
| R1 | lo >= 200 | 828 | 2000 | 0.100 | 0.0025 | x: PyPSA-Eur config default; s_nom, r inferred |
| R2 | 100 <= lo < 200, hi >= 330 | 995 | 500 | 0.122 | 0.0025 | x, r: pandapower "160 MVA 380/110 kV"; s_nom inferred |
| R3 | 100 <= lo < 200, 200 <= hi < 330 | 1,247 | 300 | 0.120 | 0.0026 | x, r: pandapower "100 MVA 220/110 kV"; s_nom inferred |
| R4 | 100 <= lo < 200, hi < 200 | 137 | 300 | 0.100 | 0.0025 | x: PyPSA-Eur default; r, s_nom inferred |
| R5 | lo < 100, hi >= 200 | 807 | 200 | 0.160 | 0.0040 | inferred: extrapolated from pandapower 110/20 family |
| R6 | lo < 100, hi < 200 | 739 | 120 | 0.160 | 0.0040 | inferred: extrapolated from pandapower 110/20 family |

Sources pinned: PyPSA-Eur commit `8119040` (config.default.yaml transformers block; `base_network.py` applies `x` unconditionally), pandapower tag `v3.1.2` (`std_types.py`; vk/vkr per Oswald's teaching text - a German lecture script, not a TSO equipment survey). Where a band takes x from a pandapower type, x = vk/100 (vk is the short-circuit impedance magnitude; the reactance correction sqrt(vk^2-vkr^2) is below 3e-5 pu). The six bands partition all 142 observed voltage pairs with no gaps or overlaps. R1's 2,000 MVA deserves its `inferred` label: it is PyPSA-Eur's config value, but that value is **dead code in their OSM workflow** (guarded by `if "s_nom" not in transformers:`, and the prepared CSV always has the column) - it is shipped here as an assumed aggregate EHV bank capacity, not as a sourced rating.

`s_nom_pypsa_eur_mva` is a second, independent rating column: the convention the reference workflow **actually ships**, `ceil(max(total incident AC line s_nom at bus0, at bus1))` per `build_osm_network.py` L1238-1248, computed from this dataset's own line layers (traction and `line_internal_to_station` excluded; 8 rows with no incident AC lines fall back to the banded value, suffixed `alt_snom_fallback_banded_no_incident_ac_lines`). It is deliberately non-binding (min 37, mean 3,654, max 54,040 MVA - the max double-counts every incident circuit). **Coupling warning:** `x_pu`/`r_pu` are per-unit on `s_nom_mva`. Mapping `s_nom_pypsa_eur_mva` onto PyPSA's `s_nom` while keeping `x_pu` rescales every transformer impedance by the ratio of the two columns (median 5x, p95 20x, max 187x) - recompute or drop `x_pu` if you swap. Use `s_nom_mva` where the transformer should have a physically plausible impedance; use `s_nom_pypsa_eur_mva` for strict PyPSA-Eur conformance or non-binding screening.

Honesty notes, in decreasing order of importance. `s_nom_mva` is the least defensible column: banded values assume 2-4 parallel banks per site coupling and no public per-substation inventory was consulted - treat it as `inferred:` throughout. PyPSA-Eur never sets transformer `r` (stays 0, zero copper loss); this dataset departs deliberately and sources `r` from vkr where a type matches. PyPSA-Eur itself destroys all transformers in `simplify_network_to_380` before optimising, so its defaults survive unvalidated - cite them as convention, not engineering. 99 rows across 12 pairs have a voltage ratio below 1.095 (`380/400`, `130/132`, `150/154`...) and are probably OSM voltage-tagging inconsistencies for one physical level rather than real plant; they are suffixed `ratio_lt_1p095_probable_voltage_tagging_artifact` and parameterised as near-transparent couplers (R1/R4). The correct upstream fix is a bus merge - v24 candidate, not attempted here.

### 13.2 DC link ratings (72 rows: 67 rated, 5 honest unknowns)

New columns: `p_nom_mw` (continuous rated capacity attributable to that row), `status`, `p_nom_source` (one URL, an explicit `inferred:` derivation naming its inputs, or `unknown`). **`status` records commissioning state** - operational 61 / under_construction 6 / unknown 3 / planned 1 / partially_operational 1, as of August 2026 - **not transient availability**; outages live in `qa_flags` (e.g. Skagerrak 2, out of service since 2026-06-02, repair due 2026-09-02, still `operational`). Per-row research notes, review revisions and appended qa flags in `dc_link_ratings.csv`.

Apportionment conventions, applied uniformly: a **series section** carries the full scheme rating (Ultranet 2,000 MW; both SACOI2 sections 300 MW); **parallel poles/circuits** split the scheme total (IFA members 4 x 500 MW, INELFE 2 x 1,000, Skagerrak poles 250/250/440/700, Konti-Skan poles 350/300 - published nameplates; SvK's 715 MW system capability exceeds their sum and sits in `qa_flags`; the same pattern is flagged on Skagerrak, whose 1,700 MW system total exceeds the 1,640 MW sum of pole nameplates). Where no per-unit figure is published the split is labelled `inferred:` in `p_nom_source` itself (Vyborg's 1,000 MW back-to-back scheme split equally across its three border circuits; pole identities on shared OSM relations). SACOI2's per-section 300 MW is likewise an inference from series topology - the source gives only the scheme rating and the 50 MW Lucciana tap, and with the tap loaded the Sardinia-Corsica section carries roughly 250 MW. A **shared corridor** row carries the rating of the scheme it is attributed to, disclosed by flag (fid 73: Norfolk Vanguard West's 1,400 MW on a corridor that will eventually carry 4.2 GW across three schemes) - the opposite convention from an umbrella row, which carries the scheme total and is excluded from sums.

**Do not naively `SUM(p_nom_mw)`.** Three rows carry `exclude_from_capacity_sums`: the IFA-2000 umbrella relation (fid 28 - the four member cable pairs, fids 30-33, are the canonical representation), one of the two SACOI2 series sections (fid 29; fid 36 is canonical), and the inferred Spittal DC tail (fid 52) which overlaps the Caithness-Moray and Shetland rows. Gross sum 56,066 MW; excluding flagged rows **52,966 MW**.

The five unknowns, with reasons: fids 62 and 64 are almost certainly **AC lines mis-tagged `frequency=0` in OSM** (Wesel-Doerpen 380 kV and Ostbayernring 380 kV respectively - both sourced), flagged `probable_ac_misclassification_frequency0_tag`; fids 63 and 65 are degenerate zero-length stub relations, unidentifiable from public data; fid 74 (Berwick Bank export) has no published per-cable rating and its OSM `under_construction` tag is unsupported - consented July 2025, no FID, so `status = planned`. These stay `unknown` because they are not (or not identifiably) HVDC assets; the Vyborg rows are rated despite also being AC circuits because they are the working feeders of an HVDC scheme with a published total. Moving 62/64 back to the AC layers touches geometry and layer membership and is deferred to a v24 candidate alongside the pseudo-transformer bus merges.

### 13.3 What v23 does not change

Geometry, feature counts, feature-layer set, bus topology, frequency assignment, component labels, and every v22 statistic. The only additions beyond the new columns are two non-spatial tables: `v23_typing_rule` (registered attributes table) and the `patch_history` row. The adversarial review verified the applied file is byte-identical to baseline on all pre-existing columns and geometry blobs, and that a from-scratch re-application reproduces it exactly. The acid test passes unchanged on structure and now runs its LPF on the shipped transformer impedances instead of placeholders (KCL residual below 1e-9 MW).
