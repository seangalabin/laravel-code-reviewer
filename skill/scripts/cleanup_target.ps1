# cleanup_target.ps1 — remove the git worktree created by setup_target.ps1.
# Windows port of cleanup_target.sh.
#
# Usage:
#   pwsh cleanup_target.ps1 <worktree-path>

$WorkTree = if ($args.Count -ge 1) { $args[0] } else { "" }

if ([string]::IsNullOrEmpty($WorkTree)) {
    [Console]::Error.WriteLine("Usage: cleanup_target.ps1 <worktree-path>")
    exit 1
}

if (-not (Test-Path -Path $WorkTree -PathType Container)) {
    [Console]::Error.WriteLine("  Worktree not found at '$WorkTree' — already removed.")
    exit 0
}

git worktree remove --force $WorkTree 2>$null
if ($LASTEXITCODE -ne 0) {
    Remove-Item -Path $WorkTree -Recurse -Force -ErrorAction SilentlyContinue
}

[Console]::Error.WriteLine("  Worktree removed: $WorkTree")
