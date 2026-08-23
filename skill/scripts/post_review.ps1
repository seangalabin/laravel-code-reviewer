# post_review.ps1 -- posts code-review findings as inline comments on the
# Bitbucket PR for the current branch. Windows port of post_review.sh.
#
# Usage (preferred on Windows -- pass a UTF-8 findings file written by the editor):
#   pwsh post_review.ps1 .ai-review/findings.json
#
# Usage (fallback -- pipe a here-string on stdin):
#   @'
#   [ { "path": "app/Foo.php", "line": 42, "body": "...", "dim": "3b", "severity": "critical" } ]
#   '@ | pwsh post_review.ps1
#
# Required env vars:
#   BITBUCKET_EMAIL     -- your Bitbucket account email
#   BITBUCKET_API_TOKEN -- API token with "Pull requests: write" scope
#
# Encoding note: this script is pure ASCII on purpose. Prefer the file-path form:
# a findings file written by the editor is UTF-8 (no BOM), so it sidesteps the
# Windows console code page, the pipe encoding, AND PowerShell's BOM-less
# here-string decoding -- every boundary that can turn emoji / em-dashes into
# mojibake (e.g. "ðŸ”µ Suggestion â€”"). Findings (whether from the file arg or
# stdin) are read as explicit UTF-8. Glyphs that end up in posted comments are
# written as Python \u escapes below, so json.dumps emits them as ASCII \uXXXX
# regardless of the console or file encoding.

param(
    [Parameter(Position = 0)]
    [string]$FindingsPath = ""
)

# ---- Auth ----
if ([string]::IsNullOrEmpty($env:BITBUCKET_EMAIL) -or [string]::IsNullOrEmpty($env:BITBUCKET_API_TOKEN)) {
    [Console]::Error.WriteLine("ERROR: BITBUCKET_EMAIL and BITBUCKET_API_TOKEN must both be set.")
    [Console]::Error.WriteLine("       `$env:BITBUCKET_EMAIL='your@email.com'")
    [Console]::Error.WriteLine("       `$env:BITBUCKET_API_TOKEN='your_token'")
    exit 1
}

# ---- Repo info from git remote ----
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

# ---- Read findings JSON as explicit UTF-8 (never the console code page) ----
# Prefer the file-path argument (UTF-8, no BOM, written by the editor); fall
# back to stdin for the legacy here-string form.
$utf8 = New-Object System.Text.UTF8Encoding($false)
if (-not [string]::IsNullOrEmpty($FindingsPath)) {
    if (-not (Test-Path -LiteralPath $FindingsPath)) {
        [Console]::Error.WriteLine("ERROR: findings file not found: $FindingsPath")
        exit 1
    }
    $FindingsRaw = [System.IO.File]::ReadAllText($FindingsPath, $utf8)
} else {
    $stdin  = [Console]::OpenStandardInput()
    $reader = New-Object System.IO.StreamReader($stdin, $utf8)
    $FindingsRaw = $reader.ReadToEnd()
    $reader.Dispose()
}

# Write to a temp file as UTF-8 (no BOM) so the Python side reads it cleanly.
$FindingsFile = [System.IO.Path]::GetTempFileName()
[System.IO.File]::WriteAllText($FindingsFile, $FindingsRaw, $utf8)

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

# ---- Resolve branch and PR (target.json wins if present) ----
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
q = urllib.parse.quote(f'source.branch.name="{branch}" AND state="OPEN"', safe='')
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

# ---- Capture HEAD SHA for comment tracking ----
$HeadSha = "$(git rev-parse HEAD)".Trim()

# ---- Post each finding (body identical to post_review.sh; glyphs as \u escapes) ----
$pyPost = @'
import json, os, sys, subprocess

findings_file = sys.argv[1]
api_base      = sys.argv[2]
pr_id         = sys.argv[3]
auth          = sys.argv[4]
workspace     = sys.argv[5]
repo_slug     = sys.argv[6]
head_sha      = sys.argv[7]

with open(findings_file, encoding='utf-8') as f:
    findings = json.load(f)

