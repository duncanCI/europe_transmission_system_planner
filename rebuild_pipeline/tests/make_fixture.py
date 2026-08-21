#!/usr/bin/env python3
"""Build tests/fixture.ndjson - a hand-built synthetic Overpass harvest.

Every element is placed by hand in a local metre frame around (1.0 E, 51.0 N)
and converted to lon/lat on write, so the geometry that each documented rule is
supposed to see is obvious from the numbers. Regenerate with:

    python tests/make_fixture.py

What each element is for (README_methodology_v23.md section in brackets):

  ways 101-106   six substation polygons: Alpha, Bravo, Charlie-1, Charlie-2
                 (120 m apart, one site by proximity - decision 3/5), Delta
                 (520 m from Charlie, must stay a separate site - decision 5),
                 Echo (the Ecrainville geometry - decision 7)
  ways 201-202   THE FOLD-BACK TRAP: two circuits of one double-circuit 400 kV
                 line, same voltage/circuits/type, sharing a node at the west end
                 and both running east into Bravo. Outward directions at the
                 shared node are the SAME, so the chain merger must refuse
                 (decision 4 / pitfall 25). Merging them produces one out-and-back
                 conductor that later set operations shred.
  ways 211-212   a chain that SHOULD merge: collinear, head-on at the shared node
                 (dot = -1), proving the gate is a direction test and not a ban
  way  221       a junction tee: ends 15 m from the middle of the merged 220 kV
                 line, perpendicular, so the 25 deg parallel test accepts it and
                 the target splits into a real T (pitfall 14 / decision 9)
  ways 231-232   cable-to-overhead transition inside one corridor: the node is the
                 sealing end, not a defect (README s4)
  ways 241-242   16.7 Hz traction (explicit tag) sharing a node with a 50 Hz line,
                 which must sever into two buses; plus an operator-inferred
                 traction line with no frequency tag (README s12)
  way  251       DC link, frequency=0, both converters ~3 km from a bus so they
                 attach and are flagged converter_far (pitfall 3)
  way  261       under-construction 400 kV span, in the totals and flagged (pitfall 8)
  way  271       multi-value voltage 400;132 with cables=6 -> two records, two
                 circuits each, derived from the cables tag (README s5)
  rel  301       route relation whose two member ways merge into one LineString,
                 so it replaces them and takes its construction type from them
                 (README s6.3 / pitfall 28)
  rel  302       route relation whose members do not merge, so it is discarded in
                 favour of the ways (README s6.3)
  ways 311-312   two tips stopping 30 m short of each other away from any
                 substation: the end-to-end pass must join them (decision 10)
  ways 321-324   Ecrainville: two 400 kV circuits stopping 159 m short of Echo at
                 a common point, a 159 m conductor carrying on into the yard, and
                 an approach conductor with both ends on Echo whose far end is
                 120 m out and must be freed rather than deleted (decisions 7, 8)
  way  325       a jumper wholly inside Echo: retained in line_internal_to_station
                 and used as busbar evidence for the bus point (decision 3)
  ways 331-332   a U-shaped jumper snapped onto both sides of one point on a
                 132 kV line: the two micro self-loops it creates are swept to the
                 internal layer and the line is re-merged by the junction dissolve
                 with a length check (decisions 12, 14 / pitfalls 13, 17)
  way  341       a cable between Charlie and Delta: it touches both polygons but
                 runs 520 m in the open, so it must NOT fuse them (decision 5)
"""

from __future__ import annotations

import json
import os

# Local frame: metres east/north of (1.0 E, 51.0 N). Only the pipeline's own
# reprojection matters, so a flat-earth conversion is right here.
LON0, LAT0 = 1.0, 51.0
M_PER_DEG_LON = 70057.0          # 111320 * cos(51 deg)
M_PER_DEG_LAT = 110540.0


def ll(x: float, y: float) -> list:
    return [round(LON0 + x / M_PER_DEG_LON, 7), round(LAT0 + y / M_PER_DEG_LAT, 7)]


def way(wid: int, tags: dict, pts: list) -> dict:
    return {"type": "way", "id": wid, "tags": tags,
            "geometry": [ll(x, y) for x, y in pts]}


def rect(wid: int, tags: dict, x0: float, y0: float, x1: float, y1: float) -> dict:
    return way(wid, tags, [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)])


def relation(rid: int, tags: dict, members: list) -> dict:
    return {"type": "relation", "id": rid, "tags": tags,
            "members": [{"type": "way", "ref": ref, "role": role,
                         "geometry": [ll(x, y) for x, y in pts]}
                        for ref, role, pts in members]}


OHL_400 = {"power": "line", "voltage": "400000", "circuits": "1"}
OHL_220 = {"power": "line", "voltage": "220000", "circuits": "1"}
OHL_132 = {"power": "line", "voltage": "132000", "circuits": "1"}


