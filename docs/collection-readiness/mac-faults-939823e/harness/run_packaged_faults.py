import argparse, datetime, fcntl, hashlib, json, os, shutil, signal, subprocess, threading, time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import psutil

ROOT=Path('/Users/ofhd/Developer/Encoding_Database/.build/native-faults-939823e')
SOURCE='939823ead2c052572f9deb5c9f91c85435d5661d'
EXPECTED_SHA='ad01bfd36ad84e0e0d9f45730bd195c1b940a240493d093f6a875faa97a6f2c0'
OWNED=[]
PACKAGE=Path('/Users/ofhd/Developer/Encoding_Database/.build/release-20260919/macos-939823e')
WORK=ROOT/'épreuve 客户端'
CACHE=Path('/Users/ofhd/Developer/Encoding_Database/.build/native-faults-20260914/épreuve 客户端/clean-cache')
STATE=Path('/Users/ofhd/Developer/Encoding_Database/.build/release-20260914/mac-host-state')
PACK='encodingdb-test-suite-v1.tar.gz'
LOGS=ROOT/'receipts'
LOGS.mkdir(parents=True,exist_ok=True)
WORK.mkdir(parents=True,exist_ok=True)
requests=[]
class LocalFailureProxy(BaseHTTPRequestHandler):
 def do_CONNECT(self):
  requests.append({'method':'CONNECT','target':self.path,'time':time.time()});self.send_error(502,'Isolated test blocks external network')
 def do_GET(self):
  requests.append({'method':'GET','target':self.path,'time':time.time()});data=b'intentionally corrupt local fixture';self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def log_message(self,*args):pass
proxy=ThreadingHTTPServer(('127.0.0.1',0),LocalFailureProxy)
threading.Thread(target=proxy.serve_forever,daemon=True).start()

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def save(name,data):
 (LOGS/(name+'.json')).write_text(json.dumps(data,indent=2))
def env_for(name,cache=CACHE,pack=None):
 env=dict(os.environ)
 for key in list(env):
  if key.lower() in ("http_proxy","https_proxy","all_proxy","no_proxy"):env.pop(key)
 for k in ('FFMPEG_EXE','FFPROBE_EXE','ENCODINGDB_RUNTIME_LOCK_PATH','ENCODINGDB_FFMPEG_PATH','ENCODINGDB_FFPROBE_PATH','ENCODINGDB_RUNTIME_BUNDLE_DIR','PYTHONPATH','PYTHONHOME','DYLD_LIBRARY_PATH','DYLD_FALLBACK_LIBRARY_PATH','DYLD_INSERT_LIBRARIES','LD_LIBRARY_PATH','LD_PRELOAD','ENCODINGDB_PROTOCOL_STABILITY_THRESHOLD','ENCODINGDB_PROTOCOL_MAX_ADAPTIVE_REPEATS'):
  env.pop(k,None)
 endpoint=f'http://127.0.0.1:{proxy.server_port}'
 explicit={'ENCODINGDB_STATE_DIR':str(STATE),'ENCODINGDB_SUITE_CACHE_DIR':str(cache),'ENCODINGDB_DEBUG_TRACEBACK':'1','ENCODINGDB_PROTOCOL_SEED':'20260921',
  'ENCODINGDB_RUNTIME_EVIDENCE_PATH':str(LOGS/(name+'-embedded-runtime.json')),
  'HTTP_PROXY':endpoint,'HTTPS_PROXY':endpoint,'ALL_PROXY':endpoint,'NO_PROXY':'localhost,127.0.0.1'}
 explicit['ENCODINGDB_SUITE_PACK_PATH']=str(pack or (PACKAGE/PACK))
 env.update(explicit)
 return env,explicit

def launch(name,command,cache=CACHE,pack=None):
 env,explicit=env_for(name,cache,pack)
 path=LOGS/(name+'.log');handle=path.open('w')
 proc=subprocess.Popen(list(map(str,command)),stdin=subprocess.DEVNULL,stdout=handle,stderr=subprocess.STDOUT,env=env,start_new_session=True,cwd=WORK)
 track(proc.pid)
 info={'sourceCommit':SOURCE,'case':name,'startedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'command':list(map(str,command)),
       'environment':explicit,'pid':proc.pid,'processCreatedAt':psutil.Process(proc.pid).create_time(),'artifactSha256':sha(command[0]),'diagnosticNotCalibration':True,'proxyRequestStart':len(requests)}
 save(name+'-started',info)
 return proc,handle,info,time.monotonic()

