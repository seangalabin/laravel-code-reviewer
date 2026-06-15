# save_reviewed_sha.ps1 - record the current HEAD SHA as a checkpoint on the PR.
# Windows port of save_reviewed_sha.sh.
#
# Posts (or updates) a hidden top-level PR comment containing:
#   <!-- ai-review:checkpoint:{sha} -->
#
# Required env vars: BITBUCKET_EMAIL, BITBUCKET_API_TOKEN
# Falls back silently if creds are missing or no open PR exists.

if ([string]::IsNullOrEmpty($env:BITBUCKET_EMAIL) -or [string]::IsNullOrEmpty($env:BITBUCKET_API_TOKEN)) {
    [Console]::Error.WriteLine("  Skipping checkpoint - BITBUCKET_EMAIL / BITBUCKET_API_TOKEN not set.")
    exit 0
}

$RemoteUrl = (git remote get-url origin 2>$null)
if ($LASTEXITCODE -ne 0) { exit 0 }
$RemoteUrl = "$RemoteUrl".Trim()
if ($RemoteUrl -notmatch 'bitbucket\.org[:/]([^/]+)/([^/]+?)(\.git)?$') {
    [Console]::Error.WriteLine("  Skipping checkpoint - not a Bitbucket remote.")
    exit 0
}

$Workspace = $Matches[1]
$RepoSlug  = $Matches[2]
$HeadSha   = "$(git rev-parse HEAD)".Trim()
$ShortSha  = "$(git rev-parse --short HEAD)".Trim()

$Branch = ""
$TargetPrId = ""
if (Test-Path ".ai-review/target.json") {
    try {
        $t = Get-Content ".ai-review/target.json" -Raw | ConvertFrom-Json
        $Branch = "$($t.branch)"
        if ($t.pr_id) { $TargetPrId = "$($t.pr_id)" }
    } catch { exit 0 }
} else {
    $Branch = "$(git rev-parse --abbrev-ref HEAD 2>$null)".Trim()
}

$ApiBase = "https://api.bitbucket.org/2.0/repositories/$Workspace/$RepoSlug"
$Auth    = "$($env:BITBUCKET_EMAIL):$($env:BITBUCKET_API_TOKEN)"

# Pass inputs via env (PowerShell can drop empty positional args); the Python
# logic below is identical to save_reviewed_sha.sh apart from this preamble.
$env:AI_REVIEW_API_BASE = $ApiBase
$env:AI_REVIEW_AUTH     = $Auth
$env:AI_REVIEW_BRANCH   = $Branch
$env:AI_REVIEW_HEAD_SHA = $HeadSha
$env:AI_REVIEW_SHORT_SHA = $ShortSha
$env:AI_REVIEW_PR_ID    = $TargetPrId

$py = @'
import json, sys, subprocess, urllib.parse, re, os

api_base     = os.environ['AI_REVIEW_API_BASE']
auth         = os.environ['AI_REVIEW_AUTH']
branch       = os.environ.get('AI_REVIEW_BRANCH', '')
head_sha     = os.environ['AI_REVIEW_HEAD_SHA']
short        = os.environ['AI_REVIEW_SHORT_SHA']
target_pr_id = os.environ.get('AI_REVIEW_PR_ID', '')


def curl(*args):
    return subprocess.run(['curl', '-sSf', '-u', auth, *args],
                          capture_output=True, text=True)


# Find open PR for branch (skip lookup when target.json provided the ID)
if target_pr_id:
    pr_id = int(target_pr_id)
else:
    q = urllib.parse.quote(f'source.branch.name="{branch}" AND state="OPEN"', safe='')
    r = curl(f'{api_base}/pullrequests?q={q}&fields=values.id')
    if r.returncode != 0:
        print(f'  Skipping checkpoint - Bitbucket API failed: {r.stderr.strip()}', file=sys.stderr)
        sys.exit(0)
    prs = json.loads(r.stdout).get('values', [])
    if not prs:
        print(f'  Skipping checkpoint - no open PR for branch "{branch}".', file=sys.stderr)
        sys.exit(0)
    pr_id = prs[0]['id']

comments_url = f'{api_base}/pullrequests/{pr_id}/comments'

body = (
    f'<!-- ai-review:checkpoint:{head_sha} -->\n\n'
    f'\U0001F516 _Code review checkpoint - last reviewed at `{short}`. '
    f'Used by `/code-reviewer --since-last-review` to skip already-reviewed commits._'
)

# Look for an existing checkpoint comment (top-level only)
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
    msg = f'  Checkpoint updated -> {short}' if r.returncode == 0 \
          else f'  Failed to update checkpoint: {r.stderr.strip()}'
else:
    r = curl('-X', 'POST', '-H', 'Content-Type: application/json',
             '-d', payload, comments_url)
    msg = f'  Checkpoint posted -> {short}' if r.returncode == 0 \
          else f'  Failed to post checkpoint: {r.stderr.strip()}'

print(msg, file=sys.stdout if r.returncode == 0 else sys.stderr)
'@

$py | python -
