#!/usr/bin/env bash
# setup_target.sh — create a git worktree for reviewing a branch without checkout.
#
# Usage:
#   setup_target.sh --branch=<name>
#   setup_target.sh --pr=<N>
#
# Prints the worktree path to stdout (all status messages go to stderr).
# Writes .ai-review/target.json inside the worktree so every subsequent
# script knows the target branch and PR ID without touching git state.
#
# Required env vars when using --pr: BITBUCKET_EMAIL, BITBUCKET_API_TOKEN

set -euo pipefail

BRANCH=""
PR_ID=""

for arg in "$@"; do
    case "$arg" in
        --branch=*) BRANCH="${arg#--branch=}" ;;
        --pr=*)     PR_ID="${arg#--pr=}"     ;;
    esac
done

if [[ -z "$BRANCH" && -z "$PR_ID" ]]; then
    echo "ERROR: pass --branch=<name> or --pr=<N>" >&2
    exit 1
fi

# ── Repo info ─────────────────────────────────────────────────────────────────
REMOTE_URL=$(git remote get-url origin 2>/dev/null) || {
    echo "ERROR: no git remote 'origin' found." >&2
    exit 1
}

IS_BITBUCKET=false
WORKSPACE=""
REPO_SLUG=""
if [[ "$REMOTE_URL" =~ bitbucket\.org[:/]([^/]+)/([^/]+?)(\.git)?$ ]]; then
    WORKSPACE="${BASH_REMATCH[1]}"
    REPO_SLUG="${BASH_REMATCH[2]}"
    IS_BITBUCKET=true
fi

BB_AUTH="${BITBUCKET_EMAIL:-}:${BITBUCKET_API_TOKEN:-}"

# ── Resolve branch from PR number ─────────────────────────────────────────────
if [[ -n "$PR_ID" && -z "$BRANCH" ]]; then
    if [[ -z "${BITBUCKET_EMAIL:-}" || -z "${BITBUCKET_API_TOKEN:-}" ]]; then
        echo "ERROR: --pr requires BITBUCKET_EMAIL and BITBUCKET_API_TOKEN." >&2
        exit 1
    fi
    if [[ "$IS_BITBUCKET" != "true" ]]; then
        echo "ERROR: --pr requires a Bitbucket remote URL." >&2
        exit 1
    fi

    BRANCH=$(python3 - "$WORKSPACE" "$REPO_SLUG" "$PR_ID" "$BB_AUTH" <<'PYEOF'
import sys, json, subprocess
workspace, repo, pr_id, auth = sys.argv[1:5]
r = subprocess.run(
    ['curl', '-sSf', '-u', auth,
     f'https://api.bitbucket.org/2.0/repositories/{workspace}/{repo}'
     f'/pullrequests/{pr_id}?fields=source.branch.name'],
    capture_output=True, text=True,
)
if r.returncode != 0:
    print(f'ERROR: Bitbucket API failed: {r.stderr.strip()}', file=sys.stderr)
    sys.exit(1)
data = json.loads(r.stdout)
branch = data.get('source', {}).get('branch', {}).get('name', '')
if not branch:
    print(f'ERROR: could not read branch name from PR #{pr_id}', file=sys.stderr)
    sys.exit(1)
print(branch)
PYEOF
    )
fi

# ── Guard against protected branches ─────────────────────────────────────────
if [[ "$BRANCH" =~ ^(main|master|develop)$ ]]; then
    echo "ERROR: Refusing to review protected branch '$BRANCH'." >&2
    exit 1
fi

# ── Require Bitbucket creds to find the PR for a branch ───────────────────────
# Without a token we cannot look the PR up; failing loudly here (instead of
# silently proceeding with pr_id=null) keeps --branch symmetric with --pr above.
if [[ -z "$PR_ID" && "$IS_BITBUCKET" == "true" ]] \
   && { [[ -z "${BITBUCKET_EMAIL:-}" ]] || [[ -z "${BITBUCKET_API_TOKEN:-}" ]]; }; then
    echo "ERROR: --branch needs Bitbucket API credentials to find the PR for '$BRANCH'." >&2
    echo "       Set BITBUCKET_EMAIL and BITBUCKET_API_TOKEN, then re-run." >&2
    echo "       In Claude Code, add them to .claude/settings.local.json under \"env\"" >&2
    echo "       (hot-reloads, no restart needed):" >&2
    echo '         { "env": { "BITBUCKET_EMAIL": "you@example.com", "BITBUCKET_API_TOKEN": "<token>" } }' >&2
    exit 1
