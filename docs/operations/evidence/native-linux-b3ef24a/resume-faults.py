"""Resume only the interrupted final fault recovery; completed phases stay immutable.

The user wrap-up stopped the fault supervisor before run-faults.py reached its
final-resume phase. This driver never re-runs corrupt-pack, SIGINT or SIGKILL.
It re-verifies the retained queue and snapshots, drains the resumed campaign to a
natural exit through the same owned-process supervisor, and seals the suite with
the same ledger/digest requirements run-faults.py would have applied.
"""
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import psutil

PLAN = json.loads(Path(__file__).with_name('plan.json').read_text())
FAULT_PLAN = json.loads(Path(__file__).with_name('fault-plan.json').read_text())
ROOT = Path(PLAN['caseRoot'])
CANDIDATE = Path(PLAN['candidateRoot'])
STATE = Path(PLAN['physicalStateRoot'])
FAULTS = ROOT / 'faults'
WORK = FAULTS / 'interrupt-resume'
QUEUE = WORK / 'queue'
BINARY = ROOT / '日本語 client trial/encodingdb-client-linux'


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def completed_snapshot(queue):
    snapshot = {}
    for path in sorted(queue.glob('campaigns/*/attempt-*.json')):
        record = json.loads(path.read_text())
        artifact = Path(record['metadata']['info']['artifactPath'])
        actual = digest(artifact)
        assert actual == record['metadata']['info']['artifactSha256'], f'Artifact hash drifted: {artifact}'
        snapshot[str(path)] = digest(path)
        snapshot[str(artifact)] = actual
    return snapshot


def require_unchanged(snapshot):
    for path, expected in snapshot.items():
        assert digest(Path(path)) == expected, f'Completed evidence changed: {path}'


def require_natural_exit(observed, expected_code):
    if (observed.get('returnCode') != expected_code or observed.get('timedOut') is not False
            or observed.get('cleanupForced') is not False or observed.get('survivingOwnedPids') != []):
        raise ValueError('Native phase did not exit naturally with all owned processes drained')


def main():
    with (STATE / 'measurement.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert json.loads((ROOT / 'execution.json').read_text())['status'] == 'timing-finished'
        assert digest(BINARY) == PLAN['packageSha256']
        assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=CANDIDATE, text=True).strip() == PLAN['sourceCommit']
        server = json.loads(subprocess.check_output(['docker', 'inspect', 'encodingdb-candidate-730de3c-server-1'], text=True))[0]
        assert 'ARTIFACT_ANALYSIS_CONCURRENCY_MAX=0' in server['Config']['Env']
        physical_id = (STATE / 'physical-source-id').read_bytes()

        results = json.loads((FAULTS / 'fault-results.json').read_text())
        names = [phase['name'] for phase in results['phases']]
        assert names == ['same-size-corrupt-pack', 'sigint', 'sigkill'], names
        campaign_id = results['phases'][-1]['campaignId']
        assert (QUEUE / 'campaigns' / campaign_id).is_dir()
        for orphan in results['phases'][-1]['ownedOrphansPausedForSnapshot']:
            if psutil.pid_exists(orphan['pid']):
                try:
                    created = psutil.Process(orphan['pid']).create_time()
                except psutil.NoSuchProcess:
                    continue
                assert abs(created - orphan['createdAt']) > 1.0, f'snapshot-paused owned encoder {orphan["pid"]} still alive'

        sys.path.insert(0, str(CANDIDATE))
        release = load('native_release', CANDIDATE / 'scripts/release_manifest_lib.py')
        ledger = load('native_ledger', CANDIDATE / 'scripts/native-e2e-ledger.py')
        ordinary = json.loads((ROOT / 'execution.json').read_text())

        def require_ordinary_ledgers():
            for case in ordinary['campaigns']:
                if case['name'] != 'help':
                    ledger.assert_unchanged(json.loads((ROOT / (case['name'] + '-immutable-ledger.json')).read_text()),
                                            ledger.capture(Path(case['queue'])))

        require_ordinary_ledgers()

        # Wrap-up must not have perturbed the completed records behind the snapshots.
        snap = FAULTS / 'snapshots' / 'after-sigkill'
        for record in sorted(snap.glob('campaigns/*/attempt-*.json')):
            live = QUEUE / record.relative_to(snap)
            assert digest(record) == digest(live), f'completed record drifted since snapshot: {live}'
        protected = completed_snapshot(QUEUE)
        require_unchanged(protected)

        env = dict(os.environ)
        for key in list(env):
            if key.lower().endswith('_proxy') or key in ('FFMPEG_EXE', 'FFPROBE_EXE', 'ENCODINGDB_RUNTIME_LOCK_PATH',
                    'ENCODINGDB_FFMPEG_PATH', 'ENCODINGDB_FFPROBE_PATH', 'ENCODINGDB_RUNTIME_BUNDLE_DIR',
                    'ENCODINGDB_SUITE_PACK_PATH', 'PYTHONPATH', 'PYTHONHOME', 'LD_PRELOAD', 'LD_LIBRARY_PATH'):
                env.pop(key, None)
        env.update({'ENCODINGDB_STATE_DIR': str(STATE), 'REQUESTS_CA_BUNDLE': str(ROOT / 'candidate-plus-public-roots.pem'),
                    'CURL_CA_BUNDLE': str(ROOT / 'candidate-plus-public-roots.pem'),
                    'ENCODINGDB_PROTOCOL_SEED': str(FAULT_PLAN['seed']), 'ENCODINGDB_DEBUG_TRACEBACK': '1',
                    'ENCODINGDB_SUITE_CACHE_DIR': str(ROOT / '日本語 client trial/clean-suite-cache')})

        def save():
            path = FAULTS / 'fault-results.json'
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(results, indent=2) + '\n')
            os.replace(temporary, path)

        os.chdir(WORK)
        command = [str(BINARY), '--cli', '--resume-campaign', campaign_id, '--no-submit', '--queue-dir', str(QUEUE),
                   '--base-url', PLAN['baseUrl'], '--max-duration-minutes', '15']
        final = release._run_smoke_command(command, env=env, queue_dir=QUEUE,
                stdout_path=WORK / 'resume-final.stdout.log', stderr_path=WORK / 'resume-final.stderr.log',
                acquisition_seconds=900, measurement_seconds=960)
        results['phases'].append({'name': 'final-resume', **final, 'campaignId': campaign_id})
        save()
        require_natural_exit(final, 0)
        require_unchanged(protected)
        (FAULTS / 'fault-campaign-immutable-ledger.json').write_text(json.dumps(ledger.capture(QUEUE), indent=2) + '\n')
        require_ordinary_ledgers()
        assert digest(BINARY) == PLAN['packageSha256']
        assert physical_id == (STATE / 'physical-source-id').read_bytes()
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        results.update({'passed': True, 'ordinaryLedgersUnchanged': True, 'completedDiagnosticFilesUnchanged': True,
                        'physicalSourceIdUnchanged': True, 'packageBytesUnchanged': True,
                        'finalResumeNote': 'final-resume executed by resume-faults.py after the user wrap-up stopped '
                                           'run-faults.py before this phase; all earlier phases and attempts retained',
                        'resumedAt': now, 'finishedAt': now})
        save()
        print(json.dumps(results, indent=2), flush=True)

if __name__ == '__main__':
    main()
