#!/usr/bin/env bash
# Round 2: the fixes from the first download run. Run from the project folder:
#     bash download_round2.sh
set -uo pipefail
mkdir -p authoritative_raw

get_arcgis() {
  mkdir -p "authoritative_raw/$1"
  if [ -s "authoritative_raw/$1/$2.geojson" ]; then echo "SKIP $1/$2"; return 0; fi
  echo "GET  $1/$2 (paged)"
  local off=0 page=1000 n=0
  : > "authoritative_raw/$1/$2.parts"
  while :; do
    curl -sSL --fail --max-time 300 -o /tmp/_pg.json \
      "$3/query?where=1%3D1&outFields=*&f=geojson&outSR=4326&resultOffset=${off}&resultRecordCount=${page}" || break
    local got
    got=$(python3 -c "import json;print(len(json.load(open('/tmp/_pg.json')).get('features',[])))" 2>/dev/null) || break
    [ "${got:-0}" -eq 0 ] && break
    python3 -c "import json;print('\n'.join(json.dumps(f) for f in json.load(open('/tmp/_pg.json'))['features']))" >> "authoritative_raw/$1/$2.parts"
    n=$((n+got)); off=$((off+got))
    [ "$got" -lt "$page" ] && break
  done
  python3 - "$1" "$2" <<'PY'
import json, sys
folder, name = sys.argv[1], sys.argv[2]
feats = [json.loads(l) for l in open(f"authoritative_raw/{folder}/{name}.parts") if l.strip()]
json.dump({"type":"FeatureCollection","features":feats}, open(f"authoritative_raw/{folder}/{name}.geojson","w"))
print(f"     {len(feats)} features")
PY
  rm -f "authoritative_raw/$1/$2.parts"
}

echo "=== NL Liander, correct layer ids from the catalogue ==="
B="https://services1.arcgis.com/v6W5HAVrpgSg3vts/arcgis/rest/services/Liander_Open_Data_Elektra/FeatureServer"
get_arcgis "NL_liander" "hoogspanningskabel_632"   "$B/632"
get_arcgis "NL_liander" "hs_bovengronds_638"       "$B/638"
get_arcgis "NL_liander" "hoogspanningsstation_641" "$B/641"

echo ""
echo "=== CZ ZABAGED: extract just the two electricity classes from the 3.7 GB FGDB ==="
CZ_DIR="authoritative_raw/CZ_zabaged_polohopis_základní_b"
if [ -f "$CZ_DIR/ZABAGED-5514-fgdb-20260818.zip" ] && [ ! -f "$CZ_DIR/cz_elektricke_vedeni.gpkg" ]; then
  if command -v ogr2ogr >/dev/null; then
    echo "unzipping (needs ~4 GB free, deletes nothing)..."
    unzip -n -q "$CZ_DIR/ZABAGED-5514-fgdb-20260818.zip" -d "$CZ_DIR/x"
    GDB=$(find "$CZ_DIR/x" -name "*.gdb" -type d | head -1)
    echo "extracting from $GDB"
    ogr2ogr -f GPKG "$CZ_DIR/cz_elektricke_vedeni.gpkg" "$GDB" ElektrickeVedeni -t_srs EPSG:4326 2>/dev/null \
      || ogrinfo "$GDB" | grep -i -E "elektr|rozvod" | head
    ogr2ogr -f GPKG -update "$CZ_DIR/cz_elektricke_vedeni.gpkg" "$GDB" RozvodnaTransformovna -t_srs EPSG:4326 2>/dev/null \
      || true
    ls -lh "$CZ_DIR/cz_elektricke_vedeni.gpkg" 2>/dev/null
    echo "You can delete $CZ_DIR/x afterwards to reclaim ~4 GB"
  else
    echo "ogr2ogr not found. Easiest: install QGIS (bundles GDAL) or 'brew install gdal',"
    echo "then re-run this script. Only the ElektrickeVedeni + RozvodnaTransformovna"
    echo "classes are needed."
  fi
fi

echo ""
echo "=== Manual (one browser session each) ==="
cat <<'MANUAL'
  GB  Log in once at ssentransmission.opendatasoft.com then:
        bash download_authoritative.sh     (re-runs just the four failed SSEN files)
  CH  geodienste.ch -> Elektrische Anlagen ueber 36 kV -> download GPKG, save into
        authoritative_raw/CH_elektrische_anlagen_mit_eine/ (replace the HTML file)
  ES  centrodedescargas.cnig.es -> BTN -> tematico Energia -> BTN_T_ENERGIA_GPKG.ZIP
        into authoritative_raw/ES_base_topográfica_nacional_bt/ (replace the HTML file)
  SI  In a browser: search "ZKGJI ATOM elektrika eprostor" - the ATOM feed for
        dataset SI.GURS.KGI serves zipped shapefiles the WFS refused
  FR  odre.opendatasoft.com -> postes-electriques-rte -> Export -> GeoJSON (the API
        route returns attributes without geometry; the browser export includes it)
MANUAL
echo "Done. Tell Claude."
