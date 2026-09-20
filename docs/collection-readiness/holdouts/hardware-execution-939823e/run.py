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
    status = previous.get('status')
    if status not in ('RUNNING', 'INTERRUPTED', 'PAUSED_MEASUREMENT_BUDGET'):
        raise ValueError('Unknown state is not an interrupted observation')
    if status == 'INTERRUPTED' and previous.get('operatorInterrupted') is not True:
        raise ValueError('Interruption was not observed by this operator')
    if status == 'PAUSED_MEASUREMENT_BUDGET' and (previous.get('exitCode') != 11 or not previous.get('resumeEvidence')):
        raise ValueError('Budget pause lacks verified retained evidence')
    for saved in previous.get('resumeEvidence', []):
        if digest(saved['path']) != saved['sha256']:
            raise ValueError('Retained resume evidence changed; refusing replacement attempts')
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


def journal_evidence(cell, host, plan, *, budget_pause=False):
    output = Path(host['outputRoot']) / cell['cellId']
    manifests = list(output.rglob('manifest.json'))
    if not manifests and not budget_pause:
        return []  # interrupted before the runner created its journal
    if len(manifests) != 1:
        raise ValueError('Resume requires exactly one retained campaign manifest')
    manifest_path = manifests[0]
    journal = manifest_path.parent
    manifest = json.loads(manifest_path.read_text())
    validate_receipt({**manifest, 'campaign': {'recipeResults': []}}, cell, host, plan)
    recipe = manifest['recipe']
    rc = recipe.get('rateControl', {})
    if (recipe.get('encoder'), recipe.get('preset'), recipe.get('crf'), rc.get('mode'), rc.get('targetBitrateKbps')) != (
            cell['encoder'], cell['preset'], None, 'vbr', cell['targetBitrateKbps']):
        raise ValueError('Retained recipe differs from the frozen hardware cell')
    recipe_id = canonical_hash(recipe)
    campaign_id = 'campaign-' + canonical_hash({'protocolVersion': '7.1', 'recipeIds': [recipe_id], 'seed': cell['seed']})[:16]
    if journal.name != campaign_id or manifest.get('sourceRegistrationHash') != recipe.get('sourceRegistrationHash'):
        raise ValueError('Retained campaign or recipe identity differs')
    paths = [manifest_path]
    attempts = sorted(journal.glob('attempt-*.json'))
    for path in attempts:
        record = json.loads(path.read_text())
        schedule = record['schedule']
        if schedule['campaign_id'] != campaign_id or schedule['recipe_id'] != recipe_id:
            raise ValueError('Completed attempt belongs to another recipe or campaign')
        info = record['metadata'].get('info', {})
        if info.get('artifactPath'):
            artifact = Path(info['artifactPath'])
            if journal.resolve() not in artifact.resolve().parents:
                raise ValueError('Completed attempt artifact left its owned journal')
            if artifact.exists():
                if digest(artifact) != info.get('artifactSha256'):
                    raise ValueError('Completed attempt artifact changed')
                paths.append(artifact)
            elif not info.get('error'):
                raise ValueError('Completed attempt artifact is missing')
        paths.append(path)
    if budget_pause:
        pauses = list(output.rglob('validation-pause.json'))
        if pauses != [journal / 'validation-pause.json']:
            raise ValueError('Budget exit requires exactly one owned validation pause')
        pause = json.loads(pauses[0].read_text())
        expected = {'status': 'PAUSED_MEASUREMENT_BUDGET', 'maximumMinutes': cell['maximumMeasurementMinutes'],
                    'campaignId': campaign_id, 'seed': cell['seed'], 'completedAttempts': len(attempts),
                    'journalPath': str(journal.resolve())}
        if pause != expected:
            raise ValueError('Budget pause differs from its retained journal or frozen cell')
        paths.append(pauses[0])
    return [{'path': str(path), 'sha256': digest(path)} for path in paths]


def run_timing_child(command, checkout, env, stream, lock):
    # The child keeps the same flock open if this operator dies. Its per-cell
    # journal lock alone cannot protect the host from other timing work.
    return subprocess.run(command, cwd=checkout, env=env, stdout=stream, stderr=stream,
                          pass_fds=(lock.fileno(),))


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
            if previous and previous.get('status') == 'PAUSED_MEASUREMENT_BUDGET':
                journal_evidence(cell, host, plan, budget_pause=True)
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
                      'resumedFrom': previous, 'outerLockPath': str(state / 'measurement.lock'),
                      'resumeEvidence': journal_evidence(cell, host, plan)}
            atomic_json(report_path, report)
            try:
                with report_path.with_suffix('.log').open('a') as stream:
                    result = run_timing_child(command, checkout, env, stream, lock)
            except KeyboardInterrupt:
                report.update(status='INTERRUPTED', operatorInterrupted=True, interruptedAt=now())
                atomic_json(report_path, report)
                return 130

            receipt_paths = list((Path(host['outputRoot']) / cell['cellId']).rglob('validation-campaign.json'))
            report.update(completedAt=now(), exitCode=result.returncode, status='FAILED', receipts=[])
            try:
                if result.returncode == 11:
                    if receipt_paths:
                        raise ValueError('Budget pause conflicts with a completed receipt')
                    report['resumeEvidence'] = journal_evidence(cell, host, plan, budget_pause=True)
                    report['status'] = 'PAUSED_MEASUREMENT_BUDGET'
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
                return 11 if report['status'] == 'PAUSED_MEASUREMENT_BUDGET' else 12
        atomic_json(evidence / 'phase-complete.json', {'executionHash': plan['executionHash'], 'host': args.host, 'cellCount': len(cells), 'completedAt': now()})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