def elements() -> list:
    els = []

    # ---- substation polygons -------------------------------------------------
    els.append(rect(101, {"power": "substation", "name": "Alpha Substation",
                          "operator": "TestGrid", "voltage": "400000;132000"},
                    -100, -100, 100, 100))
    els.append(rect(102, {"power": "substation", "name": "Bravo Substation",
                          "operator": "TestGrid", "voltage": "400000"},
                    9900, -100, 10100, 100))
    els.append(rect(103, {"power": "substation", "name": "Charlie Substation A",
                          "voltage": "132000"}, -50, 4990, 50, 5050))
    els.append(rect(104, {"power": "substation", "name": "Charlie Substation B",
                          "voltage": "132000"}, -50, 5170, 50, 5230))
    els.append(rect(105, {"power": "substation", "name": "Delta Substation",
                          "voltage": "132000"}, -50, 5750, 50, 5850))
    els.append(rect(106, {"power": "substation", "name": "Echo Substation",
                          "operator": "TestGrid", "voltage": "400000"},
                    19900, -100, 20100, 100))

    # ---- fold-back trap: two circuits of one double-circuit line -------------
    els.append(way(201, dict(OHL_400, name="Foldback Circuit 1"),
                   [(5000, 0), (7000, 0), (9900, 0)]))
    els.append(way(202, dict(OHL_400, name="Foldback Circuit 2"),
                   [(5000, 0), (5200, 40), (7000, 40), (9900, 40)]))

    # ---- chain that should merge (collinear, head-on) ------------------------
    els.append(way(211, dict(OHL_220), [(200, -2000), (2000, -2000)]))
    els.append(way(212, dict(OHL_220), [(2000, -2000), (4000, -2000)]))

    # ---- junction tee onto the merged 220 kV line ---------------------------
    els.append(way(221, dict(OHL_220, name="Tee Spur"),
                   [(3000, -4000), (3000, -2015)]))

    # ---- cable to overhead transition ---------------------------------------
    els.append(way(231, {"power": "cable", "location": "underground",
                         "voltage": "132000", "circuits": "1"},
                   [(50, 0), (100, 0), (600, 0)]))
    els.append(way(232, dict(OHL_132), [(600, 0), (1500, 0), (3000, 0)]))

    # ---- traction: explicit tag, and operator inference ---------------------
    els.append(way(241, {"power": "line", "voltage": "110000", "circuits": "2",
                         "frequency": "16.7", "operator": "DB Energie",
                         "name": "Bahnstromleitung Test"},
                   [(0, 8000), (2000, 8000), (4000, 8000)]))
    els.append(way(242, {"power": "line", "voltage": "110000", "circuits": "1"},
                   [(0, 8000), (0, 7000)]))                  # 50 Hz, same node
    els.append(way(243, {"power": "line", "voltage": "110000", "circuits": "1",
                         "operator": "DB Energie"},
                   [(0, 9000), (2000, 9000)]))               # no frequency tag

    # ---- DC link ------------------------------------------------------------
    els.append(way(251, {"power": "cable", "voltage": "320000", "frequency": "0",
                         "name": "Test HVDC Link"},
                   [(0, -3000), (5000, -3000), (10000, -3000)]))

    # ---- under construction -------------------------------------------------
    els.append(way(261, {"power": "line", "construction:power": "line",
                         "voltage": "400000", "circuits": "1",
                         "construction": "yes", "name": "New Build 400kV"},
                   [(5000, 2000), (8000, 2000)]))

    # ---- multi-value voltage with cables=6 ----------------------------------
    els.append(way(271, {"power": "line", "voltage": "400000;132000",
                         "cables": "6", "ref": "4ZZ"},
                   [(50, 50), (2000, 3000)]))

    # ---- relation that merges, replacing its member ways -------------------
    els.append(way(303, dict(OHL_220), [(0, -6000), (2000, -6000)]))
    els.append(way(304, dict(OHL_220), [(2000, -6000), (4000, -6000)]))
    els.append(relation(301, {"route": "power", "voltage": "220000",
                              "circuits": "1", "name": "Test Route 220kV"},
                        [(303, "", [(0, -6000), (2000, -6000)]),
                         (304, "", [(2000, -6000), (4000, -6000)])]))

    # ---- relation that does not merge, discarded in favour of the ways ------
    els.append(way(305, dict(OHL_132), [(0, -7000), (1000, -7000)]))
    els.append(way(306, dict(OHL_132), [(2000, -7000), (3000, -7000)]))
    els.append(relation(302, {"route": "power", "voltage": "132000",
                              "circuits": "1", "name": "Broken Route 132kV"},
                        [(305, "", [(0, -7000), (1000, -7000)]),
                         (306, "", [(2000, -7000), (3000, -7000)])]))

    # ---- end-to-end pass: 30 m gap away from any substation ----------------
    els.append(way(311, dict(OHL_132), [(0, -9000), (2000, -9000)]))
    els.append(way(312, dict(OHL_132), [(2030, -9000), (4000, -9000)]))

    # ---- Ecrainville at Echo ------------------------------------------------
    els.append(way(321, dict(OHL_400, name="Echo Circuit 1"),
                   [(15000, 0), (17000, 0), (19741, 0)]))
    els.append(way(322, dict(OHL_400, name="Echo Circuit 2"),
                   [(15000, -500), (17000, -400), (19741, 0)]))
    els.append(way(323, dict(OHL_400, name="Echo Yard Entry"),
                   [(19741, 0), (19950, 0)]))
    els.append(way(324, dict(OHL_400, name="Echo Approach"),
                   [(20000, -50), (20220, -50)]))
    els.append(way(325, dict(OHL_400, name="Echo Busbar Jumper"),
                   [(19950, 20), (20050, 20)]))

    # ---- U-shaped jumper: two micro self-loops and one dissolve ------------
    els.append(way(331, dict(OHL_132, name="Dissolve Target"),
                   [(30000, 0), (32000, 0), (34000, 0)]))
    els.append(way(332, dict(OHL_132, name="U Jumper"),
                   [(32000, 15), (32000, 120), (32020, 120), (32020, 15)]))

    # ---- cable between Charlie and Delta: must not fuse the sites ----------
    els.append(way(341, {"power": "cable", "location": "underground",
                         "voltage": "132000", "circuits": "1"},
                   [(0, 5200), (0, 5800)]))
    return els


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "fixture.ndjson")
    els = elements()
    with open(out, "w", encoding="utf-8") as fh:
        for el in els:
            fh.write(json.dumps(el, separators=(",", ":")) + "\n")
    print(f"wrote {out}: {len(els)} elements")


if __name__ == "__main__":
    main()
