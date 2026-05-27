#!/usr/bin/env bash
# cleanup_target.sh — remove the git worktree created by setup_target.sh.
#
# Usage:
#   cleanup_target.sh <worktree-path>

set -euo pipefail

WORKTREE="${1:-}"

if [[ -z "$WORKTREE" ]]; then
    echo "Usage: cleanup_target.sh <worktree-path>" >&2
    exit 1
fi

if [[ ! -d "$WORKTREE" ]]; then
    echo "  Worktree not found at '$WORKTREE' — already removed." >&2
    exit 0
fi

git worktree remove --force "$WORKTREE" 2>/dev/null \
    || rm -rf "$WORKTREE"

echo "  Worktree removed: $WORKTREE" >&2
