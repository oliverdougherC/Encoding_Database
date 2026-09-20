# Physical candidate build at the reviewed source; all dependencies stay local.
param([Parameter(Mandatory=$true)][string]$Root)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$revision='939823ead2c052572f9deb5c9f91c85435d5661d'
$source=Join-Path $Root 'source-939823e'
$runtime=Join-Path $Root 'runtime-939823e'
$bootstrap=Join-Path $Root 'bootstrap-venv-939823e'
$receiptPath=Join-Path $Root 'physical-build-receipt.json'
if ((Test-Path $source) -or (Test-Path $runtime) -or (Test-Path $bootstrap) -or (Test-Path $receiptPath)) { throw 'Create-only physical build already exists' }
$receipt=[ordered]@{schemaVersion=1;status='RUNNING';kind='physical-built-candidate-distinct-from-CI';requestedSource=$revision;startedAt=[DateTime]::UtcNow.ToString('o');step='initializing';events=@();error=$null}
function Step([string]$Value) {
 $receipt.step=$Value; $receipt.events+=@{step=$Value;at=[DateTime]::UtcNow.ToString('o')}
 $receipt | ConvertTo-Json -Depth 12 | Set-Content $receiptPath -Encoding utf8
 Write-Host ("PHYSICAL_BUILD_STEP="+$Value)
}
function Check([string]$Description) { if ($LASTEXITCODE -ne 0) { throw ($Description+' failed with exit '+$LASTEXITCODE) } }
Start-Transcript -Path (Join-Path $Root 'physical-build-transcript.log') -NoClobber
try {
 Step 'fetch-exact-public-source'
 git init $source; Check 'git init'
 git -C $source config core.autocrlf false; Check 'git core.autocrlf'
 git -C $source remote add origin https://github.com/oliverdougherC/Encoding_Database.git; Check 'git remote'
 git -C $source fetch --depth 1 origin $revision; Check 'git fetch'
 git -C $source checkout --detach FETCH_HEAD; Check 'git checkout'
 $actual=(& git -C $source rev-parse HEAD).Trim(); Check 'git revision'
 if ($actual -ne $revision) { throw 'Source checkout revision mismatch' }
 $receipt.actualSource=$actual; $receipt.sourceTree=(& git -C $source rev-parse 'HEAD^{tree}').Trim()
 Step 'provision-reviewed-runtime'
 New-Item -ItemType Directory $runtime | Out-Null
 $archive=Join-Path $runtime 'ffmpeg-win.zip'
 $url='https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-09-09-14-51/ffmpeg-n8.1.2-51-g7ba069f4f1-win64-gpl-8.1.zip'
 curl.exe --fail --location --silent --show-error --retry 2 --connect-timeout 20 --max-time 900 --output $archive $url; Check 'runtime download'
 $hash=(Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
 if ($hash -ne '4e40699fa864811312d6c1895ea4873beaf8475e1188563fee57fac860554601') { throw 'Runtime archive hash mismatch' }
 $receipt.runtimeArchive=@{url=$url;sha256=$hash;bytes=(Get-Item $archive).Length}
 Expand-Archive -LiteralPath $archive -DestinationPath $runtime
 $bundles=@(Get-ChildItem $runtime -Directory | Where-Object Name -like 'ffmpeg-*')
 if ($bundles.Count -ne 1) { throw 'Expected exactly one runtime bundle' }
 $env:ENCODINGDB_FFMPEG_PATH=Join-Path $bundles[0].FullName 'bin\ffmpeg.exe'
 $env:ENCODINGDB_FFPROBE_PATH=Join-Path $bundles[0].FullName 'bin\ffprobe.exe'
 $env:FFMPEG_EXE=$env:ENCODINGDB_FFMPEG_PATH; $env:FFPROBE_EXE=$env:ENCODINGDB_FFPROBE_PATH
 $env:ENCODINGDB_STATE_DIR=Join-Path $Root 'host-state'
 $env:ENCODINGDB_SUITE_CACHE_DIR=Join-Path $Root 'suite-cache'
 foreach ($key in @('ENCODINGDB_BUILD_ONLY','ENCODINGDB_REGISTER_RUNTIME','ENCODINGDB_RUNTIME_LOCK_PATH','ENCODINGDB_SUITE_PACK_URL','ENCODINGDB_QUICK_CLIP_ID','PYTHONPATH','PYTHONHOME','PAUSE_ON_EXIT')) { Remove-Item ('Env:\'+$key) -ErrorAction SilentlyContinue }
 Step 'isolated-declared-bootstrap-dependencies'
 python -m venv $bootstrap; Check 'bootstrap venv'
 $python=Join-Path $bootstrap 'Scripts\python.exe'
 & $python -m pip install --disable-pip-version-check requests==2.33.0 psutil==7.2.2; Check 'declared bootstrap dependencies'
 $env:PATH=(Join-Path $bootstrap 'Scripts')+';'+$env:PATH
 Set-Location $source
 Step 'materialize-frozen-canonical-suite'
 & $python scripts/materialize_final_suite.py --cache-dir $env:ENCODINGDB_SUITE_CACHE_DIR; Check 'frozen suite materialization'
 Step 'execute-pinned-model'
 & $python scripts/verify_runtime_model.py; Check 'pinned model execution'
 Step 'unmodified-native-build-and-embedded-smoke'
 & (Join-Path $source 'scripts\build_windows_client.ps1')
 if ($LASTEXITCODE -ne 0) { throw ('Native build exit '+$LASTEXITCODE) }
 $tracked=(& git status --porcelain --untracked-files=no) -join "`n"; Check 'final tracked status'
 if ($tracked) { throw 'Tracked source changed during native build' }
 $receipt.artifacts=@(Get-ChildItem $source -Filter 'encodingdb-client-windows*' -File | ForEach-Object { @{name=$_.Name;bytes=$_.Length;sha256=(Get-FileHash -Algorithm SHA256 $_.FullName).Hash.ToLowerInvariant()} })
 $receipt.status='BUILT_PENDING_INDEPENDENT_PINS_AND_ACCEPTANCE'
 Step 'build-complete'
} catch { $receipt.status='FAILED'; $receipt.error=$_.Exception.Message; Write-Host ('PHYSICAL_BUILD_ERROR='+$receipt.error) }
finally {
 $receipt.finishedAt=[DateTime]::UtcNow.ToString('o')
 $receipt | ConvertTo-Json -Depth 12 | Set-Content $receiptPath -Encoding utf8
 Stop-Transcript
}
if ($receipt.status -ne 'BUILT_PENDING_INDEPENDENT_PINS_AND_ACCEPTANCE') { exit 1 }
