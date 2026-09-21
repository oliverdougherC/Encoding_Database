# Coordinated Windows upload replay per operations/windows-upload-ready.json.
# Upload-only ledger replay of retained FINISHED canonical campaigns against the real candidate
# server over a loopback reverse tunnel. Never re-encodes; campaign bytes must stay identical.
param(
 [Parameter(Mandatory=$true)][string]$Root,
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-z0-9-]{1,40}$')][string]$Label,
 [Parameter(Mandatory=$true)][string]$CaBundlePath,
 [string]$ChainEndpoint = '100.96.210.77:3299',
 [string]$ReceiptSuffix = ''
)
$ErrorActionPreference='Stop'
$receiptPath=Join-Path $Root ('gui-upload-replay-'+$Label+$ReceiptSuffix+'-receipt.json')
if (Test-Path -LiteralPath $receiptPath) { throw 'Create-only upload replay receipt already exists' }
$source=Join-Path $Root ('source-'+$Label)
$exe=Join-Path $source 'encodingdb-client-windows-console.exe'
$exeSha=(Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
$alloc=[IO.File]::Open((Join-Path $Root 'host-state\physical-operator.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
$receipt=[ordered]@{schemaVersion=1;status='RUNNING';startedAt=[DateTime]::UtcNow.ToString('o');executableSha256=$exeSha;caBundleSha256=(Get-FileHash -LiteralPath $CaBundlePath -Algorithm SHA256).Hash.ToLowerInvariant();baseUrl='https://127.0.0.1:3199';proxyMode='none';campaigns=@();tunnel=$null;error=$null}
function Save-Receipt { $receipt | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $receiptPath -Encoding utf8 }
Save-Receipt
try {
 # Chain: P910:3094 -> Mac:3299 (Mac-side ssh forward, must already be up) -> Windows 127.0.0.1:3199.
 # Reuse a healthy local 3199 listener; otherwise own a loopback relay process for this run.
 $existing=[System.Net.Sockets.TcpClient]::new(); $haveListener=$false
 try { $existing.Connect('127.0.0.1',3199); $haveListener=$true } catch { } finally { $existing.Dispose() }
 if ($haveListener) {
  $receipt.tunnel=@{reused=$true}
 } else {
  $chain=$ChainEndpoint.Split(':')
  $tunnel=Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'windows-physical-tcp-relay.ps1'),'-RemoteHost',$chain[0],'-RemotePort',[int]$chain[1]) -PassThru -WindowStyle Hidden
  $receipt.tunnel=@{pid=$tunnel.Id;chain=$ChainEndpoint}
  Start-Sleep -Seconds 2
  if ($tunnel.HasExited) { throw ('Relay exited early with '+$tunnel.ExitCode) }
 }
 Save-Receipt
 $compat=$null
 for ($try=0; $try -lt 10 -and -not $compat; $try++) {
  $raw=curl.exe --silent --show-error --cacert $CaBundlePath --max-time 8 https://127.0.0.1:3199/v7/compatibility 2>$null
  if ($raw) { try { $compat=$raw | ConvertFrom-Json } catch { Start-Sleep -Seconds 2 } } else { Start-Sleep -Seconds 2 }
 }
 if (-not $compat -or $compat.protocolVersion -ne '7.1') { throw 'Compatibility probe did not return protocolVersion 7.1 before upload' }
 $receipt.compatibility=$compat
 Save-Receipt
 $campaigns=@(
  @{ recipe='x264-crf23'; queue=(Join-Path $Root ('acceptance-x264-crf23-'+$Label+'-'+[char]0x00E9+'\queue-'+[char]0x5BA2+[char]0x6237)); campaignId='campaign-48cfe70dd43b036c' },
  @{ recipe='nvenc-cq24'; queue=(Join-Path $Root ('acceptance-nvenc-cq24-'+$Label+'-'+[char]0x00E9+'\queue-'+[char]0x5BA2+[char]0x6237)); campaignId='campaign-ade93ae84fc38765' },
  @{ recipe='nvenc-vbr6000'; queue=(Join-Path $Root ('acceptance-nvenc-vbr6000-'+$Label+'-'+[char]0x00E9+'\queue-'+[char]0x5BA2+[char]0x6237)); campaignId='campaign-fb607b76eec675bf' }
 )
 $replayState=Join-Path $Root ('upload-replay-state-'+$Label)
 New-Item -ItemType Directory -Force -Path (Join-Path $replayState 'tmp') | Out-Null
 foreach ($entry in $campaigns) {
  $campaignDir=Join-Path $entry.queue ('campaigns\'+$entry.campaignId)
  if (-not (Test-Path -LiteralPath (Join-Path $campaignDir 'campaign-complete.json'))) { throw ('Campaign not complete before upload: '+$entry.campaignId) }
  $before=@(Get-ChildItem -LiteralPath $campaignDir -Recurse -File | ForEach-Object { @{ path=$_.FullName.Substring($campaignDir.Length); sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() } })
  $terminalBefore=@(Get-ChildItem -LiteralPath (Join-Path $entry.queue 'terminal') -File -ErrorAction SilentlyContinue).Count
  $env:REQUESTS_CA_BUNDLE=$CaBundlePath
  $env:CURL_CA_BUNDLE=$CaBundlePath
  $env:ENCODINGDB_STATE_DIR=(Join-Path $Root 'host-state')
  $env:ENCODINGDB_SUITE_PACK_PATH=(Join-Path $source 'encodingdb-test-suite-v1.tar.gz')
  $env:TEMP=(Join-Path $replayState 'tmp'); $env:TMP=$env:TEMP
  $env:PYTHONUNBUFFERED='1'
  $stdoutFile=Join-Path $Root ('gui-upload-'+$entry.recipe+'.stdout.log')
  $stderrFile=Join-Path $Root ('gui-upload-'+$entry.recipe+'.stderr.log')
  function Count-Due($q){ @(Get-ChildItem -LiteralPath $q -File | Where-Object { $_.Name -match '^[0-9a-f]{64}\.json$' } | Where-Object { ((Get-Content -LiteralPath $_.FullName -Raw) | ConvertFrom-Json).PSObject.Properties.Name -contains 'attempts' }).Count }
  $dueBefore=Count-Due $entry.queue
  $proc=Start-Process -FilePath $exe -ArgumentList @('--cli','--upload-only','--resume-campaign',$entry.campaignId,'--submit','--queue-dir',$entry.queue,'--base-url',$receipt.baseUrl,'--max-storage-mb','2048') -NoNewWindow -PassThru -RedirectStandardOutput $stdoutFile -RedirectStandardError $stderrFile
  if (-not $proc.WaitForExit(900000)) { $proc.Kill(); throw ('Upload exceeded 15 minutes: '+$entry.campaignId) }
  $proc.WaitForExit()
  $exitCode= try { [int]$proc.ExitCode } catch { -1 }
  $after=@(Get-ChildItem -LiteralPath $campaignDir -Recurse -File | ForEach-Object { @{ path=$_.FullName.Substring($campaignDir.Length); sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() } })
  $afterBy=@{};foreach($i in $after){$afterBy[$i.path]=$i.sha256}
  $changed=@($before | Where-Object { -not $afterBy.ContainsKey($_.path) -or $afterBy[$_.path] -ne $_.sha256 })
  if ($changed.Count) { throw ('Upload mutated sealed campaign bytes: '+$entry.campaignId) }
  $dueAfter=Count-Due $entry.queue
  $terminal=@(Get-ChildItem -LiteralPath (Join-Path $entry.queue 'terminal') -File -ErrorAction SilentlyContinue)
  $receipt.campaigns+=@{ recipe=$entry.recipe; campaignId=$entry.campaignId; exitCode=$exitCode; campaignFilesUnchanged=$true; dueUploadsBefore=$dueBefore; dueUploadsAfter=$dueAfter; terminalBefore=$terminalBefore; terminalAfter=$terminal.Count; stdout=(Split-Path -Leaf $stdoutFile); stderrTail=@(Get-Content -LiteralPath $stderrFile -Tail 4 -ErrorAction SilentlyContinue) }
  Save-Receipt
 }
 $deferrals=@($receipt.campaigns | Where-Object { $_.exitCode -ne 0 -or $_.dueUploadsAfter -ne 0 })
 if ($deferrals.Count) { throw ('Upload did not fully drain: '+((($deferrals | ForEach-Object { $_.recipe+' exit='+$_.exitCode+' due='+$_.dueUploadsAfter }) -join '; '))) }
 $receipt.status='PASSED'
} catch { $receipt.status='FAILED'; $receipt.error=$_.Exception.Message } finally {
 if ($tunnel -and -not $tunnel.HasExited) { $tunnel.Kill() }
 $alloc.Dispose()
 $receipt.finishedAt=[DateTime]::UtcNow.ToString('o'); Save-Receipt
}
if ($receipt.status -ne 'PASSED') { exit 1 }
'UPLOAD-REPLAY-PASSED'
