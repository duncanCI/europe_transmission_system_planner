# CLAUDE.md - europe_transmssion_system_planner

Rebuild pipeline, methodology and evidence for the European Grid Topology
Dataset: 36 countries, 50-750 kV, 91,094 AC spans, 75,315 buses, 72 DC links,
4,753 transformers, built from OpenStreetMap (ODbL 1.0). The GeoPackages
themselves are NOT in this repo - they publish on Zenodo as
DOI 10.5281/zenodo.22043867 (draft until Duncan presses publish).

## Status

Private until the Zenodo deposit is published and Duncan signs off the
pre-public review below (the DOI is already wired into README.md and
CITATION.cff on disk). Do not change repo visibility, add collaborators, or
publish anything from this repo yourself.

## Commands

```sh
# tests (fixture, gate, mutation, validator suites)
python -m unittest discover -s rebuild_pipeline/tests -p '*_test.py' -v

# pipeline stages (need network + the big source trees, see below)
python rebuild_pipeline/01_harvest_overpass.py --config rebuild_pipeline/config_europe.yaml
python rebuild_pipeline/02_build_topology.py   --config rebuild_pipeline/config_europe.yaml
python rebuild_pipeline/03_validate.py         --config rebuild_pipeline/config_europe.yaml
```

Interpreter: `/Users/duncan/miniforge3/envs/letscode/bin/python`. Harvest and
build outputs (`harvest/`, `out/`) are gitignored working directories. The
authoritative source trees and built GeoPackages live in the surrounding
campaign folder, not in git.

## Hard rules

1. Never commit: `*.gpkg`, `*.zip`, anything from `screen_v1/`,
   `internal_pipeline/`, `scenario_inputs/`, `campaign/`, `authoritative_raw/`,
   `INTERNAL_REVIEW_OUTPUTS/`, fork-handoff or certification folders, or
   `supporting/prior_art_assessment.json` (self-declared internal supporting
   material). The `.gitignore` enforces all
   of this; never loosen it. `setup_repo.sh` step 5 is the guard logic - keep
   it passing.
2. Git history is permanent and this repo's destiny is public. If a commit ever
   lands with commercial, register or client material in it, stop and surface
   to Duncan - do not just delete the file in a follow-up commit.
3. Provenance rule, verbatim from the dataset docs: values are `sourced:`,
   `inferred:` or `unknown`. Never turn an `unknown` into a plausible value,
   and never remove `inferred:` without adding a public citation.
4. Claims ceiling: this is a screening-grade topological dataset. Not
   survey-grade, not an asset register, not operational data, no forecast
   loading, no investment evidence. State limits before capabilities in any
   doc you write.
5. Attribution: every derived artefact credits "(c) OpenStreetMap contributors,
   ODbL 1.0". Method attribution per `LICENCE_AND_ATTRIBUTION.md` (Xiong et al.
   2025, PyPSA-Eur, pandapower). Warm, complementary posture to Open Energy
   Transition and PyPSA-Eur always; never a competitive framing, and never
   name commercial competitors anywhere.
6. Commits: author Duncan <duncan@continuum.industries>, committer Claude
   <noreply@anthropic.com> (the verification hook requires the committer).
   No LFS, nothing over 50 MB.

## Pre-public review (completed 2026-08-21)

All three checklist items were reviewed and resolved before the visibility
flip: TSO mentions in `supporting/README_methodology.md` are citation only;
internal-process references were trimmed from the authoritative survey report
and `survey_sources.csv`; the "What is NOT open" wording in
`LICENCE_AND_ATTRIBUTION.md` is generic. A tracked-tree sweep for engagement
and account terms came back clean. Do not re-run; new material added after
this date gets its own review before it is committed.

## Roadmap context (decided 2026-08-21)

Next engineering rungs live in the ops repo's CLAUDE.md: v4 Europe-wide N-1
screening (PTDF + LODF), then v5 linear dispatch on representative TYNDP hours.
Everything is market intelligence, never a platform capability claim. The v24
Norway weave (`patch_v24.py`, `nve_additions_v24.gpkg`, `V24_REVIEW.md`) is a
prepared go/no-go: if taken, it becomes a new Zenodo version under the same
concept DOI, not a git-tracked dataset.
