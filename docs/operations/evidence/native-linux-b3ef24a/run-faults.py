"""Isolated native faults after ordinary timing; never publish these diagnostics."""
import datetime
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time

import psutil

PLAN = json.loads(Path(__file__).with_name('plan.json').read_text())
FAULT_PLAN = json.loads(Path(__file__).with_name('fault-plan.json').read_text())
ROOT = Path(PLAN['caseRoot'])
CANDIDATE = Path(PLAN['candidateRoot'])
STATE = Path(PLAN['physicalStateRoot'])
FAULTS = ROOT / 'faults'
BINARY = ROOT / '日本語 client trial/encodingdb-client-linux'


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def same_process(process):
    try:
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def completed_snapshot(queue):
    snapshot = {}
    for path in sorted(queue.glob('campaigns/*/attempt-*.json')):
        record = json.loads(path.read_text())
        artifact = Path(record['metadata']['info']['artifactPath'])
        actual = digest(artifact)
        assert actual == record['metadata']['info']['artifactSha256']
        snapshot[str(path)] = digest(path)
        snapshot[str(artifact)] = actual
    return snapshot


def require_unchanged(snapshot):
    for path, expected in snapshot.items():
        assert digest(Path(path)) == expected, f'Completed evidence changed: {path}'


def snapshot_queue(queue, name):
    total = sum(p.stat().st_size for p in queue.rglob('*') if p.is_file())
    assert total <= 512 * 1024 * 1024
    shutil.copytree(queue, FAULTS / 'snapshots' / name)


def require_natural_exit(observed, expected_code):
    if (observed.get('returnCode') != expected_code or observed.get('timedOut') is not False
            or observed.get('cleanupForced') is not False or observed.get('survivingOwnedPids') != []):
        raise ValueError('Native phase did not exit naturally with all owned processes drained')


