#!/usr/bin/env bash
# Run Pest only for tests that map to files changed on the current branch.
#
# Mapping rule (per the project's tests/Feature/ArchitectureTest.php convention):
#   app/Foo/Bar.php  →  tests/Feature/Foo/BarTest.php
# Test files changed directly are always included.
#
# Usage: ./scripts/pest_for_changed.sh [extra pest args...]

set -euo pipefail

BASE="${BASE_BRANCH:-develop}"
REMOTE_BASE="origin/${BASE}"

if ! git rev-parse --verify "${REMOTE_BASE}" >/dev/null 2>&1; then
  echo "error: ${REMOTE_BASE} not found. Try: git fetch origin ${BASE}"
  exit 1
fi

mapfile -t changed < <(
  {
    git diff --name-only --diff-filter=AMR "${REMOTE_BASE}...HEAD" -- '*.php'
    git diff --name-only --diff-filter=AMR -- '*.php'
  } | sort -u | grep -v -e '^vendor/' -e '^storage/' || true
)

declare -A test_set
for f in "${changed[@]}"; do
  [[ -z "$f" ]] && continue
  if [[ "$f" == tests/* ]]; then
    [[ -f "$f" ]] && test_set["$f"]=1
    continue
  fi
  if [[ "$f" == app/* ]]; then
    rel="${f#app/}"
    dir=$(dirname "$rel")
    base=$(basename "$rel" .php)
    candidate="tests/Feature/${dir}/${base}Test.php"
    [[ -f "$candidate" ]] && test_set["$candidate"]=1
  fi
done

if [[ ${#test_set[@]} -eq 0 ]]; then
  echo "No matching Pest test files for the changed code."
  echo "(For the full suite, run: vendor/bin/pest --compact)"
  exit 0
fi

echo "Matched:"
for t in "${!test_set[@]}"; do
  echo "  $t"
done

echo
echo "Running ${#test_set[@]} test file(s)..."
vendor/bin/pest --compact "$@" "${!test_set[@]}"
