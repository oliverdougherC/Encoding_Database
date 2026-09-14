"""Operator-only finite revision driver; the source runner owns actual timing."""
import argparse,fcntl,hashlib,json,math,os,pathlib,subprocess,time

parser=argparse.ArgumentParser()
parser.add_argument('--plan',type=pathlib.Path,required=True)
parser.add_argument('--checkout',type=pathlib.Path,required=True)
parser.add_argument('--archive',type=pathlib.Path,required=True)
parser.add_argument('--phase',choices=['software-smoke','software-remainder','p910-hardware'],required=True)
args=parser.parse_args()
plan=json.loads(args.plan.read_text());claimed=plan.pop('planHash')
canonical=lambda value:json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
assert hashlib.sha256(canonical(plan)).hexdigest()==claimed
assert plan['status']=='PREDECLARED_BEFORE_CORRECTED_TIMING'
assert hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()==plan['operatorDriverSha256']
selected=[row for row in plan['cells'] if row['executionPhase']==args.phase]
assert selected, 'Requested phase has no declared cells'
root=pathlib.Path('/mnt/NVME/docker/encodingdb-operations/20260914-validation-holdouts')
state=pathlib.Path(plan['stateDirectory']['P910']);state.mkdir(parents=True,exist_ok=True)
operator_lock=(state/'measurement.lock').open('a+b')
fcntl.flock(operator_lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
with args.archive.open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==plan['sourceArchiveSha256']
assert hashlib.sha256((args.checkout/'scripts/run-validation-campaign.py').read_bytes()).hexdigest()==plan['runnerSha256']
python=pathlib.Path('/mnt/NVME/docker/encodingdb-operations/20260914-native-linux-candidate/native-build-venv/bin/python')
runtime=pathlib.Path('/mnt/NVME/docker/encodingdb-operations/20260914-native-linux-candidate/runtime/ffmpeg-n8.1.2-51-g7ba069f4f1-linux64-gpl-8.1/bin')
env={**os.environ,'PATH':str(runtime)+os.pathsep+os.environ.get('PATH',''),'ENCODINGDB_STATE_DIR':str(state)}
evidence=root/'timing-evidence'/plan['executionRevision'];evidence.mkdir(parents=True,exist_ok=True)
now=lambda:time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
phase_complete=False
for cell in selected:
 if pathlib.Path(plan['pauseAtCellBoundaryFile']).exists():
  print(json.dumps({'status':'PAUSED_AT_CELL_BOUNDARY','nextCell':cell['cellId'],'at':now()}),flush=True);break
 report_path=evidence/(cell['cellId']+'.json')
 if report_path.exists():
  previous=json.loads(report_path.read_text())
  if previous.get('planHash')!=claimed:raise RuntimeError('Existing report belongs to another execution revision')
  if previous.get('exitCode') in (0,4) and previous.get('cpuProvenanceVerified'):
   for receipt in previous['receipts']:
    assert hashlib.sha256(pathlib.Path(receipt['path']).read_bytes()).hexdigest()==receipt['sha256']
   print(json.dumps({'cell':cell['cellId'],'status':'REUSED_UNCHANGED_COMPLETED_RECEIPT'}),flush=True);continue
 if sum(p.stat().st_size for p in root.rglob('*') if p.is_file())>plan['taskMaximumBytes']-plan['maximumCellJournalBytes']:raise RuntimeError('Insufficient declared storage allowance; no retained observations removed')
 output=pathlib.Path(cell['outputPath']);output.mkdir(parents=True,exist_ok=True)
 command=[str(python),str(args.checkout/'scripts/run-validation-campaign.py'),'--registry',str(root/'validation-source-registry-final-v1.json'),'--workload',cell['workloadId'],'--reference',cell['referencePath'],'--output',str(output),'--encoder',cell['encoder'],'--preset',cell['preset'],'--seed',str(cell['seed']),'--max-duration-minutes',str(cell['maximumMeasurementMinutes'])]
 command += ['--target-bitrate-kbps',str(cell['targetBitrateKbps'])] if 'targetBitrateKbps' in cell else ['--crf',str(cell['crf'])]
 log=evidence/(cell['cellId']+'.log')
 report={'cell':cell,'planHash':claimed,'sourceCommit':plan['sourceCommit'],'sourceArchiveSha256':plan['sourceArchiveSha256'],'command':command,'outerLockPath':str(state/'measurement.lock'),'startedAt':now(),'phase':'TIMING_ONLY_NO_UPLOAD_OR_ANALYSIS'}
 with log.open('a') as stream:result=subprocess.run(command,cwd=args.checkout,env=env,stdout=stream,stderr=stream)
 receipts=[];provenance=True;observed_count=0
 for path in output.rglob('validation-campaign.json'):
  raw=path.read_bytes();receipt=json.loads(raw)
  for group in receipt['campaign']['recipeResults']:
   for run in group['runs']:
    if not run['countedForStability']:continue
    observed_count+=1
    snapshot=run['environmentSnapshot'] or {};pct=snapshot.get('background_cpu_pct');markers={value.strip() for value in (snapshot.get('telemetry_sources') or '').split(',')}
    if isinstance(pct,bool) or not isinstance(pct,(int,float)) or not math.isfinite(pct) or not 0<=pct<=100 or not markers.intersection({'cpu_psutil_thread_window_v1','cpu_psutil_blocking_window_v1'}):provenance=False
  receipts.append({'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()})
 report.update(exitCode=result.returncode,completedAt=now(),receipts=receipts,cpuProvenanceVerified=provenance and bool(receipts) and observed_count>0,observedCountedSamples=observed_count)
 report_path.write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({'cell':cell['cellId'],'exitCode':result.returncode,'cpuProvenanceVerified':report['cpuProvenanceVerified']}),flush=True)
 if result.returncode not in (0,4) or not report['cpuProvenanceVerified']:break

else:
 phase_complete=True
(evidence/(args.phase+'-status.json')).write_text(json.dumps({'phase':args.phase,'complete':phase_complete,'planHash':claimed,'observedAt':now()},indent=2)+'\n')
