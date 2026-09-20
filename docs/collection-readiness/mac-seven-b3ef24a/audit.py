"""Read-only audit of retained native acceptance artifacts; writes only this packet."""
import collections
import datetime
import hashlib
import json
import math
import importlib.util
from pathlib import Path
import shutil
import statistics
import subprocess

from PyInstaller.archive.readers import CArchiveReader

ROOT = Path('/Users/ofhd/Developer/Encoding_Database')
INPUT = ROOT / '.build/native-seven-mac-b3ef24a/épreuve 客户端'
PACKAGE = ROOT / '.build/release-20260919/macos-b3ef24a'
OUTPUT = Path(__file__).resolve().parent
PROBE = ROOT / '.build/runtime-macos-arm64-vmaf3.2/ffprobe'
SOURCE = 'b3ef24abb020bc6af5b5fe6b849ba3eae8314be2'
BINARY_SHA = '443e293e82f0f042b2017f55d12f1d73c7d5b6944cb43d6c9d70281beef6d70c'
COPIES = []


def read(path):
    return json.loads(path.read_text())


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def copy(path, relative):
    target = OUTPUT / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, target)
    digest = sha(path)
    assert sha(target) == digest
    COPIES.append({'originalPath': str(path), 'packetPath': str(relative), 'sha256': digest, 'byteSize': target.stat().st_size})


def near(actual, expected):
    assert math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-8), (actual, expected)


