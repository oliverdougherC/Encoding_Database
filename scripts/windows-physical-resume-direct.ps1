# Limited-token task shim: runs the durable GUI-interrupt resume driver without elevation.
param(
 [Parameter(Mandatory=$true)][string]$Root,
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-z0-9-]{1,40}$')][string]$Label,
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-z0-9-]{1,40}$')][string]$RunLabel,
 [Parameter(Mandatory=$true)][string]$QueuePath,
 [Parameter(Mandatory=$true)][ValidatePattern('^campaign-[0-9a-f]{16}$')][string]$CampaignId,
 [string]$SuiteCacheDir=''
)
$ErrorActionPreference='Stop'
& (Join-Path $Root 'windows-physical-gui-resume.ps1') -Root $Root -Label $Label -RunLabel $RunLabel -QueuePath $QueuePath -CampaignId $CampaignId -SuiteCacheDir $SuiteCacheDir
exit $LASTEXITCODE
