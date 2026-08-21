# Licence and attribution

## The data is OpenStreetMap data

`europe_grid_topology.gpkg` and `europe_grid_graph.gpkg` are a **derived database** of
OpenStreetMap, harvested 2026-08-14 via Overpass. They are therefore governed by the
**Open Database Licence 1.0 (ODbL)**: https://opendatacommons.org/licenses/odbl/1-0/

Three obligations follow, and they apply to a gated download exactly as they apply to
a public one:

1. **Attribute.** Any distribution, screenshot, map, report or slide derived from
   these files must credit OpenStreetMap contributors. The standard form is
   "© OpenStreetMap contributors, ODbL 1.0".
2. **Share alike.** If you distribute the database, or a modified version of it, you
   must offer it under ODbL 1.0. Producing an image, a route or a numerical result
   from it (a "produced work") does not oblige you to publish the database, but it
   does oblige you to state where the data came from.
3. **Keep it open.** You may not apply technical measures that restrict a
   recipient's rights under the licence.

**What that means for an email gate.** A form in front of the download is a lead
capture, not a control. Once a recipient has the file they may lawfully redistribute
it under ODbL, and you cannot licence that away. Gate it to know who is interested,
not on the assumption that it stays with them.

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

`rebuild_pipeline/` is our own work, written against the documented method. It
carries no licence grant in this repository because the repository is private. If
any of it is ever published, pick a licence first: MIT keeps it compatible with the
upstream workflow it reimplements.

## What is NOT open

Nothing in `supporting/screen_v1/` should leave the company. It maps screened
corridors to internal register and account identifiers. It is internal
supporting material.
