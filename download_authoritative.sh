#!/usr/bin/env bash
# Download the licence-clean authoritative grid sources found by the 2026-08-19
# survey, for comparison against the OSM-built dataset. Run on YOUR machine (the
# cloud container cannot reach these hosts) from inside the project folder:
#
#     cd "/Users/duncan/Claude/Projects/Europe Camapign"
#     bash download_authoritative.sh
#
# Files land in authoritative_raw/<CC>_<slug>/. When it finishes, tell Claude -
# staging and the per-country comparison run from there without further downloads.
# Every URL below was copied from a page fetched and read during the survey
# (provenance: supporting/authoritative_survey/survey_sources.csv). Sections B and
# C need a free login or one manual click each; skip them on the first pass if you
# want speed - section A alone covers 12 countries.
set -uo pipefail
mkdir -p authoritative_raw
get() {  # get <folder> <filename> <url>
  mkdir -p "authoritative_raw/$1"
  if [ -s "authoritative_raw/$1/$2" ]; then echo "SKIP $1/$2 (exists)"; return 0; fi
  echo "GET  $1/$2"
  curl -sSL --fail --retry 2 --max-time 900 -o "authoritative_raw/$1/$2" "$3"     || echo "FAIL $1/$2  <- $3"
}

echo "=== A. Direct downloads, no login ==="
get "IT_terna_pds2025" "Sintesi_tabellare_Piano_Sviluppo_2025.xlsx" "https://download.terna.it/terna/Sintesi%20tabellare%20Piano%20di%20Sviluppo%202025_8dd62ee49f5b0f4.xlsx"
get "ES_miteco_2024_modification" "Anexo_MAP.pdf" "https://www.miteco.gob.es/content/dam/miteco/es/energia/files-1/planificacion/Planificacionelectricidadygas/Documents/Anexo_MAP.pdf"
# DEFERRED DE: basemap.de basisviews is per-state, 83 MB (Berlin) to 3.6 GB (Bavaria), and whether its Leitung layer carries voltage is unconfirmed - decide after round 1: https://basemap.de/dienste/opendata/basisviews  # ~per state, 83 MB (Berlin) to 3.6 GB (Bavaria); all files dated 2026-08-19
get "FR_lignes_aériennes_rte_data_go" "lignes_aeriennes_rte.zip" "https://www.data.gouv.fr/api/1/datasets/r/9ab44d2c-3066-4074-ba1c-271002d1401d"  # ~4.6 MB (dataset page) / 4.8 MB (API resource record)
get "FR_lignes_souterraines_rte_unde" "lignes_souterraines_rte.zip" "https://atom.geo-ide.developpement-durable.gouv.fr/atomArchive/GetResource?id=0d0a1d88-d5a0-4bae-98b1-b6010d461292&dataType=dataset"
get "FR_postes_électriques_de_rte_en" "postes_rte_haute_loire.zip" "https://atom.geo-ide.developpement-durable.gouv.fr/atomArchive/GetResource?id=d61ec0a2-33b8-4400-9051-78fca55e67a3&dataType=dataset"
# DEFERRED FR: IGN BD TOPO (national, multi-GB, adds substations) - dataset page, pick one region to trial first: https://www.data.gouv.fr/datasets/bd-topo-r
get "BE_top10vector_high_voltage_net" "c6c6d674-e3c5-47a9-8398-f4e1082d3e8e_geopackage+sqlite3_4326.zip" "https://ac.ngi.be/remoteclient-open/ngi-standard-open/Vectordata/Top10Vector/Top10Vector-HighTensionNetwork/c6c6d674-e3c5-47a9-8398-f4e1082d3e8e_geopackage+sqlite3_4326.zip"
get "LU_inspire_electricitynetwork" "utilitylink.gml" "https://download.data.public.lu/resources/inspire-annex-iii-utility-and-governmental-services-electricitynetwork-utilitylink-bd-l-tc-electricity-transmission-lines-from-the-official-carto-topographic-database-3/20260612-122754/us.electricitynetwork-utilitylink.gml"
get "LU_inspire_electricitynetwork" "appurtenance_station.gml" "https://download.data.public.lu/resources/inspire-annex-iii-utility-and-governmental-services-electricitynetwork-appurtenance-electricity-station-bd-l-tc-power-stations-from-the-official-carto-topographic-database-1/20260612-122753/us.electricitynetwork-appurtenance-electricitystation.gml"
get "CH_elektrische_anlagen_mit_eine" "elektrische_anlagen_ueber_36kv.zip" "https://geodienste.ch/downloads/elektrische_anlagen_ueber_36kv?data_format=gpkg"
get "CH_sachplan_übertragungsleitung" "sachplan-uebertragungsleitungen_kraft_2056.gpkg" "https://data.geo.admin.ch/ch.bfe.sachplan-uebertragungsleitungen_kraft/sachplan-uebertragungsleitungen_kraft/sachplan-uebertragungsleitungen_kraft_2056.gpkg"
get "GB_etys_gb_transmission_system" "etys-boundary-gis-data-mar25.zip" "https://api.neso.energy/dataset/997f4820-1ad4-499b-b1fe-4b8d3d7fbc72/resource/e914fcec-1dc9-4f1f-97e7-59c0d9521bea/download/etys-boundary-gis-data-mar25.zip"
get "ES_base_topográfica_nacional_bt" "BTN_T_ENERGIA_GPKG.ZIP" "https://centrodedescargas.cnig.es/CentroDescargas/detalleArchivo?sec=12165674"  # ~38 MB; if this saves an HTML page instead of a zip, use the manual path in section C
get "IT_database_topografico_tema_re" "rete_elettr_tratto.zip" "https://rsdi.regione.basilicata.it/webGis/shape-zip/rete_elettr_tratto.zip"
get "IT_database_topografico_tema_re" "rete_elettr_nodo.zip" "https://rsdi.regione.basilicata.it/webGis/shape-zip/rete_elettr_nodo.zip"
get "IT_linee_elettriche_alta_tensio" "arezzo_rete_elettrodotti_shp.zip" "https://sit.comune.arezzo.it/metarepo2/api/datasets/rete_elettrodotti/resources/303/SHP"
get "CZ_zabaged_polohopis_základní_b" "ZABAGED-5514-fgdb-20260818.zip" "https://openzu.cuzk.gov.cz/opendata/ZABAGED-FGDB/epsg-5514/ZABAGED-5514-fgdb-20260818.zip"  # ~3,996,203,142 bytes (~3.7 GB) for EPSG:5514; ~3.8 GB for the EPSG:3045 twin at https://openzu.cuzk.gov.cz/opendata/ZABAGED-FGDB/epsg-3045/ZABAGED-3045-fgdb-20260818.zip
get "EE_eesti_topograafia_andmekogu" "ETAK_Eesti_SHP_tehnovorgud.zip" "https://geoportaal.maaamet.ee/index.php?lang_id=1&plugin_act=otsing&andmetyyp=ETAK&dl=1&f=ETAK_Eesti_SHP_tehnovorgud.zip&page_id=609"  # ~2.8 MB (tehnovõrgud thematic SHP). Full-country alternatives on the same page: ETAK_EESTI_SHP.zip 1.2 GB, ETAK_EESTI_GPKG.zip 1.3 GB
get "PL_baza_danych_obiektów_topogra" "OT_SULN_L.parquet" "https://opendata.geoportal.gov.pl/bdot10k/schemat2021/GeoParquet/OT_SULN_L.parquet"  # ~Not stated. Scale reference from GUGiK: the buildings class OT_BUBD_A is '8,34 GB w formacie GPKG, w formacie GeoParquet jest to odpowiednio 1,84 GB'; SULN will be far smaller.
# OPTIONAL lighter CZ fallback (1:50k generalised, 490 MB) if 3.7 GB is too much:
# get "CZ_data50_layer_elektrickeveden" "data50.zip" "https://openzu.cuzk.gov.cz/opendata/Data50/epsg-5514/data50.zip"  # ~490 MB (S-JTSK / EPSG:5514); 721 MB (ETRS89-TMzn / EPSG:3045 at https://openzu.cuzk.gov.cz/opendata/Data50/epsg-3045/data50.zip)

