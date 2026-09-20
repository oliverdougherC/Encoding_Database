# Physical Windows interruption/resume evidence: continue a GUI Stop interrupted durable
# campaign through the packaged console binary's documented --resume-campaign path.
# The frozen GUI exposes no resume control; that client limitation is recorded truthfully.
param(
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-z0-9-]{1,40}$')][string]$Label,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-z0-9-]{1,40}$')][string]$RunLabel,
    [Parameter(Mandatory=$true)][string]$QueuePath,
    [Parameter(Mandatory=$true)][ValidatePattern('^campaign-[0-9a-f]{16}$')][string]$CampaignId
)
$ErrorActionPreference='Stop'
$rootPath=Join-Path $Root ('source-'+$Label)
$receiptPath=Join-Path $Root ('gui-resume-'+$RunLabel+'-receipt.json')
if (Test-Path -LiteralPath $receiptPath) { throw 'Create-only GUI resume receipt already exists' }
if (-not (Test-Path -LiteralPath $QueuePath)) { throw 'Interrupted queue directory is missing' }
$campaignPath=Join-Path $QueuePath ('campaigns\'+$CampaignId)
if (-not (Test-Path -LiteralPath $campaignPath)) { throw 'Interrupted campaign directory is missing' }
if (Test-Path -LiteralPath (Join-Path $campaignPath 'campaign-complete.json')) { throw 'Campaign already completed before resume; cancellation evidence invalid' }
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$admin=([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($admin) { throw 'Resume must run non-elevated like the interrupted GUI phase' }
$receipt=[ordered]@{schemaVersion=1;status='RUNNING';startedAt=[DateTime]::UtcNow.ToString('o');scope='GUI Stop interruption resumed by packaged console binary --resume-campaign; GUI exposes no resume control';root=$Root;label=$Label;queuePath=$QueuePath;campaignId=$CampaignId;forcedCleanup=$false;error=$null}
function Save-Receipt { $receipt | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $receiptPath -Encoding utf8 }
Save-Receipt
function Snapshot-Campaign([string]$path) {
    return @(Get-ChildItem -LiteralPath $path -Recurse -File | ForEach-Object {
        @{ path=$_.FullName.Substring($path.Length); bytes=$_.Length; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    })
}
$allocation=$null
try {
    $allocation=[IO.File]::Open((Join-Path $Root 'host-state\physical-operator.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    $pins=Get-Content -LiteralPath (Join-Path $Root ('physical-candidate-pins-'+$Label+'.json')) -Raw | ConvertFrom-Json
    foreach ($entry in $pins.files.PSObject.Properties) {
        $file=Join-Path $rootPath $entry.Name
        if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value) { throw ('Pinned payload differs: '+$entry.Name) }
    }
    if ((Get-Content -LiteralPath (Join-Path $Root 'host-state\physical-source-id') -Raw).Trim() -ne 'installation-9e7cd0a8c6158d19d179f0acf79249c6c790b988b8a48f6563952c1c00acca29') { throw 'Physical identity changed' }
    $before=Snapshot-Campaign $campaignPath
    $attemptFiles=@($before | Where-Object { $_.path -like '*attempt-*.json' })
    if ($attemptFiles.Count -eq 0) { throw 'Interrupted campaign contains no retained attempts; nothing to resume' }
    $receipt.before=@{ files=$before.Count; attempts=$attemptFiles.Count; snapshot=$before }
    Save-Receipt

    $state=Join-Path $Root ('gui-resume-state-'+$RunLabel)
    New-Item -ItemType Directory -Path $state | Out-Null
    New-Item -ItemType Directory -Force (Join-Path $state 'tmp') | Out-Null
    $exe=Join-Path $rootPath 'encodingdb-client-windows-console.exe'
    $arguments=@('--cli','--resume-campaign',$CampaignId,'--no-submit','--base-url','http://127.0.0.1:9','--queue-dir',$QueuePath,'--max-duration-minutes','20','--max-storage-mb','3072')
    $quoted=@($arguments | ForEach-Object {
        $escaped=[Regex]::Replace([string]$_,'(\\*)"','$1$1\"')
        '"'+[Regex]::Replace($escaped,'(\\+)$','$1$1')+'"'
    })
    $info=[Diagnostics.ProcessStartInfo]::new($exe)
    $info.UseShellExecute=$false;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true;$info.WorkingDirectory=$state
    foreach ($key in @($info.EnvironmentVariables.Keys)) {
        if ($key -match '^(FFMPEG_EXE|FFPROBE_EXE|ENCODINGDB_(FFMPEG_PATH|FFPROBE_PATH|RUNTIME_.*|QUICK_CLIP_ID|SUITE_PACK_URL|SUITE_CACHE_DIR|STATE_DIR)|TCL_LIBRARY|TK_LIBRARY|PYTHONPATH|PYTHONHOME|LD_LIBRARY_PATH|DYLD_.*|V7_OPERATOR_.*)$') { [void]$info.EnvironmentVariables.Remove($key) }
    }
    $info.EnvironmentVariables['ENCODINGDB_RUNTIME_EVIDENCE_PATH']=Join-Path $state 'embedded-runtime.json'
    $info.EnvironmentVariables['ENCODINGDB_SUITE_CACHE_DIR']=Join-Path $state 'suite-cache'
    $info.EnvironmentVariables['ENCODINGDB_SUITE_PACK_PATH']=Join-Path $rootPath 'encodingdb-test-suite-v1.tar.gz'
    $info.EnvironmentVariables['ENCODINGDB_STATE_DIR']=Join-Path $Root 'host-state'
    $info.EnvironmentVariables['LOCALAPPDATA']=Join-Path $state 'localappdata'
    $info.EnvironmentVariables['TEMP']=Join-Path $state 'tmp';$info.EnvironmentVariables['TMP']=Join-Path $state 'tmp'
    $info.Arguments=[string]::Join(' ',$quoted)
    $receipt.command=@($exe)+$arguments
    $receipt.executableSha256=(Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
    Save-Receipt
    $process=[Diagnostics.Process]::new();$process.StartInfo=$info
    [void]$process.Start()
    $stdoutTask=$process.StandardOutput.ReadToEndAsync();$stderrTask=$process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit(1500000)) {
        $receipt.forcedCleanup=$true
        $process.Kill();$process.WaitForExit(30000)
        throw 'Resume exceeded its 25-minute bound; forced cleanup is failure'
    }
    $receipt.exitCode=$process.ExitCode
    $stdoutTask.GetAwaiter().GetResult() | Set-Content -LiteralPath (Join-Path $Root ('gui-resume-'+$RunLabel+'.stdout.log'))
    $stderrTask.GetAwaiter().GetResult() | Set-Content -LiteralPath (Join-Path $Root ('gui-resume-'+$RunLabel+'.stderr.log'))
    if ($process.ExitCode -ne 0) { throw ('Packaged console resume returned '+$process.ExitCode) }

    $marker=Join-Path $campaignPath 'campaign-complete.json'
    if (-not (Test-Path -LiteralPath $marker)) { throw 'Resumed campaign did not produce its completion marker' }
    $completion=Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
    if ($completion.failed -ne 0 -or $completion.skipped -ne 0) { throw 'Completed campaign contains failed or skipped work' }
    $after=Snapshot-Campaign $campaignPath
    $afterByPath=@{};foreach($item in $after){$afterByPath[$item.path]=$item}
    $changed=@($before | Where-Object { -not $afterByPath.ContainsKey($_.path) -or $afterByPath[$_.path].sha256 -ne $_.sha256 })
    if ($changed.Count) { throw 'Resume modified retained pre-interruption bytes' }
    $attemptRecords=@($after | Where-Object { $_.path -like '*attempt-*.json' })
    $measuredByRecipe=@{};$warmed=@{};$artifactFailures=0
    Get-ChildItem -LiteralPath $campaignPath -Filter 'attempt-*.json' | ForEach-Object {
        $attempt=Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
        if ($attempt.schedule.campaign_id -ne $CampaignId) { throw 'Attempt campaign identity changed' }
        if ($attempt.schedule.phase -eq 'warmup') { $warmed[$attempt.schedule.recipe_id]=$true }
        if ($attempt.schedule.phase -ne 'measured') { return }
        $timing=$attempt.timing
        if ($null -eq $timing -or $timing.elapsed_s -le 0) { throw ('Resumed measured attempt lacks timing: '+$attempt.schedule.execution_order) }
        if ($timing.encoded_frame_count -ne $timing.source_frame_count -or $timing.source_fps -ne 24) { throw 'Resumed measured attempt did not cover a full canonical clip' }
        $infoNode=$attempt.metadata.info
        $artifact=Get-Item -LiteralPath $infoNode.artifactPath -ErrorAction SilentlyContinue
        if (-not $artifact -or (Get-FileHash -LiteralPath $artifact.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne $infoNode.artifactSha256) { $artifactFailures++ }
        if (-not $measuredByRecipe.ContainsKey($attempt.schedule.recipe_id)) { $measuredByRecipe[$attempt.schedule.recipe_id]=0 }
        $measuredByRecipe[$attempt.schedule.recipe_id]++
    }
    if ($artifactFailures) { throw 'Resumed campaign artifacts failed byte verification' }
    if (@($measuredByRecipe.Keys).Count -eq 0) { throw 'Resumed campaign recorded no measured attempts' }
    foreach ($recipe in $measuredByRecipe.Keys) {
        if ($measuredByRecipe[$recipe] -lt 2 -or -not $warmed.ContainsKey($recipe)) { throw ('Resumed recipe lacks warmup or two measured attempts: '+$recipe) }
    }
    $survivors=@(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.ExecutablePath -and ($_.ExecutablePath -like ('*'+$Root+'*')) })
    if ($survivors.Count) { throw 'Resume left owned processes running' }
    $receipt.after=@{ files=$after.Count; attempts=$attemptRecords.Count; completed=$true; measuredByRecipe=$measuredByRecipe; retainedBytesUnchanged=$true }
    $receipt.newAttempts=$attemptRecords.Count-$attemptFiles.Count
    $receipt.status='PASSED'
} catch {
    $receipt.status='FAILED';$receipt.error=$_.Exception.Message
} finally {
    if ($allocation) { $allocation.Dispose() }
    $receipt.finishedAt=[DateTime]::UtcNow.ToString('o');Save-Receipt
}
if ($receipt.status -ne 'PASSED') { exit 1 }
