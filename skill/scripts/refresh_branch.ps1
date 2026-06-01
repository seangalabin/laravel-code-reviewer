# refresh_branch.ps1 — fetch the current branch and base branch from origin,
# fast-forward the local branch if it cleanly lags the remote, and warn on
# divergence. Windows port of refresh_branch.sh.
#
# Skips silently when invoked inside a target-mode worktree.
# Exits 0 in all non-error paths so the caller can continue.

$Base = if ($env:BASE_BRANCH) { $env:BASE_BRANCH } else { "develop" }

# Target mode: .ai-review/target.json at the worktree root means the worktree
# was created from a freshly-fetched origin/<branch>. Nothing to do.
if (Test-Path ".ai-review/target.json") { exit 0 }

$Branch = "$(git rev-parse --abbrev-ref HEAD 2>$null)".Trim()
if ([string]::IsNullOrEmpty($Branch) -or $Branch -eq "HEAD") {
    # Detached HEAD — nothing to align.
    exit 0
}

[Console]::Error.WriteLine("  Refreshing origin/$Base and origin/$Branch...")
git fetch origin $Base $Branch 2>&1 | ForEach-Object { [Console]::Error.WriteLine("  $_") }
if ($LASTEXITCODE -ne 0) {
    [Console]::Error.WriteLine("  ⚠️  Couldn't fetch — reviewing against your local copy.")
    exit 0
}

git rev-parse --verify "origin/$Branch" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    # No remote branch yet (first push pending). Nothing to align.
    exit 0
}

$Behind = "$(git rev-list --count "HEAD..origin/$Branch" 2>$null)".Trim()
$Ahead  = "$(git rev-list --count "origin/$Branch..HEAD" 2>$null)".Trim()
if ([string]::IsNullOrEmpty($Behind)) { $Behind = "0" }
if ([string]::IsNullOrEmpty($Ahead))  { $Ahead  = "0" }
$Behind = [int]$Behind
$Ahead  = [int]$Ahead

if ($Behind -eq 0 -and $Ahead -eq 0) { exit 0 }

if ($Behind -gt 0 -and $Ahead -eq 0) {
    [Console]::Error.WriteLine("  Local branch is $Behind commit(s) behind origin/$Branch — fast-forwarding.")
    git merge --ff-only "origin/$Branch" 2>&1 | ForEach-Object { [Console]::Error.WriteLine("  $_") }
    exit 0
}

if ($Ahead -gt 0 -and $Behind -eq 0) {
    [Console]::Error.WriteLine("  Local branch has $Ahead unpushed commit(s). Reviewing local HEAD.")
    exit 0
}

[Console]::Error.WriteLine("  ⚠️  Local branch and origin/$Branch have diverged ($Ahead ahead, $Behind behind).")
[Console]::Error.WriteLine("     Reviewing local HEAD. Pull/rebase and re-run to review the remote view.")
exit 0
