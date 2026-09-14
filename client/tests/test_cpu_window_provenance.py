import threading
from unittest import mock

import pytest

from client import hardware, hardware_monitor as telemetry, main
from client.config import HardwareInfo


@pytest.mark.parametrize('bad', [None, float('nan'), float('inf'), -1, 101])
def test_blocking_fallback_missing_or_invalid_counter_is_unknown(bad):
    with mock.patch.object(hardware.psutil, 'cpu_percent', return_value=bad):
        assert hardware.measure_background_cpu_load(0.5, 0.25) is None


def test_blocking_fallback_exception_never_fabricates_idle():
    with mock.patch.object(hardware.psutil, 'cpu_percent', side_effect=[50, RuntimeError('counter failed')]):
        assert hardware.measure_background_cpu_load(0.5, 0.25) is None


@pytest.mark.parametrize('seconds,interval', [(0,0.25),(1,0),(float('nan'),0.25),(1,float('inf'))])
def test_blocking_fallback_requires_a_positive_finite_window(seconds, interval):
    with mock.patch.object(hardware.psutil, 'cpu_percent') as sample:
        assert hardware.measure_background_cpu_load(seconds, interval) is None
    sample.assert_not_called()


@pytest.mark.parametrize('load', [0.0,50.0])
def test_successful_fallback_uses_blocking_fresh_intervals(load):
    with mock.patch.object(hardware.psutil, 'cpu_percent', return_value=load) as sample:
        assert hardware.measure_background_cpu_load(0.5, 0.25) == load
    assert sample.call_args_list == [mock.call(interval=0.25),mock.call(interval=0.25)]


@pytest.mark.parametrize('monitor_load,source,fallback,expected,expected_marker', [
    (0.0, telemetry.CPU_THREAD_WINDOW_SOURCE, None, 0.0, telemetry.CPU_THREAD_WINDOW_SOURCE),
    (None, 'gpu_nvml', 0.0, 0.0, hardware.CPU_BLOCKING_WINDOW_SOURCE),
    (None, telemetry.CPU_THREAD_WINDOW_SOURCE, 50.0, 50.0, hardware.CPU_BLOCKING_WINDOW_SOURCE),
    (None, telemetry.CPU_THREAD_WINDOW_SOURCE, None, None, None),
    (float('nan'), telemetry.CPU_THREAD_WINDOW_SOURCE, float('nan'), None, None),
    (25.0, 'cpu_psutil', None, 25.0, None),
])
def test_snapshot_marker_is_attributed_only_to_actual_observation(monitor_load, source, fallback, expected, expected_marker):
    metrics = telemetry.HardwareMetrics(cpu_util_avg=monitor_load, telemetry_sources=source)
    monitor = mock.Mock()
    monitor.stop.return_value = metrics
    with mock.patch.object(main, 'HardwareMonitor', return_value=monitor), \
         mock.patch.object(main.time, 'sleep'), \
         mock.patch.object(main, 'measure_background_cpu_load', return_value=fallback) as blocking:
        snapshot = main._capture_protocol_environment_snapshot(hardware=HardwareInfo('CPU',None,16,'test'), encoder='libx264')
    payload = snapshot.to_dict()
    assert payload['background_cpu_pct'] == expected
    markers = set((payload['telemetry_sources'] or '').split(',')) & {
        telemetry.CPU_THREAD_WINDOW_SOURCE, hardware.CPU_BLOCKING_WINDOW_SOURCE}
    assert markers == ({expected_marker} if expected_marker else set())
    if monitor_load is not None and monitor_load == monitor_load:
        blocking.assert_not_called()
    else:
        blocking.assert_called_once()


def test_failed_counter_and_subminimum_interval_cannot_claim_fresh_sampler_window():
    monitor = telemetry.HardwareMonitor(encoder_name='libx264')
    monitor._cpu_sampler_ident = threading.get_ident()
    with mock.patch.object(telemetry.psutil, 'cpu_percent', side_effect=[10,float('nan'),20,50,45]), \
         mock.patch.object(telemetry.time, 'monotonic', side_effect=[1.0,2.0,2.05,2.25]), \
         mock.patch.object(telemetry.psutil, 'cpu_freq', return_value=None), \
         mock.patch.object(telemetry.psutil, 'sensors_temperatures', return_value={}, create=True):
        monitor._sample_cpu()  # Initial baseline only.
        monitor._sample_cpu()  # Failed/non-finite counter invalidates baseline.
        monitor._sample_cpu()  # Successful replacement baseline only.
        monitor._sample_cpu()  # 50ms delta is not a fresh supported interval.
        assert monitor._cpu_samples == []
        assert telemetry.CPU_THREAD_WINDOW_SOURCE not in monitor._sources
        monitor._sample_cpu()  # Fresh 200ms delta.
    assert monitor._cpu_samples[0].overall_pct == 45
    assert telemetry.CPU_THREAD_WINDOW_SOURCE in monitor._sources
