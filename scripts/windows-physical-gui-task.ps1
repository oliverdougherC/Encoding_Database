# Own one limited interactive task. Start and cleanup are explicit, bounded operations.
param(
 [Parameter(Mandatory=$true)][string]$Root,
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-z0-9-]{1,40}$')][string]$Label,
 [ValidatePattern('^[a-z0-9-]{1,40}$')][string]$RunLabel='',
 [switch]$Direct,
 [ValidateSet('Start','Cleanup')][string]$Action='Start'
)
$ErrorActionPreference='Stop'
if (!$RunLabel) { $RunLabel=$Label }
$receiptPath=Join-Path $Root ('gui-task-'+$RunLabel+'-receipt.json')
if ($Action -eq 'Cleanup') {
 $receipt=Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
 $task=Get-ScheduledTask -TaskName $receipt.taskName -ErrorAction Stop
 if ($task.Actions.Count -ne 1 -or $task.Actions[0].Arguments -ne $receipt.action.arguments -or $task.Actions[0].Execute -ne $receipt.action.execute) { throw 'Owned task identity changed; cleanup refused' }
 if ($task.State -eq 'Running') { throw 'Owned task is still running; cleanup refused until it finishes or its bounded deadline expires' }
 $info=Get-ScheduledTaskInfo -TaskName $receipt.taskName
 $receipt | Add-Member -NotePropertyName taskResult -NotePropertyValue $info.LastTaskResult -Force
 Unregister-ScheduledTask -TaskName $receipt.taskName -Confirm:$false
 $receipt | Add-Member -NotePropertyName cleanupVerified -NotePropertyValue ($null -eq (Get-ScheduledTask -TaskName $receipt.taskName -ErrorAction SilentlyContinue)) -Force
 $receipt | Add-Member -NotePropertyName cleanedAt -NotePropertyValue ([DateTime]::UtcNow.ToString('o')) -Force
 $receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding utf8
 $receipt | ConvertTo-Json -Depth 8
 exit 0
}
if (Test-Path -LiteralPath $receiptPath) { throw 'Create-only GUI task receipt already exists' }
$name='EncodingDB-PhysicalGUI-'+$RunLabel+'-'+[Guid]::NewGuid().ToString('N').Substring(0,8)
if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) { throw 'Create-only task collision' }
if ($Direct) {
 $execute='powershell.exe'
 $launcher=Join-Path $Root 'windows-physical-run-gui-direct.ps1'
 $arguments='-NoProfile -NonInteractive -WindowStyle Hidden -File "'+$launcher+'" -Root "'+$Root+'" -Label '+$Label+' -RunLabel '+$RunLabel
} else {
 $execute=Join-Path $Root ('source-'+$Label+'\.build\clients\windows\venv\Scripts\pythonw.exe')
 $launcher=Join-Path $Root 'windows-physical-run-gui.py'
 $arguments='"'+$launcher+'" --root "'+$Root+'" --label '+$Label+' --run-label '+$RunLabel
 if (!(Test-Path -LiteralPath $execute)) { throw 'Existing declared Python GUI launcher is missing; no install attempted' }
}
if (!(Test-Path -LiteralPath $launcher)) { throw 'Reviewed GUI operator launcher is missing' }
$identity=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$receipt=[ordered]@{schemaVersion=1;status='CREATING';createdAt=[DateTime]::UtcNow.ToString('o');taskName=$name;principal=$identity;requestedLogonType='Interactive';requestedRunLevel='Limited';action=@{execute=$execute;arguments=$arguments};launcherSha256=(Get-FileHash -Algorithm SHA256 $launcher).Hash.ToLowerInvariant();cleanupVerified=$false}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding utf8
$registered=$false
try {
 $taskAction=New-ScheduledTaskAction -Execute $execute -Argument $arguments -WorkingDirectory $Root
 $principal=New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
 $settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 35) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
 $created=Register-ScheduledTask -TaskName $name -InputObject (New-ScheduledTask -Action $taskAction -Principal $principal -Settings $settings)
 $registered=$true
 $receipt.actualPrincipal=$created.Principal | Select-Object UserId,LogonType,RunLevel
 Start-ScheduledTask -TaskName $name
 $receipt.status='STARTED'
} catch {
 $receipt.status='FAILED_START';$receipt.error=$_.Exception.Message
 if ($registered) {
  $existing=Get-ScheduledTask -TaskName $name
  if ($existing.Actions.Count -eq 1 -and $existing.Actions[0].Arguments -eq $arguments -and $existing.State -ne 'Running') {
   Unregister-ScheduledTask -TaskName $name -Confirm:$false
   $receipt.cleanupVerified=($null -eq (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue))
  }
 }
 throw
} finally { $receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding utf8 }
$receipt | ConvertTo-Json -Depth 8
