#!/usr/bin/env python3
"""Stage 1 - chunked Overpass harvest to NDJSON.

Implements the retrieval step of README_methodology_v23.md s6.1: an Overpass
query per chunk in two voltage passes (>= high_pass_floor_kv, then
voltage_floor_kv..high_pass_floor_kv-1), a substation pass, and a separate DC
sweep with no voltage filter, because DC relations are not reliably voltage
tagged. The voltage filter is pushed into the query rather than applied
afterwards, for payload reasons (s6 deviation 5); the exact floor is re-enforced
in stage 2, so the query filter only has to be a superset.

MUST RUN OUTSIDE AN EGRESS-RESTRICTED ENVIRONMENT. It reaches Overpass mirrors
and nothing else. Output is one NDJSON file per (chunk, pass), which makes the
run resumable: a chunk whose file already exists and parses is skipped.

Usage:
    python 01_harvest_overpass.py --config config_europe.yaml
    python 01_harvest_overpass.py --config config_europe.yaml --dry-run
    python 01_harvest_overpass.py --config config_europe.yaml --only dc
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, log, write_ndjson  # noqa: E402

USER_AGENT = (
    "grid-topology-rebuild/1.0 (OSM transmission topology; "
    "contact: set contact in the config)"
)

# Overpass etiquette. Values are deliberately conservative: the reference build
# took ~4 hours for Europe and that is the expected order of magnitude.
STATUS_POLL_S = 15          # wait between /api/status polls when slots are queued
STATUS_MAX_WAIT_S = 900     # give up waiting for a slot and rotate mirrors


# --------------------------------------------------------------------------- #
# voltage regex: match integers >= floor, in volts, inside a multi-value tag
# --------------------------------------------------------------------------- #

def _fixed_width_alts(lo: int, hi: int, width: int) -> List[str]:
    """Alternatives matching exactly the integers in [lo, hi] written at `width`
    digits. Both bounds are enforced: an earlier version generated ">= lo" only,
    so a band that did not end on a digit-width boundary (e.g. 66-110 kV, whose
    6-digit part is 100000..109999) also matched 132000, 220000 and 500000, and
    the second harvest pass silently re-fetched the whole first pass."""
    if width == 0:
        return [""]
    if lo == 0 and hi == 10 ** width - 1:
        return [f"[0-9]{{{width}}}" if width > 1 else "[0-9]"]
    slo, shi = str(lo).zfill(width), str(hi).zfill(width)
    if slo == shi:
        return [slo]
    if slo[0] == shi[0]:
        return [slo[0] + a for a in _fixed_width_alts(int(slo[1:] or 0), int(shi[1:] or 0), width - 1)]
    out: List[str] = [slo[0] + a for a in
                      _fixed_width_alts(int(slo[1:] or 0), 10 ** (width - 1) - 1, width - 1)]
    a, b = int(slo[0]) + 1, int(shi[0]) - 1
    if a <= b:
        cls = f"[{a}-{b}]" if a < b else str(a)
        out.append(cls + (f"[0-9]{{{width - 1}}}" if width > 2 else ("[0-9]" if width == 2 else "")))
    out += [shi[0] + a for a in _fixed_width_alts(0, int(shi[1:] or 0), width - 1)]
    return out


def voltage_regex(lo_kv: float, hi_kv: Optional[float], max_kv: float = 1500.0) -> str:
    """Regex matching a voltage value in volts in [lo_kv, hi_kv), both bounds
    enforced. Anchored on value boundaries so it works on a multi-value tag such
    as '110000;20000' (paper Tables 2-3). hi_kv=None means unbounded above.
    """
    lo_v = int(round(lo_kv * 1000))
    hi_v = int(round((hi_kv if hi_kv else max_kv) * 1000))
    alts: List[str] = []
    for width in range(len(str(lo_v)), len(str(hi_v)) + 1):
        band_lo = max(lo_v, 10 ** (width - 1))
        band_hi = min(hi_v - 1, 10 ** width - 1)
        if band_lo > band_hi:
            continue
        alts.extend(_fixed_width_alts(band_lo, band_hi, width))
    body = "|".join(alts)
    # (^|;) ... (;|$) keeps '20000' in '120000' from matching.
    return f"(^|;)({body})(;|$)"


# --------------------------------------------------------------------------- #
# query construction
# --------------------------------------------------------------------------- #

def _scope_clause(scope: Dict[str, Any]) -> Tuple[str, str]:
    """Return (prelude, selector) for a bbox chunk or a named area."""
    if scope["kind"] == "bbox":
        s, w, n, e = scope["bbox"]
        return "", f"({s},{w},{n},{e})"
    # Named area: ISO code or Overpass area name. Selector is (area.a).
    if scope.get("iso"):
        prelude = f'area["ISO3166-1"="{scope["iso"]}"][admin_level=2]->.a;\n'
    else:
        prelude = f'area["name"="{scope["name"]}"]->.a;\n'
    return prelude, "(area.a)"


def build_conductor_query(scope: Dict[str, Any], lo_kv: float, hi_kv: Optional[float],
                          timeout_s: int) -> str:
    """power=line / power=cable ways and relations in a voltage band, with
    geometry and tags. Route relations are matched on route=power too, because
    an HVDC or multi-way route relation frequently carries no power tag of its
    own (README s7 pitfall 28) - its construction type is later derived from its
    member ways."""
    prelude, sel = _scope_clause(scope)
    vre = voltage_regex(lo_kv, hi_kv)
    return (
        f"[out:json][timeout:{timeout_s}];\n"
        f"{prelude}"
        "(\n"
        f'  way["power"~"^(line|cable|minor_line)$"]["voltage"~"{vre}"]{sel};\n'
        f'  relation["power"~"^(line|cable)$"]["voltage"~"{vre}"]{sel};\n'
        f'  relation["route"="power"]["voltage"~"{vre}"]{sel};\n'
        ");\n"
        "out tags geom;\n"
    )


def build_substation_query(scope: Dict[str, Any], timeout_s: int) -> str:
    """Substation ways and relations, no voltage filter: substation polygons are
    frequently untagged for voltage, and the site geometry is needed whatever
    voltage the conductors turn out to be (README s6.4)."""
    prelude, sel = _scope_clause(scope)
    return (
        f"[out:json][timeout:{timeout_s}];\n"
        f"{prelude}"
        "(\n"
        f'  way["power"="substation"]{sel};\n'
        f'  relation["power"="substation"]{sel};\n'
        ");\n"
        "out tags geom;\n"
    )


def build_dc_query(scope: Dict[str, Any], timeout_s: int) -> str:
    """DC sweep: frequency=0 conductors and route relations, no voltage filter
    (README s6.1). Kept separate so a missing voltage tag cannot drop an
    interconnector."""
    prelude, sel = _scope_clause(scope)
    return (
        f"[out:json][timeout:{timeout_s}];\n"
        f"{prelude}"
        "(\n"
        f'  way["power"~"^(line|cable)$"]["frequency"="0"]{sel};\n'
        f'  relation["power"~"^(line|cable)$"]["frequency"="0"]{sel};\n'
        f'  relation["route"="power"]["frequency"="0"]{sel};\n'
        ");\n"
        "out tags geom;\n"
    )


# --------------------------------------------------------------------------- #
# chunking
# --------------------------------------------------------------------------- #

def chunk_scopes(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Config region -> list of harvest scopes.

    `bboxes` are split into a grid of `chunk_deg` tiles so no single query has
    to return a continent; `areas` are harvested one area at a time, which is
    what the reference build did (two passes per country, README s6.1).
    """
    scopes: List[Dict[str, Any]] = []
    step = float(cfg["overpass"]["chunk_deg"])
    for bbox in cfg.get("bboxes") or []:
        s, w, n, e = [float(v) for v in bbox]
        lat = s
        while lat < n - 1e-9:
            lat2 = min(lat + step, n)
            lon = w
            while lon < e - 1e-9:
                lon2 = min(lon + step, e)
                scopes.append({
                    "kind": "bbox",
                    "bbox": [round(lat, 4), round(lon, 4), round(lat2, 4), round(lon2, 4)],
                    "name": f"bbox_{lat:.1f}_{lon:.1f}".replace("-", "m").replace(".", "p"),
                })
                lon = lon2
            lat = lat2
    for area in cfg.get("areas") or []:
        if isinstance(area, bool) or not isinstance(area, (str, dict)):
            # YAML 1.1 reads an unquoted NO / N / Y / ON / OFF as a boolean, so
            # an unquoted country list loses Norway without saying so. Refuse.
            raise SystemExit(
                f"config areas: {area!r} is not an area name - quote ISO codes "
                "in YAML (unquoted NO parses as boolean false)")
        if isinstance(area, str):
            scopes.append({"kind": "area", "iso": area, "name": f"area_{area}"})
        else:
            scopes.append({"kind": "area", "iso": area.get("iso"),
                           "name": f"area_{area.get('iso') or area.get('name')}",
                           **area})
    return scopes


