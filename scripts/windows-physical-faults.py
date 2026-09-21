#!/usr/bin/env python3
"""Bounded physical native faults using only owned files and loopback fixtures."""
import argparse
from contextlib import contextmanager
from datetime import datetime,timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


@contextmanager
def owned_native_process(command, receipt, **kwargs):
    """Keep the live Popen identity owned through receipt failures and interrupts."""
    process = subprocess.Popen(command, **kwargs)
    try:
        yield process
    finally:
        if process.poll() is None:
            receipt['forcedCleanup'] = True
            cleanup_error = None
            try:
                result = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                        capture_output=True, text=True, timeout=30)
                receipt['cleanup'] = {'exitCode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
                if result.returncode:
                    cleanup_error = RuntimeError('taskkill did not confirm owned tree cleanup')
            except (OSError, subprocess.SubprocessError) as error:
                cleanup_error = error
                receipt['cleanup'] = {'error': str(error)}
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=30)
            if cleanup_error is not None:
                raise RuntimeError('Owned native tree cleanup failed; inspect retained receipt') from cleanup_error


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--case',choices=['offline-upload','backpressure','storage-budget','corrupt-pack'],required=True)
    p.add_argument('--execute',action='store_true')
    a=p.parse_args()
    if not a.execute:print(json.dumps({'case':a.case,'mode':'plan-only','scope':__doc__}));return
    if os.name!='nt':raise RuntimeError('Actual Windows is required')
    root=a.root.resolve(strict=True);source=root/'source-b3ef24a'
    op=module('physical_operator',root/'windows-physical-acceptance.py')
    ledger=module('immutable_ledger',source/'scripts/native-e2e-ledger.py')
    pins=op.read(root/'physical-candidate-pins-b3ef24a.json')
    with op.host_lock(root/'host-state'):
        exe,manifest=op.verify_payload(source,pins)
        phase=root/('fault-'+a.case+'-b3ef24a');phase.mkdir(exist_ok=False)
        (phase/'tmp').mkdir()
        receipt={'schemaVersion':1,'case':a.case,'status':'RUNNING','scope':'Physical native fault acceptance; local files/loopback only; no production or P910 contact','startedAt':datetime.now(timezone.utc).isoformat(),'sourceRevision':pins['actualBuildRevision'],'executableSha256':pins['files'][exe.name],'commands':[],'networkEvents':[],'forcedCleanup':False}
        receipt_path=phase/'receipt.json'
        def save():op.save(receipt_path,receipt)
        save()
        env=os.environ.copy()
        for key in list(env):
            if key.startswith(('ENCODINGDB_','V7_OPERATOR_','DYLD_')) or key in ('FFMPEG_EXE','FFPROBE_EXE','PYTHONPATH','PYTHONHOME','LD_LIBRARY_PATH','API_KEY') or key.lower().endswith('_proxy'):del env[key]
        env.update(ENCODINGDB_STATE_DIR=str(root/'host-state'),ENCODINGDB_SUITE_CACHE_DIR=str(root/'suite-cache'),ENCODINGDB_SUITE_PACK_PATH=str(source/'encodingdb-test-suite-v1.tar.gz'),TEMP=str(phase/'tmp'),TMP=str(phase/'tmp'))
        source_queue=root/'acceptance-x264-crf23-b3ef24a-é/queue-客户'
        campaign=json.loads((root/'acceptance-x264-crf23-b3ef24a-é/operator-receipt.json').read_text())['evidence']['campaignId']
        before=ledger.capture(source_queue)
        op.save(phase/'original-measurements-before.json',before)
        server=None;thread=None
        class Fixture(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def event(self):
                if len(receipt['networkEvents'])>=100:raise RuntimeError('Loopback fixture event cap exceeded')
                receipt['networkEvents'].append({'method':self.command,'target':self.path,'at':time.time(),'forwarded':False})
            def respond(self,status,payload,retry=None):
                body=json.dumps(payload).encode();self.send_response(status)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)))
                if retry:self.send_header('Retry-After',str(retry))
                self.end_headers();self.wfile.write(body)
            def do_CONNECT(self):self.event();self.respond(502,{'fixture':'No external forwarding permitted'})
            def do_GET(self):
                self.event()
                if a.case=='backpressure' and self.path=='/v7/compatibility':
                    self.respond(200,{'protocolVersion':'7.1','encodeTimerBoundary':'ffmpeg-process-v1','sourceSuiteVersion':'encodingdb-test-suite-v1','suiteFingerprint':pins['suiteFingerprint'],'minimumClientVersion':'client/0.3.0'})
                else:self.respond(503,{'fixture':'Acquisition unavailable'})
            def do_POST(self):
                self.event();length=int(self.headers.get('Content-Length','0'))
                if length>1024*1024:self.respond(413,{'fixture':'Unexpected request size'});return
                self.rfile.read(length)
                if a.case=='backpressure' and self.path=='/v7/benchmark-runs':self.respond(429,{'fixture':'Controlled backpressure; no row created'},60)
                else:self.respond(404,{'fixture':'No endpoint'})
        def run(arguments,name,expected,timeout=240):
            env['ENCODINGDB_RUNTIME_EVIDENCE_PATH']=str(phase/(name+'-embedded-runtime.json'))
            command=[str(exe),*arguments];entry={'argv':command,'startedAt':datetime.now(timezone.utc).isoformat()};receipt['commands'].append(entry);save();start=time.monotonic()
            with (phase/(name+'.stdout.log')).open('xb') as out,(phase/(name+'.stderr.log')).open('xb') as err:
                with owned_native_process(command,receipt,cwd=phase,env=env,stdout=out,stderr=err) as process:
                    entry['pid']=process.pid;save()
                    try:entry['exitCode']=process.wait(timeout=timeout)
                    except subprocess.TimeoutExpired as error:
                        raise RuntimeError('Native fault exceeded its declared deadline') from error
            entry['wallSeconds']=time.monotonic()-start;save()
            if entry['exitCode']!=expected:raise RuntimeError(f'Expected native exit {expected}, got {entry["exitCode"]}')
        try:
            if a.case in ('backpressure','corrupt-pack'):
                server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                fixture_url='http://127.0.0.1:'+str(server.server_port);receipt['fixtureUrl']=fixture_url
            base=['--cli','--api-key','','--retries','1']
            if a.case=='offline-upload':
                run(base+['--upload-only','--base-url','http://127.0.0.1:9','--resume-campaign',campaign,'--queue-dir',str(source_queue)],'offline-upload',10,120)
            elif a.case=='backpressure':
                arguments=base+['--upload-only','--base-url',fixture_url,'--resume-campaign',campaign,'--queue-dir',str(source_queue),'--max-storage-mb','4096']
                run(arguments,'first-replay',10)
                first_posts=sum(x['method']=='POST' for x in receipt['networkEvents'])
                entries=[op.read(x) for x in source_queue.glob('*.json')]
                pending=[x for x in entries if x.get('payload',{}).get('submissionKind')]
                if len(pending)!=14 or first_posts!=14:raise RuntimeError('Expected one backpressured request per measured artifact')
                if any(x.get('attempts')!=1 or x['nextAttemptAt']<x['lastAttemptAt']+59 for x in pending):raise RuntimeError('Retry-After was not preserved')
                receipt['pendingEntries']=[{k:x.get(k) for k in ['localHash','attempts','queuedAt','lastAttemptAt','nextAttemptAt','retryDeadlineAt','lastError']} for x in pending]
                run(arguments,'immediate-replay',10)
                if sum(x['method']=='POST' for x in receipt['networkEvents'])!=first_posts:raise RuntimeError('Immediate replay ignored persisted backoff')
                receipt['firstReplayPosts']=first_posts;receipt['immediateReplayPosts']=0
            else:
                queue=phase/'queue-客户';queue.mkdir()
                if a.case=='storage-budget':
                    (queue/'owned-capacity-fixture.bin').write_bytes(b'\0'*(1024*1024))
                    receipt['capacityFixtureBytes']=1024*1024
                    expected=6
                else:
                    binary_dir=phase/'isolated-package';binary_dir.mkdir()
                    copied=binary_dir/exe.name;shutil.copyfile(exe,copied)
                    if op.sha(copied)!=receipt['executableSha256']:raise RuntimeError('Copied candidate differs')
                    exe=copied
                    corrupt=binary_dir/'encodingdb-test-suite-v1.tar.gz';shutil.copyfile(source/corrupt.name,corrupt)
                    with corrupt.open('r+b') as handle:
                        first=handle.read(1)[0];handle.seek(0);handle.write(bytes([first^1]))
                    receipt['corruptPackSha256']=op.sha(corrupt);receipt['corruptPackBytes']=corrupt.stat().st_size
                    if receipt['corruptPackSha256']==manifest['suite']['pack']['sha256']:raise RuntimeError('Fault input was not corrupted')
                    env.update(ENCODINGDB_SUITE_CACHE_DIR=str(phase/'fresh-cache'),ENCODINGDB_SUITE_PACK_PATH=str(corrupt),HTTP_PROXY=fixture_url,HTTPS_PROXY=fixture_url,ALL_PROXY=fixture_url,NO_PROXY='')
                    expected=3
                run(base+['--no-submit','--base-url','http://127.0.0.1:9','--campaign','quick','--codec','libx264','--presets','fast','--crf','23','--queue-dir',str(queue),'--max-duration-minutes','1','--max-storage-mb','1' if a.case=='storage-budget' else '128'],'native-rejection',expected,600)
                if list(queue.rglob('attempt-*.json')):raise RuntimeError('Fault unexpectedly produced an encode attempt')
                receipt['newAttempts']=0
                if a.case=='corrupt-pack' and op.sha(source/'encodingdb-test-suite-v1.tar.gz')!=manifest['suite']['pack']['sha256']:raise RuntimeError('Original source pack changed')
            after=ledger.capture(source_queue);ledger.assert_unchanged(before,after)
            receipt['originalImmutableFilesUnchanged']=len(after['files'])
            receipt['installationId']=(root/'host-state/physical-source-id').read_text().strip()
            receipt['status']='PASSED_EXPECTED_NATIVE_FAILURE_AND_RETENTION'
        except BaseException as error:receipt['status']='FAILED';receipt['error']=str(error);raise
        finally:
            if server:server.shutdown();server.server_close()
            if thread:thread.join(timeout=3)
            receipt['finishedAt']=datetime.now(timezone.utc).isoformat();save();print(json.dumps({'case':a.case,'status':receipt['status'],'receipt':str(receipt_path)}),flush=True)


if __name__=='__main__':main()
