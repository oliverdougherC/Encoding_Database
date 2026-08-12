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
$bundleDir = if ($env:ENCODINGDB_RUNTIME_BUNDLE_DIR) { $env:ENCODINGDB_RUNTIME_BUNDLE_DIR } else { Join-Path $clientDir "bin\win" }
$ffmpegPath = if ($env:ENCODINGDB_FFMPEG_PATH) { $env:ENCODINGDB_FFMPEG_PATH } else { Join-Path $bundleDir "ffmpeg.exe" }
$ffprobePath = if ($env:ENCODINGDB_FFPROBE_PATH) { $env:ENCODINGDB_FFPROBE_PATH } else { Join-Path $bundleDir "ffprobe.exe" }
$defaultRuntimeLockPath = Join-Path $clientDir "resources\runtime\ffmpeg-lock.json"
$runtimeLockPath = if ($env:ENCODINGDB_RUNTIME_LOCK_PATH) { $env:ENCODINGDB_RUNTIME_LOCK_PATH } else { $defaultRuntimeLockPath }
$guiAppName = "encodingdb-client-windows"
$consoleAppName = "encodingdb-client-windows-console"
$guiEntrypoint = Join-Path $clientDir "_pyinstaller_gui_entry.py"
$consoleEntrypoint = Join-Path $clientDir "_pyinstaller_entry.py"
$buildRoot = Join-Path $rootDir ".build\clients\windows"
$legacyDistDir = Join-Path $clientDir "dist\windows"
$pyiDistDir = Join-Path $buildRoot "dist"
$pyiWorkDir = Join-Path $buildRoot "work"
$pyiSpecDir = Join-Path $buildRoot "spec"
$runtimeResourceDir = Join-Path $buildRoot "runtime_resources"
$suiteResourceDir = Join-Path $buildRoot "suite_resources\test_suite_v1"
$suitePackPath = if ($env:ENCODINGDB_SUITE_PACK_PATH) { $env:ENCODINGDB_SUITE_PACK_PATH } else { Join-Path $rootDir "encodingdb-test-suite-v1.tar.gz" }
$guiOutputPath = Join-Path $rootDir "$guiAppName.exe"
$consoleOutputPath = Join-Path $rootDir "$consoleAppName.exe"
$logFile = Join-Path $buildRoot "build.log"
$buildRequirements = Join-Path $clientDir "requirements-build.txt"

Ensure-Exists -Path $ffmpegPath -Description "ffmpeg.exe"
Ensure-Exists -Path $ffprobePath -Description "ffprobe.exe"
Ensure-Exists -Path (Join-Path $clientDir "presets.json") -Description "presets.json"
Ensure-Exists -Path (Join-Path $clientDir "resources\\test_suite_v1\\manifest.json") -Description "suite manifest"
Ensure-Exists -Path (Join-Path $clientDir "resources\\test_suite_v1\\suite-pack.json") -Description "suite pack metadata"
Ensure-Exists -Path (Join-Path $clientDir "resources\vmaf\manifest.json") -Description "VMAF manifest"
Ensure-Exists -Path (Join-Path $clientDir "resources\vmaf\vmaf_v1.0.16_3d0h.json") -Description "VMAF model"
Ensure-Exists -Path $defaultRuntimeLockPath -Description "runtime lock manifest"
Ensure-Exists -Path $guiEntrypoint -Description "GUI PyInstaller entrypoint"
Ensure-Exists -Path $consoleEntrypoint -Description "Console PyInstaller entrypoint"
Ensure-Exists -Path $buildRequirements -Description "pinned build requirements"

Write-Log "Preparing build directories..."
if (Test-Path -LiteralPath $buildRoot) { Remove-Item -LiteralPath $buildRoot -Recurse -Force }
if (Test-Path -LiteralPath $legacyDistDir) { Remove-Item -LiteralPath $legacyDistDir -Recurse -Force }
if (Test-Path -LiteralPath $guiOutputPath) { Remove-Item -LiteralPath $guiOutputPath -Force }
if (Test-Path -LiteralPath $consoleOutputPath) { Remove-Item -LiteralPath $consoleOutputPath -Force }
if (Test-Path -LiteralPath $suitePackPath) { Remove-Item -LiteralPath $suitePackPath -Force }
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

