# CLAUDE.md - europe_transmission_system_planner

Rebuild pipeline, methodology and evidence for the European Grid Topology
Dataset: 36 countries, 50-750 kV, 91,094 AC spans, 75,315 buses, 72 DC links,
4,753 transformers, built from OpenStreetMap (ODbL 1.0). The GeoPackages
themselves are NOT in this repo - they publish on Zenodo as
DOI 10.5281/zenodo.22043867.

## Commands

```sh
# tests (fixture, gate, mutation, validator suites)
python -m unittest discover -s rebuild_pipeline/tests -p '*_test.py' -v

# pipeline stages (need network + the big source trees, see below)
python rebuild_pipeline/01_harvest_overpass.py --config rebuild_pipeline/config_europe.yaml
python rebuild_pipeline/02_build_topology.py   --config rebuild_pipeline/config_europe.yaml
python rebuild_pipeline/03_validate.py         --config rebuild_pipeline/config_europe.yaml

# web map tiles (needs the two GeoPackages and tippecanoe on PATH)
python webmap/build_tiles.py --data-root /path/to/geopackages
python webmap/serve_local.py        # PMTiles needs byte-range requests
```

Harvest and build outputs (`harvest/`, `out/`) are gitignored working
directories. The GeoPackages are downloaded from Zenodo, not tracked here.

## Hard rules

1. Never commit `*.gpkg` or `*.zip`, and never loosen `.gitignore` - the
   dataset is distributed through Zenodo, not through git. `setup_repo.sh`
   step 5 is the guard logic; keep it passing. No LFS, nothing over 50 MB.
2. Provenance rule, verbatim from the dataset docs: values are `sourced:`,
   `inferred:` or `unknown`. Never turn an `unknown` into a plausible value,
   and never remove `inferred:` without adding a public citation.
3. Claims ceiling: this is a screening-grade topological dataset. Not
   survey-grade, not an asset register, not operational data, no forecast
   loading, no investment evidence. State limits before capabilities in any
   doc you write, and in any user-visible string in `docs/`.
4. Attribution: every derived artefact credits "(c) OpenStreetMap
   contributors, ODbL 1.0". Method attribution per
   `LICENCE_AND_ATTRIBUTION.md` (Xiong et al. 2025, PyPSA-Eur, pandapower).
   Warm, complementary posture to PyPSA-Eur and the wider open-energy
   community - this dataset extends published work and says so.
5. Published tiles carry their build command in their own metadata: build
   them with relative paths (see `webmap/build_tiles.py`) so no local
   filesystem path ships to the web.
6. Commits: author Duncan <duncan@continuum.industries>, committer Claude
   <noreply@anthropic.com> (the verification hook requires the committer).

## Working notes

Development interpreter: `/Users/duncan/miniforge3/envs/letscode/bin/python`
(any environment with geopandas/pyogrio, numpy, scipy and pypsa will do).
