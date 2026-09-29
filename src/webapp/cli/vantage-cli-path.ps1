param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Add", "Remove")]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [string]$Directory,
    [string]$PathValue,
    [switch]$TestPathValue
)

$ErrorActionPreference = "Stop"

function Normalize-PathEntry([string]$Entry) {
    $candidate = $Entry.Trim()
    if ($candidate.Length -ge 2 -and $candidate.StartsWith('"') -and $candidate.EndsWith('"')) {
        $candidate = $candidate.Substring(1, $candidate.Length - 2)
    }
    if (-not $candidate) {
        return ""
    }

    $candidate = [Environment]::ExpandEnvironmentVariables($candidate)
    try {
        $candidate = [IO.Path]::GetFullPath($candidate)
    } catch {
        # Preserve unusual but unrelated PATH entries; only compare normalized paths.
    }
    if ($candidate.Length -gt 3) {
        $candidate = $candidate.TrimEnd('\', '/')
    }
    return $candidate
}

function Update-PathValue([string]$Current, [string]$Target, [string]$RequestedAction) {
    $normalizedTarget = Normalize-PathEntry $Target
    $remaining = @()
    if ($null -ne $Current -and $Current.Length -gt 0) {
        foreach ($entry in $Current.Split([char]';')) {
            if (-not [string]::Equals(
                (Normalize-PathEntry $entry),
                $normalizedTarget,
                [StringComparison]::OrdinalIgnoreCase
            )) {
                $remaining += $entry
            }
        }
    }

    if ($RequestedAction -eq "Add") {
        return (@($Target) + $remaining) -join ';'
    }
    return $remaining -join ';'
}

if ($TestPathValue) {
    [Console]::Out.Write((Update-PathValue $PathValue $Directory $Action))
    exit 0
}

try {
    $environmentKeyPath = "Environment"
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($environmentKeyPath, $true)
    if ($null -eq $key) {
        if ($Action -eq "Remove") {
            exit 0
        }
        $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($environmentKeyPath)
    }

    $pathExists = $key.GetValueNames() -contains "Path"
    if (-not $pathExists -and $Action -eq "Remove") {
        $key.Dispose()
        exit 0
    }

    $currentValue = if ($pathExists) {
        [string]$key.GetValue(
            "Path",
            "",
            [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
        )
    } else {
        ""
    }
    $valueKind = if ($pathExists) {
        $key.GetValueKind("Path")
    } else {
        [Microsoft.Win32.RegistryValueKind]::ExpandString
    }
    $updatedValue = Update-PathValue $currentValue $Directory $Action
    if ($updatedValue -cne $currentValue -or -not $pathExists) {
        if ($Action -eq "Remove" -and $updatedValue.Length -eq 0) {
            $key.DeleteValue("Path", $false)
        } else {
            $key.SetValue("Path", $updatedValue, $valueKind)
        }
        $key.Dispose()

        $nativeCode = @'
using System;
using System.Runtime.InteropServices;
public static class VantageEnvironmentBroadcast {
    [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
    public static extern IntPtr SendMessageTimeout(
        IntPtr hWnd, uint message, UIntPtr wParam, string lParam,
        uint flags, uint timeout, out UIntPtr result);
}
'@
        Add-Type -TypeDefinition $nativeCode -ErrorAction SilentlyContinue
        $result = [UIntPtr]::Zero
        [void][VantageEnvironmentBroadcast]::SendMessageTimeout(
            [IntPtr]0xffff,
            0x001A,
            [UIntPtr]::Zero,
            "Environment",
            0x0002,
            5000,
            [ref]$result
        )
    } else {
        $key.Dispose()
    }
} catch {
    [Console]::Error.WriteLine("Could not update the Vantage user PATH entry.")
    exit 1
}
