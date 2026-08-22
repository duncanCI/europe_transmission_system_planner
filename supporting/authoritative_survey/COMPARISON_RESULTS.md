# Authoritative vs OSM: round-1 comparison results

2026-08-19. Six countries compared nationally, one regionally, from the files your
download run fetched. Method per country: geodesic route-km by voltage class both
sides; two-way coverage (share of one side's length within 100 m/250 m of the
other); substation matching at 250 m with voltage agreement. Machine-readable
per-country results in `out/*.json` (note: the JSONs carry an auto-suggested
verdict whose subset-case branches were mislabelled; the table below is the
corrected read and is what stands).

**Nothing has been changed in the dataset.** The verdicts below are proposals for
your review.

## Verdict table

| Country | Authoritative km | OSM km (same scope) | Auth in OSM, 250 m | OSM in auth, 250 m | Verdict |
|---|---|---|---|---|---|
| FR (RTE 45-400 kV, 2023) | 88,758 | 99,646 | 98.1% | 96.9% | **keep-osm, validated** - near-total mutual agreement; harvest the 1.9% RTE-only (~1,670 km) as an OSM-gap patch list |
| NO (NVE >=33 kV) | 32,182 | 29,102 | 93.2% | 92.5% | **fuse, targeted** - the strongest case: ~2,200 km NVE-only (mostly 45-73 kV regional), 611 stations OSM lacks, 95% voltage agreement on 937 matched stations |
| PL (BDOT10k >=110 kV) | 41,128 | 48,935 | 97.9% | 94.8% | **keep-osm** + take the 2.1% BDOT-only as a delta list; bands, no kV |
| EE (ETAK >=50 kV) | 4,248 | 4,938 | 97.4% | 93.2% | **keep-osm** + 2.6% ETAK-only delta list; 330 kV agrees to 1% |
| BE (NGI Top10Vector) | 5,717 | 7,052 | 97.6% | 89.4% | **keep-osm** - authoritative is a subset and its voltage is an undecoded 1-6 code |
| LU (INSPIRE cadastre) | 644 | 625 | 85.2% | 87.2% | **investigate** - 15% mutual disagreement on a tiny network; one QGIS session settles it |
| IT/Veneto (regional) | - | 9,627 in bbox | - | 51.4% | **keep-osm** - regional layer misses half the HV grid and has no voltage field |

## Three findings bigger than any single verdict

1. **OSM's geometry is vindicated.** In every country with a national
   authoritative layer, 93-98% of the official network lies within 250 m of our
   OSM-built lines - and the agreement holds voltage-matched where both sides
   carry kV. The dataset's base layer does not need replacing anywhere surveyed.
2. **The route-km gaps at high voltage are accounting, not geometry.** OSM FR
   400 kV is 21,686 km against RTE's 13,691 - but RTE's published 400 kV
   circuit length is ~21,700 km, and coverage is symmetric at ~98%. Consistent
   with per-circuit mapping in OSM France (and the same pattern at FR 225,
   EE 110, PL 110). Open question for the README: our "route-km" at these
   voltages behaves like circuit-km. Worth resolving before quoting route-km
   against a TSO's own figures.
3. **Norway is where fusion pays.** NVE's regional tiers (45-73 kV, ~1,800 km
   OSM lacks or misclassifies) plus 611 unmatched stations with numeric kV and
   commissioning years, under attribution-only NLOD. Everything else surveyed is
   confirmation, not addition.

## Failed this round, with the fix

| Item | What happened | Fix |
|---|---|---|
| FR ODRE current-edition exports | Fetched but geometry is null (attributes only) - so no national FR substation layer yet, and lines stay on the 2023 snapshot | Browser session on odre.opendatasoft.com export page, or the Geo-IDE per-departement sweep |
| NL Liander | Layer ids 0-6 guessed wrong; the catalogue names the real ones | `download_round2.sh`: layers 632/638 (HV cables/overhead), 641 (HV stations) |
| CH BFE >=36 kV | geodienste.ch returned its download page, not the file (needs a session) | One browser click, then drop the gpkg in the folder |
| ES CNIG BTN Energia | Portal session page, not the zip | Manual path in section C of the script |
| SI GURS WFS | GetFeature 400 | Try the ATOM feed in a browser (dataset SI.GURS.KGI) |
| GB SSEN Transmission | 42-byte error stubs - anonymous export refused | Free portal login once, re-run those four URLs |
| CZ ZABAGED | Downloaded (3.7 GB) but too big to stage | Extract locally: needs only ft_at030 + ft_ad030 from the FGDB; command in `download_round2.sh` |

## Proposed v24 weave (needs your go/no-go per row)

1. NO: add NVE-only geometry and stations, `source=NVE Nettanlegg (NLOD 1.0)`
   per feature, OSM untouched elsewhere.
2. FR: emit the 1,670 km RTE-only list as a review file first - the 2023
   snapshot means some of it may since have been built into OSM or
   decommissioned.
3. EE/PL: small delta files for eyeball review, no automatic merge.
4. BE/LU/IT: no action.
5. Attribution block gains one line per fused source; ODbL position unchanged
   (all fused sources are attribution-only licences).

## Final verdict on everything downloaded (2026-08-19, round 1 closed)

Denmark skipped by choice; CZ/SE/FI/DK and the failed fetches stay open only if
wanted later. One line per folder on disk:

| On disk | Verdict | Why |
|---|---|---|
| NO - NVE lines + stations | **MERGE** | ~2,200 km of 45-73 kV regional network and 611 stations we lack; numeric kV, build years, attribution-only licence |
| FR - RTE lines (national, 2023) | keep ours, validated | 98% mutual agreement over 88,758 km; 1,670 km RTE-only becomes a gap review list |
| FR - RTE postes, Haute-Loire | keep ours, validated | 24 of 28 official substations matched ours within 250 m, median offset 29 m - strong spot-check of bus placement |
| PL - BDOT10k >=110 kV | keep ours | official layer is a subset (97.9% inside ours); 2.1% delta list |
| EE - ETAK >=50 kV | keep ours | same shape: subset + 2.6% delta list; 330 kV lengths agree to 1% |
| BE - NGI Top10Vector | keep ours | subset, voltage is an undecoded 1-6 code |
| LU - INSPIRE cadastre | eyeball in QGIS | 15% mutual disagreement on 644 km - too small to automate, too big to ignore |
| IT Veneto / Basilicata / Bolzano / Arezzo | keep ours | regional files covering 41-51% of their own region's HV grid, mostly voltage-less; no action |
| CH - Sachplan corridors | not topology - planned-corridor source | 74 facilities + 158 federal planning measures = future-corridor pipeline, planned-corridor material |
| GB - NESO ETYS boundaries | not topology - congestion-screening reference | 34 study boundaries to label congestion-screen corridors the way NESO does |
| CH anlagen / ES CNIG / SI / GB SSEN / NL Liander | not fetched (portal sessions / wrong layer ids) | fixes in download_round2.sh, none blocks anything |

Net: one merge (Norway), two side-products (CH Sachplan -> register, ETYS ->
screen), everything else confirms the dataset as built. Awaiting go/no-go on the
Norway weave.