def finish(run,timeout=360):
 proc,handle,info,started=run
 try:code=proc.wait(timeout=timeout)
 except subprocess.TimeoutExpired:
  try:
   for child in psutil.Process(proc.pid).children(recursive=True):track(child.pid)
  except psutil.NoSuchProcess:pass
  cleanup_owned()
  code=proc.wait(timeout=10);info['wallTimeout']=True
 handle.close();info.update(exitCode=code,wallSeconds=time.monotonic()-started,proxyRequests=requests[info.pop('proxyRequestStart'):])
 save(info['case'],info);print(json.dumps({'case':info['case'],'exit':code,'seconds':info['wallSeconds']}),flush=True)
 return info

def records(queue):
 out={}
 for path in (queue/'campaigns').glob('*/attempt-*.json'):
  try:
   row=json.loads(path.read_text());out[str(path)]=row
  except (OSError,ValueError):pass
 return out

def snapshot(queue):
 out={}
 for path,row in records(queue).items():
  artifact=(row.get('metadata',{}).get('info') or {}).get('artifactPath')
  out[path]={'recordSha256':sha(path),'schedule':row['schedule'],'timing':row.get('timing'),
             'artifactPath':artifact,'artifactSha256':sha(artifact) if artifact and Path(artifact).is_file() else None}
 return out

def stop_at_active(run,queue,need_measured,mode):
 proc,_,info,_=run;deadline=time.monotonic()+180
 while time.monotonic()<deadline and proc.poll() is None:
  if (ROOT/'PAUSE').exists():raise RuntimeError('Parent quiet window requested')
  previous=records(queue)
  eligible=[r for r in previous.values() if r.get('timing') and (not need_measured or r['schedule']['phase']=='measured')]
  if eligible:
   for path in (queue/'campaigns').glob('*/*.active.json'):
    try:
     active=json.loads(path.read_text());encoder=psutil.Process(active['pid']);owner=encoder.parent()
     if encoder.create_time()!=active['createdAt'] or encoder.cmdline()!=active['command']:continue
     if not owner or not (owner.pid==proc.pid or any(p.pid==proc.pid for p in owner.parents())):continue
     track(owner.pid);track(encoder.pid)
     prior=snapshot(queue);info['beforeStop']=prior;info['activeReceipt']=active;info['clientMainPid']=owner.pid;info['clientMainCreatedAt']=owner.create_time()
     info['signal']=mode;os.kill(owner.pid,signal.SIGINT if mode=='SIGINT' else signal.SIGKILL)
     save(info['case']+'-signal',info)
     result=finish(run,30)
     try:result['orphanAliveAfterStop']=encoder.is_running() and encoder.status()!=psutil.STATUS_ZOMBIE
     except psutil.NoSuchProcess:result['orphanAliveAfterStop']=False
     save(info['case'],result)
     return result,prior,path.parent.name
    except (FileNotFoundError,psutil.NoSuchProcess,psutil.ZombieProcess):continue
  time.sleep(0.05)
 result=finish(run,1);raise RuntimeError(f'No requested active phase observed: {result}')

def clone(src,dst):
 dst.parent.mkdir(parents=True,exist_ok=True)
 if not dst.exists():subprocess.run(['cp','-c',str(src),str(dst)],check=True)
 assert src.stat().st_ino != dst.stat().st_ino

def corrupt():
 folder=WORK/'corrupt-package';exe=folder/'encodingdb-client-macos'
 clone(PACKAGE/'encodingdb-client-macos',exe)
 corrupt_pack=Path('/Users/ofhd/Developer/Encoding_Database/.build/native-faults-20260914/épreuve 客户端/corrupt-package')/PACK
 expected=sha(corrupt_pack)
 assert corrupt_pack.stat().st_size==(PACKAGE/PACK).stat().st_size
 cache=WORK/'corrupt-cache';assert not cache.exists()
 os.environ['ENCODINGDB_SUITE_PACK_URL']=f'http://127.0.0.1:{proxy.server_port}/corrupt-pack'
 result=finish(launch('corrupt-pack',[exe,'--cli','--codec','libx264','--presets','fast','--no-submit','--queue-dir',WORK/'corrupt-queue'],cache,corrupt_pack),180)
 os.environ.pop('ENCODINGDB_SUITE_PACK_URL',None)
 result.update(corruptPackSha256=sha(corrupt_pack),referencePackSha256=sha(PACKAGE/PACK),corruptPackBytes=corrupt_pack.stat().st_size,referencePackBytes=(PACKAGE/PACK).stat().st_size,attemptRecords=len(records(WORK/'corrupt-queue')))
 assert result['exitCode']==3 and result['attemptRecords']==0 and result['corruptPackSha256']==expected and expected!=result['referencePackSha256']
 save('corrupt-pack',result)

