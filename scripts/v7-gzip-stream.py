#!/usr/bin/env python3
"""Bounded, compatible gzip archive stream; stored blocks suit encoded media."""
import gzip
import json
import os
import sys
import time

level = int(os.environ.get('V7_BACKUP_COMPRESSION_LEVEL', '0'))
if not 0 <= level <= 9 or len(sys.argv) != 2:
    raise SystemExit('provide output path and compression level 0..9')
started = time.monotonic()
size = 0
with open(sys.argv[1], 'xb') as raw:
    with gzip.GzipFile(filename='', mode='wb', fileobj=raw, compresslevel=level, mtime=0) as output:
        while chunk := sys.stdin.buffer.read(1024 * 1024):
            output.write(chunk)
            size += len(chunk)
    raw.flush()
    os.fsync(raw.fileno())
print(json.dumps({'kind': 'backup-archive-stream', 'compressionLevel': level, 'inputBytes': size, 'elapsedSeconds': time.monotonic() - started}), file=sys.stderr)
