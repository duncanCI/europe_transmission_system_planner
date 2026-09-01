# Task ledger — public map brand re-skin

Status key: `TODO` / `WIP` / `DONE` / `BLOCKED`
Scope: `docs/` chrome only. The **data** palette (headroom ramp, voltage
classes, planned violet `#7c3aed`, DC teal) is semantic and stays as-is.

Reconstructed 2026-09-01. `resume.txt` was not found anywhere on this
machine (project dir, ~/Claude, prior session scratchpads, Spotlight), so
the stuck point below is inferred from the uncommitted diff, not from
session notes. If the real resume.txt surfaces, reconcile this file first.

## Context

Uncommitted WIP on `main` re-skins the published map (`docs/index.html`,
`docs/feedback.js`) to Continuum Industries / Optioneer brand tokens:

    --paper #EEF0F2   --ink #231A45   --muted #5B5773   --rule #CED6D7
    --brand #29194F   --brand-2 #330084   --link #3E0CBA
    --teal #1CCDD8    --teal-soft #9CEDF2   --warn #E8590C   --apricot #FDC182

Converted so far: header, h1, subtitle links, #asmbtn, feedback dialog
primary button, focus ring (added), Roboto font. The conversion is
**half-finished**; the tasks below are the remainder plus the defects it
introduced.

## Ledger

| # | Task | Files | Status |
|---|------|-------|--------|
| 1 | Stale paper in map halos: `circle-stroke-color:"#f5f7f6"` is the *old* `--paper`; point halos no longer match the `#EEF0F2` ground (which shows through the transparent map canvas — style has no background layer, so CSS `--paper` is the ground; keep it that way) | `docs/index.html` 366, 599, 639, 676 | DONE |
| 2 | Convert remaining chrome greys in `index.html` to tokens: `#cbd5e1`→`--rule`, `#64748b`→`--muted`, `#0f172a`→`--ink`, `#3b5f7a`→`--link`/`--brand`. Note line 49: `#asmbtn` still has `border:1px solid #cbd5e1` *under* its new `--brand` background — the later `border-color:var(--brand)` wins, so drop the stale slate | `docs/index.html` 49, 58, 61, 66, 78, 85, 93, 94 | DONE |
| 3 | Finish `feedback.js`: 9 remaining literals (`#64748b`, `#cbd5e1`, `#f8fafc`, `#eef2f7`). Injected CSS lives in the same document, so it can read `var(--muted)` etc. directly instead of re-hardcoding | `docs/feedback.js` 75, 76, 79, 85, 86, 91, 94, 95 | DONE |
| 4 | Focus ring fails contrast: `--teal #1CCDD8` measures **1.71:1** on `#EEF0F2` (1.95:1 on white) vs WCAG 2.2 SC 1.4.11's 3:1 floor. Use `--brand`/`--link`, or teal inner ring against a dark outer | `docs/index.html` 110 | DONE |
| 5 | Regularise cache-busting: `?v=ecc0a163a4` works (any string busts) but is derived from nothing — not a git object, not the file md5 — and breaks the prior date-stamp convention (`20260822d`). Pick one scheme (date-stamp or content hash), apply to both script tags, and check `TILE_VERSION` uses the same convention | `docs/index.html` 11, 12 | DONE |
| 6 | DECISION (user): `.yearctl`/`.scenrow` use `accent-color:#7c3aed` — chrome that *encodes* planned-scheme violet. Keep for semantic consistency with the data it filters, or move to `--brand`? | `docs/index.html` 34, 35, 38 | DONE (kept violet — semantic echo; user-approved default) |
| 7 | Verify in-browser: `python webmap/serve_local.py` (port 8123 per .claude/launch.json), check header, layer panel, popups, assumptions register, feedback dialog, keyboard focus ring, halo/ground match; confirm ODbL attribution line and claims-ceiling strings untouched | — | DONE |
| 8 | Commit. Author `Duncan <duncan@continuum.industries>`, committer `Claude <noreply@anthropic.com>` (CLAUDE.md rule 6; the verification hook requires the committer). Ledger gets final tick-off in same change | — | TODO |

## Guardrails carried from CLAUDE.md

- Rule 1: never commit `*.gpkg` / `*.zip`; do not loosen `.gitignore`.
- Rule 3: claims ceiling — screening-grade, not survey-grade. State limits
  before capabilities in any user-visible string in `docs/`.
- Rule 4: every derived artefact credits "(c) OpenStreetMap contributors,
  ODbL 1.0". Do not let a re-skin drop the attribution line.
- Rule 5: published tiles carry their build command; build with relative
  paths so no local filesystem path ships.

## Execution notes (2026-09-01)

- T1: halos now use a shared `PAPER` const (documented: must match `--paper`;
  MapLibre paints cannot read CSS custom properties) — prevents recurrence.
- T2: scope grew on re-read: also converted `#475569`, `#94a3b8`, `#334155`,
  the undefined `var(--line,#e2e8f0)` fallback, both modal scrims
  (slate→ink rgba), the popup font stack (Roboto-first), and the
  request-access CTA (`#7c3aed`→`--link`: it is an action, not a data mark).
  Left: `.bias #7c2d12` (semantic, not a grey), `#sites` `#1f2937` (data).
- T3: whole injected sheet now reads page tokens via `var()`, including the
  previously hardcoded brand hexes; secondary buttons: `--rule` border,
  `--paper` bg, `--teal-soft` hover. Syntax-checked via JavaScriptCore.
- T4: focus ring `--teal`→`--link` with a comment citing SC 1.4.11.
- T5: script tags `?v=20260901` (date-stamp convention restored).
  `TILE_VERSION` untouched — tiles unchanged, no forced ~67 MB re-download.
- T7: verified in headless Chrome (installed Playwright into letscode env,
  drove installed Chrome via channel="chrome"): computed styles assert to
  exact token values; screenshots of initial view, zoom, popup, assumptions
  register, feedback dialog, focus ring all correct; zero console errors.
  Pre-existing quirk, untouched: `details.lgroup` border-top computes 0px on
  every group (`:first-of-type` matches each because each is alone in its
  parent) — identical before and after, no visual change.
- T8: committed as 42a7d64 (author Duncan, committer Claude). This ledger
  stays untracked: session artefact, not repo material.
- T9 (2026-09-01): header CTA for the gated stress screen (teal chip, top right,
  same GATED_STRESS_URL gate, limits-first wording). Committed+pushed.
- Model/loading epic (2026-09-01): diagnosed and tracked in the private ops repo ledger — not mirrored here.
