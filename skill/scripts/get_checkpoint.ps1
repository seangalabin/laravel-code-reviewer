# get_checkpoint.ps1 - print the last-reviewed SHA from the PR's checkpoint
# comment, or nothing if no checkpoint exists. Windows port of get_checkpoint.sh.
#
# Prints nothing (caller falls back to a full diff against the base branch,
# $env:AI_REVIEW_BASE_BRANCH or develop) when there is
# no checkpoint, no creds, or no PR. A persistent Bitbucket API error (after
# retries) is reported distinctly on stderr rather than passed off as "no
# checkpoint", so a transient API blip doesn't read as if the saved checkpoint
# vanished. Transient failures (network, 429, 5xx) are retried with backoff.
#
# Required env vars: BITBUCKET_EMAIL, BITBUCKET_API_TOKEN

$BaseLabel = if ($env:AI_REVIEW_BASE_BRANCH) { $env:AI_REVIEW_BASE_BRANCH } else { "develop" }

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
import json, sys, subprocess, urllib.parse, re, os, time

api_base     = os.environ['AI_REVIEW_API_BASE']
auth         = os.environ['AI_REVIEW_AUTH']
branch       = os.environ.get('AI_REVIEW_BRANCH', '')
target_pr_id = os.environ.get('AI_REVIEW_PR_ID', '')


def curl_json(url, retries=3):
    """Fetch url -> (ok, data). Retries transient failures (curl transport error,
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
        sys.exit(3)
    prs = data.get('values', [])
    if not prs:
        sys.exit(0)
    pr_id = prs[0]['id']

url = (f'{api_base}/pullrequests/{pr_id}/comments'
       '?pagelen=100&fields=values.id,values.inline,values.content.raw,next')
while url:
    ok, page = curl_json(url)
    if not ok:
        sys.exit(3)
    for c in page.get('values', []):
        if c.get('inline'):
            continue
        raw = (c.get('content', {}) or {}).get('raw', '') or ''
        m = re.search(r'<!--\s*ai-review:checkpoint:([a-f0-9]+)\s*-->', raw)
        if m:
            print(m.group(1))
            sys.exit(0)
    url = page.get('next')
sys.exit(0)
'@

$CheckpointSha = ($py | python - 2>$null)
$PyStatus = $LASTEXITCODE
$CheckpointSha = "$CheckpointSha".Trim()

if ($PyStatus -eq 3) {
    [Console]::Error.WriteLine("  WARNING: Couldn't read the checkpoint - Bitbucket API error after retries.")
    [Console]::Error.WriteLine("      Running a full review against $BaseLabel. Your saved checkpoint likely still")
    [Console]::Error.WriteLine("      exists; the next run should pick it up once the API is reachable.")
} elseif (-not [string]::IsNullOrEmpty($CheckpointSha)) {
    $short = if ($CheckpointSha.Length -ge 7) { $CheckpointSha.Substring(0, 7) } else { $CheckpointSha }
    [Console]::Error.WriteLine("  Found checkpoint at $short - incremental review.")
    Write-Output $CheckpointSha
} else {
    [Console]::Error.WriteLine("  No checkpoint comment on PR yet - full review against $BaseLabel.")
}
exit 0
