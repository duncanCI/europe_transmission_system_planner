# v24: NVE fusion - review before applying

2026-08-19. Adds Norwegian network from NVE Nettanlegg (licence NLOD 1.0,
attribution-only) that has no counterpart in the OSM-built layers. Nothing
existing is modified or deleted; every added row is marked
`qa_flags=nve_fused_v24` and `frequency_source/construction_source=NVE`, so the
fusion is filterable and fully reversible.

## What goes in

| Addition | Count | Detail |
|---|---|---|
| Lines | 189 (1,053 km) | 50-420 kV; dominated by 50 kV (476 km), 132 kV (264 km), 66 kV (108 km), 145 kV (97 km). By NVE tier: regionalnett 882 km, transmisjonsnett 212 km (incl. Statnett 111 km), sea cables 44 km |
| Substations | 63 | NVE stations >500 m from any OSM station, voltage known, incl. name/owner/kV |
| Junction nodes | 72 | Created where added line segments meet each other (endpoints clustered at 100 m) |

Selection rule for lines: less than 40% of the feature's length lies within
150 m of ANY existing 50 Hz line (sampled every 50 m). 3,575 NVE features
failed that test (already present) and were not touched.

## What deliberately stays out (review files beside this one)

| File | Content | Why held back |
|---|---|---|
| `review_suspected_dc_or_oddclass.geojson` | 18 features, 85 km at 230/250/350/420 kV sea-cable classes | Skagerrak-class HVDC legs would double-count the `dc_link` layer; needs eyes |
| `review_partial_coverage.geojson` | 35 features, 334 km at 40-85% overlap | Ambiguous - could be parallel routes or OSM half-mapped |
| 179 NVE stations | unknown voltage or no matching site layer | A bus needs a voltage; adding them would violate the schema's bus = station x voltage rule |
| 8,527 features < 50 kV (4,725 km) | below the dataset floor | Floor kept; noted as available if the floor ever drops |

## Honest limitations of the fused rows

- `n_circuits = 1` on every added line, `circuits_source` says inferred - NVE
  publishes traces, not circuit counts.
- Electrical parameters are typed from the dataset's existing per-voltage rule
  (`typing_used.json`), same convention as every other line: s_nom = sqrt(3)*V*I.
- 70 of 189 lines have at least one free end (`start_point/end_point =
  free_end`): they end at stations OSM lacks and which fell in the 179 held-back
  set. They are correct geometry for routeing/screening; treat them as
  non-load-flow until endpoints gain buses. 52 lines attach to the existing
  grid via snapped buses; the rest form NVE-only islands in areas OSM has no
  coverage - that is precisely why they are worth adding.
- `driftsattaar` (commissioning year) > 2026 sets under_construction=1.

## How to apply

```
cd "/Users/duncan/Claude/Projects/Europe Camapign"
python3 supporting/_xfer/patch_v24.py            # dry run, prints the plan
python3 supporting/_xfer/patch_v24.py --apply    # backs up both gpkgs first
```

Needs `nve_additions_v24.gpkg` in the same directory as the two GeoPackages
(the patch script path-checks and refuses otherwise; move it to the folder root
or run the patch from wherever the three files sit together). Tested end to
end on copies here: counts verified, spatial indexes stay consistent, re-run
refuses, revert = restore the `.v23.bak.gpkg` files it creates.

## Attribution obligation

The dataset's attribution block gains one line, required by NLOD:
"Contains data under the Norwegian Licence for Open Government Data (NLOD)
distributed by The Norwegian Water Resources and Energy Directorate (NVE)."
`LICENCE_AND_ATTRIBUTION.md` needs that sentence before the Zenodo deposit if
v24 is what gets published.
