"""Real psutil delta calculation with deterministic OS counters and a reused thread key."""
import threading
from unittest import mock

import psutil
import pytest
from client import hardware_monitor as telemetry


@pytest.mark.parametrize('fresh_percent', [0.0, 50.0])
def test_sampler_excludes_old_thread_work_but_retains_fresh_background(fresh_percent):
    cpu_tuple = type(psutil.cpu_times())
    def counters(user, idle):
        return cpu_tuple(**{key: user if key == 'user' else idle if key == 'idle' else 0.0 for key in cpu_tuple._fields})
    # Historical work between the old thread lifetime and this invocation yields
    # 400/(400+500)=44.4%, despite zero fresh work in the quiet case.
    historical = counters(0, 100)
    current = [counters(400, 600)]
    clock = [10.0]
    observed_calls = []
    errors = []
    monitor = telemetry.HardwareMonitor(interval=0.1, encoder_name='libx264')
    actual_cpu_percent = psutil.cpu_percent
    sample = monitor._sample_cpu
    def take_one_sample():
        sample()
        if monitor._cpu_samples:
            monitor._stop_event.set()
    monitor._collectors = [telemetry._Collector('cpu_psutil', 0.5, take_one_sample)]
    def wait(seconds):
        clock[0] += seconds
        current[0] = counters(400 + fresh_percent, 600 + 100 - fresh_percent)
        return monitor._stop_event.is_set()
    def read_cpu_times():
        observed_calls.append(threading.get_ident())
        return current[0]
    def run_sampler():
        try:
            # Deterministically reproduce a recycled thread ID in real psutil's
            # installed map; no private psutil mutation exists in production code.
            psutil._last_cpu_times[threading.get_ident()] = historical
            monitor._sample_loop()
        except BaseException as error:
            errors.append(error)
    with mock.patch.dict(psutil._last_cpu_times, {}, clear=True), \
         mock.patch.object(psutil, 'cpu_times', side_effect=read_cpu_times), \
         mock.patch.object(psutil, 'cpu_freq', return_value=None), \
         mock.patch.object(psutil, 'sensors_temperatures', return_value={}, create=True), \
         mock.patch.object(telemetry.time, 'monotonic', side_effect=lambda: clock[0]), \
         mock.patch.object(monitor._stop_event, 'wait', side_effect=wait):
        actual_cpu_percent(interval=None)  # This caller-thread prime did not fix the sampler.
        caller = threading.get_ident()
        thread = threading.Thread(target=run_sampler)
        thread.start()
        thread.join(timeout=2)
        if thread.is_alive():
            monitor._stop_event.set()
            thread.join(timeout=2)
            raise AssertionError('sampler did not finish')
    assert not errors
    assert len(monitor._cpu_samples) == 1
    assert monitor._cpu_samples[0].overall_pct == fresh_percent
    assert monitor._aggregate().cpu_util_avg == fresh_percent
    assert len(set(observed_calls) - {caller}) == 1


def test_failed_prime_discards_first_success_instead_of_retaining_stale_history():
    monitor = telemetry.HardwareMonitor(encoder_name='libx264')
    with mock.patch.object(psutil, 'cpu_percent', side_effect=[RuntimeError('unavailable'), 88.0, 45.0]), \
         mock.patch.object(psutil, 'cpu_freq', return_value=None), \
         mock.patch.object(psutil, 'sensors_temperatures', return_value={}, create=True):
        assert monitor._read_cpu_percent() is None
        monitor._sample_cpu()
        assert monitor._cpu_samples == []
        monitor._sample_cpu()
    assert monitor._aggregate().cpu_util_avg == 45.0
    assert 'cpu_unavailable' in monitor._missing


def test_stop_before_fresh_interval_does_not_manufacture_a_zero_sample():
    monitor = telemetry.HardwareMonitor(encoder_name='libx264')
    monitor._build_collectors()
    with mock.patch.object(psutil, 'cpu_percent', return_value=99), \
         mock.patch.object(monitor._stop_event, 'wait', return_value=True) as wait:
        monitor._sample_loop()
    wait.assert_called_once_with(0.1)
    assert monitor._cpu_samples == []
    assert monitor._aggregate().cpu_util_avg is None


def test_start_primes_system_cpu_on_actual_sampler_thread_only():
    monitor = telemetry.HardwareMonitor(interval=0.1, encoder_name='libx264')
    caller = threading.get_ident()
    callers = []
    sample = monitor._sample_cpu
    def one_sample():
        sample()
        monitor._stop_event.set()
    def collectors():
        monitor._collectors = [telemetry._Collector('cpu_psutil', 0.5, one_sample)]
    def cpu_percent(**kwargs):
        callers.append(threading.get_ident())
        return 50.0
    with mock.patch.object(telemetry, 'EnergyCollector') as energy, \
         mock.patch.object(monitor, '_select_nvml_device_indexes', return_value=None), \
         mock.patch.object(monitor, '_capture_battery_snapshot'), \
         mock.patch.object(monitor, '_build_collectors', side_effect=collectors), \
         mock.patch.object(psutil, 'cpu_percent', side_effect=cpu_percent), \
         mock.patch.object(psutil, 'cpu_freq', return_value=None), \
         mock.patch.object(psutil, 'sensors_temperatures', return_value={}, create=True):
        energy.return_value.stop.return_value = []
        monitor.start()
        monitor._thread.join(timeout=2)
        metrics = monitor.stop()
    assert len(callers) == 2
    assert caller not in callers and len(set(callers)) == 1
    assert metrics.cpu_util_avg == 50.0 and metrics.cpu_sample_count == 1
