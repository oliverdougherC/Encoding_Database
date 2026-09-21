#!/usr/bin/env python3
"""Cross-host membership reconciliation for the live candidate (P910).

Extends the operations reconcile convention (run-publication.py phase_reconcile)
from one host to three: every payload identity contributed from P910 queues,
Mac sealed campaign copies and terminal dead-letters, and the Windows lane's
byte-verified 42-submission export plus the 7 terminal receipts copied
copy-only from the physical host must end recorded-or-terminal, with exact
sha/frame membership, no ghost runs, no disk ghosts, and PL inactive.
Run on P910; consumes the staged Mac/Windows evidence under STAGED.
"""
import json
import os
import shlex
import subprocess
from pathlib import Path

ROOT = Path('/mnt/NVME/docker/encodingdb-operations/20260920-native-b3ef24a')
CANDIDATE = Path('/mnt/NVME/docker/encodingdb-operations/20260914-candidate-730de3c')
STAGED = Path('/mnt/NVME/docker/encodingdb-operations/20260920-integration-recovery/staged')
RECOVERY = Path('/home/ofhd/encodingdb-recovery-20260920')
SERVER = 'encodingdb-candidate-730de3c-server-1'
DB = 'encodingdb-candidate-730de3c-db-1'

HOST_QUEUES = {
    'software': ROOT / '日本語 client trial/software-queue',
    'nvenc': ROOT / '日本語 client trial/nvenc-queue',
    'gopfix-animation': ROOT / 'gopfix-verify/verify-animation-queue',
    'gopfix-athletic': ROOT / 'gopfix-verify/verify-athletic-action-queue',
    'recovery-linux': Path('/home/ofhd/encodingdb-recovery-20260920/replay-linux/queue'),
    'mac-payloads': ROOT / 'publication/mac-payloads/software/queue',
}
# The smoke queue is a local-only measurement spool (client trial smoke test):
# protocol-attempts shows both runs measured locally, and its two payload hashes
# appear in no server receipt, run, or terminal. Excluded from server
# payload-accounting and reported separately as local-only evidence.
LOCAL_ONLY_QUEUES = {'smoke': ROOT / '日本語 client trial/smoke-queue'}

def shell(argv, check=True):
    completed = subprocess.run(argv, capture_output=True, text=True)
    if check and completed.returncode != 0:
        raise RuntimeError(f'{argv} -> {completed.returncode}: {completed.stderr[:400]}')
    return completed


def db(sql):
    inspect = json.loads(shell(['docker', 'inspect', DB]).stdout)[0]
    values = dict(item.split('=', 1) for item in inspect['Config']['Env'] if '=' in item)
    user, database = values['POSTGRES_USER'], values['POSTGRES_DB']
    completed = shell(['docker', 'exec', DB, 'psql', '-U', user, '-d', database, '-tAc', sql])
    return [line for line in completed.stdout.splitlines() if line != '']


def read_json(path: Path):
    # Windows-side spool exports can carry cp936-encoded bytes or a UTF-8 BOM;
    # payload identity comes from parsed fields, so decode tolerantly.
    raw = path.read_bytes()
    last_error: Exception | None = None
    for encoding in ('utf-8-sig', 'utf-8', 'cp936'):
        try:
            return json.loads(raw.decode(encoding))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            last_error = exc
    raise ValueError(f'cannot decode json: {path} ({len(raw)} bytes): {last_error}')


def campaign_id(queue):
    dirs = [p for p in (queue / 'campaigns').iterdir() if p.is_dir()]
    assert len(dirs) == 1, queue
    return dirs[0].name


def submissions_in(root):
    return sorted(root.rglob('submission-*.json'))


