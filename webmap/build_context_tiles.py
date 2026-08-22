#!/usr/bin/env python
"""Build docs/europe_grid_v23_context.pmtiles - the temporal and scenario
context layers behind the map's year slider.

Tile layers built from the sanitised public export (a set of GeoJSON files)
produced by internal compilation tooling. Attribute values - including the
sourced:/inferred:/unknown provenance prefixes - pass through verbatim. Most
layers are public-plan or OSM fact with per-feature citations; the `tyndp`
layer is the exception and carries its own licence (see below).

  projects           Planned grid developments compiled from public national
                     and TSO network development plans (NESO "Beyond 2030",
                     Terna PdS 2025, RTE's project catalogue, MITECO's 2024
                     planning modification, and the plans cited per feature
                     in source_doc/source_url; TYNDP investment numbers are
                     quoted only where a national plan states them verbatim).
                     Promoter-stated service windows with verbatim date
                     language. Geometry is either sourced
                     plan geometry (geometry_kind says so) or a straight
                     schematic between matched public endpoint locations -
                     never a route alignment.

  tyndp              ENTSO-E TYNDP 2026 project portfolio (preliminary draft):
                     transmission and storage projects with ENTSO-E's own
                     commissioning years, plus the study corridors drawn
                     around them - broad zones under study, NOT routes. This
                     is NOT open data: the scenario figures are CC BY 4.0 but
                     the project portfolio is ENTSO-E's, published here by
                     ENTSO-E's permission. See
                     LICENCE_AND_ATTRIBUTION.md before reusing it.

  fr_sddr            RTE's SDDR 2025 works programme, from the Cart'Elec map
                     built for the CNDP public debate. Classes: new build,
                     adaptation/connection, like-for-like renewal, substation
                     sites, and the Phase 1/2 reinforcement ZONES that RTE
                     publishes without routes. Carries NO scheme name, year or
                     voltage - the SDDR publishes no project register. (c) RTE
                     / CNDP, NOT open data, held by permission.

  scenario_stations  One point per >=220 kV backbone station with TYNDP 2026
                     scenario demand and generation (NT+ 2030/35/40, LEV and
                     HEV 2035/40), spatially disaggregated from national
                     figures by OSM population and plant patterns. Inferred
                     visualization weights - not forecasts, not dispatch.
                     ENTSO-E TYNDP 2026 Scenarios, CC BY 4.0.

The demand (places) and generation (plants) layers carry static national
shares; the viewer multiplies them by the national totals in
scenario_totals.json (copied to docs/ by this script), so scenario and
horizon switching needs no tile rebuild.

Tiling contract (fixes the "schemes vanish when you zoom out" defect):
projects and the TYNDP portfolio are the CONTENT of the year slider, so they
are tiled with no RATE or SIZE dropping at any zoom (a raised per-tile byte
budget instead of --drop-densest-as-needed). Note the residual limit: a
feature shorter than one tile coordinate unit still collapses geometrically,
which costs a few percent at z0-z1 only (projects 2,971 of 3,026; tyndp 266 of
284) and nothing from z2 up, where counts exceed the source through
tile-boundary duplication. The
dense context point/polygon layers start at z4 - matching the viewer's layer
minzooms - with -r1 keeping every point and dropping only as a last-resort
tile-size guard. The two runs are merged with tile-join. Everything runs in a
temp cwd under bare filenames because tippecanoe stamps its full command line
into the published tile metadata (generator_options).

Usage:
    python webmap/build_context_tiles.py --export-dir path/to/public_export
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = REPO_ROOT / "docs"
OUT = DOCS / "europe_grid_v23_context.pmtiles"

NAME = "European Grid Topology v23 - development and scenario context"
ATTRIBUTION = ("&copy; OpenStreetMap contributors ODbL 1.0; "
               "scenario figures: ENTSO-E TYNDP 2026 Scenarios (CC BY 4.0); "
               "TYNDP 2026 project portfolio &copy; ENTSO-E and SDDR 2025 "
               "works &copy; RTE/CNDP, both published by permission "
               "(not open data - contact the publisher to reuse)")

# never-drop layers: every feature present at every zoom (0-10)
FULL_LAYERS = {
    "projects": "projects_public.geojson",
    # ENTSO-E TYNDP 2026 portfolio (by permission). Tiled through the
    # never-drop pass for the same reason as the projects: MapLibre's own
    # GeoJSON simplification silently discards small features at low zoom,
    # which is exactly the defect this build path exists to avoid.
    "tyndp": "tyndp_projects_public.geojson",
    # RTE SDDR 2025 works (RTE/CNDP, by permission). Never-drop, like the
    # other planned layers: France is already the worst-covered large country
    # and thinning it at zoom would compound that.
    "fr_sddr": "fr_sddr_public.geojson",
}
# dense context layers: z4+ (viewer minzoom), -r1, size-guard backstop
CONTEXT_LAYERS = {
    "scenario_stations": "scenario_stations_public.geojson",
    "places": "places_public.geojson",
    "plants": "plants_public.geojson",
    # present only once the plant-geometry harvest has run
    "plant_polys": "plants_polygons_public.geojson",
}


def layer_args(layers: dict[str, str], export_dir: Path, tmp: Path) -> list[str]:
    out: list[str] = []
    for layer, fname in layers.items():
        path = export_dir / fname
        if not path.exists():
            print(f"skipping layer {layer}: {fname} not present")
            continue
        link = tmp / fname
        if not link.exists():
            link.symlink_to(path.resolve())
        out += ["-L", f"{layer}:{fname}"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export-dir", type=Path, required=True,
                    help="folder holding the sanitised public export")
    args = ap.parse_args()

    DOCS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        subprocess.run([
            "tippecanoe", "-o", "full.pmtiles", "--force", "--quiet",
            "--name", NAME, "--attribution", ATTRIBUTION,
            "-r1",   # no point rate-dropping: every project at every zoom
            "--maximum-tile-bytes", "2500000",
            "--minimum-zoom", "0", "--maximum-zoom", "10",
            *layer_args(FULL_LAYERS, args.export_dir, tmp),
        ], check=True, cwd=tmp)
        subprocess.run([
            "tippecanoe", "-o", "ctx.pmtiles", "--force", "--quiet",
            "--name", NAME, "--attribution", ATTRIBUTION,
            "-r1", "--drop-densest-as-needed",
            "--maximum-tile-bytes", "2000000",
            "--minimum-zoom", "4", "--maximum-zoom", "10",
            *layer_args(CONTEXT_LAYERS, args.export_dir, tmp),
        ], check=True, cwd=tmp)
        subprocess.run([
            "tile-join", "-o", "merged.pmtiles", "--force", "-pk",
            "--name", NAME, "--attribution", ATTRIBUTION,
            "full.pmtiles", "ctx.pmtiles",
        ], check=True, cwd=tmp)
        shutil.move(str(tmp / "merged.pmtiles"), OUT)

    shutil.copyfile(args.export_dir / "scenario_totals.json",
                    DOCS / "scenario_totals.json")

    size_mb = OUT.stat().st_size / 1e6
    print(f"wrote {OUT.name} ({size_mb:.1f} MB) and scenario_totals.json")
    return 0 if size_mb <= 45 else 2


if __name__ == "__main__":
    raise SystemExit(main())
