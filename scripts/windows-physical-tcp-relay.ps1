# Minimal loopback TCP relay: 127.0.0.1:3199 -> chain endpoint (Mac forward to P910 candidate).
# Used so the Windows client can keep its loopback base-url while traffic chains Mac -> P910.
# Single-threaded non-blocking poller: every open connection is serviced every tick, so an
# idle keep-alive connection can never starve a new one. No per-connection threads.
param(
 [int]$ListenPort=3199,
 [string]$RemoteHost='100.96.210.77',
 [int]$RemotePort=3299
)
$ErrorActionPreference='Stop'
$listener=[System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback,$ListenPort)
$listener.Start()
$conns=New-Object 'System.Collections.Generic.List[object]'
$buf=New-Object byte[] 65536
 function Pump-Once($sock,$a,$b,$acc){
  # Move any immediately-readable bytes a->b; return $false when either side closed.
  # NetworkStream has no Poll in .NET Framework; the underlying Socket does.
  try {
   if ($sock.Poll(0,'SelectRead')) {
    $n=$a.Read($acc,0,$acc.Length)
    if ($n -le 0) { return $false }
    $b.Write($acc,0,$n); $b.Flush()
   }
   return $true
  } catch { return $false }
 }
while($true){
 if ($listener.Pending()) {
  try {
   $client=$listener.AcceptTcpClient()
   $remote=[System.Net.Sockets.TcpClient]::new()
   $iar=$remote.BeginConnect($RemoteHost,$RemotePort,$null,$null)
   if (-not $iar.AsyncWaitHandle.WaitOne(5000)) { $client.Close(); $remote.Close() }
   elseif (-not $remote.Connected) { $client.Close(); $remote.Close() }
   else {
    $remote.EndConnect($iar)
    $conns.Add([pscustomobject]@{client=$client;remote=$remote;cs=$client.GetStream();rs=$remote.GetStream()})
   }
  } catch { try{$client.Close()}catch{}; try{$remote.Close()}catch{} }
 }
 $dead=@()
 foreach($c in $conns){
  $alive = (Pump-Once $c.client.Client $c.cs $c.rs $buf) -and (Pump-Once $c.remote.Client $c.rs $c.cs $buf)
  if (-not $alive) { $dead+=$c }
 }
 foreach($c in $dead){
  try{$c.client.Close()}catch{}; try{$c.remote.Close()}catch{}
  $conns.Remove($c) | Out-Null
 }
 Start-Sleep -Milliseconds 2
}
