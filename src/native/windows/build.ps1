[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$BackendRuntime,
    [string]$OutputDirectory,
    [ValidateSet('x64', 'ARM64')][string]$Architecture = 'x64',
    [switch]$SkipTests
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$runtime = (Resolve-Path $BackendRuntime).Path
if (-not (Test-Path (Join-Path $runtime 'VantageBackend.exe'))) { throw 'BackendRuntime must contain the real VantageBackend.exe bundle.' }
if (-not (Test-Path (Join-Path $runtime 'runtime-manifest.json'))) { throw 'Backend runtime manifest is required; use src/scripts/build_backend_runtime.py.' }
& python (Join-Path $repo 'scripts/validate_native_runtime.py') --runtime $runtime --platform win32 --architecture ($Architecture.ToLower())
if ($LASTEXITCODE -ne 0) { throw 'Backend runtime validation failed.' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $repo 'build/native/windows' }
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$target = Join-Path $OutputDirectory 'Vantage'
$rid = if ($Architecture -eq 'ARM64') { 'win-arm64' } else { 'win-x64' }
if (-not $SkipTests) {
    & dotnet test (Join-Path $PSScriptRoot 'Vantage.Core.Tests/Vantage.Core.Tests.csproj') -c Release
    if ($LASTEXITCODE -ne 0) { throw 'Native core tests failed.' }
}
# Publish into a clean staging directory; never overlay a prior native/runtime version.
$stage = Join-Path $OutputDirectory ('stage-' + [Guid]::NewGuid().ToString('N'))
try {
    & dotnet publish (Join-Path $PSScriptRoot 'Vantage.Windows/Vantage.Windows.csproj') -c Release -r $rid "-p:Platform=$Architecture" -p:WindowsPackageType=None --self-contained true -o $stage
    if ($LASTEXITCODE -ne 0) { throw 'WinUI publish failed.' }
    New-Item -ItemType Directory -Path (Join-Path $stage 'backend-runtime') -Force | Out-Null
    Copy-Item $runtime (Join-Path $stage 'backend-runtime/VantageBackend') -Recurse
    Copy-Item (Join-Path $repo 'LICENSE') $stage
    if (-not (Test-Path (Join-Path $stage 'Vantage.Windows.exe'))) { throw 'Native executable missing from publish output.' }
    if (Test-Path $target) { Remove-Item $target -Recurse -Force }
    Move-Item $stage $target
    $zip = Join-Path $OutputDirectory "Vantage-Windows-$($Architecture.ToLower()).zip"
    if (Test-Path $zip) { Remove-Item $zip -Force }
    # Compress-Archive has a 2GB input-file limit, so use .NET's ZIP implementation.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::CreateFromDirectory($target, $zip, [IO.Compression.CompressionLevel]::Optimal, $true)
    Write-Output "Native application: $target"
    Write-Output "Portable package: $zip"
} finally { if (Test-Path $stage) { Remove-Item $stage -Recurse -Force } }
