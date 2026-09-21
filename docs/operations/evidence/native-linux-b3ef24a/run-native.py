"""Execute the frozen b3 Linux plan only after the parent's capacity handback."""
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import certifi

PLAN_PATH = Path(__file__).with_name('plan.json')
PLAN = json.loads(PLAN_PATH.read_text())
ROOT = Path(PLAN['caseRoot'])
CANDIDATE = Path(PLAN['candidateRoot'])
STATE = Path(PLAN['physicalStateRoot'])
WORK = ROOT / '日本語 client trial'


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def save(name, value):
    target = ROOT / name
    temporary = target.with_suffix(target.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    os.replace(temporary, target)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main():
    assert PLAN['sourceCommit'] == 'b3ef24abb020bc6af5b5fe6b849ba3eae8314be2'
    assert PLAN['tracingEnabled'] is False and PLAN['uploadsEnabled'] is False
    with (STATE / 'measurement.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=CANDIDATE, text=True).strip() == PLAN['sourceCommit']
        server = json.loads(subprocess.check_output(['docker', 'inspect', 'encodingdb-candidate-730de3c-server-1'], text=True))[0]
        assert server['Config']['Labels']['com.docker.compose.project'] == 'encodingdb-candidate-730de3c'
        assert 'ARTIFACT_ANALYSIS_CONCURRENCY_MAX=0' in server['Config']['Env']
        assert server['Image'] == 'sha256:589c89b95e471fb32782a374c88b91d8ea2526080b7cdb7bc48608f97eba399a'
        physical_id = (STATE / 'physical-source-id').read_bytes()
        WORK.mkdir(parents=True, exist_ok=False)
        binary = WORK / 'encodingdb-client-linux'
        shutil.copy2(CANDIDATE / 'encodingdb-client-linux', binary)
        assert digest(binary) == PLAN['packageSha256']
        roots = Path(certifi.where())
        candidate_certificate = CANDIDATE / 'nginx/dev-certs/selfsigned.crt'
        trust = ROOT / 'candidate-plus-public-roots.pem'
        trust.write_bytes(roots.read_bytes() + b'\n' + candidate_certificate.read_bytes())
        for key in ('FFMPEG_EXE', 'FFPROBE_EXE', 'ENCODINGDB_RUNTIME_LOCK_PATH',
                    'ENCODINGDB_FFMPEG_PATH', 'ENCODINGDB_FFPROBE_PATH',
                    'ENCODINGDB_RUNTIME_BUNDLE_DIR', 'ENCODINGDB_SUITE_PACK_PATH',
                    'PYTHONPATH', 'PYTHONHOME', 'LD_LIBRARY_PATH', 'LD_PRELOAD',
                    'DYLD_LIBRARY_PATH', 'DYLD_FALLBACK_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES'):
            os.environ.pop(key, None)
        cache = WORK / 'clean-suite-cache'
        cache.mkdir()
        os.environ.update({'ENCODINGDB_STATE_DIR': str(STATE), 'REQUESTS_CA_BUNDLE': str(trust),
                           'CURL_CA_BUNDLE': str(trust), 'BACKEND_BASE_URL': PLAN['baseUrl'],
                           'ENCODINGDB_SUITE_CACHE_DIR': str(cache), 'ENCODINGDB_DEBUG_TRACEBACK': '1'})
        os.chdir(WORK)
        sys.path.insert(0, str(CANDIDATE))
        release = load_module('native_release', CANDIDATE / 'scripts/release_manifest_lib.py')
        ledger = load_module('native_ledger', CANDIDATE / 'scripts/native-e2e-ledger.py')
        source_lock = json.loads((CANDIDATE / 'client/resources/runtime/ffmpeg-lock.json').read_text())['platforms']['linux']
        state = {'startedAt': now(), 'sourceCommit': PLAN['sourceCommit'], 'packageSha256': PLAN['packageSha256'],
                 'planSha256': digest(PLAN_PATH), 'physicalSourceId': physical_id.decode().strip(),
                 'tracingEnabled': False, 'uploadsAttempted': False, 'status': 'smoke', 'campaigns': [],
                 'trustBundleSha256': digest(trust), 'acquisition': 'fresh cache and advertised URL, no local pack override'}
        save('execution.json', state)

        def execute(name, command, queue, limits, seed, capture_ledger=True):
            env = dict(os.environ)
            env['ENCODINGDB_PROTOCOL_SEED'] = str(seed)
            receipt_path = ROOT / (name + '-embedded-runtime.json')
            env['ENCODINGDB_RUNTIME_EVIDENCE_PATH'] = str(receipt_path)
            entry = {'name': name, 'startedAt': now(), 'argv': command, 'queue': str(queue), 'seed': seed}
            state['campaigns'].append(entry)
            save('execution.json', state)
            entry.update(release._run_smoke_command(command, env=env, queue_dir=queue,
                         stdout_path=ROOT / (name + '.stdout.log'), stderr_path=ROOT / (name + '.stderr.log'),
                         acquisition_seconds=limits['acquisitionDeadlineSeconds'],
                         measurement_seconds=limits['supervisorMeasurementDeadlineSeconds']))
            entry['finishedAt'] = now()
            if capture_ledger:
                try:
                    receipt = json.loads(receipt_path.read_text())
                    assert receipt['frozen'] is True and receipt['platform'] == 'linux'
                    for key in ['ffmpegPath', 'ffprobePath', 'lockPath']:
                        assert os.path.commonpath([receipt['extractionRoot'], receipt[key]]) == receipt['extractionRoot']
                    for key in ['ffmpeg', 'ffprobe']:
                        assert receipt['identity'][key]['sha256'] == source_lock[key]['sha256']
                    entry['embeddedRuntimeVerified'] = True
                    save(name + '-immutable-ledger.json', ledger.capture(queue))
                    entry['immutableLedgerCaptured'] = True
                except Exception as error:
                    entry['evidenceError'] = str(error)
                    entry['immutableLedgerCaptured'] = False
            save('execution.json', state)
            return entry

        smoke_queue = WORK / 'smoke-queue'
        smoke_queue.mkdir()
        help_result = execute('help', [str(binary), '--help'], smoke_queue, PLAN['smoke'], PLAN['seeds']['smoke'], False)
        if help_result['returnCode'] != 0 or help_result['timedOut'] or help_result['cleanupForced']:
            raise RuntimeError('Native help failed; original receipt retained')
        smoke_args = [str(binary), '--cli', '--campaign', 'quick', '--codec', 'libx264', '--presets', 'fast',
                      '--crf', '24', '--no-submit', '--max-attempts', '5', '--max-duration-minutes', '10',
                      '--max-storage-mb', '2048', '--queue-dir', str(smoke_queue), '--base-url', PLAN['baseUrl']]
        smoke_result = execute('smoke', smoke_args, smoke_queue, PLAN['smoke'], PLAN['seeds']['smoke'])
        if smoke_result['returnCode'] != 0 or smoke_result['timedOut'] or smoke_result['cleanupForced'] or not smoke_result['immutableLedgerCaptured']:
            raise RuntimeError('Native smoke failed; original receipt retained')
        state['status'] = 'full-campaigns'
        save('execution.json', state)
        for recipe in PLAN['campaigns']:
            name = recipe['name']
            queue = WORK / (name + '-queue')
            queue.mkdir()
            arguments = ['--codec', recipe['codec'], '--presets', recipe['preset']]
            arguments += ['--crf', str(recipe['crf'])] if 'crf' in recipe else ['--target-bitrate-kbps', str(recipe['targetBitrateKbps'])]
            command = [str(binary), '--cli', '--campaign', 'full', *arguments, '--no-submit', '--max-attempts', '35',
                       '--max-duration-minutes', '45', '--max-storage-mb', '2048', '--queue-dir', str(queue), '--base-url', PLAN['baseUrl']]
            execute(name, command, queue, PLAN['campaignLimits'], PLAN['seeds'][name])
        assert physical_id == (STATE / 'physical-source-id').read_bytes()
        assert digest(binary) == PLAN['packageSha256']
        state.update({'status': 'timing-finished', 'finishedAt': now(), 'physicalSourceIdUnchanged': True, 'packageBytesUnchanged': True})
        save('execution.json', state)
        print(json.dumps(state, indent=2), flush=True)


if __name__ == '__main__':
    main()
