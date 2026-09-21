#!/usr/bin/env python3
"""Hash completed measured evidence around upload-only replay; no API credentials."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def capture(queue):
    queue = queue.resolve(strict=True)
    files = {}
    campaigns = []
    def retain(path, campaign):
        if campaign not in path.resolve(strict=True).parents:
            raise ValueError('Evidence file is outside its owned campaign')
        files[str(path.relative_to(queue))] = digest(path)

    for campaign in sorted((queue / 'campaigns').glob('campaign-*')):
        if campaign.resolve().parent != queue / 'campaigns':
            raise ValueError('Campaign is outside its owned queue')
        if not (campaign / 'campaign-complete.json').is_file():
            raise ValueError('Complete collection before capturing replay evidence')
        campaigns.append(campaign.name)
        records = sorted(campaign.glob('attempt-*.json'))
        if not records:
            raise ValueError('Campaign has no attempt records')
        for record_path in [campaign / 'manifest.json', campaign / 'campaign-complete.json', *records]:
            retain(record_path, campaign)
        for record_path in records:
            record = json.loads(record_path.read_text())
            artifact = (record.get('metadata') or {}).get('info', {}).get('artifactPath')
            if artifact:
                path = Path(artifact).resolve(strict=True)
                if campaign.resolve() not in path.parents:
                    raise ValueError('Artifact is outside its owned campaign')
                actual = digest(path)
                expected = record['metadata']['info'].get('artifactSha256')
                if actual != expected:
                    raise ValueError('Artifact bytes differ from the journal')
                files[str(path.relative_to(queue))] = actual
    if not campaigns:
        raise ValueError('No completed campaigns found')
    return {'kind': 'immutable-measurement-replay-ledger', 'queue': str(queue), 'campaigns': campaigns, 'files': files}


def assert_unchanged(before, after):
    if before != after:
        raise ValueError('Replay changed campaign, measurement records, or original artifact bytes')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['capture', 'assert'])
    parser.add_argument('--queue', type=Path, required=True)
    parser.add_argument('--ledger', type=Path, required=True)
    args = parser.parse_args()
    current = capture(args.queue)
    if args.action == 'capture':
        with args.ledger.open('x') as output:
            json.dump(current, output, indent=2)
            output.write('\n')
    else:
        assert_unchanged(json.loads(args.ledger.read_text()), current)
    print(json.dumps({'action': args.action, 'campaigns': len(current['campaigns']), 'immutableFiles': len(current['files']), 'passed': True}))


if __name__ == '__main__':
    main()
