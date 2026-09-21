"""Exact recorded-or-terminal reconciliation of the Mac b3 queues against the candidate DB.

Runs on the Mac; queries P910's candidate DB through ssh+psql. Every prepared
submission payload must either have a DB run (matching sha, frame coverage, unique
measurement-group repetition) or a terminal receipt. No re-encoding, no writes.
"""
import glob
import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path('/Users/ofhd/Developer/Encoding_Database')
WORKTREE = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent
BASE = ROOT / '.build/native-seven-mac-b3ef24a/épreuve 客户端'
LEDGERS = WORKTREE / 'docs/collection-readiness/mac-seven-b3ef24a/replay-ledgers'
CASES = {'software': 'campaign-cda14a5876e816b6', 'videotoolbox': 'campaign-5cdcb087bc1fc57a'}
RESULTS = EVIDENCE / 'mac-reconcile.json'

def sql(statement):
    argv = ['docker', 'exec', 'encodingdb-candidate-730de3c-db-1',
            'psql', '-U', 'encodingdb_candidate', '-d', 'candidate', '-tAc', statement]
    remote = ' '.join(shlex.quote(a) for a in argv)
    done = subprocess.run(['ssh', 'ofhd@100.99.6.59', remote], capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(done.stderr[:400])
    return [l for l in done.stdout.splitlines() if l]

def main():
    report = {'cases': {}}
    for case, campaign in CASES.items():
        queue = BASE / case / 'queue'
        sealed = json.loads((LEDGERS / f'{case}-before-upload.json').read_text())
        current = hashlib.sha256(json.dumps(sealed, sort_keys=True).encode()).hexdigest()
        prepared = {}
        for path in sorted(glob.glob(str(queue / 'campaigns' / campaign / 'submission-*.json'))):
            payload = json.loads(Path(path).read_text())
            run_create = payload.get('runCreate') or {}
            ph = run_create.get('payloadHash')
            assert ph and ph not in prepared, path
            prepared[ph] = {'sha256': payload.get('artifactSha256'),
                            'key': (run_create.get('campaignId'), run_create.get('repetitionGroupId'),
                                    run_create.get('repetitionIndex'))}
        terminal = {}
        for path in sorted(glob.glob(str(queue / 'terminal' / '*.json'))):
            entry = json.loads(Path(path).read_text())
            run_create = (entry.get('payload') or {}).get('runCreate') or {}
            if run_create.get('payloadHash'):
                terminal[run_create['payloadHash']] = entry.get('lastError')
        rows = sql(f"SELECT r.id || chr(9) || r.\"payloadHash\" || chr(9) || a.sha256 || chr(9) "
                   f"|| a.\"storageState\" || chr(9) || coalesce(r.\"sourceFrameCount\",-1)::text || chr(9) "
                   f"|| coalesce(r.\"encodedFrameCount\",-1)::text || chr(9) || coalesce(r.\"repetitionIndex\",-1)::text "
                   f"FROM \"BenchmarkRun\" r JOIN \"Artifact\" a ON a.\"benchmarkRunId\"=r.id "
                   f"WHERE r.\"campaignId\"='{campaign}'")
        runs = {}
        problems = []
        for line in rows:
            rid, ph, sha, state, sf, ef, idx = line.split(chr(9))
            if ph not in prepared:
                problems.append(f'ghost run {rid} payload {ph[:12]}')
                continue
            expect = prepared[ph]
            if expect['sha256'] != sha:
                problems.append(f'run {rid} sha mismatch')
            if sf != ef:
                problems.append(f'run {rid} frame coverage {sf}/{ef}')
            if expect['key'][2] != int(idx):
                problems.append(f'run {rid} repetition mismatch')
            runs[ph] = state
        unaccounted = sorted(ph for ph in prepared if ph not in runs and ph not in terminal)
        analyses = sql(f"SELECT q.status || chr(9) || count(DISTINCT q.id) FROM \"QualityAnalysis\" q "
                       f"JOIN \"BenchmarkRun\" r ON r.id=q.\"benchmarkRunId\" "
                       f"WHERE r.\"campaignId\"='{campaign}' GROUP BY q.status")
        report['cases'][case] = {
            'campaign': campaign,
            'preparedSubmissions': len(prepared),
            'dbRuns': len(runs),
            'terminalReceipts': len(terminal),
            'unaccountedAttempts': unaccounted,
            'problems': problems,
            'artifactStates': {ph[:12]: state for ph, state in runs.items()},
            'analyses': [l.replace(chr(9), '=') for l in analyses],
            'sealedLedgerSha256': current,
            'ledgerFiles': len(sealed['files']),
        }
        assert not unaccounted and not problems, report['cases'][case]
    RESULTS.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=1))


if __name__ == '__main__':
    sys.exit(main())