def capture(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    return {'command': command, 'exitCode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}


receipt = read(INPUT / 'receipt.json')
plan = read(INPUT / 'plan.json')
assert len(receipt['cases']) == 2 and all(case.get('exitCode') == 0 for case in receipt['cases'])
assert plan['sourceCommit'] == SOURCE and plan['executableSha256'] == BINARY_SHA
assert sha(INPUT / 'run.py') == plan['runnerSha256']
ledger_spec = importlib.util.spec_from_file_location('native_replay_ledger', ROOT / 'scripts/native-e2e-ledger.py')
ledger_module = importlib.util.module_from_spec(ledger_spec)
ledger_spec.loader.exec_module(ledger_module)
ledgers = {}
for case in receipt['cases']:
    assert case['seed'] == plan['seeds'][case['name']]
    assert case['seed'] == int(hashlib.sha256(f"{SOURCE}:mac-native-acceptance:{case['name']}:1".encode()).hexdigest()[:13], 16)
    ledger = ledger_module.capture(INPUT / case['name'] / 'queue')
    target = OUTPUT / 'replay-ledgers' / (case['name'] + '-before-upload.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        ledger_module.assert_unchanged(read(target), ledger)
    else:
        with target.open('x') as stream:
            json.dump(ledger, stream, indent=2)
            stream.write('\n')
    ledgers[case['name']] = ledger
print('Both immutable replay ledgers captured before media probing.', flush=True)
assert receipt['sourceCommit'] == SOURCE and receipt['executableSha256'] == BINARY_SHA
assert sha(PACKAGE / 'encodingdb-client-macos') == BINARY_SHA
release = read(PACKAGE / 'encodingdb-client-macos.release-manifest.json')
assert sha(PROBE) == '12da1d9d189806ba249f3c44b703f20b804e309a6150b3bef1e0ab4b569e9b66'
assert sha(ROOT / 'client/resources/vmaf/vmaf_v1.0.16_3d0h.json') == release['qualityModel']['sha256']
archive = CArchiveReader(str(PACKAGE / 'encodingdb-client-macos'))
embedded_model_sha = hashlib.sha256(archive.extract(release['qualityModel']['bundleRelativePath'])).hexdigest()
assert embedded_model_sha == release['qualityModel']['sha256']
assert sha(PACKAGE / 'encodingdb-test-suite-v1.tar.gz') == release['suite']['pack']['sha256']
copy(INPUT / 'receipt.json', Path('original/receipt.json'))
copy(INPUT / 'plan.json', Path('original/plan.json'))
copy(INPUT / 'post-run-owned-processes.json', Path('original/post-run-owned-processes.json'))
copy(INPUT / 'run.py', Path('original/run.py'))
for path in PACKAGE.glob('encodingdb-client-macos.*'):
    if path.is_file() and path.stat().st_size < 100000:
        copy(path, Path('original/package') / path.name)

summary = {
    'schemaVersion': 1, 'auditedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'sourceCommit': SOURCE, 'executableSha256': BINARY_SHA,
    'freshProbePath': str(PROBE), 'freshProbeSha256': sha(PROBE),
    'qualityModel': release['qualityModel'], 'embeddedModelSha256': embedded_model_sha, 'suite': release['suite'],
    'nativeHost': capture(['sw_vers']), 'architecture': capture(['uname', '-m']),
    'signingDisplay': capture(['codesign', '-dv', '--verbose=4', str(PACKAGE / 'encodingdb-client-macos')]),
    'signingVerify': capture(['codesign', '--verify', '--strict', str(PACKAGE / 'encodingdb-client-macos')]),
    'minimumOsFromAllRuntimeHeaders': release['runtime']['minimumOsFromHeaders'],
    'claims': 'Retained no-submit native acceptance and fresh artifact audit only. No server analysis, calibration, PL, or production claim.',
    'cases': [], 'sourceInputs': {},
}
assert summary['minimumOsFromAllRuntimeHeaders'] == '27.0.0'
for case in receipt['cases']:
    name = case['name']
    base = INPUT / name
    assert case['exitCode'] == 0 and '--no-submit' in case['command']
    assert sha(base / 'client.log') == case['logSha256']
    for path in base.rglob('*'):
        if path.is_file() and (path.suffix == '.json' or path.name == 'client.log'):
            assert path.stat().st_size < 2_000_000, path
            relative = Path('original') / name / path.relative_to(base)
            if path.name == 'client.log':
                relative = relative.with_name('client-log.txt')
            copy(path, relative)
    ledger = ledgers[name]
    if (base / 'before-upload.json').exists():
        ledger_module.assert_unchanged(read(base / 'before-upload.json'), ledger)
    for relative, expected in ledger['files'].items():
        assert sha(base / 'queue' / relative) == expected, relative
    campaign = base / 'queue/campaigns' / case['campaigns'][0]
    manifest = read(campaign / 'manifest.json')
    embedded = read(base / 'embedded-runtime.json')
    assert embedded['frozen'] is True
    assert '_MEI' in embedded['ffmpegPath'] and '_MEI' in embedded['ffprobePath']
    assert manifest['runtime']['ffmpeg']['sha256'] == 'ef1da73e929cb11aae5f4770ba0fcab617641d9feb03c5d00bb7c0702ebdf5d2'
    assert manifest['runtime']['ffprobe']['sha256'] == sha(PROBE)
    assert manifest['runtime']['clientExecutionArchitecture'] == 'arm64'
    if name == 'videotoolbox':
        assert manifest['selectedDevices']['h264_videotoolbox']['deviceId'] == 'videotoolbox:system'
        assert manifest['selectedDevices']['h264_videotoolbox']['model'] == 'Apple M4 Pro'
    attempts = [read(path) for path in sorted(campaign.glob('attempt-*.json'))]
    phases = collections.Counter(a['schedule']['phase'] for a in attempts)
    assert phases['warmup'] == 7 and 14 <= phases['measured'] <= 28 and len(attempts) == sum(phases.values())
    assert set(phases) == {'warmup', 'measured'}
    result = {'name': name, 'campaignId': campaign.name, 'exitCode': case['exitCode'],
              'physicalSourceId': manifest['physicalSourceId'], 'selectedDevices': manifest['selectedDevices'],
              'runtimeFingerprint': embedded['runtimeLockFingerprint'], 'attemptCounts': dict(phases), 'seed': case['seed'], 'attempts': [], 'groups': []}
    for attempt in attempts:
        info = attempt['metadata']['info']
        schedule = attempt['schedule']
        clip = attempt['metadata']['suiteClip']['clip_id']
        expected_frames = 192 if clip == 'animation-1080p24-final' else 240
        artifact = Path(info['artifactPath'])
        source = Path(attempt['metadata']['effectiveInput'])
        if str(source) not in summary['sourceInputs']:
            summary['sourceInputs'][str(source)] = sha(source)
        assert summary['sourceInputs'][str(source)] == attempt['metadata']['inputHash']
        assert sha(artifact) == info['artifactSha256']
        process = read(Path(str(artifact) + '.process.json'))
        assert process['returncode'] == 0 and process['artifactSha256'] == info['artifactSha256']
        assert process['processRuntime']['executableSha256'] == manifest['runtime']['ffmpeg']['sha256']
        assert process['processRuntime']['runtimeDependencies'] == manifest['runtime']['runtimeDependencies']
        command = info['executedCommand']
        assert command == process['command'] and command[0] == embedded['ffmpegPath']
        recipe = json.loads(info['effectiveRecipeJson'])
        if name == 'videotoolbox':
            assert command[command.index('-c:v') + 1] == 'h264_videotoolbox'
            assert command[command.index('-b:v') + 1] == '6000k'
            assert not set(['-crf', '-q:v', '-cq', '-qp']).intersection(command)
            assert recipe['rateControlEffective']['mode'] == 'vbr'
            assert recipe['rateControlEffective']['targetBitrateKbps'] == 6000
        else:
            assert command[command.index('-c:v') + 1] == 'libx264'
            assert command[command.index('-crf') + 1] == '23'
            assert command[command.index('-preset') + 1] == 'fast'
        probe_command = [str(PROBE), '-v', 'error', '-threads', '2', '-count_frames', '-show_streams', '-show_format', '-of', 'json', str(artifact)]
        observed = capture(probe_command)
        assert observed['exitCode'] == 0 and not observed['stderr']
        media = json.loads(observed['stdout'])
        assert len(media['streams']) == 1
        stream = media['streams'][0]
        assert stream['codec_type'] == 'video' and stream['codec_name'] == 'h264'
        assert (stream['width'], stream['height'], stream['pix_fmt']) == (1920, 1080, 'yuv420p')
        assert int(stream['nb_read_frames']) == expected_frames
        assert stream['avg_frame_rate'] == '24/1' and stream['r_frame_rate'] == '24/1'
        assert all(stream[key] == 'bt709' for key in ['color_space', 'color_transfer', 'color_primaries'])
        near(float(stream['duration']), expected_frames / 24)
        (OUTPUT / 'fresh-probes' / name).mkdir(parents=True, exist_ok=True)
        (OUTPUT / 'fresh-probes' / name / (artifact.name + '.json')).write_text(json.dumps(observed, indent=2) + '\n')
        timing = attempt['timing']
        elapsed = (timing['end_monotonic_ns'] - timing['start_monotonic_ns']) / 1e9
        near(timing['elapsed_s'], elapsed)
        near(process['elapsed'], elapsed)
        near(timing['encode_fps'], expected_frames / elapsed)
        assert info['encodeTimerBoundary'] == 'ffmpeg-process-v1'
        assert info['encodeStartMonotonicNs'] == timing['start_monotonic_ns']
        assert info['encodeEndMonotonicNs'] == timing['end_monotonic_ns']
        assert info['elapsedMs'] == round(elapsed * 1000)
        assert timing['encoded_frame_count'] == expected_frames and timing['source_frame_count'] == expected_frames
        env = attempt['environmentSnapshot']
        if schedule['phase'] == 'measured':
            assert env is not None
            assert 'cpu_psutil_thread_window_v1' in env['telemetry_sources']
            assert math.isfinite(env['background_cpu_pct'])
        if info['ffmpegSampleCount'] > 0:
            assert 'ffmpeg_psutil_process_window_v1' in info['telemetrySources']
            assert math.isfinite(info.get('ffmpegCpuUtilAvg')) and info.get('ffmpegCpuUtilAvg') >= 0
            assert math.isfinite(info.get('ffmpegCpuUtilMax')) and info.get('ffmpegCpuUtilMax') >= 0
        else:
            assert 'ffmpeg_psutil_process_window_v1' not in info['telemetrySources']
            assert info.get('ffmpegCpuUtilAvg') is None and info.get('ffmpegCpuUtilMax') is None
            assert 'ffmpeg_unavailable' in info['telemetryMissing']
        if name == 'videotoolbox' and schedule['phase'] == 'measured':
            assert 'gpu_ioreg_agx_system_utilization_v1' in env['telemetry_sources']
        result['attempts'].append({'executionOrder': schedule['execution_order'], 'clipId': clip, 'phase': schedule['phase'],
            'repetition': schedule['repetition_index'], 'artifactSha256': info['artifactSha256'], 'frames': expected_frames,
            'elapsedSeconds': elapsed, 'encodeFps': timing['encode_fps'], 'overallValidity': attempt['overallValidity'],
            'countedForStability': attempt['countedForStability'], 'backgroundCpuPct': env['background_cpu_pct'] if env else None,
            'backgroundGpuPct': env['background_gpu_pct'] if env else None, 'preRunPowerSource': env['power_source'] if env else None,
            'encodePowerSource': info.get('powerSource'), 'processCpuAveragePct': info.get('ffmpegCpuUtilAvg'),
            'processCpuMaximumPct': info.get('ffmpegCpuUtilMax'), 'processCpuSampleCount': info['ffmpegSampleCount']})
    protocol = read(base / 'queue/protocol-attempts' / (campaign.name + '.json'))
    assert len(protocol['recipeResults']) == 7
    for group in protocol['recipeResults']:
        selected = [a for a in attempts if a['schedule']['recipe_id'] == group['recipeId']]
        assert len([a for a in selected if a['schedule']['phase'] == 'warmup']) == 1
        assert 3 <= len(selected) <= 5
        measured = [a for a in selected if a['schedule']['phase'] == 'measured' and a['countedForStability']]
        assert 2 <= len(measured) <= 4
        assert group['stability']['sample_count'] == len(measured)
        values = [a['timing']['elapsed_s'] for a in measured]
        spread = (max(values) - min(values)) / statistics.mean(values)
        near(group['stability']['elapsed_relative_spread'], spread)
        assert group['stability']['stable'] == (spread <= 0.03)
        for attempt in measured:
            submission = read(campaign / f"submission-{attempt['schedule']['execution_order']:06d}.json")['runCreate']
            assert submission['measurementGroup']['completed'] is True
            assert len(submission['measurementGroup']['countedAttempts']) == len(measured)
            assert [m['repetitionIndex'] for m in submission['measurementGroup']['countedAttempts']] == sorted(a['schedule']['repetition_index'] for a in measured)
            for member in submission['measurementGroup']['countedAttempts']:
                target = next(a for a in measured if a['schedule']['repetition_index'] == member['repetitionIndex'])
                near(member['encodeWallTimeMs'], target['timing']['elapsed_s'] * 1000)
            near(submission['encodeWallTimeMs'], attempt['timing']['elapsed_s'] * 1000)
        result['groups'].append({'recipeId': group['recipeId'], 'measuredSeconds': values, 'relativeSpread': spread,
                                 'stable': spread <= 0.03, 'countedAttempts': len(measured)})
    result['validityCounts'] = dict(collections.Counter(a['overallValidity']['state'] for a in attempts))
    summary['cases'].append(result)
summary['passed'] = True
summary['verificationScope'] = 'Artifact/metadata integrity checks passed; does not assert all timing groups are stable or all environments valid.'
summary['replayLedgers'] = {name: {'path': 'replay-ledgers/' + name + '-before-upload.json', 'sha256': sha(OUTPUT / 'replay-ledgers' / (name + '-before-upload.json')), 'immutableFileCount': len(ledger['files'])} for name, ledger in ledgers.items()}
(OUTPUT / 'audit-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
(OUTPUT / 'original-file-checksums.json').write_text(json.dumps(COPIES, indent=2) + '\n')
print(json.dumps({case['name']: {'attempts': len(case['attempts']), 'validity': case['validityCounts'],
      'stableGroups': sum(group['stable'] for group in case['groups'])} for case in summary['cases']}, indent=2))
