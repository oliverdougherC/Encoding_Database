# Native packaged GUI verification only. Never clicks Start or launches measurement.
# Reuses repository-owned Win32 ownership, dynamic control observation and click guards.
param([Parameter(Mandatory=$true)][string]$Root,
      [Parameter(Mandatory=$true)][string]$RunLabel,
      [Parameter(Mandatory=$true)][string]$Nonce,
      [Parameter(Mandatory=$true)][string]$Scenario)
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$request=Get-Content (Join-Path $Scenario 'gui-request.json') -Raw | ConvertFrom-Json
$result=[ordered]@{name=$request.action;passed=$false;events=@();realBackend=$false;newAttemptRecords=0}
$id=[Security.Principal.WindowsIdentity]::GetCurrent()
$identity=@{nonce=$Nonce;pid=$PID;session=(Get-Process -Id $PID).SessionId;sid=$id.User.Value;admin=([Security.Principal.WindowsPrincipal]::new($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)}
$ack=Join-Path $Root ('desktop-launch-'+$RunLabel+'\session1-ack.json')
$identity|ConvertTo-Json|Set-Content $ack -Encoding UTF8
$result.identity=$identity
$script:owned=@{};$process=$null
function Save-Result { $result | ConvertTo-Json -Depth 12 | Set-Content $request.result -Encoding UTF8 }
function Record-Event([string]$name,$data){$result.events+=@{kind=$name;at=[DateTime]::UtcNow.ToString('o');data=$data}}
function Wait-Until([scriptblock]$condition,[int]$seconds,[string]$failure){
 $until=[DateTime]::UtcNow.AddSeconds($seconds)
 do {if(&$condition){return};Start-Sleep -Milliseconds 250}while([DateTime]::UtcNow -lt $until)
 throw $failure
}
function Get-OwnedProcesses {
 $all=@(Get-CimInstance Win32_Process);$by=@{};foreach($p in $all){$by[[string]$p.ProcessId]=$p}
 do{$added=$false;foreach($p in $all){$k=[string]$p.ProcessId;$parent=[string]$p.ParentProcessId
 if(!$script:owned.ContainsKey($k) -and $script:owned.ContainsKey($parent) -and $by.ContainsKey($parent) -and $by[$parent].CreationDate -eq $script:owned[$parent].CreationDate -and $p.CreationDate -ge $by[$parent].CreationDate){$script:owned[$k]=$p;$added=$true}}}while($added)
 @($all|Where-Object{$script:owned.ContainsKey([string]$_.ProcessId) -and $_.CreationDate -eq $script:owned[[string]$_.ProcessId].CreationDate})
}
function Get-OwnedWindows {
 $alive=@(Get-OwnedProcesses)
 @([EdbWindows]::Windows([IntPtr]::Zero)|Where-Object{[uint32]$o=0;[void][EdbWindows]::GetWindowThreadProcessId($_,[ref]$o);$o -in @($alive.ProcessId) -and [EdbWindows]::IsWindowVisible($_)})
}
function Focus-Owned($tree){
 for($i=0;$i -lt 30;$i++){
  [void][EdbWindows]::ShowWindow($tree.handle,9);[void][EdbWindows]::SetForegroundWindow($tree.handle)
  if([EdbWindows]::GetForegroundWindow() -eq $tree.handle){return}
  $click=[EdbOwnedCaption]::ClickOnce($tree.handle,$tree.owner)
  Start-Sleep -Milliseconds 500
 }
 throw 'Owned GUI could not acquire foreground; no control click sent'
}
function Click-Retry {
 $tree=Get-OwnedClientTree;Focus-Owned $tree
 $obs=Get-ObservedRetryControl 'Retry'
 $click=[EdbWindows]::SendOwnedControlClick($obs.handle,$obs.owner,[IntPtr]$obs.child,$obs.x,$obs.y,$obs.rootBounds.left,$obs.rootBounds.top,$obs.rootBounds.right,$obs.rootBounds.bottom)
 Record-Event 'retry-click' $click
 if($click.Error){throw ('Retry refused: '+$click.Error)}
}
try {
 if($identity.session -ne 1 -or $identity.admin){throw 'Ordinary active-console session1 required'}
 if((Get-FileHash $request.package -Algorithm SHA256).Hash.ToLowerInvariant() -ne $request.packageSha256){throw 'Package hash mismatch'}
 # Parse ONLY the reviewed repository helper type/functions; never execute its benchmark workflow.
 $helper=Join-Path $Root 'test-windows-native-gui.ps1';$source=Get-Content $helper -Raw
 $block=[regex]::Match($source,"(?s)Add-Type @'\r?\n(.*?)\r?\n'@")
 if(!$block.Success){throw 'Reviewed native helper type missing'}
 Add-Type -AssemblyName System.Windows.Forms,System.Drawing,UIAutomationClient,UIAutomationTypes
 Add-Type -TypeDefinition $block.Groups[1].Value
 Add-Type -Path (Join-Path $Root 'windows-owned-caption.cs')
 $tokens=$null;$parseErrors=$null;$ast=[Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$parseErrors)
 foreach($name in @('Get-OwnedClientTree','Get-ObservedRunControl','Get-OwnedExitConfirmation')){
  $node=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
  if($null -eq $node){throw ('Reviewed helper missing: '+$name)}
  $text=$node.Extent.Text
  if($name -eq 'Get-ObservedRunControl'){
   $text=$text.Replace('Get-ObservedRunControl','Get-ObservedRetryControl').Replace("'Start','Stop'","'Retry','Stop'").Replace("if (`$Action -eq 'Start') { `$rows[0].first }","if (`$Action -eq 'Retry') { `$rows[0].third }")
  }
  Invoke-Expression $text
 }
 New-Item -ItemType Directory -Force $request.state|Out-Null
 [IO.File]::WriteAllText((Join-Path $request.state 'publication-consent.json'),'{"version":1,"acceptedAt":1791177297,"scope":"benchmark-publication"}',[Text.UTF8Encoding]::new($false))
 $env:ENCODINGDB_STATE_DIR=$request.state
 $info=[Diagnostics.ProcessStartInfo]::new();$info.FileName=$request.package;$info.Arguments='--gui --base-url '+$request.baseUrl+' --queue-dir "'+$request.queue+'"';$info.UseShellExecute=$false;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
 $process=[Diagnostics.Process]::new();$process.StartInfo=$info;[void]$process.Start()
 $stdout=$process.StandardOutput.ReadToEndAsync();$stderr=$process.StandardError.ReadToEndAsync()
 $script:owned[[string]$process.Id]=Get-CimInstance Win32_Process -Filter ('ProcessId='+$process.Id)
 Wait-Until {@(Get-OwnedWindows|Where-Object{[EdbWindows]::Text($_) -eq 'EncodingDB Windows Client'}).Count -eq 1} 35 'Packaged GUI window absent'
 Record-Event 'gui-launched' @{pid=$process.Id;packageSha256=$request.packageSha256}
 Click-Retry
 if($request.cancel){
  Wait-Until {Test-Path (Join-Path $Scenario 'barrier.json')} 15 'Retry did not reach requested network phase'
  $barrier=Get-Content (Join-Path $Scenario 'barrier.json') -Raw|ConvertFrom-Json
  if($barrier.phase -ne $request.phase){throw 'Foreign network barrier'}
  $tree=Get-OwnedClientTree;Focus-Owned $tree
  $stop=[EdbWindows]::SendOwnedShortcut($tree.handle,$tree.owner,[uint16]0x53)
  Record-Event 'stop-at-network-barrier' @{phase=$barrier.phase;shortcut=$stop}
  if($stop.Error){throw ('Stop shortcut refused: '+$stop.Error)}
  Start-Sleep -Seconds 3
  if(!(Test-Path (Join-Path $request.queue ($request.localHash+'.json')))){throw 'Pending evidence vanished before acknowledgment'}
 }else{
  Wait-Until {Test-Path (Join-Path $request.queue ('receipts\'+$request.localHash+'.json'))} 25 'GUI Retry did not write receipt'
 }
 $tree=Get-OwnedClientTree
 [void][EdbWindows]::PostMessage($tree.handle,0x0010,[IntPtr]::Zero,[IntPtr]::Zero)
 Start-Sleep -Milliseconds 500
 $confirmation=Get-OwnedExitConfirmation
 if($null -ne $confirmation){
  [UIntPtr]$sent=[UIntPtr]::Zero
  if([EdbWindows]::SendMessageTimeout($confirmation.button,0x00F5,[IntPtr]::Zero,[IntPtr]::Zero,2,2000,[ref]$sent) -eq [IntPtr]::Zero){throw 'Exit confirmation failed'}
  Record-Event 'owned-exit-confirmation' @{}
 }
 Wait-Until {@(Get-OwnedProcesses).Count -eq 0} 20 'GUI process tree did not stop after Close'
 $process.WaitForExit();$result.exitCode=$process.ExitCode
 [IO.File]::WriteAllText((Join-Path $Scenario ($request.action+'-gui.stdout')),$stdout.Result)
 [IO.File]::WriteAllText((Join-Path $Scenario ($request.action+'-gui.stderr')),$stderr.Result)
 $result.newAttemptRecords=@(Get-ChildItem $request.queue -Recurse -Filter 'attempt-*.json').Count
 if($result.newAttemptRecords -ne 0){throw 'Unexpected measurement records'}
 if($result.exitCode -ne 0){throw 'GUI exit was not clean'}
 $result.passed=$true
}catch{$result.error=$_.Exception.Message}
finally{
 if($process -and !$process.HasExited){$result.forcedCleanup=$true;taskkill /PID $process.Id /T /F|Out-Null}
 Save-Result
}
