# Windows runner evidence; no coordinate guessing, external media runtime, or submission.
[CmdletBinding()]
param(
    [ValidateSet('Gui','Console')][string]$Mode = 'Gui',
    [string]$Output = '.test-reports/windows-native-gui',
    [int]$AcquisitionSeconds = 600,
    [int]$MeasurementMinutes = 20
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'This acceptance harness requires actual Windows.' }
$repo = Split-Path -Parent $PSScriptRoot
$outputRoot = [IO.Path]::GetFullPath((Join-Path $repo $Output))
New-Item -ItemType Directory -Force $outputRoot | Out-Null
$modeRoot = Join-Path $outputRoot $Mode.ToLowerInvariant()
if (Test-Path $modeRoot) { throw "Create-only acceptance output already exists: $modeRoot" }
New-Item -ItemType Directory $modeRoot | Out-Null
$script:currentPhase = $null
$script:owned = @{}
$script:process = $null
$script:stdoutTask = $null
$script:stderrTask = $null
$script:operationStage = 'initializing'
$script:harnessDeadline = [DateTime]::UtcNow.AddSeconds(($MeasurementMinutes*60)+$AcquisitionSeconds)
$receipt = [ordered]@{
    schemaVersion = 1; status = 'RUNNING'; mode = $Mode; startedAt = [DateTime]::UtcNow.ToString('o')
    sourceCommit = (git -C $repo rev-parse HEAD); runnerImage = $env:ImageOS; runnerImageVersion = $env:ImageVersion
    os = (Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber, OSArchitecture)
    computer = (Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer, Model)
    interactive = [Environment]::UserInteractive; sessionId = (Get-Process -Id $PID).SessionId
    actionBackend = 'normal mouse clicks on dynamically reobserved visible Start/Stop controls; documented Alt+R/Alt+S keyboard primitive retained but not dispatched'
    scope = 'GitHub hosted virtualized Windows software acceptance; no physical Windows/GPU certification or submissions'
    phases = @(); error = $null; primaryError = $null; cleanupErrors = @(); cleanupForced = $false
}
function Save-Json($Value, [string]$Path) { $Value | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $Path -Encoding utf8 }
function Record-Event([string]$Kind, $Data) {
    $event = @{ at = [DateTime]::UtcNow.ToString('o'); kind = $Kind; data = $Data }
    $event | ConvertTo-Json -Depth 12 -Compress | Add-Content -LiteralPath (Join-Path $modeRoot 'events.jsonl') -Encoding utf8
    # Preserve progress in the live runner log even if the outer job is cancelled.
    Write-Host ($event | ConvertTo-Json -Depth 12 -Compress)
    Save-Json $receipt (Join-Path $modeRoot 'receipt.json')
}
Save-Json $receipt (Join-Path $modeRoot 'receipt.json')
try {
Add-Type -AssemblyName System.Windows.Forms, System.Drawing, UIAutomationClient, UIAutomationTypes
Add-Type @'
using System; using System.Collections.Generic; using System.Runtime.InteropServices; using System.Text;
public static class EdbWindows {
 public struct Rect { public int Left, Top, Right, Bottom; }
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out Rect r);
 public struct Point { public int X, Y; }
 [DllImport("user32.dll")] public static extern bool GetCursorPos(out Point p);
 [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(Point p);
 [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h, uint flags);
 [DllImport("user32.dll")] public static extern int GetSystemMetrics(int index);
 [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
 [DllImport("user32.dll",SetLastError=true)] static extern IntPtr OpenInputDesktop(uint flags, bool inherit, uint access);
 [DllImport("user32.dll")] static extern bool CloseDesktop(IntPtr h);
 [DllImport("user32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool GetUserObjectInformation(IntPtr h, int index, StringBuilder value, int bytes, out int required);
 [DllImport("user32.dll")] public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
 [DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint flags);
 public delegate bool EnumProc(IntPtr h, IntPtr p);
 [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc f, IntPtr p);
 [DllImport("user32.dll")] static extern bool EnumChildWindows(IntPtr h, EnumProc f, IntPtr p);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h,StringBuilder s,int n);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr h,StringBuilder s,int n);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int command);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr h);
 [DllImport("user32.dll")] public static extern IntPtr GetParent(IntPtr h);
 [DllImport("user32.dll")] public static extern int GetDlgCtrlID(IntPtr h);
 [DllImport("user32.dll",SetLastError=true)] public static extern IntPtr SendMessageTimeout(IntPtr h,uint m,IntPtr w,IntPtr l,uint flags,uint timeout,out UIntPtr result);
 [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h,uint m,IntPtr w,IntPtr l);
 [StructLayout(LayoutKind.Sequential)] public struct GuiThreadInfo { public uint cbSize,flags; public IntPtr active,focus,capture,menuOwner,moveSize,caret; public Rect caretRect; }
 [StructLayout(LayoutKind.Sequential)] struct KeyboardInput { public ushort key,scan; public uint flags,time; public UIntPtr extra; }
 [StructLayout(LayoutKind.Sequential)] struct MouseInput { public int x,y; public uint data,flags,time; public UIntPtr extra; }
 [StructLayout(LayoutKind.Explicit)] struct InputUnion { [FieldOffset(0)] public KeyboardInput keyboard; [FieldOffset(0)] public MouseInput mouse; }
 [StructLayout(LayoutKind.Sequential)] struct Input { public uint type; public InputUnion value; }
 public sealed class ShortcutReceipt { public string Error; public long Root,Focus,KeyboardLayout; public uint Owner,FocusOwner,InsertedCount,ReleaseCount; public int InputSize,Win32Error; public bool ForegroundBefore,ForegroundAfter,CapsLock; }
 [DllImport("user32.dll",SetLastError=true)] static extern bool GetGUIThreadInfo(uint thread,ref GuiThreadInfo info);
 [DllImport("user32.dll")] static extern IntPtr GetKeyboardLayout(uint thread);
 [DllImport("user32.dll")] static extern bool IsChild(IntPtr parent,IntPtr child);
 [DllImport("user32.dll")] static extern short GetAsyncKeyState(int key);
 [DllImport("user32.dll")] static extern short GetKeyState(int key);
 [DllImport("user32.dll",SetLastError=true)] static extern uint SendInput(uint count,Input[] input,int size);
 static Input Key(ushort key,bool up) { var i=new Input();i.type=1;i.value.keyboard.key=key;i.value.keyboard.flags=up?2u:0u;return i; }
 public static ShortcutReceipt ObserveOwnedFocus(IntPtr root, uint owner) {
  var r=new ShortcutReceipt();r.Root=root.ToInt64();r.Owner=owner;r.InputSize=Marshal.SizeOf(typeof(Input));
  uint actualOwner;uint thread=GetWindowThreadProcessId(root,out actualOwner);
  r.ForegroundBefore=GetForegroundWindow()==root;
  if(!r.ForegroundBefore || actualOwner!=owner || thread==0 || !IsWindowEnabled(root)) {r.Error="Owned root lost foreground/identity or is disabled.";return r;}
  var g=new GuiThreadInfo();g.cbSize=(uint)Marshal.SizeOf(typeof(GuiThreadInfo));
  if(!GetGUIThreadInfo(thread,ref g)) {r.Error="Cannot observe target GUI keyboard focus.";r.Win32Error=Marshal.GetLastWin32Error();return r;}
  r.Focus=g.focus.ToInt64();GetWindowThreadProcessId(g.focus,out r.FocusOwner);r.KeyboardLayout=GetKeyboardLayout(thread).ToInt64();
  if(g.active!=root || g.focus==IntPtr.Zero || r.FocusOwner!=owner || (g.focus!=root && !IsChild(root,g.focus))) {r.Error="Keyboard focus is not inside the exact owned active root.";return r;}
  return r;
 }
 public static ShortcutReceipt SendOwnedShortcut(IntPtr root, uint owner, ushort key) {
  // Dispatch re-observes readiness; successful polling never authorizes stale focus.
  var r=ObserveOwnedFocus(root,owner);
  if(r.Error!=null) return r;
  if(key!=0x52 && key!=0x53) {r.Error="Only documented Alt+R/Alt+S shortcuts are allowed.";return r;}
  r.CapsLock=(GetKeyState(0x14)&1)!=0;
  if(r.CapsLock) {r.Error="Caps Lock is active; user keyboard state was not changed.";return r;}
  foreach(int k in new int[]{0x10,0x11,0x12,0x5b,0x5c,key}) {
   if((GetAsyncKeyState(k)&0x8000)!=0) {r.Error="A shortcut key/modifier is already held; no input sent.";return r;}
  }
  // One complete normal keyboard-input batch; no WinForms journal-hook backend.
  if(GetForegroundWindow()!=root) {r.Error="Foreground changed before input; no input sent.";return r;}
  var input=new Input[]{Key(0x12,false),Key(key,false),Key(key,true),Key(0x12,true)};
  r.InsertedCount=SendInput((uint)input.Length,input,r.InputSize);r.Win32Error=r.InsertedCount==4?0:Marshal.GetLastWin32Error();
  if(r.InsertedCount!=4) {
   // Release only keys this incomplete batch could have pressed; never retry key-downs.
   if(r.InsertedCount>0 && GetForegroundWindow()==root) {var release=r.InsertedCount==2?new Input[]{Key(key,true),Key(0x12,true)}:new Input[]{Key(0x12,true)};r.ReleaseCount=SendInput((uint)release.Length,release,r.InputSize);}
   r.Error="SendInput did not insert the complete four-event shortcut.";
  }
  r.ForegroundAfter=GetForegroundWindow()==root;
  if(!r.ForegroundAfter && r.Error==null) r.Error="Foreground changed during input; acceptance is blocked.";
  return r;
 }
 public sealed class ClickReceipt { public string Error,Desktop; public long Root,PointWindow; public uint Owner,PointOwner,InsertedCount,ReleaseCount; public int InputSize,Win32Error; public Rect Window,Observed; public Point Point,CursorBefore,CursorAfter; public bool Visible,Enabled,ForegroundBefore,ExactPointRoot,PointOwnerMatches,ClientHit,GeometryUnchanged,ForegroundAfter; }
 static bool HeldInput() { foreach(int k in new int[]{1,2,4,5,6,16,17,18,0x5b,0x5c}) if((GetAsyncKeyState(k)&0x8000)!=0) return true; return false; }
 static string InputDesktopName() {
  IntPtr desktop=OpenInputDesktop(0,false,1);
  if(desktop==IntPtr.Zero) return null;
  try { var name=new StringBuilder(256); int needed; if(GetUserObjectInformation(desktop,2,name,512,out needed)) return name.ToString(); return null; }
  finally { CloseDesktop(desktop); }
 }
 public static string DesktopName() { return InputDesktopName(); }
 public static ClickReceipt SendOwnedControlClick(IntPtr root, uint owner, IntPtr expectedChild, int x, int y, int observedLeft, int observedTop, int observedRight, int observedBottom) {
  var r=new ClickReceipt();r.Root=root.ToInt64();r.Owner=owner;r.Point.X=x;r.Point.Y=y;r.InputSize=Marshal.SizeOf(typeof(Input));
  IntPtr oldDpi=SetThreadDpiAwarenessContext(new IntPtr(-4));
  if(oldDpi==IntPtr.Zero){r.Error="Cannot establish physical click coordinates; no input.";return r;}
  try {
   r.Desktop=InputDesktopName();
   if(r.Desktop!="Default" || HeldInput()){r.Error="Secure desktop or held mouse/modifier input; no click.";return r;}
   uint actualOwner;GetWindowThreadProcessId(root,out actualOwner);
   r.Visible=IsWindowVisible(root);r.Enabled=IsWindowEnabled(root);
   r.ForegroundBefore=GetForegroundWindow()==root;
   if(actualOwner!=owner || !r.Visible || !r.Enabled || !r.ForegroundBefore) {r.Error="Owned root lost foreground/identity or is disabled; no click.";return r;}
   if(!GetWindowRect(root,out r.Window)){r.Error="Cannot observe physical root bounds; no click.";return r;}
   r.Observed.Left=observedLeft;r.Observed.Top=observedTop;r.Observed.Right=observedRight;r.Observed.Bottom=observedBottom;
   r.GeometryUnchanged=r.Window.Left==observedLeft && r.Window.Top==observedTop && r.Window.Right==observedRight && r.Window.Bottom==observedBottom;
   if(!r.GeometryUnchanged){r.Error="Observed window geometry changed between observation and dispatch; no click.";return r;}
   if(x<=r.Window.Left || x>=r.Window.Right-1 || y<=r.Window.Top || y>=r.Window.Bottom-1){r.Error="Observed control point is outside the owned root window; no click.";return r;}
   if(x<-32768 || x>32767 || y<-32768 || y>32767){r.Error="Observed point exceeds hit-test coordinate range; no click.";return r;}
   UIntPtr hit;long packed=((long)x & 65535L) | (((long)y & 65535L) << 16);
   r.ClientHit=SendMessageTimeout(root,0x0084,IntPtr.Zero,new IntPtr(packed),2,1000,out hit)!=IntPtr.Zero && hit.ToUInt64()==1;
   if(!r.ClientHit){r.Error="Observed point is not an unoccluded client hit-test inside the owned window; no click.";return r;}
   IntPtr at=WindowFromPoint(r.Point);r.PointWindow=at.ToInt64();GetWindowThreadProcessId(at,out r.PointOwner);
   r.ExactPointRoot=(expectedChild==IntPtr.Zero ? GetAncestor(at,2)==root : at==expectedChild && GetAncestor(at,2)==root);r.PointOwnerMatches=r.PointOwner==owner;
   if(!r.ExactPointRoot || !r.PointOwnerMatches){r.Error="Observed point is not an unoccluded exact owned client target; no click.";return r;}
   int left=GetSystemMetrics(76),top=GetSystemMetrics(77),width=GetSystemMetrics(78),height=GetSystemMetrics(79);
   if(width<=1 || height<=1 || x<left || x>=left+width || y<top || y>=top+height){r.Error="Observed point is outside the physical virtual desktop; no click.";return r;}
   Point cursor;
   if(!GetCursorPos(out cursor) || HeldInput() || GetForegroundWindow()!=root){r.Error="Input/desktop state changed during validation; no click.";return r;}
   r.CursorBefore=cursor;
   var move=new Input();move.type=0;move.value.mouse.x=(int)Math.Round((x-left)*65535.0/(width-1));move.value.mouse.y=(int)Math.Round((y-top)*65535.0/(height-1));move.value.mouse.flags=0xC001u;
   var down=new Input();down.type=0;down.value.mouse.flags=2u;
   var up=new Input();up.type=0;up.value.mouse.flags=4u;
   // One complete normal mouse batch at the validated point; no drag, wheel or extra buttons.
   r.InsertedCount=SendInput(3,new Input[]{move,down,up},r.InputSize);r.Win32Error=r.InsertedCount==3?0:Marshal.GetLastWin32Error();
   if(r.InsertedCount!=3){
    // Release only what this incomplete batch could have pressed; never re-press.
    if(r.InsertedCount==2 && GetForegroundWindow()==root){r.ReleaseCount=SendInput(1,new Input[]{up},r.InputSize);}
    r.Error="Normal mouse click input was not inserted completely.";
   }
   GetCursorPos(out r.CursorAfter);
   r.ForegroundAfter=GetForegroundWindow()==root;
   if(!r.ForegroundAfter && r.Error==null) r.Error="Foreground changed during input; acceptance is blocked.";
   return r;
  } finally { SetThreadDpiAwarenessContext(oldDpi); }
 }
 public static IntPtr[] Windows(IntPtr parent) { var a=new List<IntPtr>(); EnumProc f=(h,p)=>{a.Add(h);return true;}; if(parent==IntPtr.Zero)EnumWindows(f,IntPtr.Zero);else EnumChildWindows(parent,f,IntPtr.Zero);return a.ToArray(); }
 public static string Text(IntPtr h) { var s=new StringBuilder(4096);GetWindowText(h,s,s.Capacity);return s.ToString(); }
 public static string Class(IntPtr h) { var s=new StringBuilder(256);GetClassName(h,s,s.Capacity);return s.ToString(); }
}
'@
} catch {
    $receipt.status='BLOCKED'; $receipt.error="Windows GUI API initialization failed: $($_.Exception.Message)"
    Save-Json $receipt (Join-Path $modeRoot 'receipt.json'); throw
}
function Observe-Processes {
    $all = @(Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId, CreationDate, Name, ExecutablePath, CommandLine)
    $byId = @{}
    foreach ($item in $all) { $byId[[string]$item.ProcessId] = $item }
    do {
        $added = $false
        foreach ($item in $all) {
            $key = [string]$item.ProcessId
            $parentKey = [string]$item.ParentProcessId
            $parentLive = $script:owned.ContainsKey($parentKey) -and $byId.ContainsKey($parentKey) -and $byId[$parentKey].CreationDate -eq $script:owned[$parentKey].CreationDate
            if (-not $script:owned.ContainsKey($key) -and $parentLive) {
                $script:owned[$key] = $item; $added = $true
                Record-Event 'owned-process-discovered' $item
            }
        }
    } while ($added)
    $alive = @($all | Where-Object { $script:owned.ContainsKey([string]$_.ProcessId) -and $_.CreationDate -eq $script:owned[[string]$_.ProcessId].CreationDate })
    foreach ($item in $alive | Where-Object { $_.Name -eq 'ffmpeg.exe' -and $_.CommandLine -match '(?:-c:v|-vcodec)\s+"?libx264' }) {
        if (-not $script:currentPhase.helpers.ContainsKey($item.ExecutablePath)) {
            $script:currentPhase.helpers[$item.ExecutablePath] = @{ path = $item.ExecutablePath; sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $item.ExecutablePath).Hash.ToLowerInvariant(); commandLine = $item.CommandLine }
        }
        $script:currentPhase.encoderObserved = $true
    }
    if ($script:currentPhase.name -eq 'prepare-stop' -and -not $script:currentPhase.preparationProbe) {
        $probes=@($alive | Where-Object { $_.Name -eq 'ffprobe.exe' -and $_.CommandLine -match '-count_frames' -and $_.ExecutablePath })
        if ($probes.Count) {
            $probe=$probes[0]
            $script:currentPhase.preparationProbe=@{ path=$probe.ExecutablePath; sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $probe.ExecutablePath).Hash.ToLowerInvariant(); commandLine=$probe.CommandLine }
            Record-Event 'owned-preparation-probe' $script:currentPhase.preparationProbe
        }
    }
    return $alive
}
function Get-OwnedWindows {
    $alive = @(Observe-Processes)
    return @([EdbWindows]::Windows([IntPtr]::Zero) | Where-Object {
        [uint32]$ownerId = 0; [void][EdbWindows]::GetWindowThreadProcessId($_, [ref]$ownerId)
        $ownerId -in @($alive | ForEach-Object { $_.ProcessId }) -and [EdbWindows]::IsWindowVisible($_)
    })
}
function Get-Elements {
    $elements = [Collections.Generic.List[object]]::new()
    foreach ($handle in @(Get-OwnedWindows)) {
        $root = [Windows.Automation.AutomationElement]::FromHandle($handle)
        $elements.Add($root)
        foreach ($element in $root.FindAll([Windows.Automation.TreeScope]::Descendants, [Windows.Automation.Condition]::TrueCondition)) {
            if ($elements.Count -ge 1000) { throw 'UI tree exceeded the bounded capture limit.' }
            $elements.Add($element)
        }
    }
    return $elements.ToArray()
}
function Capture-Ui([string]$Label) {
    # Observe owned windows in physical pixels so captures and click coordinates share one space.
    $previousDpi=[EdbWindows]::SetThreadDpiAwarenessContext([IntPtr]::new(-4))
    if ($previousDpi -eq [IntPtr]::Zero) { throw 'Unable to align owned capture DPI coordinates.' }
    try {
    $base = Join-Path $script:currentPhase.path $Label
    $native = @(foreach ($handle in @(Get-OwnedWindows)) {
        foreach ($child in (@($handle) + @([EdbWindows]::Windows($handle)))) {
            $rect = [EdbWindows+Rect]::new(); [void][EdbWindows]::GetWindowRect($child, [ref]$rect)
            @{ handle = $child.ToInt64(); name = [EdbWindows]::Text($child); class = [EdbWindows]::Class($child); bounds = @{ x=$rect.Left; y=$rect.Top; width=($rect.Right-$rect.Left); height=($rect.Bottom-$rect.Top) } }
        }
    })
    Save-Json $native "$base.win32.json"
    $bounds = [Windows.Forms.SystemInformation]::VirtualScreen
    $bitmap = [Drawing.Bitmap]::new($bounds.Width, $bounds.Height)
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    try { $graphics.CopyFromScreen($bounds.Location, [Drawing.Point]::Empty, $bounds.Size); $bitmap.Save("$base.png", [Drawing.Imaging.ImageFormat]::Png) }
    finally { $graphics.Dispose(); $bitmap.Dispose() }
    $elements = @(Get-Elements)
    $controls = @(foreach ($element in $elements) {
        $c = $element.Current
        @{ name = $c.Name; automationId = $c.AutomationId; type = $c.ControlType.ProgrammaticName; enabled = $c.IsEnabled; offscreen = $c.IsOffscreen; processId = $c.ProcessId; handle = $c.NativeWindowHandle; bounds = @{ x=$c.BoundingRectangle.X; y=$c.BoundingRectangle.Y; width=$c.BoundingRectangle.Width; height=$c.BoundingRectangle.Height }; patterns = @($element.GetSupportedPatterns() | ForEach-Object { $_.ProgrammaticName }) }
    })
    Save-Json $controls "$base.uia.json"
    Record-Event 'ui-observed' @{ snapshot=$Label; controls=$controls.Count; screenshot="$base.png" }
    return $elements
    } finally { [void][EdbWindows]::SetThreadDpiAwarenessContext($previousDpi) }
}
function Get-OwnedExitConfirmation {
    # Use the same native readiness predicate for polling and invocation.
    $dialogs=@(Get-OwnedWindows | Where-Object { [EdbWindows]::Text($_) -eq 'Exit' -and [EdbWindows]::Class($_) -eq '#32770' })
    if ($dialogs.Count -gt 1) { throw "BLOCKED_GUI_AUTOMATION: multiple owned native Exit dialogs were observed." }
    if ($dialogs.Count -eq 0) { return $null }
    $dialog=$dialogs[0]
    $buttons=@([EdbWindows]::Windows($dialog) | Where-Object {
        [EdbWindows]::GetParent($_) -eq $dialog -and [EdbWindows]::Class($_) -eq 'Button' -and
        [EdbWindows]::Text($_).Replace('&','') -eq 'Yes' -and [EdbWindows]::GetDlgCtrlID($_) -eq 6 -and
        [EdbWindows]::IsWindowVisible($_) -and [EdbWindows]::IsWindowEnabled($_)
    })
    if ($buttons.Count -gt 1) { throw "BLOCKED_GUI_AUTOMATION: multiple observed enabled native Yes buttons were found." }
    if ($buttons.Count -eq 0) { return $null }
    [uint32]$dialogOwner=0; [uint32]$buttonOwner=0
    [void][EdbWindows]::GetWindowThreadProcessId($dialog,[ref]$dialogOwner)
    [void][EdbWindows]::GetWindowThreadProcessId($buttons[0],[ref]$buttonOwner)
    if ($dialogOwner -ne $buttonOwner) { throw 'BLOCKED_GUI_AUTOMATION: native Yes button owner differs from its dialog.' }
    return @{ dialog=$dialog; button=$buttons[0]; owner=$buttonOwner }
}
function Confirm-ObservedExit {
    $script:operationStage='close:capture-confirmation'
    [void](Capture-Ui 'before-action-Yes')
    $script:operationStage='close:validate-native-confirmation'
    $confirmation=Get-OwnedExitConfirmation
    if ($null -eq $confirmation) { throw 'BLOCKED_GUI_AUTOMATION: owned native Exit/Yes confirmation is no longer ready.' }
    $dialog=$confirmation.dialog; $button=$confirmation.button; $buttonOwner=$confirmation.owner
    [void][EdbWindows]::SetForegroundWindow($dialog)
    Wait-Until { return [EdbWindows]::GetForegroundWindow() -eq $dialog } 5 'BLOCKED_GUI_FOCUS: Exit dialog did not receive foreground focus.'
    [UIntPtr]$result=[UIntPtr]::Zero
    # BM_CLICK, bounded by SMTO_ABORTIFHUNG. Normal close/cancellation checks follow.
    $script:operationStage='close:click-native-yes'
    $sent=[EdbWindows]::SendMessageTimeout($button,0x00F5,[IntPtr]::Zero,[IntPtr]::Zero,2,2000,[ref]$result)
    if ($sent -eq [IntPtr]::Zero) { throw 'BLOCKED_GUI_AUTOMATION: native Yes button did not accept the bounded click.' }
    Record-Event 'observed-native-button-clicked' @{ name='Yes'; processId=$buttonOwner; dialogHandle=$dialog.ToInt64(); buttonHandle=$button.ToInt64(); controlId=6 }
}
function Get-ObservedRunControl([ValidateSet('Start','Stop')][string]$Action) {
    # Tk widgets expose no accessible name (verified: every descendant is an unnamed UIA Pane and only
    # the TkTopLevel carries window text). The frozen client packs Start then Stop as exact native
    # child HWNDs inside one row container, so the control is reobserved from that live Win32 structure:
    # the unique row whose two visible same-owner children share one height tightly equal to the row
    # height, ordered left to right with the first child wider than the second. Start is the first.
    $roots=@(Get-OwnedWindows | Where-Object { [EdbWindows]::Text($_) -eq 'EncodingDB Windows Client' })
    if ($roots.Count -ne 1) { throw 'BLOCKED_GUI_POINT: expected one observed owned client window.' }
    $handle=$roots[0]
    [uint32]$ownerId=0; [void][EdbWindows]::GetWindowThreadProcessId($handle,[ref]$ownerId)
    $previousDpi=[EdbWindows]::SetThreadDpiAwarenessContext([IntPtr]::new(-4))
    if ($previousDpi -eq [IntPtr]::Zero) { throw 'BLOCKED_GUI_POINT: cannot establish physical observation coordinates.' }
    try {
        $rootRect=[EdbWindows+Rect]::new()
        if (-not [EdbWindows]::GetWindowRect($handle,[ref]$rootRect)) { throw 'BLOCKED_GUI_POINT: cannot observe physical root bounds.' }
        $rootWidth=$rootRect.Right-$rootRect.Left
        $children=@([EdbWindows]::Windows($handle))
        $byHandle=@{}
        foreach ($child in $children) {
            $rect=[EdbWindows+Rect]::new()
            if (-not [EdbWindows]::GetWindowRect($child,[ref]$rect)) { continue }
            [uint32]$childOwner=0; [void][EdbWindows]::GetWindowThreadProcessId($child,[ref]$childOwner)
            if ($childOwner -ne $ownerId) { throw 'BLOCKED_GUI_POINT: an owned-tree child belongs to another process.' }
            if ($rect.Right -le $rect.Left -or $rect.Bottom -le $rect.Top) { continue }
            if ($rect.Left -lt $rootRect.Left -or $rect.Top -lt $rootRect.Top -or $rect.Right -gt $rootRect.Right -or $rect.Bottom -gt $rootRect.Bottom) { continue }
            $byHandle[$child.ToInt64()]=@{ handle=$child; rect=$rect; parent=[int64]([EdbWindows]::GetParent($child).ToInt64()); visible=[EdbWindows]::IsWindowVisible($child); enabled=[EdbWindows]::IsWindowEnabled($child) }
        }
        $rows=@()
        foreach ($key in @($byHandle.Keys)) {
            $candidate=$byHandle[$key]
            $pRect=$candidate.rect
            $pWidth=$pRect.Right-$pRect.Left; $pHeight=$pRect.Bottom-$pRect.Top
            if ($pWidth -lt [Math]::Floor($rootWidth*0.5)) { continue }
            $kids=@($byHandle.Values | Where-Object { $_.parent -eq $key -and $_.visible })
            if ($kids.Count -ne 2) { continue }
            $heights=@($kids | ForEach-Object { $_.rect.Bottom-$_.rect.Top } | Select-Object -Unique)
            if ($heights.Count -ne 1) { continue }
            if ([Math]::Abs($heights[0]-$pHeight) -gt 1) { continue }
            $ordered=@($kids | Sort-Object { $_.rect.Left })
            $first=$ordered[0]; $second=$ordered[1]
            if ($first.rect.Left -ne $pRect.Left) { continue }
            if ($second.rect.Left -lt $first.rect.Right) { continue }
            if ($second.rect.Right -gt $pRect.Right) { continue }
            if (($second.rect.Left-$first.rect.Right) -gt 32) { continue }
            if (($first.rect.Right-$first.rect.Left) -le ($second.rect.Right-$second.rect.Left)) { continue }
            $rows+=,@{ row=$candidate; first=$first; second=$second }
        }
        if ($rows.Count -ne 1) { throw "BLOCKED_GUI_POINT: observed $($rows.Count) candidate Start/Stop rows on this fresh instance; the unique two-button run-control row is not established." }
        $control=if ($Action -eq 'Start') { $rows[0].first } else { $rows[0].second }
        $rect=$control.rect
        $width=$rect.Right-$rect.Left; $height=$rect.Bottom-$rect.Top
        if ($width -lt 24 -or $height -lt 16) { throw 'BLOCKED_GUI_POINT: observed control is too small for a reliable click.' }
        return @{
            handle=$handle; owner=$ownerId; child=$control.handle; label=$Action
            x=[int][Math]::Floor(($rect.Left+$rect.Right)/2.0); y=[int][Math]::Floor(($rect.Top+$rect.Bottom)/2.0)
            controlBounds=@{ x=$rect.Left; y=$rect.Top; width=$width; height=$height }
            rootBounds=@{ left=$rootRect.Left; top=$rootRect.Top; right=$rootRect.Right; bottom=$rootRect.Bottom }
            childEnabled=$control.enabled
        }
    } finally { [void][EdbWindows]::SetThreadDpiAwarenessContext($previousDpi) }
}
function Invoke-RunAction([ValidateSet('Start','Stop')][string]$Action) {
    $script:operationStage="run-action:${Action}:capture"
    [void](Capture-Ui "before-click-$Action")
    $script:operationStage="run-action:${Action}:activate"
    $roots=@(Get-OwnedWindows | Where-Object { [EdbWindows]::Text($_) -eq 'EncodingDB Windows Client' })
    if ($roots.Count -ne 1) { throw 'BLOCKED_GUI_FOCUS: expected one observed owned client window.' }
    $handle=$roots[0]
    [void][EdbWindows]::ShowWindow($handle,9)
    [void][EdbWindows]::SetForegroundWindow($handle)
    Wait-Until { return [EdbWindows]::GetForegroundWindow() -eq $handle } 5 'BLOCKED_GUI_FOCUS: client did not receive foreground focus; no click sent.'
    $script:operationStage="run-action:${Action}:observe-control"
    $observation=$null; $attempts=0; $lastError=$null
    $observeDeadline=[DateTime]::UtcNow.AddSeconds(10)
    if ($observeDeadline -gt $script:harnessDeadline) { $observeDeadline=$script:harnessDeadline }
    # In-scope polling keeps the dynamic observation (a child scope cannot publish observations).
    do {
        $attempts++
        try { $observation=Get-ObservedRunControl $Action; break } catch { $observation=$null; $lastError=$_.Exception.Message }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $observeDeadline)
    if ($null -eq $observation) { throw "BLOCKED_GUI_POINT: no enabled, visible, physically consistent '$Action' control was observed for the owned client. Last observation: $lastError" }
    # Fresh dynamic re-observation immediately before the one normal click.
    try { $observation=Get-ObservedRunControl $Action } catch { throw "BLOCKED_GUI_POINT: control observation changed before dispatch: $($_.Exception.Message)" }
    if ($observation.handle -ne $handle) { throw 'BLOCKED_GUI_POINT: the owned client root changed during observation.' }
    $script:operationStage="run-action:${Action}:click"
    $desktopWaits=0
    $clickDeadline=[DateTime]::UtcNow.AddSeconds(120); if ($clickDeadline -gt $script:harnessDeadline) { $clickDeadline=$script:harnessDeadline }
    while ($true) {
        $native=[EdbWindows]::SendOwnedControlClick($observation.handle,$observation.owner,[IntPtr]$observation.child,[int]$observation.x,[int]$observation.y,[int]$observation.rootBounds.left,[int]$observation.rootBounds.top,[int]$observation.rootBounds.right,[int]$observation.rootBounds.bottom)
        Record-Event 'observed-native-control-click' @{ action=$Action; control=$observation.label; processId=$observation.owner; observedHandle=$observation.handle.ToInt64(); childHandle=$observation.child.ToInt64(); controlBounds=$observation.controlBounds; rootBounds=$observation.rootBounds; point=@{ x=$observation.x; y=$observation.y }; attempts=$attempts; desktopWaits=$desktopWaits; childEnabled=$observation.childEnabled; lastObservationError=$lastError; input=$native }
        if (-not $native.Error) { break }
        # A console screensaver lock swaps the input desktop off Default; the native guard refuses every click.
        # Wait only for the same session to return to Default, reobserve, then allow one fresh click.
        if ($native.Error -notlike 'Secure desktop or held mouse*' -or [DateTime]::UtcNow -ge $clickDeadline) { throw "BLOCKED_GUI_INPUT: $($native.Error)" }
        Record-Event 'observed-click-deferred-for-desktop' @{ action=$Action; inputDesktop=[EdbWindows]::DesktopName(); waitedSeconds=$desktopWaits }
        Start-Sleep -Seconds 2
        $desktopWaits++
        try { $observation=Get-ObservedRunControl $Action } catch { throw "BLOCKED_GUI_POINT: control observation changed while awaiting the input desktop: $($_.Exception.Message)" }
        if ($observation.handle -ne $handle) { throw 'BLOCKED_GUI_POINT: the owned client root changed during observation.' }
    }
    Record-Event 'observed-control-clicked' @{ action=$Action; control=$observation.label; backend='normal mouse click on visibly observed control'; insertedCount=$native.InsertedCount }
}
function Get-CompletionMarkers {
    return @(Get-ChildItem -Path $script:currentPhase.queue -Recurse -Filter 'campaign-complete.json' -ErrorAction SilentlyContinue)
}
function Wait-Until([scriptblock]$Condition, [int]$Seconds, [string]$Failure) {
    $script:operationStage=$Failure
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    if ($deadline -gt $script:harnessDeadline) { $deadline = $script:harnessDeadline }
    do { if (& $Condition) { return }; Start-Sleep -Milliseconds 250 } while ([DateTime]::UtcNow -lt $deadline)
    throw $Failure
}
function Start-Owned([string]$Name, [bool]$Gui) {
    $script:operationStage="phase:${Name}:launch"
    $phasePath = Join-Path $modeRoot $Name; New-Item -ItemType Directory $phasePath | Out-Null
    $state = Join-Path $env:RUNNER_TEMP ("encodingdb-native-$Mode-$Name-" + [Guid]::NewGuid().ToString('N') + '-' + [char]0x00E9)
    New-Item -ItemType Directory -Force (Join-Path $state 'tmp') | Out-Null
    $phase = @{ name=$Name; path=$phasePath; status='RUNNING'; helpers=@{}; encoderObserved=$false; preparationProbe=$null; queue= (Join-Path $phasePath ('queue-' + [char]0x00E9)); state=$state; exitCode=$null; survivors=@(); action=$null }
    $script:currentPhase = $phase; $script:owned = @{}
    $exe = Join-Path $repo $(if ($Gui) {'encodingdb-client-windows.exe'} else {'encodingdb-client-windows-console.exe'})
    $info = [Diagnostics.ProcessStartInfo]::new($exe)
    $info.UseShellExecute=$false; $info.RedirectStandardOutput=$true; $info.RedirectStandardError=$true; $info.WorkingDirectory=$phasePath
    foreach ($key in @($info.EnvironmentVariables.Keys)) {
        if ($key -match '^(FFMPEG_EXE|FFPROBE_EXE|ENCODINGDB_(FFMPEG_PATH|FFPROBE_PATH|RUNTIME_.*|QUICK_CLIP_ID|SUITE_PACK_URL)|TCL_LIBRARY|TK_LIBRARY|PYTHONPATH|PYTHONHOME|LD_LIBRARY_PATH|DYLD_.*|V7_OPERATOR_.*)$') { [void]$info.EnvironmentVariables.Remove($key) }
    }
    $info.EnvironmentVariables['ENCODINGDB_RUNTIME_EVIDENCE_PATH'] = Join-Path $phasePath 'embedded-runtime.json'
    $info.EnvironmentVariables['ENCODINGDB_SUITE_CACHE_DIR'] = Join-Path $state 'suite-cache'
    $info.EnvironmentVariables['ENCODINGDB_SUITE_PACK_PATH'] = Join-Path $repo 'encodingdb-test-suite-v1.tar.gz'
    $info.EnvironmentVariables['ENCODINGDB_STATE_DIR'] = Join-Path $outputRoot 'host-state'
    $info.EnvironmentVariables['LOCALAPPDATA'] = Join-Path $state 'localappdata'
    $info.EnvironmentVariables['TEMP'] = Join-Path $state 'tmp'; $info.EnvironmentVariables['TMP'] = Join-Path $state 'tmp'
    $arguments = @('--no-submit','--base-url','http://127.0.0.1:9','--codec','libx264','--presets','fast','--queue-dir',$phase.queue,'--max-duration-minutes',"$MeasurementMinutes",'--max-storage-mb','3072')
    if ($Gui) { $arguments += '--gui' } else { $arguments += @('--cli','--campaign','full') }
    # Windows native argv quoting, including spaces, non-ASCII and trailing slashes.
    $quoted = @($arguments | ForEach-Object {
        $escaped = [Regex]::Replace([string]$_, '(\\*)"', '$1$1\"')
        '"' + [Regex]::Replace($escaped, '(\\+)$', '$1$1') + '"'
    })
    $info.Arguments = [string]::Join(' ', $quoted)
    if ($Name -eq 'prepare-stop') {
        $phase.sourcePackPath=Join-Path $repo 'encodingdb-test-suite-v1.tar.gz'
        $phase.sourcePackBefore=(Get-FileHash -LiteralPath $phase.sourcePackPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $phase.command = @($exe) + $arguments; $phase.executableSha256 = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLowerInvariant()
    $script:process = [Diagnostics.Process]::new(); $script:process.StartInfo=$info; [void]$script:process.Start()
    $record = Get-CimInstance Win32_Process -Filter "ProcessId=$($script:process.Id)" | Select-Object ProcessId, ParentProcessId, CreationDate, Name, ExecutablePath, CommandLine
    $script:owned[[string]$record.ProcessId] = $record
    $script:stdoutTask=$script:process.StandardOutput.ReadToEndAsync(); $script:stderrTask=$script:process.StandardError.ReadToEndAsync()
    $receipt.phases += $phase
    Record-Event 'packaged-process-started' $phase
    return $phase
}
function Save-ProcessOutput {
    if ($script:process -and $script:process.HasExited) {
        $script:currentPhase.exitCode=$script:process.ExitCode
        $script:stdoutTask.GetAwaiter().GetResult() | Set-Content (Join-Path $script:currentPhase.path 'stdout.log')
        $script:stderrTask.GetAwaiter().GetResult() | Set-Content (Join-Path $script:currentPhase.path 'stderr.log')
    }
}
function Wait-Encoder {
    Wait-Until { [void](Observe-Processes); return $script:currentPhase.encoderObserved } $AcquisitionSeconds 'Timed out before observing the packaged libx264 encoder; acquisition/launch not certified.'
}
function Wait-NoEncoders {
    Wait-Until { return @((Observe-Processes) | Where-Object { $_.Name -in @('ffmpeg.exe','ffprobe.exe') }).Count -eq 0 } 60 'Owned media process survived GUI cancellation.'
}
try {
    if ($Mode -eq 'Console') {
        $phase=Start-Owned 'seven-clips' $false; Wait-Encoder
        Wait-Until { [void](Observe-Processes); return $script:process.HasExited } (($MeasurementMinutes*60)+60) 'Seven-clip console campaign exceeded its deadline.'
        Save-ProcessOutput
        if ($phase.exitCode -ne 0) { throw "Seven-clip console returned $($phase.exitCode); not accepted as PASS." }
        $phase.survivors=@(Observe-Processes); if ($phase.survivors.Count) { throw 'Console left owned children running.' }; $phase.status='PASSED'
    } else {
        # A console screensaver lock interrupted the previous evidence run mid-phase. This per-thread
        # ES_CONTINUOUS|ES_DISPLAY_REQUIRED request lasts only for this harness process; it changes no
        # system power or lock setting.
        [void][EdbWindows]::SetThreadExecutionState([uint32]2147483650) # ES_DISPLAY_REQUIRED(0x80000002)|ES_CONTINUOUS(0x2)
        foreach ($name in @('prepare-stop','complete','stop','close')) {
            $phase=Start-Owned $name $true
            Wait-Until { return @(Get-OwnedWindows | Where-Object { [EdbWindows]::Text($_) -eq 'EncodingDB Windows Client' }).Count -eq 1 } 90 'BLOCKED_GUI_DESKTOP: no packaged GUI window appeared.'
            [void](Capture-Ui 'launch')
            # CLI settings initialize the GUI; retained manifests verify the actual recipe.
            Invoke-RunAction 'Start'
            if ($name -eq 'prepare-stop') {
                Wait-Until { [void](Observe-Processes); return $null -ne $phase.preparationProbe } $AcquisitionSeconds 'Source preparation probe was not observed.'
                if (@(Get-ChildItem -Path $phase.queue -Recurse -Filter 'manifest.json' -ErrorAction SilentlyContinue).Count) { throw 'Campaign already exists; preparation cancellation was not exercised.' }
                [void](Capture-Ui 'source-preparation')
                Invoke-RunAction 'Stop'; $phase.action='Stop during preparation'
                Wait-NoEncoders; Start-Sleep -Seconds 2; Wait-NoEncoders
                if (@(Get-CompletionMarkers).Count -or @(Get-ChildItem -Path $phase.queue -Recurse -Filter 'attempt-*.json' -ErrorAction SilentlyContinue).Count) { throw 'Measured work appeared during preparation cancellation.' }
                [void](Capture-Ui 'preparation-cancelled')
                $phase.sourcePackAfter=(Get-FileHash -LiteralPath $phase.sourcePackPath -Algorithm SHA256).Hash.ToLowerInvariant()
                $phase.preparationCache=@(Get-ChildItem -LiteralPath (Join-Path $phase.state 'suite-cache') -Recurse -File -ErrorAction SilentlyContinue | Select-Object FullName,Length)
                $phase.scope='Local-pack source preparation Stop; not a network-download resume test'
                $phase.visualStatusReview='PENDING_PARENT_INSPECTION'
            } else {
                Wait-Encoder
                if ($name -eq 'complete') {
                    Wait-Until {
                        $media=@((Observe-Processes) | Where-Object { $_.Name -in @('ffmpeg.exe','ffprobe.exe') })
                        return @(Get-CompletionMarkers).Count -gt 0 -and $media.Count -eq 0
                    } (($MeasurementMinutes*60)+60) 'GUI did not finish a durable campaign before its deadline.'
                    Start-Sleep -Seconds 2
                    [void](Capture-Ui 'locally-complete')
                    $phase.visualStatusReview='PENDING_PARENT_INSPECTION'
                } else {
                    # Cancel only after a durable measured attempt, while a later owned encode is active.
                    Wait-Until {
                        $measured=@(Get-ChildItem -Path $phase.queue -Recurse -Filter 'attempt-*.json' -ErrorAction SilentlyContinue | Where-Object { (Get-Content $_.FullName -Raw | ConvertFrom-Json).schedule.phase -eq 'measured' })
                        $encoding=@((Observe-Processes) | Where-Object { $_.Name -eq 'ffmpeg.exe' -and $_.CommandLine -match '(?:-c:v|-vcodec)\s+"?libx264' })
                        return $measured.Count -gt 0 -and $encoding.Count -gt 0
                    } (($MeasurementMinutes*60)+30) 'No later encode after a durable measured attempt; cancellation scenario not exercised.'
                    if ($name -eq 'stop') {
                        Invoke-RunAction 'Stop'; $phase.action='Stop'
                        Wait-NoEncoders
                        Start-Sleep -Seconds 2
                        Wait-NoEncoders
                        if (@(Get-CompletionMarkers).Count) { throw 'Stop arrived after campaign completion; cancellation was not exercised.' }
                        [void](Capture-Ui 'cancelled')
                        $phase.visualStatusReview='PENDING_PARENT_INSPECTION'
                    } else {
                        $windows=@(Get-OwnedWindows | Where-Object { [EdbWindows]::Text($_) -eq 'EncodingDB Windows Client' })
                        [void](Capture-Ui 'before-window-close'); [void][EdbWindows]::PostMessage($windows[0],0x0010,[IntPtr]::Zero,[IntPtr]::Zero)
                        Wait-Until { return $null -ne (Get-OwnedExitConfirmation) } 10 'Native Close confirmation did not appear.'
                        Confirm-ObservedExit; $phase.action='Close confirmed'
                        $phase.visualStatusReview='PENDING_PARENT_INSPECTION'
                    }
                }
            }
            if ($name -ne 'close') {
                $windows=@(Get-OwnedWindows | Where-Object { [EdbWindows]::Text($_) -eq 'EncodingDB Windows Client' })
                [void][EdbWindows]::PostMessage($windows[0],0x0010,[IntPtr]::Zero,[IntPtr]::Zero)
            }
            Wait-Until { [void](Observe-Processes); return $script:process.HasExited } 60 'GUI did not close after its owned worker stopped.'
            Save-ProcessOutput; $phase.survivors=@(Observe-Processes)
            if ($phase.survivors.Count) { throw 'GUI left owned children running.' }
            $phase.status='PASSED'
            Record-Event 'phase-completed' @{ name=$phase.name; status=$phase.status }
            # Keep journals/encodes under output; discard only this phase's clean source cache.
            Remove-Item -LiteralPath $phase.state -Recurse -Force
        }
    }
    $receipt.status='PENDING_EVIDENCE_VALIDATION'
} catch {
    $receipt.status= if ($_.Exception.Message -like 'BLOCKED_GUI_*') {'BLOCKED'} else {'FAILED'}
    $receipt.error=$_.Exception.Message
    $receipt.primaryError=@{ message=$_.Exception.Message; type=$_.Exception.GetType().FullName; stage=$script:operationStage; phase=$(if ($script:currentPhase) {$script:currentPhase.name} else {$null}); at=[DateTime]::UtcNow.ToString('o'); scriptStackTrace=$_.ScriptStackTrace }
    # Persist the initiating failure before diagnostic capture or cleanup can fail.
    Save-Json $receipt (Join-Path $modeRoot 'receipt.json')
    Record-Event 'phase-failed' $receipt.primaryError
    if ($script:currentPhase) { $script:currentPhase.status=$receipt.status; try { [void](Capture-Ui 'failure') } catch { Record-Event 'capture-failed' $_.Exception.Message } }
} finally {
    function Record-CleanupFailure([string]$Stage, [string]$Message, $OwnedProcess) {
        $failure=@{ stage=$Stage; message=$Message; at=[DateTime]::UtcNow.ToString('o') }
        if ($OwnedProcess) { $failure.processId=$OwnedProcess.ProcessId; $failure.creationDate=$OwnedProcess.CreationDate; $failure.name=$OwnedProcess.Name }
        $receipt.cleanupErrors+=@($failure)
        $receipt.status='FAILED'
        if (-not $receipt.error) { $receipt.error="Process cleanup/evidence failed: $Message" }
        Record-Event 'cleanup-failed' $failure
    }
    try {
        if ($script:process) {
            $alive=@(Observe-Processes)
            if ($alive.Count) {
                $receipt.cleanupForced=$true
                foreach ($item in $alive | Sort-Object ProcessId -Descending) {
                    try {
                        $candidate = Get-Process -Id $item.ProcessId -ErrorAction SilentlyContinue
                        if ($candidate -and [Math]::Abs(($candidate.StartTime.ToUniversalTime() - $item.CreationDate.ToUniversalTime()).TotalMilliseconds) -lt 1) { $candidate.Kill() }
                    } catch { Record-CleanupFailure 'kill-owned-process' $_.Exception.Message $item }
                }
                Start-Sleep -Seconds 1
            }
            $script:currentPhase.survivors=@(Observe-Processes)
            if ($script:currentPhase.survivors.Count) { Record-CleanupFailure 'verify-owned-exit' 'Owned processes survived cleanup.' $null }
            if ($script:process.HasExited) {
                $script:currentPhase.exitCode=$script:process.ExitCode
                if ($script:stdoutTask.IsCompleted -and $script:stderrTask.IsCompleted) { Save-ProcessOutput }
                else { Record-CleanupFailure 'capture-owned-output' 'Owned output streams remain open after cleanup; no unbounded read attempted.' $null }
            }
        }
    } catch { Record-CleanupFailure 'cleanup-or-evidence' $_.Exception.Message $null }
    $receipt.finishedAt=[DateTime]::UtcNow.ToString('o')
    Save-Json $receipt (Join-Path $modeRoot 'receipt.json')
}
if ($receipt.status -ne 'PENDING_EVIDENCE_VALIDATION') { throw "$($receipt.status): $($receipt.error)" }
python (Join-Path $PSScriptRoot 'verify_windows_native_gui.py') --receipt (Join-Path $modeRoot 'receipt.json') --suite-manifest (Join-Path $repo 'client/resources/test_suite_v1/manifest.json') --runtime-lock (Join-Path $repo 'encodingdb-client-windows-console.exe.runtime-lock.json')
if ($LASTEXITCODE -ne 0) { throw 'Native journal/helper evidence validation failed.' }