echo ""
echo "=== B. Service queries (ArcGIS REST / WFS), still no login ==="
# paged ArcGIS query: get_arcgis <folder> <name> <layer-url>
get_arcgis() {
  mkdir -p "authoritative_raw/$1"
  if [ -s "authoritative_raw/$1/$2.geojson" ]; then echo "SKIP $1/$2"; return 0; fi
  echo "GET  $1/$2 (paged)"
  local off=0 page=1000 n=0
  echo '{"type":"FeatureCollection","features":[' > "authoritative_raw/$1/$2.tmp"
  while :; do
    curl -sSL --fail --max-time 300 -o /tmp/_pg.json \
      "$3/query?where=1%3D1&outFields=*&f=geojson&outSR=4326&resultOffset=${off}&resultRecordCount=${page}" || break
    local got
    got=$(python3 -c "import json,sys;d=json.load(open('/tmp/_pg.json'));f=d.get('features',[]);print(len(f))" 2>/dev/null) || break
    [ "${got:-0}" -eq 0 ] && break
    python3 - "$off" <<'PY' >> "authoritative_raw/$1/$2.tmp"
import json,sys
f=json.load(open('/tmp/_pg.json'))['features']
pre = ',' if int(sys.argv[1])>0 else ''
print(pre + ','.join(json.dumps(x) for x in f))
PY
    n=$((n+got)); off=$((off+got))
    [ "$got" -lt "$page" ] && break
  done
  echo ']}' >> "authoritative_raw/$1/$2.tmp"
  mv "authoritative_raw/$1/$2.tmp" "authoritative_raw/$1/$2.geojson"
  echo "     $n features"
}

# Norway - NVE Nettanlegg4 (lines: 0 transmisjon luft, 1 regionalnett luft, 2-3 cables; 5 transformer stations)
for L in 0 1 2 3 5; do
  get_arcgis "NO_nve_nettanlegg" "layer${L}" "https://kart.nve.no/enterprise/rest/services/Nettanlegg4/MapServer/${L}"
