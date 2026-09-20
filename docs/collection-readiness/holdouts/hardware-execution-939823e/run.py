"""Frozen hardware-only operator: dry run by default, never uploads or analyzes."""
import argparse
import datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def read_sealed(path, key):
    document = json.loads(Path(path).read_text())
    claimed = document.pop(key)
    if canonical_hash(document) != claimed:
        raise ValueError(f'{key} mismatch: {path}')
    document[key] = claimed
    return document


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + '.partial')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def command_for(host, cell):
    return [host['python'], str(Path(host['checkout']) / 'scripts/run-validation-campaign.py'),
            '--registry', host['registry'], '--workload', cell['workloadId'],
            '--reference', cell['referencePath'], '--output', str(Path(host['outputRoot']) / cell['cellId']),
            '--encoder', cell['encoder'], '--preset', cell['preset'], '--seed', str(cell['seed']),
            '--max-duration-minutes', str(cell['maximumMeasurementMinutes']),
            '--target-bitrate-kbps', str(cell['targetBitrateKbps'])]


def validate_allocation(document, plan, host_name):
    expected = {'host': host_name, 'executionHash': plan['executionHash'], 'sourceCommit': plan['sourceCommit'],
                'exclusiveTimingGranted': True, 'nativeAcceptanceComplete': True,
                'noBuildAnalysisUploadOrSourcePreparation': True}
    if any(document.get(key) != value for key, value in expected.items()):
        raise ValueError('Allocation does not authorize this exact host and execution phase')
    expires = datetime.datetime.fromisoformat(document['expiresAt'])
    if expires.tzinfo is None or expires <= datetime.datetime.now(datetime.timezone.utc):
        raise ValueError('Allocation is expired or has no timezone')


def validate_previous(previous, execution_hash, command, resume_interrupted):
    if previous.get('executionHash') != execution_hash or previous.get('command') != command:
        raise ValueError('Existing ledger belongs to different source, settings or plan')
    if previous.get('status') == 'COMPLETE':
        if previous.get('exitCode') not in (0, 4) or not previous.get('receipts'):
            raise ValueError('Terminal ledger lacks a completed protocol receipt')
        for receipt in previous['receipts']:
            if digest(receipt['path']) != receipt['sha256']:
                raise ValueError('Completed receipt changed; refusing to rerun')
        return 'reuse'
    if previous.get('status') == 'FAILED':
        raise ValueError('Failed observation is retained; no automatic new attempt or replacement')
    if not resume_interrupted:
        raise ValueError('Interrupted cell requires --resume-interrupted after verifying no owned process remains')
    return 'resume'


def verify_runtime(host):
    if digest(host['runtimeLockPath']) != host['runtimeLockSha256']:
        raise ValueError('Reviewed filtered runtime lock bytes changed')
    payload = json.loads(Path(host['runtimeLockPath']).read_text())
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    if fingerprint != host['runtimeLockFingerprint']:
        raise ValueError('Reviewed runtime cohort fingerprint changed')
    for entry in host['runtimeFiles']:
        path = Path(entry['path'])
        if path.stat().st_size != entry['byteSize'] or digest(path) != entry['sha256']:
            raise ValueError(f'Runtime bytes changed: {path}')


def validate_receipt(receipt, cell, host, plan):
    if receipt['seed'] != cell['seed'] or receipt['runnerSha256'] != plan['runnerSha256']:
        raise ValueError('Receipt execution identity differs')
    if receipt['physicalSourceId'] != host['physicalSourceId'] or receipt['sourceRegistrationHash'] != cell['sourceRegistrationHash']:
        raise ValueError('Receipt source identity differs')
    if receipt['runtimeVerification']['fingerprint'] != host['runtimeLockFingerprint']:
        raise ValueError('Receipt used another runtime cohort')
    protocol = receipt['protocolConfig']
    if (protocol['warmup_runs'], protocol['minimum_measured_runs'], protocol['max_adaptive_repeats'], protocol['stability_threshold_ratio']) != (1, 2, 2, .03):
        raise ValueError('Receipt protocol gates changed')
    for group in receipt['campaign']['recipeResults']:
        for run in group['runs']:
            info = run['metadata'].get('info', {})
            if info.get('artifactPath') and digest(info['artifactPath']) != info['artifactSha256']:
                raise ValueError('Retained artifact differs')
            if run['countedForStability']:
                snapshot = run['environmentSnapshot'] or {}
                markers = set((snapshot.get('telemetry_sources') or '').split(','))
                pct = snapshot.get('background_cpu_pct')
                if not markers.intersection({'cpu_psutil_thread_window_v1', 'cpu_psutil_blocking_window_v1'}) or isinstance(pct, bool) or not isinstance(pct, (int, float)) or not math.isfinite(pct):
                    raise ValueError('Counted attempt lacks corrected CPU provenance')
                effective = json.loads(info['effectiveRecipeJson'])
                for key in ('rateControlRequested', 'rateControlEffective'):
                    if effective[key]['mode'] != 'vbr' or effective[key]['targetBitrateKbps'] != cell['targetBitrateKbps']:
                        raise ValueError('Native VBR target changed')


