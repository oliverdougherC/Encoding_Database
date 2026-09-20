param([Parameter(Mandatory=$true)][string]$Root,[Parameter(Mandatory=$true)][long]$Handle,[Parameter(Mandatory=$true)][int]$Owner,[Parameter(Mandatory=$true)][string]$Label)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;using System.Runtime.InteropServices;
public static class EdbClientCapture {
 public struct Rect {public int Left,Top,Right,Bottom;} public struct Point {public int X,Y;}
 [DllImport("user32.dll")] public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr c);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);
 [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h,out Rect r);
 [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h,ref Point p);
 [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(Point p);
 [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h,uint flags);
}
'@
$dir=Join-Path $Root ('owned-client-capture-'+$Label);New-Item -ItemType Directory -Path $dir -ErrorAction Stop|Out-Null
$receipt=[ordered]@{scope='Read-only owned client-area capture; no input/activation';status='RUNNING';targetHandle=$Handle;owner=$Owner;sessionId=(Get-Process -Id $PID).SessionId}
$old=[EdbClientCapture]::SetThreadDpiAwarenessContext([IntPtr]::new(-4))
try {
 $target=[IntPtr]::new($Handle);[uint32]$actual=0;[void][EdbClientCapture]::GetWindowThreadProcessId($target,[ref]$actual)
 if($actual -ne $Owner){throw 'Target ownership changed'}
 $rect=[EdbClientCapture+Rect]::new();$point=[EdbClientCapture+Point]::new()
 if(![EdbClientCapture]::GetClientRect($target,[ref]$rect) -or ![EdbClientCapture]::ClientToScreen($target,[ref]$point)){throw 'No live client bounds'}
 $width=$rect.Right-$rect.Left;$height=$rect.Bottom-$rect.Top
 foreach($x in @(12,[int]($width/2),($width-12))){foreach($y in @(12,[int]($height/2),($height-12))){
  $sample=[EdbClientCapture+Point]::new();$sample.X=$point.X+$x;$sample.Y=$point.Y+$y
  if([EdbClientCapture]::GetAncestor([EdbClientCapture]::WindowFromPoint($sample),2) -ne $target){throw 'Owned client area is occluded; no screenshot captured'}
 }}
 $bitmap=[Drawing.Bitmap]::new($width,$height);$graphics=[Drawing.Graphics]::FromImage($bitmap)
 try{$graphics.CopyFromScreen($point.X,$point.Y,0,0,[Drawing.Size]::new($width,$height));$bitmap.Save((Join-Path $dir 'client.png'),[Drawing.Imaging.ImageFormat]::Png)}finally{$graphics.Dispose();$bitmap.Dispose()}
 $receipt.clientArea=@{left=$point.X;top=$point.Y;width=$width;height=$height};$receipt.status='CAPTURED'
}catch{$receipt.status='BLOCKED';$receipt.error=$_.Exception.Message}
finally{if($old -ne [IntPtr]::Zero){[void][EdbClientCapture]::SetThreadDpiAwarenessContext($old)};$receipt|ConvertTo-Json -Depth 6|Set-Content (Join-Path $dir 'receipt.json') -Encoding utf8}