def main():
    assert json.loads((ROOT / 'execution.json').read_text())['status'] == 'timing-finished'
    with (STATE / 'measurement.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert digest(BINARY) == PLAN['packageSha256']
        assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=CANDIDATE, text=True).strip() == PLAN['sourceCommit']
        server = json.loads(subprocess.check_output(['docker', 'inspect', 'encodingdb-candidate-730de3c-server-1'], text=True))[0]
        assert 'ARTIFACT_ANALYSIS_CONCURRENCY_MAX=0' in server['Config']['Env']
        physical_id = (STATE / 'physical-source-id').read_bytes()
        FAULTS.mkdir(exist_ok=False)
        sys.path.insert(0, str(CANDIDATE))
        release = load('native_release', CANDIDATE / 'scripts/release_manifest_lib.py')
        ledger = load('native_ledger', CANDIDATE / 'scripts/native-e2e-ledger.py')
        ordinary = json.loads((ROOT / 'execution.json').read_text())
        for case in ordinary['campaigns']:
            if case['name'] != 'help':
                ledger.assert_unchanged(json.loads((ROOT / (case['name'] + '-immutable-ledger.json')).read_text()), ledger.capture(Path(case['queue'])))
        env = dict(os.environ)
        for key in list(env):
            if key.lower().endswith('_proxy') or key in ('FFMPEG_EXE', 'FFPROBE_EXE', 'ENCODINGDB_RUNTIME_LOCK_PATH',
                    'ENCODINGDB_FFMPEG_PATH', 'ENCODINGDB_FFPROBE_PATH', 'ENCODINGDB_RUNTIME_BUNDLE_DIR',
                    'ENCODINGDB_SUITE_PACK_PATH', 'PYTHONPATH', 'PYTHONHOME', 'LD_PRELOAD', 'LD_LIBRARY_PATH'):
                env.pop(key, None)
        env.update({'ENCODINGDB_STATE_DIR': str(STATE), 'REQUESTS_CA_BUNDLE': str(ROOT / 'candidate-plus-public-roots.pem'),
                    'CURL_CA_BUNDLE': str(ROOT / 'candidate-plus-public-roots.pem'),
                    'ENCODINGDB_PROTOCOL_SEED': str(FAULT_PLAN['seed']), 'ENCODINGDB_DEBUG_TRACEBACK': '1'})
        result = {'sourceCommit': PLAN['sourceCommit'], 'packageSha256': PLAN['packageSha256'],
                  'startedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'performanceOrCalibrationEligible': False, 'uploadsAttempted': False, 'phases': []}
        def save():
            path = FAULTS / 'fault-results.json'
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(result, indent=2) + '\n')
            os.replace(temporary, path)
        save()

        corrupt_work = FAULTS / 'corrupt-pack'
        corrupt_work.mkdir()
        original = CANDIDATE / 'encodingdb-test-suite-v1.tar.gz'
        bad_pack = corrupt_work / 'corrupted-suite.tar.gz'
        assert digest(original) == 'd20407f8d78f152f06c3b7271881d8b3f07d2b76cf3a2642b241162d666ac150'
        shutil.copyfile(original, bad_pack)
        with bad_pack.open('r+b') as output:
            output.seek(bad_pack.stat().st_size // 2)
            value = output.read(1)
            output.seek(-1, 1)
            output.write(bytes([value[0] ^ 1]))
        refusal_events = []
        class Refusal(BaseHTTPRequestHandler):
            def do_CONNECT(self):
                refusal_events.append({'method': 'CONNECT', 'target': self.path, 'status': 503})
                self.send_response(503)
                self.end_headers()
            def log_message(self, *_args):
                pass
        proxy = ThreadingHTTPServer(('127.0.0.1', 0), Refusal)
        proxy.daemon_threads = True
        thread = threading.Thread(target=proxy.serve_forever, daemon=True)
        thread.start()
        corrupt_queue = corrupt_work / 'queue'
        corrupt_queue.mkdir()
        corrupt_env = dict(env, ENCODINGDB_SUITE_PACK_PATH=str(bad_pack),
                           ENCODINGDB_SUITE_CACHE_DIR=str(corrupt_work / 'empty-cache'),
                           HTTPS_PROXY=f'http://127.0.0.1:{proxy.server_port}', HTTP_PROXY=f'http://127.0.0.1:{proxy.server_port}', NO_PROXY='')
        os.chdir(corrupt_work)
        try:
            observed = release._run_smoke_command([str(BINARY), '--cli', '--campaign', 'quick', '--codec', 'libx264',
                       '--presets', 'fast', '--crf', '24', '--no-submit', '--max-attempts', '1', '--queue-dir', str(corrupt_queue)],
                       env=corrupt_env, queue_dir=corrupt_queue, stdout_path=corrupt_work/'stdout.log',
                       stderr_path=corrupt_work/'stderr.log', acquisition_seconds=120, measurement_seconds=120)
        finally:
            proxy.shutdown()
            proxy.server_close()
            thread.join(timeout=5)
        phase = {'name': 'same-size-corrupt-pack', **observed, 'sameSize': original.stat().st_size == bad_pack.stat().st_size,
                 'corruptSha256': digest(bad_pack), 'fallbackRefusals': refusal_events,
                 'attemptCount': len(list(corrupt_queue.glob('campaigns/*/attempt-*.json')))}
        result['phases'].append(phase)
        save()
        require_natural_exit(phase, 3)
        assert phase['attemptCount'] == 0

        cancel_work = FAULTS / 'interrupt-resume'
        cancel_work.mkdir()
        queue = cancel_work / 'queue'
        queue.mkdir()
        os.chdir(cancel_work)
        env['ENCODINGDB_SUITE_CACHE_DIR'] = str(ROOT / '日本語 client trial/clean-suite-cache')
        initial = [str(BINARY), '--cli', '--campaign', 'quick', '--codec', 'libx264', '--presets', 'veryslow',
                   '--crf', '24', '--no-submit', '--max-attempts', '20', '--max-duration-minutes', '15',
                   '--max-storage-mb', '256', '--queue-dir', str(queue), '--base-url', PLAN['baseUrl']]
        deadline = time.monotonic() + FAULT_PLAN['controllerDeadlineSeconds']
        protected = {}
        owned_orphans = []
        try:
            for name, required_records, sig in [('sigint', 1, signal.SIGINT), ('sigkill', 2, signal.SIGKILL)]:
                command = initial if name == 'sigint' else [str(BINARY), '--cli', '--resume-campaign', campaign_id,
                          '--no-submit', '--queue-dir', str(queue), '--base-url', PLAN['baseUrl'], '--max-duration-minutes', '15']
                observed_children = {}
                with (cancel_work/(name+'.stdout.log')).open('w') as out, (cancel_work/(name+'.stderr.log')).open('w') as err:
                    process = subprocess.Popen(command, stdout=out, stderr=err, env=env, start_new_session=True)
                    triggered = False
                    try:
                        while process.poll() is None and time.monotonic() < deadline:
                            release._smoke_children(process, observed_children)
                            records = list(queue.glob('campaigns/*/attempt-*.json'))
                            encoders = []
                            try:
                                children = psutil.Process(process.pid).children(recursive=True)
                            except psutil.NoSuchProcess:
                                break
                            for child in children:
                                try:
                                    args = child.cmdline()
                                    if args and args[0].endswith('/ffmpeg') and args[-1].endswith('.mp4') and str(queue) in args[-1]:
                                        encoders.append(child)
                                except psutil.Error:
                                    pass
                            if len(records) >= required_records and encoders:
                                protected.update(completed_snapshot(queue))
                                campaign_id = records[0].parent.name
                                assert os.getpgid(process.pid) == process.pid
                                os.killpg(process.pid, sig)
                                process.wait(timeout=20)
                                paused = []
                                if sig == signal.SIGKILL:
                                    for child in encoders:
                                        if same_process(child):
                                            try:
                                                child.suspend()
                                                owned_orphans.append(child)
                                                paused.append({'pid': child.pid, 'createdAt': child.create_time()})
                                            except psutil.NoSuchProcess:
                                                pass
                                else:
                                    assert not release._smoke_survivors(observed_children)
                                snapshot_queue(queue, 'after-'+name)
                                result['phases'].append({'name': name, 'returnCode': process.returncode,
                                    'completedRecordsPreserved': len(records), 'protectedFileCount': len(protected),
                                    'ownedOrphansPausedForSnapshot': paused, 'campaignId': campaign_id})
                                save()
                                assert process.returncode == (130 if sig == signal.SIGINT else -signal.SIGKILL)
                                triggered = True
                                break
                            time.sleep(0.1)
                    finally:
                        if process.poll() is None or (not triggered and release._smoke_survivors(observed_children)):
                            release._stop_smoke_tree(process, observed_children)
                    assert triggered, f'{name} trigger was not observed before completion/deadline'
                require_unchanged(protected)
            command = [str(BINARY), '--cli', '--resume-campaign', campaign_id, '--no-submit', '--queue-dir', str(queue),
                       '--base-url', PLAN['baseUrl'], '--max-duration-minutes', '15']
            assert time.monotonic() < deadline, 'Controller deadline exhausted before final resume'
            remaining = min(960, deadline-time.monotonic())
            final = release._run_smoke_command(command, env=env, queue_dir=queue,
                     stdout_path=cancel_work/'resume.stdout.log', stderr_path=cancel_work/'resume.stderr.log',
                     acquisition_seconds=min(900, remaining), measurement_seconds=remaining)
            result['phases'].append({'name': 'final-resume', **final, 'campaignId': campaign_id})
            save()
            require_natural_exit(final, 0)
            require_unchanged(protected)
            (FAULTS/'fault-campaign-immutable-ledger.json').write_text(json.dumps(ledger.capture(queue), indent=2)+'\n')
            assert not any(same_process(child) for child in owned_orphans)
        finally:
            for child in owned_orphans:
                if same_process(child):
                    child.kill()
                    try:
                        child.wait(timeout=5)
                    except psutil.Error:
                        pass
        for case in ordinary['campaigns']:
            if case['name'] != 'help':
                ledger.assert_unchanged(json.loads((ROOT/(case['name']+'-immutable-ledger.json')).read_text()), ledger.capture(Path(case['queue'])))
        assert digest(BINARY) == PLAN['packageSha256']
        assert physical_id == (STATE / 'physical-source-id').read_bytes()
        result.update({'passed': True, 'ordinaryLedgersUnchanged': True, 'completedDiagnosticFilesUnchanged': True,
                       'physicalSourceIdUnchanged': True, 'packageBytesUnchanged': True,
                       'finishedAt': datetime.datetime.now(datetime.timezone.utc).isoformat()})
        save()
        print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
