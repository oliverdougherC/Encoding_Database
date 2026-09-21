#!/usr/bin/env python3
"""Freeze a relocatable native FFmpeg bundle from an installed macOS runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def dependencies(path):
    return [line.strip().split(' (compatibility version')[0]
            for line in command('otool', '-L', str(path)).splitlines()[1:]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg', required=True, type=Path)
    parser.add_argument('--ffprobe', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--architecture', default='arm64')
    parser.add_argument('--libvmaf', type=Path, help='Pinned model-compatible replacement libvmaf dylib')
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    lib = root / 'lib'
    lib.mkdir()
    originals = {args.ffmpeg.resolve(): root / 'ffmpeg', args.ffprobe.resolve(): root / 'ffprobe'}
    edges = {}
    pending = list(originals)
    names = {}
    while pending:
        source = pending.pop()
        if command('lipo', '-archs', str(source)).split() != [args.architecture]:
            raise RuntimeError(f'Wrong architecture: {source}')
        edges[source] = []
        for dependency in dependencies(source):
            if dependency.startswith(('/System/Library/', '/usr/lib/')):
                continue
            if dependency.startswith('@loader_path/'):
                resolved = (source.parent / dependency[len('@loader_path/'):]).resolve()
            elif dependency.startswith('/'):
                resolved = Path(dependency).resolve()
            elif dependency.startswith('@rpath/'):
                # Homebrew libraries use sibling dylibs with an LC_RPATH;
                # require a concrete existing sibling instead of a loader guess.
                resolved = (source.parent / dependency[len('@rpath/'):]).resolve()
                if not resolved.is_file():
                    raise RuntimeError(f'Unresolved rpath dependency {dependency} in {source}')
            else:
                raise RuntimeError(f'Unresolved dependency {dependency} in {source}')
            if resolved == source:
                continue
            if args.libvmaf and resolved.name.startswith('libvmaf.'):
                resolved = args.libvmaf.resolve(strict=True)
            edges[source].append((dependency, resolved))
            if resolved not in originals:
                existing = names.get(resolved.name)
                if existing is not None and existing != resolved:
                    raise RuntimeError(f'Conflicting dylib basename: {resolved.name}')
                names[resolved.name] = resolved
                originals[resolved] = lib / resolved.name
                pending.append(resolved)
    for source, destination in originals.items():
        shutil.copy2(source, destination)
        destination.chmod(0o755)
        if destination.parent == lib:
            subprocess.run(['install_name_tool', '-id', f'@loader_path/{destination.name}', str(destination)], check=True, capture_output=True)
        for old, resolved in edges[source]:
            prefix = '@loader_path/' if destination.parent == lib else '@loader_path/lib/'
            subprocess.run(['install_name_tool', '-change', old, prefix + originals[resolved].name, str(destination)], check=True, capture_output=True)
        subprocess.run(['codesign', '--force', '--sign', '-', str(destination)], check=True, capture_output=True)
    # Verify the relocated helpers execute with no loader search-path overrides.
    for helper in ('ffmpeg', 'ffprobe'):
        command(str(root / helper), '-version')
    records = []
    for source, destination in originals.items():
        records.append({
            'path': str(destination.relative_to(root)),
            'source': str(source),
            'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
            'byteSize': destination.stat().st_size,
            'architectures': command('lipo', '-archs', str(destination)).split(),
        })
    (root / 'bundle-manifest.json').write_text(json.dumps({
        'schemaVersion': 1, 'architecture': args.architecture, 'signing': 'ad-hoc; not Developer ID or notarized',
        'files': sorted(records, key=lambda record: record['path']),
    }, indent=2) + '\n')
    print(json.dumps({'bundle': str(root), 'files': len(records), 'bytes': sum(row['byteSize'] for row in records)}))


if __name__ == '__main__':
    main()
