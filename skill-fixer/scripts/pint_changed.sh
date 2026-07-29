#!/usr/bin/env bash
# Run Pint against only the PHP files changed on the current branch.
# Usage: ./scripts/pint_changed.sh [--fix]
# Default mode is --test (check only). Pass --fix to auto-format and stage.

set -euo pipefail

BASE="${AI_REVIEW_BASE_BRANCH:-${BASE_BRANCH:-develop}}"
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

# Collect committed-vs-base AND uncommitted PHP changes, dedup, keep existing.
# Portable (no mapfile / no `declare -A` — both are bash 4+; macOS ships 3.2).
files=$(
  {
    git diff --name-only --diff-filter=AMR "${REMOTE_BASE}...HEAD" -- '*.php'
    git diff --name-only --diff-filter=AMR -- '*.php'
  } | grep -v -e '^vendor/' -e '^storage/' | sort -u || true
)

existing=()
while IFS= read -r f; do
  [[ -z "$f" ]] && continue
  [[ -f "$f" ]] && existing+=("$f")
done <<< "$files"

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
