#!/usr/bin/env bash
# Run Pint against only the PHP files changed on the current branch.
# Usage: ./scripts/pint_changed.sh [--fix]
# Default mode is --test (check only). Pass --fix to auto-format and stage.

set -euo pipefail

BASE="${BASE_BRANCH:-develop}"
REMOTE_BASE="origin/${BASE}"
MODE="--test"
FIX_AND_STAGE=0

if [[ "${1:-}" == "--fix" ]]; then
  MODE=""
  FIX_AND_STAGE=1
fi

if ! git rev-parse --verify "${REMOTE_BASE}" >/dev/null 2>&1; then
  echo "error: ${REMOTE_BASE} not found. Try: git fetch origin ${BASE}"
  exit 1
fi

mapfile -t files < <(
  git diff --name-only --diff-filter=AMR "${REMOTE_BASE}...HEAD" -- '*.php' \
    | grep -v -e '^vendor/' -e '^storage/' || true
)

# Also include any uncommitted PHP changes (so the agent can lint dirty trees too)
mapfile -t -O "${#files[@]}" files < <(
  git diff --name-only --diff-filter=AMR -- '*.php' \
    | grep -v -e '^vendor/' -e '^storage/' || true
)

# Deduplicate, keep only files that still exist
declare -A seen
existing=()
for f in "${files[@]}"; do
  [[ -z "$f" ]] && continue
  [[ -n "${seen[$f]:-}" ]] && continue
  seen["$f"]=1
  [[ -f "$f" ]] && existing+=("$f")
done

if [[ ${#existing[@]} -eq 0 ]]; then
  echo "No PHP changes vs ${BASE}."
  exit 0
fi

echo "Checking ${#existing[@]} changed PHP file(s)..."
if [[ -n "$MODE" ]]; then
  vendor/bin/pint "$MODE" "${existing[@]}"
else
  vendor/bin/pint "${existing[@]}"
  if [[ "$FIX_AND_STAGE" == "1" ]]; then
    git add "${existing[@]}"
    echo "Staged ${#existing[@]} formatted file(s)."
  fi
fi
