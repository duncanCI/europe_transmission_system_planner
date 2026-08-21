#!/usr/bin/env python
"""Build docs/europe_grid_v23_context.pmtiles - the temporal and scenario
context layers behind the map's year slider.

Two tile layers, built from the sanitised public export (two GeoJSON files)
produced by internal compilation tooling. Everything in them is public-plan
fact with per-feature citations; attribute values - including the
sourced:/inferred:/unknown provenance prefixes - pass through verbatim.

  projects           Planned grid developments compiled from public network
                     development plans: ENTSO-E TYNDP 2026 project material
                     and national/TSO plans (NESO "Beyond 2030", Terna PdS
                     2025, RTE's project catalogue, MITECO's 2024 planning
                     modification, and the plans cited per feature in
                     source_doc/source_url). Promoter-stated service windows
                     with verbatim date language. Geometry is either sourced
                     plan geometry (geometry_kind says so) or a straight
                     schematic between matched public endpoint locations -
                     never a route alignment.

  scenario_stations  One point per >=220 kV backbone station with TYNDP 2026
                     scenario demand and generation (NT+ 2030/35/40, LEV and
                     HEV 2035/40), spatially disaggregated from national
                     figures by OSM population and plant patterns. Inferred
                     visualization weights - not forecasts, not dispatch.
                     ENTSO-E TYNDP 2026 Scenarios, CC BY 4.0.

The demand (places) and generation (plants) layers carry static national
shares; the viewer multiplies them by the national totals in
scenario_totals.json (copied to docs/ by this script), so scenario and
horizon switching needs no tile rebuild. -r1 keeps every point at every zoom
(the tile-size guard still thins the very lowest zooms if needed).

Usage:
    python webmap/build_context_tiles.py --export-dir path/to/public_export
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = REPO_ROOT / "docs"
OUT = DOCS / "europe_grid_v23_context.pmtiles"

LAYERS = {
    "projects": "projects_public.geojson",
    "scenario_stations": "scenario_stations_public.geojson",
    "places": "places_public.geojson",
    "plants": "plants_public.geojson",
    # present only once the plant-geometry harvest has run
    "plant_polys": "plants_polygons_public.geojson",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export-dir", type=Path, required=True,
                    help="folder holding the sanitised public export")
    args = ap.parse_args()

    DOCS.mkdir(parents=True, exist_ok=True)
    cmd = [
        "tippecanoe", "-o", str(OUT), "--force", "--quiet",
        "--name", "European Grid Topology v23 - development and scenario context",
        "--attribution",
        "&copy; OpenStreetMap contributors ODbL 1.0; "
        "scenario figures: ENTSO-E TYNDP 2026 Scenarios (CC BY 4.0)",
        "--drop-densest-as-needed", "-r1",
        "--minimum-zoom", "0", "--maximum-zoom", "10",
    ]
    for layer, fname in LAYERS.items():
        path = args.export_dir / fname
        if not path.exists():
            print(f"skipping layer {layer}: {fname} not present")
            continue
        cmd += ["-L", f"{layer}:{path}"]
    subprocess.run(cmd, check=True)

    shutil.copyfile(args.export_dir / "scenario_totals.json",
                    DOCS / "scenario_totals.json")

    size_mb = OUT.stat().st_size / 1e6
    print(f"wrote {OUT.name} ({size_mb:.1f} MB) and scenario_totals.json")
    return 0 if size_mb <= 45 else 2


if __name__ == "__main__":
    raise SystemExit(main())
