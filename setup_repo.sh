#!/usr/bin/env bash
# One-time setup: turn this folder into a PUBLIC GitHub repository - code, docs and
# evidence only. The two GeoPackages are NOT tracked: they publish on Zenodo with a
# DOI (see ZENODO_DEPOSIT.md). No git-lfs anywhere.
#
# v2, 2026-08-19. Supersedes the private-repo + LFS script of 2026-08-18. If you ran
# that version, this one detects the old init and resets it (safe: nothing was ever
# committed).
#
# Run from the folder itself, in Terminal, on your own machine:
#     cd "/Users/duncan/Claude/Projects/Europe Camapign"
#     bash setup_repo.sh
#
# It stops before anything irreversible. It does not create the GitHub repo and does
# not push: it prints those commands at the end, so what lands under your account
# stays your click.
set -euo pipefail

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

command -v git >/dev/null || { echo "git not found. Install Xcode command line tools: xcode-select --install"; exit 1; }

say "1. Clearing the superseded 2026-08-18 private-repo init, if present"
if [ -d .git ]; then
  if git rev-parse HEAD >/dev/null 2>&1; then
    echo "   STOP: this repo already has commits. The old design committed nothing,"
    echo "   so something happened since - look before deleting history. Not touching it."
    exit 1
  fi
  rm -rf .git
  echo "   removed empty .git (old LFS-based init, no commits)"
fi
# the old .gitattributes routed the GeoPackages through LFS; this design has no LFS
if [ -f .gitattributes ] && grep -q 'filter=lfs' .gitattributes; then
  rm .gitattributes
  echo "   removed LFS .gitattributes (GeoPackages are untracked now, not LFS-tracked)"
fi

say "2. Initialising"
git init -b main

say "3. Checking the exclusions are in place"
test -f .gitignore || { echo ".gitignore missing - stopping"; exit 1; }
for pat in 'europe_grid_topology.gpkg' 'screen_v1' 'internal_pipeline/' 'INTERNAL_REVIEW_OUTPUTS/' 'scenario_inputs/' 'campaign/' 'authoritative_raw/' '_backup_v20'; do
  grep -q "$pat" .gitignore || { echo ".gitignore does not exclude $pat - wrong version, stopping"; exit 1; }
done
echo "   excluded: GeoPackages (Zenodo instead), internal screens and campaign material, raw inputs, backups, _to_delete/, zips"

say "4. Staging"
git add -A
echo "   files staged: $(git diff --cached --name-only | wc -l | tr -d ' ')"
echo "   total size:   $(git diff --cached --name-only | tr '\n' '\0' | du -ch --files0-from=- 2>/dev/null | tail -1 | awk '{print $1}' || echo 'n/a')"

say "5. Guard: nothing over 50 MB, nothing sensitive"
BAD=0
while IFS= read -r f; do
  [ -f "$f" ] || continue
  SZ=$(stat -f%z "$f" 2>/dev/null || stat -c%s "$f")
  if [ "$SZ" -gt 50000000 ]; then
    echo "   PROBLEM: $f is $((SZ/1000000)) MB - this repo has no LFS, nothing big belongs in it"
    BAD=1
  fi
done < <(git diff --cached --name-only)
if git diff --cached --name-only | grep -Ei 'register_matches|screen_v1/|internal_pipeline/|INTERNAL_REVIEW_OUTPUTS|scenario_inputs/|campaign/|authoritative_raw/' >/dev/null; then
  echo "   PROBLEM: internal or raw working material is staged - .gitignore is wrong"
  BAD=1
fi
[ "$BAD" -eq 0 ] && echo "   clean" || { echo "   fix before committing"; exit 1; }

say "6. Committing"
git -c user.name="${GIT_AUTHOR_NAME:-$(git config user.name || echo Duncan)}" \
    -c user.email="${GIT_AUTHOR_EMAIL:-$(git config user.email || echo duncan@continuum.industries)}" \
    commit -q -m "European grid topology: rebuild pipeline, methodology and evidence (v23)

The region-agnostic rebuild pipeline with its four test suites and acceptance
benchmark, plus methodology, validation and provenance for the published dataset.
The GeoPackages themselves are on Zenodo (DOI in README.md and CITATION.cff).
OpenStreetMap-derived work under ODbL 1.0 - see LICENCE_AND_ATTRIBUTION.md."
echo "   committed: $(git rev-parse --short HEAD)"

say "Done locally. Three steps left, all yours:"
cat <<'NEXT'

  1. Zenodo deposit first (ZENODO_DEPOSIT.md) - you want the reserved DOI in
     README.md and CITATION.cff before the repo goes public. Edit both, then:
       git add README.md CITATION.cff && git commit -m "Add dataset DOI"

  2. Create an EMPTY repository on github.com/new
       - name: eu-grid-topology (or your preference)
       - visibility: PUBLIC
       - do NOT add a README, .gitignore or licence - the folder has them

  3. Push:
       git remote add origin git@github.com:<your-account>/eu-grid-topology.git
       git push -u origin main

  No LFS, ~40 MB, unlimited clones. Colleagues just need the URL.
NEXT
