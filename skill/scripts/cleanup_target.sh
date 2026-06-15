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

if ! git worktree remove --force "$WORKTREE" 2>/dev/null; then
    # Not a registered worktree (or remove failed). Delete the dir directly,
    # then prune so no stale admin entry leaks into .git/worktrees.
    rm -rf "$WORKTREE"
    git worktree prune 2>/dev/null || true
fi

echo "  Worktree removed: $WORKTREE" >&2
