#!/usr/bin/env bash
# refresh_branch.sh — fetch the current branch and base branch from origin,
# fast-forward the local branch if it cleanly lags the remote, and warn on
# divergence. Runs before /code-reviewer resolves its diff base so PR reviews
# always see the latest commits on Bitbucket.
#
# Skips silently when invoked inside a target-mode worktree
# (setup_target.sh already fetched and the worktree is detached at the
# latest origin/<branch>).
#
# Exits 0 in all non-error paths so the caller can continue.

set -uo pipefail

BASE="${BASE_BRANCH:-develop}"

# Target mode: .ai-review/target.json lives at the worktree root and the
# worktree was created from a freshly-fetched origin/<branch>. Nothing to do.
if [[ -f .ai-review/target.json ]]; then
    exit 0
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)
if [[ -z "$BRANCH" || "$BRANCH" == "HEAD" ]]; then
    # Detached HEAD — nothing to align.
    exit 0
fi

echo "  Refreshing origin/$BASE and origin/$BRANCH..." >&2
if ! git fetch origin "$BASE" "$BRANCH" 2>&1 | sed 's/^/  /' >&2; then
    echo "  ⚠️  Couldn't fetch — reviewing against your local copy." >&2
    exit 0
fi

if ! git rev-parse --verify "origin/$BRANCH" >/dev/null 2>&1; then
    # No remote branch yet (first push pending). Nothing to align.
    exit 0
fi

BEHIND=$(git rev-list --count "HEAD..origin/$BRANCH" 2>/dev/null || echo 0)
AHEAD=$(git rev-list --count "origin/$BRANCH..HEAD" 2>/dev/null || echo 0)

if [[ "$BEHIND" -eq 0 && "$AHEAD" -eq 0 ]]; then
    exit 0
fi

if [[ "$BEHIND" -gt 0 && "$AHEAD" -eq 0 ]]; then
    echo "  Local branch is $BEHIND commit(s) behind origin/$BRANCH — fast-forwarding." >&2
    git merge --ff-only "origin/$BRANCH" 2>&1 | sed 's/^/  /' >&2
    exit 0
fi

if [[ "$AHEAD" -gt 0 && "$BEHIND" -eq 0 ]]; then
    echo "  Local branch has $AHEAD unpushed commit(s). Reviewing local HEAD." >&2
    exit 0
fi

echo "  ⚠️  Local branch and origin/$BRANCH have diverged ($AHEAD ahead, $BEHIND behind)." >&2
echo "     Reviewing local HEAD. Pull/rebase and re-run to review the remote view." >&2
exit 0
