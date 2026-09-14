#!/usr/bin/env python3
"""Bound backup execution and give its EXIT trap time to restart stopped writers."""
import os
import signal
import subprocess
import sys
import time


def main():
    timeout = int(os.environ.get('V7_BACKUP_TIMEOUT_SECONDS', '300'))
    grace = int(os.environ.get('V7_BACKUP_RECOVERY_GRACE_SECONDS', '60'))
    if timeout < 1 or grace < 1:
        raise SystemExit('backup timeout and recovery grace must be positive')
    started = time.monotonic()
    child = subprocess.Popen(['bash', *sys.argv[1:]], env={**os.environ, 'V7_BACKUP_SUPERVISED': '1'}, start_new_session=True)

    def terminate(_sig=None, _frame=None):
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        code = child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f'Backup exceeded {timeout}s deadline; cancelling owned commands and restarting quiesced services via EXIT trap.', file=sys.stderr)
        terminate()
        try:
            child.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            print('Backup recovery grace expired. Operator must verify/restart writer services; backup did not pass.', file=sys.stderr)
        code = 124
    print(f'Backup supervisor: exit={code}, elapsedSeconds={time.monotonic() - started:.3f}', file=sys.stderr)
    return code if code >= 0 else 128 - code


if __name__ == '__main__':
    raise SystemExit(main())
