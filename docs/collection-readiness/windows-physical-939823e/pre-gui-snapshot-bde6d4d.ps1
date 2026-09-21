$ErrorActionPreference = 'Stop'
$output = Join-Path $env:GITHUB_WORKSPACE '.test-reports/windows-pre-gui'
New-Item -ItemType Directory -Force $output | Out-Null
$memory = Get-CimInstance Win32_OperatingSystem
$drives = @($env:GITHUB_WORKSPACE, $env:RUNNER_TEMP | ForEach-Object { [IO.Path]::GetPathRoot($_).TrimEnd('\') } | Select-Object -Unique)
$disks = @(Get-CimInstance Win32_LogicalDisk | Where-Object { $_.DeviceID -in $drives } | ForEach-Object {
  @{ drive = $_.DeviceID; freeBytes = [int64]$_.FreeSpace; totalBytes = [int64]$_.Size }
})
$snapshot = [ordered]@{
  schemaVersion = 1; capturedAt = [DateTime]::UtcNow.ToString('o')
  status = 'CANDIDATE_GUI_AND_CONSOLE_ACCEPTANCE_UNVERIFIED'
  sourceCommit = (git rev-parse HEAD); workflowCommit = $env:GITHUB_SHA
  totalRamBytes = [int64]$memory.TotalVisibleMemorySize * 1024
  availableRamBytes = [int64]$memory.FreePhysicalMemory * 1024
  disks = $disks
  phasePaths = @{
    gui = Join-Path $env:GITHUB_WORKSPACE '.test-reports/windows-native-gui/gui'
    console = Join-Path $env:GITHUB_WORKSPACE '.test-reports/windows-native-gui/console'
    nativeSmoke = Join-Path $env:GITHUB_WORKSPACE '.test-reports/native-smoke'
    extractionParent = $env:RUNNER_TEMP
  }
}
$snapshot | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $output 'resources.json')
