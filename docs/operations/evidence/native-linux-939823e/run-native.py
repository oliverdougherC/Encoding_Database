"""Exact operator driver for the isolated939823e Linux acceptance, no uploads."""
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

CANDIDATE = Path('/mnt/NVME/docker/encodingdb-operations/20260914-candidate-730de3c')
ROOT = Path('/mnt/NVME/docker/encodingdb-operations/20260920-native-939823e-untraced')
SMOKE_ROOT = Path('/mnt/NVME/docker/encodingdb-operations/20260920-native-939823e-trusted-roots')
WORK = ROOT / '日本語 client trial'
STATE = Path('/mnt/NVME/docker/encodingdb-operations/20260914-validation-holdouts/host-state')
PIN = '939823ead2c052572f9deb5c9f91c85435d5661d'
PACKAGE_SHA = '46a6dcad789f824909911455b19979a33e4053dae1440f09524da5142ca18dc3'


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def save(name, value):
    target = ROOT / name
    temp = target.with_suffix(target.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    os.replace(temp, target)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main():
    # Nonblocking shared lock covers acquisition, smoke and both declared campaigns.
    with (STATE / 'measurement.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=CANDIDATE, text=True).strip() == PIN
        server = json.loads(subprocess.check_output(['docker', 'inspect', 'encodingdb-candidate-730de3c-server-1'], text=True))[0]
        assert server['Config']['Labels']['com.docker.compose.project'] == 'encodingdb-candidate-730de3c'
        assert 'ARTIFACT_ANALYSIS_CONCURRENCY_MAX=0' in server['Config']['Env']
        physical_id = (STATE / 'physical-source-id').read_bytes()
        WORK.mkdir(parents=True, exist_ok=False)
        binary = WORK / 'encodingdb-client-linux'
        shutil.copy2(CANDIDATE / 'encodingdb-client-linux', binary)
        assert digest(binary) == PACKAGE_SHA
        # A custom Requests CA bundle replaces public roots, so retain both trust domains.
        public_roots = Path(certifi.where())
        candidate_cert = CANDIDATE / 'nginx/dev-certs/selfsigned.crt'
        trust_bundle = ROOT / 'candidate-plus-public-roots.pem'
        trust_bundle.write_bytes(public_roots.read_bytes() + b'\n' + candidate_cert.read_bytes())
        for key in ('FFMPEG_EXE', 'FFPROBE_EXE', 'ENCODINGDB_RUNTIME_LOCK_PATH',
                    'ENCODINGDB_FFMPEG_PATH', 'ENCODINGDB_FFPROBE_PATH',
                    'ENCODINGDB_RUNTIME_BUNDLE_DIR', 'ENCODINGDB_SUITE_PACK_PATH',
                    'PYTHONPATH', 'PYTHONHOME', 'LD_LIBRARY_PATH', 'LD_PRELOAD',
                    'DYLD_LIBRARY_PATH', 'DYLD_FALLBACK_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES'):
            os.environ.pop(key, None)
        os.environ.update({
            'ENCODINGDB_STATE_DIR': str(STATE),
            'REQUESTS_CA_BUNDLE': str(trust_bundle),
            'CURL_CA_BUNDLE': str(trust_bundle),
            'BACKEND_BASE_URL': 'https://127.0.0.1:3094',
            'ENCODINGDB_DEBUG_TRACEBACK': '1',
        })
        os.chdir(WORK)
        sys.path.insert(0, str(CANDIDATE))
        release = module('native_release', CANDIDATE / 'scripts/release_manifest_lib.py')
        ledger = module('native_ledger', CANDIDATE / 'scripts/native-e2e-ledger.py')
        state = {'startedAt': now(), 'sourceCommit': PIN, 'packageSha256': PACKAGE_SHA,
                 'physicalSourceId': physical_id.decode().strip(), 'status': 'campaigns',
                 'suiteAcquisition': 'reuse cache acquired from advertised URL by separate smoke; no explicit local pack',
                 'trustBundle': {'publicRootsSha256': digest(public_roots),
                                 'candidateCertificateSha256': digest(candidate_cert),
                                 'combinedSha256': digest(trust_bundle)},
                 'campaigns': []}
        save('execution.json', state)
        cache = SMOKE_ROOT / '日本語 client trial/clean-suite-cache'
        assert cache.is_dir()
        smoke = json.loads((SMOKE_ROOT / 'embedded-smoke.json').read_text())
        assert all(c['returnCode'] == 0 and not c['timedOut'] and not c['cleanupForced']
                   and not c['survivingOwnedPids'] for c in smoke['commands'])
        assert smoke['embeddedRuntime']['frozen'] is True
        save('embedded-smoke.instrumented.json', smoke)
        state['smokeSource'] = {'path': str(SMOKE_ROOT), 'instrumented': True,
                                'ordinaryPerformanceEligible': False}
        state['fullCampaignTracingEnabled'] = False
        prior = json.loads((SMOKE_ROOT / 'operator-instrumentation-interruption.json').read_text())
        preserved_seed = prior['manifest']['seed']
        state['campaignSeed'] = preserved_seed
        state['seedPolicy'] = 'software preserves interrupted seed; first NVENC execution uses the same predeclared seed'
        save('execution.json', state)
        plans = [('software', ['--codec', 'libx264', '--presets', 'medium', '--crf', '24']),
                 ('nvenc', ['--codec', 'h264_nvenc', '--presets', 'p4', '--target-bitrate-kbps', '4000'])]
        for name, recipe in plans:
            queue = WORK / (name + '-queue')
            queue.mkdir()
            env = dict(os.environ)
            env['ENCODINGDB_SUITE_CACHE_DIR'] = str(cache)
            env['ENCODINGDB_RUNTIME_EVIDENCE_PATH'] = str(ROOT / (name + '-embedded-runtime.json'))
            env['ENCODINGDB_PROTOCOL_SEED'] = str(preserved_seed)
            command = [str(binary), '--cli', '--campaign', 'full', *recipe, '--no-submit',
                       '--max-attempts', '35', '--max-duration-minutes', '45',
                       '--max-storage-mb', '2048', '--queue-dir', str(queue),
                       '--base-url', 'https://127.0.0.1:3094']
            entry = {'name': name, 'startedAt': now(), 'argv': command, 'queue': str(queue)}
            state['campaigns'].append(entry)
            save('execution.json', state)
            entry.update(release._run_smoke_command(command, env=env, queue_dir=queue,
                         stdout_path=ROOT / (name + '.stdout.log'), stderr_path=ROOT / (name + '.stderr.log'),
                         acquisition_seconds=900, measurement_seconds=2760))
            entry['finishedAt'] = now()
            try:
                save(name + '-immutable-ledger.json', ledger.capture(queue))
                entry['immutableLedgerCaptured'] = True
            except Exception as error:
                entry['immutableLedgerCaptured'] = False
                entry['ledgerError'] = str(error)
            save('execution.json', state)
            # Never extend attempts, retry unstable groups or alter eligibility flags.
        assert physical_id == (STATE / 'physical-source-id').read_bytes()
        assert digest(binary) == PACKAGE_SHA
        state.update({'status': 'timing-finished', 'finishedAt': now(), 'physicalSourceIdUnchanged': True,
                      'packageBytesUnchanged': True, 'uploadsAttempted': False})
        save('execution.json', state)
        print(json.dumps(state, indent=2), flush=True)


if __name__ == '__main__':
    main()
