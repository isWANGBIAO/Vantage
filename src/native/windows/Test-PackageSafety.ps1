# Runs on PowerShell without Pester, dotnet, models or user data.
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'PackageSafety.psm1') -Force
$temp = Join-Path ([IO.Path]::GetTempPath()) ('vantage-package-safety-' + [Guid]::NewGuid().ToString('N'))
$repo = Join-Path $temp 'Vantage'
$runtime = Join-Path $repo 'build/backend-runtime/stage/VantageBackend'
$data = Join-Path $temp 'user-data/Vantage'
foreach ($path in @($repo, $runtime, $data)) { New-Item -ItemType Directory -Path $path -Force | Out-Null }
$checks = 0
function Assert-Rejected([string]$Output, [string]$Label) {
    $rejected = $false
    try { Assert-VantagePackageDestination -OutputDirectory $Output -RepositoryRoot $repo -BackendRuntime $runtime -ProtectedDataDirectories @($data) -ArchiveName 'Vantage-Windows-x64.zip' | Out-Null }
    catch { $rejected = $true }
    if (-not $rejected) { throw "Expected rejection: $Label" }
    $script:checks++
}
try {
    $safe = Join-Path $repo 'build/native/windows'
    $result = Assert-VantagePackageDestination -OutputDirectory $safe -RepositoryRoot $repo -BackendRuntime $runtime -ProtectedDataDirectories @($data) -ArchiveName 'Vantage-Windows-x64.zip'
    if ($result.TargetDirectory -ne (Join-Path $safe 'Vantage')) { throw 'Unexpected safe target.' }; $checks++
    Assert-Rejected $temp 'repository itself'
    Assert-Rejected (Join-Path $temp 'user-data') 'user data itself'
    Assert-Rejected (Join-Path $data 'packages') 'nested inside data'
    Assert-Rejected (Join-Path $runtime 'packages') 'nested inside backend'
    # Marker-less directories and archives must never be removed, even if empty.
    New-Item -ItemType Directory -Path $result.TargetDirectory -Force | Out-Null
    Assert-Rejected $safe 'unmanaged existing directory'
    Write-VantagePackageMarker -Directory $result.TargetDirectory
    Assert-VantagePackageDestination -OutputDirectory $safe -RepositoryRoot $repo -BackendRuntime $runtime -ProtectedDataDirectories @($data) -ArchiveName 'Vantage-Windows-x64.zip' | Out-Null
    $checks++
    New-Item -ItemType Directory -Path $result.ArchivePath -Force | Out-Null
    Assert-Rejected $safe 'archive destination is a directory'
    Remove-Item -LiteralPath $result.ArchivePath -Force
    Set-Content -LiteralPath $result.ArchivePath -Value 'owned synthetic archive'
    Assert-VantagePackageDestination -OutputDirectory $safe -RepositoryRoot $repo -BackendRuntime $runtime -ProtectedDataDirectories @($data) -ArchiveName 'Vantage-Windows-x64.zip' | Out-Null
    $checks++
    Set-Content -LiteralPath (Join-Path $result.TargetDirectory $result.MarkerName) -Value '{"schema":1,"kind":"unrelated"}'
    Assert-Rejected $safe 'wrong ownership marker'
    Write-VantagePackageMarker -Directory $data
    Assert-Rejected (Join-Path $temp 'user-data') 'data protected even if it contains a package marker'
    $archiveOnly = Join-Path $repo 'build/archive-only'; New-Item -ItemType Directory -Path $archiveOnly -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $archiveOnly 'Vantage-Windows-x64.zip') -Value 'unrelated archive'
    Assert-Rejected $archiveOnly 'unowned existing archive'
    $prefixSibling = Join-Path $temp 'user-data/Vantage-build'
    Assert-VantagePackageDestination -OutputDirectory $prefixSibling -RepositoryRoot $repo -BackendRuntime $runtime -ProtectedDataDirectories @($data) -ArchiveName 'Vantage-Windows-x64.zip' | Out-Null
    $checks++
    # Windows junction creation is unprivileged; reject aliases before any deletion.
    if ($env:OS -eq 'Windows_NT') {
        $alias = Join-Path $temp 'alias'; New-Item -ItemType Junction -Path $alias -Target $data | Out-Null
        try { Assert-Rejected $alias 'junction alias' }
        finally { [IO.Directory]::Delete($alias) }
    }
    Write-Output "Native package destination safety: $checks checks passed."
} finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force } }
