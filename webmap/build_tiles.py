#!/usr/bin/env python
"""Build the vector tiles behind docs/index.html from the two GeoPackages.

Reads the published dataset (europe_grid_topology.gpkg, europe_grid_graph.gpkg),
exports the four map layers as GeoJSONSeq, and runs tippecanoe twice to produce
docs/europe_grid_v23_linework.pmtiles (AC lines + DC links, z0-10) and
docs/europe_grid_v23_points.pmtiles (sites + transformers, z4-11). The viewer
overzooms beyond the tiled maximum. Attribute values - including `*_source` columns and
`unknown` - are passed through verbatim; the map never invents a value.

Requires: geopandas/pyogrio (any recent version) and tippecanoe on PATH
(`brew install tippecanoe`). The GeoPackages are NOT in this repository -
download them from the Zenodo deposit (DOI 10.5281/zenodo.22043867) or point
--data-root at a folder that holds them.

Usage:
    python webmap/build_tiles.py --data-root /path/to/geopackages
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import geopandas as gpd

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = REPO_ROOT / "docs"

# map layer -> (gpkg file, gpkg layer, columns kept for the map)
LAYERS = {
    "ac_lines": (
        "europe_grid_graph.gpkg",
        "ac_line_all",
        [
            "line_id", "voltage_kv", "ref", "line_label", "line_label_source",
            "operator", "n_circuits", "circuits_source", "frequency_hz",
            "frequency_source", "under_construction", "countries",
        ],
    ),
    "dc_links": (
        "europe_grid_topology.gpkg",
        "dc_link",
        [
            "name", "voltage_kv", "p_nom_mw", "p_nom_source", "status",
            "countries",
        ],
    ),
    "sites": (
        "europe_grid_graph.gpkg",
        "site_all",
        [
            "bus_id", "station_name", "node_type", "voltage_kv",
            "station_voltages_kv", "operator", "countries", "frequency_hz",
            "frequency_source", "n_lines",
        ],
    ),
    "transformers": (
        "europe_grid_topology.gpkg",
        "transformer",
        [
            "transformer_id", "station_name", "voltage0_kv", "voltage1_kv",
            "s_nom_mva", "parameters_source",
        ],
    ),
}

# output file -> (droppable layers, never-drop layers, minzoom, maxzoom).
# never-drop layers (the 72 DC links) are tiled in a separate pass with no
# feature dropping, then merged with tile-join: the size-guard flags on the
# dense AC pass were silently thinning DC links at low zooms (66/72 at z0).
RUNS = {
    "europe_grid_v23_linework.pmtiles": (["ac_lines"], ["dc_links"], "0", "10"),
    "europe_grid_v23_points.pmtiles": (["sites", "transformers"], [], "4", "11"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", type=Path, required=True,
                    help="folder holding the two GeoPackages")
    args = ap.parse_args()

    failed = False
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        exports: dict[str, Path] = {}
        for name, (gpkg, layer, cols) in LAYERS.items():
            src = args.data_root / gpkg
            if not src.exists():
                print(f"missing {src} - download from Zenodo first", file=sys.stderr)
                return 1
            gdf = gpd.read_file(src, layer=layer, columns=cols)
            path = tmp / f"{name}.geojsonl"
            gdf.to_file(path, driver="GeoJSONSeq")
            exports[name] = f"{name}.geojsonl"
            print(f"exported {name}: {len(gdf)} features")

        DOCS.mkdir(parents=True, exist_ok=True)
        common = [
            "--name", "European Grid Topology v23",
            "--attribution", "&copy; OpenStreetMap contributors, ODbL 1.0",
        ]
        # tippecanoe records its full command line in the tile metadata
        # (generator_options), which ships to the public web. Everything runs
        # in the temp cwd under bare filenames so no local path is published.
        for out_name, (drop_layers, keep_layers, minz, maxz) in RUNS.items():
            out = DOCS / out_name
            cmd = [
                "tippecanoe", "-o", out_name, "--force", "--quiet", *common,
                "--drop-densest-as-needed",
                "--coalesce-densest-as-needed",
                "--extend-zooms-if-still-dropping",
                "--simplification", "8",
                "--minimum-zoom", minz,
                "--maximum-zoom", maxz,
            ]
            for name in drop_layers:
                cmd += ["-L", f"{name}:{exports[name]}"]
            subprocess.run(cmd, check=True, cwd=tmp)
            if keep_layers:
                cmd = [
                    "tippecanoe", "-o", f"keep_{out_name}", "--force",
                    "--quiet", *common, "-r1",
                    "--maximum-tile-bytes", "2500000",
                    "--minimum-zoom", minz, "--maximum-zoom", maxz,
                ]
                for name in keep_layers:
                    cmd += ["-L", f"{name}:{exports[name]}"]
                subprocess.run(cmd, check=True, cwd=tmp)
                subprocess.run([
                    "tile-join", "-o", f"merged_{out_name}", "--force", "-pk",
                    *common, out_name, f"keep_{out_name}",
                ], check=True, cwd=tmp)
                (tmp / f"merged_{out_name}").replace(tmp / out_name)
            shutil.move(str(tmp / out_name), out)
            size_mb = out.stat().st_size / 1e6
            print(f"wrote {out.name} ({size_mb:.1f} MB)")
            if size_mb > 45:
                print(f"WARNING: {out.name} over 45 MB - reduce maxzoom or raise "
                      "simplification before committing (repo hard limit is "
                      "50 MB, no LFS)", file=sys.stderr)
                failed = True

    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
