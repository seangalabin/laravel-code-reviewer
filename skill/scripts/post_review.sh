#!/usr/bin/env bash
# post_review.sh — posts code-review findings as inline comments on the Bitbucket PR
# for the current branch.
#
# Usage (preferred — pass a UTF-8 findings file written by the editor):
#   ./post_review.sh .ai-review/findings.json
#
# Usage (fallback — pipe a JSON array on stdin):
#   ./post_review.sh < findings.json
#
# Input: a JSON array (from the file-path arg or stdin). Each element:
#   { "path": "app/Foo.php", "line": 42, "body": "MUST FIX — ..." }
#     → posted as an inline comment anchored to that file:line
#   { "body": "Summary..." }
#     → posted as a top-level PR comment (use for the compliance summary)
#
# Required env vars:
#   BITBUCKET_EMAIL     — your Bitbucket account email
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

# NOTE: the trailing `.git` is stripped with ${...%.git} rather than matched by an
# optional group. The previous pattern used `([^/]+?)` — a NON-GREEDY quantifier,
# which is not valid POSIX ERE. glibc tolerates it, so CI (node:20/Debian) matched
# fine, but BSD libc does not: on macOS bash 3.2 this failed to match EVERY remote
# URL form, so the script bailed with "not a recognised Bitbucket URL" for every
# local run. Keep this POSIX-clean.
if [[ "$REMOTE_URL" =~ bitbucket\.org[:/]([^/]+)/([^/]+)$ ]]; then
    WORKSPACE="${BASH_REMATCH[1]}"
    REPO_SLUG="${BASH_REMATCH[2]%.git}"
else
    echo "ERROR: remote URL is not a recognised Bitbucket URL: $REMOTE_URL" >&2
    exit 1
fi

API_BASE="https://api.bitbucket.org/2.0/repositories/$WORKSPACE/$REPO_SLUG"
BASIC_AUTH="$BITBUCKET_EMAIL:$BITBUCKET_API_TOKEN"

# ── Read findings JSON: prefer a file-path arg (UTF-8), fall back to stdin ────
# The optional first argument is a path to a UTF-8 findings file written by the
# editor — the same calling convention as post_review.ps1. This sidesteps shell
# quoting and (on Windows) console-encoding issues; falls back to reading stdin
# (heredoc) when no path is given.
FINDINGS_PATH="${1:-}"
FINDINGS_FILE=$(mktemp)
trap "rm -f '$FINDINGS_FILE'" EXIT

if [[ -n "$FINDINGS_PATH" ]]; then
    if [[ ! -f "$FINDINGS_PATH" ]]; then
        echo "ERROR: findings file not found: $FINDINGS_PATH" >&2
        exit 1
    fi
    cat "$FINDINGS_PATH" > "$FINDINGS_FILE"
else
    cat > "$FINDINGS_FILE"
fi

python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
if not isinstance(data, list):
    print('ERROR: input must be a JSON array', file=sys.stderr)
    sys.exit(1)
" "$FINDINGS_FILE" || exit 1

# ── Resolve branch and PR (target.json wins if present) ───────────────────────
TARGET_JSON=".ai-review/target.json"
if [[ -f "$TARGET_JSON" ]]; then
    BRANCH=$(python3 -c "import json; print(json.load(open('$TARGET_JSON'))['branch'])")
    PR_ID=$(python3 -c "import json; d=json.load(open('$TARGET_JSON')); print(d.get('pr_id') or '')")
else
    BRANCH=$(git rev-parse --abbrev-ref HEAD)
    PR_ID=""
fi

# In a dry run there is nothing to post, so resolving the real PR is pointless — and
# resolving it requires a live Bitbucket call, which the eval harness has no
# credentials for and must not depend on. Use a placeholder and let the reporting
# path downstream describe what would have happened.
if [[ -n "${AI_REVIEW_DRY_RUN:-}" && -z "$PR_ID" ]]; then
    PR_ID="DRY-RUN"
fi

