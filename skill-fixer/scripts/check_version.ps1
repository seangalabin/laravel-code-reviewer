# Checks the installed skill version against the latest on GitHub.
# Exits 0 if current or GitHub unreachable. Exits 1 if outdated.
$SkillDir = Split-Path -Parent $PSScriptRoot
$VersionFile = Join-Path $SkillDir "VERSION"
$LocalVersion = if (Test-Path $VersionFile) { (Get-Content $VersionFile -Raw).Trim() } else { $null }

$RemoteVersion = $null
try {
    $response = Invoke-WebRequest `
        -Uri "https://raw.githubusercontent.com/seangalabin/laravel-code-reviewer/master/skill-fixer/VERSION" `
        -TimeoutSec 5 `
        -UseBasicParsing `
        -ErrorAction Stop
    $RemoteVersion = $response.Content.Trim()
} catch {
    exit 0
}

if ([string]::IsNullOrEmpty($RemoteVersion)) { exit 0 }

if ($LocalVersion -ne $RemoteVersion) {
    $installed = if ($LocalVersion) { $LocalVersion } else { "unknown" }
    Write-Host ""
    Write-Host "⚠️  code-fixer is out of date (installed: $installed, latest: $RemoteVersion)."
    Write-Host "   Update before continuing:"
    Write-Host ""
    Write-Host "     npx github:seangalabin/laravel-code-reviewer --skill=fixer"
    Write-Host ""
    exit 1
}

exit 0
