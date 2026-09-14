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
$script:harnessDeadline = [DateTime]::UtcNow.AddSeconds(($MeasurementMinutes*60)+$AcquisitionSeconds)
$receipt = [ordered]@{
    schemaVersion = 1; status = 'RUNNING'; mode = $Mode; startedAt = [DateTime]::UtcNow.ToString('o')
    sourceCommit = (git -C $repo rev-parse HEAD); runnerImage = $env:ImageOS; runnerImageVersion = $env:ImageVersion
    os = (Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber, OSArchitecture)
    computer = (Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer, Model)
    interactive = [Environment]::UserInteractive; sessionId = (Get-Process -Id $PID).SessionId
    scope = 'GitHub hosted virtualized Windows software acceptance; no physical Windows/GPU certification or submissions'
    phases = @(); error = $null; cleanupForced = $false
}
function Save-Json($Value, [string]$Path) { $Value | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $Path -Encoding utf8 }
function Record-Event([string]$Kind, $Data) {
    $event = @{ at = [DateTime]::UtcNow.ToString('o'); kind = $Kind; data = $Data }
    $event | ConvertTo-Json -Depth 12 -Compress | Add-Content -LiteralPath (Join-Path $modeRoot 'events.jsonl') -Encoding utf8
}
Save-Json $receipt (Join-Path $modeRoot 'receipt.json')
try {
Add-Type -AssemblyName System.Windows.Forms, System.Drawing, UIAutomationClient, UIAutomationTypes
Add-Type @'
using System; using System.Collections.Generic; using System.Runtime.InteropServices; using System.Text;
public static class EdbWindows {
 public struct Rect { public int Left, Top, Right, Bottom; }
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out Rect r);
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
 [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h,uint m,IntPtr w,IntPtr l);
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
}
function Invoke-Observed([string]$Name) {
    $observed = @(Capture-Ui ("before-action-" + ($Name -replace '\W','')))
    $matches = @($observed | Where-Object { $_.Current.Name.Replace('&','') -eq $Name -and $_.Current.IsEnabled -and -not $_.Current.IsOffscreen })
    if ($matches.Count -ne 1) { throw "BLOCKED_GUI_AUTOMATION: expected one observed enabled '$Name'; found $($matches.Count). Screenshots and trees retained." }
    $element = $matches[0]; $observedProcessId = $element.Current.ProcessId; $pattern = $null
    if ($element.TryGetCurrentPattern([Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) { $pattern.Invoke() }
    else { throw "BLOCKED_GUI_AUTOMATION: '$Name' exposes no invoke pattern." }
    Record-Event 'observed-control-invoked' @{name=$Name; processId=$observedProcessId}
}
function Send-RunShortcut([ValidateSet('Start','Stop')][string]$Action) {
    [void](Capture-Ui "before-shortcut-$Action")
    $roots=@(Get-OwnedWindows | Where-Object { [EdbWindows]::Text($_) -eq 'EncodingDB Windows Client' })
    if ($roots.Count -ne 1) { throw 'BLOCKED_GUI_FOCUS: expected one observed owned client window.' }
    $handle=$roots[0]
    [void][EdbWindows]::ShowWindow($handle,9)
    [void][EdbWindows]::SetForegroundWindow($handle)
    Wait-Until { return [EdbWindows]::GetForegroundWindow() -eq $handle } 5 'BLOCKED_GUI_FOCUS: client did not receive foreground focus; no keys sent.'
    $keys=if ($Action -eq 'Start') {'%r'} else {'%s'}
    [Windows.Forms.SendKeys]::SendWait($keys)
    Record-Event 'documented-shortcut-sent' @{ action=$Action; keys=$keys; observedHandle=$handle.ToInt64() }
}
function Get-CompletionMarkers {
    return @(Get-ChildItem -Path $script:currentPhase.queue -Recurse -Filter 'campaign-complete.json' -ErrorAction SilentlyContinue)
}
function Wait-Until([scriptblock]$Condition, [int]$Seconds, [string]$Failure) {
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    if ($deadline -gt $script:harnessDeadline) { $deadline = $script:harnessDeadline }
    do { if (& $Condition) { return }; Start-Sleep -Milliseconds 250 } while ([DateTime]::UtcNow -lt $deadline)
    throw $Failure
}
function Start-Owned([string]$Name, [bool]$Gui) {
    $phasePath = Join-Path $modeRoot $Name; New-Item -ItemType Directory $phasePath | Out-Null
    $state = Join-Path $env:RUNNER_TEMP ("encodingdb-native-$Mode-$Name-" + [Guid]::NewGuid().ToString('N') + '-' + [char]0x00E9)
    New-Item -ItemType Directory -Force (Join-Path $state 'tmp') | Out-Null
    $phase = @{ name=$Name; path=$phasePath; status='RUNNING'; helpers=@{}; encoderObserved=$false; queue= (Join-Path $phasePath ('queue-' + [char]0x00E9)); state=$state; exitCode=$null; survivors=@(); action=$null }
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
    $phase.command = @($exe) + $arguments; $phase.executableSha256 = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLowerInvariant()
    $script:process = [Diagnostics.Process]::new(); $script:process.StartInfo=$info; [void]$script:process.Start()
    $record = Get-CimInstance Win32_Process -Filter "ProcessId=$($script:process.Id)" | Select-Object ProcessId, ParentProcessId, CreationDate, Name, ExecutablePath, CommandLine
    $script:owned[[string]$record.ProcessId] = $record
    $script:stdoutTask=$script:process.StandardOutput.ReadToEndAsync(); $script:stderrTask=$script:process.StandardError.ReadToEndAsync()
    Record-Event 'packaged-process-started' $phase
    $receipt.phases += $phase
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
        foreach ($name in @('complete','stop','close')) {
            $phase=Start-Owned $name $true
            Wait-Until { return @(Get-OwnedWindows | Where-Object { [EdbWindows]::Text($_) -eq 'EncodingDB Windows Client' }).Count -eq 1 } 90 'BLOCKED_GUI_DESKTOP: no packaged GUI window appeared.'
            [void](Capture-Ui 'launch')
            # CLI settings initialize the GUI; retained manifests verify the actual recipe.
            Send-RunShortcut 'Start'; Wait-Encoder
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
                    Send-RunShortcut 'Stop'; $phase.action='Stop'
                    Wait-NoEncoders
                    Start-Sleep -Seconds 2
                    Wait-NoEncoders
                    if (@(Get-CompletionMarkers).Count) { throw 'Stop arrived after campaign completion; cancellation was not exercised.' }
                    [void](Capture-Ui 'cancelled')
                    $phase.visualStatusReview='PENDING_PARENT_INSPECTION'
                } else {
                    $windows=@(Get-OwnedWindows | Where-Object { [EdbWindows]::Text($_) -eq 'EncodingDB Windows Client' })
                    [void](Capture-Ui 'before-window-close'); [void][EdbWindows]::PostMessage($windows[0],0x0010,[IntPtr]::Zero,[IntPtr]::Zero)
                    Wait-Until { return @(Get-Elements | Where-Object { $_.Current.Name.Replace('&','') -eq 'Yes' }).Count -gt 0 } 10 'Native Close confirmation did not appear.'
                    Invoke-Observed 'Yes'; $phase.action='Close confirmed'
                    $phase.visualStatusReview='PENDING_PARENT_INSPECTION'
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
            # Keep journals/encodes under output; discard only this phase's clean source cache.
            Remove-Item -LiteralPath $phase.state -Recurse -Force
        }
    }
    $receipt.status='PENDING_EVIDENCE_VALIDATION'
} catch {
    $receipt.status= if ($_.Exception.Message -like 'BLOCKED_GUI_*') {'BLOCKED'} else {'FAILED'}
    $receipt.error=$_.Exception.Message
    if ($script:currentPhase) { $script:currentPhase.status=$receipt.status; try { [void](Capture-Ui 'failure') } catch { Record-Event 'capture-failed' $_.Exception.Message } }
} finally {
    try {
    if ($script:process) {
        $alive=@(Observe-Processes)
        if ($alive.Count) {
            $receipt.cleanupForced=$true
            foreach ($item in $alive | Sort-Object ProcessId -Descending) {
                $candidate = Get-Process -Id $item.ProcessId -ErrorAction SilentlyContinue
                if ($candidate -and [Math]::Abs(($candidate.StartTime.ToUniversalTime() - $item.CreationDate.ToUniversalTime()).TotalMilliseconds) -lt 1) { $candidate.Kill() }
            }
            Start-Sleep -Seconds 1
        }
        Save-ProcessOutput
    }
    } catch { $receipt.status='FAILED'; $receipt.error="Process cleanup/evidence failed: $($_.Exception.Message)" }
    $receipt.finishedAt=[DateTime]::UtcNow.ToString('o')
    Save-Json $receipt (Join-Path $modeRoot 'receipt.json')
}
if ($receipt.status -ne 'PENDING_EVIDENCE_VALIDATION') { throw "$($receipt.status): $($receipt.error)" }
python (Join-Path $PSScriptRoot 'verify_windows_native_gui.py') --receipt (Join-Path $modeRoot 'receipt.json') --suite-manifest (Join-Path $repo 'client/resources/test_suite_v1/manifest.json') --runtime-lock (Join-Path $repo 'encodingdb-client-windows-console.exe.runtime-lock.json')
if ($LASTEXITCODE -ne 0) { throw 'Native journal/helper evidence validation failed.' }
