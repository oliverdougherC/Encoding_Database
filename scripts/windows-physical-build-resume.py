#!/usr/bin/env python3
"""Resume source-939's exact packaging commands without PS5 stderr coercion."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

REVISION = '939823ead2c052572f9deb5c9f91c85435d5661d'
ARCHIVE = '4e40699fa864811312d6c1895ea4873beaf8475e1188563fee57fac860554601'


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    source = root / 'source-939823e'
    receipt_path = root / 'physical-build-resume-receipt.json'
    log_path = root / 'physical-build-resume.log'
    if receipt_path.exists() or log_path.exists():
        raise RuntimeError('Create-only resume evidence already exists')
    if os.name != 'nt':
        raise RuntimeError('Actual Windows is required')
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    changes = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain', '--untracked-files=no'], text=True).strip()
    if revision != REVISION or changes:
        raise RuntimeError('Reviewed source is not clean and exact')
    if sha(root / 'runtime-939823e' / 'ffmpeg-win.zip') != ARCHIVE:
        raise RuntimeError('Reviewed runtime archive changed')
    build = source / '.build' / 'clients' / 'windows'
    python = build / 'venv' / 'Scripts' / 'python.exe'
    bins = root / 'runtime-939823e' / 'ffmpeg-n8.1.2-51-g7ba069f4f1-win64-gpl-8.1' / 'bin'
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(('ENCODINGDB_', 'V7_OPERATOR_', 'DYLD_')) or key in ('FFMPEG_EXE', 'FFPROBE_EXE', 'PYTHONPATH', 'PYTHONHOME', 'LD_LIBRARY_PATH'):
            del env[key]
    env['ENCODINGDB_FFMPEG_PATH'] = str(bins / 'ffmpeg.exe')
    env['ENCODINGDB_FFPROBE_PATH'] = str(bins / 'ffprobe.exe')
    env['FFMPEG_EXE'] = env['ENCODINGDB_FFMPEG_PATH']
    env['FFPROBE_EXE'] = env['ENCODINGDB_FFPROBE_PATH']
    env['PATH'] = str(root / 'bootstrap-venv-939823e' / 'Scripts') + os.pathsep + env['PATH']
    env['ENCODINGDB_STATE_DIR'] = str(root / 'host-state')
    env['ENCODINGDB_SUITE_CACHE_DIR'] = str(root / 'suite-cache')
    receipt = {'schemaVersion': 1, 'status': 'RUNNING', 'kind': 'physical-built-candidate-distinct-from-CI',
        'actualSource': revision, 'trackedStatusBefore': changes, 'sourceTree': subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD^{tree}'], text=True).strip(), 'startedAt': datetime.now(timezone.utc).isoformat(), 'commands': [],
        'buildDeviation': 'Unmodified source build script stopped because Windows PowerShell 5.1 treated normal PyInstaller stderr INFO as terminating. This operator executes its exact PyInstaller and finalizer arguments via subprocess, leaving tracked source untouched.'}

    def save():
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')

    save()
    import msvcrt
    state = root / 'host-state'
    state.mkdir(parents=True, exist_ok=True)
    allocation = (state / 'physical-operator.lock').open('a+b')
    allocation.seek(0)
    allocation.write(b'0')
    allocation.flush()
    allocation.seek(0)
    msvcrt.locking(allocation.fileno(), msvcrt.LK_NBLCK, 1)
    try:
        with log_path.open('x', encoding='utf-8') as log:
            def run(command):
                entry = {'argv': list(map(str, command)), 'startedAt': datetime.now(timezone.utc).isoformat()}
                receipt['commands'].append(entry)
                save()
                print('PHYSICAL_BUILD_RESUME: ' + ' '.join(entry['argv']), flush=True)
                result = subprocess.run(command, cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
                entry.update(exitCode=result.returncode, finishedAt=datetime.now(timezone.utc).isoformat())
                save()
                if result.returncode:
                    raise RuntimeError(f'Packaging command failed: {result.returncode}; see {log_path}')

            # Same arguments, stage directories and entrypoints as source-939's
            # Invoke-PyInstallerBuild; only the parent stream transport differs.
            for name, entrypoint, windowed in [
                ('encodingdb-client-windows', '_pyinstaller_gui_entry.py', True),
                ('encodingdb-client-windows-console', '_pyinstaller_entry.py', False),
            ]:
                output = source / (name + '.exe')
                if output.exists():
                    raise RuntimeError(f'Refuse overwriting an existing candidate: {output}')
                work, spec = build / 'work' / name, build / 'spec' / name
                work.mkdir(parents=True, exist_ok=True)
                spec.mkdir(parents=True, exist_ok=True)
                command = [str(python), '-m', 'PyInstaller', '--clean', '--onefile', '--name', name,
                    '--distpath', str(build / 'dist'), '--workpath', str(work), '--specpath', str(spec), '--paths', str(source),
                    '--add-data', f'{bins / "ffmpeg.exe"};bin/win', '--add-data', f'{bins / "ffprobe.exe"};bin/win',
                    '--add-data', f'{source / "client" / "presets.json"};.',
                    '--add-data', f'{build / "suite_resources" / "test_suite_v1"};resources/test_suite_v1',
                    '--add-data', f'{build / "runtime_resources"};resources/runtime',
                    '--add-data', f'{source / "client" / "resources" / "vmaf"};resources/vmaf']
                if windowed:
                    command.append('--windowed')
                command.append(str(source / 'client' / entrypoint))
                run(command)
                (build / 'dist' / output.name).rename(output)
            for name, skip in [('encodingdb-client-windows', True), ('encodingdb-client-windows-console', False)]:
                command = [str(python), str(source / 'scripts' / 'release_manifest_lib.py'), '--artifact-path', str(source / (name + '.exe')),
                    '--platform', 'win', '--ffmpeg-path', str(bins / 'ffmpeg.exe'), '--ffprobe-path', str(bins / 'ffprobe.exe'),
                    '--runtime-lock-path', str(source / 'client' / 'resources' / 'runtime' / 'ffmpeg-lock.json'),
                    '--suite-pack-path', str(source / 'encodingdb-test-suite-v1.tar.gz'), '--output-dir', str(source)]
                if skip:
                    command.append('--skip-smoke')
                run(command)
            run([str(python), '-m', 'pip', 'freeze', '--all'])
        receipt['trackedStatusAfter'] = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain', '--untracked-files=no'], text=True).strip()
        if receipt['trackedStatusAfter']:
            raise RuntimeError('Tracked source changed')
        receipt['artifacts'] = [{'name': path.name, 'bytes': path.stat().st_size, 'sha256': sha(path)} for path in sorted(source.glob('encodingdb-client-windows*')) if path.is_file()]
        receipt['status'] = 'BUILT_PENDING_INDEPENDENT_PINS_AND_ACCEPTANCE'
    except BaseException as error:
        receipt['status'] = 'FAILED'
        receipt['error'] = str(error)
        raise
    finally:
        receipt['finishedAt'] = datetime.now(timezone.utc).isoformat()
        save()
        allocation.seek(0)
        msvcrt.locking(allocation.fileno(), msvcrt.LK_UNLCK, 1)
        allocation.close()
        print(json.dumps({'status': receipt['status'], 'receipt': str(receipt_path)}), flush=True)


if __name__ == '__main__':
    main()
