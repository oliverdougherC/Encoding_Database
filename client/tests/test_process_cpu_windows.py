"""Process CPU deltas must survive discovery without inheriting reused PID history."""
import os
from types import SimpleNamespace
from unittest import mock

import psutil
import pytest

from client import hardware_monitor as telemetry


@pytest.fixture
def process_clock(monkeypatch):
    state = SimpleNamespace(now=10.0, cpu=1.0, created=100.0)
    monkeypatch.setattr(psutil, '_timer', lambda: state.now)
    monkeypatch.setattr(telemetry.time, 'monotonic', lambda: state.now)
    return state


def discovered_process(state, *, pid=None, created=None):
    # Keep real psutil.Process.cpu_percent and its actual per-object baselines.
    # Only the OS counters are deterministic; no busy worker is needed.
    proc = psutil.Process(os.getpid())
    if pid is not None:
        proc._pid = pid
    proc._proc = SimpleNamespace(cpu_times=lambda: SimpleNamespace(user=state.cpu, system=0.0))
    proc.create_time = lambda: state.created if created is None else created
    return proc


def test_fresh_discovery_retains_real_psutil_deltas_and_valid_zero(process_clock):
    state = process_clock
    monitor = telemetry.HardwareMonitor(ffmpeg_pid=os.getpid(), encoder_name='libx264')
    with mock.patch.object(monitor, '_collect_process_tree', side_effect=lambda **kw: [discovered_process(state)]):
        monitor._sample_ffmpeg_process()
        assert monitor._aggregate().ffmpeg_cpu_util_avg is None
        assert monitor._aggregate().ffmpeg_sample_count == 0
        state.now += 0.5
        state.cpu += 1.0
        assert discovered_process(state).cpu_percent(interval=None) == 0.0  # Original defect.
        monitor._sample_ffmpeg_process()
        state.now += 0.5
        monitor._sample_ffmpeg_process()
    metrics = monitor._aggregate()
    assert [sample.cpu_pct for sample in monitor._proc_samples] == [200.0, 0.0]
    assert metrics.ffmpeg_cpu_util_avg == 100.0
    assert metrics.ffmpeg_cpu_util_max == 200.0
    assert metrics.ffmpeg_sample_count == 2
    assert telemetry.FFMPEG_PROCESS_WINDOW_SOURCE in monitor._sources


def test_reused_pid_discards_prior_process_baseline(process_clock):
    state = process_clock
    monitor = telemetry.HardwareMonitor(encoder_name='libx264')
    with mock.patch.object(monitor, '_collect_process_tree', side_effect=lambda **kw: [discovered_process(state)]):
        monitor._sample_ffmpeg_process()
        state.now += 0.5
        state.created += 1.0
        state.cpu = 1000.0
        monitor._sample_ffmpeg_process()
        assert monitor._proc_samples == []
        assert len(monitor._proc_cpu_windows) == 1
        state.now += 0.5
        state.cpu += 0.25
        monitor._sample_ffmpeg_process()
    assert monitor._aggregate().ffmpeg_cpu_util_avg == 50.0


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -1.0, None, psutil.AccessDenied(123)])
def test_failed_counter_requires_new_baseline_without_manufacturing_zero(process_clock, bad):
    state = process_clock
    monitor = telemetry.HardwareMonitor(encoder_name='libx264')
    with mock.patch.object(monitor, '_collect_process_tree', side_effect=lambda **kw: [discovered_process(state)]):
        monitor._sample_ffmpeg_process()
        cached = next(iter(monitor._proc_cpu_windows.values()))[0]
        cached.cpu_percent = mock.Mock(side_effect=bad) if isinstance(bad, Exception) else mock.Mock(return_value=bad)
        state.now += 0.5
        monitor._sample_ffmpeg_process()
        assert monitor._proc_samples == []
        assert monitor._proc_cpu_windows == {}
        assert monitor._aggregate().ffmpeg_cpu_util_avg is None
        assert 'ffmpeg_cpu_unavailable' in monitor._missing
        state.now += 0.5
        monitor._sample_ffmpeg_process()
        assert monitor._proc_samples == []
        state.now += 0.5
        state.cpu += 0.5
        monitor._sample_ffmpeg_process()
    assert monitor._aggregate().ffmpeg_cpu_util_avg == 100.0


def test_new_child_makes_whole_sample_unknown_until_all_baselines_are_warm(process_clock):
    state = process_clock
    monitor = telemetry.HardwareMonitor(encoder_name='libx264')
    include_child = [False]
    def discover(**kwargs):
        root = discovered_process(state)
        return [root, discovered_process(state, pid=999)] if include_child[0] else [root]
    with mock.patch.object(monitor, '_collect_process_tree', side_effect=discover):
        monitor._sample_ffmpeg_process()
        state.now += 0.5
        state.cpu += 0.5
        include_child[0] = True
        monitor._sample_ffmpeg_process()
        assert monitor._proc_samples == []
        state.now += 0.5
        state.cpu += 0.5
        monitor._sample_ffmpeg_process()
        assert monitor._aggregate().ffmpeg_cpu_util_avg == 200.0
        include_child[0] = False
        state.now += 0.5
        monitor._sample_ffmpeg_process()
        assert len(monitor._proc_cpu_windows) == 1
        include_child[0] = True
        state.now += 0.5
        monitor._sample_ffmpeg_process()
        assert len(monitor._proc_samples) == 2  # Returned child needs a new baseline.


def test_too_short_window_and_missing_tree_are_unknown(process_clock):
    state = process_clock
    monitor = telemetry.HardwareMonitor(encoder_name='libx264')
    with mock.patch.object(monitor, '_collect_process_tree', side_effect=lambda **kw: [discovered_process(state)]):
        monitor._sample_ffmpeg_process()
        state.now += 0.01
        monitor._sample_ffmpeg_process()
    with mock.patch.object(monitor, '_collect_process_tree', return_value=[]):
        monitor._sample_ffmpeg_process()
    metrics = monitor._aggregate()
    assert metrics.ffmpeg_cpu_util_avg is None
    assert metrics.ffmpeg_cpu_util_max is None
    assert metrics.ffmpeg_sample_count == 0
    assert monitor._proc_cpu_windows == {}
    assert 'ffmpeg_unavailable' in monitor._missing
    assert telemetry.FFMPEG_PROCESS_WINDOW_SOURCE not in monitor._sources


def test_failed_child_discovery_does_not_publish_partial_process_cpu(process_clock):
    monitor = telemetry.HardwareMonitor(ffmpeg_pid=os.getpid(), encoder_name='libx264')
    root = discovered_process(process_clock)
    root.children = mock.Mock(side_effect=psutil.AccessDenied(root.pid))
    with mock.patch.object(psutil, 'Process', return_value=root):
        monitor._sample_ffmpeg_process()
    assert monitor._aggregate().ffmpeg_cpu_util_avg is None
    assert 'ffmpeg_cpu_unavailable' in monitor._missing


@pytest.mark.parametrize('created', [None, float('nan'), 0.0])
def test_missing_process_identity_is_unknown(process_clock, created):
    process_clock.created = created
    monitor = telemetry.HardwareMonitor(encoder_name='libx264')
    with mock.patch.object(monitor, '_collect_process_tree', side_effect=lambda **kw: [discovered_process(process_clock)]):
        monitor._sample_ffmpeg_process()
    assert monitor._proc_cpu_windows == {}
    assert monitor._aggregate().ffmpeg_cpu_util_avg is None
    assert 'ffmpeg_cpu_unavailable' in monitor._missing
