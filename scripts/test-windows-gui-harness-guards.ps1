# Pure operator tests: parse the real functions and provide synthetic native observations.
# No user32 calls, windows, input, screenshots, process inventory, or client execution.
param([string]$Harness=(Join-Path $PSScriptRoot 'test-windows-native-gui.ps1'))
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$tokens=$null; $parseErrors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Harness,[ref]$tokens,[ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
foreach ($name in @('Get-OwnedExitConfirmation','Record-CleanupFailure')) {
    $definitions=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true))
    if ($definitions.Count -ne 1) { throw "Expected one real $name definition." }
    Invoke-Expression $definitions[0].Extent.Text
}
Add-Type @'
using System; using System.Collections.Generic;
public static class EdbWindows {
 public sealed class Window { public long Parent; public string Text,Class; public int Control; public bool Visible=true,Enabled=true; public uint Owner=42; }
 public static Dictionary<long,Window> Data=new Dictionary<long,Window>();
 public static string Text(IntPtr h){return Data[h.ToInt64()].Text;}
 public static string Class(IntPtr h){return Data[h.ToInt64()].Class;}
 public static IntPtr GetParent(IntPtr h){return new IntPtr(Data[h.ToInt64()].Parent);}
 public static int GetDlgCtrlID(IntPtr h){return Data[h.ToInt64()].Control;}
 public static bool IsWindowVisible(IntPtr h){return Data[h.ToInt64()].Visible;}
 public static bool IsWindowEnabled(IntPtr h){return Data[h.ToInt64()].Enabled;}
 public static uint GetWindowThreadProcessId(IntPtr h,out uint owner){owner=Data[h.ToInt64()].Owner;return 7;}
 public static IntPtr[] Windows(IntPtr h){var result=new List<IntPtr>();foreach(var item in Data)if(item.Value.Parent==h.ToInt64())result.Add(new IntPtr(item.Key));return result.ToArray();}
}
'@
$script:roots=@()
function Get-OwnedWindows { return $script:roots }
function Assert-True([bool]$Value,[string]$Message) { if (-not $Value) { throw $Message } }
function Assert-Throws([scriptblock]$Action,[string]$Pattern) {
    $caught=$false
    try { & $Action | Out-Null } catch { $caught=$_.Exception.Message -like $Pattern }
    Assert-True $caught "Expected error matching $Pattern"
}
function Ready-Fixture {
    [EdbWindows]::Data.Clear()
    $dialog=[EdbWindows+Window]::new();$dialog.Text='Exit';$dialog.Class='#32770'
    $button=[EdbWindows+Window]::new();$button.Text='&Yes';$button.Class='Button';$button.Parent=1;$button.Control=6
    [EdbWindows]::Data.Add(1,$dialog);[EdbWindows]::Data.Add(2,$button)
    $script:roots=@([IntPtr]1)
}
Assert-True ($null -eq (Get-OwnedExitConfirmation)) 'Absent dialog must wait.'
Ready-Fixture
$ready=Get-OwnedExitConfirmation
Assert-True ($ready.dialog -eq [IntPtr]1 -and $ready.button -eq [IntPtr]2 -and $ready.owner -eq 42) 'Ready native identities changed.'
foreach ($field in @('Visible','Enabled')) {
    Ready-Fixture;[EdbWindows]::Data[2].$field=$false
    Assert-True ($null -eq (Get-OwnedExitConfirmation)) "$field guard was bypassed."
}
Ready-Fixture;[EdbWindows]::Data[2].Control=7
Assert-True ($null -eq (Get-OwnedExitConfirmation)) 'Only IDYES is accepted.'
Ready-Fixture;[EdbWindows]::Data[2].Parent=9
Assert-True ($null -eq (Get-OwnedExitConfirmation)) 'Only a direct dialog child is accepted.'
Ready-Fixture;[EdbWindows]::Data[2].Text='No'
Assert-True ($null -eq (Get-OwnedExitConfirmation)) 'Only observed Yes is accepted.'
Ready-Fixture;[EdbWindows]::Data[2].Class='Pane'
Assert-True ($null -eq (Get-OwnedExitConfirmation)) 'Only a native Button is accepted.'
Ready-Fixture;[EdbWindows]::Data[1].Class='TkTopLevel'
Assert-True ($null -eq (Get-OwnedExitConfirmation)) 'Only a native Exit dialog is accepted.'
Ready-Fixture;[EdbWindows]::Data[2].Owner=99
Assert-Throws {Get-OwnedExitConfirmation} '*owner differs*'
Ready-Fixture;[EdbWindows]::Data.Add(3,[EdbWindows]::Data[1]);$script:roots+=([IntPtr]3)
Assert-Throws {Get-OwnedExitConfirmation} '*multiple owned native Exit dialogs*'
Ready-Fixture;[EdbWindows]::Data.Add(3,[EdbWindows]::Data[2])
Assert-Throws {Get-OwnedExitConfirmation} '*multiple observed enabled native Yes buttons*'
$script:events=@()
function Record-Event([string]$Kind,$Data) { $script:events+=@{kind=$Kind;data=$Data} }
$receipt=@{status='BLOCKED';error='original failure';primaryError=@{message='original failure';stage='close readiness'};cleanupErrors=@()}
$owned=[pscustomobject]@{ProcessId=123;CreationDate=[DateTime]'2026-09-20T00:00:00Z';Name='owned.exe'}
Record-CleanupFailure 'kill-owned-process' 'access denied' $owned
Record-CleanupFailure 'verify-owned-exit' 'survivor' $null
Assert-True ($receipt.error -eq 'original failure' -and $receipt.primaryError.stage -eq 'close readiness') 'Cleanup overwrote the initiating failure.'
Assert-True ($receipt.status -eq 'FAILED' -and $receipt.cleanupErrors.Count -eq 2 -and $script:events.Count -eq 2) 'Separate cleanup failures were lost.'
Assert-True ($receipt.cleanupErrors[0].processId -eq 123 -and $receipt.cleanupErrors[0].creationDate -eq $owned.CreationDate) 'Owned process identity was lost.'
$receipt=@{status='PENDING_EVIDENCE_VALIDATION';error=$null;primaryError=$null;cleanupErrors=@()}
Record-CleanupFailure 'capture-owned-output' 'pipe still open' $null
Assert-True ($receipt.error -eq 'Process cleanup/evidence failed: pipe still open') 'Cleanup-only failure was not reported.'
Write-Output 'PASS: real native-readiness and primary-error preservation functions; synthetic observations only, no Windows interaction.'