def recovery():
 exe=WORK/'encodingdb-client-macos';queue=WORK/'recovery-queue'
 command=[exe,'--codec','libx264','--presets','veryslow','--no-submit','--max-duration-minutes','3','--queue-dir',queue]
 stopped,prior,campaign=stop_at_active(launch('cancel',command),queue,False,'SIGINT')
 assert stopped['exitCode']==130
 resume=[exe,'--resume-campaign',campaign,'--no-submit','--max-duration-minutes','3','--queue-dir',queue]
 killed,more,campaign=stop_at_active(launch('kill-after-resume',resume),queue,True,'SIGKILL')
 result=finish(launch('resume-after-kill',resume),300)
 result['priorRecordsUnchanged']=all(Path(p).exists() and sha(p)==row['recordSha256'] and (not row['artifactPath'] or sha(row['artifactPath'])==row['artifactSha256']) for p,row in more.items())
 result['preservedRecords']=more
 result['orphanReceiptRemoved']=not any((queue/'campaigns'/campaign).glob('*.active.json'))
 result['campaignId']=campaign
 active=killed['activeReceipt']
 try:
  old=psutil.Process(active['pid']);result['oldOrphanStillAlive']=old.create_time()==active['createdAt'] and old.is_running() and old.status()!=psutil.STATUS_ZOMBIE
 except psutil.NoSuchProcess:result['oldOrphanStillAlive']=False
 assert killed['orphanAliveAfterStop'] and not result['oldOrphanStillAlive']
 assert result['exitCode']==0 and result['priorRecordsUnchanged'] and result['orphanReceiptRemoved']
 save('resume-after-kill',result)

def track(pid):
 try:
  process=psutil.Process(pid)
  identity=(pid,process.create_time())
  if identity not in OWNED:OWNED.append(identity)
 except psutil.NoSuchProcess:pass


def cleanup_owned():
 results=[]
 for pid,created in reversed(OWNED):
  try:
   process=psutil.Process(pid)
   if process.create_time()!=created:continue
   if process.is_running() and process.status()!=psutil.STATUS_ZOMBIE:
    process.kill()
    try:process.wait(timeout=5)
    except psutil.TimeoutExpired:pass
   results.append({'pid':pid,'createdAt':created,'alive':process.is_running() and process.status()!=psutil.STATUS_ZOMBIE})
  except psutil.NoSuchProcess:results.append({'pid':pid,'createdAt':created,'alive':False})
 save('owned-cleanup',results)
 assert not any(row['alive'] for row in results)


if __name__=='__main__':
 assert sha(PACKAGE/'encodingdb-client-macos')==EXPECTED_SHA
 protected=[PACKAGE/PACK,*sorted((CACHE/'canonical').glob('*.mkv'))]
 protected_before={str(p):sha(p) for p in protected}
 save('protected-inputs-before',protected_before)
 clone(PACKAGE/'encodingdb-client-macos',WORK/'encodingdb-client-macos')
 with (STATE/'measurement.lock').open('a+b') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  save('host-lock',{'path':str(STATE/'measurement.lock'),'pid':os.getpid(),'acquiredAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'sourceCommit':SOURCE,'executableSha256':EXPECTED_SHA})
  try:
   corrupt()
   recovery()
   import run_disk_full
   run_disk_full.run(sys_modules_helper=__import__('sys').modules[__name__])
  finally:
   cleanup_owned();save('local-http',requests);proxy.shutdown();proxy.server_close()
   protected_after={str(p):sha(p) for p in protected}
   save('protected-inputs-after',protected_after)
   assert protected_after==protected_before
 save('host-lock-released',{'path':str(STATE/'measurement.lock'),'releasedAt':datetime.datetime.now(datetime.timezone.utc).isoformat()})
