#!/usr/bin/env python3
"""Install/remove only a uniquely marked isolated acceptance cron entry.

This is not a production scheduler installer. Never restores a stale whole
crontab: removal always re-reads and removes only this exact marker.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


def current():
    result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    if result.returncode and 'no crontab' not in result.stderr.lower():
        raise RuntimeError('cannot read user crontab')
    return result.stdout if result.returncode == 0 else ''


def update(marker, replacement):
    for _ in range(10):
        before = current()
        lines = [line for line in before.splitlines() if not line.endswith('# ' + marker)]
        if replacement is not None:
            lines.append(replacement)
        after = '\n'.join(lines) + ('\n' if lines else '')
        if current() != before:
            continue
        result = subprocess.run(['crontab', '-'], input=after, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError('user crontab update failed')
        observed = current()
        # Retain concurrent additions made after installation; never overwrite them.
        if all(line in observed.splitlines() for line in lines):
            return before, observed
        raise RuntimeError('crontab changed during update; stop for inspection instead of restoring stale contents')
    raise RuntimeError('user crontab kept changing; no update attempted')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['install', 'remove'])
    parser.add_argument('--marker', required=True)
    parser.add_argument('--work-root', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'encodingdb-isolated-[a-z0-9-]+', args.marker):
        parser.error('marker must identify an isolated EncodingDB acceptance job')
    root = args.work_root.resolve()
    if not str(root).startswith('/mnt/NVME/docker/encodingdb-operations/20260914-') or any(c in str(root) for c in '\n%\r '):
        parser.error('use the explicit task-owned P910 acceptance work root')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    entry = None
    if args.mode == 'install':
        if not (root / 'cron-once.sh').is_file():
            parser.error('prepare the bounded cron-once.sh and private environment first')
        entry = f'* * * * * /bin/bash {root}/cron-once.sh >> {root}/cron.log 2>&1 # {args.marker}'
    if args.mode == 'install':
        private = root / 'crontab-before.private'
        try:
            with open(private, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as saved:
                saved.write(current())
        except FileExistsError:
            pass  # Keep the original private receipt on an idempotent retry.
    before, after = update(args.marker, entry)
    own = '# ' + args.marker
    receipt = {'mode': args.mode, 'marker': args.marker, 'beforeSha256': hashlib.sha256(before.encode()).hexdigest(), 'afterSha256': hashlib.sha256(after.encode()).hexdigest(), 'unrelatedLinesPreserved': all(line in after.splitlines() for line in before.splitlines() if not line.endswith(own)), 'ownEntryCount': sum(line.endswith(own) for line in after.splitlines())}
    (root / f'cron-{args.mode}-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