fi

# ── Resolve PR ID from branch name when only --branch was given ───────────────
# Distinguish three outcomes that used to collapse into a silent empty pr_id:
#   • HTTP 200, no match → genuinely no open PR for this branch
#   • HTTP 401/403       → the token is REJECTED (expired/revoked/wrong scopes)
#   • curl/other failure → couldn't reach Bitbucket
# Only the first is "no PR"; the other two get a loud stderr warning so the
# review's final message reflects the real cause instead of "no open PR".
if [[ -z "$PR_ID" && "$IS_BITBUCKET" == "true" ]]; then
    PR_ID=$(python3 - "$WORKSPACE" "$REPO_SLUG" "$BRANCH" "$BB_AUTH" <<'PYEOF' || true
import sys, json, subprocess, urllib.parse
workspace, repo, branch, auth = sys.argv[1:5]
q = urllib.parse.quote(f'source.branch.name="{branch}" AND state="OPEN"', safe='')
r = subprocess.run(
    ['curl', '-sS', '-w', '\n__HTTP__%{http_code}', '-u', auth,
     f'https://api.bitbucket.org/2.0/repositories/{workspace}/{repo}'
     f'/pullrequests?q={q}&fields=values.id'],
    capture_output=True, text=True,
)
body, _, code = r.stdout.rpartition('__HTTP__')
code = code.strip()
if r.returncode != 0:
    print(f"WARNING: couldn't reach Bitbucket to find the PR for '{branch}' "
          f"(curl exit {r.returncode}). The review will run but can't post.", file=sys.stderr)
    sys.exit(0)
if code in ('401', '403'):
    print(f"WARNING: Bitbucket rejected the API credentials (HTTP {code}) while looking up "
          f"the PR for '{branch}'.", file=sys.stderr)
    print("         This is NOT 'no PR' — the review will run, but findings can't be posted.", file=sys.stderr)
    print("         BITBUCKET_API_TOKEN is invalid, expired, or lacks Bitbucket scopes. Regenerate it", file=sys.stderr)
    print("         at https://id.atlassian.com/manage-profile/security/api-tokens (Pull requests:", file=sys.stderr)
    print("         read+write) and confirm BITBUCKET_EMAIL matches that Atlassian account.", file=sys.stderr)
    sys.exit(0)
if code != '200':
    print(f"WARNING: Bitbucket returned HTTP {code} while looking up the PR for '{branch}'. "
          f"The review will run but can't post.", file=sys.stderr)
    sys.exit(0)
try:
    prs = json.loads(body).get('values', [])
except json.JSONDecodeError:
    sys.exit(0)
print(prs[0]['id'] if prs else '')
PYEOF
    ) || PR_ID=""
fi

# ── Fetch the branch and create worktree ──────────────────────────────────────
echo "  Fetching origin/$BRANCH..." >&2
git fetch origin "$BRANCH" 2>&1 | sed 's/^/  /' >&2 || {
    echo "ERROR: could not fetch 'origin/$BRANCH'. Does the branch exist on the remote?" >&2
    exit 1
}

WORKTREE=$(mktemp -d /tmp/ai-review-XXXXXX)
echo "  Creating worktree at $WORKTREE..." >&2
git worktree add --detach "$WORKTREE" "origin/$BRANCH" 2>&1 | sed 's/^/  /' >&2

# ── Write target.json inside the worktree ─────────────────────────────────────
python3 - "$BRANCH" "${PR_ID:-}" "$WORKTREE" <<'PYEOF'
import sys, json, os
branch, pr_id_str, worktree = sys.argv[1:4]
os.makedirs(f'{worktree}/.ai-review', exist_ok=True)
data = {
    'branch':       branch,
    'pr_id':        int(pr_id_str) if pr_id_str else None,
    'worktree_path': worktree,
}
with open(f'{worktree}/.ai-review/target.json', 'w') as f:
    json.dump(data, f, indent=2)
PYEOF

echo "  Ready — branch: $BRANCH${PR_ID:+, PR #$PR_ID}" >&2
echo "$WORKTREE"
