#!/usr/bin/env bash
# get_checkpoint.sh — print the last-reviewed SHA from the PR's checkpoint
# comment, or nothing if no checkpoint exists.
#
# Used by SKILL.md when `--since-last-review` is passed:
#   CHECKPOINT_SHA=$(.claude/skills/code-reviewer/scripts/get_checkpoint.sh)
#
# Prints nothing (letting the caller fall back to a full diff against develop)
# when there is no checkpoint, no creds, or no PR. A *persistent* Bitbucket API
# error (after retries) is reported distinctly on stderr rather than being
# passed off as "no checkpoint" — a transient API blip must not read as if the
# saved checkpoint comment vanished. Transient failures (network, 429, 5xx) are
# retried with backoff before giving up.
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

# Capture the SHA and the python exit code so we can tell three states apart:
#   exit 0 + SHA on stdout → checkpoint found (incremental review)
#   exit 0 + empty stdout  → genuinely no checkpoint yet (full review)
#   exit 3                 → Bitbucket API error after retries; the checkpoint
#                            may still exist. Fall back to a full review, but
#                            DON'T claim "no checkpoint" — that misleads the dev
#                            into thinking the saved comment vanished.
PY_STATUS=0
CHECKPOINT_SHA=$(python3 - "$API_BASE" "$AUTH" "$BRANCH" "${TARGET_PR_ID:-}" 2>/dev/null <<'PYEOF'
import json, sys, subprocess, urllib.parse, re, time

api_base, auth, branch, target_pr_id = sys.argv[1:5]


def curl_json(url, retries=3):
    """Fetch url → (ok, data). Retries transient failures (curl transport error,
    HTTP 429 / 5xx) with backoff. ok=False signals a *persistent* API error —
    the caller must NOT treat that as 'no checkpoint'."""
    delay = 0.5
    for attempt in range(retries + 1):
        r = subprocess.run(
            ['curl', '-sS', '-w', '\n__HTTP__%{http_code}', '-u', auth, url],
            capture_output=True, text=True)
        body, _, code = r.stdout.rpartition('__HTTP__')
        code = code.strip()
        if r.returncode == 0 and code.startswith('2'):
            try:
                return True, json.loads(body)
            except json.JSONDecodeError:
                return False, None
        transient = (r.returncode != 0) or code == '429' or code.startswith('5')
        if not transient or attempt == retries:
            return False, None
        time.sleep(delay)
        delay *= 2
    return False, None


if target_pr_id:
    pr_id = int(target_pr_id)
else:
    q = urllib.parse.quote(f'source.branch.name="{branch}" AND state="OPEN"', safe='')
    ok, data = curl_json(f'{api_base}/pullrequests?q={q}&fields=values.id')
    if not ok:
        sys.exit(3)               # API error resolving the PR — state unknown
    prs = data.get('values', [])
    if not prs:
        sys.exit(0)               # genuinely no open PR
    pr_id = prs[0]['id']

url = (f'{api_base}/pullrequests/{pr_id}/comments'
       '?pagelen=100&fields=values.id,values.inline,values.content.raw,next')
while url:
    ok, page = curl_json(url)
    if not ok:
        sys.exit(3)               # error mid-pagination — checkpoint may exist
    for c in page.get('values', []):
        if c.get('inline'):
            continue
        raw = (c.get('content', {}) or {}).get('raw', '') or ''
        m = re.search(r'<!--\s*ai-review:checkpoint:([a-f0-9]+)\s*-->', raw)
        if m:
            print(m.group(1))
            sys.exit(0)
    url = page.get('next')
sys.exit(0)                       # paginated fully — genuinely absent
PYEOF
) || PY_STATUS=$?

if [[ "$PY_STATUS" -eq 3 ]]; then
    echo "  ⚠️  Couldn't read the checkpoint — Bitbucket API error after retries." >&2
    echo "      Running a full review against develop. Your saved checkpoint likely still" >&2
    echo "      exists; the next run should pick it up once the API is reachable." >&2
elif [[ -n "$CHECKPOINT_SHA" ]]; then
    echo "  ✓ Found checkpoint at ${CHECKPOINT_SHA:0:7} — incremental review." >&2
    echo "$CHECKPOINT_SHA"
else
    echo "  ↷ No checkpoint comment on PR yet — full review against develop." >&2
fi
