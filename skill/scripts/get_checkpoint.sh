#!/usr/bin/env bash
# get_checkpoint.sh — print the last-reviewed SHA from the PR's checkpoint
# comment, or nothing if no checkpoint exists.
#
# Used by SKILL.md when `--since-last-review` is passed:
#   CHECKPOINT_SHA=$(.claude/skills/code-reviewer/scripts/get_checkpoint.sh)
#
# Exits silently with no output on any failure (no creds, no PR, API error)
# so the caller can fall back cleanly to a full diff against develop.
#
# Required env vars: BITBUCKET_EMAIL, BITBUCKET_API_TOKEN

set -euo pipefail

echo "🔍 Checking PR for previous review checkpoint..." >&2

if [[ -z "${BITBUCKET_EMAIL:-}" || -z "${BITBUCKET_API_TOKEN:-}" ]]; then
    echo "  ↷ Bitbucket creds not set — full review against develop." >&2
    exit 0
fi

REMOTE_URL=$(git remote get-url origin 2>/dev/null) || {
    echo "  ↷ No git remote — full review against develop." >&2; exit 0; }
if [[ ! "$REMOTE_URL" =~ bitbucket\.org[:/]([^/]+)/([^/]+?)(\.git)?$ ]]; then
    echo "  ↷ Not a Bitbucket remote — full review against develop." >&2
    exit 0
fi

WORKSPACE="${BASH_REMATCH[1]}"
REPO_SLUG="${BASH_REMATCH[2]}"
API_BASE="https://api.bitbucket.org/2.0/repositories/$WORKSPACE/$REPO_SLUG"
AUTH="$BITBUCKET_EMAIL:$BITBUCKET_API_TOKEN"

# Branch and optional pre-resolved PR ID (target.json wins if present)
TARGET_JSON=".ai-review/target.json"
if [[ -f "$TARGET_JSON" ]]; then
    BRANCH=$(python3 -c "import json; print(json.load(open('$TARGET_JSON'))['branch'])" 2>/dev/null) || exit 0
    TARGET_PR_ID=$(python3 -c "import json; d=json.load(open('$TARGET_JSON')); print(d.get('pr_id') or '')" 2>/dev/null) || TARGET_PR_ID=""
else
    BRANCH=$(git rev-parse --abbrev-ref HEAD)
    TARGET_PR_ID=""
fi

# Capture the SHA so we can emit a stderr status alongside it.
CHECKPOINT_SHA=$(python3 - "$API_BASE" "$AUTH" "$BRANCH" "${TARGET_PR_ID:-}" 2>/dev/null <<'PYEOF' || true
import json, sys, subprocess, urllib.parse, re

api_base, auth, branch, target_pr_id = sys.argv[1:5]


def curl(url):
    return subprocess.run(['curl', '-sSf', '-u', auth, url],
                          capture_output=True, text=True)


if target_pr_id:
    pr_id = int(target_pr_id)
else:
    q = urllib.parse.quote(f'source.branch.name="{branch}" AND state="OPEN"', safe='')
    r = curl(f'{api_base}/pullrequests?q={q}&fields=values.id')
    if r.returncode != 0:
        sys.exit(0)
    prs = json.loads(r.stdout).get('values', [])
    if not prs:
        sys.exit(0)
    pr_id = prs[0]['id']

url = f'{api_base}/pullrequests/{pr_id}/comments?pagelen=50'
while url:
    r = curl(url)
    if r.returncode != 0:
        sys.exit(0)
    page = json.loads(r.stdout)
    for c in page.get('values', []):
        if c.get('inline'):
            continue
        raw = c.get('content', {}).get('raw', '')
        m = re.search(r'<!--\s*ai-review:checkpoint:([a-f0-9]+)\s*-->', raw)
        if m:
            print(m.group(1))
            sys.exit(0)
    url = page.get('next')
PYEOF
)

if [[ -n "$CHECKPOINT_SHA" ]]; then
    echo "  ✓ Found checkpoint at ${CHECKPOINT_SHA:0:7} — incremental review." >&2
    echo "$CHECKPOINT_SHA"
else
    echo "  ↷ No checkpoint comment on PR yet — full review against develop." >&2
fi
