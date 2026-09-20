#!/usr/bin/env python3
"""Run create-only, local-only physical Windows acceptance with reviewed CI pins."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from datetime import datetime, timezone


RECIPES = {
    'x264-crf23': ['--codec', 'libx264', '--presets', 'fast', '--crf', '23'],
    'nvenc-cq24': ['--codec', 'h264_nvenc', '--presets', 'p4', '--crf', '24'],
    'nvenc-vbr6000': ['--codec', 'h264_nvenc', '--presets', 'p4', '--target-bitrate-kbps', '6000'],
}


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


@contextlib.contextmanager
def host_lock(root):
    import msvcrt
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'physical-operator.lock').open('a+b') as lock:
        lock.seek(0)
        lock.write(b'0')
        lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def verify_payload(payload, pins):
    # Pins are reviewed outside this harness against GitHub's exact artifact and
    # source merge tree; sidecars alone are not an independent trust anchor.
    if not re.fullmatch('[0-9a-f]{40}', pins['actualBuildRevision']):
        raise ValueError('An exact observed build revision is required')
    for name, expected in pins['files'].items():
        path = (payload / name).resolve(strict=True)
        if payload not in path.parents or sha(path) != expected:
            raise ValueError(f'Reviewed payload hash mismatch: {name}')
    exe = payload / 'encodingdb-client-windows-console.exe'
    manifest_path = payload / (exe.name + '.release-manifest.json')
    lock_path = payload / (exe.name + '.runtime-lock.json')
    for required in [exe.name, manifest_path.name, lock_path.name, 'encodingdb-test-suite-v1.tar.gz']:
        if required not in pins['files']:
            raise ValueError(f'Missing independent file pin: {required}')
    manifest = read(manifest_path)
    if manifest['source']['revision'] != pins['actualBuildRevision'] or manifest['source']['trackedChanges'] is not False:
        raise ValueError('Build source is not the reviewed clean revision')
    if sha(exe) != manifest['artifact']['sha256']:
        raise ValueError('Executable does not match release manifest')
    if sha(payload / 'encodingdb-test-suite-v1.tar.gz') != manifest['suite']['pack']['sha256']:
        raise ValueError('Suite pack does not match release manifest')
    if manifest['suite']['suiteFingerprint'] != pins['suiteFingerprint']:
        raise ValueError('Unexpected canonical suite')
    return exe, manifest


def audit(queue, phase, manifest):
    campaigns = list((queue / 'campaigns').glob('campaign-*'))
    if len(campaigns) != 1:
        raise ValueError('Expected exactly one campaign in the create-only phase queue')
    campaign = campaigns[0]
    if not (campaign / 'campaign-complete.json').is_file():
        raise ValueError('Campaign did not complete durably')
    runtime = read(phase / 'embedded-runtime.json')
    if runtime['frozen'] is not True or runtime['platform'] != 'win':
        raise ValueError('Actual execution did not report a frozen Windows runtime')
    extraction = Path(runtime['extractionRoot']).resolve()
    for helper in ['ffmpeg', 'ffprobe']:
        if extraction not in Path(runtime[helper + 'Path']).resolve().parents:
            raise ValueError('An external media helper was used')
        if runtime['identity'][helper]['sha256'] != manifest['runtime']['payload']['platforms']['win'][helper]['sha256']:
            raise ValueError('Observed embedded helper differs from reviewed lock')
    attempts = []
    for path in sorted(campaign.glob('attempt-*.json')):
        record = read(path)
        info = record['metadata'].get('info') or {}
        artifact = info.get('artifactPath')
        if artifact:
            target = Path(artifact).resolve(strict=True)
            if campaign.resolve() not in target.parents or sha(target) != info['artifactSha256']:
                raise ValueError('Retained artifact differs from immutable attempt record')
        attempts.append({'record': str(path), 'recordSha256': sha(path), 'schedule': record['schedule'],
                         'countedForStability': record.get('countedForStability'), 'metadata': record['metadata']})
    # Keep complete metadata and every group outcome, including SUSPECT/unstable.
    return {'campaignId': campaign.name, 'attempts': attempts, 'completion': read(campaign / 'campaign-complete.json'),
            'manifestSha256': sha(campaign / 'manifest.json'), 'runtime': runtime}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--pins', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--recipe', choices=RECIPES, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Only actual Windows is supported')
    payload = args.payload.resolve(strict=True)
    pins = read(args.pins)
    command = ['--cli', '--campaign', 'full', '--no-submit', '--base-url', 'http://127.0.0.1:9',
               '--max-duration-minutes', '20', '--max-storage-mb', '4096', '--max-attempts', '100'] + RECIPES[args.recipe]
    if not args.execute:
        print(json.dumps({'mode': 'plan-only', 'recipe': args.recipe, 'arguments': command, 'scope': 'physical acceptance; not calibration fitting data'}))
        return
    exe, manifest = verify_payload(payload, pins)
    root = args.root.resolve()
    state = root / 'host-state'
    with host_lock(state):
        phase = root / ('acceptance-' + args.recipe + '-é')
        phase.mkdir(parents=True, exist_ok=False)
        queue = phase / 'queue-客户'
        (phase / 'tmp').mkdir()
        env = os.environ.copy()
        for key in list(env):
            if re.match(r'^(FFMPEG_EXE|FFPROBE_EXE|ENCODINGDB_.*|V7_OPERATOR_.*|TCL_LIBRARY|TK_LIBRARY|PYTHONPATH|PYTHONHOME|LD_LIBRARY_PATH|DYLD_.*)$', key):
                del env[key]
        env.update(ENCODINGDB_STATE_DIR=str(state), ENCODINGDB_SUITE_CACHE_DIR=str(root / 'suite-cache'),
                   ENCODINGDB_SUITE_PACK_PATH=str(payload / 'encodingdb-test-suite-v1.tar.gz'),
                   ENCODINGDB_RUNTIME_EVIDENCE_PATH=str(phase / 'embedded-runtime.json'),
                   TEMP=str(phase / 'tmp'), TMP=str(phase / 'tmp'))
        command = [str(exe), *command, '--queue-dir', str(queue)]
        receipt = {'status': 'RUNNING', 'scope': 'physical Windows native acceptance; no submissions; not fitting data',
                   'startedAt': datetime.now(timezone.utc).isoformat(), 'command': command, 'pins': pins,
                   'forcedCleanup': False, 'recipe': args.recipe}
        receipt_path = phase / 'operator-receipt.json'
        save(receipt_path, receipt)
        started = time.monotonic()
        try:
            with (phase / 'stdout.log').open('wb') as stdout, (phase / 'stderr.log').open('wb') as stderr:
                process = subprocess.Popen(command, cwd=phase, env=env, stdout=stdout, stderr=stderr)
                receipt['pid'] = process.pid
                save(receipt_path, receipt)
                try:
                    receipt['exitCode'] = process.wait(timeout=2400)
                except subprocess.TimeoutExpired:
                    # Popen still owns this live PID: never discover/kill by name.
                    receipt['forcedCleanup'] = True
                    result = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, text=True, timeout=30)
                    receipt['cleanup'] = {'exitCode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
                    process.wait(timeout=30)
                    raise RuntimeError('Acquisition plus measurement deadline exceeded; this phase fails')
            if receipt['exitCode'] != 0:
                raise RuntimeError(f"Native client exited {receipt['exitCode']}; evidence retained")
            receipt['evidence'] = audit(queue, phase, manifest)
            receipt['installationId'] = (state / 'physical-source-id').read_text().strip()
            receipt['status'] = 'EXECUTED_PENDING_INDEPENDENT_REVIEW'
        except Exception as error:
            receipt['status'] = 'FAILED'
            receipt['error'] = str(error)
            raise
        finally:
            receipt['wallSeconds'] = time.monotonic() - started
            receipt['finishedAt'] = datetime.now(timezone.utc).isoformat()
            save(receipt_path, receipt)
            print(json.dumps({'receipt': str(receipt_path), 'status': receipt['status']}))


if __name__ == '__main__':
    main()