def environment_gate(host, encoder, env):
    # Read actual conditions without launching an encode or changing thresholds.
    code = '''import dataclasses,json,sys
sys.path.insert(0,sys.argv[1])
from client.hardware import detect_hardware
from client.main import _capture_protocol_environment_snapshot
from client.protocol import ProtocolConfig,validate_environment
s=_capture_protocol_environment_snapshot(hardware=detect_hardware(),encoder=sys.argv[2])
v=validate_environment(s,ProtocolConfig.for_version("7.1").environment)
print(json.dumps({"snapshot":dataclasses.asdict(s),"validity":dataclasses.asdict(v)}))
sys.exit(0 if s.power_source=="ac" and v.state=="valid" else 9)
'''
    result = subprocess.run([host['python'], '-c', code, host['checkout'], encoder], env=env, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ValueError('Environment is not ready; no encode launched: ' + result.stdout[-4000:] + result.stderr[-1000:])
    return json.loads(result.stdout.strip().splitlines()[-1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execution', type=Path, default=Path(__file__).with_name('execution.json'))
    parser.add_argument('--base-plan', type=Path, default=Path(__file__).parents[1] / 'timing-hardware-extension-v1.json')
    parser.add_argument('--host', choices=['Mac', 'P910'], required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--allocation', type=Path)
    parser.add_argument('--resume-interrupted', action='store_true')
    args = parser.parse_args()
    plan = read_sealed(args.execution, 'executionHash')
    base = read_sealed(args.base_plan, 'planHash')
    if base['planHash'] != plan['basePlanHash'] or base['cells'] != plan['cells']:
        raise ValueError('Original cell choices/order/seeds changed')
    if digest(__file__) != plan['operatorSha256']:
        raise ValueError('Operator driver differs from frozen execution')
    host = plan['hosts'][args.host]
    cells = [cell for cell in plan['cells'] if cell['host'] == args.host]
    if not args.execute:
        print(json.dumps({'mode': 'DRY_RUN_NO_HOST_PROBES_OR_WRITES', 'executionHash': plan['executionHash'],
                          'host': args.host, 'cells': [{'cellId': cell['cellId'], 'command': command_for(host, cell)} for cell in cells]}, indent=2))
        return 0
    if not args.allocation:
        raise ValueError('--execute requires a current parent allocation file')
    allocation = json.loads(args.allocation.read_text())
    validate_allocation(allocation, plan, args.host)
    state = Path(host['stateDirectory'])
    if (state / 'physical-source-id').read_text().strip() != host['physicalSourceId']:
        raise ValueError('Existing installation identity changed; no new identity created')
    with (state / 'measurement.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if digest(host['archivePath']) != plan['sourceArchiveSha256']:
            raise ValueError('Source archive changed or is unstaged')
        checkout = Path(host['checkout'])
        if subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip() != plan['sourceCommit']:
            raise ValueError('Checkout commit differs')
        subprocess.run(['git', '-C', str(checkout), 'diff', '--quiet', 'HEAD', '--'], check=True)
        if digest(checkout / 'scripts/run-validation-campaign.py') != plan['runnerSha256'] or digest(checkout / 'client/resources/vmaf/vmaf_v1.0.16_3d0h.json') != plan['model']['sha256']:
            raise ValueError('Runner or reviewed model bytes changed')
        verify_runtime(host)
        registry = read_sealed(host['registry'], 'registryHash')
        if registry['registryHash'] != base['registryHash']:
            raise ValueError('Registered source registry differs')
        env = {key: value for key, value in os.environ.items() if not key.startswith(('PYTHON', 'DYLD_', 'LD_'))}
        env.update(FFMPEG_EXE=host['ffmpeg'], FFPROBE_EXE=host['ffprobe'], ENCODINGDB_RUNTIME_LOCK_PATH=host['runtimeLockPath'], ENCODINGDB_STATE_DIR=str(state))
        evidence = Path(host['outputRoot']) / 'operator-ledger'
        evidence.mkdir(parents=True, exist_ok=True)
        atomic_json(evidence / ('allocation-' + datetime.datetime.now().strftime('%Y%m%dT%H%M%S') + '.json'), allocation)
        for cell in cells:
            validate_allocation(allocation, plan, args.host)
            if Path(host['pauseFile']).exists():
                return 11
            command = command_for(host, cell)
            report_path = evidence / (cell['cellId'] + '.json')
            previous = json.loads(report_path.read_text()) if report_path.exists() else None
            if previous and validate_previous(previous, plan['executionHash'], command, args.resume_interrupted) == 'reuse':
                for saved in previous['receipts']:
                    validate_receipt(json.loads(Path(saved['path']).read_text()), cell, host, plan)
                print(json.dumps({'cellId': cell['cellId'], 'status': 'REUSED_UNCHANGED_COMPLETED_RECEIPT'}), flush=True)
                continue
            if shutil.disk_usage(state).free < plan['minimumFreeBytes'] + base['maximumCellJournalBytes']:
                raise ValueError('Insufficient free space to preserve the reserve after one maximum-size cell')
            budget_root = Path(host['budgetRoot'])
            current_bytes = sum(p.stat().st_size for p in budget_root.rglob('*') if p.is_file())
            if current_bytes + base['maximumCellJournalBytes'] > host['maximumTaskBytes']:
                raise ValueError('Declared task storage budget would be exceeded; no evidence removed')
            registered = next(source for source in registry['sources'] if source['workloadId'] == cell['workloadId'])
            if Path(cell['referencePath']).stat().st_size != registered['byteSize'] or digest(cell['referencePath']) != cell['sourceSha256']:
                raise ValueError('Pre-staged reference differs')
            snapshot = environment_gate(host, cell['encoder'], env)
            report = {'executionHash': plan['executionHash'], 'cell': cell, 'command': command, 'status': 'RUNNING', 'startedAt': now(), 'preflight': snapshot,
                      'resumedFrom': previous, 'outerLockPath': str(state / 'measurement.lock')}
            atomic_json(report_path, report)
            with report_path.with_suffix('.log').open('a') as stream:
                result = subprocess.run(command, cwd=checkout, env=env, stdout=stream, stderr=stream)
            receipt_paths = list((Path(host['outputRoot']) / cell['cellId']).rglob('validation-campaign.json'))
            report.update(completedAt=now(), exitCode=result.returncode, status='FAILED', receipts=[])
            try:
                for path in receipt_paths:
                    receipt = json.loads(path.read_text())
                    validate_receipt(receipt, cell, host, plan)
                    stable = receipt['campaign']['recipeResults'][0]['stability']['stable']
                    if result.returncode in (0, 4) and (result.returncode == 0) != stable:
                        raise ValueError('Protocol stability and exit status disagree')
                    report['receipts'].append({'path': str(path), 'sha256': digest(path)})
                if result.returncode in (0, 4) and len(receipt_paths) == 1:
                    report['status'] = 'COMPLETE'
            except Exception as error:
                report['verificationError'] = str(error)
            atomic_json(report_path, report)
            print(json.dumps({'cellId': cell['cellId'], 'exitCode': result.returncode, 'status': report['status']}), flush=True)
            if report['status'] != 'COMPLETE':
                return 12
        atomic_json(evidence / 'phase-complete.json', {'executionHash': plan['executionHash'], 'host': args.host, 'cellCount': len(cells), 'completedAt': now()})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
