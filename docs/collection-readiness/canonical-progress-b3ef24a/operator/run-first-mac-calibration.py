import hashlib,json,os,subprocess
from pathlib import Path
root=Path('/Users/ofhd/Developer/Encoding_Database')
p=json.loads((root/'docs/collection-readiness/canonical-execution-b3ef24a/execution.json').read_text());h=p['hosts']['Mac']
for key,expected in [('runner',p['runnerSha256']),('matrix',p['matrixSha256']),('cli',h['binarySha256'])]:
 with Path(h[key]).open('rb') as f: assert hashlib.file_digest(f,'sha256').hexdigest()==expected,key
assert 'AC Power' in subprocess.check_output(['pmset','-g','batt'],text=True)
env=dict(os.environ)
for key in ['FFMPEG_EXE','FFPROBE_EXE','ENCODINGDB_FFMPEG_PATH','ENCODINGDB_FFPROBE_PATH','ENCODINGDB_RUNTIME_LOCK_PATH','DYLD_LIBRARY_PATH','DYLD_FALLBACK_LIBRARY_PATH','PYTHONPATH','PYTHONHOME','ENCODINGDB_PROTOCOL_STABILITY_THRESHOLD','ENCODINGDB_PROTOCOL_MAX_ADAPTIVE_REPEATS']:env.pop(key,None)
env.update(h['requiredEnvironment'])
env.update(ENCODINGDB_SUITE_CACHE_DIR=str(root/'.build/native-faults-20260914/épreuve 客户端/clean-cache'),ENCODINGDB_SUITE_PACK_PATH=str(Path(h['cli']).parent/'encodingdb-test-suite-v1.tar.gz'))
args=h['proposedInitialTimingArgv'];os.chdir(root);os.execve(args[0],args,env)
