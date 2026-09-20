"""Keep an owned orphan alive until the actual native resume path recovers it."""
import datetime
import fcntl
import os
import signal
import time

import psutil
import run_packaged_faults as h

h.LOGS = h.ROOT / 'live-orphan-receipts'
h.LOGS.mkdir(exist_ok=False)
queue = h.WORK / 'live-orphan-queue'
assert not queue.exists()
original_finish = h.finish


def finish_with_paused_orphan(run, timeout=360):
    info = run[2]
    if info['case'] == 'live-orphan-kill':
        active = info['activeReceipt']
        encoder = psutil.Process(active['pid'])
        assert encoder.create_time() == active['createdAt'] and encoder.cmdline() == active['command']
        assert os.getpgid(encoder.pid) == encoder.pid
        os.killpg(encoder.pid, signal.SIGSTOP)
        deadline = time.monotonic() + 2
        while encoder.status() != psutil.STATUS_STOPPED and time.monotonic() < deadline:
            time.sleep(0.01)
        assert encoder.status() == psutil.STATUS_STOPPED
        info['orphanPause'] = {'signal': 'SIGSTOP', 'pid': encoder.pid, 'createdAt': encoder.create_time(),
                               'status': encoder.status(), 'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                               'purpose': 'Keep the owned orphan live until native recovery; no timing/calibration claim.'}
        h.save('live-orphan-pause', info['orphanPause'])
    return original_finish(run, timeout)


h.finish = finish_with_paused_orphan
with (h.STATE / 'measurement.lock').open('a+b') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    h.save('host-lock', {'path': str(h.STATE / 'measurement.lock'), 'pid': os.getpid(),
                         'acquiredAt': datetime.datetime.now(datetime.timezone.utc).isoformat()})
    try:
        exe = h.WORK / 'encodingdb-client-macos'
        assert h.sha(exe) == h.EXPECTED_SHA
        command = [exe, '--cli', '--codec', 'libx264', '--presets', 'veryslow', '--no-submit',
                   '--max-duration-minutes', '3', '--queue-dir', queue]
        killed, prior, campaign = h.stop_at_active(h.launch('live-orphan-kill', command), queue, False, 'SIGKILL')
        assert killed['exitCode'] == -9 and killed['orphanAliveAfterStop']
        active = killed['activeReceipt']
        old = psutil.Process(active['pid'])
        assert old.create_time() == active['createdAt'] and old.status() == psutil.STATUS_STOPPED
        resume = [exe, '--resume-campaign', campaign, '--no-submit', '--max-duration-minutes', '3', '--queue-dir', queue]
        result = h.finish(h.launch('live-orphan-resume', resume), 300)
        result['retainedBefore'] = prior
        result['retainedAfter'] = h.snapshot(queue)
        result['priorRecordsUnchanged'] = all(h.sha(path) == row['recordSha256'] and h.sha(row['artifactPath']) == row['artifactSha256'] for path, row in prior.items())
        try:
            old = psutil.Process(active['pid'])
            result['oldOrphanStillAlive'] = old.create_time() == active['createdAt'] and old.is_running() and old.status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            result['oldOrphanStillAlive'] = False
        result['orphanReceiptRemoved'] = not any((queue / 'campaigns' / campaign).glob('*.active.json'))
        h.save('live-orphan-resume', result)
        assert result['exitCode'] == 0 and result['priorRecordsUnchanged'] and not result['oldOrphanStillAlive'] and result['orphanReceiptRemoved']
    finally:
        h.cleanup_owned()
        h.save('local-http', h.requests)
        h.proxy.shutdown()
        h.proxy.server_close()
h.save('host-lock-released', {'path': str(h.STATE / 'measurement.lock'), 'releasedAt': datetime.datetime.now(datetime.timezone.utc).isoformat()})
