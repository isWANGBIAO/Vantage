[CmdletBinding()]
param(
    [int]$BackendVerifyTimeoutSeconds = 60,
    [int]$BuildWorkers = 0,
    [switch]$SkipBackendSmoke
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$WebappRoot = Join-Path $ProjectRoot "src\webapp"
$BackendRuntimeVenv = Join-Path $ProjectRoot ".venv-backend-runtime-gpu"
$BackendRuntimePython = Join-Path $BackendRuntimeVenv "Scripts\python.exe"
$BackendRuntimeRequirements = Join-Path $ProjectRoot "requirements-backend-runtime-gpu.txt"
$BackendRuntimeRequirementsStamp = Join-Path $BackendRuntimeVenv ".requirements-backend-runtime-gpu.sha256"
$WebappBuildInfo = Join-Path $WebappRoot "build-info.json"
$BuildInfoBackup = Join-Path $env:TEMP ("vantage-release-build-info-{0}-{1}.json" -f $PID, [Guid]::NewGuid().ToString("N"))
$BuildInfoBackupCreated = $false

$CustomNsisBinaryRelease = "1.0.0"
$CustomNsisBinaryFile = "nsisbi-electronbuilder-3.10.3.7z"
$CustomNsisBinaryUrl = "https://github.com/SoundSafari/NSISBI-ElectronBuilder/releases/download/$CustomNsisBinaryRelease/$CustomNsisBinaryFile"
$CustomNsisBinarySha256 = "374cfc092fd1bd1898472df627549ecc165b0d6ba88e82deba085673aec95336"

if (-not $env:VANTAGE_ELECTRON_MIRROR_FALLBACK) {
    $env:VANTAGE_ELECTRON_MIRROR_FALLBACK = "https://npmmirror.com/mirrors/electron/"
}

if ($BuildWorkers -le 0) {
    if ($env:VANTAGE_BUILD_WORKERS) {
        $BuildWorkers = [int]$env:VANTAGE_BUILD_WORKERS
    } else {
        $BuildWorkers = [Environment]::ProcessorCount
    }
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = $ProjectRoot
    )

    Push-Location $WorkingDirectory
    try {
        & $FilePath @ArgumentList
        if ($LASTEXITCODE -ne 0) {
            throw "$FilePath $($ArgumentList -join ' ') failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}

function Invoke-WithElectronMirrorFallback {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Action,
        [Parameter(Mandatory = $true)][string]$Description
    )

    try {
        & $Action
        return
    } catch {
        if ($env:ELECTRON_MIRROR) {
            throw
        }
        $env:ELECTRON_MIRROR = $env:VANTAGE_ELECTRON_MIRROR_FALLBACK
        Write-Host "Retrying $Description with Electron mirror fallback: $env:ELECTRON_MIRROR"
        & $Action
    }
}

function Ensure-CustomNsisArchiveCache {
    $cacheRoot = $env:ELECTRON_BUILDER_CACHE
    if (-not $cacheRoot -or -not [System.IO.Path]::IsPathRooted($cacheRoot)) {
        if ($env:LOCALAPPDATA) {
            $cacheRoot = Join-Path $env:LOCALAPPDATA "electron-builder\Cache"
        } else {
            $cacheRoot = Join-Path $env:TEMP "electron-builder-cache"
        }
    }

    $archiveDir = Join-Path $cacheRoot $CustomNsisBinaryRelease
    $archive = Join-Path $archiveDir $CustomNsisBinaryFile
    New-Item -ItemType Directory -Force -Path $archiveDir | Out-Null

    if (Test-Path -LiteralPath $archive) {
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
        if ($actual -eq $CustomNsisBinarySha256) {
            Write-Host "Custom NSIS archive cache ready"
            return
        }
        Write-Host "Custom NSIS archive checksum mismatch; refreshing"
        Remove-Item -LiteralPath $archive -Force
    }

    $tmp = "$archive.tmp"
    if (Test-Path -LiteralPath $tmp) {
        Remove-Item -LiteralPath $tmp -Force
    }
    & curl.exe --silent --show-error --location --retry 3 --retry-delay 2 --fail --output $tmp $CustomNsisBinaryUrl
    if ($LASTEXITCODE -ne 0) {
        throw "curl failed while downloading custom NSIS archive with exit code $LASTEXITCODE"
    }

    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $tmp).Hash.ToLowerInvariant()
    if ($actual -ne $CustomNsisBinarySha256) {
        Remove-Item -LiteralPath $tmp -Force
        throw "Custom NSIS archive checksum mismatch"
    }
    Move-Item -LiteralPath $tmp -Destination $archive -Force
    Write-Host "Custom NSIS archive cache ready"
}

function Restore-BuildInfo {
    if ($BuildInfoBackupCreated -and (Test-Path -LiteralPath $BuildInfoBackup)) {
        Copy-Item -LiteralPath $BuildInfoBackup -Destination $WebappBuildInfo -Force
        Remove-Item -LiteralPath $BuildInfoBackup -Force
        Write-Host "Source build-info restored"
    }
}

Set-Location $ProjectRoot

try {
    Write-Host "[1/7] Installing frontend dependencies"
    if ($env:CI -eq "true") {
        Invoke-WithElectronMirrorFallback -Description "npm ci" -Action {
            Invoke-Native -FilePath "npm" -ArgumentList @("ci") -WorkingDirectory $WebappRoot
        }
    } elseif (-not (Test-Path -LiteralPath (Join-Path $WebappRoot "node_modules"))) {
        Invoke-WithElectronMirrorFallback -Description "npm install" -Action {
            Invoke-Native -FilePath "npm" -ArgumentList @("install") -WorkingDirectory $WebappRoot
        }
    } else {
        Write-Host "Frontend dependencies already installed"
    }

    Invoke-WithElectronMirrorFallback -Description "Electron binary preparation" -Action {
        Invoke-Native -FilePath "node" -ArgumentList @("node_modules\electron\install.js") -WorkingDirectory $WebappRoot
    }
    Invoke-Native -FilePath "npm" -ArgumentList @("exec", "--", "electron", "--version") -WorkingDirectory $WebappRoot

    Write-Host "[2/7] Preparing backend runtime environment"
    if (-not (Test-Path -LiteralPath $BackendRuntimePython)) {
        Invoke-Native -FilePath "python" -ArgumentList @("-m", "venv", $BackendRuntimeVenv)
    }

    $requirementsHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $BackendRuntimeRequirements).Hash
    $storedHash = $null
    if (Test-Path -LiteralPath $BackendRuntimeRequirementsStamp) {
        $storedHash = (Get-Content -LiteralPath $BackendRuntimeRequirementsStamp -Raw).Trim()
    }

    if ($requirementsHash -eq $storedHash -and $env:VANTAGE_FORCE_BACKEND_DEPS -ne "1") {
        Write-Host "Backend runtime dependencies already synced"
    } else {
        Invoke-Native -FilePath $BackendRuntimePython -ArgumentList @("-m", "pip", "install", "--upgrade", "pip")
        Invoke-Native -FilePath $BackendRuntimePython -ArgumentList @("-m", "pip", "install", "-r", $BackendRuntimeRequirements)
        Set-Content -LiteralPath $BackendRuntimeRequirementsStamp -Value $requirementsHash -Encoding ascii
    }
    Invoke-Native -FilePath $BackendRuntimePython -ArgumentList @("-c", "import chinese_calendar, lap, zhdate; print('backend runtime dependency imports ok')")

    Write-Host "[3/7] Preparing release build metadata"
    if (Test-Path -LiteralPath $WebappBuildInfo) {
        Copy-Item -LiteralPath $WebappBuildInfo -Destination $BuildInfoBackup -Force
        $BuildInfoBackupCreated = $true
    }
    Invoke-Native -FilePath "node" -ArgumentList @("scripts\prepare-build-version.mjs", "--mode", "sync") -WorkingDirectory $WebappRoot

    Write-Host "[4/7] Building frontend and backend runtime"
    Invoke-Native -FilePath $BackendRuntimePython -ArgumentList @(
        "src\scripts\run_packaging_builds.py",
        "--backend-python",
        $BackendRuntimePython,
        "--workers",
        "$BuildWorkers"
    )

    Write-Host "[5/7] Verifying backend runtime"
    $verifyArgs = @("src\scripts\verify_backend_runtime.py", "--timeout-seconds", "$BackendVerifyTimeoutSeconds")
    if ($SkipBackendSmoke) {
        $verifyArgs += "--skip-launch"
    }
    Invoke-Native -FilePath $BackendRuntimePython -ArgumentList $verifyArgs

    Write-Host "[6/7] Building Windows installer"
    Ensure-CustomNsisArchiveCache
    Invoke-WithElectronMirrorFallback -Description "Electron package" -Action {
        Invoke-Native -FilePath "npm" -ArgumentList @("run", "electron:package") -WorkingDirectory $WebappRoot
    }

    Write-Host "[7/7] Locating installer"
    $installer = Get-ChildItem -LiteralPath (Join-Path $WebappRoot "electron-dist") -Filter "Vantage Setup *.exe" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $installer) {
        throw "Installer package not found in src\webapp\electron-dist"
    }
    if ($installer.Length -ge 2147483648) {
        throw "Installer is $($installer.Length) bytes, which is at or above GitHub's 2 GiB release asset limit."
    }

    Write-Host "Release installer ready: $($installer.FullName)"
    if ($env:GITHUB_OUTPUT) {
        Add-Content -LiteralPath $env:GITHUB_OUTPUT -Value "installer_path=$($installer.FullName)"
        Add-Content -LiteralPath $env:GITHUB_OUTPUT -Value "installer_name=$($installer.Name)"
    }
} finally {
    Restore-BuildInfo
}