if [[ -z "$PR_ID" ]]; then
    # quote(..., safe='') so a "/" in the branch (e.g. feature/B20-1) is encoded
    # too — an unescaped "/" inside the already-encoded BBQL value breaks the
    # PR lookup and yields a false "no open PR found".
    ENCODED_BRANCH=$(python3 -c "import urllib.parse, sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$BRANCH")
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

    PR_TITLE=$(python3 -c "
import sys, json
prs = json.load(sys.stdin).get('values', [])
print(prs[0]['title'] if prs else '')
" <<< "$PR_JSON")
else
    PR_TITLE=""
fi

if [[ -z "$PR_ID" ]]; then
    echo "ERROR: no open PR found for branch '$BRANCH' in $WORKSPACE/$REPO_SLUG." >&2
    echo "       Push the branch and open a PR first." >&2
    exit 1
fi

echo "Found PR #$PR_ID${PR_TITLE:+: $PR_TITLE}"
echo ""

# ── Capture HEAD SHA for comment tracking ─────────────────────────────────────
HEAD_SHA=$(git rev-parse HEAD)

# ── Post each finding as an inline (or top-level) comment ────────────────────
python3 - "$FINDINGS_FILE" "$API_BASE" "$PR_ID" "$BASIC_AUTH" "$WORKSPACE" "$REPO_SLUG" "$HEAD_SHA" <<'PYEOF'
import json, os, sys, subprocess

findings_file = sys.argv[1]
api_base      = sys.argv[2]
pr_id         = sys.argv[3]
auth          = sys.argv[4]
workspace     = sys.argv[5]
repo_slug     = sys.argv[6]
head_sha      = sys.argv[7]

with open(findings_file) as f:
    findings = json.load(f)

# ── Severity gate ─────────────────────────────────────────────────────────────
# Enforced here, in the script, and not only in the prompt: a prompt instruction is
# a strong suggestion, a filter is a guarantee. The lens carries far more 🔵
# Suggestion rules than 🔴/🟡 ones, and a review whose output is mostly style nits
# gets skimmed instead of read — so cap what actually reaches the PR.
#
#   AI_REVIEW_MIN_SEVERITY    critical | warning | suggestion   (default: see below)
#   AI_REVIEW_MAX_SUGGESTIONS integer, 0 = none                 (default 3)
#
# Default floor is `warning` in CI and `suggestion` locally: a developer who ran the
# skill by hand asked for everything, whereas a pipeline posts to a PR other people
# have to read. Set AI_REVIEW_MIN_SEVERITY explicitly to override either way.
#
# Withheld findings are counted and reported, never silently dropped — the operator
# must be able to see that the gate did something.
RANK = {'critical': 3, 'warning': 2, 'suggestion': 1}
EMOJI_RANK = {'\U0001F534': 3, '\U0001F7E1': 2, '\U0001F535': 1}


def severity_rank(finding):
    """Rank a finding, preferring the explicit field and falling back to the emoji.

    Anything unrecognised ranks as critical: a finding whose severity we cannot read
    must not be silently discarded by a gate meant to remove noise.
    """
    s = str(finding.get('severity', '')).strip().lower()
    if s in RANK:
        return RANK[s]
    head = finding.get('body', '')[:200]
    for glyph, rank in EMOJI_RANK.items():
        if glyph in head:
            return rank
    return 3


def apply_severity_gate(findings):
    ci = os.environ.get('AI_REVIEW_CI') or os.environ.get('CI', '').lower() == 'true'
    floor_name = os.environ.get(
        'AI_REVIEW_MIN_SEVERITY', 'warning' if ci else 'suggestion').strip().lower()
    floor = RANK.get(floor_name)
    if floor is None:
        print(f'  \u21b7 AI_REVIEW_MIN_SEVERITY="{floor_name}" is not one of '
              'critical/warning/suggestion — ignoring the floor.', file=sys.stderr)
        floor = 1
        floor_name = 'suggestion'

    raw_cap = os.environ.get('AI_REVIEW_MAX_SUGGESTIONS', '3').strip()
    try:
        cap = max(0, int(raw_cap))
    except ValueError:
        print(f'  \u21b7 AI_REVIEW_MAX_SUGGESTIONS="{raw_cap}" is not an integer — '
              'using the default of 3.', file=sys.stderr)
        cap = 3

    kept, below_floor, over_cap = [], 0, 0
    suggestions_kept = 0
    for f in findings:
        rank = severity_rank(f)
        if rank < floor:
            below_floor += 1
            continue
        if rank == 1:
            if suggestions_kept >= cap:
                over_cap += 1
                continue
            suggestions_kept += 1
        kept.append(f)

    if below_floor:
        print(f'  \u21b7 {below_floor} finding(s) withheld: below the '
              f'AI_REVIEW_MIN_SEVERITY={floor_name} floor.')
    if over_cap:
        print(f'  \u21b7 {over_cap} suggestion(s) withheld: over the '
              f'AI_REVIEW_MAX_SUGGESTIONS={cap} cap.')
    if below_floor or over_cap:
        print(f'  \u2192 posting {len(kept)} of {len(findings)} finding(s). '
              'Withheld findings are still listed in the run\'s coverage ledger.')
    return kept


findings = apply_severity_gate(findings)
if not findings:
    print('  \u21b7 Nothing left to post after the severity gate.')
    sys.exit(0)

# ── Dry run ───────────────────────────────────────────────────────────────────
# AI_REVIEW_DRY_RUN=1 makes every Bitbucket write a no-op: the findings file is
# still produced and the plan is printed, but nothing reaches the PR. Two users:
# the eval harness (which scores findings and must never touch a real PR), and a
# developer testing the skill against a live PR without spraying comments on it.
if os.environ.get('AI_REVIEW_DRY_RUN'):
    print('  \u21b7 DRY RUN — no comments, tasks, or checkpoints will be posted.')
    for f in findings:
        loc = (f"{f['path']}:{f['line']}"
               if 'path' in f and 'line' in f else 'PR level')
        sev = str(f.get('severity', '?')).lower()
        print(f'     would post [{sev}] {loc}'
              + ('  + blocking task' if sev == 'critical' else ''))
    print(f'  \u21b7 {len(findings)} finding(s) would post to PR #{pr_id}.')
    sys.exit(0)

comments_url = f'{api_base}/pullrequests/{pr_id}/comments'
tasks_url    = f'{api_base}/pullrequests/{pr_id}/tasks'

def post_comment(payload):
    return subprocess.run(
        ['curl', '-sSf', '-u', auth,
         '-X', 'POST',
         '-H', 'Content-Type: application/json',
         '-d', json.dumps(payload),
         comments_url],
        capture_output=True, text=True
    )

def update_comment(comment_id, body):
    subprocess.run(
        ['curl', '-sSf', '-u', auth,
         '-X', 'PUT',
         '-H', 'Content-Type: application/json',
         '-d', json.dumps({'content': {'raw': body}}),
         f'{comments_url}/{comment_id}'],
        capture_output=True, text=True
    )

def create_task(comment_id, text):
    """Create a Bitbucket PR task linked to a comment. Returns (ok, detail).

    A 🔴 Critical finding is supposed to block the merge, and a comment cannot do
    that — only a PR task can, via the repo's "Check for unresolved tasks" merge
    check. Best-effort by design: some workspaces/plans do not expose the tasks
    endpoint, and a review that posted its findings must not be reported as failed
    just because the task could not be created.
    """
    r = subprocess.run(
        ['curl', '-sS', '-o', '/dev/null', '-w', '%{http_code}', '-u', auth,
         '-X', 'POST',
         '-H', 'Content-Type: application/json',
         '-d', json.dumps({'content': {'raw': text},
                           'comment': {'id': int(comment_id)}}),
         tasks_url],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        return (False, 'transport failure')
    code = (r.stdout or '').strip()
    if code.startswith('2'):
        return (True, code)
    return (False, f'HTTP {code}')


# ── Post AI disclaimer header once per PR (skip if already present) ───────────
DISCLAIMER_MARKER = '<!-- ai-review:disclaimer -->'
HEADER = (
    "🤖 **AI Code Review — please verify before acting**\n\n"
    "This review was generated by an AI assistant. It can miss context, misread intent, "
    "or be flat-out wrong. Treat each comment as a suggestion to verify, not a verdict. "
    "If something looks off, trust your judgment over mine.\n\n"
    f"{DISCLAIMER_MARKER}"
)

DISCLAIMER_SIGNATURE = '🤖 **AI Code Review'  # matches the header text across versions

def disclaimer_already_posted() -> bool:
    url = f'{comments_url}?pagelen=50&fields=values.content.raw,values.inline,next'
    while url:
        r = subprocess.run(['curl', '-sSf', '-u', auth, url],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return False  # be safe: post the header rather than silently skip
        try:
            page = json.loads(r.stdout)
        except json.JSONDecodeError:
            return False
        for c in page.get('values', []):
            if c.get('inline'):
                continue
            raw = (c.get('content', {}) or {}).get('raw', '') or ''
            if DISCLAIMER_MARKER in raw or DISCLAIMER_SIGNATURE in raw:
                return True
        url = page.get('next')
    return False

if disclaimer_already_posted():
    print('  ↷ disclaimer already on this PR — skipped header post')
else:
    header_result = post_comment({'content': {'raw': HEADER}})
    if header_result.returncode == 0:
        print('  ✓ posted AI disclaimer header')
    else:
        print(f'  ✗ failed to post header: {header_result.stderr.strip()}', file=sys.stderr)

posted = 0
failed = 0
tasks_created = 0
tasks_failed  = 0

for finding in findings:
    body      = finding['body']
    is_inline = 'path' in finding and 'line' in finding
    payload   = {'content': {'raw': body}}

    if is_inline:
        payload['inline'] = {'path': finding['path'], 'to': int(finding['line'])}
        location = f"{finding['path']}:{finding['line']}"
    else:
        location = 'PR level'

    result = post_comment(payload)

    if result.returncode == 0:
        try:
            comment_id = json.loads(result.stdout).get('id', '?')
        except Exception:
            comment_id = '?'

        if comment_id != '?' and is_inline:
            # For inline comments, append the tracking marker (used by
            # check_resolved.py) and, when the finding carries dimension/
            # severity, a telemetry meta marker.
            final_body = body + f'\n\n<!-- ai-review:open:{head_sha} -->'
            meta = {}
            if 'dim' in finding:
                meta['dim'] = finding['dim']
            if 'severity' in finding:
                meta['severity'] = finding['severity']
            if meta:
                meta_json = json.dumps(meta, separators=(',', ':'))
                final_body += f'\n<!-- ai-review:meta {meta_json} -->'
            update_comment(comment_id, final_body)

        print(f'  ✓ comment #{comment_id} → {location}')
        posted += 1

        # 🔴 Critical → also create a blocking PR task. The severity field is the
        # source of truth; fall back to the emoji in the body for older callers
        # that omit it.
        severity = str(finding.get('severity', '')).lower()
        is_critical = severity == 'critical' or (not severity and '🔴' in body[:200])
        if is_critical and comment_id != '?':
            ok, detail = create_task(
                comment_id,
                f'🔴 Critical (AI review): resolve or dismiss — {location}',
            )
            if ok:
                tasks_created += 1
                print(f'    ✓ blocking task created for {location}')
            else:
                tasks_failed += 1
                print(f'    ↷ could not create blocking task for {location} ({detail}) '
                      '— the comment still posted', file=sys.stderr)
    else:
        print(f'  ✗ failed ({location}): {result.stderr.strip() or result.stdout.strip()}',
              file=sys.stderr)
        failed += 1

summary = f'\nPosted {posted} comment(s), {failed} failed.'
if tasks_created or tasks_failed:
    summary += f' Blocking tasks: {tasks_created} created'
    if tasks_failed:
        summary += f', {tasks_failed} could not be created'
    summary += '.'
print(summary)
print(f'https://bitbucket.org/{workspace}/{repo_slug}/pull-requests/{pr_id}')
sys.exit(1 if failed > 0 else 0)
PYEOF
