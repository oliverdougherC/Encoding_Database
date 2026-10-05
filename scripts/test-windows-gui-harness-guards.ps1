# Pure operator tests: parse the real functions and provide synthetic native observations.
# No user32 calls, windows, input, screenshots, process inventory, or client execution:
# the harness is only parsed (top-level code never runs); every native API the extracted
# functions touch resolves to the stub EdbWindows class below; Observe-Processes is always
# called while the synthetic process probe is installed.
param([string]$Harness=(Join-Path $PSScriptRoot 'test-windows-native-gui.ps1'))
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$tokens=$null; $parseErrors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Harness,[ref]$tokens,[ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
foreach ($name in @('Get-OwnedExitConfirmation','Get-OwnedDownloadEstimateConfirmation','Confirm-ObservedDownloadEstimate','Record-CleanupFailure','Get-OwnedClientTree','Get-ObservedRunControl','Get-ObservedModeControl','Set-OwnedForeground','Select-AdvancedSingleMode','Invoke-RunAction','Wait-Until','Observe-Processes','Get-CompletionMarkers','Wait-Encoder','Wait-NoEncoders','Get-ActiveEncodeEvidence','Get-DurableMeasuredAttempts','Wait-MeasuredThenActiveEncode')) {
    $definitions=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true))
    if ($definitions.Count -ne 1) { throw "Expected one real $name definition." }
    Invoke-Expression $definitions[0].Extent.Text
}
Add-Type @'
using System; using System.Collections.Generic;
public static class EdbWindows {
 public struct Rect { public int Left, Top, Right, Bottom; }
 public sealed class Window { public long Parent; public string Text="",Class=""; public int Control; public bool Visible=true,Enabled=true; public uint Owner=42; public int[] Bounds=new int[]{0,0,0,0}; }
 public static Dictionary<long,Window> Data=new Dictionary<long,Window>();
 public sealed class ClickReceipt { public string Error; public uint InsertedCount; public long Root,Child; public int X,Y,Left,Top,Right,Bottom; }
 public static int Clicks; public static ClickReceipt LastClick; public static bool NextClickFails=false; public static bool DeferOnce=false;
 public static bool ActivateSucceeds=true; public static IntPtr Foreground=IntPtr.Zero;
 // Mode-selection simulation: 'post', 'absent', 'misaligned', 'two' or 'stuck' popup behavior.
 public static string ModePopup="post"; public static List<uint> Keys=new List<uint>();
 public static long ObservedFocus=0; public static string FocusFailure=null;
 public static bool SetForegroundWindow(IntPtr h){if(ActivateSucceeds){Foreground=h;return true;}return false;}
 public static IntPtr GetForegroundWindow(){return Foreground;}
 public static long LastMessageTarget=0; public static uint LastMessage=0;
 public static IntPtr SendMessageTimeout(IntPtr h,uint m,IntPtr w,IntPtr l,uint flags,uint timeout,out UIntPtr result){LastMessageTarget=h.ToInt64();LastMessage=m;result=new UIntPtr(1);return Data.ContainsKey(h.ToInt64())?new IntPtr(1):IntPtr.Zero;}
 public static bool GetWindowRect(IntPtr h, out Rect r){ var b=Data[h.ToInt64()].Bounds; r=new Rect{Left=b[0],Top=b[1],Right=b[2],Bottom=b[3]}; return true; }
 public static IntPtr SetThreadDpiAwarenessContext(IntPtr c){ return new IntPtr(-1); }
 public static bool ShowWindow(IntPtr h,int mode){return true;}
 static bool IsDescendant(long h,long ancestor){var seen=new HashSet<long>();long p=h;while(Data.ContainsKey(p)){p=Data[p].Parent;if(p==ancestor)return true;if(!seen.Add(p))break;}return false;}
 static void PostPopup(long id,int l,int t,int r,int b){ var w=new Window(); w.Parent=0; w.Bounds=new int[]{l,t,r,b}; w.Class="TkTopLevel"; w.Text="popdown"; Data[id]=w; } // real Tk names the combobox popdown by its widget path (CI 35665619085 evidence)
 public static ClickReceipt SendOwnedControlClick(IntPtr root,uint owner,IntPtr child,int x,int y,int left,int top,int right,int bottom){
  Clicks++;var r=new ClickReceipt();r.Root=root.ToInt64();r.Child=child.ToInt64();r.X=x;r.Y=y;r.Left=left;r.Top=top;r.Right=right;r.Bottom=bottom;
  if(NextClickFails){r.Error="synthetic native rejection";}else if(DeferOnce){DeferOnce=false;r.Error="Secure desktop or held mouse/modifier input; no click.";}else{r.InsertedCount=3;}LastClick=r;
  if(r.InsertedCount==3&&child.ToInt64()==42){
   if(ModePopup=="post"||ModePopup=="stuck") PostPopup(60,83,99,214,194);
   else if(ModePopup=="misaligned") PostPopup(60,300,99,431,194);
   else if(ModePopup=="two"){PostPopup(60,83,99,214,194);PostPopup(61,300,300,431,395);}
   else if(ModePopup=="wrongtitle"){PostPopup(60,83,99,214,194);Data[60].Text="evil-tool";}
   else if(ModePopup=="wrongclass"){PostPopup(60,83,99,214,194);Data[60].Class="Panel";}
  }
  return r;}
 public static void ResetModeState(){Keys.Clear();ModePopup="post";ObservedFocus=42;FocusFailure=null;Data.Remove(60);Data.Remove(61);}
 public sealed class KeyReceipt { public string Error; public uint InsertedCount,Vk; }
 public static KeyReceipt SendOwnedPopupKey(IntPtr root,uint owner,IntPtr popup,ushort vk,bool extended){
  var r=new KeyReceipt();r.Vk=vk;Keys.Add(vk);
  if(popup==IntPtr.Zero||!Data.ContainsKey(popup.ToInt64())){r.Error="synthetic popup window is gone; no key.";return r;}
  r.InsertedCount=2;
  if(vk==0x0D&&ModePopup!="stuck"){Data.Remove(60);Data.Remove(61);}
  return r;}
 public sealed class FocusState { public string Error; public long Foreground,Focus; public uint Owner,ForegroundOwner,FocusOwner; public bool FocusIsRoot,FocusInRoot; public int Win32Error; }
 public static FocusState ObserveOwnedFocusState(IntPtr root,uint owner){var s=new FocusState();s.Owner=owner;s.Foreground=Foreground.ToInt64();s.ForegroundOwner=42;
  if(FocusFailure!=null){s.Error=FocusFailure;return s;}
  s.Focus=ObservedFocus;s.FocusOwner=42;s.FocusIsRoot=ObservedFocus==root.ToInt64();s.FocusInRoot=ObservedFocus!=0&&ObservedFocus!=root.ToInt64()&&IsDescendant(ObservedFocus,root.ToInt64());return s;}
 public static string DesktopName(){return "Default";}
 public static string Text(IntPtr h){return Data.ContainsKey(h.ToInt64())?Data[h.ToInt64()].Text:"";}
 public static string Class(IntPtr h){return Data.ContainsKey(h.ToInt64())?Data[h.ToInt64()].Class:"";}
 public static IntPtr GetParent(IntPtr h){return new IntPtr(Data[h.ToInt64()].Parent);}
 public static int GetDlgCtrlID(IntPtr h){return Data[h.ToInt64()].Control;}
 public static bool IsWindowVisible(IntPtr h){return Data.ContainsKey(h.ToInt64())&&Data[h.ToInt64()].Visible;}
 public static bool IsWindowEnabled(IntPtr h){return Data.ContainsKey(h.ToInt64())&&Data[h.ToInt64()].Enabled;}
 public static uint GetWindowThreadProcessId(IntPtr h,out uint owner){owner=Data.ContainsKey(h.ToInt64())?Data[h.ToInt64()].Owner:0u;return 7;}
 public static IntPtr[] Windows(IntPtr h){var result=new List<IntPtr>();foreach(var item in Data){long p=item.Value.Parent;var seen=new HashSet<long>();bool found=false;while(p!=0&&seen.Add(p)){if(p==h.ToInt64()){found=true;break;}p=Data.ContainsKey(p)?Data[p].Parent:0;}if(found)result.Add(new IntPtr(item.Key));}return result.ToArray();}
}
'@
function Get-OwnedWindows { return @([EdbWindows]::Data.Keys | Where-Object { [EdbWindows]::Data[$_].Parent -eq 0 } | ForEach-Object { [IntPtr]$_ }) }
# Every assertion names its case and, for Assert-Throws, the actual outcome, so a failure
# identifies the fixture and the real error instead of only the expected pattern.
$script:case='(startup)'
function Case([string]$Name) { $script:case=$Name }
function Assert-True([bool]$Value,[string]$Message) { if (-not $Value) { throw "guard case '$script:case' failed: $Message" } }
function Assert-Throws([scriptblock]$Action,[string]$Pattern) {
    $actual=$null
    try { & $Action | Out-Null } catch { $actual=$_.Exception.Message }
    if ($null -eq $actual) { throw "guard case '$script:case' expected error matching $Pattern; no error was thrown" }
    if ($actual -notlike $Pattern) { throw "guard case '$script:case' expected error matching $Pattern; actual error: $actual" }
}
function Run-Window([long]$Handle,[long]$Parent,[int[]]$Bounds,[string]$Class) {
    $w=[EdbWindows+Window]::new();$w.Parent=$Parent;$w.Bounds=$Bounds;$w.Class=$Class
    [EdbWindows]::Data.Add($Handle,$w)
}
$script:events=@()
function Record-Event([string]$Kind,$Data) { $script:events+=@{kind=$Kind;data=$Data} }
function Capture-Ui([string]$Label) { return @() }
function Run-Fixture {
    # Hosted-runner geometry: the three-button run row (Start, Stop, Retry due uploads) and the
    # current three-control guided mode row from CI 35976723286 prepare-stop dumps, plus the
    # decoy log frame whose Text child and ScrollBar child match every purely
    # geometric rule except child count and class.
    [void][EdbWindows]::Data.Clear()
    Run-Window 1 0 @(8,8,1016,703) 'TkTopLevel'; $t=[EdbWindows]::Data[1];$t.Text='EncodingDB Windows Client'
    Run-Window 10 1 @(38,490,986,673) 'TkChild'
    Run-Window 11 10 @(38,490,969,673) 'TkChild'
    Run-Window 12 10 @(969,490,986,673) 'ScrollBar'
    Run-Window 20 1 @(40,167,984,192) 'TkChild'
    Run-Window 21 20 @(40,167,139,192) 'TkChild'
    Run-Window 22 20 @(147,167,223,192) 'TkChild'
    Run-Window 23 20 @(239,167,367,192) 'TkChild'
    Run-Window 40 1 @(40,78,984,99) 'TkChild'
    Run-Window 41 40 @(40,79,75,98) 'TkChild'
    Run-Window 42 40 @(83,78,214,99) 'TkChild'
    Run-Window 43 40 @(230,78,385,99) 'TkChild'
}
Case 'run-row:real-identity-with-hosted-decoys'
Run-Fixture
$obs=Get-ObservedRunControl 'Start'
Assert-True ($obs.child -eq [IntPtr]21 -and $obs.owner -eq 42 -and $obs.x -eq 89 -and $obs.y -eq 179) 'Real observer picked the wrong Start control with the hosted decoy rows present.'
$obs=Get-ObservedRunControl 'Stop'
Assert-True ($obs.child -eq [IntPtr]22 -and $obs.x -eq 185 -and $obs.y -eq 179) 'Real observer picked the wrong Stop control with the hosted decoy rows present.'
Case 'run-row:reject-two-child-row'
Run-Fixture
[void][EdbWindows]::Data.Remove(23)
Assert-Throws {Get-ObservedRunControl 'Start'} '*BLOCKED_GUI_POINT*not established*'
Case 'run-row:reject-four-child-row'
Run-Fixture;Run-Window 24 20 @(375,167,503,192) 'TkChild'
Assert-Throws {Get-ObservedRunControl 'Start'} '*BLOCKED_GUI_POINT*not established*'
Case 'run-row:reject-mixed-class-children'
Run-Fixture;$flipped=[EdbWindows]::Data[21];$flipped.Class='ScrollBar'
Assert-Throws {Get-ObservedRunControl 'Start'} '*BLOCKED_GUI_POINT*not established*'
Case 'run-row:reject-mixed-child-heights'
Run-Fixture;$shrink=[EdbWindows]::Data[23];$shrink.Bounds=@(239,167,367,191)
Assert-Throws {Get-ObservedRunControl 'Start'} '*BLOCKED_GUI_POINT*not established*'
Case 'run-row:reject-ambiguous-decoy-copycat'
# Strip the decoy log frame's ScrollBar guard AND give it a third child sized to satisfy every
# purely geometric rule: two structurally valid run rows must block acceptance, never guess.
Run-Fixture;[EdbWindows]::Data[12].Class='TkChild';[EdbWindows]::Data[11].Bounds=@(38,490,300,673);[EdbWindows]::Data[12].Bounds=@(308,490,460,673)
Run-Window 13 10 @(468,490,700,673) 'TkChild'
Assert-Throws {Get-ObservedRunControl 'Start'} '*BLOCKED_GUI_POINT*observed 2 candidate Start/Stop rows*not established*'
Case 'run-row:mode-row-uniform-height-never-selected'
# Flattening every mode-row child to the mode row's uniform height must not let the three-control
# row impersonate the run row nor displace the real Start/Stop identity.
Run-Fixture
foreach ($id in @(41,43)) { $row1=[EdbWindows]::Data[$id]; $row1.Bounds=@($row1.Bounds[0],78,$row1.Bounds[2],99) }
$obs=Get-ObservedRunControl 'Start'
Assert-True ($obs.child -eq [IntPtr]21 -and $obs.x -eq 89 -and $obs.y -eq 179) 'The uniform-height mode row impersonated the run control.'
Case 'run-row:reject-first-not-wider'
Run-Fixture;$narrow=[EdbWindows]::Data[21];$narrow.Bounds=@(40,167,116,192)
Assert-Throws {Get-ObservedRunControl 'Start'} '*BLOCKED_GUI_POINT*not established*'
Case 'run-row:reject-first-second-gap'
Run-Fixture;$gap=[EdbWindows]::Data[22];$gap.Bounds=@(180,167,256,192)
Assert-Throws {Get-ObservedRunControl 'Start'} '*BLOCKED_GUI_POINT*not established*'
Case 'run-row:reject-second-third-gap'
Run-Fixture;$gap2=[EdbWindows]::Data[23];$gap2.Bounds=@(400,167,528,192)
Assert-Throws {Get-ObservedRunControl 'Start'} '*BLOCKED_GUI_POINT*not established*'
Case 'run-row:reject-second-overlaps-third-and-wider'
Run-Fixture;$wide=[EdbWindows]::Data[22];$wide.Bounds=@(147,167,295,192)
Assert-Throws {Get-ObservedRunControl 'Start'} '*BLOCKED_GUI_POINT*not established*'
Case 'mode-row:real-identity-after-run-row-rejection'
$mode=Get-ObservedModeControl
Assert-True ($mode.child -eq [IntPtr]42 -and $mode.owner -eq 42 -and $mode.x -eq 148 -and $mode.y -eq 88) 'Real mode observer picked the wrong mode combobox on the hosted geometry.'
Case 'mode-row:reject-four-control-row'
Run-Fixture;Run-Window 48 40 @(401,78,456,98) 'TkChild'
Assert-Throws {Get-ObservedModeControl} '*BLOCKED_GUI_POINT*configuration rows*not established*'
Case 'mode-row:reject-mixed-class-children'
Run-Fixture;$mflipped=[EdbWindows]::Data[43];$mflipped.Class='ScrollBar'
Assert-Throws {Get-ObservedModeControl} '*BLOCKED_GUI_POINT*configuration rows*not established*'
Case 'mode-row:reject-overlapping-children'
Run-Fixture;$mover=[EdbWindows]::Data[43];$mover.Bounds=@(200,78,412,99)
Assert-Throws {Get-ObservedModeControl} '*BLOCKED_GUI_POINT*configuration rows*not established*'
Case 'mode-row:reject-undersized-combobox'
Run-Fixture;$msmall=[EdbWindows]::Data[42];$msmall.Bounds=@(83,78,110,99)
Assert-Throws {Get-ObservedModeControl} '*BLOCKED_GUI_POINT*not established*'
Case 'mode-row:reject-ambiguous-second-three-control-row'
Run-Fixture;Run-Window 50 1 @(40,216,984,237) 'TkChild'
Run-Window 51 50 @(40,217,75,236) 'TkChild'
Run-Window 52 50 @(83,216,214,237) 'TkChild'
Run-Window 53 50 @(230,216,385,237) 'TkChild'
Assert-Throws {Get-ObservedModeControl} '*observed 2 candidate configuration rows*'
function Mode-Fixture {
    Run-Fixture
    [EdbWindows]::ResetModeState()
    [EdbWindows]::ActivateSucceeds=$true;[EdbWindows]::Foreground=[IntPtr]::Zero
    [EdbWindows]::Clicks=0;[EdbWindows]::NextClickFails=$false;[EdbWindows]::DeferOnce=$false
    $script:events=@()
    $script:harnessDeadline=[DateTime]::UtcNow.AddSeconds(30)
    $script:currentPhase=@{ name='mode-test'; path='.' }
}
Case 'mode-select:happy-path-aligns-walks-commits'
Mode-Fixture
Select-AdvancedSingleMode
Assert-True ($script:currentPhase.modeSelection.attempts -eq 1) 'A posted aligned popup required an unexpected retry.'
Assert-True (@($script:currentPhase.modeSelection.keyCodes) -join ',' -eq '28,28,28,28,28,28,13') 'Mode traversal must walk Down past the clamped final entry and then commit once with Return.'
Assert-True ([EdbWindows]::Clicks -eq 1 -and -not [EdbWindows]::Data.ContainsKey(60)) 'The commit must close the observed popup exactly once.'
Assert-True (@($script:events | Where-Object { $_.kind -eq 'observed-mode-selection' }).Count -eq 1) 'The mode selection evidence was not recorded.'
Case 'mode-select:reject-popup-that-never-posts'
Mode-Fixture;[EdbWindows]::ModePopup='absent';$script:harnessDeadline=[DateTime]::UtcNow.AddSeconds(-1)
Assert-Throws {Select-AdvancedSingleMode} '*BLOCKED_GUI_MODE*no mode combobox popup was observed*'
Assert-True ([EdbWindows]::Clicks -eq 3 -and [EdbWindows]::Keys.Count -eq 0) 'A popup that never posted must be bounded to three clicks and zero keys.'
Case 'mode-select:reject-misaligned-popup'
Mode-Fixture;[EdbWindows]::ModePopup='misaligned';$script:harnessDeadline=[DateTime]::UtcNow.AddSeconds(-1)
Assert-Throws {Select-AdvancedSingleMode} '*BLOCKED_GUI_MODE*does not align*'
Assert-True (-not [EdbWindows]::Keys.Contains(13)) 'An unaligned popup must never receive the commit key.'
Case 'mode-select:reject-popup-with-unexpected-title'
Mode-Fixture;[EdbWindows]::ModePopup='wrongtitle';$script:harnessDeadline=[DateTime]::UtcNow.AddSeconds(-1)
Assert-Throws {Select-AdvancedSingleMode} '*BLOCKED_GUI_MODE*not the observed Tk popdown*evil-tool*'
Assert-True ([EdbWindows]::Keys.Count -eq 0) 'A popup with an unrelated title must block before any traversal key.'
Case 'mode-select:reject-popup-with-wrong-class'
Mode-Fixture;[EdbWindows]::ModePopup='wrongclass';$script:harnessDeadline=[DateTime]::UtcNow.AddSeconds(-1)
Assert-Throws {Select-AdvancedSingleMode} '*BLOCKED_GUI_MODE*not the observed Tk popdown*Panel*'
Assert-True ([EdbWindows]::Keys.Count -eq 0) 'A popup of the wrong window class must block before any traversal key.'
Case 'mode-select:reject-two-simultaneous-popups'
Mode-Fixture;[EdbWindows]::ModePopup='two'
Assert-Throws {Select-AdvancedSingleMode} '*BLOCKED_GUI_MODE*multiple unexpected owned top-level windows*'
Assert-True ([EdbWindows]::Keys.Count -eq 0) 'Ambiguous popups must block before any traversal key.'
Case 'mode-select:reject-stuck-popup-after-commit'
Mode-Fixture;[EdbWindows]::ModePopup='stuck';$script:harnessDeadline=[DateTime]::UtcNow.AddSeconds(-1)
Assert-Throws {Select-AdvancedSingleMode} '*BLOCKED_GUI_MODE*stayed open*'
Assert-True ([EdbWindows]::Keys.Contains(13)) 'The stuck-popup replay must have dispatched the commit key before blocking.'
Case 'mode-select:reject-foreign-focus-after-commit'
Mode-Fixture;[EdbWindows]::FocusFailure='synthetic focus elsewhere';$script:harnessDeadline=[DateTime]::UtcNow.AddSeconds(-1)
Assert-Throws {Select-AdvancedSingleMode} '*BLOCKED_GUI_MODE*focus did not return*'
Assert-True (-not $script:currentPhase.ContainsKey('modeSelection')) 'A lost focus after commit must never record a completed mode selection.'
Case 'mode-select:reject-focus-outside-owned-tree'
Mode-Fixture;[EdbWindows]::ObservedFocus=999;$script:harnessDeadline=[DateTime]::UtcNow.AddSeconds(-1)
Assert-Throws {Select-AdvancedSingleMode} '*BLOCKED_GUI_MODE*focus did not return*'
Case 'mode-select:reject-refused-combobox-click'
Mode-Fixture;[EdbWindows]::NextClickFails=$true
Assert-Throws {Select-AdvancedSingleMode} '*BLOCKED_GUI_INPUT*mode combobox click was refused*'
Assert-True ([EdbWindows]::Keys.Count -eq 0) 'A refused combobox click must not send keys.'
Case 'mode-select:reject-activation-failure'
Mode-Fixture;[EdbWindows]::ActivateSucceeds=$false;$script:harnessDeadline=[DateTime]::UtcNow.AddSeconds(-1)
Assert-Throws {Select-AdvancedSingleMode} '*foreground focus*'
Assert-True ([EdbWindows]::Clicks -eq 0) 'Activation failure must block before any combobox click.'
Case 'mode-select:reject-preexisting-foreign-top-level'
Mode-Fixture;Run-Window 55 0 @(500,500,700,600) 'TkChild'
Assert-Throws {Select-AdvancedSingleMode} '*before mode selection*'
function Ready-Fixture {
    [EdbWindows]::Data.Clear()
    $dialog=[EdbWindows+Window]::new();$dialog.Text='Exit';$dialog.Class='#32770'
    $button=[EdbWindows+Window]::new();$button.Text='&Yes';$button.Class='Button';$button.Parent=1;$button.Control=6
    [EdbWindows]::Data.Add(1,$dialog);[EdbWindows]::Data.Add(2,$button)
}
Case 'exit-confirmation:absent-dialog-waits'
Assert-True ($null -eq (Get-OwnedExitConfirmation)) 'Absent dialog must wait.'
Case 'exit-confirmation:ready-native-identities'
Ready-Fixture
$ready=Get-OwnedExitConfirmation
Assert-True ($ready.dialog -eq [IntPtr]1 -and $ready.button -eq [IntPtr]2 -and $ready.owner -eq 42) 'Ready native identities changed.'
foreach ($field in @('Visible','Enabled')) {
    Case "exit-confirmation:reject-button-$field-false"
    Ready-Fixture;[EdbWindows]::Data[2].$field=$false
    Assert-True ($null -eq (Get-OwnedExitConfirmation)) "$field guard was bypassed."
}
Case 'exit-confirmation:reject-wrong-control-id'
Ready-Fixture;[EdbWindows]::Data[2].Control=7
Assert-True ($null -eq (Get-OwnedExitConfirmation)) 'Only IDYES is accepted.'
Case 'exit-confirmation:reject-indirect-button'
Ready-Fixture;[EdbWindows]::Data[2].Parent=9
Assert-True ($null -eq (Get-OwnedExitConfirmation)) 'Only a direct dialog child is accepted.'
Case 'exit-confirmation:reject-non-yes-button-text'
Ready-Fixture;[EdbWindows]::Data[2].Text='No'
Assert-True ($null -eq (Get-OwnedExitConfirmation)) 'Only observed Yes is accepted.'
Case 'exit-confirmation:reject-non-native-button-class'
Ready-Fixture;[EdbWindows]::Data[2].Class='Pane'
Assert-True ($null -eq (Get-OwnedExitConfirmation)) 'Only a native Button is accepted.'
Case 'exit-confirmation:reject-non-dialog-root-class'
Ready-Fixture;[EdbWindows]::Data[1].Class='TkTopLevel'
Assert-True ($null -eq (Get-OwnedExitConfirmation)) 'Only a native Exit dialog is accepted.'
Case 'exit-confirmation:reject-cross-process-button'
Ready-Fixture;[EdbWindows]::Data[2].Owner=99
Assert-Throws {Get-OwnedExitConfirmation} '*owner differs*'
Case 'exit-confirmation:reject-two-dialogs'
Ready-Fixture;[EdbWindows]::Data.Add(3,[EdbWindows]::Data[1])
Assert-Throws {Get-OwnedExitConfirmation} '*multiple owned native Exit dialogs*'
Case 'exit-confirmation:reject-two-yes-buttons'
Ready-Fixture;[EdbWindows]::Data.Add(3,[EdbWindows]::Data[2])
Assert-Throws {Get-OwnedExitConfirmation} '*multiple observed enabled native Yes buttons*'
function Download-Estimate-Fixture {
    [EdbWindows]::Data.Clear()
    Run-Window 1 0 @(8,8,1016,703) 'TkTopLevel';[EdbWindows]::Data[1].Text='EncodingDB Windows Client'
    Run-Window 2 0 @(317,310,722,469) '#32770';[EdbWindows]::Data[2].Text='Download and storage estimate'
    Run-Window 3 2 @(541,429,616,452) 'Button';[EdbWindows]::Data[3].Text='&Yes';[EdbWindows]::Data[3].Control=6
    Run-Window 4 2 @(624,429,699,452) 'Button';[EdbWindows]::Data[4].Text='&No';[EdbWindows]::Data[4].Control=7
    Run-Window 5 2 @(387,367,686,395) 'Static';[EdbWindows]::Data[5].Text='This run may download 1.4 GB of frozen reference media. Estimated peak extra storage: 2.9 GB. Continue?'
    [EdbWindows]::ActivateSucceeds=$true;[EdbWindows]::Foreground=[IntPtr]::Zero
    [EdbWindows]::LastMessageTarget=0;[EdbWindows]::LastMessage=0
    $script:harnessDeadline=[DateTime]::UtcNow.AddSeconds(30)
    $script:events=@()
}
Case 'download-estimate:exact-native-dialog-and-bounded-yes'
Download-Estimate-Fixture
$estimate=Get-OwnedDownloadEstimateConfirmation
Assert-True ($estimate.dialog -eq [IntPtr]2 -and $estimate.button -eq [IntPtr]3 -and $estimate.owner -eq 42) 'The estimate observer did not identify the owned Yes button.'
Confirm-ObservedDownloadEstimate
Assert-True ([EdbWindows]::LastMessageTarget -eq 3 -and [EdbWindows]::LastMessage -eq 0x00F5) 'The observed estimate Yes button did not receive BM_CLICK.'
Assert-True (@($script:events | Where-Object { $_.kind -eq 'observed-download-estimate-approved' }).Count -eq 1) 'Estimate approval evidence was not recorded.'
Case 'download-estimate:reject-unexpected-title'
Download-Estimate-Fixture;[EdbWindows]::Data[2].Text='Allow Benchmark Publication'
Assert-Throws {Get-OwnedDownloadEstimateConfirmation} '*unexpected owned dialog*'
Case 'download-estimate:reject-missing-cost-disclosure'
Download-Estimate-Fixture;[EdbWindows]::Data[5].Text='Continue?'
Assert-Throws {Get-OwnedDownloadEstimateConfirmation} '*lacks one visible Yes/No pair and the expected cost disclosure*'
Case 'download-estimate:reject-wrong-button-identity'
Download-Estimate-Fixture;[EdbWindows]::Data[3].Control=7
Assert-Throws {Get-OwnedDownloadEstimateConfirmation} '*lacks one visible Yes/No pair and the expected cost disclosure*'
Case 'download-estimate:reject-foreign-owner'
Download-Estimate-Fixture;[EdbWindows]::Data[5].Owner=99
Assert-Throws {Get-OwnedDownloadEstimateConfirmation} '*owner differs from the client*'
Case 'cleanup:primary-error-and-owned-identity-preserved'
$script:events=@()
$receipt=@{status='BLOCKED';error='original failure';primaryError=@{message='original failure';stage='close readiness'};cleanupErrors=@()}
$owned=[pscustomobject]@{ProcessId=123;CreationDate=[DateTime]'2026-09-20T00:00:00Z';Name='owned.exe'}
Record-CleanupFailure 'kill-owned-process' 'access denied' $owned
Record-CleanupFailure 'verify-owned-exit' 'survivor' $null
Assert-True ($receipt.error -eq 'original failure' -and $receipt.primaryError.stage -eq 'close readiness') 'Cleanup overwrote the initiating failure.'
Assert-True ($receipt.status -eq 'FAILED' -and $receipt.cleanupErrors.Count -eq 2 -and $script:events.Count -eq 2) 'Separate cleanup failures were lost.'
Assert-True ($receipt.cleanupErrors[0].processId -eq 123 -and $receipt.cleanupErrors[0].creationDate -eq $owned.CreationDate) 'Owned process identity was lost.'
Case 'cleanup:cleanup-only-failure-reported'
$receipt=@{status='PENDING_EVIDENCE_VALIDATION';error=$null;primaryError=$null;cleanupErrors=@()}
Record-CleanupFailure 'capture-owned-output' 'pipe still open' $null
Assert-True ($receipt.error -eq 'Process cleanup/evidence failed: pipe still open') 'Cleanup-only failure was not reported.'
# The real Observe-Processes closure must never adopt a process older than its claimed parent.
# Replay of CI 35549600291 attempt2 at 02:43:35: boot-time csrss.exe/winlogon.exe whose stale WMI
# ParentProcessId 8092 was just reused by the client worker's ~100ms Get-Counter GPU-sampler child.
function New-FakeProcess([long]$ProcessId,[long]$ParentProcessId,[DateTime]$CreationDate,[string]$Name,[string]$CommandLine) {
    [pscustomobject]@{ProcessId=$ProcessId;ParentProcessId=$ParentProcessId;CreationDate=$CreationDate;Name=$Name;ExecutablePath=('C:\fake\'+$Name);CommandLine=$CommandLine}
}
$boot=[DateTime]'2026-09-21T02:15:31.696'; $seeded=[DateTime]'2026-09-21T02:43:20.000'; $sampler=[DateTime]'2026-09-21T02:43:35.595'; $samplerChild=[DateTime]'2026-09-21T02:43:35.618'
$fakes=@(
    (New-FakeProcess 4588 1 $seeded 'encodingdb-client-windows.exe' 'client'),
    (New-FakeProcess 8092 4588 $sampler 'powershell.exe' 'powershell -NoProfile -Command Get-Counter GPU Engine'),
    (New-FakeProcess 6400 8092 $samplerChild 'conhost.exe' 'conhost 0x4'),
    (New-FakeProcess 8108 8092 $boot 'csrss.exe' ''),
    (New-FakeProcess 8156 8092 $boot 'winlogon.exe' 'winlogon.exe'),
    (New-FakeProcess 8112 4588 ([DateTime]'2026-09-21T02:43:22.840') 'powershell.exe' 'worker')
)
$script:events=@()
$script:processProbe={ return $fakes }
$script:currentPhase=@{ name='close'; helpers=@{} }
$script:owned=@{ '4588'=$fakes[0] }
$script:targetedProbe=$null
$script:PreDispatchRecheck=$null
$script:process=$null
# Extracted functions run without the harness param block; supply the bounded acquisition value
# Wait-Encoder needs so no case can wait on a real acquisition window.
$AcquisitionSeconds=5
$script:guardTemps=@()
Case 'process-closure:real-reused-pid-replay'
$aliveIds=@(Observe-Processes | ForEach-Object { $_.ProcessId })
Assert-True (@($aliveIds) -contains 8092 -and @($aliveIds) -contains 6400 -and @($aliveIds) -contains 8112) 'Legitimate owned descendants were not adopted by the closure.'
Assert-True (@($aliveIds) -notcontains 8108 -and @($aliveIds) -notcontains 8156) 'The closure adopted a process older than its claimed reused-PID parent.'
Assert-True (@($script:events | Where-Object { $_.kind -eq 'owned-process-discovered' -and @(8108,8156) -contains $_.data.ProcessId }).Count -eq 0) 'Stale-parent system processes were recorded as discovered.'
# The real Get-ObservedRunControl enumerates live Win32 child windows; this synthetic double supplies
# observation outcomes so the extracted Invoke-RunAction dispatch discipline is testable.
function Get-ObservedRunControl([string]$Action) {
    $script:observeCalls++
    if ($script:observeFail -and ($null -eq $script:failAfter -or $script:observeCalls -gt $script:failAfter)) { throw 'BLOCKED_GUI_POINT: synthetic observation refused.' }
    return @{ handle=$script:roots[0]; owner=42; child=[IntPtr]55; label=$Action; x=134; y=270
              controlBounds=@{ x=60; y=251; width=149; height=38 }
              rootBounds=@{ left=12; top=12; right=1686; bottom=1211 }
              childEnabled=$true }
}
function Click-Fixture {
    Ready-Fixture
    [EdbWindows]::Data[1].Text='EncodingDB Windows Client';[EdbWindows]::Data[1].Class='TkTopLevel'
    [EdbWindows]::ActivateSucceeds=$true;[EdbWindows]::Foreground=[IntPtr]::Zero
    [EdbWindows]::Clicks=0;[EdbWindows]::LastClick=$null;[EdbWindows]::NextClickFails=$false;[EdbWindows]::DeferOnce=$false
    $script:roots=@([IntPtr]1)
    $script:observeCalls=0;$script:observeFail=$false;$script:failAfter=$null
    $script:events=@()
    $script:harnessDeadline=[DateTime]::UtcNow.AddSeconds(5)
    $script:PreDispatchRecheck=$null
}
Case 'dispatch:reject-activation-failure-before-observation'
Click-Fixture;[EdbWindows]::ActivateSucceeds=$false;$script:harnessDeadline=[DateTime]::UtcNow.AddSeconds(-1)
Assert-Throws {Invoke-RunAction 'Start'} '*foreground focus*'
Assert-True ($script:observeCalls -eq 0 -and [EdbWindows]::Clicks -eq 0) 'Foreground failure must block before observation or click.'
Case 'dispatch:reject-unobservable-control'
Click-Fixture;$script:observeFail=$true;$script:harnessDeadline=[DateTime]::UtcNow.AddSeconds(-1)
Assert-Throws {Invoke-RunAction 'Start'} '*physically consistent*'
Assert-True ($script:observeCalls -gt 0 -and [EdbWindows]::Clicks -eq 0) 'Unobservable controls must never receive a click.'
Case 'dispatch:reject-control-changed-before-dispatch'
Click-Fixture;$script:observeFail=$true;$script:failAfter=1
Assert-Throws {Invoke-RunAction 'Stop'} '*changed before dispatch*'
Assert-True ([EdbWindows]::Clicks -eq 0) 'A changed fresh re-observation must cancel dispatch.'
Case 'dispatch:one-click-with-pinned-geometry'
Click-Fixture
Invoke-RunAction 'Start'
Assert-True ([EdbWindows]::Clicks -eq 1) 'One prepared action must dispatch exactly one native click.'
$click=[EdbWindows]::LastClick
Assert-True ($click.Child -eq 55 -and $click.X -eq 134 -and $click.Y -eq 270 -and $click.Left -eq 12 -and $click.Top -eq 12 -and $click.Right -eq 1686 -and $click.Bottom -eq 1211) 'The dispatch lost the exact child handle, observed point or pinned root geometry.'
Assert-True (@($script:events | Where-Object { $_.kind -eq 'observed-native-control-click' }).Count -eq 1 -and (@($script:events | Where-Object { $_.kind -eq 'observed-control-clicked' })[0].data.backend -like 'normal mouse click*')) 'Click receipts were not recorded.'
Case 'dispatch:refused-native-click-not-retried'
Click-Fixture;[EdbWindows]::NextClickFails=$true
Assert-Throws {Invoke-RunAction 'Stop'} '*BLOCKED_GUI_INPUT*synthetic native rejection*'
Assert-True ([EdbWindows]::Clicks -eq 1) 'A rejected native click must be preserved without retry.'
Case 'dispatch:desktop-deferral-reobserves-and-retries-once'
Click-Fixture;[EdbWindows]::DeferOnce=$true
Invoke-RunAction 'Start'
Assert-True ([EdbWindows]::Clicks -eq 2) 'A transient input-desktop refusal must be reobserved and retried within bounds.'
Assert-True (@($script:events | Where-Object { $_.kind -eq 'observed-click-deferred-for-desktop' }).Count -eq 1) 'The input-desktop deferral was not recorded.'
# Cancellation-window observation guards (CI 35670931191): the failure mode - a live encode absent
# from every full enumeration plus an idle campaign waited out to the deadline - is replayed with
# synthetic rows and temp-dir attempt journals only. No real process, window, input or screenshot
# action occurs; every path below runs with the synthetic process probe installed.
function New-EncoderProcess([long]$ProcessId,[long]$Parent,[DateTime]$Date,[string]$CommandLine) {
    [pscustomobject]@{ProcessId=$ProcessId;ParentProcessId=$Parent;CreationDate=$Date;Name='ffmpeg.exe';ExecutablePath=$script:fakeEncoderPath;CommandLine=$CommandLine}
}
function New-GuardQueue([bool]$Durable) {
    $queue=Join-Path ([IO.Path]::GetTempPath()) ('edb-guards-'+[Guid]::NewGuid().ToString('N'))
    $dir=Join-Path $queue 'campaigns/c1'; New-Item -ItemType Directory -Force $dir | Out-Null
    $script:guardTemps+=@($queue)
    $artifact=$null
    if ($Durable) { $artifact=Join-Path $dir 'measured.mp4'; Set-Content -LiteralPath $artifact -Value 'SYNTHETIC measured fixture' -Encoding Ascii }
    $timing=if ($Durable) { @{ elapsed_s=120.5 } } else { $null }
    @{ schedule=@{ campaign_id='c1'; recipe_id='clip-a|libx264|slower|24'; phase='measured' }; timing=$timing; metadata=@{ info=@{ artifactPath=$artifact } } } |
        ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $dir 'attempt-000001.json') -Encoding Ascii
    return $queue
}
function Encoder-Fixture([bool]$Durable) {
    $script:fakeEncoderPath=Join-Path ([IO.Path]::GetTempPath()) 'edb-guard-fake-ffmpeg.exe'
    Set-Content -LiteralPath $script:fakeEncoderPath -Value 'SYNTHETIC fake helper bytes' -Encoding Ascii
    $script:guardTemps+=@($script:fakeEncoderPath)
    $queue=New-GuardQueue $Durable
    $script:currentPhase=@{ name='stop'; queue=$queue; helpers=@{}; encoderObserved=$false }
    $script:owned=@{ '4588'=(New-FakeProcess 4588 1 $seeded 'encodingdb-client-windows.exe' 'client') }
    $script:events=@()
    $script:harnessDeadline=[DateTime]::UtcNow.AddMinutes(2)
    $script:process=[pscustomobject]@{ HasExited=$false }
    $script:processProbe={ @(New-FakeProcess 4588 1 $seeded 'encodingdb-client-windows.exe' 'client') }
    $script:targetedProbe=$null
    $script:targetedCalls=0
    return $queue
}
$encoderLine='ffmpeg.exe -hide_banner -v error -i in.mkv -c:v libx264 -preset slower -crf 24 out.mp4'
Case 'encode-observation:targeted-query-adopts-when-full-inventory-missed'
$null=Encoder-Fixture $true
$script:targetedProbe={ $script:targetedCalls++; @(New-EncoderProcess 9100 4588 $seeded.AddSeconds(30) $encoderLine) }
$ev=Get-ActiveEncodeEvidence
Assert-True ($ev.identified.Count -eq 1 -and $ev.identified[0].ProcessId -eq 9100) 'A live encode missing from the full enumeration was not adopted from the targeted query.'
Assert-True ($script:owned.ContainsKey('9100')) 'The targeted encode bypassed the ownership closure.'
Assert-True (@($script:events | Where-Object { $_.kind -eq 'owned-process-discovered' -and $_.data.ProcessId -eq 9100 }).Count -eq 1) 'The adopted targeted encode was not recorded as discovered.'
Assert-True ($script:currentPhase.encoderObserved -and $script:currentPhase.helpers.Count -eq 1) 'The adopted encode did not certify packaged-helper evidence.'
Case 'encode-observation:command-line-blind-owned-child-is-unidentified-encode'
$null=Encoder-Fixture $true
$script:targetedProbe={ @(New-EncoderProcess 9101 4588 $seeded.AddSeconds(30) $null) }
$ev=Get-ActiveEncodeEvidence
Assert-True ($ev.identified.Count -eq 0 -and $ev.unidentified.Count -eq 1) 'An owned ffmpeg row without command-line evidence was not reported as command-line-blind.'
Case 'encode-observation:full-inventory-hit-skips-targeted-query'
$null=Encoder-Fixture $true
$script:processProbe={ @((New-FakeProcess 4588 1 $seeded 'encodingdb-client-windows.exe' 'client'),(New-EncoderProcess 9102 4588 $seeded.AddSeconds(30) $encoderLine)) }
$script:targetedProbe={ $script:targetedCalls++; @() }
$ev=Get-ActiveEncodeEvidence
Assert-True ($ev.identified.Count -eq 1 -and $script:targetedCalls -eq 0) 'A full-inventory encode hit must not run the targeted query.'
Case 'encoder-acquisition:full-inventory-certifies-packaged-encoder'
$null=Encoder-Fixture $true
$script:processProbe={ @((New-FakeProcess 4588 1 $seeded 'encodingdb-client-windows.exe' 'client'),(New-EncoderProcess 9106 4588 $seeded.AddSeconds(30) $encoderLine)) }
Wait-Encoder
Assert-True ($script:currentPhase.encoderObserved -and $script:currentPhase.helpers.Count -eq 1) 'Wait-Encoder did not certify the observed packaged encoder.'
Case 'measured-wait:requires-durable-receipt-and-active-encode-together'
$null=Encoder-Fixture $true
$script:targetedProbe={ @(New-EncoderProcess 9103 4588 $seeded.AddSeconds(30) $encoderLine) }
Wait-MeasuredThenActiveEncode 5
Assert-True (@($script:events | Where-Object { $_.kind -eq 'cancellation-window-observed' -and $_.data.durableReceipts -eq 1 -and @($_.data.identifiedEncoders) -contains 9103 }).Count -eq 1) 'The cancellation window observation was not recorded.'
Case 'measured-wait:timing-null-attempt-is-not-a-durable-receipt'
$null=Encoder-Fixture $false
$script:targetedProbe={ @(New-EncoderProcess 9104 4588 $seeded.AddSeconds(30) $encoderLine) }
Assert-Throws { Wait-MeasuredThenActiveEncode 0 } '*No later encode after a durable measured attempt*'
Case 'measured-wait:campaign-completion-fails-fast'
$queue=Encoder-Fixture $true
Set-Content -LiteralPath (Join-Path $queue 'campaigns/c1/campaign-complete.json') -Value '{}' -Encoding Ascii
Assert-Throws { Wait-MeasuredThenActiveEncode 0 } '*Campaign completed before the cancellation click*'
Case 'measured-wait:budget-pause-fails-fast'
$queue=Encoder-Fixture $true
Set-Content -LiteralPath (Join-Path $queue 'campaigns/c1/budget-exhausted-1.json') -Value '{}' -Encoding Ascii
Assert-Throws { Wait-MeasuredThenActiveEncode 0 } '*time budget paused scheduling*'
Case 'measured-wait:gui-exit-fails-fast'
$null=Encoder-Fixture $true
$script:process=[pscustomobject]@{ HasExited=$true }
Assert-Throws { Wait-MeasuredThenActiveEncode 0 } '*BLOCKED_GUI_DESKTOP*'
Case 'zero-survivor:targeted-query-exposes-surviving-encode'
$null=Encoder-Fixture $true
$script:targetedProbe={ @(New-EncoderProcess 9105 4588 $seeded.AddSeconds(30) $encoderLine) }
$script:harnessDeadline=[DateTime]::UtcNow # clamps Wait-Until to a single probe pass; no real waiting
Assert-Throws { Wait-NoEncoders } '*survived GUI cancellation*'
Case 'zero-survivor:clean-closure-passes'
$null=Encoder-Fixture $true
$script:harnessDeadline=[DateTime]::UtcNow
Wait-NoEncoders
Case 'dispatch:preclick-recheck-refuses-stale-encode'
Click-Fixture
$script:PreDispatchRecheck={ param($action) if ($action -eq 'Stop') { throw 'BLOCKED_GUI_RACE: guard synthetic staleness.' } }
Assert-Throws { Invoke-RunAction 'Stop' } '*BLOCKED_GUI_RACE*'
Assert-True ([EdbWindows]::Clicks -eq 0) 'A stale cancellation window must never receive the click.'
Case 'dispatch:preclick-recheck-passes-when-encode-live'
Click-Fixture
$script:PreDispatchRecheck={ param($action) }
Invoke-RunAction 'Stop'
Assert-True ([EdbWindows]::Clicks -eq 1) 'A live-encode recheck must dispatch the prepared click.'
$script:PreDispatchRecheck=$null
foreach ($temp in $script:guardTemps) { Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue }
Write-Output 'PASS: real native readiness, three-button run row, mode combobox identity, observed-popup mode selection, primary-error preservation and observe-before-click functions, targeted-query encode adoption, durable measured-receipt gating with completion/budget/exit fail-fast, and pre-dispatch cancellation rechecks; synthetic observations only, no Windows interaction.'
