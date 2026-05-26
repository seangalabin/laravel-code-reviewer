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

if [[ -z "${BITBUCKET_EMAIL:-}" || -z "${BITBUCKET_API_TOKEN:-}" ]]; then
    exit 0
fi

REMOTE_URL=$(git remote get-url origin 2>/dev/null) || exit 0
if [[ ! "$REMOTE_URL" =~ bitbucket\.org[:/]([^/]+)/([^/]+?)(\.git)?$ ]]; then
    exit 0
fi

WORKSPACE="${BASH_REMATCH[1]}"
REPO_SLUG="${BASH_REMATCH[2]}"
BRANCH=$(git rev-parse --abbrev-ref HEAD)
API_BASE="https://api.bitbucket.org/2.0/repositories/$WORKSPACE/$REPO_SLUG"
AUTH="$BITBUCKET_EMAIL:$BITBUCKET_API_TOKEN"

python3 - "$API_BASE" "$AUTH" "$BRANCH" 2>/dev/null <<'PYEOF' || true
import json, sys, subprocess, urllib.parse, re

api_base, auth, branch = sys.argv[1:4]


def curl(url):
    return subprocess.run(['curl', '-sSf', '-u', auth, url],
                          capture_output=True, text=True)


q = urllib.parse.quote(f'source.branch.name="{branch}" AND state="OPEN"')
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
