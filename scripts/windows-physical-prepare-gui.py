#!/usr/bin/env python3
"""Adapt only operator paths/scope/capture bounds for the physical desktop."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--root',type=Path,required=True)
p.add_argument('--label',required=True)
p.add_argument('--revision',required=True)
p.add_argument('--harness-dir',type=Path)
p.add_argument('--harness-sha256')
p.add_argument('--harness-revision')
p.add_argument('--run-label')
p.add_argument('--caption-activation',action='store_true')
a=p.parse_args()
if not re.fullmatch('[a-z0-9-]{1,40}',a.label) or not re.fullmatch('[0-9a-f]{40}',a.revision):raise ValueError('Invalid source label/revision')
run_label=a.run_label or a.label
if not re.fullmatch('[a-z0-9-]{1,40}',run_label):raise ValueError('Invalid run label')
root=a.root.resolve(strict=True);source=root/('source-'+a.label)
if subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()!=a.revision:raise ValueError('Source revision differs')
driver=root/('gui-driver-'+run_label);driver.mkdir(exist_ok=False)
harness_dir=a.harness_dir.resolve(strict=True) if a.harness_dir else source/'scripts'
original=harness_dir/'test-windows-native-gui.ps1'
if a.harness_dir and (not re.fullmatch('[0-9a-f]{64}',a.harness_sha256 or '') or hashlib.sha256(original.read_bytes()).hexdigest()!=a.harness_sha256):raise ValueError('Reviewed external harness hash differs')
text=original.read_text()
changes=[]
def replace_once(old,new,reason):
    global text
    if text.count(old)!=1:raise ValueError('Expected unique source fragment: '+reason)
    text=text.replace(old,new);changes.append(reason)
def psquote(value):return "'"+str(value).replace("'","''")+"'"
replace_once('$repo = Split-Path -Parent $PSScriptRoot','$repo = '+psquote(source),'Bind operator to exact candidate checkout')
replace_once("scope = 'GitHub hosted virtualized Windows software acceptance; no physical Windows/GPU certification or submissions'", "scope = 'Physical Windows desktop GUI software acceptance; no submissions; packaged source unchanged'",'Record actual physical scope')
replace_once("$info.EnvironmentVariables['ENCODINGDB_STATE_DIR'] = Join-Path $outputRoot 'host-state'", "$info.EnvironmentVariables['ENCODINGDB_STATE_DIR'] = "+psquote(root/'host-state'),'Preserve the existing physical installation identity')
replace_once('    $bounds = [Windows.Forms.SystemInformation]::VirtualScreen',r'''    # Capture only the observed owned application windows, intersected with visible monitors.
    $rectangles=@(foreach ($ownedHandle in @(Get-OwnedWindows)) {
        $ownedRect=[EdbWindows+Rect]::new()
        if ([EdbWindows]::GetWindowRect($ownedHandle,[ref]$ownedRect) -and $ownedRect.Right -gt $ownedRect.Left -and $ownedRect.Bottom -gt $ownedRect.Top) { $ownedRect }
    })
    if (!$rectangles.Count) { throw 'No observed owned window bounds available for capture.' }
    $screen=[Windows.Forms.SystemInformation]::VirtualScreen
    $left=[Math]::Max(($rectangles.Left | Measure-Object -Minimum).Minimum,$screen.Left)
    $top=[Math]::Max(($rectangles.Top | Measure-Object -Minimum).Minimum,$screen.Top)
    $right=[Math]::Min(($rectangles.Right | Measure-Object -Maximum).Maximum,$screen.Right)
    $bottom=[Math]::Min(($rectangles.Bottom | Measure-Object -Maximum).Maximum,$screen.Bottom)
    if ($right -le $left -or $bottom -le $top) { throw 'Owned windows are outside visible monitor bounds.' }
    $bounds=[Drawing.Rectangle]::FromLTRB($left,$top,$right,$bottom)''','Crop screenshots to observed owned client window bounds')
# The reviewed harness now natively aligns capture/observation coordinates with
# SetThreadDpiAwarenessContext; do not re-inject DPI patches into it.
if a.caption_activation:
    caption_source=Path(__file__).with_name('windows-owned-caption.cs')
    shutil.copyfile(caption_source,driver/caption_source.name)
    replace_once('Add-Type -AssemblyName System.Windows.Forms, System.Drawing, UIAutomationClient, UIAutomationTypes', 'Add-Type -AssemblyName System.Windows.Forms, System.Drawing, UIAutomationClient, UIAutomationTypes\nAdd-Type -Path (Join-Path $PSScriptRoot "windows-owned-caption.cs")', 'Load reviewed operator-only caption activation helper')
    replace_once('    [void][EdbWindows]::ShowWindow($handle,9)\n    [void][EdbWindows]::SetForegroundWindow($handle)\n    Wait-Until', '    if (-not $script:currentPhase.ContainsKey("captionActivation")) {\n        [uint32]$captionOwner=0; [void][EdbWindows]::GetWindowThreadProcessId($handle,[ref]$captionOwner)\n        $caption=[EdbOwnedCaption]::ClickOnce($handle,$captionOwner)\n        $script:currentPhase.captionActivation=$caption\n        Record-Event "owned-caption-input" $caption\n        if ($caption.Error) { throw "BLOCKED_GUI_CAPTION: $($caption.Error)" }\n    }\n    Wait-Until', 'One guarded native caption click per fresh owned window; no activation retry ladder')
else:
    replace_once('    [void][EdbWindows]::SetForegroundWindow($handle)\n    Wait-Until', '    [void][EdbWindows]::SetForegroundWindow($handle)\n    if ([EdbWindows]::GetForegroundWindow() -ne $handle) {\n        [uint32]$ownedProcessId=0; [void][EdbWindows]::GetWindowThreadProcessId($handle,[ref]$ownedProcessId)\n        $activationShell=New-Object -ComObject WScript.Shell\n        try { $activated=$activationShell.AppActivate([int]$ownedProcessId) }\n        finally { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($activationShell) }\n        Record-Event "owned-app-activation" @{ processId=$ownedProcessId; succeeded=$activated }\n    }\n    Wait-Until', 'Attempt normal activation of observed owned PID; preserve foreground guard')
replace_once('python (Join-Path $PSScriptRoot', '& '+psquote(root/('source-'+a.label)/'.build/clients/windows/venv/Scripts/python.exe')+' (Join-Path $PSScriptRoot', 'Bind evidence verifier to the declared source-local venv Python')
# The harness and verifier retain the same four phases and all acceptance checks.
output=driver/'test-windows-native-gui.ps1';output.write_text(text,encoding='utf-8-sig')
verifier=harness_dir/'verify_windows_native_gui.py'
if hashlib.sha256(verifier.read_bytes()).digest()!=hashlib.sha256((source/'scripts/verify_windows_native_gui.py').read_bytes()).digest():raise ValueError('Acceptance verifier changed')
shutil.copyfile(verifier,driver/verifier.name)
receipt={'kind':'physical-desktop-operator-adaptation','sourceRevision':a.revision,'operatorRunLabel':run_label,'operatorHarnessRevision':a.harness_revision or a.revision,'sourceHarnessSha256':hashlib.sha256(original.read_bytes()).hexdigest(),'driverSha256':hashlib.sha256(output.read_bytes()).hexdigest(),'verifierSha256':hashlib.sha256(verifier.read_bytes()).hexdigest(),'changes':changes,'packagedClientModified':False,'acceptanceCriteriaModified':False,'captionHelperSha256':hashlib.sha256((driver/'windows-owned-caption.cs').read_bytes()).hexdigest() if a.caption_activation else None}
(driver/'adaptation.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt))
