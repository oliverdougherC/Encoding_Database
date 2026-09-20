#!/usr/bin/env python3
"""Independently rehash physical candidate files before native acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    source = root / 'source-939823e'
    revision = '939823ead2c052572f9deb5c9f91c85435d5661d'
    tree = '532898f45d3e71fd0138d4911889dd7ff1a2ccdc'
    if subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() != revision:
        raise ValueError('Source revision differs')
    if subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD^{tree}'], text=True).strip() != tree:
        raise ValueError('Reviewed source tree differs')
    if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain', '--untracked-files=no'], text=True).strip():
        raise ValueError('Tracked source is dirty')
    pack_sha = sha(source / 'encodingdb-test-suite-v1.tar.gz')
    if pack_sha != 'd20407f8d78f152f06c3b7271881d8b3f07d2b76cf3a2642b241162d666ac150':
        raise ValueError('Canonical pack differs')
    model_sha = sha(source / 'client/resources/vmaf/vmaf_v1.0.16_3d0h.json')
    if model_sha != 'e4cf8c147e1368b35497d772920bc92f98c1ad7853c1033d8a836947f427140e':
        raise ValueError('Pinned model differs')
    files = {p.name: sha(p) for p in sorted(source.glob('encodingdb-client-windows*')) if p.is_file()}
    files['encodingdb-test-suite-v1.tar.gz'] = pack_sha
    for name in ['encodingdb-client-windows.exe', 'encodingdb-client-windows-console.exe']:
        manifest = json.loads((source / (name + '.release-manifest.json')).read_text())
        if manifest['source']['revision'] != revision or manifest['source']['trackedChanges'] is not False or manifest['artifact']['sha256'] != files[name]:
            raise ValueError('Executable/source manifest differs')
        if manifest['qualityModel']['sha256'] != model_sha or manifest['protocol']['benchmarkProtocolVersion'] != '7.1':
            raise ValueError('Unexpected quality model or protocol')
        with (source / name).open('rb') as handle:
            header = handle.read(64)
            if header[:2] != b'MZ':
                raise ValueError('Expected PE executable')
            handle.seek(struct.unpack_from('<I', header, 60)[0])
            if handle.read(6) != b'PE\0\0\x64\x86':
                raise ValueError('Expected native x86_64 PE machine')
    smoke = json.loads((source / 'encodingdb-client-windows-console.exe.smoke.json').read_text())
    if smoke['submissionMode'] != 'no-submit' or smoke['embeddedRuntime']['frozen'] is not True:
        raise ValueError('Embedded smoke not observed')
    if [x['name'] for x in smoke['commands']] != ['help', 'no-submit-suite']:
        raise ValueError('Required smoke commands not observed')
    if any(x['returnCode'] != 0 or x['timedOut'] or x['cleanupForced'] or x['survivingOwnedPids'] for x in smoke['commands']):
        raise ValueError('Smoke did not pass cleanly')
    pins = {'kind': 'physical-built-candidate-not-CI', 'actualBuildRevision': revision, 'sourceTree': tree,
        'buildPythonVersion': manifest['source']['buildPythonVersion'], 'suiteFingerprint': 'd40bff563dead0e78003af90b2626003bd80afcc12220ab86bc6d4a4b8c83b6e',
        'modelSha256': model_sha, 'files': files}
    path = root / 'physical-candidate-pins.json'
    with path.open('x', encoding='utf-8') as output:
        json.dump(pins, output, indent=2)
        output.write('\n')
    print(json.dumps({'status': 'PINNED', 'path': str(path), 'consoleSha256': files['encodingdb-client-windows-console.exe'], 'guiSha256': files['encodingdb-client-windows.exe']}))


if __name__ == '__main__':
    main()
