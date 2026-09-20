"""Verify completed local fault receipts and copy metadata without media."""
import datetime
import hashlib
import json
import plistlib
from pathlib import Path
import shutil
import subprocess

import psutil

ROOT = Path('/Users/ofhd/Developer/Encoding_Database')
FAULT = ROOT / '.build/native-faults-939823e'
OUT = Path(__file__).resolve().parent.parent
SOURCE = '939823ead2c052572f9deb5c9f91c85435d5661d'
BINARY_SHA = 'ad01bfd36ad84e0e0d9f45730bd195c1b940a240493d093f6a875faa97a6f2c0'
COPIES = []


def read(path):
    return json.loads(path.read_text())


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def copy(path, relative):
    target = OUT / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, target)
    digest = sha(path)
    assert sha(target) == digest
    COPIES.append({'source': str(path), 'packetPath': str(relative), 'sha256': digest, 'byteSize': target.stat().st_size})


assert sha(FAULT / 'épreuve 客户端/encodingdb-client-macos') == BINARY_SHA
cases = {}
runtimes = []
for folder, names in [('receipts', ['corrupt-pack', 'cancel', 'kill-after-resume', 'resume-after-kill', 'disk-full', 'disk-full-freed-resume']),
                       ('live-orphan-receipts', ['live-orphan-kill', 'live-orphan-resume'])]:
    base = FAULT / folder
    assert (base / 'host-lock-released.json').exists()
    assert not any(row['alive'] for row in read(base / 'owned-cleanup.json'))
    for name in names:
        result = read(base / (name + '.json'))
        assert result['sourceCommit'] == SOURCE and result['artifactSha256'] == BINARY_SHA
        assert not result.get('wallTimeout') and '--no-submit' in result['command']
        cases[name] = result
    for path in sorted(base.glob('*-embedded-runtime.json')):
        runtime = read(path)
        assert runtime['frozen'] and '_MEI' in runtime['ffmpegPath'] and '_MEI' in runtime['ffprobePath']
        assert runtime['identity']['ffmpeg']['sha256'] == 'ef1da73e929cb11aae5f4770ba0fcab617641d9feb03c5d00bb7c0702ebdf5d2'
        assert runtime['identity']['ffprobe']['sha256'] == '12da1d9d189806ba249f3c44b703f20b804e309a6150b3bef1e0ab4b569e9b66'
        assert not Path(runtime['extractionRoot']).exists()
        runtimes.append({'receipt': str(path), 'extractionRoot': runtime['extractionRoot'], 'removedAfterExit': True, 'frozen': True})
    for path in sorted(base.rglob('*')):
        if path.is_file() and path.suffix in ('.json', '.log'):
            relative = Path('original') / folder / path.relative_to(base)
            if path.suffix == '.log':
                relative = Path(str(relative) + '.txt')
            copy(path, relative)
assert {name: result['exitCode'] for name, result in cases.items()} == {
    'corrupt-pack': 3, 'cancel': 130, 'kill-after-resume': -9, 'resume-after-kill': 0,
    'disk-full': 6, 'disk-full-freed-resume': 0, 'live-orphan-kill': -9, 'live-orphan-resume': 0,
}
assert cases['corrupt-pack']['attemptRecords'] == 0
assert cases['corrupt-pack']['corruptPackBytes'] == cases['corrupt-pack']['referencePackBytes']
assert cases['corrupt-pack']['corruptPackSha256'] != cases['corrupt-pack']['referencePackSha256']
assert not cases['cancel']['orphanAliveAfterStop'] and cases['kill-after-resume']['orphanAliveAfterStop']
assert any(row['schedule']['phase'] == 'measured' for row in cases['kill-after-resume']['beforeStop'].values())
for name in ['resume-after-kill', 'disk-full', 'disk-full-freed-resume', 'live-orphan-resume']:
    assert cases[name]['priorRecordsUnchanged']
for name in ['resume-after-kill', 'live-orphan-resume']:
    assert not cases[name]['oldOrphanStillAlive'] and cases[name]['orphanReceiptRemoved']
