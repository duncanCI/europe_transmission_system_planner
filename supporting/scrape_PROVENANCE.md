# OSM frequency/operator scrape - provenance

Purpose: authoritative id-list of non-50 Hz and railway-operator power elements for the v22
frequency-separation patch of the Europe grid GeoPackages.

Method: Overpass API queried FROM THE OWNER'S BROWSER (Chrome, same machine and method as the
original 2026-08-14 harvest), because the cloud container's egress policy denies all OSM hosts.
Primary endpoint: https://overpass.kumi.systems/api/interpreter (same-origin fetch from a tab on
that host); fallbacks per attempt rotation: https://overpass-api.de/api/interpreter,
https://overpass.private.coffee/api/interpreter. Data is live OSM (ODbL 1.0), retrieved
2026-08-18 ~02:45-03:20 UTC+1.

Two query families, CSV output ([out:csv(::type,::id,frequency,voltage,operator;false;"|")], timeout 240 s):
F - frequency-tagged non-50: way/relation, power~"^(line|cable|minor_line)$" (relations: line|cable),
    ["frequency"]["frequency"!~"^50$"]; run on 10 bboxes covering lon -11..42, lat 35..72.
O - railway operators regardless of frequency tag: operator~"DB Energie|OBB|ÖBB|OeBB|SBB|CFF|FFS|
    Trafikverket|Banverket|Bane NOR|Jernbaneverket"; run on the 5 central/nordic bboxes only.

Events: bbox (49,-11,61.5,2.5) F-query initially returned HTTP 504 x3 then an EMPTY 200 body from
kumi under load; retried split into two half-bboxes -> 2,329 rows, of which 31 not already covered
by neighbouring bboxes. North-Nordic operator query returned 0 rows (accepted: electrified traction
transmission is concentrated south of the bbox; the 66-72N frequency pass returned rows).
All other 13 jobs returned clean bodies.

Result: 6,346 unique (type,id) rows in freq_nonstd_real.csv. Frequency-string distribution:
16.7 x4500, 0 x969, 16.67 x213, 50;16.7 x211, 50 x126 (operator-query rows tagged 50 Hz),
empty x54 (operator rows with no frequency tag), plus junk values (10000, 500, 60, 40, 25...)
retained verbatim for the classifier to flag rather than silently drop.

Classification rules applied downstream (patch_v22.py): pure 16.x tag -> 16.7 Hz
(frequency_source=osm_frequency_tag); mixed 50+16.x tag -> 16.7 only when the span's operator is a
known 16.7 Hz system, else kept 50 Hz and flagged; explicit 50 tag VETOES operator inference;
frequency=0 -> flagged dc_tagged_in_ac_layer; operator inference (operator_inferred) only at
<=132 kV in DE/AT/CH/SE/NO and only when every operator token is a 16.7 Hz system.
