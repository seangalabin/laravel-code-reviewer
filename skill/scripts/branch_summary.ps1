# One-glance summary of what the current branch changed vs the base.
# Usage: pwsh scripts/branch_summary.ps1 [base]
# Default base: develop
#
# If [base] looks like a commit SHA (7-40 hex chars) it is used directly
# (the --since-last-review checkpoint case); otherwise it is treated as a
# branch name and resolved via origin/.
param([string]$Base = $(if ($env:AI_REVIEW_BASE_BRANCH) { $env:AI_REVIEW_BASE_BRANCH } elseif ($env:BASE_BRANCH) { $env:BASE_BRANCH } else { "develop" }))

if ($Base -match '^[0-9a-f]{7,40}$') {
    $RemoteBase = $Base
} else {
    $RemoteBase = "origin/$Base"
    git fetch origin $Base 2>$null
}

git rev-parse --verify $RemoteBase 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "error: $RemoteBase not found."
    exit 1
}

$HeadBranch = (git branch --show-current).Trim()
$CommitsAhead = (git rev-list --count "${RemoteBase}..HEAD").Trim()
$ChangedFilesList = @(git diff --name-only "${RemoteBase}...HEAD" | Where-Object { $_ })
$FilesChanged = $ChangedFilesList.Count
$Untracked = @(git ls-files --others --exclude-standard | Where-Object { $_ }).Count

Write-Host "Base:           $RemoteBase"
Write-Host "Branch:         $HeadBranch"
Write-Host "Commits ahead:  $CommitsAhead"
Write-Host "Files changed:  $FilesChanged"
Write-Host "Untracked:      $Untracked"
Write-Host ""
Write-Host "Changed files by type:"

$typeCounts = @{}
foreach ($f in $ChangedFilesList) {
    $type = if     ($f -like "*.blade.php") { "Blade" }
            elseif ($f -like "*.php")       { "PHP" }
            elseif ($f -like "*.vue")       { "Vue" }
            elseif ($f -like "*.js" -or $f -like "*.ts") { "JS/TS" }
            elseif ($f -like "*.yaml" -or $f -like "*.yml") { "YAML" }
            elseif ($f -like "*.json")      { "JSON" }
            elseif ($f -like "*.css" -or $f -like "*.scss") { "CSS" }
            else                            { "Other" }
    $typeCounts[$type] = if ($typeCounts.ContainsKey($type)) { $typeCounts[$type] + 1 } else { 1 }
}
foreach ($key in ($typeCounts.Keys | Sort-Object)) {
    Write-Host ("  {0,-8} {1}" -f "$($key):", $typeCounts[$key])
}

Write-Host ""
Write-Host "Recent commits:"
git log --oneline "${RemoteBase}..HEAD"
