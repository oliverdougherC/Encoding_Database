#!/usr/bin/env python3
"""Finite, local-only matrix execution; journals remain the evidence authority."""
import argparse
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / 'server/config/calibration/final1080p-corrected-timing.matrix-v1.json'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    with temp.open('w') as f:
        json.dump(value, f, indent=2, sort_keys=True)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read(path):
    return json.loads(path.read_text())


def plan(matrix, slots, sessions, seed, root):
    if not slots or set(slots) - matrix['sourceSlots'].keys():
        raise ValueError('Select registered physical source slots')
    hosts = {matrix['sourceSlots'][s]['candidateHost'] for s in slots}
    if len(hosts) != 1:
        raise ValueError('One execution root must represent one actual host')
    if not sessions or set(sessions) - {1, 2}:
        raise ValueError('Sessions must be 1, 2 or 1,2')
    items = []
    seen = set()
    for cell in matrix['cells']:
        if cell['cellId'] in seen:
            raise ValueError('Duplicate matrix cell')
        seen.add(cell['cellId'])
        if (cell['warmupsPerSession'], cell['measuredRunsPerSession'],
            cell['maximumAdaptiveAdditionalRunsPerSession'], cell['sessionsPerSource']) != (1, 2, 2, 2):
            raise ValueError('Matrix repetition bounds differ from implemented client protocol')
        for slot in sorted(set(slots).intersection(cell['physicalSourceSlots'])):
            for session in sorted(set(sessions)):
                key = f"{slot}/session-{session}/{cell['cellId']}"
                if not re.fullmatch(r'[A-Za-z0-9_/-]+', key) or '..' in key:
                    raise ValueError('Unsafe matrix identifier')
                cell_seed = int.from_bytes(hashlib.sha256(
                    f"{matrix['matrixVersion']}:{seed}:{key}".encode()).digest()[:8], 'big') & ((1 << 63) - 1)
                items.append(dict(key=key, seed=cell_seed, sourceSlot=slot, session=session,
                                  cell=cell, queueDir=str(root / 'queues' / key)))
    return sorted(items, key=lambda x: (x['session'], x['seed'], x['key']))


def command(cli, item, storage_mb, minutes, campaign=None, upload=False, base_url=None):
    args = [str(cli), '--cli', '--queue-dir', item['queueDir']]
    if upload:
        args += ['--upload-only', '--resume-campaign', campaign, '--base-url', base_url, '--retries', '0']
    else:
        args += ['--no-submit', '--max-attempts', '5', '--max-storage-mb', str(storage_mb),
                 '--max-duration-minutes', str(minutes)]
        if campaign:
            args += ['--resume-campaign', campaign]
        else:
            cell = item['cell']
            args += ['--campaign', 'quick', '--v7-suite-clip', cell['workloadId'],
                     '--codec', cell['encoderImplementation'], '--presets', cell['preset']]
            rc = cell['nativeRateControl']
            if rc['mode'] == 'crf' and set(rc) == {'mode', 'qualityValue'}:
                args += ['--crf', str(rc['qualityValue'])]
            elif rc['mode'] == 'vbr' and set(rc) == {'mode', 'targetBitrateKbps'}:
                args += ['--target-bitrate-kbps', str(rc['targetBitrateKbps'])]
            else:
                raise ValueError('Unsupported native rate control; no substitution allowed')
    return args


def campaign_path(item):
    paths = list((Path(item['queueDir']) / 'campaigns').glob('campaign-*'))
    if len(paths) > 1:
        raise ValueError('Multiple campaigns in a cell-owned queue; refusing ambiguous resume')
    if paths and not (paths[0] / 'manifest.json').is_file():
        raise ValueError('Campaign lacks durable manifest; inspect before resuming')
    return paths[0] if paths else None


def evidence(item):
    root = campaign_path(item)
    if root is None:
        return {}
    manifest = read(root / 'manifest.json')
    if manifest['seed'] != item['seed']:
        raise ValueError('Retained campaign seed differs from immutable matrix plan')
    cell = item['cell']
    expected_task = dict(encoder=cell['encoderImplementation'], preset=cell['preset'],
                         clipId=cell['workloadId'])
    tasks = manifest.get('tasks', [])
    if len(tasks) != 1 or any(tasks[0].get(k) != v for k, v in expected_task.items()):
        raise ValueError('Retained recipe differs from declared matrix cell')
    rc = cell['nativeRateControl']
    if (rc['mode'] == 'crf' and tasks[0].get('crf') != rc['qualityValue']) or (
            rc['mode'] == 'vbr' and tasks[0].get('rateControl') != rc):
        raise ValueError('Retained native rate control differs from matrix')
    result = {'campaignId': root.name, 'manifest': manifest, 'records': []}
    for p in sorted(root.glob('attempt-*.json')):
        row = read(p)
        meta = row.get('metadata') or {}
        info = meta.get('info') or {}
        result['records'].append({'path': str(p), 'sha256': digest(p),
                                  'inputHash': meta.get('inputHash'),
                                  'artifactSha256': info.get('artifactSha256'),
                                  'schedule': row.get('schedule')})
    result['receipts'] = [{'path': str(p), 'sha256': digest(p), 'receipt': read(p)}
                          for p in sorted((Path(item['queueDir']) / 'receipts').glob('*.json'))]
    marker = root / 'campaign-complete.json'
    result['completion'] = read(marker) if marker.exists() else None
    return result


