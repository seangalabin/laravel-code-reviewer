# Run Pint against only the PHP files changed on the current branch.
# Usage: pwsh scripts/pint_changed.ps1 [-Fix]
# Default mode is check-only. Pass -Fix to auto-format and stage.
param([switch]$Fix)

$Base = if ($env:BASE_BRANCH) { $env:BASE_BRANCH } else { "develop" }
$RemoteBase = "origin/$Base"

git rev-parse --verify $RemoteBase 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "error: $RemoteBase not found. Try: git fetch origin $Base"
    exit 1
}

$branchChanged = @(git diff --name-only --diff-filter=AMR "${RemoteBase}...HEAD" -- '*.php' |
    Where-Object { $_ -and $_ -notmatch "^vendor/" -and $_ -notmatch "^storage/" })
$dirtyChanged = @(git diff --name-only --diff-filter=AMR -- '*.php' |
    Where-Object { $_ -and $_ -notmatch "^vendor/" -and $_ -notmatch "^storage/" })

$existing = @(($branchChanged + $dirtyChanged) |
    Select-Object -Unique |
    Where-Object { $_ -and (Test-Path $_) })

if ($existing.Count -eq 0) {
    Write-Host "No PHP changes vs $Base."
    exit 0
}

Write-Host "Checking $($existing.Count) changed PHP file(s)..."
if ($Fix) {
    php vendor/bin/pint @existing
    if ($LASTEXITCODE -eq 0) {
        git add @existing
        Write-Host "Staged $($existing.Count) formatted file(s)."
    }
} else {
    php vendor/bin/pint --test @existing
}
