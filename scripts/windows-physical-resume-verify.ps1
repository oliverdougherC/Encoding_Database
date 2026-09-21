# Independent byte/journal verification of a GUI-interrupted campaign completed via --resume-campaign.
# Replays the resume driver's post-conditions without owning a new run: retained bytes must be
# unchanged against the pre-interruption snapshot recorded in the failed attempt's driver receipts,
# completion must be genuine, and every measured attempt must be a full canonical clip.
param(
 [Parameter(Mandatory=$true)][string]$Root,
 [Parameter(Mandatory=$true)][string]$RunLabel,
 [Parameter(Mandatory=$true)][string]$QueuePath,
 [Parameter(Mandatory=$true)][ValidatePattern('^campaign-[0-9a-f]{16}$')][string]$CampaignId,
 [Parameter(Mandatory=$true)][string]$SnapshotReceiptPath
)
$ErrorActionPreference='Stop'
$receiptPath=Join-Path $Root ('gui-resume-verify-'+$RunLabel+'-receipt.json')
if (Test-Path -LiteralPath $receiptPath) { throw 'Create-only verify receipt already exists' }
$receipt=[ordered]@{schemaVersion=1;status='RUNNING';startedAt=[DateTime]::UtcNow.ToString('o');queuePath=$QueuePath;campaignId=$CampaignId;snapshotFrom=$SnapshotReceiptPath;error=$null}
try {
 $campaign=Join-Path $QueuePath ('campaigns\'+$CampaignId)
 $snap=Get-Content -LiteralPath $SnapshotReceiptPath -Raw | ConvertFrom-Json
 if ($snap.status -notlike 'RUNNING*' -and $snap.before -eq $null) { throw 'Snapshot receipt has no before-snapshot' }
 $before=@($snap.before.snapshot)
 $marker=Join-Path $campaign 'campaign-complete.json'
 if (-not (Test-Path -LiteralPath $marker)) { throw 'campaign-complete.json missing' }
 $completion=Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
 if ($completion.failed -ne 0 -or $completion.skipped -ne 0) { throw 'Completion marker reports failed or skipped work' }
 $after=@(Get-ChildItem -LiteralPath $campaign -Recurse -File | ForEach-Object { @{ path=$_.FullName.Substring($campaign.Length); bytes=$_.Length; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() } })
 $afterByPath=@{};foreach($item in $after){$afterByPath[$item.path]=$item}
 $changed=@($before | Where-Object { -not $afterByPath.ContainsKey($_.path) -or $afterByPath[$_.path].sha256 -ne $_.sha256 })
 if ($changed.Count) { throw ('Resume modified retained pre-interruption bytes: '+ (($changed | ForEach-Object { $_.path }) -join ';')) }
 $measuredByRecipe=@{};$warmed=@{};$artifactFailures=0
 Get-ChildItem -LiteralPath $campaign -Filter 'attempt-*.json' | ForEach-Object {
  $attempt=Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
  if ($attempt.schedule.campaign_id -ne $CampaignId) { throw 'Attempt campaign identity changed' }
  if ($attempt.schedule.phase -eq 'warmup') { $warmed[$attempt.schedule.recipe_id]=$true }
  if ($attempt.schedule.phase -ne 'measured') { return }
  $timing=$attempt.timing
  if ($null -eq $timing -or $timing.elapsed_s -le 0) { throw ('Measured attempt lacks timing: '+$attempt.schedule.execution_order) }
  if ($timing.encoded_frame_count -ne $timing.source_frame_count -or $timing.source_fps -ne 24) { throw 'Measured attempt did not cover a full canonical clip' }
  $infoNode=$attempt.metadata.info
  $artifact=Get-Item -LiteralPath $infoNode.artifactPath -ErrorAction SilentlyContinue
  if (-not $artifact -or (Get-FileHash -LiteralPath $artifact.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne $infoNode.artifactSha256) { $artifactFailures++ }
  if (-not $measuredByRecipe.ContainsKey($attempt.schedule.recipe_id)) { $measuredByRecipe[$attempt.schedule.recipe_id]=0 }
  $measuredByRecipe[$attempt.schedule.recipe_id]++
 }
 if ($artifactFailures) { throw 'Artifact byte verification failed' }
 foreach ($recipe in $measuredByRecipe.Keys) {
  if ($measuredByRecipe[$recipe] -lt 2 -or -not $warmed.ContainsKey($recipe)) { throw ('Recipe lacks warmup or two measured attempts: '+$recipe) }
 }
 $survivors=@(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.ExecutablePath -and ($_.ExecutablePath -like ('*'+$Root+'*')) })
 if ($survivors.Count) { throw 'Owned processes still running' }
 $receipt.beforeAttempts=$snap.before.attempts
 $receipt.attempts=@($after | Where-Object { $_.path -like '*attempt-*.json' }).Count
 $receipt.measuredByRecipe=$measuredByRecipe
 $receipt.retainedBytesUnchanged=$true
 $receipt.status='PASSED'
} catch { $receipt.status='FAILED'; $receipt.error=$_.Exception.Message } finally {
 $receipt.finishedAt=[DateTime]::UtcNow.ToString('o')
 $receipt | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $receiptPath -Encoding utf8
}
if ($receipt.status -ne 'PASSED') { exit 1 }
'RESUME-VERIFY-PASSED'
