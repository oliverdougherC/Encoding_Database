import json
import unittest

from client.ffmpeg import build_telemetry_notes
from client.hardware_monitor import (
    HardwareMonitor,
    _BatterySample,
    _CpuSample,
    _GpuSample,
    _ProcSample,
    infer_gpu_vendor_for_encoder,
    parse_pmset_battery_output,
    parse_windows_gpu_counter_output,
)


class TelemetryMonitorTests(unittest.TestCase):
    def test_infer_gpu_vendor_for_encoder(self) -> None:
        self.assertEqual(infer_gpu_vendor_for_encoder("h264_nvenc"), "nvidia")
        self.assertEqual(infer_gpu_vendor_for_encoder("hevc_qsv"), "intel")
        self.assertEqual(infer_gpu_vendor_for_encoder("av1_amf"), "amd")
        self.assertEqual(infer_gpu_vendor_for_encoder("h264_videotoolbox"), "apple")
        self.assertIsNone(infer_gpu_vendor_for_encoder("libx264"))

    def test_parse_pmset_battery_output(self) -> None:
        percent, source = parse_pmset_battery_output(
            "Now drawing from 'AC Power'\n -InternalBattery-0\t85%; charging; 0:59 remaining present: true"
        )
        self.assertEqual(percent, 85.0)
        self.assertEqual(source, "ac")

    def test_parse_windows_gpu_counter_output(self) -> None:
        payload = json.dumps([
            {
                "Path": r"\\HOST\\GPU Engine(pid_100_luid_0x0_0x0_engtype_3D)\\Utilization Percentage",
                "CookedValue": 24.5,
            },
            {
                "Path": r"\\HOST\\GPU Engine(pid_100_luid_0x0_0x0_engtype_Copy)\\Utilization Percentage",
                "CookedValue": 12.0,
            },
            {
                "Path": r"\\HOST\\GPU Adapter Memory(_Total)\\Dedicated Usage",
                "CookedValue": 268435456,
            },
        ])
        parsed = parse_windows_gpu_counter_output(payload)
        self.assertEqual(parsed["util_pct"], 36.5)
        self.assertEqual(parsed["mem_used_mb"], 256.0)

    def test_aggregate_uses_monotonic_duration_and_counts(self) -> None:
        monitor = HardwareMonitor(ffmpeg_pid=None, encoder_name="h264_nvenc", host_gpu_vendors=["nvidia"])
        monitor._start_mono = 10.0
        monitor._end_mono = 12.5
        monitor._battery_start_pct = 90.0
        monitor._battery_end_pct = 88.0
        monitor._power_source = "battery"
        monitor._gpu_samples = [_GpuSample(util_pct=50.0, power_w=80.0, mem_used_mb=512.0, temp_c=70.0)]
        monitor._cpu_samples = [_CpuSample(overall_pct=42.0, freq_mhz=3500.0, temp_c=71.0)]
        monitor._proc_samples = [_ProcSample(cpu_pct=180.0)]
        monitor._battery_samples = [
            _BatterySample(percent=90.0, power_source="battery"),
            _BatterySample(percent=88.0, power_source="battery"),
        ]
        monitor._sources.update({"cpu_psutil", "gpu_nvml", "ffmpeg_psutil", "battery_psutil"})

        metrics = monitor._aggregate()

        self.assertEqual(metrics.monitor_duration_ms, 2500)
        self.assertEqual(metrics.cpu_sample_count, 1)
        self.assertEqual(metrics.gpu_sample_count, 1)
        self.assertEqual(metrics.ffmpeg_sample_count, 1)
        self.assertEqual(metrics.battery_sample_count, 2)
        self.assertEqual(metrics.sample_count, 2)
        self.assertIsNotNone(metrics.telemetry_sources)
        self.assertIn("cpu_psutil", metrics.telemetry_sources or "")
        self.assertIn("gpu_nvml", metrics.telemetry_sources or "")

    def test_software_encode_disables_ambiguous_gpu_collection(self) -> None:
        monitor = HardwareMonitor(ffmpeg_pid=None, encoder_name="libx264", host_gpu_vendors=["intel", "nvidia"])
        self.assertFalse(monitor._allow_gpu_collection)
        self.assertIn("gpu_ambiguous", monitor._missing)


class TelemetryNoteTests(unittest.TestCase):
    def test_build_telemetry_notes_emits_valid_json(self) -> None:
        notes = build_telemetry_notes(
            {"gpuUtilAvg": 62.1, "cpuSampleCount": 14},
            {"telemetrySources": "cpu_psutil,gpu_nvml", "telemetryMissing": "battery_unavailable"},
        )
        self.assertGreaterEqual(len(notes), 1)
        for note in notes:
            prefix, blob = note.split("=", 1)
            self.assertIn(prefix, {"telemetry", "telemetry_meta"})
            self.assertIsInstance(json.loads(blob), dict)

    def test_build_telemetry_notes_drops_low_priority_meta(self) -> None:
        notes = build_telemetry_notes(
            {"sampleCount": 12},
            {
                "telemetrySources": ",".join([f"source_{idx}" for idx in range(40)]),
                "telemetryMissing": "gpu_ambiguous",
            },
            max_len=120,
        )
        self.assertEqual(len(notes), 2)
        self.assertTrue(notes[0].startswith("telemetry="))
        self.assertEqual(json.loads(notes[1].split("=", 1)[1]), {"telemetryMissing": "gpu_ambiguous"})


if __name__ == "__main__":
    unittest.main()
