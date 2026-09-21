"""Upload-only replay of the retained Mac b3 campaigns over a loopback TLS tunnel.

Uses the exact packaged executable (no app/runtime/pack overrides), certifi public
roots plus the existing public candidate certificate, and the sealed pre-upload
ledgers for immutable-evidence assertions. Upload-only replay never encodes; the
client's persistent receipts stop local re-sends and the server completes lost
responses idempotently. Nothing here touches production or calibration timing.
"""
import datetime
import fcntl
import hashlib
import json
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path('/Users/ofhd/Developer/Encoding_Database')
WORKTREE = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent
CLI = ROOT / '.build/release-20260919/macos-b3ef24a/encodingdb-client-macos'
CLI_SHA = '443e293e82f0f042b2017f55d12f1d73c7d5b6944cb43d6c9d70281beef6d70c'
STATE = ROOT / '.build/release-20260914/mac-host-state'
BASE_QUEUES = ROOT / '.build/native-seven-mac-b3ef24a/épreuve 客户端'
LEDGERS = WORKTREE / 'docs/collection-readiness/mac-seven-b3ef24a/replay-ledgers'
CANDIDATE_CA = ROOT / '.test-reports/release-20260914/p910-candidate-ca.crt'
LEDGER_TOOL = WORKTREE / 'scripts/native-e2e-ledger.py'
LOCAL_PORT = 13094
RESULTS = EVIDENCE / 'mac-upload-results.json'
EXPECTED = {
    'software': {'campaign': 'campaign-cda14a5876e816b6', 'submissions': 18},
    'videotoolbox': {'campaign': 'campaign-5cdcb087bc1fc57a', 'submissions': 14},
}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def ledger_capture(queue):
    spec = importlib.util.spec_from_file_location('native_e2e_ledger', LEDGER_TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.capture(queue)


def ledger_assert(queue, path):
    current = ledger_capture(queue)
    sealed = json.loads(Path(path).read_text())
    if current != sealed:
        raise RuntimeError(f'immutable evidence drifted against {path.name}')
    return current


def shell(command):
    completed = subprocess.run(command, capture_output=True, text=True)
    return completed


def main():
    case = sys.argv[1]
    expected = EXPECTED[case]
    queue = BASE_QUEUES / case / 'queue'
    assert digest(CLI) == CLI_SHA
    with (STATE / 'measurement.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        bundle = EVIDENCE / 'mac-candidate-plus-public-roots.pem'
        if not bundle.is_file():
            certifi = shell([sys.executable, '-c', 'import certifi;print(certifi.where())']).stdout.strip()
            assert certifi and Path(certifi).is_file(), 'certifi roots are required'
            bundle.write_bytes(Path(certifi).read_bytes() + b'\n' + CANDIDATE_CA.read_bytes())
            os.chmod(bundle, 0o600)
        before = ledger_assert(queue, LEDGERS / f'{case}-before-upload.json')
        forward = subprocess.Popen(['ssh', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes',
                                    '-o', 'ServerAliveInterval=20', '-N',
                                    f'-L', f'127.0.0.1:{LOCAL_PORT}:127.0.0.1:3094', 'ofhd@100.99.6.59'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.time() + 20
        while time.time() < deadline:
            probe = shell(['curl', '--silent', '--show-error', '--cacert', str(bundle),
                           f'https://127.0.0.1:{LOCAL_PORT}/v7/compatibility'])
            if probe.returncode == 0:
                break
            time.sleep(1)
        else:
            forward.kill()
            raise RuntimeError('tunnel probe failed: ' + (forward.stderr.read().decode() if forward.stderr else ''))
        env = dict(os.environ)
        for key in list(env):
            if key in ('FFMPEG_EXE', 'FFPROBE_EXE', 'ENCODINGDB_FFMPEG_PATH', 'ENCODINGDB_FFPROBE_PATH',
                       'ENCODINGDB_RUNTIME_LOCK_PATH', 'ENCODINGDB_RUNTIME_BUNDLE_DIR', 'ENCODINGDB_SUITE_PACK_PATH',
                       'DYLD_LIBRARY_PATH', 'DYLD_FALLBACK_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES',
                       'PYTHONPATH', 'PYTHONHOME') or key.lower().endswith('_proxy'):
                env.pop(key, None)
        env.update({'REQUESTS_CA_BUNDLE': str(bundle), 'CURL_CA_BUNDLE': str(bundle),
                    'ENCODINGDB_STATE_DIR': str(STATE), 'ENCODINGDB_DEBUG_TRACEBACK': '1'})
        command = [str(CLI), '--cli', '--upload-only', '--resume-campaign', expected['campaign'], '--submit',
                   '--queue-dir', str(queue), '--base-url', f'https://127.0.0.1:{LOCAL_PORT}',
                   '--max-storage-mb', '2048']
        log = (EVIDENCE / f'{case}.client.log').open('w')
        began = time.monotonic()
        try:
            process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = process.wait(timeout=2700)
            except subprocess.TimeoutExpired:
                process.kill()
                code = 124
        finally:
            forward.terminate()
            forward.wait(timeout=10)
            log.close()
        after = ledger_assert(queue, LEDGERS / f'{case}-before-upload.json')
        pending = sorted(p.name for p in queue.glob('*.json'))
        receipt = {'case': case, 'campaign': expected['campaign'], 'at': now(),
                   'executableSha256': CLI_SHA, 'clientExitCode': code,
                   'wallSeconds': round(time.monotonic() - began, 1),
                   'submissionsExpected': expected['submissions'],
                   'clientLogSha256': digest(EVIDENCE / f'{case}.client.log'),
                   'pendingRootEntries': pending,
                   'ledgerImmutable': before == after,
                   'immutableFiles': len(after['files'])}
        existing = json.loads(RESULTS.read_text()) if RESULTS.is_file() else {'cases': []}
        existing['cases'] = [row for row in existing['cases'] if row['case'] != case]
        existing['cases'].append(receipt)
        (EVIDENCE / f'{case}-after-upload.json').write_text(json.dumps(after, indent=2) + '\n')
        RESULTS.write_text(json.dumps(existing, indent=2) + '\n')
        assert not pending and receipt['ledgerImmutable'], receipt
        print(json.dumps(receipt, indent=1))


if __name__ == '__main__':
    main()
