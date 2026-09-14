import errno,json,os,plistlib,shutil,subprocess
from pathlib import Path
import run_packaged_faults as h
root=h.ROOT/'disk-full';root.mkdir(exist_ok=True)
image=root/'bounded-64MiB.dmg';queue=h.WORK/'recovery-queue';backup=root/'host-queue-backup'
if image.exists() or backup.exists():raise RuntimeError('Refusing to overwrite prior disk-full evidence')
campaign=next((queue/'campaigns').iterdir()).name
assert (queue/'campaigns'/campaign/'campaign-complete.json').exists(),'Recovery campaign must finish first'
prior=h.snapshot(queue)
assert any(row['schedule']['phase']=='measured' for row in prior.values())
subprocess.run(['hdiutil','create','-size','64m','-fs','HFS+','-volname','EncodingDBFault20260914','-type','UDIF','-nospotlight',str(image)],check=True,capture_output=True)
queue.rename(backup);queue.mkdir()
device=None
try:
 attached=plistlib.loads(subprocess.check_output(['hdiutil','attach','-nobrowse','-mountpoint',str(queue),'-plist',str(image)]))
 device=next(e['dev-entry'] for e in attached['system-entities'] if 'mount-point' in e)
 h.save('disk-full-attachment',{'image':str(image),'mount':str(queue),'device':device,'entities':attached['system-entities']})
 space=os.statvfs(queue)
 assert os.path.ismount(queue) and queue.stat().st_dev!=root.stat().st_dev
 assert space.f_blocks*space.f_frsize<=128*1024*1024,'Refusing to fill host filesystem'
 shutil.copytree(backup,queue,dirs_exist_ok=True)
 h.save('disk-full-before',prior)
 filler=queue/'owned-filler.bin';written=0;observed=None
 with filler.open('wb',buffering=0) as handle:
  while written<128*1024*1024:
   try:written+=handle.write(b'\0'*(1024*1024))
   except OSError as error:
    if error.errno!=errno.ENOSPC:raise
    observed={'errno':error.errno,'message':str(error)};break
 assert observed,'Fixed volume did not produce ENOSPC'
 command=[h.WORK/'encodingdb-client-macos','--resume-campaign',campaign,'--no-submit','--queue-dir',queue]
 result=h.finish(h.launch('disk-full',command),180)
 result.update(volumeBytes=space.f_blocks*space.f_frsize,fillerBytes=written,osError=observed,method='Completed journal replay on private full HFS+ volume; no re-encoding requested',priorRecordsUnchanged=all(Path(p).exists() and h.sha(p)==row['recordSha256'] and(not row['artifactPath'] or h.sha(row['artifactPath'])==row['artifactSha256'])for p,row in prior.items()))
 assert result['exitCode']==6 and result['priorRecordsUnchanged']
 filler.unlink()
 shutil.copytree(queue,h.LOGS/'disk-full-retained-queue',dirs_exist_ok=True)
 h.save('disk-full',result)
finally:
 if device:subprocess.run(['hdiutil','detach',device],check=True,capture_output=True)
 if queue.exists():queue.rmdir()
 backup.rename(queue)
 h.save('disk-full-detached',{'device':device,'detached':True,'imageSha256':h.sha(image),'originalHostQueueRestored':True})
 h.proxy.shutdown()
