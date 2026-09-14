"""Small actual OS child, no media or network; defer during calibration quiet windows."""
import subprocess
import sys
import threading
import time
from unittest import mock

from client import campaign, suite


def test_actual_owned_slow_probe_stops_without_starting_measurement_allowance():
    stop = threading.Event()
    processes = []
    real_popen = subprocess.Popen
    def launch(command, **kwargs):
        if '-count_frames' not in command:
            return real_popen(command, **kwargs)
        # A deliberately stalled native-process stand-in exercises actual owned
        # process cancellation without depending on a media runtime or input.
        process = real_popen([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
        processes.append(process)
        stop.set()
        return process
    started = time.monotonic()
    try:
        with mock.patch.object(campaign.subprocess, 'Popen', side_effect=launch):
            with campaign.PreparationScope(stop).activate():
                assert campaign._MEASUREMENT_BUDGET.get() is None
                try:
                    suite._probe_clip('owned-source.mkv')
                    raise AssertionError('cancelled probe returned')
                except KeyboardInterrupt:
                    pass
        assert len(processes) == 1
        assert processes[0].poll() is not None
        assert time.monotonic() - started < 5
        assert campaign._PREPARATION.get() is None
        assert campaign._MEASUREMENT_BUDGET.get() is None
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
