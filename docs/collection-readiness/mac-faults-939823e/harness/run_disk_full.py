"""Exhaust only a bounded task-owned HFS+ image, then verify native replay recovery."""
import errno
import json
import os
import plistlib
import shutil
import subprocess


def run(sys_modules_helper):
    h = sys_modules_helper
    root = h.ROOT / 'disk-full'
    root.mkdir(exist_ok=False)
    image = root / 'bounded-64MiB.dmg'
    queue = h.WORK / 'recovery-queue'
    backup = root / 'host-queue-backup'
    campaign = next((queue / 'campaigns').iterdir()).name
    assert (queue / 'campaigns' / campaign / 'campaign-complete.json').exists()
    prior = h.snapshot(queue)
    assert any(row['schedule']['phase'] == 'measured' for row in prior.values())
    assert sum(p.stat().st_size for p in queue.rglob('*') if p.is_file()) < 45 * 1024 * 1024
    commands = []

    def command(argv):
        result = subprocess.run(argv, capture_output=True, timeout=60)
        commands.append({'command': argv, 'exitCode': result.returncode,
                         'stdout': result.stdout.decode(errors='replace'), 'stderr': result.stderr.decode(errors='replace')})
        h.save('disk-full-volume-commands', commands)
        result.check_returncode()
        return result.stdout

    def unchanged():
        return all(h.sha(path) == row['recordSha256'] and h.sha(row['artifactPath']) == row['artifactSha256']
                   for path, row in prior.items())

    command(['hdiutil', 'create', '-size', '64m', '-fs', 'HFS+', '-volname', 'EncodingDBFault939', '-type', 'UDIF', '-nospotlight', str(image)])
    queue.rename(backup)
    queue.mkdir()
    device = None
    detached = False
    try:
        attachment = plistlib.loads(command(['hdiutil', 'attach', '-nobrowse', '-mountpoint', str(queue), '-plist', str(image)]))
        device = next(e['dev-entry'] for e in attachment['system-entities'] if 'mount-point' in e)
        h.save('disk-full-attachment', {'image': str(image), 'mount': str(queue), 'device': device, 'entities': attachment['system-entities']})
        space = os.statvfs(queue)
        assert os.path.ismount(queue) and queue.stat().st_dev != root.stat().st_dev
        assert space.f_blocks * space.f_frsize <= 128 * 1024 * 1024, 'Refusing to fill host filesystem'
        shutil.copytree(backup, queue, dirs_exist_ok=True)
        h.save('disk-full-before', prior)
        filler = queue / 'owned-filler.bin'
        written = 0
        observed = None
        with filler.open('wb', buffering=0) as handle:
            while written < 128 * 1024 * 1024:
                try:
                    written += handle.write(b'\0' * (1024 * 1024))
                except OSError as error:
                    if error.errno != errno.ENOSPC:
                        raise
                    observed = {'errno': error.errno, 'message': str(error)}
                    break
        assert observed
        tiny = []
        for index in range(4096):
            path = queue / f'owned-tail-{index}.bin'
            try:
                with path.open('wb', buffering=0) as handle:
                    handle.write(b'x')
                tiny.append(path)
            except OSError as error:
                if error.errno != errno.ENOSPC:
                    raise
                observed = {'errno': error.errno, 'message': str(error), 'freshOneByteWriteFailed': True}
                break
        else:
            raise RuntimeError('Did not exhaust small-file allocation')
        remaining = os.statvfs(queue)
        h.save('disk-full-capacity', {'totalBytes': remaining.f_blocks * remaining.f_frsize,
                                     'availableBytes': remaining.f_bavail * remaining.f_frsize,
                                     'tinyFiles': len(tiny), 'osError': observed})
        argv = [h.WORK / 'encodingdb-client-macos', '--resume-campaign', campaign, '--no-submit', '--max-duration-minutes', '3', '--queue-dir', queue]
        result = h.finish(h.launch('disk-full', argv), 180)
        result.update(volumeBytes=space.f_blocks * space.f_frsize, fillerBytes=written, osError=observed,
                      method='Completed journal replay on private full HFS+ volume; no re-encoding requested', priorRecordsUnchanged=unchanged())
        h.save('disk-full', result)
        assert result['exitCode'] == 6 and result['priorRecordsUnchanged']
        filler.unlink()
        for path in tiny:
            path.unlink(missing_ok=True)
        recovered = h.finish(h.launch('disk-full-freed-resume', argv), 180)
        recovered.update(priorRecordsUnchanged=unchanged(), before=prior, after=h.snapshot(queue))
        h.save('disk-full-freed-resume', recovered)
        assert recovered['exitCode'] == 0 and recovered['priorRecordsUnchanged'] and set(recovered['after']) == set(prior)
        for path in queue.rglob('*.json'):
            target = h.LOGS / 'disk-full-retained-metadata' / path.relative_to(queue)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    finally:
        h.cleanup_owned()
        if device:
            command(['hdiutil', 'detach', device])
            detached = True
        if not os.path.ismount(queue):
            queue.rmdir()
            backup.rename(queue)
        h.save('disk-full-detached', {'device': device, 'detached': detached, 'imageSha256': h.sha(image),
                                     'originalHostQueueRestored': queue.is_dir() and not backup.exists(),
                                     'originalRecordsUnchanged': unchanged() if queue.is_dir() else False})
