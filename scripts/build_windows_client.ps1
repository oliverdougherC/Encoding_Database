[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Log {
    param([string]$Message)
    Write-Host "[Windows] $Message"
}

function Fail {
    param([string]$Message)
    throw "[Windows] ERROR: $Message"
}

function Ensure-Exists {
    param(
        [string]$Path,
        [string]$Description
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        Fail "Missing $Description at $Path"
    }
}

function Resolve-PythonCommand {
    $candidates = @(
        @("py", "-3"),
        @("py.exe", "-3"),
        @("python.exe"),
        @("python")
    )

    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) {
            continue
        }
        try {
            $args = @()
            if ($candidate.Count -gt 1) {
                $args += $candidate[1..($candidate.Count - 1)]
            }
            $args += "--version"
            & $exe @args *> $null
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        } catch {
            continue
        }
    }

    Fail "No Windows Python interpreter found. Expected py/py.exe/python.exe."
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = (Resolve-Path -LiteralPath (Join-Path $scriptDir "..")).Path
$clientDir = Join-Path $rootDir "client"
$binDir = Join-Path $clientDir "bin\win"
$guiAppName = "encodingdb-client-windows"
$consoleAppName = "encodingdb-client-windows-console"
$guiEntrypoint = Join-Path $clientDir "_pyinstaller_gui_entry.py"
$consoleEntrypoint = Join-Path $clientDir "_pyinstaller_entry.py"
$buildRoot = Join-Path $rootDir ".build\clients\windows"
$legacyDistDir = Join-Path $clientDir "dist\windows"
$pyiDistDir = Join-Path $buildRoot "dist"
$pyiWorkDir = Join-Path $buildRoot "work"
$pyiSpecDir = Join-Path $buildRoot "spec"
$guiOutputPath = Join-Path $rootDir "$guiAppName.exe"
$consoleOutputPath = Join-Path $rootDir "$consoleAppName.exe"
$logFile = Join-Path $buildRoot "build.log"

Ensure-Exists -Path (Join-Path $binDir "ffmpeg.exe") -Description "ffmpeg.exe"
Ensure-Exists -Path (Join-Path $binDir "ffprobe.exe") -Description "ffprobe.exe"
Ensure-Exists -Path (Join-Path $rootDir "sample.mp4") -Description "sample.mp4"
Ensure-Exists -Path (Join-Path $clientDir "presets.json") -Description "presets.json"
Ensure-Exists -Path $guiEntrypoint -Description "GUI PyInstaller entrypoint"
Ensure-Exists -Path $consoleEntrypoint -Description "Console PyInstaller entrypoint"

Write-Log "Preparing build directories..."
if (Test-Path -LiteralPath $buildRoot) { Remove-Item -LiteralPath $buildRoot -Recurse -Force }
if (Test-Path -LiteralPath $legacyDistDir) { Remove-Item -LiteralPath $legacyDistDir -Recurse -Force }
if (Test-Path -LiteralPath $guiOutputPath) { Remove-Item -LiteralPath $guiOutputPath -Force }
if (Test-Path -LiteralPath $consoleOutputPath) { Remove-Item -LiteralPath $consoleOutputPath -Force }
if (Test-Path -LiteralPath (Join-Path $rootDir "dist\$guiAppName.exe")) { Remove-Item -LiteralPath (Join-Path $rootDir "dist\$guiAppName.exe") -Force }
if (Test-Path -LiteralPath (Join-Path $rootDir "dist\$consoleAppName.exe")) { Remove-Item -LiteralPath (Join-Path $rootDir "dist\$consoleAppName.exe") -Force }
if (Test-Path -LiteralPath (Join-Path $rootDir "build\$guiAppName")) { Remove-Item -LiteralPath (Join-Path $rootDir "build\$guiAppName") -Recurse -Force }
if (Test-Path -LiteralPath (Join-Path $rootDir "build\$consoleAppName")) { Remove-Item -LiteralPath (Join-Path $rootDir "build\$consoleAppName") -Recurse -Force }

New-Item -ItemType Directory -Path $pyiDistDir -Force | Out-Null
New-Item -ItemType Directory -Path $pyiWorkDir -Force | Out-Null
New-Item -ItemType Directory -Path $pyiSpecDir -Force | Out-Null

$pythonCmd = Resolve-PythonCommand
$pythonExe = $pythonCmd[0]
$pythonPrefixArgs = @()
if ($pythonCmd.Count -gt 1) {
    $pythonPrefixArgs = $pythonCmd[1..($pythonCmd.Count - 1)]
}

Write-Log ("Using Python command: " + ($pythonCmd -join " "))

$checkArgs = $pythonPrefixArgs + @("-m", "PyInstaller", "--version")
& $pythonExe @checkArgs *> $null
if ($LASTEXITCODE -ne 0) {
    Fail "PyInstaller is not installed for this interpreter. Install with: $($pythonCmd -join ' ') -m pip install pyinstaller"
}

function Invoke-PyInstallerBuild {
    param(
        [string]$Name,
        [string]$Entrypoint,
        [switch]$Windowed
    )

    $workDirForBuild = Join-Path $pyiWorkDir $Name
    $specDirForBuild = Join-Path $pyiSpecDir $Name
    New-Item -ItemType Directory -Path $workDirForBuild -Force | Out-Null
    New-Item -ItemType Directory -Path $specDirForBuild -Force | Out-Null

    $buildArgs = $pythonPrefixArgs + @(
        "-m", "PyInstaller",
        "--clean",
        "--onefile",
        "--name", $Name,
        "--distpath", $pyiDistDir,
        "--workpath", $workDirForBuild,
        "--specpath", $specDirForBuild,
        "--paths", $rootDir,
        "--add-data", "client/bin/win/ffmpeg.exe;bin/win",
        "--add-data", "client/bin/win/ffprobe.exe;bin/win",
        "--add-data", "sample.mp4;.",
        "--add-data", "client/presets.json;."
    )
    if ($Windowed) {
        $buildArgs += "--windowed"
    }
    $buildArgs += $Entrypoint

    Write-Log "Running PyInstaller for $Name..."
    Push-Location -LiteralPath $rootDir
    try {
        & $pythonExe @buildArgs *>&1 | Tee-Object -FilePath $logFile -Append
        if ($LASTEXITCODE -ne 0) {
            Fail "PyInstaller failed for $Name. See build log: $logFile"
        }
    } finally {
        Pop-Location
    }
}

Invoke-PyInstallerBuild -Name $guiAppName -Entrypoint $guiEntrypoint -Windowed
Invoke-PyInstallerBuild -Name $consoleAppName -Entrypoint $consoleEntrypoint

$builtGuiExe = Join-Path $pyiDistDir "$guiAppName.exe"
if (-not (Test-Path -LiteralPath $builtGuiExe)) {
    Fail "GUI build output not found at $builtGuiExe"
}
$builtConsoleExe = Join-Path $pyiDistDir "$consoleAppName.exe"
if (-not (Test-Path -LiteralPath $builtConsoleExe)) {
    Fail "Console build output not found at $builtConsoleExe"
}

Write-Log "Placing executables in repository root..."
Move-Item -LiteralPath $builtGuiExe -Destination $guiOutputPath -Force
Move-Item -LiteralPath $builtConsoleExe -Destination $consoleOutputPath -Force

Write-Log "Build complete: $guiOutputPath"
Write-Log "Build complete: $consoleOutputPath"
Write-Log "Build log saved to: $logFile"
Write-Log "Hidden build artifacts: $buildRoot"

if ($env:PAUSE_ON_EXIT -eq "1") {
    [void](Read-Host "Press Enter to close")
}
