#!/usr/bin/env bash
# One-glance summary of what the current branch changed vs the base.
# Usage: ./scripts/branch_summary.sh [base-branch]
# Default base: develop

set -euo pipefail

BASE="${1:-${AI_REVIEW_BASE_BRANCH:-${BASE_BRANCH:-develop}}}"
REMOTE_BASE="origin/${BASE}"
HEAD_BRANCH=$(git branch --show-current)

git fetch origin "${BASE}" 2>/dev/null || true

if ! git rev-parse --verify "${REMOTE_BASE}" >/dev/null 2>&1; then
  echo "error: ${REMOTE_BASE} not found. Try: git fetch origin ${BASE}"
  exit 1
fi

COMMITS_AHEAD=$(git rev-list --count "${REMOTE_BASE}..HEAD")
FILES_CHANGED=$(git diff --name-only "${REMOTE_BASE}...HEAD" | wc -l | tr -d ' ')
UNTRACKED=$(git ls-files --others --exclude-standard | wc -l | tr -d ' ')

echo "Base:           ${BASE} @ ${REMOTE_BASE}"
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
