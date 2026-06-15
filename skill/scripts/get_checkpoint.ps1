# get_checkpoint.ps1 - print the last-reviewed SHA from the PR's checkpoint
# comment, or nothing if no checkpoint exists. Windows port of get_checkpoint.sh.
#
# Exits silently with no output on any failure (no creds, no PR, API error)
# so the caller can fall back cleanly to a full diff against develop.
#
# Required env vars: BITBUCKET_EMAIL, BITBUCKET_API_TOKEN

if ([string]::IsNullOrEmpty($env:BITBUCKET_EMAIL) -or [string]::IsNullOrEmpty($env:BITBUCKET_API_TOKEN)) { exit 0 }

$RemoteUrl = (git remote get-url origin 2>$null)
if ($LASTEXITCODE -ne 0) { exit 0 }
$RemoteUrl = "$RemoteUrl".Trim()
if ($RemoteUrl -notmatch 'bitbucket\.org[:/]([^/]+)/([^/]+?)(\.git)?$') { exit 0 }

$Workspace = $Matches[1]
$RepoSlug  = $Matches[2]
$ApiBase   = "https://api.bitbucket.org/2.0/repositories/$Workspace/$RepoSlug"
$Auth      = "$($env:BITBUCKET_EMAIL):$($env:BITBUCKET_API_TOKEN)"

# Branch and optional pre-resolved PR ID (target.json wins if present)
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

# Pass inputs via env (PowerShell can drop empty positional args); the Python
# logic below is identical to get_checkpoint.sh apart from this preamble.
$env:AI_REVIEW_API_BASE = $ApiBase
$env:AI_REVIEW_AUTH     = $Auth
$env:AI_REVIEW_BRANCH   = $Branch
$env:AI_REVIEW_PR_ID    = $TargetPrId

$py = @'
import json, sys, subprocess, urllib.parse, re, os

api_base     = os.environ['AI_REVIEW_API_BASE']
auth         = os.environ['AI_REVIEW_AUTH']
branch       = os.environ.get('AI_REVIEW_BRANCH', '')
target_pr_id = os.environ.get('AI_REVIEW_PR_ID', '')


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
'@

$py | python - 2>$null
exit 0
