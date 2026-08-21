# Authoritative grid geometry: 36-country survey and comparison plan

2026-08-19. Five research agents surveyed what TSOs, regulators, national mapping
agencies and DNOs actually publish for download, per country, with licences read
verbatim and every URL copied from a fetched page. 89 sources assessed:
12 supersede OSM on their patch, 41 complement it, 25 are metadata-only, 11
unusable. 15 countries verified as publishing nothing usable. Full evidence:
`survey_sources.csv` (one row per source, with notes) and `survey_full.json`.

**The one blocker:** this container's egress proxy refuses connections to all of
these hosts, so nothing could be downloaded here. `download_authoritative.sh` in
the project folder fetches everything licence-clean in one run on your machine
(~10 minutes, mostly small files; the one big item is Czechia at 3.7 GB, skippable).
When it finishes, say so - staging and the per-country comparison run from there
with no further downloads.

## Where authoritative data is worth having (script fetches these)

| Country | Source | Licence | What it adds over OSM |
|---|---|---|---|
| France | RTE lines via data.gouv.fr mirror + ODRE current-edition attempt | Licence Ouverte 2.0 | The workhorse: full RTE overhead + underground. Caveats: mirror is a 2023-06 snapshot (the script also tries RTE's 2026-06 edition directly); **no voltage field in the line schema** - voltage joins via line names/ouvrage refs |
| Norway | NVE Nettanlegg (lines by tier + transformer stations) | NLOD 1.0 | Transmission and regional nets as separate layers, station points; live per-feature edit dates |
| Switzerland | BFE elektrische Anlagen >=36 kV + Sachplan corridors | Opendata BY | Statutory register of all >=36 kV installations |
| Czechia | CUZK ZABAGED (lines + substations) | CC BY 4.0 | 1.5 m precision, numeric kV attribute, the only country with authoritative lines AND substations. 3.7 GB whole-topo download |
| Estonia | ETAK tehnovorgud | Own open licence (commercial reuse explicit) | Captured from 1 kV, weekly refresh, 2.8 MB |
| Slovenia | GURS ZKGJI utility cadastre WFS | CC BY 4.0 (portal) | Operator-fed national cadastre. Licence divergence to resolve: WFS terms point at GURS general conditions |
| Poland | BDOT10k OT_SULN_L GeoParquet | Statutory free reuse | National single-file 1:10k lines; voltage as four bands, not kV |
| Belgium | NGI Top10Vector high-voltage network | CC BY 4.0 | National topo HV layer, GeoPackage |
| Luxembourg | INSPIRE ElectricityNetwork (links + stations) | CC0 | Complete official pair |
| Netherlands | Liander Open Data Elektra (ArcGIS) | CC BY 4.0 | DSO layer for most of NL; TenneT itself publishes only viewers |
| Spain | CNIG BTN Energia GeoPackage | CNIG licence, stated CC-BY-compatible | Only national-coverage candidate in the south, 38 MB |
| Italy | Veneto WFS, Basilicata DBT, South Tyrol (CC0, has VOLTAGE), Arezzo | IODL 2.0 / CC0 / CC BY | Regional patches only; **Veneto has no voltage attribute at all** |
| GB | SSEN Transmission x4 (lines + substations, CC BY 4.0), NESO ETYS boundaries | CC BY 4.0 / NESO Open Licence | North Scotland transmission authoritative; ETYS boundaries for constraint context |

Needs your (free) account, one manual download each - script section C lists the
click-paths: Denmark GeoDanmark, Sweden Lantmateriet Topografi 10, Finland MML
Maastotietokanta.

## Licence-blocked or gone - validation-only at best, no fusion

| Source | Why |
|---|---|
| Energinet (DK TSO lines + stations) | ISO metadata carries severe use restrictions despite empty WFS fees fields |
| Svenska kraftnat | Host robots-blocked and proxy-refused; licence unresolved |
| Andalucia AAE (400/220/132/66/50 kV, REE+Endesa-sourced) | "Todos los derechos reservados" - a permission request, not a download |
| HOPS WFS (HR) | Access "on request for a fee" |
| Lithuania ESO | Public access withdrawn 2025-06-01 to a contractor-gated portal |
| NGET route maps | Custom, very restrictive licence |
| UKPN / ENWL / SPEN / NGED | Login-gated with bespoke shared-data licences nobody has read; two PDFs to read would unblock a large share of the GB 132 kV+ estate |
| Austria APG | INSPIRE-restricted, no open licence |
| Ireland | EirGrid and ESB publish nothing downloadable. The Republic stays OSM-only unless a licensing conversation is opened directly |

Nothing usable: PT, GR, RO*, BG*, RS, BA, ME, MK, AL, XK, MD, UA, IM, JE, GG
(*RO/BG are unverified-negative - the INSPIRE geoportal's redirect broke
theme-filtered search this session; worth one browser pass later.)

## Three rules for the comparison phase, set by what the survey found

1. **OSM stays the voltage authority.** Only Czechia gives a clean numeric kV
   field. France has none, Poland has bands, Estonia/Slovenia unconfirmed,
   Veneto none. Authoritative layers are geometry and existence evidence.
2. **Mixable-for-us is not mixable-for-OSM.** CC BY 4.0 suffices for our ODbL
   derived database with attribution; it does not licence upstream OSM edits
   (the GB waiver saga). We are building the former, not the latter.
3. **Substations lag lines everywhere.** Only CZ has a national authoritative
   pair; NVE and SSEN-T have stations for their patches; NIE has NI sites but
   no circuits. Bus-level validation stays OSM-anchored.

## Cheap follow-ups surfaced by the survey (not started)

ETYS Appendix B circuit tables (NESO + SSEN-T publish machine-readable circuit,
transformer and fault-level series under open licences) - the fastest
authoritative check on GB connectivity and real impedances/ratings, no geometry
involved. Two one-question emails: GIS-Centras (does GDR50LT fall under the
CC BY 4.0 open-data terms - its ELEKTR_L layer has kV + a 35 kV floor) and LGIA
(same for Topo50). Two licence PDFs to read: SPEN and NGED shared-data licences.
One browser probe each: Fingrid's viewer backend, GSE's Italian substation app,
geodata.gov.gr CKAN.

## What happens when the files land

Per country: route-km by voltage class (authoritative vs OSM), two-way coverage
at 100 m/250 m buffers, substation matching at 250 m/500 m with voltage
agreement - the harness is built and self-tested (identity = 1.0, 500 m
perturbation collapses coverage, licence gate fires, floor scoping works). Output
is a per-country verdict table - fuse / partial / keep-osm / blocked-licence -
with the numbers behind it. Nothing is woven into the dataset until you have
reviewed that table.

## Decisions in force alongside this survey (2026-08-19)

Gating split confirmed: the dataset publishes openly (Zenodo DOI; public
no-LFS repo via the rewritten `setup_repo.sh`). Commercial screening material
is maintained separately, outside this repository, and none of it feeds the
published dataset.
