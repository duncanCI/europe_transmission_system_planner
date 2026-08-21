# Prior-art check: what was new, what was not, and one error to correct

Commissioned before publishing anything. Four researchers assessed 68 datasets and
tools; I then verified every load-bearing claim myself against the PyPSA-Eur source at
commit `a5408e9` (release v2026.08.0, committed 2026-08-19).

**Headline: the artefact is unoccupied, the method largely is not, and two of the five
things I told you were distinguishing features are wrong. Do not publish the current
framing.**

## The scorecard

| Claim | Verdict | Evidence |
|---|---|---|
| 1. Voltage floor 50 kV, not 220 | **Not novel as method** | PyPSA-Eur PR #1740, merged 2025-08-25, ships `config/examples/config.distribution-grid-experimental.yaml` with `voltages: [63, 66, 90, 110, 132, 150, 220 ... 750]`. Author: Bobby Xiong, lead author of the paper we recreated. Conductor types for 63-150 kV are in `config.default.yaml`. The Overpass query applies no voltage filter at all |
| 2. Conductor geometry preserved; buses inside substations | **FALSE as stated** | `_map_endpoints_to_buses(shape="station_polygon")` is both the default and the only call site. `git log -S'shape="poi_perimeter"'` returns zero commits: a 500 m clip has never existed upstream. `geometry` is in `LINES_COLUMNS`, so the published release already carries full WKT LineStrings, and `_extend_lines_to_buses` extends them to the bus. Buses are placed by `polylabel` inside the real polygon |
| 3. Unclustered, asset resolution | **Weak** | The published release is already one bus per (substation x voltage). Staying unclustered means not running `cluster_network`. Nothing in the survey challenges it, but nothing had to |
| 4. 16.7 Hz traction separated | **Survives, and matters more than I thought** | `clean_osm_data.py:886` sets `valid_frequency = ["50", "0"]` and coerces everything else to `"50"`. `frequency` appears nowhere in `prepare_osm_network_release.py`, so it is not even exported. Upstream normalises `16.67` to `16.7` and then relabels it 50 Hz |
| 5. Cell-level provenance | **Survives** | No grid dataset found does per-cell sourced / inferred / unknown labelling. State of the art is dataset-level documentation |

## The error, in full

`supporting/README_methodology.md` line 205 says the published workflow "truncates
every line at the 500 m station buffer, discards the stub, and represents the station
as a point". That is not true, and it is the load-bearing sentence for our biggest
claimed differentiator. Upstream clips at the real substation polygon and publishes
full-resolution geometry.

What is true, and what I conflated it with: `BUS_TOL = 500` governs substation
**aggregation**. Upstream buffers substations by 500 m, unions the buffers, and keeps
one bus per merged group, which does fuse genuinely separate neighbouring substations
into a single bus. Their own documentation states this plainly: "Close substations
within a radius of 500 m are aggregated to single buses, exact locations of underlying
substations is preserved."

So the real difference is narrower and is a **design choice, not a defect in their
work**: they aggregate at 500 m because a power-flow model wants one node per
electrical station; we decline the aggregation because a routeing model needs the two
compounds kept apart. Our measured figures - 9.2% of bus points in open ground, median
44 m out, up to 20 substations fused - describe **our own early implementation**, which
we then fixed. Attributing them to the paper was wrong. They are in the v10-v20 build
history as our defects, and that is where they belong.

## Where the build is redundant on geography

Some operators publish better data than OSM for their own territory, and for those
countries this dataset is the inferior source:

| Country | What is already published | Effect |
|---|---|---|
| France | RTE open data: overhead lines, underground cables, substation sites, tapping points and individual pylons | **Supersedes.** The country our headline claim leads with is the country where authoritative geometry is already free |
| Netherlands | TenneT Assets Hoogspanning feature service | Supersedes nationally |
| Switzerland | Federal inventory of electrical installations above 36 kV | Supersedes nationally |
| GB | DNO 132 kV and 33 kV asset shapefiles; NESO route-map shapefiles | Substantial overlap below 275 kV |
| Norway, Sweden, Germany | Kraftlinjer/Nettanlegg, Topografi 10 Ledningar, DLM250 | Partial: geometry without electrical topology |

## What is genuinely unoccupied

All four researchers independently reached the same conclusion, and it is worth stating
precisely because it is the only claim that survives contact:

> No open, pan-European, OSM-derived, topologically connected, asset-resolution grid
> model covering 50-150 kV with preserved conductor geometry and cell-level provenance
> has been published.

The structural reason is the sharpest argument for the work: **the pan-European
electrical models have no geography, and the national geographic datasets have no
electrical topology.** ENTSO-E's public grid map is explicitly schematic ("network
elements are not located at their real geographic location"), its STUM electrical model
carries no node coordinates at all, and the JRC has published a grid dataset for Africa
but none for Europe. Meanwhile RTE gives you exact pylons and no graph.

Two supporting facts. Every published PyPSA-Eur prebuilt release, 0.1 through 0.7
(2026-02-12), is 220-750 kV; the maintainer states "the osm-prebuilt network will still
be created from 220 kV upwards". And upstream's own source still carries two unfinished
markers specific to the range PR #1740 opened:

```python
# TODO: In first draft, skip line splitting for lower voltage levels
high_voltage_lines = lines.query("voltage >= 220000")
...
# TODO: Relevant only for sub 220 kV AC lines: Implement fix for MultiLineStrings
```

Line splitting at overpassing nodes is what turns conductors into a connected graph, and
it is still restricted to 220 kV and above. So the capability is upstream and a year
old; the topologically resolved sub-transmission **artefact** is not, and their own code
says why.

## What I would do now

**Reframe from "we did it better" to "we published the thing nobody had published".**
The defensible claims are: the artefact at 50 kV with resolved topology, the frequency
separation, the provenance discipline, and honest documentation of the residuals. Drop
the geometry claim entirely and stop describing the aggregation as a defect.

**Report the traction finding upstream.** `valid_frequency = ["50", "0"]` coercing
16.7 Hz to 50 Hz is harmless at 220 kV and above, where there is almost no traction, and
becomes a real defect the moment someone uses the new 63-150 kV config: DB Energie,
SBB, OBB and Trafikverket traction lands in the public grid as 50 Hz. We have the
measured extent (16,524 route-km) and external validation (Switzerland 1,764 km against
SBB's published 1,800). That is a contribution to the project we depend on, and it is a
better introduction to Bobby Xiong and Fabian Neumann than a blog post claiming to have
outdone them.

**Reconsider the gated download.** The evidence pack's credibility rests on the
methodology document, which currently contains the false claim. Fix that before anything
goes out.

## Sources

PyPSA-Eur source at `a5408e9`, verified locally: `scripts/build_osm_network.py`,
`scripts/clean_osm_data.py`, `scripts/prepare_osm_network_release.py`,
`config/config.default.yaml`, `config/examples/config.distribution-grid-experimental.yaml`.
PR #1740: https://github.com/PyPSA/pypsa-eur/pull/1740
Prebuilt release v0.7: https://zenodo.org/records/18619025
Xiong et al. 2025: https://doi.org/10.1038/s41597-025-04550-7
Full 68-dataset assessment: `prior_art_assessment.json`
