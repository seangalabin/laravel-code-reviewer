#!/usr/bin/env bash
# post_review.sh — posts code-review findings as inline comments on the Bitbucket PR
# for the current branch.
#
# Usage:
#   ./post_review.sh < findings.json
#
# Input: a JSON array on stdin. Each element:
#   { "path": "app/Foo.php", "line": 42, "body": "MUST FIX — ..." }
#     → posted as an inline comment anchored to that file:line
#   { "body": "Summary..." }
#     → posted as a top-level PR comment (use for the compliance summary)
#
# Required env vars:
#   BITBUCKET_EMAIL     — your Bitbucket account email (e.g. sean@redhq.com.au)
#   BITBUCKET_API_TOKEN — API token with "Pull requests: write" scope
#                         Create one at: https://bitbucket.org/account/settings/personal-access-tokens/

set -euo pipefail

# ── Auth ──────────────────────────────────────────────────────────────────────
if [[ -z "${BITBUCKET_EMAIL:-}" || -z "${BITBUCKET_API_TOKEN:-}" ]]; then
    echo "ERROR: BITBUCKET_EMAIL and BITBUCKET_API_TOKEN must both be set." >&2
    echo "       export BITBUCKET_EMAIL=your@email.com" >&2
    echo "       export BITBUCKET_API_TOKEN=your_token" >&2
    exit 1
fi

# ── Repo info from git remote ─────────────────────────────────────────────────
REMOTE_URL=$(git remote get-url origin 2>/dev/null) || {
    echo "ERROR: no git remote 'origin' found." >&2
    exit 1
}

if [[ "$REMOTE_URL" =~ bitbucket\.org[:/]([^/]+)/([^/]+?)(\.git)?$ ]]; then
    WORKSPACE="${BASH_REMATCH[1]}"
    REPO_SLUG="${BASH_REMATCH[2]}"
else
    echo "ERROR: remote URL is not a recognised Bitbucket URL: $REMOTE_URL" >&2
    exit 1
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)
API_BASE="https://api.bitbucket.org/2.0/repositories/$WORKSPACE/$REPO_SLUG"
BASIC_AUTH="$BITBUCKET_EMAIL:$BITBUCKET_API_TOKEN"

# ── Read findings JSON from stdin ─────────────────────────────────────────────
FINDINGS_FILE=$(mktemp)
trap "rm -f '$FINDINGS_FILE'" EXIT

cat > "$FINDINGS_FILE"

python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
if not isinstance(data, list):
    print('ERROR: input must be a JSON array', file=sys.stderr)
    sys.exit(1)
" "$FINDINGS_FILE" || exit 1

# ── Find open PR for this branch ──────────────────────────────────────────────
ENCODED_BRANCH=$(python3 -c "import urllib.parse, sys; print(urllib.parse.quote(sys.argv[1]))" "$BRANCH")
QUERY="source.branch.name%3D%22${ENCODED_BRANCH}%22%20AND%20state%3D%22OPEN%22"

PR_JSON=$(curl -sSf -u "$BASIC_AUTH" \
    "$API_BASE/pullrequests?q=$QUERY&fields=values.id,values.title" 2>&1) || {
    echo "ERROR: Bitbucket API request failed. Check your credentials and network access." >&2
    echo "Response: $PR_JSON" >&2
    exit 1
}

PR_ID=$(python3 -c "
import sys, json
prs = json.load(sys.stdin).get('values', [])
print(prs[0]['id'] if prs else '')
" <<< "$PR_JSON")

if [[ -z "$PR_ID" ]]; then
    echo "ERROR: no open PR found for branch '$BRANCH' in $WORKSPACE/$REPO_SLUG." >&2
    echo "       Push the branch and open a PR first." >&2
    exit 1
fi

PR_TITLE=$(python3 -c "
import sys, json
prs = json.load(sys.stdin).get('values', [])
print(prs[0]['title'] if prs else '')
" <<< "$PR_JSON")

echo "Found PR #$PR_ID: $PR_TITLE"
echo ""

# ── Post each finding as an inline (or top-level) comment ────────────────────
python3 - "$FINDINGS_FILE" "$API_BASE" "$PR_ID" "$BASIC_AUTH" "$WORKSPACE" "$REPO_SLUG" <<'PYEOF'
import json, sys, subprocess

findings_file = sys.argv[1]
api_base      = sys.argv[2]
pr_id         = sys.argv[3]
auth          = sys.argv[4]
workspace     = sys.argv[5]
repo_slug     = sys.argv[6]

with open(findings_file) as f:
    findings = json.load(f)

posted = 0
failed = 0

for finding in findings:
    payload = {'content': {'raw': finding['body']}}

    if 'path' in finding and 'line' in finding:
        payload['inline'] = {'path': finding['path'], 'to': int(finding['line'])}
        location = f"{finding['path']}:{finding['line']}"
    else:
        location = 'PR level'

    result = subprocess.run(
        ['curl', '-sSf', '-u', auth,
         '-X', 'POST',
         '-H', 'Content-Type: application/json',
         '-d', json.dumps(payload),
         f'{api_base}/pullrequests/{pr_id}/comments'],
        capture_output=True, text=True
    )

    if result.returncode == 0:
        try:
            comment_id = json.loads(result.stdout).get('id', '?')
        except Exception:
            comment_id = '?'
        print(f'  ✓ comment #{comment_id} → {location}')
        posted += 1
    else:
        print(f'  ✗ failed ({location}): {result.stderr.strip() or result.stdout.strip()}',
              file=sys.stderr)
        failed += 1

print(f'\nPosted {posted} comment(s), {failed} failed.')
print(f'https://bitbucket.org/{workspace}/{repo_slug}/pull-requests/{pr_id}')
sys.exit(1 if failed > 0 else 0)
PYEOF