assert cases['live-orphan-kill']['orphanPause']['signal'] == 'SIGSTOP'
assert cases['live-orphan-kill']['orphanAliveAfterStop']
capacity = read(FAULT / 'receipts/disk-full-capacity.json')
assert capacity['totalBytes'] <= 128 * 1024 * 1024 and capacity['availableBytes'] == 0
assert capacity['osError']['errno'] == 28 and capacity['osError']['freshOneByteWriteFailed']
detach = read(FAULT / 'receipts/disk-full-detached.json')
assert detach['detached'] and detach['originalHostQueueRestored'] and detach['originalRecordsUnchanged']
assert read(FAULT / 'receipts/protected-inputs-before.json') == read(FAULT / 'receipts/protected-inputs-after.json')
for path, digest in read(FAULT / 'receipts/protected-inputs-after.json').items():
    assert sha(Path(path)) == digest
mounts = plistlib.loads(subprocess.check_output(['hdiutil', 'info', '-plist'], timeout=30))
matching = [image for image in mounts.get('images', []) if str(FAULT) in image.get('image-path', '')]
assert not matching
owned_live = []
for process in psutil.process_iter(['pid', 'name', 'cmdline', 'status']):
    try:
        info = process.info
        if info['name'] in {'ffmpeg', 'ffprobe', 'encodingdb-client-macos'} and info['status'] != psutil.STATUS_ZOMBIE:
            if any(str(FAULT / 'épreuve 客户端') in arg for arg in (info['cmdline'] or [])):
                owned_live.append(info)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
assert not owned_live

reference = next((ROOT / '.build/native-seven-mac-939823e/épreuve 客户端/software/queue/campaigns').glob('*/manifest.json'))
physical_source = read(reference)['physicalSourceId']
campaigns = []
for queue_name in ['recovery-queue', 'live-orphan-queue']:
    queue = FAULT / 'épreuve 客户端' / queue_name
    for path in sorted(queue.rglob('*.json')):
        copy(path, Path('original/queues') / queue_name / path.relative_to(queue))
    for manifest_path in queue.glob('campaigns/*/manifest.json'):
        manifest = read(manifest_path)
        assert manifest['physicalSourceId'] == physical_source
        attempts = []
        for path in sorted(manifest_path.parent.glob('attempt-*.json')):
            attempt = read(path)
            artifact = Path(attempt['metadata']['info']['artifactPath'])
            assert sha(artifact) == attempt['metadata']['info']['artifactSha256']
            attempts.append({'record': str(path), 'recordSha256': sha(path), 'artifact': str(artifact), 'artifactSha256': sha(artifact),
                             'schedule': attempt['schedule'], 'overallValidity': attempt['overallValidity']})
        assert (manifest_path.parent / 'campaign-complete.json').exists()
        campaigns.append({'queue': queue_name, 'campaignId': manifest_path.parent.name, 'physicalSourceId': physical_source, 'attempts': attempts})
for name in ['mac-faults-939823e-harness.log', 'mac-live-orphan-939823e-harness.log']:
    copy(ROOT / '.build' / name, Path('original') / (name + '.txt'))
summary = {
    'schemaVersion': 1, 'auditedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'sourceCommit': SOURCE,
    'executableSha256': BINARY_SHA, 'passed': True, 'diagnosticNotCalibration': True,
    'noSubmission': True, 'noRemoteHostContact': True,
    'exitCodes': {name: result['exitCode'] for name, result in cases.items()},
    'volumeCapacity': capacity, 'volumeDetached': detach, 'matchingMountedFaultImages': matching,
    'sharedProtectedInputsUnchanged': True, 'campaigns': campaigns, 'packagedRuntimes': runtimes, 'liveTaskClientOrMediaProcesses': owned_live,
    'limitations': ['Fault tests on battery; preserve all suspect flags.', 'Not calibration, throughput, eligibility, server, upload, or PL evidence.',
                    'Corrupt-pack network fallback uses an intentionally failing localhost proxy, not a real-server recovery test.'],
}
(OUT / 'acceptance.json').write_text(json.dumps(summary, indent=2) + '\n')
(OUT / 'original-file-checksums.json').write_text(json.dumps(COPIES, indent=2) + '\n')
print(json.dumps({'passed': True, 'exitCodes': summary['exitCodes'], 'copiedMetadataFiles': len(COPIES), 'campaigns': len(campaigns)}, indent=2))