def dc_scopes(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Scopes for the DC sweep, covering the WHOLE configured region.

    DC relations are not reliably voltage tagged (README s6.1), so they are
    swept separately with no voltage filter. A bbox region collapses to one
    query; an `areas` region needs one query per area - returning a single area
    here silently harvested DC for one country and dropped every untagged DC
    relation elsewhere.
    """
    if cfg.get("bboxes"):
        s = min(float(b[0]) for b in cfg["bboxes"])
        w = min(float(b[1]) for b in cfg["bboxes"])
        n = max(float(b[2]) for b in cfg["bboxes"])
        e = max(float(b[3]) for b in cfg["bboxes"])
        return [{"kind": "bbox", "bbox": [s, w, n, e], "name": "region"}]
    return [sc for sc in chunk_scopes(cfg) if sc["kind"] == "area"]


# --------------------------------------------------------------------------- #
# HTTP with mirror rotation and polite backoff
# --------------------------------------------------------------------------- #

class Harvester:
    def __init__(self, cfg: Dict[str, Any]) -> None:
        o = cfg["overpass"]
        self.endpoints: List[str] = list(o["endpoints"])
        self.timeout_s = int(o["timeout_s"])
        self.max_attempts = int(o["max_attempts"])
        self.backoff_base_s = float(o["backoff_base_s"])
        self.backoff_max_s = float(o["backoff_max_s"])
        self.polite_gap_s = float(o["polite_gap_s"])
        self.contact = cfg.get("contact")
        self._next: int = 0
        self._last_request_t = 0.0

    def _headers(self) -> Dict[str, str]:
        ua = USER_AGENT if not self.contact else f"grid-topology-rebuild/1.0 ({self.contact})"
        return {"User-Agent": ua, "Accept-Encoding": "gzip"}

    def _wait_for_slot(self, endpoint: str) -> None:
        """Poll /api/status and wait until a slot is free. Mirrors that do not
        expose the endpoint are simply not gated - the backoff still applies."""
        status_url = endpoint.rsplit("/", 1)[0] + "/status"
        waited = 0.0
        while waited < STATUS_MAX_WAIT_S:
            try:
                req = urllib.request.Request(status_url, headers=self._headers())
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = resp.read().decode("utf-8", "replace")
            except Exception:
                return  # no status endpoint, or unreachable: let backoff handle it
            free = "slots available" in body.lower() or "available now" in body.lower()
            if free or "Slot available after" not in body:
                return
            log(f"    slot queued on {endpoint}, waiting {STATUS_POLL_S}s")
            time.sleep(STATUS_POLL_S)
            waited += STATUS_POLL_S

    def fetch(self, query: str) -> Dict[str, Any]:
        """POST a query, rotating mirrors and backing off. Raises on final failure."""
        last_err = "no attempt made"
        for attempt in range(1, self.max_attempts + 1):
            endpoint = self.endpoints[self._next % len(self.endpoints)]
            self._next += 1
            gap = self.polite_gap_s - (time.time() - self._last_request_t)
            if gap > 0:
                time.sleep(gap)
            self._wait_for_slot(endpoint)
            data = urllib.parse.urlencode({"data": query}).encode("utf-8")
            req = urllib.request.Request(endpoint, data=data, headers=self._headers())
            try:
                self._last_request_t = time.time()
                with urllib.request.urlopen(req, timeout=self.timeout_s + 120) as resp:
                    raw = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        import gzip
                        raw = gzip.decompress(raw)
                payload = json.loads(raw.decode("utf-8", "replace"))
                if "elements" not in payload:
                    raise ValueError(f"no elements key in response: {str(payload)[:200]}")
                return payload
            except urllib.error.HTTPError as exc:
                last_err = f"HTTP {exc.code} from {endpoint}"
            except Exception as exc:                      # noqa: BLE001 - report and retry
                last_err = f"{type(exc).__name__}: {exc} from {endpoint}"
            sleep_s = min(self.backoff_max_s,
                          self.backoff_base_s * (2 ** (attempt - 1)))
            sleep_s *= 0.75 + 0.5 * random.random()       # jitter, so mirrors do not sync
            log(f"    attempt {attempt}/{self.max_attempts} failed ({last_err}); "
                f"sleeping {sleep_s:.0f}s")
            time.sleep(sleep_s)
        raise RuntimeError(f"all attempts failed: {last_err}")


# --------------------------------------------------------------------------- #
# element normalisation
# --------------------------------------------------------------------------- #

def normalise(el: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Keep exactly what stage 2 needs: type, id, tags, geometry, members.

    Overpass `out geom` puts a way's vertices in `geometry` and a relation's
    member geometry inside each member. Discarding the rest keeps the harvest
    to roughly the 165 MB the reference build recorded (README s8).
    """
    t = el.get("type")
    if t not in ("way", "relation"):
        return None
    rec: Dict[str, Any] = {"type": t, "id": el["id"], "tags": el.get("tags") or {}}
    if t == "way":
        geom = el.get("geometry")
        if not geom:
            return None
        rec["geometry"] = [[round(p["lon"], 7), round(p["lat"], 7)]
                           for p in geom if p and p.get("lat") is not None]
        if len(rec["geometry"]) < 2:
            return None
    else:
        members = []
        for m in el.get("members") or []:
            mm: Dict[str, Any] = {"type": m.get("type"), "ref": m.get("ref"),
                                  "role": m.get("role") or ""}
            g = m.get("geometry")
            if g:
                mm["geometry"] = [[round(p["lon"], 7), round(p["lat"], 7)]
                                  for p in g if p and p.get("lat") is not None]
            members.append(mm)
        if not members:
            return None
        rec["members"] = members
    return rec


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #

def already_done(path: str) -> bool:
    """Resumability: a chunk counts as done when its file exists and every line
    parses. A truncated file (killed mid-write) is re-fetched; write_ndjson's
    temp-then-rename means that should not happen in the first place."""
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    json.loads(line)
        return True
    except Exception:
        log(f"    re-fetching unreadable chunk {os.path.basename(path)}")
        return False


def passes_for(cfg: Dict[str, Any]) -> List[Tuple[str, float, Optional[float]]]:
    """The two documented voltage passes (README s6.1).

    High pass first: >= high_pass_floor_kv, unbounded above. Then the low band,
    voltage_floor_kv .. high_pass_floor_kv, which is the band that made the
    difference to France, Spain, Portugal, Norway, Denmark, Belgium and
    Switzerland (README s2).
    """
    floor = float(cfg["voltage_floor_kv"])
    high = float(cfg["high_pass_floor_kv"])
    out = [("hv", high, None)]
    if floor < high:
        out.append(("sub", floor, high))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and one sample query, fetch nothing")
    ap.add_argument("--only", choices=["hv", "sub", "substation", "dc"],
                    help="run a single pass")
    args = ap.parse_args()

    cfg = load_config(args.config)
    hdir = cfg["harvest_dir"]
    os.makedirs(hdir, exist_ok=True)
    scopes = chunk_scopes(cfg)
    vpasses = passes_for(cfg)

    jobs: List[Tuple[str, Dict[str, Any], str]] = []
    for name, lo, hi in vpasses:
        for sc in scopes:
            jobs.append((f"{sc['name']}__{name}", sc,
                         build_conductor_query(sc, lo, hi, cfg["overpass"]["timeout_s"])))
    if cfg["overpass"]["harvest_substations"]:
        for sc in scopes:
            jobs.append((f"{sc['name']}__substation", sc,
                         build_substation_query(sc, cfg["overpass"]["timeout_s"])))
    if cfg["overpass"]["harvest_dc_sweep"]:
        for rs in dc_scopes(cfg):
            jobs.append((f"{rs['name']}__dc", rs,
                         build_dc_query(rs, cfg["overpass"]["timeout_s"])))
    if args.only:
        jobs = [j for j in jobs if j[0].endswith("__" + args.only)]

    log(f"{cfg['region_name']}: {len(scopes)} chunks x {len(vpasses)} voltage passes "
        f"+ substations + dc = {len(jobs)} harvest jobs -> {hdir}/")
    if args.dry_run:
        print(jobs[0][2])
        print(f"# {len(jobs)} jobs planned; "
              f"{sum(1 for j in jobs if already_done(os.path.join(hdir, j[0] + '.ndjson')))}"
              " already on disk")
        return 0

    harvester = Harvester(cfg)
    manifest_path = os.path.join(hdir, "manifest.json")
    manifest: Dict[str, Any] = {}
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)

    failures: List[str] = []
    for i, (job, _scope, query) in enumerate(jobs, 1):
        path = os.path.join(hdir, job + ".ndjson")
        if already_done(path):
            log(f"[{i}/{len(jobs)}] skip {job} (on disk)")
            continue
        log(f"[{i}/{len(jobs)}] fetch {job}")
        try:
            payload = harvester.fetch(query)
        except Exception as exc:                            # noqa: BLE001
            # A failed chunk is recorded and skipped, never written as an empty
            # file: an empty file would be indistinguishable from "no data here"
            # on the next run. Same rule as the reference build's scrape scripts.
            log(f"    FAILED {job}: {exc}")
            failures.append(job)
            manifest[job] = {"status": "failed", "error": str(exc)[:300]}
            continue
        recs = [r for r in (normalise(e) for e in payload["elements"]) if r]
        n = write_ndjson(path, recs)
        manifest[job] = {"status": "ok", "elements": n,
                         "fetched_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                         "bytes": os.path.getsize(path)}
        log(f"    {n} elements, {os.path.getsize(path) / 1e6:.1f} MB")
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=1, sort_keys=True)

    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
    ok = sum(1 for v in manifest.values() if v.get("status") == "ok")
    log(f"harvest done: {ok} chunks ok, {len(failures)} failed")
    if failures:
        log("failed chunks (re-run the same command to retry only these): "
            + ", ".join(failures))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
