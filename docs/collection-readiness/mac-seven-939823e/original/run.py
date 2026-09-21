import datetime,fcntl,hashlib,json,os,signal,subprocess,time
from pathlib import Path
root=Path('/Users/ofhd/Developer/Encoding_Database')
output=root/'.build/native-seven-mac-939823e/épreuve 客户端'
cli=root/'.build/release-20260919/macos-939823e/encodingdb-client-macos'
state=root/'.build/release-20260914/mac-host-state'
cache=root/'.build/native-faults-20260914/épreuve 客户端/clean-cache'
state.mkdir(parents=True,exist_ok=True)
receipt={'sourceCommit':'939823ead2c052572f9deb5c9f91c85435d5661d','executableSha256':hashlib.file_digest(cli.open('rb'),'sha256').hexdigest(),'purpose':'Actual packaged seven-clip native acceptance; no publication and not the predeclared calibration matrix','cases':[]}
def save():
 p=output/'receipt.tmp';p.write_text(json.dumps(receipt,indent=2)+'\n');p.replace(output/'receipt.json')
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
with (state/'measurement.lock').open('a+b') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 for name,codec,settings,seed in [('software','libx264',['--presets','fast','--crf','23'],20260919),('videotoolbox','h264_videotoolbox',['--presets','default','--target-bitrate-kbps','6000'],20260920)]:
  path=output/name;path.mkdir(exist_ok=False)
  command=[str(cli),'--cli','--codec',codec,*settings,'--campaign','full','--no-submit','--max-attempts','35','--max-storage-mb','2048','--max-duration-minutes','20','--queue-dir',str(path/'queue')]
  env=dict(os.environ)
  for key in list(env):
   if key in ['FFMPEG_EXE','FFPROBE_EXE','ENCODINGDB_FFMPEG_PATH','ENCODINGDB_FFPROBE_PATH','ENCODINGDB_RUNTIME_LOCK_PATH','DYLD_LIBRARY_PATH','DYLD_FALLBACK_LIBRARY_PATH','PYTHONPATH','PYTHONHOME']:env.pop(key,None)
  env.update(ENCODINGDB_STATE_DIR=str(state),ENCODINGDB_SUITE_CACHE_DIR=str(cache),ENCODINGDB_SUITE_PACK_PATH=str(cli.parent/'encodingdb-test-suite-v1.tar.gz'),ENCODINGDB_RUNTIME_EVIDENCE_PATH=str(path/'embedded-runtime.json'),ENCODINGDB_PROTOCOL_SEED=str(seed),ENCODINGDB_DEBUG_TRACEBACK='1')
  case={'name':name,'command':command,'startedAt':now(),'exitCode':None,'seed':seed};receipt['cases'].append(case);save()
  began=time.monotonic()
  with (path/'client.log').open('w') as log:
   process=subprocess.Popen(command,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,pass_fds=(lock.fileno(),))
   try: code=process.wait(timeout=2100)
   except subprocess.TimeoutExpired:
    os.killpg(process.pid,signal.SIGINT)
    try:process.wait(timeout=30)
    except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
    code=124
  case.update(exitCode=code,finishedAt=now(),wallSeconds=time.monotonic()-began,logSha256=hashlib.file_digest((path/'client.log').open('rb'),'sha256').hexdigest())
  case['campaigns']=[p.parent.name for p in (path/'queue/campaigns').glob('*/manifest.json')]
  save();print(json.dumps(case),flush=True)
  if code:raise SystemExit(code)