done

# Netherlands - Liander Open Data Elektra: catalogue first, then common layer ids (non-fatal)
mkdir -p authoritative_raw/NL_liander
curl -sSL --fail -o authoritative_raw/NL_liander/_catalog.json \
  "https://services1.arcgis.com/v6W5HAVrpgSg3vts/arcgis/rest/services/Liander_Open_Data_Elektra/FeatureServer?f=pjson" \
  && echo "GET  NL_liander/_catalog.json"
for L in 0 1 2 3 4 5 6; do
  get_arcgis "NL_liander" "layer${L}" "https://services1.arcgis.com/v6W5HAVrpgSg3vts/arcgis/rest/services/Liander_Open_Data_Elektra/FeatureServer/${L}" || true
done

# Italy / Veneto - single SHAPE-ZIP GetFeature (URL verbatim from the survey)
get "IT_veneto_linee_elettriche" "linee_elettriche.zip" \
  "http://idt2-geoserver.regione.veneto.it/geoserver/wfs?service=WFS&VERSION=1.0.0&REQUEST=GetFeature&typeName=rv:linee_elettriche&outputFormat=SHAPE-ZIP"

# Italy / South Tyrol - CC0, has a VOLTAGE field (typenames verified via DescribeFeatureType)
get "IT_bolzano_power" "power_pipes.json" \
  "https://geoservices3.civis.bz.it/geoserver/gvcc-Infrastructures/ows?service=WFS&version=2.0.0&request=GetFeature&typenames=gvcc-Infrastructures:Power-Pipes&outputFormat=application/json&srsName=EPSG:4326"
get "IT_bolzano_power" "power_nodes.json" \
  "https://geoservices3.civis.bz.it/geoserver/gvcc-Infrastructures/ows?service=WFS&version=2.0.0&request=GetFeature&typenames=gvcc-Infrastructures:Power-Nodes&outputFormat=application/json&srsName=EPSG:4326"

# Slovenia - GURS ZKGJI electricity network (SHAPE-ZIP confirmed in GetCapabilities)
get "SI_gurs_zkgji" "electricity_cable.zip" \
  "https://ipi.eprostor.gov.si/wfs-si-gurs-ins/us-net-el/wfs?service=WFS&version=2.0.0&request=GetFeature&typeNames=us-net-el:ElectricityCable&outputFormat=SHAPE-ZIP"

# GB - SSEN Transmission OpenDataSoft exports (CC BY 4.0; anonymous export usually
# works from a browser/curl - if you get 401/403, log in once on the portal first)
get "GB_ssen_transmission" "ohl_supergrid.geojson" "https://ssentransmission.opendatasoft.com/api/explore/v2.1/catalog/datasets/ssen-transmission-overhead-line-supergrid/exports/geojson"
get "GB_ssen_transmission" "ohl_grid.geojson"      "https://ssentransmission.opendatasoft.com/api/explore/v2.1/catalog/datasets/overhead-line-grid/exports/geojson"
get "GB_ssen_transmission" "sub_supergrid.geojson" "https://ssentransmission.opendatasoft.com/api/explore/v2.1/catalog/datasets/ssen-transmission-substation-site-supergrid/exports/geojson"
get "GB_ssen_transmission" "sub_grid.geojson"      "https://ssentransmission.opendatasoft.com/api/explore/v2.1/catalog/datasets/ssen-transmission-substation-site-grid/exports/geojson"

# EXPERIMENTAL (URL pattern confirmed on a sibling dataset, not on these two):
# ODRE's own current-edition exports - if these work they replace the 2023 mirror
# snapshot above with RTE's 2026-06 edition AND add the national substation layer.
get "FR_odre_current" "lignes_aeriennes_rte_nv.geojson" "https://odre.opendatasoft.com/api/explore/v2.1/catalog/datasets/lignes-aeriennes-rte-nv/exports/geojson"
get "FR_odre_current" "postes_electriques_rte.geojson" "https://odre.opendatasoft.com/api/explore/v2.1/catalog/datasets/postes-electriques-rte/exports/geojson"

echo ""
echo "=== C. Need a free account / manual click (skip on first pass if short of time) ==="
cat <<'MANUAL'
  DK  GeoDanmark Hoejspaendingsledning: datafordeler.dk -> GeoDanmark Vektor fildownload
      (free login; download the Teknik theme, GeoPackage or GML)
  SE  Lantmateriet Topografi 10 Tema Ledningar: geotorget.lantmateriet.se (free login, CC0)
  FI  Maanmittauslaitos Maastotietokanta Johtoverkosto: asiointi.maanmittauslaitos.fi
      file service (free, CC BY 4.0) - sahkolinja feature classes
  ES  CNIG BTN Energia: the section-A URL fetches a page if the portal insists on a
      session; if so use centrodedescargas.cnig.es -> Base Topografica Nacional ->
      tematico Energia (BTN_T_ENERGIA_GPKG.ZIP, ~38 MB, licence compatible CC BY 4.0)
MANUAL
echo ""
echo "Done. Sizes:"; du -sh authoritative_raw/* 2>/dev/null
echo "Tell Claude the run is finished."
