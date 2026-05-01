param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Message
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$FrontendDir = Join-Path $RepoRoot "frontend"
$PackageJsonPath = Join-Path $FrontendDir "package.json"
$PackageLockPath = Join-Path $FrontendDir "package-lock.json"
$BackendVersionPath = Join-Path $RepoRoot "backend\app\version.py"

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)] [string[]]$Args)
    & git -C $RepoRoot @Args
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Args -join ' ') failed."
    }
}

if (-not (Test-Path (Join-Path $RepoRoot ".git"))) {
    throw "This script must be run inside a Git checkout."
}

foreach ($Path in @($PackageJsonPath, $PackageLockPath, $BackendVersionPath)) {
    if (-not (Test-Path $Path)) {
        throw "Required version file not found: $Path"
    }
}

$VersionFiles = @(
    "frontend/package.json",
    "frontend/package-lock.json",
    "backend/app/version.py"
)

$ForbiddenPatterns = @(
    "^results/",
    "^frontend/dist/",
    "^frontend/node_modules/",
    "(^|/)__pycache__/",
    "\.pyc$",
    "\.log$",
    "\.err\.log$"
)

$StagedFiles = @(Invoke-Git diff --cached --name-only | ForEach-Object { $_ -replace "\\", "/" })
$StagedFeatureFiles = @($StagedFiles | Where-Object { $VersionFiles -notcontains $_ })
if ($StagedFeatureFiles.Count -eq 0) {
    throw "No staged feature changes found. Stage the files you want to commit first, then run this script."
}

$ForbiddenStagedFiles = @(
    foreach ($File in $StagedFiles) {
        foreach ($Pattern in $ForbiddenPatterns) {
            if ($File -match $Pattern) {
                $File
                break
            }
        }
    }
)
if ($ForbiddenStagedFiles.Count -gt 0) {
    throw "Refusing to commit generated or log files: $($ForbiddenStagedFiles -join ', ')"
}

$PackageJson = Get-Content -Raw -Path $PackageJsonPath
$PackageInfo = $PackageJson | ConvertFrom-Json
$CurrentVersion = [string]$PackageInfo.version
if ($CurrentVersion -notmatch "^(\d+)\.(\d+)\.(\d+)$") {
    throw "frontend/package.json version must use major.minor.patch format. Current value: $CurrentVersion"
}

$Major = [int]$Matches[1]
$Minor = [int]$Matches[2]
$Patch = [int]$Matches[3] + 1
$NextVersion = "$Major.$Minor.$Patch"

$PackageVersionPattern = '(?m)^(\s*"version"\s*:\s*")[^"]+(")'
$PackageVersionReplacement = [System.Text.RegularExpressions.MatchEvaluator]{
    param($Match)
    $Match.Groups[1].Value + $NextVersion + $Match.Groups[2].Value
}
$UpdatedPackageJson = [regex]::Replace($PackageJson, $PackageVersionPattern, $PackageVersionReplacement, 1)
if ($UpdatedPackageJson -eq $PackageJson) {
    throw "Could not update version in frontend/package.json."
}
[System.IO.File]::WriteAllText($PackageJsonPath, $UpdatedPackageJson, [System.Text.UTF8Encoding]::new($false))

$PackageLock = Get-Content -Raw -Path $PackageLockPath
$PackageLockInfo = $PackageLock | ConvertFrom-Json -AsHashTable
$PackageLockInfo["version"] = $NextVersion
if (-not $PackageLockInfo.ContainsKey("packages") -or -not $PackageLockInfo["packages"].ContainsKey("")) {
    throw "Could not find root package entry in frontend/package-lock.json."
}
$PackageLockInfo["packages"][""]["version"] = $NextVersion
$UpdatedPackageLock = $PackageLockInfo | ConvertTo-Json -Depth 100
[System.IO.File]::WriteAllText($PackageLockPath, $UpdatedPackageLock, [System.Text.UTF8Encoding]::new($false))

$BackendVersion = Get-Content -Raw -Path $BackendVersionPath
$VersionPattern = "(?m)^APP_VERSION\s*=\s*['""][^'""]+['""]"
$UpdatedBackendVersion = [regex]::Replace($BackendVersion, $VersionPattern, "APP_VERSION = `"$NextVersion`"", 1)
if ($UpdatedBackendVersion -eq $BackendVersion) {
    throw "Could not find APP_VERSION in backend/app/version.py."
}

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($BackendVersionPath, $UpdatedBackendVersion, $Utf8NoBom)

Invoke-Git add -- frontend/package.json frontend/package-lock.json backend/app/version.py
Invoke-Git commit -m $Message

Write-Host "Committed $Message with version v$NextVersion"
