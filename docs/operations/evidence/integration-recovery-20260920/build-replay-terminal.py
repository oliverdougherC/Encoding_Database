#!/usr/bin/env python3
"""Build replay queues for the 32 valid-unrecorded sealed-group members.

Every input identity comes from classify-terminal-only.py's
valid-unrecorded-sealed-member set. For each one this tool copies (never
moves) the terminal receipt payload into a fresh queue directory, restages
the artifact bytes under the queue, verifies the copy against the sealed
artifactSha256, and writes a pending spool envelope with the ORIGINAL
localHash and byte-identical payload (only artifactPath is repointed at the
staged copy). Original terminal receipts, tombstones and bytes are untouched.
Missing or non-matching bytes abort that identity with an explicit report.
"""
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

CLASSIFY = Path(sys.argv[1] if len(sys.argv) > 1 else '/home/ofhd/classify-raw.json')
OUT_ROOT = Path(sys.argv[2] if len(sys.argv) > 2 else '/home/ofhd/encodingdb-recovery-20260920/replay-terminal')
WINDOWS_SSH = 'ofhd@100.80.56.105'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    raw = CLASSIFY.read_text()
    dec = json.JSONDecoder()
    _summary, idx = dec.raw_decode(raw)
    items = json.loads(raw[idx:])
    targets = [i for i in items if i['classification'] == 'valid-unrecorded-sealed-member']
    report = {'built': [], 'blocked': [], 'needMacStaging': [], 'needWindowsStaging': []}
    for item in targets:
        receipt_path = Path(item['file'])
        entry = json.loads(receipt_path.read_text(encoding='utf-8-sig'))
        payload = entry['payload']
        source = item['source']
        campaign = str(item['campaignId'])
        group_dir = OUT_ROOT / f"{source.replace('-terminal', '')}-{campaign[-8:]}"
        queue = group_dir / 'queue'
        for sub in ('receipts', 'artifacts', 'terminal', 'campaigns', 'dead-letter'):
            (queue / sub).mkdir(parents=True, exist_ok=True)
        expected_sha = payload['artifactSha256']
        staged = queue / 'artifacts' / f'{expected_sha}.mp4'
        if not staged.is_file():
            source_path = payload.get('artifactPath') or ''
            if source == 'mac-terminal':
                report['needMacStaging'].append({'sha': expected_sha, 'queue': str(queue), 'macPath': source_path})
                continue
            if source == 'windows-terminal':
                report['needWindowsStaging'].append({'sha': expected_sha, 'queue': str(queue), 'windowsPath': source_path})
                continue
            host_path = Path(source_path)
            if not host_path.is_file():
                # Managed copies of terminal media may have been cleaned; the sealed
                # campaign original survives (cleanup must not erase the verdict). The
                # payload's artifactSha256 is the identity proof: adopt the original only
                # when its bytes hash to exactly that value.
                queue_root = Path(source_path).parent.parent if 'artifacts' in source_path else queue
                campaigns = queue_root / 'campaigns'
                host_path = next((c for c in (campaigns.rglob('*.mp4') if campaigns.is_dir() else [])
                                  if sha256(c) == expected_sha), None)
                if host_path is None:
                    report['blocked'].append({'payloadHash': item['payloadHash'], 'source': source,
                                              'reason': f'bytes missing at {source_path} and no campaign original hashes to {expected_sha}'})
                    continue
            shutil.copyfile(host_path, staged)
        if sha256(staged) != expected_sha:
            staged.unlink()
            report['blocked'].append({'payloadHash': item['payloadHash'], 'source': source,
                                      'reason': 'staged bytes failed sha256 verification'})
            continue
        replay_payload = dict(payload)
        replay_payload['artifactPath'] = str(staged)
        envelope = {
            'version': int(entry.get('version') or 1),
            'localHash': entry['localHash'],
            'payload': replay_payload,
            'queuedAt': int(time.time()),
            'attempts': 0,
            'lastAttemptAt': None,
            'lastError': '',
            'retryDeadlineAt': max(int(entry.get('retryDeadlineAt') or 0), int(time.time()) + 7 * 86_400),
            'nextAttemptAt': 0,
        }
        out = queue / f"{entry['localHash']}.json"
        out.write_text(json.dumps(envelope, ensure_ascii=False), encoding='utf-8')
        report['built'].append({'payloadHash': item['payloadHash'], 'source': source,
                                'campaign': campaign, 'queue': str(queue), 'entry': str(out)})
    print(json.dumps(report, indent=1))
    pending_fetch = [r for r in report['needMacStaging'] + report['needWindowsStaging']]
    (OUT_ROOT / f'fetch-needed-{Path(sys.argv[3]).name if len(sys.argv) > 3 else "fetch.json"}').parent.mkdir(parents=True, exist_ok=True)
    (OUT_ROOT / 'fetch-needed.json').write_text(json.dumps(report, indent=1))
    sys.exit(0 if not report['blocked'] else 3)


if __name__ == '__main__':
    main()
