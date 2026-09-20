param([Parameter(Mandatory=$true)][string]$Root,[Parameter(Mandatory=$true)][string]$Label)
$ErrorActionPreference='Stop'
$receipt=[ordered]@{scope='PowerShell syntax and embedded C# compilation only; no GUI actions';powershellVersion=$PSVersionTable.PSVersion.ToString();files=@();csharpBlocks=0;status='RUNNING'}
$driver=Join-Path $Root ('gui-driver-'+$Label+'\test-windows-native-gui.ps1')
foreach ($file in @($driver,(Join-Path $Root 'windows-physical-gui-task.ps1'))) {
 $tokens=$null;$parseErrors=$null
 [void][Management.Automation.Language.Parser]::ParseFile($file,[ref]$tokens,[ref]$parseErrors)
 $receipt.files+=@{path=$file;sha256=(Get-FileHash -Algorithm SHA256 $file).Hash.ToLowerInvariant();errorCount=@($parseErrors).Count;errors=@($parseErrors | Select-Object Message,ErrorId)}
 if (@($parseErrors).Count) { throw 'PowerShell operator syntax did not parse' }
}
$text=Get-Content -LiteralPath $driver -Raw
$blocks=[Regex]::Matches($text,"Add-Type @'\r?\n(.*?)\r?\n'@",[Text.RegularExpressions.RegexOptions]::Singleline)
if ($blocks.Count -ne 1) { throw 'Expected exactly one reviewed C# helper block' }
foreach ($block in $blocks) { Add-Type -TypeDefinition $block.Groups[1].Value; $receipt.csharpBlocks++ }
$inputType=[EdbWindows].GetNestedType('Input',[Reflection.BindingFlags]::NonPublic)
if ($inputType) {
 $receipt.nativeInputSize=[Runtime.InteropServices.Marshal]::SizeOf([type]$inputType)
 $receipt.controllerPointerSize=[IntPtr]::Size
 if ($receipt.nativeInputSize -ne $(if ([IntPtr]::Size -eq 8) {40} else {28})) {throw 'Unexpected native INPUT layout'}
}
$captionPath=Join-Path (Split-Path -Parent $driver) 'windows-owned-caption.cs'
if (Test-Path -LiteralPath $captionPath) {
 Add-Type -Path $captionPath
 $captionType=[EdbOwnedCaption].GetNestedType('Input',[Reflection.BindingFlags]::NonPublic)
 $receipt.captionInputSize=[Runtime.InteropServices.Marshal]::SizeOf([type]$captionType)
 $receipt.captionHelperSha256=(Get-FileHash -LiteralPath $captionPath -Algorithm SHA256).Hash.ToLowerInvariant()
 if ($receipt.captionInputSize -ne $(if ([IntPtr]::Size -eq 8) {40} else {28})) {throw 'Unexpected native mouse INPUT layout'}
}
$receipt.status='PASSED'
$receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $Root ('gui-operator-parse-'+$Label+'.json')) -Encoding utf8
$receipt | ConvertTo-Json -Depth 6
