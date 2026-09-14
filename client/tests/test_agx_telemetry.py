import copy
import plistlib
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from client import hardware_monitor as hm

FIXTURE = (Path(__file__).parent / "fixtures" / "agx-m4-pro.plist").read_bytes()


class AgxTelemetryTests(unittest.TestCase):
    def monitor(self):
        with mock.patch.object(hm, "_DARWIN", True), mock.patch(
            "client.identity.selected_device",
            return_value={"deviceId": "videotoolbox:system", "model": "Apple M4 Pro"},
        ):
            return hm.HardwareMonitor(encoder_name="h264_videotoolbox")

    def test_actual_narrow_fixture_and_valid_zero_high_load(self):
        self.assertEqual(hm.parse_agx_system_utilization(FIXTURE, "Apple M4 Pro"), 56)
        for value in [0, 99.5, 100]:
            rows = plistlib.loads(FIXTURE)
            rows[0]["PerformanceStatistics"]["Device Utilization %"] = value
            self.assertEqual(hm.parse_agx_system_utilization(plistlib.dumps(rows), "Apple M4 Pro"), value)

    def test_ambiguous_mismatched_missing_and_malformed_remain_unknown(self):
        original = plistlib.loads(FIXTURE)
        bad = [b'<?xml version="1.0"?><plist><broken>', b"garbage", plistlib.dumps([]), plistlib.dumps(original * 2), plistlib.dumps({"adapter": original[0]})]
        for key in ["model", "IOObjectClass", "PerformanceStatistics"]:
            rows = copy.deepcopy(original)
            del rows[0][key]
            bad.append(plistlib.dumps(rows))
        for value in [-1, 101, float("nan"), float("inf"), True, "0"]:
            rows = copy.deepcopy(original)
            rows[0]["PerformanceStatistics"]["Device Utilization %"] = value
            bad.append(plistlib.dumps(rows))
        for raw in bad:
            with self.subTest(raw=raw[:40]):
                self.assertIsNone(hm.parse_agx_system_utilization(raw, "Apple M4 Pro"))
        for expected in [None, "unknown", "Apple M3 Pro"]:
            self.assertIsNone(hm.parse_agx_system_utilization(FIXTURE, expected))
        self.assertIsNone(hm.parse_agx_system_utilization(b"x" * (hm._AGX_OUTPUT_LIMIT + 1), "Apple M4 Pro"))

    def test_collector_attribution_and_source_do_not_invent_temperature(self):
        monitor = self.monitor()
        with mock.patch.object(hm, "_read_agx_ioreg", return_value=FIXTURE):
            monitor._sample_agx_system_gpu()
        with mock.patch.object(hm, "_DARWIN", True):
            monitor._sample_gpu_fast()
        metrics = monitor._aggregate()
        self.assertNotIn("gpu_unavailable", metrics.telemetry_missing or "")
        self.assertEqual(metrics.gpu_util_avg, 56)
        self.assertEqual(metrics.gpu_sample_count, 1)
        self.assertEqual(metrics.gpu_util_sample_count, 1)
        self.assertIsNone(metrics.gpu_temp_max_c)
        self.assertIn(hm.AGX_SYSTEM_GPU_SOURCE, metrics.telemetry_sources)
        monitor._agx_expected_model = None
        with mock.patch.object(hm, "_read_agx_ioreg") as read:
            monitor._sample_agx_system_gpu()
            read.assert_not_called()
        self.assertIn("gpu_ioreg_agx_unattributed", monitor._missing)

    def test_timeout_and_missing_data_use_existing_failure_backoff(self):
        monitor = self.monitor()
        collector = hm._Collector("agx_system_gpu", .5, monitor._sample_agx_system_gpu)
        with mock.patch.object(hm, "_read_agx_ioreg", side_effect=subprocess.TimeoutExpired("ioreg", 1)):
            monitor._run_collector(collector, 10)
        self.assertGreater(collector.backoff_until_s, 10)
        self.assertIn("collector_timeout_agx_system_gpu", monitor._missing)
        with mock.patch.object(hm, "_read_agx_ioreg", return_value=b"garbage"):
            monitor._run_collector(collector, 12)
        self.assertIn("gpu_ioreg_agx_unavailable", monitor._missing)
        self.assertEqual(monitor._aggregate().gpu_util_sample_count, 0)
        self.assertIsNone(monitor._aggregate().gpu_util_avg)

    def test_temperature_and_invalid_utilization_do_not_establish_load_observation(self):
        monitor = self.monitor()
        monitor._gpu_samples = [hm._GpuSample(temp_c=60), hm._GpuSample(util_pct=float("nan")), hm._GpuSample(util_pct=101)]
        metrics = monitor._aggregate()
        self.assertEqual(metrics.gpu_sample_count, 3)
        self.assertEqual(metrics.gpu_util_sample_count, 0)
        self.assertIsNone(metrics.gpu_util_avg)
        self.assertEqual(metrics.gpu_temp_max_c, 60)
        self.assertIn("gpu_utilization_unavailable", metrics.telemetry_missing)

    def test_non_videotoolbox_and_unknown_device_do_not_claim_agx(self):
        with mock.patch.object(hm, "_DARWIN", True), mock.patch("client.identity.selected_device", return_value={"deviceId": "unknown", "model": "Apple M4 Pro"}):
            monitor = hm.HardwareMonitor(encoder_name="h264_videotoolbox")
            self.assertIsNone(monitor._agx_expected_model)
            software = hm.HardwareMonitor(encoder_name="libx264")
            software._build_collectors()
            self.assertNotIn("agx_system_gpu", [c.name for c in software._collectors])

    def test_snapshot_trust_uses_valid_utilization_count_and_preserves_high_load_gate(self):
        from client import main, protocol
        hardware = main.HardwareInfo("Apple M4 Pro", "Apple M4 Pro", 24, "macOS")
        for samples, expected_trust in [([hm._GpuSample(temp_c=60)], False),
                                       ([hm._GpuSample(util_pct=0)], True),
                                       ([hm._GpuSample(util_pct=80)], True)]:
            monitor = self.monitor()
            monitor._gpu_samples = samples
            monitor._cpu_samples = [hm._CpuSample(overall_pct=1)]
            metrics = monitor._aggregate()
            with mock.patch.object(main, "HardwareMonitor") as factory, mock.patch.object(main.time, "sleep"), mock.patch.object(main, "selected_device", return_value={"deviceId": "videotoolbox:system"}):
                factory.return_value.stop.return_value = metrics
                snapshot = main._capture_protocol_environment_snapshot(hardware=hardware, encoder="h264_videotoolbox")
            self.assertEqual(snapshot.gpu_load_trustworthy, expected_trust)
            self.assertEqual(snapshot.gpu_sample_count, 1 if expected_trust else 0)
            self.assertEqual(metrics.gpu_sample_count, 1)
            if expected_trust and metrics.gpu_util_avg == 80:
                result = protocol.validate_environment(snapshot, protocol.EnvironmentThresholds())
                self.assertIn("background-gpu-high", [reason.code for reason in result.reasons])

    @unittest.skipIf(sys.platform == "win32", "AGX uses POSIX pipes on macOS")
    def test_bounded_reader_reaps_timeout_and_excess_output(self):
        for script, error in [("import time;time.sleep(10)", subprocess.TimeoutExpired), ("import sys;sys.stdout.write('x'*300000);sys.stdout.flush()", ValueError)]:
            with self.subTest(error=error), mock.patch.object(hm, "_AGX_COMMAND", [sys.executable, "-c", script]), mock.patch.object(hm.subprocess, "Popen", wraps=subprocess.Popen) as spawn:
                began = time.monotonic()
                with self.assertRaises(error):
                    hm._read_agx_ioreg()
                self.assertLess(time.monotonic() - began, 3)
                self.assertEqual(spawn.call_count, 1)


if __name__ == "__main__":
    unittest.main()
