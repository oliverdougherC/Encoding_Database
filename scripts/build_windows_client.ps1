# PowerShell script to build Windows standalone client with PyInstaller
# Run this from Windows PowerShell or PowerShell Core
# Requires: Windows Python with PyInstaller installed, and ffmpeg/ffprobe in client/bin/win

param(
    [switch]$Verbose,
    [switch]$PauseOnExit
)

# Enable strict error handling
$ErrorActionPreference = "Stop"

# Get script directory and set up paths
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
$ClientDir = Join-Path $RootDir "client"
$BuildDir = Join-Path $ClientDir "dist\windows"
$BinSrcDir = Join-Path $ClientDir "bin\win"
$VenvScriptsDir = Join-Path $RootDir ".myenv\Scripts"

# Enable verbose output if requested
if ($Verbose) {
    $VerbosePreference = "Continue"
}

Write-Host "[Windows] Preparing build directories..." -ForegroundColor Green
# Remove existing build directory
if (Test-Path $BuildDir) {
    Remove-Item -Path $BuildDir -Recurse -Force
}
# Create build directory structure
New-Item -Path $BuildDir -ItemType Directory -Force | Out-Null
New-Item -Path (Join-Path $BuildDir "bin\win") -ItemType Directory -Force | Out-Null

# Set up log file
$LogFile = Join-Path $BuildDir "build.log"
Write-Host "[Windows] Build log will be saved to: $LogFile" -ForegroundColor Yellow

Write-Host "[Windows] Verifying ffmpeg/ffprobe binaries..." -ForegroundColor Green
$FfmpegPath = Join-Path $BinSrcDir "ffmpeg.exe"
$FfprobePath = Join-Path $BinSrcDir "ffprobe.exe"

if (-not (Test-Path $FfmpegPath) -or -not (Test-Path $FfprobePath)) {
    Write-Error "ERROR: Expected ffmpeg.exe and ffprobe.exe at $BinSrcDir"
    exit 1
}

Write-Host "[Windows] Copying resources..." -ForegroundColor Green
Copy-Item -Path $FfmpegPath -Destination (Join-Path $BuildDir "bin\win\ffmpeg.exe") -Force
Copy-Item -Path $FfprobePath -Destination (Join-Path $BuildDir "bin\win\ffprobe.exe") -Force

# Copy sample video if it exists
$SampleVideo = Join-Path $RootDir "sample.mp4"
if (Test-Path $SampleVideo) {
    Copy-Item -Path $SampleVideo -Destination $BuildDir -Force
}

# Copy presets.json if it exists
$PresetsFile = Join-Path $ClientDir "presets.json"
if (Test-Path $PresetsFile) {
    Copy-Item -Path $PresetsFile -Destination $BuildDir -Force
}

Write-Host "[Windows] Running PyInstaller..." -ForegroundColor Green
Set-Location $ClientDir

# Determine which Python/PyInstaller to use
$PyInstallerCmd = $null

# Check for local venv PyInstaller first
$VenvPyInstaller = Join-Path $VenvScriptsDir "pyinstaller.exe"
if (Test-Path $VenvPyInstaller) {
    Write-Host "[Windows] Using local venv PyInstaller: $VenvPyInstaller" -ForegroundColor Yellow
    $PyInstallerCmd = $VenvPyInstaller
}
# Check for local venv Python
elseif (Test-Path (Join-Path $VenvScriptsDir "python.exe")) {
    $VenvPython = Join-Path $VenvScriptsDir "python.exe"
    Write-Host "[Windows] Using local venv Python: $VenvPython" -ForegroundColor Yellow
    $PyInstallerCmd = @($VenvPython, "-m", "PyInstaller")
}
# Try Windows Python launcher
elseif (Get-Command py -ErrorAction SilentlyContinue) {
    Write-Host "[Windows] Using Windows Python launcher: py -3" -ForegroundColor Yellow
    $PyInstallerCmd = @("py", "-3", "-m", "PyInstaller")
}
# Try py.exe
elseif (Get-Command py.exe -ErrorAction SilentlyContinue) {
    Write-Host "[Windows] Using Windows Python launcher: py.exe -3" -ForegroundColor Yellow
    $PyInstallerCmd = @("py.exe", "-3", "-m", "PyInstaller")
}
# Try python.exe
elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
    Write-Host "[Windows] Using python.exe" -ForegroundColor Yellow
    $PyInstallerCmd = @("python.exe", "-m", "PyInstaller")
}
# Fallback to python
elseif (Get-Command python -ErrorAction SilentlyContinue) {
    Write-Host "[Windows] Using python (fallback)" -ForegroundColor Yellow
    $PyInstallerCmd = @("python", "-m", "PyInstaller")
}
else {
    Write-Error "ERROR: No Python interpreter found. Please install Python or activate your virtual environment."
    exit 1
}

# Verify PyInstaller is available
Write-Host "[Windows] Verifying PyInstaller is available..." -ForegroundColor Green
try {
    if ($PyInstallerCmd -is [string]) {
        & $PyInstallerCmd --version | Out-Null
    } else {
        & $PyInstallerCmd[0] $PyInstallerCmd[1..($PyInstallerCmd.Length-1)] --version | Out-Null
    }
} catch {
    Write-Error "ERROR: PyInstaller is not installed for this Python interpreter."
    Write-Error "       Install with: $($PyInstallerCmd -join ' ') -m pip install pyinstaller"
    exit 3
}

# Run PyInstaller
Write-Host "[Windows] Building executable..." -ForegroundColor Green
$PyInstallerArgs = @(
    "--clean",
    "--onefile",
    "--name", "encodingdb-client-windows",
    "--add-data", "bin/win/ffmpeg.exe;bin/win",
    "--add-data", "bin/win/ffprobe.exe;bin/win",
    "--add-data", "../sample.mp4;.",
    "--add-data", "presets.json;.",
    "main.py"
)

try {
    if ($PyInstallerCmd -is [string]) {
        & $PyInstallerCmd @PyInstallerArgs
    } else {
        & $PyInstallerCmd[0] $PyInstallerCmd[1..($PyInstallerCmd.Length-1)] @PyInstallerArgs
    }
} catch {
    Write-Error "ERROR: PyInstaller failed to build the executable."
    Write-Error $_.Exception.Message
    exit 2
}

Write-Host "[Windows] Moving artifact to $BuildDir..." -ForegroundColor Green
$ExePath = Join-Path $ClientDir "dist\encodingdb-client-windows.exe"
$DirPath = Join-Path $ClientDir "dist\encodingdb-client-windows"

if (Test-Path $ExePath) {
    Move-Item -Path $ExePath -Destination $BuildDir -Force
    Write-Host "[Windows] Build complete: $BuildDir" -ForegroundColor Green
} elseif (Test-Path $DirPath) {
    Move-Item -Path $DirPath -Destination $BuildDir -Force
    Write-Host "[Windows] Build complete: $BuildDir" -ForegroundColor Green
} else {
    Write-Error "ERROR: PyInstaller did not produce encodingdb-client-windows.exe."
    Write-Error "       Ensure Windows Python (py -3) is used and PyInstaller is installed."
    exit 2
}

Write-Host "[Windows] Build log saved to: $LogFile" -ForegroundColor Yellow

# Optional pause for double-click runs
if ($PauseOnExit) {
    Read-Host "Press Enter to close..."
}
