#!/usr/bin/env python3
"""Build acceptance-replay queues from the original sealed terminal receipts.

The isolated package-acceptance stack (fresh database, fresh secrets, fresh
volumes) re-records byte-identical sealed payloads so each rebuilt package's
--upload-only contract can be proven: recorded success and zero encoding.
Bytes are hard-linked from the already-verified recovery staging (macOS and
Windows runs stage their own copies on their hosts). Nothing encodes, nothing
existing is modified.
"""
import json
import os
import sys
import time
from pathlib import Path

CLASSIFY = Path(sys.argv[1])
OUT_ROOT = Path(sys.argv[2])
# source -> (receipt glob root, staged bytes resolver)
HOST_STAGED = Path('/home/ofhd/encodingdb-recovery-20260920/replay-terminal')


def main():
    raw = CLASSIFY.read_text()
    dec = json.JSONDecoder()
    _summary, idx = dec.raw_decode(raw)
    items = json.loads(raw[idx:])
    targets = [i for i in items if i['classification'] == 'valid-unrecorded-sealed-member'
               and i['source'] not in ('mac-terminal', 'windows-terminal')]
    built = []
    for item in targets:
        entry = json.loads(Path(item['file']).read_text(encoding='utf-8-sig'))
        payload = dict(entry['payload'])
        group = f"{item['source'].replace('-terminal', '')}-{str(item['campaignId'])[-8:]}"
        queue = OUT_ROOT / group / 'queue'
        (queue / 'artifacts').mkdir(parents=True, exist_ok=True)
        sha = payload['artifactSha256']
        staged = queue / 'artifacts' / f'{sha}.mp4'
        if not staged.is_file():
            # The successful recovery replay cleaned its managed queue copies
            # (unreferenced-after-upload). Re-adopt the sealed campaign original from
            # the source queue, adopted only when its bytes hash to the payload's
            # artifactSha256 exactly.
            import hashlib
            def _sha(path):
                h = hashlib.sha256()
                with path.open('rb') as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b''):
                        h.update(chunk)
                return h.hexdigest()
            source = Path(HOST_STAGED / group / 'queue' / 'artifacts' / f'{sha}.mp4')
            if not source.is_file():
                original_queue = Path(str(payload.get('artifactPath') or '')).parent.parent
                campaigns = original_queue / 'campaigns'
                source = next((c for c in (campaigns.rglob('*.mp4') if campaigns.is_dir() else []) if _sha(c) == sha), None)
            assert source is not None, f'no bytes for {sha} in {group}'
            import shutil
            shutil.copyfile(source, staged)
            assert _sha(staged) == sha, f'staged copy failed verification for {sha}'
        payload['artifactPath'] = str(staged)
        envelope = {'version': int(entry.get('version') or 1), 'localHash': entry['localHash'],
                    'payload': payload, 'queuedAt': int(time.time()), 'attempts': 0,
                    'lastAttemptAt': None, 'lastError': '',
                    'retryDeadlineAt': int(time.time()) + 7 * 86_400, 'nextAttemptAt': 0}
        (queue / f"{entry['localHash']}.json").write_text(json.dumps(envelope, ensure_ascii=False), encoding='utf-8')
        built.append({'payloadHash': item['payloadHash'], 'queue': str(queue)})
    print(json.dumps({'built': len(built), 'groups': sorted({b['queue'] for b in built})}, indent=1))


if __name__ == '__main__':
    main()
