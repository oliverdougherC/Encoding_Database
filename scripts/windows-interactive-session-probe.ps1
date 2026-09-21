# Own identity only. No screenshots, window enumeration, benchmarks, or elevation.
param([Parameter(Mandatory=$true)][string]$Root)
$ErrorActionPreference='Stop'
$stamp=[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')+'-'+[Guid]::NewGuid().ToString('N').Substring(0,8)
$name='EncodingDB-Interactive-Probe-'+$stamp
$dir=Join-Path $Root ('interactive-probe-'+$stamp)
if ((Test-Path -LiteralPath $dir) -or (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue)) { throw 'Create-only probe collision' }
New-Item -ItemType Directory -Path $dir | Out-Null
$probePath=Join-Path $dir 'probe.ps1'; $resultPath=Join-Path $dir 'result.json'; $receiptPath=Join-Path $dir 'receipt.json'
@'
param([string]$ResultPath)
$ErrorActionPreference='Stop'
Add-Type @"
using System.Runtime.InteropServices;
public static class EdbConsoleProbe {
 [DllImport("kernel32.dll")] public static extern uint WTSGetActiveConsoleSessionId();
}
"@
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=[Security.Principal.WindowsPrincipal]::new($identity)
[ordered]@{
 capturedAt=[DateTime]::UtcNow.ToString('o'); user=$identity.Name; processId=$PID
 sessionId=(Get-Process -Id $PID).SessionId
 activeConsoleSessionId=[EdbConsoleProbe]::WTSGetActiveConsoleSessionId()
 userInteractive=[Environment]::UserInteractive
 administratorRole=$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
 scope='Own process/session identity only; no screenshots, window enumeration, user application interaction or native workload'
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ResultPath -Encoding utf8
'@ | Set-Content -LiteralPath $probePath -Encoding utf8
$principalId=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$actionArgs='-NoProfile -NonInteractive -WindowStyle Hidden -File "'+$probePath+'" -ResultPath "'+$resultPath+'"'
$receipt=[ordered]@{schemaVersion=1;status='RUNNING';taskName=$name;createdAt=[DateTime]::UtcNow.ToString('o');principal=$principalId;requestedLogonType='Interactive';requestedRunLevel='Limited';action=@{execute='powershell.exe';arguments=$actionArgs};registrationSucceeded=$false;cleanupVerified=$false;error=$null}
$registered=$false
try {
 $action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $actionArgs -WorkingDirectory $dir
 $principal=New-ScheduledTaskPrincipal -UserId $principalId -LogonType Interactive -RunLevel Limited
 $settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
 $created=Register-ScheduledTask -TaskName $name -InputObject (New-ScheduledTask -Action $action -Principal $principal -Settings $settings)
 $registered=$true; $receipt.registrationSucceeded=$true
 $receipt.actualPrincipal=$created.Principal | Select-Object UserId,LogonType,RunLevel
 $receipt | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $receiptPath -Encoding utf8
 Start-ScheduledTask -TaskName $name
 $deadline=[DateTime]::UtcNow.AddSeconds(45)
 while (!(Test-Path -LiteralPath $resultPath) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 500 }
 if (!(Test-Path -LiteralPath $resultPath)) { throw 'Interactive probe produced no result within 45 seconds' }
 $result=Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json; $receipt.result=$result
 $deadline=[DateTime]::UtcNow.AddSeconds(10)
 while ((Get-ScheduledTask -TaskName $name).State -eq 'Running' -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 250 }
 $receipt.taskInfo=Get-ScheduledTaskInfo -TaskName $name | Select-Object LastRunTime,LastTaskResult,NumberOfMissedRuns
 if ($receipt.taskInfo.LastTaskResult -ne 0) { throw "Interactive task result was $($receipt.taskInfo.LastTaskResult)" }
 if ($result.sessionId -eq 0 -or $result.sessionId -ne $result.activeConsoleSessionId -or !$result.userInteractive -or $result.user -ne $principalId -or $result.administratorRole) { throw 'Probe did not prove the current user limited interactive console session' }
 $receipt.status='PASSED'
} catch { $receipt.status='BLOCKED'; $receipt.error=$_.Exception.Message }
finally {
 if ($registered) {
  try {
   $existing=Get-ScheduledTask -TaskName $name
   if ($existing.Actions.Count -ne 1 -or $existing.Actions[0].Arguments -ne $actionArgs) { throw 'Owned task identity changed; cleanup refused' }
   if ($existing.State -eq 'Running') { Stop-ScheduledTask -TaskName $name; $receipt.ownedTaskStopped=$true }
   Unregister-ScheduledTask -TaskName $name -Confirm:$false
   $receipt.cleanupVerified=($null -eq (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue))
  } catch { $receipt.cleanupError=$_.Exception.Message; $receipt.status='FAILED_CLEANUP' }
 } else { $receipt.cleanupVerified=($null -eq (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue)) }
 $receipt.finishedAt=[DateTime]::UtcNow.ToString('o')
 $receipt | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $receiptPath -Encoding utf8
}
$receipt | ConvertTo-Json -Depth 10
Write-Output ('RECEIPT_PATH='+$receiptPath)
