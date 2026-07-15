#!/usr/bin/env bash
# End-to-end smoke harness for zer0-image-generator.
#
# Drives the REAL gem CLI (`bundle exec jekyll preview-images`) against a
# throwaway copy of test/fixture-site using the free deterministic `local`
# provider — no API keys, no network, repo stays clean. Falls back to the
# standalone Python engine when Ruby/bundler are unavailable.
#
#   .claude/skills/run-zer0-image-generator/smoke.sh            # full run
#   .claude/skills/run-zer0-image-generator/smoke.sh --keep     # keep tmp site
#
# Exit 0 = every stage passed. Any failure prints the stage and exits 1.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
KEEP="${1:-}"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/zig-smoke.XXXXXX")"
[ "$KEEP" = "--keep" ] || trap 'rm -rf "$TMP"' EXIT

fail() { echo "SMOKE FAIL [$1]: $2" >&2; exit 1; }
pass() { echo "  ✓ $1"; }

echo "== zer0-image-generator smoke ($TMP) =="

# ---- stage 0: unit tests (the layer most PRs touch) -------------------------
python3 "$REPO/test/test_preview_generator.py" >/dev/null 2>&1 \
  || fail unit-python "python3 test/test_preview_generator.py failed"
pass "python unit suite"
if command -v ruby >/dev/null; then
  ruby "$REPO/test/test_command.rb" >/dev/null 2>&1 \
    || fail unit-ruby "ruby test/test_command.rb failed"
  pass "ruby command-layer suite"
fi

# ---- stage 1: throwaway fixture site ----------------------------------------
cp -R "$REPO/test/fixture-site/" "$TMP/site/"
cd "$TMP/site"

# ---- stage 2: pick the driver — gem CLI when bundler works, else engine -----
RUNNER=""
if command -v bundle >/dev/null; then
  # Point the path-gem at the absolute repo (the fixture's ../.. breaks in /tmp).
  # BSD and GNU sed accept -i differently; write via a temp file instead.
  sed "s|path: \"../..\"|path: \"$REPO\"|" Gemfile > Gemfile.tmp && mv Gemfile.tmp Gemfile
  export BUNDLE_PATH="$TMP/bundle"
  if bundle install >/dev/null 2>&1; then
    RUNNER="bundle exec jekyll preview-images"
    pass "bundle install (gem CLI path)"
  fi
fi
if [ -z "$RUNNER" ]; then
  RUNNER="python3 $REPO/lib/zer0_image_generator/preview_generator.py"
  pass "standalone engine path (no usable Ruby/bundler)"
fi

# ---- stage 3: list-missing sees both fixture files ---------------------------
$RUNNER --list-missing 2>&1 | grep -q "Hello World" || fail list-missing "post not listed"
$RUNNER --list-missing 2>&1 | grep -q "Getting Started" || fail list-missing "doc not listed"
pass "--list-missing finds 2 files"

# ---- stage 4: dry-run writes NOTHING (guards the 0.2.2 flag-forwarding bug) --
$RUNNER --dry-run >/dev/null 2>&1
[ ! -e assets/images/previews ] || fail dry-run "--dry-run wrote files"
if grep -q "^preview:" _posts/*.md; then fail dry-run "--dry-run touched front matter"; fi
pass "--dry-run writes nothing"

# ---- stage 5: generate with the free local provider --------------------------
$RUNNER --provider local >/dev/null 2>&1 || fail generate "generation run failed"
ls assets/images/previews/hello-world.* >/dev/null 2>&1 || fail generate "no post banner"
ls assets/images/previews/getting-started.* >/dev/null 2>&1 || fail generate "no doc banner"
grep -qE "^preview: /images/previews/hello-world\.(png|svg)$" _posts/2026-01-01-hello-world.md \
  || fail generate "post front matter not wired"
grep -qE "^preview: /images/previews/getting-started\.(png|svg)$" _docs/getting-started.md \
  || fail generate "doc front matter not wired"
pass "local provider generated 2 banners + wired front matter"

# ---- stage 6: idempotency -----------------------------------------------------
$RUNNER --provider local 2>&1 | grep -q "Files skipped: 2" || fail idempotent "rerun did not skip"
pass "rerun skips existing banners"

echo "== SMOKE OK =="
[ "$KEEP" = "--keep" ] && echo "site kept at: $TMP/site"
exit 0
