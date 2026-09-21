"""Fresh, bounded post-timing file hashes and actual decoded frame counts."""
import datetime
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import time

PLAN = json.loads(Path(__file__).with_name('plan.json').read_text())
ROOT = Path(PLAN['caseRoot'])
CANDIDATE = Path(PLAN['candidateRoot'])
PROBE = Path('/mnt/NVME/docker/encodingdb-operations/20260914-native-linux-candidate/runtime/ffmpeg-n8.1.2-51-g7ba069f4f1-linux64-gpl-8.1/bin/ffprobe')


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def validate_execution(execution):
    if (execution.get('status') != 'timing-finished' or execution.get('sourceCommit') != PLAN['sourceCommit']
            or execution.get('packageSha256') != PLAN['packageSha256']):
        raise ValueError('Execution source, package or completed phase does not match the frozen plan')
    expected_names = ['help', 'smoke', *[case['name'] for case in PLAN['campaigns']]]
    cases = execution.get('campaigns')
    if not isinstance(cases, list) or sorted(case.get('name', '') for case in cases) != sorted(expected_names):
        raise ValueError('Execution must contain exactly the planned help, smoke and full campaign cases')
    work = ROOT / '日本語 client trial'
    if work.is_symlink() or not work.is_dir() or ROOT.resolve() not in work.resolve().parents:
        raise ValueError('Execution working directory is not owned by this case')
    for case in cases:
        queue_name = 'smoke' if case['name'] == 'help' else case['name']
        expected_queue = work / (queue_name + '-queue')
        if (case.get('queue') != str(expected_queue) or expected_queue.is_symlink()
                or not expected_queue.is_dir() or expected_queue.resolve().parent != work.resolve()):
            raise ValueError('Execution queue identity is outside the exact planned case')
        if (case.get('returnCode') != 0 or case.get('timedOut') is not False
                or case.get('cleanupForced') is not False or case.get('survivingOwnedPids') != []):
            raise ValueError('Execution case is incomplete or required forced cleanup')
        if case['name'] != 'help' and (case.get('embeddedRuntimeVerified') is not True or case.get('immutableLedgerCaptured') is not True):
            raise ValueError('Execution case lacks its completed runtime/ledger evidence')


def audit_locked():
    started = time.monotonic()
    deadline = started + 1200
    execution = json.loads((ROOT / 'execution.json').read_text())
    validate_execution(execution)
    actual_package_sha256 = digest(ROOT / '日本語 client trial/encodingdb-client-linux')
    if actual_package_sha256 != PLAN['packageSha256']:
        raise ValueError('Copied package bytes no longer match the frozen plan')
    expected_probe = json.loads((CANDIDATE / 'client/resources/runtime/ffmpeg-lock.json').read_text())['platforms']['linux']['ffprobe']['sha256']
    assert digest(PROBE) == expected_probe
    spec = importlib.util.spec_from_file_location('ledger', CANDIDATE / 'scripts/native-e2e-ledger.py')
    ledger = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ledger)
    result = {'startedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'sourceCommit': PLAN['sourceCommit'], 'timingPhaseAlreadyFinished': True,
              'actualPackageSha256': actual_package_sha256,
              'auditHelperPath': str(PROBE), 'auditHelperSha256': expected_probe,
              'totalDeadlineSeconds': 1200, 'perFileDeadlineSeconds': 60, 'cases': []}
    for entry in execution['campaigns']:
        if entry['name'] == 'help':
            continue
        queue = Path(entry['queue'])
        current = {'name': entry['name'], 'artifacts': [], 'ledgerUnchanged': False}
        result['cases'].append(current)
        try:
            ledger.assert_unchanged(json.loads((ROOT / (entry['name'] + '-immutable-ledger.json')).read_text()), ledger.capture(queue))
            current['ledgerUnchanged'] = True
        except Exception as error:
            current['ledgerError'] = str(error)
        for record_path in sorted(queue.glob('campaigns/*/attempt-*.json')):
            record = json.loads(record_path.read_text())
            info = record['metadata']['info']
            artifact = Path(info['artifactPath']).resolve(strict=True)
            assert queue.resolve() in artifact.parents
            observation = {'record': str(record_path), 'artifact': str(artifact),
                           'sha256': digest(artifact), 'byteSize': artifact.stat().st_size, 'passed': False}
            current['artifacts'].append(observation)
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Whole audit deadline exhausted')
                command = [str(PROBE), '-v', 'error', '-count_frames', '-show_entries',
                           'stream=index,codec_type,codec_name,width,height,pix_fmt,nb_read_frames,avg_frame_rate,color_range,color_space,color_transfer,color_primaries:format=duration,size,format_name',
                           '-of', 'json', str(artifact)]
                probe = subprocess.run(command, capture_output=True, text=True, timeout=min(60, remaining))
                observation.update({'returnCode': probe.returncode, 'stderr': probe.stderr})
                assert probe.returncode == 0 and not probe.stderr.strip()
                media = json.loads(probe.stdout)
                observation['actualProbe'] = media
                assert len(media['streams']) == 1
                video = media['streams'][0]
                frames = 192 if record['schedule']['recipe_id'].startswith('animation-') else 240
                assert video['codec_type'] == 'video' and video['codec_name'] == 'h264'
                assert int(video['nb_read_frames']) == frames
                assert video['width'] == 1920 and video['height'] == 1080 and video['pix_fmt'] == 'yuv420p'
                assert video['avg_frame_rate'] == '24/1'
                assert all(video.get(key) == 'bt709' for key in ['color_space', 'color_transfer', 'color_primaries'])
                assert observation['sha256'] == info['artifactSha256']
                assert observation['byteSize'] == info['fileSizeBytes']
                observation['passed'] = True
            except Exception as error:
                observation['error'] = str(error) or type(error).__name__
        print(json.dumps({'case': entry['name'], 'artifacts': len(current['artifacts']),
                          'passed': sum(a['passed'] for a in current['artifacts'])}), flush=True)
    gpu = subprocess.run(['nvidia-smi', '-i', '0', '--query-gpu=index,name,driver_version,pci.bus_id',
                          '--format=csv,noheader'], capture_output=True, text=True, timeout=10)
    result['freshSelectedGpu'] = {'returnCode': gpu.returncode, 'stdout': gpu.stdout, 'stderr': gpu.stderr}
    result['elapsedSeconds'] = time.monotonic() - started
    expected_cases = {'smoke', *[case['name'] for case in PLAN['campaigns']]}
    result['passed'] = ({case['name'] for case in result['cases']} == expected_cases and gpu.returncode == 0
                        and all(c['ledgerUnchanged'] and c['artifacts'] and all(a['passed'] for a in c['artifacts']) for c in result['cases']))
    (ROOT / 'fresh-artifact-audit.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'passed': result['passed'], 'elapsedSeconds': result['elapsedSeconds']}), flush=True)
    if not result['passed']:
        raise SystemExit(1)


def main():
    with (Path(PLAN['physicalStateRoot']) / 'measurement.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        audit_locked()


if __name__ == '__main__':
    main()
