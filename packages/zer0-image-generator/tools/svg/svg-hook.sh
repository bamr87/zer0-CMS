#!/usr/bin/env bash
# svg-hook.sh — PostToolUse hook. Reads Claude Code's event JSON on stdin.
#
# Contract:
#   exit 0 + stdout  -> message lands in Claude's context (here: the PNG path)
#   exit 2 + stderr  -> Claude is told the write was bad and asked to fix it
#
# This is the whole trick. Without it, the model writes SVG blind and you
# spend your turns telling it what it should have been able to see.
set -uo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
INPUT=$(cat)

# jq if present, else a portable grep fallback
if command -v jq >/dev/null 2>&1; then
  FILE=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty')
else
  FILE=$(printf '%s' "$INPUT" | sed -n 's/.*"file_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
fi

[[ "$FILE" == *.svg ]] || exit 0
[[ -f "$FILE" ]] || exit 0

if ! LINT=$(python3 "$ROOT/tools/svg/svg-check.py" "$FILE" 2>&1); then
  echo "SVG validation failed for $FILE:" >&2
  echo "$LINT" >&2
  echo "Fix these before continuing. Do not re-render until they pass." >&2
  exit 2
fi

PNG=$(bash "$ROOT/tools/svg/svg-render.sh" "$FILE" 2>/dev/null) || {
  echo "Wrote $FILE (lint clean). No rasterizer installed — visual check skipped."
  exit 0
}

echo "Wrote $FILE (lint clean). Rendered to $PNG"
echo "Read $PNG now and critique the composition before making further edits."
exit 0