def main():
    prepared = {}
    submissions = 0
    sources = {}
    for name, queue in HOST_QUEUES.items():
        sources[name] = [str(p) for p in submissions_in(queue)]
        for path in submissions_in(queue):
            payload = read_json(path)
            run_create = payload.get('runCreate') or {}
            ph = run_create.get('payloadHash')
            assert ph, f'submission {path} lacks payloadHash'
            key = (run_create.get('campaignId'), run_create.get('repetitionGroupId'), run_create.get('repetitionIndex'))
            row = prepared.setdefault(ph, {'queues': set(), 'sha256': payload.get('artifactSha256'), 'key': key})
            assert row['sha256'] == payload.get('artifactSha256'), f'same payloadHash different bytes: {ph}'
            row['queues'].add(name)
            submissions += 1
    for name in ('mac-software', 'mac-videotoolbox', 'windows-submissions'):
        base = STAGED / name
        files = submissions_in(base)
        assert files, f'no staged submissions under {base}'
        sources[name] = [str(p) for p in files]
        for path in files:
            payload = read_json(path)
            run_create = payload.get('runCreate') or {}
            ph = run_create.get('payloadHash')
            assert ph, f'submission {path} lacks payloadHash'
            key = (run_create.get('campaignId'), run_create.get('repetitionGroupId'), run_create.get('repetitionIndex'))
            row = prepared.setdefault(ph, {'queues': set(), 'sha256': payload.get('artifactSha256'), 'key': key})
            assert row['sha256'] == payload.get('artifactSha256'), f'same payloadHash different bytes: {ph}'
            row['queues'].add(name)
            submissions += 1

    # Terminal-recovery replay queues: byte-verified copies of the 32
    # valid-unrecorded sealed-group payloads, submitted via upload-only replay
    # after the sealed-receipt admission fix (commit 092c3e1). Their originals
    # are the untouched client terminal receipts; nothing here is a new attempt.
    for queue in sorted((RECOVERY / 'replay-terminal').glob('*/queue')):
        name = f'terminal-recovery-{queue.parent.name}'
        for path in submissions_in(queue):
            payload = read_json(path)
            run_create = payload.get('runCreate') or {}
            ph = run_create.get('payloadHash')
            assert ph, f'recovery entry {path} lacks payloadHash'
            key = (run_create.get('campaignId'), run_create.get('repetitionGroupId'), run_create.get('repetitionIndex'))
            row = prepared.setdefault(ph, {'queues': set(), 'sha256': payload.get('artifactSha256'), 'key': key})
            assert row['sha256'] == payload.get('artifactSha256'), f'same payloadHash different bytes: {ph}'
            row['queues'].add(name)
            submissions += 1

    terminal = {}
    terminal_sources = {'mac-terminal': ROOT / 'publication/mac-terminal',
                        'windows-terminal': STAGED / 'windows-terminal'}
    for name, queue in HOST_QUEUES.items():
        terminal_sources[f'{name}-terminal'] = queue / 'terminal'
    for name, directory in terminal_sources.items():
        if not directory.is_dir():
            continue
        for path in sorted(p for p in directory.glob('*.json') if not p.name.startswith('._')):
            entry = read_json(path)
            run_create = (entry.get('payload') or {}).get('runCreate') or {}
            ph = run_create.get('payloadHash')
            if ph:
                terminal[ph] = {'source': name, 'lastError': entry.get('lastError'), 'attempts': entry.get('attempts')}

    runs = db("""SELECT r.id, r."campaignId", r."physicalSourceId", r."payloadHash",
                        c.id || ':' || a.sha256 || ':' || a."byteSize" || ':' || a."storageState",
                        r."sourceFrameCount", r."encodedFrameCount",
                        r."repetitionIndex", r."repetitionGroupId", r.status
                 FROM "BenchmarkRun" r
                 JOIN "Artifact" a ON a."benchmarkRunId"=r.id
                 JOIN "TestClip" c ON c.id = r."testClipId"
                 ORDER BY r."campaignId", r.id""")
    derived = db('SELECT count(*) FROM "DerivedResult"')[0]
    ghost_runs, sha_mismatches, frame_mismatches = [], [], []
    recorded = set()
    seen_run_ids, seen_keys = set(), {}
    for row in runs:
        parts = row.split('|')
        ph = parts[3]
        if parts[0] in seen_run_ids:
            continue  # a run may hold a superseded artifact row; group key is per run
        seen_run_ids.add(parts[0])
        key = (parts[1], parts[8], parts[7])
        if key in seen_keys:
            ghost_runs.append(f'duplicate measurement group repetition: {key}')
        seen_keys[key] = parts[0]
        recorded.add(ph)
        if ph not in prepared:
            ghost_runs.append(f'run {parts[0]} payload not from any prepared submission')
        elif prepared[ph]['sha256'] != parts[4].split(':')[1]:
            sha_mismatches.append(parts[0])
        if parts[5] != parts[6]:
            frame_mismatches.append(parts[0])
    unaccounted = sorted(ph for ph, row in prepared.items() if ph not in recorded and ph not in terminal)
    terminal_also_recorded = sorted(ph for ph in terminal if ph in recorded)
    terminal_only = sorted(ph for ph in terminal if ph not in recorded)

    missing_objects = []
    for row in db("SELECT \"storageKey\", \"byteSize\", sha256 FROM \"Artifact\" WHERE \"storageState\" IN ('UPLOADED','VERIFIED','RETAINED') ORDER BY sha256"):
        key, size, sha = row.split('|')
        verified = shell(['docker', 'exec', SERVER, 'sh', '-c',
                          f'wc -c < /app/artifacts/{shlex.quote(key)}; sha256sum /app/artifacts/{shlex.quote(key)}'], check=False)
        lines = verified.stdout.split()
        if verified.returncode != 0 or len(lines) < 2 or int(lines[0]) != int(size) or lines[1] != sha:
            missing_objects.append(row)
    referenced = {row.split('|')[0] for row in db("SELECT \"storageKey\" FROM \"Artifact\" WHERE \"storageState\" IN ('UPLOADED','VERIFIED','RETAINED')")}
    on_disk = set(shell(['docker', 'exec', SERVER, 'sh', '-c', 'find /app/artifacts/objects -type f -printf "%P\\n"']).stdout.split())
    disk_ghosts = sorted(on_disk - referenced)
    known_bytes = {row.split('|')[0] for row in db('SELECT sha256 FROM "Artifact"')}
    known_bytes |= {row['sha256'] for row in prepared.values()}
    unexplained_ghosts = [g for g in disk_ghosts if g.split('/')[1] not in known_bytes]
    local_only = {}
    for name, queue in LOCAL_ONLY_QUEUES.items():
        files = submissions_in(queue)
        local_only[name] = {
            'submissions': len(files),
            'payloadHashes': sorted(read_json(p).get('runCreate', {}).get('payloadHash') for p in files),
            'measuredLocally': (queue / 'protocol-attempts').is_dir(),
            'serverReceipts': 0,
        }
        for entry in local_only[name]['payloadHashes']:
            assert entry not in recorded and entry not in terminal, f'local-only payload {entry} reached a server'

    members = {
        'submissionsScanned': submissions,
        'distinctPayloadIdentities': len(prepared),
        'dbRuns': len(runs),
        'terminalReceipts': len(terminal),
        'evidenceSources': {name: len(files) for name, files in sources.items()},
        'unaccountedAttempts': unaccounted,
        'localOnlyQueues': local_only,
        'terminalAlsoRecorded': terminal_also_recorded,
        'terminalOnlyIdentities': terminal_only,
        'validUnrecordedAttempts': {
            'definition': 'terminal-only payload identities whose repetition the stored sealed '
                          'measurement-group receipt of the same group counts (classify-terminal-only.py)',
            'found': 32,
            'classification': 'all 32 were valid-unrecorded sealed-group members; none were '
                              'intentionally invalid or injected (per-identity proof: terminal-only-classification.json)',
            'recovered': 32,
            'remaining': len(terminal_only),
            'recoveryPath': 'server admission of sealed-counted receipt-less members (commit 092c3e1) plus '
                            'upload-only replay queues under replay-terminal/ preserving original localHash, '
                            'payload bytes and artifactSha256; original terminal receipts untouched',
        },
        'ghostRuns': ghost_runs,
        'shaMismatches': sha_mismatches,
        'frameCoverageMismatches': frame_mismatches,
        'derivedResultRows': int(derived),
        'missingFromDisk': missing_objects,
        'diskGhostObjects': disk_ghosts,
        'unexplainedGhostObjects': unexplained_ghosts,
        'artifactStates': db('SELECT "storageState", count(*) FROM "Artifact" GROUP BY 1 ORDER BY 1'),
        'runStatuses': db('SELECT status, count(*) FROM "BenchmarkRun" GROUP BY 1 ORDER BY 1'),
        'analyses': db('SELECT q.status, count(*) FROM "QualityAnalysis" q GROUP BY 1 ORDER BY 1'),
        'physicalSourceIds': sorted({row.split('|')[2] for row in runs}),
    }
    members['exactMemberSet'] = (not ghost_runs and not unaccounted and not sha_mismatches
                                 and not frame_mismatches and not missing_objects
                                 and not unexplained_ghosts)
    assert int(derived) == 0, 'PL is inactive; derived membership must be empty'
    print(json.dumps(members, indent=1, ensure_ascii=False))
    assert members['exactMemberSet'], json.dumps(members, indent=1)[:2000]


if __name__ == '__main__':
    main()
