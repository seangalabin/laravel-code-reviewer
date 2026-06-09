#!/usr/bin/env bash
# save_reviewed_sha.sh — record the current HEAD SHA as a checkpoint on the PR.
#
# Posts (or updates) a hidden top-level PR comment containing:
#   <!-- ai-review:checkpoint:{sha} -->
#
# The next `/code-reviewer --since-last-review` reads this marker via
# get_checkpoint.sh and scopes the diff to new commits only.
#
# Storing the checkpoint on the PR (instead of on disk) means it survives
# fresh checkouts, multi-machine workflows, and teammates picking up the
# branch — all of them see the same checkpoint.
#
# Required env vars: BITBUCKET_EMAIL, BITBUCKET_API_TOKEN
# Falls back silently if creds are missing or no open PR exists.

set -euo pipefail

echo "💾 Saving review checkpoint to PR..." >&2

if [[ -z "${BITBUCKET_EMAIL:-}" || -z "${BITBUCKET_API_TOKEN:-}" ]]; then
    echo "  ↷ Skipping checkpoint — BITBUCKET_EMAIL / BITBUCKET_API_TOKEN not set." >&2
    exit 0
fi

REMOTE_URL=$(git remote get-url origin 2>/dev/null) || exit 0
if [[ ! "$REMOTE_URL" =~ bitbucket\.org[:/]([^/]+)/([^/]+?)(\.git)?$ ]]; then
    echo "  ↷ Skipping checkpoint — not a Bitbucket remote." >&2
    exit 0
fi

WORKSPACE="${BASH_REMATCH[1]}"
REPO_SLUG="${BASH_REMATCH[2]}"
HEAD_SHA=$(git rev-parse HEAD)
SHORT_SHA=$(git rev-parse --short HEAD)

# Branch and optional pre-resolved PR ID (target.json wins if present)
TARGET_JSON=".ai-review/target.json"
if [[ -f "$TARGET_JSON" ]]; then
    BRANCH=$(python3 -c "import json; print(json.load(open('$TARGET_JSON'))['branch'])")
    TARGET_PR_ID=$(python3 -c "import json; d=json.load(open('$TARGET_JSON')); print(d.get('pr_id') or '')")
else
    BRANCH=$(git rev-parse --abbrev-ref HEAD)
    TARGET_PR_ID=""
fi
API_BASE="https://api.bitbucket.org/2.0/repositories/$WORKSPACE/$REPO_SLUG"
AUTH="$BITBUCKET_EMAIL:$BITBUCKET_API_TOKEN"

python3 - "$API_BASE" "$AUTH" "$BRANCH" "$HEAD_SHA" "$SHORT_SHA" "${TARGET_PR_ID:-}" <<'PYEOF'
import json, sys, subprocess, urllib.parse, re

api_base, auth, branch, head_sha, short, target_pr_id = sys.argv[1:7]


def curl(*args):
    return subprocess.run(['curl', '-sSf', '-u', auth, *args],
                          capture_output=True, text=True)


# ── Find open PR for branch (skip lookup when target.json provided the ID) ──
if target_pr_id:
    pr_id = int(target_pr_id)
else:
    q = urllib.parse.quote(f'source.branch.name="{branch}" AND state="OPEN"')
    r = curl(f'{api_base}/pullrequests?q={q}&fields=values.id')
    if r.returncode != 0:
        print(f'  Skipping checkpoint — Bitbucket API failed: {r.stderr.strip()}', file=sys.stderr)
        sys.exit(0)
    prs = json.loads(r.stdout).get('values', [])
    if not prs:
        print(f'  Skipping checkpoint — no open PR for branch "{branch}".', file=sys.stderr)
        sys.exit(0)
    pr_id = prs[0]['id']

comments_url = f'{api_base}/pullrequests/{pr_id}/comments'

body = (
    f'<!-- ai-review:checkpoint:{head_sha} -->\n\n'
    f'🔖 _Code review checkpoint — last reviewed at `{short}`. '
    f'Used by `/code-reviewer --since-last-review` to skip already-reviewed commits._'
)

# ── Look for an existing checkpoint comment (top-level only) ──
existing_id = None
url = f'{comments_url}?pagelen=50'
while url:
    r = curl(url)
    if r.returncode != 0:
        break
    page = json.loads(r.stdout)
    for c in page.get('values', []):
        if c.get('inline'):
            continue  # checkpoint is a top-level comment, not inline
        raw = c.get('content', {}).get('raw', '')
        if re.search(r'<!--\s*ai-review:checkpoint:', raw):
            existing_id = c['id']
            break
    if existing_id:
        break
    url = page.get('next')

payload = json.dumps({'content': {'raw': body}})

if existing_id:
    r = curl('-X', 'PUT', '-H', 'Content-Type: application/json',
             '-d', payload, f'{comments_url}/{existing_id}')
    msg = f'  Checkpoint updated → {short}' if r.returncode == 0 \
          else f'  Failed to update checkpoint: {r.stderr.strip()}'
else:
    r = curl('-X', 'POST', '-H', 'Content-Type: application/json',
             '-d', payload, comments_url)
    msg = f'  Checkpoint posted → {short}' if r.returncode == 0 \
          else f'  Failed to post checkpoint: {r.stderr.strip()}'

print(msg, file=sys.stdout if r.returncode == 0 else sys.stderr)
PYEOF
