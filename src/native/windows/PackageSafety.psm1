Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-NativeFullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    $full = [IO.Path]::GetFullPath($Path)
    if ($full.StartsWith('\\')) { throw 'Native package paths must be local paths, not UNC or device paths.' }
    $root = [IO.Path]::GetPathRoot($full)
    if ($full.Length -gt $root.Length) { return $full.TrimEnd([char[]]@([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)) }
    return $full
}

function Test-NativeWithin {
    param([string]$Child, [string]$Parent)
    if ([string]::Equals($Child, $Parent, [StringComparison]::OrdinalIgnoreCase)) { return $true }
    $prefix = $Parent
    if (-not $prefix.EndsWith([IO.Path]::DirectorySeparatorChar.ToString())) { $prefix += [IO.Path]::DirectorySeparatorChar }
    return $Child.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
}

function Assert-NativeNoReparsePath {
    param([string]$Path)
    $current = $Path
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'Native package and protected paths must not traverse a symlink or junction.'
            }
        }
        $parent = Split-Path -Path $current -Parent
        if (-not $parent -or $parent -eq $current) { break }
        $current = $parent
    }
}

function Assert-VantagePackageDestination {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$OutputDirectory,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$BackendRuntime,
        [Parameter(Mandatory = $true)][string[]]$ProtectedDataDirectories,
        [Parameter(Mandatory = $true)][string]$ArchiveName
    )
    if ($ArchiveName -notmatch '^Vantage-Windows-(x64|arm64)\.zip$') { throw 'ArchiveName must be a supported native package filename.' }
    $output = Get-NativeFullPath $OutputDirectory
    $target = Get-NativeFullPath (Join-Path $output 'Vantage')
    $archive = Get-NativeFullPath (Join-Path $output $ArchiveName)
    $repo = Get-NativeFullPath $RepositoryRoot
    $runtime = Get-NativeFullPath $BackendRuntime
    foreach ($path in @($output, $target, $archive, $repo, $runtime)) { Assert-NativeNoReparsePath $path }
    if (Test-NativeWithin $repo $target) { throw 'Native package destination would replace the repository or one of its ancestors.' }
    if ((Test-NativeWithin $runtime $target) -or (Test-NativeWithin $target $runtime) -or (Test-NativeWithin $output $runtime)) {
        throw 'Native package destination overlaps the selected backend runtime.'
    }
    foreach ($data in $ProtectedDataDirectories) {
        if ([string]::IsNullOrWhiteSpace($data)) { continue }
        $protected = Get-NativeFullPath $data
        Assert-NativeNoReparsePath $protected
        if ((Test-NativeWithin $protected $target) -or (Test-NativeWithin $target $protected) -or (Test-NativeWithin $output $protected)) {
            throw 'Native package destination overlaps a protected Vantage data directory.'
        }
    }
    $markerName = '.vantage-native-package.json'
    $marker = Join-Path $target $markerName
    $owned = $false
    if (Test-Path -LiteralPath $target) {
        if (-not (Test-Path -LiteralPath $target -PathType Container)) { throw 'Native package target is an existing non-directory.' }
        if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) { throw 'Refusing to replace an unmarked directory. Choose a new output directory or inspect and remove the old output yourself.' }
        Assert-NativeNoReparsePath $marker
        if ((Get-Item -LiteralPath $marker).Length -gt 4096) { throw 'Native package ownership marker is invalid.' }
        $metadata = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
        if ($metadata.schema -ne 1 -or $metadata.kind -ne 'vantage-native-windows') { throw 'Native package ownership marker is invalid.' }
        $owned = $true
    }
    if (Test-Path -LiteralPath $archive) {
        if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) { throw 'Archive destination is an existing non-file.' }
        if (-not $owned) { throw 'Refusing to overwrite an archive without an owned native package directory.' }
    }
    return [pscustomobject]@{ OutputDirectory = $output; TargetDirectory = $target; ArchivePath = $archive; MarkerName = $markerName }
}

function Write-VantagePackageMarker {
    param([Parameter(Mandatory = $true)][string]$Directory)
    $marker = Join-Path $Directory '.vantage-native-package.json'
    @{ schema = 1; kind = 'vantage-native-windows' } | ConvertTo-Json | Set-Content -LiteralPath $marker -Encoding UTF8
}

Export-ModuleMember -Function Assert-VantagePackageDestination, Write-VantagePackageMarker
