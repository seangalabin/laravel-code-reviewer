# setup_target.ps1 - create a git worktree for reviewing a branch without checkout.
# Windows port of setup_target.sh.
#
# Usage:
#   pwsh setup_target.ps1 --branch=<name>
#   pwsh setup_target.ps1 --pr=<N>
#
# Prints the worktree path to stdout (all status messages go to stderr).
# Writes .ai-review/target.json inside the worktree.
#
# Required env vars when using --pr: BITBUCKET_EMAIL, BITBUCKET_API_TOKEN

$Branch = ""
$PrId = ""
foreach ($a in $args) {
    if     ($a -like "--branch=*") { $Branch = $a.Substring(9) }
    elseif ($a -like "--pr=*")     { $PrId   = $a.Substring(5) }
}

if ([string]::IsNullOrEmpty($Branch) -and [string]::IsNullOrEmpty($PrId)) {
    [Console]::Error.WriteLine("ERROR: pass --branch=<name> or --pr=<N>")
    exit 1
}

$RemoteUrl = (git remote get-url origin 2>$null)
if ($LASTEXITCODE -ne 0) {
    [Console]::Error.WriteLine("ERROR: no git remote 'origin' found.")
    exit 1
}
$RemoteUrl = "$RemoteUrl".Trim()

$IsBitbucket = $false; $Workspace = ""; $RepoSlug = ""
if ($RemoteUrl -match 'bitbucket\.org[:/]([^/]+)/([^/]+?)(\.git)?$') {
    $Workspace = $Matches[1]; $RepoSlug = $Matches[2]; $IsBitbucket = $true
}

$Auth = "$($env:BITBUCKET_EMAIL):$($env:BITBUCKET_API_TOKEN)"

# Resolve branch from PR number
if (-not [string]::IsNullOrEmpty($PrId) -and [string]::IsNullOrEmpty($Branch)) {
    if ([string]::IsNullOrEmpty($env:BITBUCKET_EMAIL) -or [string]::IsNullOrEmpty($env:BITBUCKET_API_TOKEN)) {
        [Console]::Error.WriteLine("ERROR: --pr requires BITBUCKET_EMAIL and BITBUCKET_API_TOKEN.")
        exit 1
    }
    if (-not $IsBitbucket) {
        [Console]::Error.WriteLine("ERROR: --pr requires a Bitbucket remote URL.")
        exit 1
    }
    $env:AI_REVIEW_WS = $Workspace; $env:AI_REVIEW_REPO = $RepoSlug
    $env:AI_REVIEW_PR_ID = $PrId;    $env:AI_REVIEW_AUTH = $Auth
    $py = @'
import sys, json, subprocess, os
workspace = os.environ['AI_REVIEW_WS']
repo      = os.environ['AI_REVIEW_REPO']
pr_id     = os.environ['AI_REVIEW_PR_ID']
auth      = os.environ['AI_REVIEW_AUTH']
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
'@
    $Branch = ($py | python -)
    if ($LASTEXITCODE -ne 0) { exit 1 }
    $Branch = "$Branch".Trim()
}

# Guard against protected branches
if ($Branch -match '^(main|master|develop)$') {
    [Console]::Error.WriteLine("ERROR: Refusing to review protected branch '$Branch'.")
    exit 1
}

# Require Bitbucket creds to find the PR for a branch.
# Without a token we cannot look the PR up; fail loudly instead of silently
# proceeding with pr_id=null, keeping --branch symmetric with --pr above.
if ([string]::IsNullOrEmpty($PrId) -and $IsBitbucket -and `
    ([string]::IsNullOrEmpty($env:BITBUCKET_EMAIL) -or [string]::IsNullOrEmpty($env:BITBUCKET_API_TOKEN))) {
    [Console]::Error.WriteLine("ERROR: --branch needs Bitbucket API credentials to find the PR for '$Branch'.")
    [Console]::Error.WriteLine("       Set BITBUCKET_EMAIL and BITBUCKET_API_TOKEN, then re-run.")
    [Console]::Error.WriteLine('       In Claude Code, add them to .claude/settings.local.json under "env"')
    [Console]::Error.WriteLine("       (hot-reloads, no restart needed):")
    [Console]::Error.WriteLine('         { "env": { "BITBUCKET_EMAIL": "you@example.com", "BITBUCKET_API_TOKEN": "<token>" } }')
    exit 1
}

# Resolve PR ID from branch name when only --branch was given
if ([string]::IsNullOrEmpty($PrId) -and $IsBitbucket) {
    $env:AI_REVIEW_WS = $Workspace; $env:AI_REVIEW_REPO = $RepoSlug
    $env:AI_REVIEW_BRANCH = $Branch; $env:AI_REVIEW_AUTH = $Auth
    $py = @'
import sys, json, subprocess, urllib.parse, os
workspace = os.environ['AI_REVIEW_WS']
repo      = os.environ['AI_REVIEW_REPO']
branch    = os.environ['AI_REVIEW_BRANCH']
auth      = os.environ['AI_REVIEW_AUTH']
# Distinguish "no PR" (HTTP 200, empty) from a rejected token (401/403) or an
# unreachable API, so the review's final message reflects the real cause.
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
    print("         This is NOT 'no PR' - the review will run, but findings can't be posted.", file=sys.stderr)
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
'@
    $PrId = ($py | python -)
    $PrId = "$PrId".Trim()
}

# Fetch the branch and create the worktree
[Console]::Error.WriteLine("  Fetching origin/$Branch...")
git fetch origin $Branch 2>&1 | ForEach-Object { [Console]::Error.WriteLine("  $_") }
if ($LASTEXITCODE -ne 0) {
    [Console]::Error.WriteLine("ERROR: could not fetch 'origin/$Branch'. Does the branch exist on the remote?")
    exit 1
}

$rand = [Guid]::NewGuid().ToString('N').Substring(0, 6)
$WorkTree = Join-Path ([System.IO.Path]::GetTempPath()) "ai-review-$rand"
[Console]::Error.WriteLine("  Creating worktree at $WorkTree...")
git worktree add --detach $WorkTree "origin/$Branch" 2>&1 | ForEach-Object { [Console]::Error.WriteLine("  $_") }
if ($LASTEXITCODE -ne 0) {
    [Console]::Error.WriteLine("ERROR: git worktree add failed.")
    exit 1
}

# Write target.json inside the worktree
$env:AI_REVIEW_BRANCH = $Branch
$env:AI_REVIEW_PR_ID = $PrId
$env:AI_REVIEW_WORKTREE = $WorkTree
$py = @'
import os, json
branch    = os.environ['AI_REVIEW_BRANCH']
pr_id_str = os.environ.get('AI_REVIEW_PR_ID', '')
worktree  = os.environ['AI_REVIEW_WORKTREE']
os.makedirs(os.path.join(worktree, '.ai-review'), exist_ok=True)
data = {
    'branch':        branch,
    'pr_id':         int(pr_id_str) if pr_id_str else None,
    'worktree_path': worktree,
}
with open(os.path.join(worktree, '.ai-review', 'target.json'), 'w') as f:
    json.dump(data, f, indent=2)
'@
$py | python -

$prNote = if ($PrId) { ", PR #$PrId" } else { "" }
[Console]::Error.WriteLine("  Ready - branch: $Branch$prNote")
Write-Output $WorkTree