$venvDir = Join-Path $buildRoot "venv"
$venvCreateArgs = $pythonPrefixArgs + @("-m", "venv", $venvDir)
& $pythonExe @venvCreateArgs
if ($LASTEXITCODE -ne 0) { Fail "Unable to create isolated build environment" }
$buildPython = Join-Path $venvDir "Scripts\python.exe"
& $buildPython -m pip install --disable-pip-version-check -r $buildRequirements
if ($LASTEXITCODE -ne 0) { Fail "Unable to install pinned build requirements" }

$runtimeRegisterArgs = @(
    (Join-Path $rootDir "scripts\register_ffmpeg_runtime.py"),
    "--platform", "win",
    "--ffmpeg-path", $ffmpegPath,
    "--ffprobe-path", $ffprobePath,
    "--lock-path", $runtimeLockPath,
    "--stage-runtime-dir", $runtimeResourceDir
)
if ($env:ENCODINGDB_REGISTER_RUNTIME -eq "1") { $runtimeRegisterArgs += "--update" }
& $buildPython @runtimeRegisterArgs *> $null
if ($LASTEXITCODE -ne 0) {
    Fail "Runtime lock validation failed"
}

$suitePrepareArgs = @(
    (Join-Path $rootDir "scripts\prepare_client_suite_distribution.py"),
    "--staged-resource-dir", $suiteResourceDir,
    "--pack-out", $suitePackPath
)
& $buildPython @suitePrepareArgs *> $null
if ($LASTEXITCODE -ne 0) {
    Fail "Suite pack preparation failed"
}

$verifyArgs = @(
    (Join-Path $rootDir "scripts\verify_suite_assets.py"),
    (Join-Path $clientDir "resources\test_suite_v1")
)
& $buildPython @verifyArgs
if ($LASTEXITCODE -ne 0) {
    Fail "Canonical suite asset verification failed"
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

    $buildArgs = @(
        "-m", "PyInstaller",
        "--clean",
        "--onefile",
        "--name", $Name,
        "--distpath", $pyiDistDir,
        "--workpath", $workDirForBuild,
        "--specpath", $specDirForBuild,
        "--paths", $rootDir,
        "--add-data", "$ffmpegPath;bin/win",
        "--add-data", "$ffprobePath;bin/win",
        "--add-data", "client/presets.json;.",
        "--add-data", "$suiteResourceDir;resources/test_suite_v1",
        "--add-data", "$runtimeResourceDir;resources/runtime",
        "--add-data", "client/resources/vmaf;resources/vmaf"
    )
    if ($Windowed) {
        $buildArgs += "--windowed"
    }
    $buildArgs += $Entrypoint

    Write-Log "Running PyInstaller for $Name..."
    Push-Location -LiteralPath $rootDir
    try {
        & $buildPython @buildArgs *>&1 | Tee-Object -FilePath $logFile -Append
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

if ($env:ENCODINGDB_BUILD_ONLY -eq "1") {
    Write-Log "Build-only validation complete; release sidecars require an assigned project version."
} else {
    $guiReleaseManifestArgs = $pythonPrefixArgs + @(
        (Join-Path $rootDir "scripts\\release_manifest_lib.py"),
        "--artifact-path", $guiOutputPath,
        "--platform", "win",
        "--ffmpeg-path", $ffmpegPath,
        "--ffprobe-path", $ffprobePath,
        "--runtime-lock-path", $runtimeLockPath,
        "--suite-pack-path", $suitePackPath,
        "--output-dir", $rootDir,
        "--skip-smoke"
    )
    & $pythonExe @guiReleaseManifestArgs
    if ($LASTEXITCODE -ne 0) {
        Fail "GUI release manifest finalization failed"
    }

    $releaseManifestArgs = $pythonPrefixArgs + @(
        (Join-Path $rootDir "scripts\\release_manifest_lib.py"),
        "--artifact-path", $consoleOutputPath,
        "--platform", "win",
        "--ffmpeg-path", $ffmpegPath,
        "--ffprobe-path", $ffprobePath,
        "--runtime-lock-path", $runtimeLockPath,
        "--suite-pack-path", $suitePackPath,
        "--output-dir", $rootDir
    )
    & $pythonExe @releaseManifestArgs
    if ($LASTEXITCODE -ne 0) {
        Fail "Release manifest finalization failed"
    }
}

Write-Log "Build complete: $guiOutputPath"
Write-Log "Build complete: $consoleOutputPath"
Write-Log "Suite pack: $suitePackPath"
Write-Log "Build log saved to: $logFile"
Write-Log "Hidden build artifacts: $buildRoot"

if ($env:PAUSE_ON_EXIT -eq "1") {
    [void](Read-Host "Press Enter to close")
}
