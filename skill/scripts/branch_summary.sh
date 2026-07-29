#!/usr/bin/env bash
# One-glance summary of what the current branch changed vs the base.
# Usage: ./scripts/branch_summary.sh [base-branch]
# Default base: develop

set -euo pipefail

BASE="${1:-${AI_REVIEW_BASE_BRANCH:-${BASE_BRANCH:-develop}}}"
HEAD_BRANCH=$(git branch --show-current)

# If BASE looks like a commit SHA (7–40 hex chars), use it directly.
# Otherwise treat it as a branch name and resolve via origin/.
if [[ "$BASE" =~ ^[0-9a-f]{7,40}$ ]]; then
    REMOTE_BASE="$BASE"
else
    REMOTE_BASE="origin/${BASE}"
    git fetch origin "${BASE}" 2>/dev/null || true
fi

if ! git rev-parse --verify "${REMOTE_BASE}" >/dev/null 2>&1; then
  echo "error: ${REMOTE_BASE} not found."
  exit 1
fi

COMMITS_AHEAD=$(git rev-list --count "${REMOTE_BASE}..HEAD")
FILES_CHANGED=$(git diff --name-only "${REMOTE_BASE}...HEAD" | wc -l | tr -d ' ')
UNTRACKED=$(git ls-files --others --exclude-standard | wc -l | tr -d ' ')

echo "Base:           ${REMOTE_BASE}"
echo "Branch:         ${HEAD_BRANCH}"
echo "Commits ahead:  ${COMMITS_AHEAD}"
echo "Files changed:  ${FILES_CHANGED}"
echo "Untracked:      ${UNTRACKED}"
echo
echo "Changed files by type:"
git diff --name-only "${REMOTE_BASE}...HEAD" | while read -r f; do
  case "$f" in
    *.blade.php)   echo "Blade"      ;;
    *.php)         echo "PHP"        ;;
    *.vue)         echo "Vue"        ;;
    *.js|*.ts)     echo "JS/TS"      ;;
    *.yaml|*.yml)  echo "YAML"       ;;
    *.json)        echo "JSON"       ;;
    *.css|*.scss)  echo "CSS"        ;;
    *)             echo "Other"      ;;
  esac
done | sort | uniq -c | awk '{printf "  %-8s %d\n", $2 ":", $1}'

echo
echo "Recent commits:"
git log --oneline "${REMOTE_BASE}..HEAD"
