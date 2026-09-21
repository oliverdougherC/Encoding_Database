# Direct limited scheduled PowerShell launch, matching the successful idle diagnostic.
param([Parameter(Mandatory=$true)][string]$Root,[Parameter(Mandatory=$true)][string]$Label,[Parameter(Mandatory=$true)][string]$RunLabel)
$ErrorActionPreference='Stop'
$receiptPath=Join-Path $Root ('gui-launch-'+$RunLabel+'-receipt.json')
if (Test-Path $receiptPath) { throw 'Create-only GUI launch receipt exists' }
Add-Type @'
using System.Runtime.InteropServices;
public static class EdbDirectSession { [DllImport("kernel32.dll")] public static extern uint WTSGetActiveConsoleSessionId(); }
'@
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$admin=([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$session=(Get-Process -Id $PID).SessionId
if ($session -eq 0 -or $session -ne [EdbDirectSession]::WTSGetActiveConsoleSessionId() -or $admin) { throw 'Require active non-elevated console session' }
$outerReceipt=[ordered]@{status='RUNNING';startedAt=[DateTime]::UtcNow.ToString('o');sessionId=$session;activeConsoleSessionId=[EdbDirectSession]::WTSGetActiveConsoleSessionId();administratorRole=$admin;launchContext='direct limited scheduled PowerShell with WindowStyle Hidden';forcedCleanup=$false}
function Save-Outer { $outerReceipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding utf8 }
Save-Outer
$allocation=$null
Start-Transcript -Path (Join-Path $Root ('gui-direct-'+$RunLabel+'.log')) -NoClobber | Out-Null
try {
 $allocation=[IO.File]::Open((Join-Path $Root 'host-state\physical-operator.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
 $source=Join-Path $Root ('source-'+$Label)
 $pins=Get-Content -LiteralPath (Join-Path $Root ('physical-candidate-pins-'+$Label+'.json')) -Raw | ConvertFrom-Json
 foreach ($entry in $pins.files.PSObject.Properties) {
  $file=Join-Path $source $entry.Name
  if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value) {throw ('Pinned payload differs: '+$entry.Name)}
 }
 if ((Get-Content -LiteralPath (Join-Path $Root 'host-state\physical-source-id') -Raw).Trim() -ne 'installation-9e7cd0a8c6158d19d179f0acf79249c6c790b988b8a48f6563952c1c00acca29') {throw 'Physical identity changed'}
 $env:RUNNER_TEMP=Join-Path $Root ('gui-temp-'+$RunLabel)
 New-Item -ItemType Directory -Path $env:RUNNER_TEMP -ErrorAction Stop | Out-Null
 $driver=Join-Path $Root ('gui-driver-'+$RunLabel+'\test-windows-native-gui.ps1')
 $outerReceipt.driverSha256=(Get-FileHash -LiteralPath $driver -Algorithm SHA256).Hash.ToLowerInvariant()
 $outerReceipt.sourceRevision=$pins.actualBuildRevision
 Save-Outer
 & $driver -Mode Gui -Output ('.test-reports/windows-physical-gui-'+$RunLabel) -AcquisitionSeconds 600 -MeasurementMinutes 20
 if ($LASTEXITCODE -ne 0) {throw ('GUI verifier exited '+$LASTEXITCODE)}
 $outerReceipt.status='EXECUTED_PENDING_VISUAL_REVIEW';$outerReceipt.exitCode=0
} catch {
 $outerReceipt.status='FAILED';$outerReceipt.error=$_.Exception.Message
} finally {
 if ($allocation) {$allocation.Dispose()}
 $outerReceipt.finishedAt=[DateTime]::UtcNow.ToString('o');Save-Outer
 Stop-Transcript | Out-Null
}
if ($outerReceipt.status -ne 'EXECUTED_PENDING_VISUAL_REVIEW') {exit 1}
