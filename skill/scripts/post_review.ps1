# post_review.ps1 — posts code-review findings as inline comments on the
# Bitbucket PR for the current branch. Windows port of post_review.sh.
#
# Usage (PowerShell here-string piped on stdin):
#   @'
#   [ { "path": "app/Foo.php", "line": 42, "body": "...", "dim": "3b", "severity": "critical" } ]
#   '@ | pwsh post_review.ps1
#
# Required env vars:
#   BITBUCKET_EMAIL     — your Bitbucket account email
#   BITBUCKET_API_TOKEN — API token with "Pull requests: write" scope

# ── Auth ──────────────────────────────────────────────────────────────────────
if ([string]::IsNullOrEmpty($env:BITBUCKET_EMAIL) -or [string]::IsNullOrEmpty($env:BITBUCKET_API_TOKEN)) {
    [Console]::Error.WriteLine("ERROR: BITBUCKET_EMAIL and BITBUCKET_API_TOKEN must both be set.")
    [Console]::Error.WriteLine("       `$env:BITBUCKET_EMAIL='your@email.com'")
    [Console]::Error.WriteLine("       `$env:BITBUCKET_API_TOKEN='your_token'")
    exit 1
}

# ── Repo info from git remote ─────────────────────────────────────────────────
$RemoteUrl = (git remote get-url origin 2>$null)
if ($LASTEXITCODE -ne 0) {
    [Console]::Error.WriteLine("ERROR: no git remote 'origin' found.")
    exit 1
}
$RemoteUrl = "$RemoteUrl".Trim()
if ($RemoteUrl -notmatch 'bitbucket\.org[:/]([^/]+)/([^/]+?)(\.git)?$') {
    [Console]::Error.WriteLine("ERROR: remote URL is not a recognised Bitbucket URL: $RemoteUrl")
    exit 1
}
$Workspace = $Matches[1]
$RepoSlug  = $Matches[2]
$ApiBase   = "https://api.bitbucket.org/2.0/repositories/$Workspace/$RepoSlug"
$Auth      = "$($env:BITBUCKET_EMAIL):$($env:BITBUCKET_API_TOKEN)"

# ── Read findings JSON from stdin → temp file (UTF-8, no BOM) ─────────────────
$FindingsRaw = [Console]::In.ReadToEnd()
$FindingsFile = [System.IO.Path]::GetTempFileName()
[System.IO.File]::WriteAllText($FindingsFile, $FindingsRaw, (New-Object System.Text.UTF8Encoding($false)))

$pyValidate = @'
import json, sys
with open(sys.argv[1], encoding='utf-8') as f:
    data = json.load(f)
if not isinstance(data, list):
    print('ERROR: input must be a JSON array', file=sys.stderr)
    sys.exit(1)
'@
$pyValidate | python - $FindingsFile
if ($LASTEXITCODE -ne 0) {
    Remove-Item $FindingsFile -Force -ErrorAction SilentlyContinue
    exit 1
}

# ── Resolve branch and PR (target.json wins if present) ───────────────────────
$Branch = ""
$PrId = ""
if (Test-Path ".ai-review/target.json") {
    try {
        $t = Get-Content ".ai-review/target.json" -Raw | ConvertFrom-Json
        $Branch = "$($t.branch)"
        if ($t.pr_id) { $PrId = "$($t.pr_id)" }
    } catch { }
}
if ([string]::IsNullOrEmpty($Branch)) {
    $Branch = "$(git rev-parse --abbrev-ref HEAD)".Trim()
}

$PrTitle = ""
if ([string]::IsNullOrEmpty($PrId)) {
    $env:AI_REVIEW_WS = $Workspace; $env:AI_REVIEW_REPO = $RepoSlug
    $env:AI_REVIEW_BRANCH = $Branch; $env:AI_REVIEW_AUTH = $Auth
    $pyPr = @'
import sys, json, subprocess, urllib.parse, os
ws     = os.environ['AI_REVIEW_WS']
repo   = os.environ['AI_REVIEW_REPO']
branch = os.environ['AI_REVIEW_BRANCH']
auth   = os.environ['AI_REVIEW_AUTH']
q = urllib.parse.quote(f'source.branch.name="{branch}" AND state="OPEN"')
r = subprocess.run(
    ['curl', '-sSf', '-u', auth,
     f'https://api.bitbucket.org/2.0/repositories/{ws}/{repo}'
     f'/pullrequests?q={q}&fields=values.id,values.title'],
    capture_output=True, text=True,
)
if r.returncode != 0:
    print('ERROR\t' + (r.stderr.strip() or 'request failed'), file=sys.stderr)
    sys.exit(1)
prs = json.loads(r.stdout).get('values', [])
if prs:
    print(str(prs[0]['id']) + '\t' + (prs[0].get('title') or ''))
'@
    $resolved = ($pyPr | python -)
    if ($LASTEXITCODE -ne 0) {
        [Console]::Error.WriteLine("ERROR: Bitbucket API request failed. Check your credentials and network access.")
        Remove-Item $FindingsFile -Force -ErrorAction SilentlyContinue
        exit 1
    }
    if ($resolved) {
        $parts = "$resolved".Split("`t")
        $PrId = $parts[0].Trim()
        if ($parts.Count -gt 1) { $PrTitle = $parts[1] }
    }
}

if ([string]::IsNullOrEmpty($PrId)) {
    [Console]::Error.WriteLine("ERROR: no open PR found for branch '$Branch' in $Workspace/$RepoSlug.")
    [Console]::Error.WriteLine("       Push the branch and open a PR first.")
    Remove-Item $FindingsFile -Force -ErrorAction SilentlyContinue
    exit 1
}

if ($PrTitle) { Write-Host "Found PR #${PrId}: $PrTitle" } else { Write-Host "Found PR #$PrId" }
Write-Host ""

# ── Capture HEAD SHA for comment tracking ─────────────────────────────────────
$HeadSha = "$(git rev-parse HEAD)".Trim()

# ── Post each finding (body identical to post_review.sh) ──────────────────────
$pyPost = @'
import json, sys, subprocess

findings_file = sys.argv[1]
api_base      = sys.argv[2]
pr_id         = sys.argv[3]
auth          = sys.argv[4]
workspace     = sys.argv[5]
repo_slug     = sys.argv[6]
head_sha      = sys.argv[7]

with open(findings_file, encoding='utf-8') as f:
    findings = json.load(f)

comments_url = f'{api_base}/pullrequests/{pr_id}/comments'

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

# Post AI disclaimer header once per PR (skip if already present)
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

        if comment_id != '?':
            final_body = body.replace('{COMMENT_ID}', str(comment_id))
            if is_inline:
                final_body += f'\n\n<!-- ai-review:open:{head_sha} -->'
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
    else:
        print(f'  ✗ failed ({location}): {result.stderr.strip() or result.stdout.strip()}',
              file=sys.stderr)
        failed += 1

print(f'\nPosted {posted} comment(s), {failed} failed.')
print(f'https://bitbucket.org/{workspace}/{repo_slug}/pull-requests/{pr_id}')
sys.exit(1 if failed > 0 else 0)
'@

$pyPost | python - $FindingsFile $ApiBase $PrId $Auth $Workspace $RepoSlug $HeadSha
$code = $LASTEXITCODE
Remove-Item $FindingsFile -Force -ErrorAction SilentlyContinue
exit $code
