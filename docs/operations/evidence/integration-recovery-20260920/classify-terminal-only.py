#!/usr/bin/env python3
"""Individually classify every terminal-only payload identity.

Terminal-only = the payload appears in a client terminal receipt but its
payloadHash is not any recorded run. Recorded-OR-terminal is not the end of
the audit: for each such identity this tool binds the original sealed attempt
validity from the source host spool to the exact sent/stored measurement-group
state on the live candidate, and prints a per-identity classification with the
evidence a reviewer needs. No state is mutated.
"""
import json
import subprocess
from pathlib import Path

ROOT = Path('/mnt/NVME/docker/encodingdb-operations/20260920-native-b3ef24a')
STAGED = Path('/mnt/NVME/docker/encodingdb-operations/20260920-integration-recovery/staged')
DB = 'encodingdb-candidate-730de3c-db-1'


def shell(argv, check=True):
    completed = subprocess.run(argv, capture_output=True, text=True)
    if check and completed.returncode != 0:
        raise RuntimeError(f'{argv} -> {completed.returncode}: {completed.stderr[:400]}')
    return completed


def db(sql):
    return shell(['docker', 'exec', DB, 'psql', '-U', 'encodingdb_candidate', '-d', 'candidate',
                  '-tA', '-F', '\t', '-c', sql]).stdout


def read_json(path: Path):
    raw = path.read_bytes()
    for encoding in ('utf-8-sig', 'utf-8', 'cp936'):
        try:
            return json.loads(raw.decode(encoding))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return None


def terminal_sources():
    yield 'mac-terminal', ROOT / 'publication/mac-terminal', False
    yield 'windows-terminal', STAGED / 'windows-terminal', False
    for name, queue in {
        'software': ROOT / '日本語 client trial/software-queue',
        'nvenc': ROOT / '日本語 client trial/nvenc-queue',
        'gopfix-animation': ROOT / 'gopfix-verify/verify-animation-queue',
        'gopfix-athletic': ROOT / 'gopfix-verify/verify-athletic-action-queue',
        'recovery-linux': Path('/home/ofhd/encodingdb-recovery-20260920/replay-linux/queue'),
        'mac-payloads': ROOT / 'publication/mac-payloads/software/queue',
    }.items():
        yield f'{name}-terminal', queue, True


def attempt_index(queue_dirs):
    out = {}
    for base in queue_dirs:
        campaigns = base / 'campaigns'
        if not campaigns.is_dir():
            continue
        for campaign_dir in campaigns.glob('campaign-*'):
            for path in campaign_dir.glob('attempt-*.json'):
                entry = read_json(path)
                if not entry:
                    continue
                schedule = entry.get('schedule') or {}
                key = (campaign_dir.name, schedule.get('repetitionGroupId'), schedule.get('repetitionIndex'))
                validity = {k: entry.get(k) for k in ('overallValidity', 'structuralValidity',
                                                      'environmentValidity', 'countedForStability',
                                                      'skippedBeforeEncode')}
                out.setdefault(key, []).append({'file': str(path.relative_to(base)), **validity})
    return out


