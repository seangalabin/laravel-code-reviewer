# Run Pest only for tests that map to files changed on the current branch.
#
# Mapping rule: app/Foo/Bar.php -> tests/Feature/Foo/BarTest.php
# Test files changed directly are always included.
#
# Usage: pwsh scripts/pest_for_changed.ps1 [extra pest args...]
param([Parameter(ValueFromRemainingArguments=$true)][string[]]$PestArgs)

$Base = if ($env:AI_REVIEW_BASE_BRANCH) { $env:AI_REVIEW_BASE_BRANCH } elseif ($env:BASE_BRANCH) { $env:BASE_BRANCH } else { "develop" }
$RemoteBase = "origin/$Base"

git rev-parse --verify $RemoteBase 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "error: $RemoteBase not found. Try: git fetch origin $Base"
    exit 1
}

$branchChanged = @(git diff --name-only --diff-filter=AMR "${RemoteBase}...HEAD" -- '*.php' | Where-Object { $_ })
$dirtyChanged  = @(git diff --name-only --diff-filter=AMR -- '*.php' | Where-Object { $_ })

$changed = @(($branchChanged + $dirtyChanged) |
    Where-Object { $_ -and $_ -notmatch "^vendor/" -and $_ -notmatch "^storage/" } |
    Select-Object -Unique)

$testSet = @{}
foreach ($f in $changed) {
    if ($f -match "^tests/") {
        if (Test-Path $f) { $testSet[$f] = 1 }
        continue
    }
    if ($f -match "^app/") {
        $rel      = $f -replace "^app/", ""
        $dir      = (Split-Path $rel -Parent) -replace "\\", "/"
        $baseName = [System.IO.Path]::GetFileNameWithoutExtension($rel)
        $candidate = "tests/Feature/$dir/${baseName}Test.php"
        if (Test-Path $candidate) { $testSet[$candidate] = 1 }
    }
}

if ($testSet.Count -eq 0) {
    Write-Host "No matching Pest test files for the changed code."
    Write-Host "(For the full suite, run: php vendor/bin/pest --compact)"
    exit 0
}

Write-Host "Matched:"
$testSet.Keys | ForEach-Object { Write-Host "  $_" }
Write-Host ""
Write-Host "Running $($testSet.Count) test file(s)..."
php vendor/bin/pest --compact @PestArgs @($testSet.Keys)
