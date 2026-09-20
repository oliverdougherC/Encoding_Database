#!/usr/bin/env python3
"""Export immutable native journal JSON with hashes; never rewrite originals."""
import argparse
import hashlib
import json
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--root', type=Path, required=True)
p.add_argument('--recipe', choices=['x264-crf23', 'nvenc-cq24', 'nvenc-vbr6000'], required=True)
a = p.parse_args()
phase = a.root / ('acceptance-' + a.recipe + '-é')
campaigns = list((phase / 'queue-客户' / 'campaigns').glob('campaign-*'))
if len(campaigns) != 1 or not (campaigns[0] / 'campaign-complete.json').is_file():
    raise ValueError('Expected one completed campaign')
files = sorted(campaigns[0].rglob('*.json'))
if len(files) > 250 or sum(x.stat().st_size for x in files) > 10 * 1024 * 1024:
    raise ValueError('Unexpectedly large journal export')
result = {'scope': 'Exact original native journal JSON; flags/timing unchanged', 'campaign': str(campaigns[0]), 'files': []}
for file in files:
    raw = file.read_bytes()
    result['files'].append({'name': str(file.relative_to(campaigns[0])), 'sha256': hashlib.sha256(raw).hexdigest(), 'data': json.loads(raw)})
output = a.root / ('raw-journals-' + a.recipe + '.json')
with output.open('x', encoding='utf-8') as handle:
    json.dump(result, handle, indent=2)
    handle.write('\n')
print(json.dumps({'output': str(output), 'files': len(files)}))