def completed(ev):
    marker = ev.get('completion')
    return marker is not None and not marker.get('failed') and not marker.get('skipped')


def queue_due(item, now):
    entries = [read(p) for p in Path(item['queueDir']).glob('*.json')]
    if not entries:
        return now
    return min(min(e.get('nextAttemptAt', 0), e.get('retryDeadlineAt', now)) for e in entries)


@contextlib.contextmanager
def exclusive(root):
    # macOS/Linux runner. Inherited lock keeps a surviving CLI fenced after parent SIGKILL.
    import fcntl
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'runner.lock').open('a+b') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another runner or its surviving CLI still owns this root') from None
        yield f


def run_child(cmd, env, log, seconds, lock):
    with log.open('ab') as out:
        p = subprocess.Popen(cmd, env=env, stdout=out, stderr=subprocess.STDOUT,
                             start_new_session=True, pass_fds=(lock.fileno(),))
        try:
            return p.wait(timeout=seconds)
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            os.killpg(p.pid, signal.SIGINT)
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
            return 130 if isinstance(exc, KeyboardInterrupt) else 124


def execute(args, items):
    root = args.output.resolve()
    with exclusive(root) as lock:
        identity = dict(matrixSha256=digest(args.matrix), clientSha256=digest(args.cli),
                        clientSourceSha=args.client_source_sha, runnerSha256=digest(__file__),
                        slots=sorted(set(args.source_slot)), sessions=sorted(set(args.sessions)), seed=args.seed)
        path = root / 'ledger.json'
        ledger = read(path) if path.exists() else dict(identity=identity, phase='timing', cells={}, invocations=[])
        if ledger['identity'] != identity:
            raise ValueError('Matrix/client/source/runner/selection changed; use a new root')
        if args.phase == 'timing' and ledger['phase'] != 'timing':
            raise ValueError('Upload phase already began; no more timing in this root')
        if args.phase == 'upload':
            if not args.all_host_timing_complete or not args.base_url:
                raise ValueError('Upload requires --all-host-timing-complete and an explicit --base-url')
            if not all(completed(evidence(item)) for item in items):
                raise ValueError('All selected cells/sessions must finish timing before any upload')
            ledger['phase'] = 'upload'
        help_result = subprocess.run([str(args.cli), '--help'], capture_output=True, timeout=60)
        (root / 'client-help.txt').write_bytes(help_result.stdout + help_result.stderr)
        required = (b'--max-duration-minutes', b'--upload-only', b'--resume-campaign', b'--v7-suite-clip')
        if help_result.returncode or any(flag not in help_result.stdout for flag in required):
            raise ValueError('Packaged client lacks required finite/resumable interface; see client-help.txt')
        invocation = dict(startedAt=time.time(), phase=args.phase, maxCells=args.max_cells,
                          maxMinutes=args.max_duration_minutes, maxStorageMiB=args.max_storage_mb,
                          perCellStorageMiB=args.cell_storage_mb, perCellMinutes=args.cell_minutes,
                          helpExitCode=help_result.returncode, helpSha256=digest(root / 'client-help.txt'))
        ledger['invocations'].append(invocation)
        atomic(path, ledger)
        started = time.monotonic()
        count = 0
        result = 0
        for item in items:
            ev = evidence(item)
            row = ledger['cells'].setdefault(item['key'], dict(seed=item['seed'], calls=[]))
            if ev:
                observed = {k: ev['manifest'].get(k) for k in ('physicalSourceId', 'runtime')}
                if not observed['physicalSourceId'] or not observed['runtime']:
                    raise ValueError('Campaign lacks physical-source/runtime provenance')
                if ledger.setdefault('observedHost', observed) != observed:
                    raise ValueError('Physical source or runtime changed within host execution root')
            row['evidence'] = ev
            row['timingComplete'] = completed(ev)
            if args.phase == 'timing' and completed(ev):
                continue
            if args.phase == 'upload' and row.get('uploadComplete'):
                continue
            if args.phase == 'upload' and row.get('nextUploadAt', 0) > time.time():
                result = 10
                continue
            if count >= args.max_cells:
                break
            remaining = args.max_duration_minutes * 60 - (time.monotonic() - started)
            if remaining <= 1:
                result = 10
                break
            used = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
            free_mb = (args.max_storage_mb * 1024 * 1024 - used) // (1024 * 1024)
            queue = Path(item['queueDir'])
            queue_used_mb = math.ceil(sum(p.stat().st_size for p in queue.rglob('*') if p.is_file()) / (1024 * 1024))
            cap = min(args.cell_storage_mb, queue_used_mb + free_mb - 1)
            if cap <= queue_used_mb:
                result = 6
                break
            minutes = min(args.cell_minutes, remaining / 60)
            cmd = command(args.cli, item, cap, minutes, ev.get('campaignId'),
                          args.phase == 'upload', args.base_url)
            log = root / 'logs' / (item['key'].replace('/', '__') + f"-{len(row['calls'])}.log")
            log.parent.mkdir(parents=True, exist_ok=True)
            call = dict(command=cmd, seed=item['seed'], startedAt=time.time(), exitCode=None, log=str(log))
            row['calls'].append(call)
            atomic(path, ledger)  # durable before the child can create an artifact
            env = dict(os.environ, ENCODINGDB_PROTOCOL_SEED=str(item['seed']))
            code = run_child(cmd, env, log, minutes * 60 + 30, lock)
            call.update(exitCode=code, finishedAt=time.time(), logSha256=digest(log))
            atomic(path, ledger)
            ev = evidence(item)
            if ev:
                observed = {k: ev['manifest'].get(k) for k in ('physicalSourceId', 'runtime')}
                if not observed['physicalSourceId'] or not observed['runtime']:
                    raise ValueError('Campaign lacks physical-source/runtime provenance')
                if ledger.setdefault('observedHost', observed) != observed:
                    raise ValueError('Physical source or runtime changed within host execution root')
            row['evidence'] = ev
            row['timingComplete'] = completed(ev)
            if args.phase == 'upload':
                row['uploadComplete'] = code == 0
                row['nextUploadAt'] = max(time.time() + 60, queue_due(item, time.time())) if code == 10 else 0
            atomic(path, ledger)
            count += 1
            if code or (args.phase == 'timing' and not completed(ev)):
                result = code or 1
                break  # fail/defer once; do not busy-replay or silently skip a bad recipe
        invocation.update(finishedAt=time.time(), executedCells=count, exitCode=result)
        atomic(path, ledger)
        print(json.dumps(dict(ledger=str(path), executedCells=count, exitCode=result,
                              timingComplete=sum(v.get('timingComplete', False) for v in ledger['cells'].values()),
                              selectedCellSessions=len(items))))
        return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--matrix', type=Path, default=DEFAULT_MATRIX)
    p.add_argument('--cli', type=Path, required=True, help='Exact native packaged executable')
    p.add_argument('--client-source-sha', default='', help='Exact source commit of packaged executable; required for execution')
    p.add_argument('--source-slot', action='append', required=True)
    p.add_argument('--sessions', type=lambda s: [int(x) for x in s.split(',')], default=[1, 2])
    p.add_argument('--seed', type=int, default=20260914)
    p.add_argument('--output', type=Path, required=True, help='Dedicated persistent host campaign root')
    p.add_argument('--execute', action='store_true', help='Actually run; otherwise print every planned cell')
    p.add_argument('--phase', choices=['timing', 'upload'], default='timing')
    p.add_argument('--all-host-timing-complete', action='store_true')
    p.add_argument('--base-url', help='Explicit publication target, used only in upload phase')
    p.add_argument('--max-cells', type=int, default=1, help='Cell/session invocations in this call (default 1)')
    p.add_argument('--max-duration-minutes', type=float, default=30)
    p.add_argument('--cell-minutes', type=float, default=10)
    p.add_argument('--max-storage-mb', type=int, default=16384)
    p.add_argument('--cell-storage-mb', type=int, default=1024)
    args = p.parse_args(argv)
    try:
        for name in ['max_cells', 'max_duration_minutes', 'cell_minutes', 'max_storage_mb', 'cell_storage_mb']:
            if not math.isfinite(getattr(args, name)) or getattr(args, name) <= 0:
                raise ValueError(f'{name} must be finite and positive')
        args.cli = args.cli.resolve()
        items = plan(read(args.matrix), args.source_slot, args.sessions, args.seed, args.output.resolve())
        if not items:
            raise ValueError('No matrix cells selected')
        if not args.execute:
            print(json.dumps(dict(status='PLAN_ONLY_UNEXECUTED', matrixSha256=digest(args.matrix),
                matrixCells=len(read(args.matrix)['cells']), selectedCellSessions=len(items),
                maximumEncodes=len(items) * 5, invocationMaxCells=args.max_cells,
                invocationMaxMinutes=args.max_duration_minutes, storageLimitMiB=args.max_storage_mb,
                cells=[dict(**i, command=command(args.cli, i, args.cell_storage_mb, args.cell_minutes,
                    (campaign_path(i).name if campaign_path(i) else 'RETAINED_CAMPAIGN_ID')
                    if args.phase == 'upload' else None, args.phase == 'upload',
                    args.base_url or 'EXPLICIT_UPLOAD_BASE_URL')) for i in items]), indent=2))
            return 0
        if not re.fullmatch('[0-9a-f]{40}', args.client_source_sha):
            raise ValueError('Execution requires exact --client-source-sha (40 hex characters)')
        return execute(args, items)
    except (ValueError, OSError, KeyError, subprocess.TimeoutExpired) as exc:
        print(f'Matrix runner stopped: {exc}', file=sys.stderr)
        return 6


if __name__ == '__main__':
    sys.exit(main())
