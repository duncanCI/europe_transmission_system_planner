# DRAFT GitHub issue for PyPSA/pypsa-eur - review before filing, post from your account

**Suggested title:** 16.7 Hz railway traction is relabelled 50 Hz in clean_osm_data and
merges into the public grid - invisible at the 220 kV floor, ~16,500 route-km once the
distribution-grid config is used

---

## Summary

`clean_osm_data.py` deliberately normalises 16.7 Hz frequency tags and then relabels
every non-DC element to 50 Hz, so the Central European railway traction network - a
separate synchronous system - is absorbed into the public AC grid rather than filtered
or distinguished. This is harmless at the current 220 kV release floor, because
traction runs at 55-132 kV. It becomes material the moment
`config.distribution-grid-experimental.yaml` (#1740) is used: by our measurement,
about 16,500 route-km of traction network in DE/AT/CH/SE/NO then enters the model as
ordinary 50 Hz AC, topologically welded to the public grid wherever OSM shares nodes
or substations.

We hit this while building a sub-transmission dataset on your published method, and
we have a measured extent, an external validation and a working classification rule
to offer. Happy to turn any of it into a PR if you would take one.

## Mechanism (master @ `a5408e9`, 2026-08-19)

1. `scripts/clean_osm_data.py:267-268` - `_clean_frequency` normalises `"16.67"` and
   `"16,7"` to `"16.7"`, so the value is parsed, not rejected.
2. `scripts/clean_osm_data.py:884` - `bool_ac = df_lines["frequency"] != "0"`
   classes 16.7 Hz as AC.
3. Every AC cleaning branch then assigns `frequency = "50"` (lines 894, 912, 941,
   957, 976, 1002, 1014), and route relations are blanket-assigned `"50"` at
   line 1905. The final `df_lines[df_lines["frequency"] == "50"]` at line 2021
   therefore keeps the traction elements - relabelled.
4. Substations: line 827 coerces every non-{0,50} frequency to `"50"`, so traction
   feeder stations become public-grid buses; with `BUS_TOL = 500` aggregation, a
   traction substation within 500 m of a public one merges into the same bus.
5. `frequency` is not in the release columns (`prepare_osm_network_release.py`), so
   the information is unrecoverable downstream.

## Why it does not show at 220 kV, and what changes below it

Every traction element we classified sits at 55-132 kV (DB/OBB 110 kV, SBB 66/132 kV,
Trafikverket 130 kV, Bane NOR 55 kV), so releases v0.1-v0.7 are unaffected. With the
63-750 kV voltage list from #1740, our measured exposure (OSM harvest of 2026-08-14,
frequency scrape of 6,346 tagged elements):

| Country | 16.7 Hz route-km entering the 50 Hz model |
|---|---|
| DE | 10,199 |
| AT | 2,382 |
| SE | 1,914 |
| CH | 1,764 (incl. border spans) |
| NO | 185 |
| Total | 16,524 route-km, 1,397 spans |

External validation of the classification: the Swiss total (1,764 km) against SBB's
published ~1,800 km transmission network; the Swedish total (1,914 km) against
Trafikverket's ~1,700-2,000 km. In our build, separating traction required severing
235 shared buses and deleting 56 inferred transformers that had welded the two
synchronous systems - the same weldings will occur in any model built from the merged
data.

## Suggested handling

Smallest correct change: treat `"16.7"` as a valid frequency through cleaning, carry
the column into the build and the release, and let a config switch decide whether
traction elements are dropped or kept as a distinct sub-network - rather than
silently relabelling them.

One design note from doing this ourselves: an operator-based inference (SBB, DB
Energie, OBB, Trafikverket, Bane NOR tokens) usefully catches untagged traction, but
it must be gated to <= ~132 kV - railway operators also own EHV grid-supply lines,
which are 50 Hz.

We can share the classified element list (OSM ids + frequency + operator, ODbL) and
the tag-precedence rule, or submit either as a PR - whichever is more useful.

---

*Context: found while recreating the Xiong et al. (2025) method at a 50 kV floor for
route/corridor screening work. Filed with thanks - the method and the recent #1740
work are what made the sub-transmission build possible at all.*