# ── Severity gate ─────────────────────────────────────────────────────────────
# Enforced here, in the script, and not only in the prompt: a prompt instruction is
# a strong suggestion, a filter is a guarantee. The lens carries far more Suggestion
# Suggestion rules than Critical/Warning ones, and a review whose output is mostly style nits
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
        print(f'  [skip] AI_REVIEW_MIN_SEVERITY="{floor_name}" is not one of '
              'critical/warning/suggestion — ignoring the floor.', file=sys.stderr)
        floor = 1
        floor_name = 'suggestion'

    raw_cap = os.environ.get('AI_REVIEW_MAX_SUGGESTIONS', '3').strip()
    try:
        cap = max(0, int(raw_cap))
    except ValueError:
        print(f'  [skip] AI_REVIEW_MAX_SUGGESTIONS="{raw_cap}" is not an integer — '
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
        print(f'  [skip] {below_floor} finding(s) withheld: below the '
              f'AI_REVIEW_MIN_SEVERITY={floor_name} floor.')
    if over_cap:
        print(f'  [skip] {over_cap} suggestion(s) withheld: over the '
              f'AI_REVIEW_MAX_SUGGESTIONS={cap} cap.')
    if below_floor or over_cap:
        print(f'  -> posting {len(kept)} of {len(findings)} finding(s). '
              'Withheld findings are still listed in the run\'s coverage ledger.')
    return kept


findings = apply_severity_gate(findings)
if not findings:
    print('  [skip] Nothing left to post after the severity gate.')
    sys.exit(0)

# ── Dry run ───────────────────────────────────────────────────────────────────
# AI_REVIEW_DRY_RUN=1 makes every Bitbucket write a no-op: the findings file is
# still produced and the plan is printed, but nothing reaches the PR. Two users:
# the eval harness (which scores findings and must never touch a real PR), and a
# developer testing the skill against a live PR without spraying comments on it.
if os.environ.get('AI_REVIEW_DRY_RUN'):
    print('  [dry-run] DRY RUN — no comments, tasks, or checkpoints will be posted.')
    for f in findings:
        loc = (f"{f['path']}:{f['line']}"
               if 'path' in f and 'line' in f else 'PR level')
        sev = str(f.get('severity', '?')).lower()
        print(f'     would post [{sev}] {loc}'
              + ('  + blocking task' if sev == 'critical' else ''))
    print(f'  [dry-run] {len(findings)} finding(s) would post to PR #{pr_id}.')
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

    A Critical finding is supposed to block the merge, and a comment cannot do
    that -- only a PR task can, via the repo's "Check for unresolved tasks" merge
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


# Post AI disclaimer header once per PR (skip if already present)
DISCLAIMER_MARKER = '<!-- ai-review:disclaimer -->'
HEADER = (
    "\U0001F916 **AI Code Review \u2014 please verify before acting**\n\n"
    "This review was generated by an AI assistant. It can miss context, misread intent, "
    "or be flat-out wrong. Treat each comment as a suggestion to verify, not a verdict. "
    "If something looks off, trust your judgment over mine.\n\n"
    f"{DISCLAIMER_MARKER}"
)

DISCLAIMER_SIGNATURE = '\U0001F916 **AI Code Review'  # matches the header text across versions

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
    print('  - disclaimer already on this PR (skipped header post)')
else:
    header_result = post_comment({'content': {'raw': HEADER}})
    if header_result.returncode == 0:
        print('  [ok] posted AI disclaimer header')
    else:
        print(f'  [x] failed to post header: {header_result.stderr.strip()}', file=sys.stderr)

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

        print(f'  [ok] comment #{comment_id} -> {location}')
        posted += 1

        # Critical -> also create a blocking PR task. The severity field is the
        # source of truth; fall back to the emoji in the body for older callers
        # that omit it.
        severity = str(finding.get('severity', '')).lower()
        is_critical = severity == 'critical' or (not severity and '\U0001F534' in body[:200])
        if is_critical and comment_id != '?':
            ok, detail = create_task(
                comment_id,
                f'Critical (AI review): resolve or dismiss -- {location}',
            )
            if ok:
                tasks_created += 1
                print(f'    [ok] blocking task created for {location}')
            else:
                tasks_failed += 1
                print(f'    [skip] could not create blocking task for {location} ({detail}) '
                      '-- the comment still posted', file=sys.stderr)
    else:
        print(f'  [x] failed ({location}): {result.stderr.strip() or result.stdout.strip()}',
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
'@

$pyPost | python - $FindingsFile $ApiBase $PrId $Auth $Workspace $RepoSlug $HeadSha
$code = $LASTEXITCODE
Remove-Item $FindingsFile -Force -ErrorAction SilentlyContinue
exit $code