def main():
    recorded = {}
    rows = json.loads(db("""SELECT json_agg(q)::text FROM (SELECT r."campaignId" AS campaign, r."physicalSourceId" AS src, r."repetitionGroupId" AS grp,
                            r."repetitionIndex" AS idx, r."payloadHash" AS ph, r.id AS "runId", r.status,
                            a."storageState" AS state, a.sha256 AS sha, r."encodeWallTimeMs" AS wall,
                            (r."preRunEnvironmentCheck"->'measurementGroup'->>'completed') AS completed
                     FROM "BenchmarkRun" r JOIN "Artifact" a ON a."benchmarkRunId"=r.id) q""".replace('\n', '')))
    for row in rows:
        recorded.setdefault((row['campaign'], row['grp'], row['src']), []).append(row)

    group_receipts = {}
    receipts = json.loads(db("""SELECT json_agg(q)::text FROM (SELECT DISTINCT r."campaignId" AS campaign,
                            r."physicalSourceId" AS src, r."repetitionGroupId" AS grp,
                            r."preRunEnvironmentCheck"->'measurementGroup' AS receipt
                     FROM "BenchmarkRun" r WHERE r."preRunEnvironmentCheck" ? 'measurementGroup') q""".replace('\n', '')))
    for row in receipts:
        receipt = row['receipt']
        if isinstance(receipt, str):
            receipt = json.loads(receipt)
        if receipt.get('completed'):
            group_receipts[(row['campaign'], row['grp'], row['src'])] = receipt

    host_queue_dirs = [ROOT / '日本語 client trial/software-queue', ROOT / '日本語 client trial/nvenc-queue',
                       ROOT / 'gopfix-verify/verify-animation-queue', ROOT / 'gopfix-verify/verify-athletic-action-queue',
                       ROOT / 'publication/mac-payloads/software/queue',
                       Path('/home/ofhd/encodingdb-recovery-20260920/replay-linux/queue')]
    attempts = attempt_index(host_queue_dirs)

    classifications = []
    for name, directory, is_queue in terminal_sources():
        if not directory.is_dir():
            continue
        target = directory / 'terminal' if is_queue else directory
        if not target.is_dir():
            continue
        for path in sorted(p for p in target.glob('*.json') if not p.name.startswith('._')):
            entry = read_json(path)
            item = {'payloadHash': None, 'source': name, 'file': str(path)}
            if not entry:
                item['classification'] = 'UNDECODABLE-RECEIPT'
                classifications.append(item)
                continue
            payload = entry.get('payload') or {}
            run_create = payload.get('runCreate') or payload.get('run_create') or payload
            campaign, group, index = (run_create.get('campaignId'), run_create.get('repetitionGroupId'),
                                      run_create.get('repetitionIndex'))
            key = (campaign, group, run_create.get('physicalSourceId'))
            members = recorded.get(key, [])
            item.update({
                'payloadHash': run_create.get('payloadHash'),
                'campaignId': campaign, 'repetitionGroupId': group, 'repetitionIndex': index,
                'recipeId': run_create.get('recipeId'),
                'artifactSha256': run_create.get('artifactSha256') or payload.get('artifactSha256'),
                'byteSize': run_create.get('byteSize'),
                'lastError': entry.get('lastError'), 'attempts': entry.get('attempts'),
                'terminalUpdatedAt': entry.get('updatedAt') or entry.get('terminalAt'),
                'groupRecordedMembers': members,
                'recordedIndexMatchesTerminal': any(m['idx'] == index for m in members),
                'groupSealedCounted': sorted(a['repetitionIndex'] for a in group_receipts[key]['countedAttempts'])
                if key in group_receipts else None,
                'terminalCountedInOwnReceipt': None,
                'localAttemptValidity': attempts.get((campaign, group, index), 'not-on-p910-spool'),
            })
            classifications.append(item)

    recorded_hashes = {m['ph'] for members in recorded.values() for m in members}
    for item in classifications:
        ph = item.get('payloadHash')
        if not ph or ph in recorded_hashes:
            item['classification'] = 'recorded-again-later'
            continue
        if item.get('recordedIndexMatchesTerminal'):
            item['classification'] = 'superseded-duplicate-repetition'
        elif item.get('groupSealedCounted') is not None and item.get('repetitionIndex') in item['groupSealedCounted']:
            # The stored sealed receipt counts this exact repetition, but no recorded row
            # carries it: the group demands this member and the server receipt-asymmetry
            # gate (sealed sibling vs receipt-less submission) refuses it at run create.
            item['classification'] = 'valid-unrecorded-sealed-member'
        elif item.get('groupSealedCounted') is not None:
            # The group sealed with a fixed counted set that excludes this repetition:
            # it is an excess adaptive repeat the sealed evidence proves unnecessary.
            item['classification'] = 'excess-attempt-outside-seal'
        elif item.get('groupRecordedMembers'):
            item['classification'] = 'missing-repetition-on-partial-group'
        else:
            item['classification'] = 'missing-entire-group'
    terminal_only = [c for c in classifications if c['classification'] != 'recorded-again-later']
    summary = {}
    for item in terminal_only:
        summary[item['classification']] = summary.get(item['classification'], 0) + 1
    print(json.dumps({'terminalOnlyCount': len(terminal_only), 'byClassification': summary,
                      'validUnrecordedCandidates': sorted(i['payloadHash'] for i in terminal_only
                                                          if i['classification'].startswith('missing'))}, indent=1))
    print(json.dumps(classifications, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
