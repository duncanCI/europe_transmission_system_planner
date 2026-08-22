# Licence and attribution

## The data is OpenStreetMap data

`europe_grid_topology.gpkg` and `europe_grid_graph.gpkg` are a **derived database** of
OpenStreetMap, harvested 2026-08-14 via Overpass. They are therefore governed by the
**Open Database Licence 1.0 (ODbL)**: https://opendatacommons.org/licenses/odbl/1-0/

Three obligations follow:

1. **Attribute.** Any distribution, screenshot, map, report or slide derived from
   these files must credit OpenStreetMap contributors. The standard form is
   "© OpenStreetMap contributors, ODbL 1.0".
2. **Share alike.** If you distribute the database, or a modified version of it, you
   must offer it under ODbL 1.0. Producing an image, a route or a numerical result
   from it (a "produced work") does not oblige you to publish the database, but it
   does oblige you to state where the data came from.
3. **Keep it open.** You may not apply technical measures that restrict a
   recipient's rights under the licence.

## The scenario figures are ENTSO-E's

`docs/scenario_totals.json` and the scenario fields carried in the context tiles hold
national demand and generation figures from the **ENTSO-E TYNDP 2026 scenarios**
(National Trends+, and the Low and High Economy Variants), published by ENTSO-E under
**CC BY 4.0**: https://creativecommons.org/licenses/by/4.0/. Redistributing them here
is permitted on that basis, and the credit form is "© ENTSO-E TYNDP 2026 Scenarios,
CC BY 4.0".

Two limits on what those figures are. They are national totals: anything shown below
national level in the web map is `inferred:`, shared out by OSM patterns as a
visualisation weight, and is not a forecast. And this covers the **scenario figures
only** - the TYNDP project portfolio is not open data, is not redistributed here, and
is not a source of any layer in this repository.

## Method attribution

The build recreates the method of:

> Xiong, B., Fioriti, D., Neumann, F., Riepin, I. and Brown, T. (2025).
> Modelling the high-voltage grid using open data for Europe and beyond.
> *Scientific Data* 12:277. https://doi.org/10.1038/s41597-025-04550-7

The reference implementation is the PyPSA-Eur workflow
(https://github.com/PyPSA/pypsa-eur), MIT licensed. Open Energy Transition's
Open-TYNDP (https://github.com/open-energy-transition/open-tyndp) is a soft-fork of
that workflow developed with ENTSO-E and takes its base network from the same OSM
method; this build shares that foundation and diverges from it deliberately (see
`supporting/README_methodology.md`).

Transformer parameters cite pandapower v3.1.2 standard types
(https://github.com/e2nIEE/pandapower, BSD-3) and PyPSA-Eur commit `8119040`.

## The code in this repository

`rebuild_pipeline/` is our own work, written against the documented method. The code
in this repository is released under the **MIT Licence** (see `LICENSE` in the
repository root), which keeps it compatible with the upstream workflow it
reimplements. That grant covers the code only. The data the pipeline harvests and
builds is a derived database of OpenStreetMap and stays under **ODbL 1.0**, with the
obligations set out above: an MIT licence on the code does not relicense the data.

## What is NOT open

Some of the working material behind this build is internal and is deliberately not
part of this repository, the published dataset or any of the licences above. It is
not distributed, and `.gitignore` keeps it out of the tracked tree. What is published
here - the pipeline, the documentation and the published dataset (DOI [10.5281/zenodo.22043867](https://doi.org/10.5281/zenodo.22043867)) - is covered
by the terms set out in this file, and nothing else should be assumed to be.
