"""Preserve reviewed runtime bytes through PyInstaller's Mach-O processing."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath


def _sha(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(value):
    text = str(value).replace('\\', '/')
    path = PurePosixPath(text)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        raise ValueError('Unsafe locked runtime archive path')
    return str(path)


def locked_records(payload, platform):
    entry = payload['platforms'][platform]
    records = {_relative(entry[k]['relativePath']): entry[k] for k in ('ffmpeg', 'ffprobe')}
    root = PurePosixPath(_relative(entry['ffmpeg']['relativePath'])).parent
    for dependency in entry.get('runtimeDependencies', []):
        name = str(root / _relative(dependency['relativePath']))
        if name in records:
            raise ValueError('Duplicate locked runtime path')
        records[name] = dependency
    return records


def preserve_locked_runtime(analysis, lock_path, platform):
    """Run after Analysis reclassification and before EXE/PKG binary transforms.

    PyInstaller 6.19 retains executable mode for executable DATA entries without
    rewriting their load commands/signatures. Python binaries stay untouched here.
    """
    records = locked_records(json.loads(Path(lock_path).read_text()), platform)
    selected = {}
    for entry in [*analysis.binaries, *analysis.datas]:
        destination, source, _kind = entry
        name = _relative(destination)
        if name not in records:
            continue
        if name in selected:
            raise ValueError(f'Duplicate runtime TOC member: {name}')
        expected = records[name]
        if os.path.getsize(source) != expected['byteSize'] or _sha(source) != expected['sha256']:
            raise ValueError(f'Analysis runtime bytes differ from reviewed lock: {name}')
        selected[name] = (destination, source, 'DATA')
    if set(selected) != set(records):
        raise ValueError(f'Analysis is missing locked runtime members: {sorted(set(records)-set(selected))}')
    analysis.binaries = [entry for entry in analysis.binaries if _relative(entry[0]) not in records]
    analysis.datas = [entry for entry in analysis.datas if _relative(entry[0]) not in records]
    analysis.datas.extend(selected.values())


def patch_spec(spec_path, lock_path, platform):
    spec = Path(spec_path)
    text = spec.read_text()
    marker = 'pyz = PYZ(a.pure)'
    if text.count(marker) != 1 or 'preserve_locked_runtime' in text:
        raise ValueError('Unexpected generated PyInstaller spec layout')
    root = str(Path(__file__).resolve().parent.parent)
    injection = (f'import sys\nsys.path.insert(0, {root!r})\n'
                 'from scripts.pyinstaller_locked_runtime import preserve_locked_runtime\n'
                 f'preserve_locked_runtime(a, {str(Path(lock_path).resolve())!r}, {platform!r})\n\n')
    spec.write_text(text.replace(marker, injection + marker))


def audit_archive(artifact_path, lock_path, platform, reader=None):
    if reader is None:
        from PyInstaller.archive.readers import CArchiveReader
        reader = CArchiveReader(str(artifact_path))
    payload = json.loads(Path(lock_path).read_text())
    records = locked_records(payload, platform)
    prefix = str(PurePosixPath(payload['platforms'][platform]['ffmpeg']['relativePath']).parent) + '/'
    actual = {name for name in reader.toc if name.startswith(prefix)}
    issues = []
    if actual != set(records):
        issues.append({'missing': sorted(set(records)-actual), 'unexpected': sorted(actual-set(records))})
    embedded = json.loads(reader.extract('resources/runtime/ffmpeg-lock.json'))
    expected_lock = {'schemaVersion': payload['schemaVersion'], 'runtimeId': payload['runtimeId'],
                     'source': payload['source'], 'platforms': {platform: payload['platforms'][platform]}}
    if embedded != expected_lock:
        issues.append({'error': 'embedded runtime lock differs from reviewed lock'})
    helpers = {payload['platforms'][platform][key]['relativePath'] for key in ('ffmpeg', 'ffprobe')}
    entries = []
    for name in sorted(actual & set(records)):
        data = reader.extract(name)
        observed = hashlib.sha256(data).hexdigest()
        kind = reader.toc[name][-1]
        expected = records[name]
        valid = observed == expected['sha256'] and len(data) == expected['byteSize']
        executable = kind == 'b'
        if not valid or (name in helpers and not executable):
            issues.append({'path': name, 'sha256Matches': valid, 'executable': executable})
        entries.append({'path': name, 'sha256': observed, 'byteSize': len(data), 'archiveType': kind})
    return {'schemaVersion': 1, 'platform': platform, 'artifactSha256': _sha(artifact_path),
            'reviewedLockSha256': _sha(lock_path), 'ok': not issues, 'issues': issues, 'entries': entries}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('patch-spec', 'audit'))
    parser.add_argument('--path', required=True)
    parser.add_argument('--lock', required=True)
    parser.add_argument('--platform', default='mac')
    args = parser.parse_args()
    if args.operation == 'patch-spec':
        patch_spec(args.path, args.lock, args.platform)
        return 0
    result = audit_archive(args.path, args.lock, args.platform)
    print(json.dumps(result, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
