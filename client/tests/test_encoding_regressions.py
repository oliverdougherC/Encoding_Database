import tempfile
import unittest
from unittest import mock

from client import config
from client import ffmpeg
from client.encoders import map_preset_for_encoder, sort_presets_by_speed_desc
from client.hardware_monitor import HardwareMetrics


class EncodingRegressionTests(unittest.TestCase):
    def test_corrected_metrics_use_distinguishable_client_version(self) -> None:
        from client import main as client_main

        self.assertEqual(client_main.CLIENT_VERSION, "client/0.2.0")

    def test_vmaf_passes_distorted_input_before_reference(self) -> None:
        completed = mock.Mock(stdout='{"VMAF_score": 88.5}')
        with mock.patch.object(ffmpeg.subprocess, "run", return_value=completed) as run_mock:
            score = ffmpeg.compute_vmaf("reference.mp4", "distorted.mp4")

        self.assertEqual(score, 88.5)
        cmd = run_mock.call_args.args[0]
        input_positions = [i for i, value in enumerate(cmd) if value == "-i"]
        self.assertEqual(cmd[input_positions[0] + 1], "distorted.mp4")
        self.assertEqual(cmd[input_positions[1] + 1], "reference.mp4")

    def test_nvenc_presets_and_friendly_mapping_run_fast_to_slow(self) -> None:
        presets = [f"p{number}" for number in range(7, 0, -1)]
        self.assertEqual(
            sort_presets_by_speed_desc("h264_nvenc", presets),
            ["p1", "p2", "p3", "p4", "p5", "p6", "p7"],
        )
        labels = ["ultrafast", "veryfast", "fast", "medium", "slow", "veryslow"]
        mapped = [map_preset_for_encoder("hevc_nvenc", label)[1] for label in labels]
        self.assertEqual(mapped, ["p1", "p2", "p3", "p4", "p5", "p6"])

    def test_nvenc_batch_selection_keeps_the_fast_end(self) -> None:
        from client.main import build_batch_tasks_for_mode

        cfg = {"smallBenchmark": {"crfValues": [24]}, "mediumBenchmark": {"crfValues": [24]}}
        small = build_batch_tasks_for_mode(mode="small", presets_cfg=cfg, encoders=["h264_nvenc"])
        medium = build_batch_tasks_for_mode(mode="medium", presets_cfg=cfg, encoders=["h264_nvenc"])

        self.assertEqual([task["preset"] for task in small], ["p2", "p3", "p4"])
        self.assertEqual([task["preset"] for task in medium], ["p1", "p2", "p3", "p4", "p5", "p6"])

    def test_hardware_failure_does_not_fallback_to_software(self) -> None:
        commands = []

        def run_monitored(cmd, **_kwargs):
            commands.append(cmd)
            return "", "hardware failed", 1, 1.0, HardwareMetrics()

        with tempfile.TemporaryDirectory() as out_dir, \
                mock.patch.object(ffmpeg, "_run_monitored", side_effect=run_monitored):
            result = ffmpeg.encode_to_artifact(
                input_path="input.mp4",
                encoder="h264_nvenc",
                preset="p1",
                crf=24,
                out_dir=out_dir,
                artifact_name="output.mp4",
            )

        self.assertEqual(result["encoderRequested"], "h264_nvenc")
        self.assertEqual(result["encoderUsed"], "h264_nvenc")
        self.assertEqual(result["presetRequested"], "p1")
        self.assertEqual(result["presetUsed"], "p1")
        self.assertEqual(len(commands), 1)
        self.assertIsNotNone(result["error"])

    def test_single_payload_includes_v7_contract_fields(self) -> None:
        hardware = config.HardwareInfo("CPU", "GPU", 16, "Test OS")
        info = {
            "artifactPath": "unused.mp4",
            "encoderUsed": "h264_nvenc",
            "presetUsed": "p1",
            "elapsedMs": 1000,
            "fps": 30.0,
            "fileSizeBytes": 100,
            "error": None,
        }
        probe_data = {
            "input.mp4": {"sourceFps": 29.97, "sourceDurationSeconds": 60.0, "videoBitrateBps": 17_600_000},
            "unused.mp4": {"sourceFps": 30.0, "sourceDurationSeconds": 60.0, "videoBitrateBps": 4_250_000},
        }
        with mock.patch.object(ffmpeg, "encode_to_artifact", return_value=info), \
                mock.patch.object(
                    ffmpeg,
                    "compute_vmaf_metrics",
                    return_value={
                        "vmaf": 94.2,
                        "vmafMean": 94.2,
                        "vmafP5": 88.1,
                        "metricModelId": "vmaf-v1-sdr-1080p",
                    },
                ), \
                mock.patch.object(ffmpeg, "compute_ssim", return_value=None), \
                mock.patch.object(ffmpeg, "compute_psnr", return_value=None), \
                mock.patch.object(ffmpeg, "probe_video_stream_metrics", side_effect=lambda path: probe_data[path]):
            payload = ffmpeg.run_single_benchmark(
                hardware, "input.mp4", preset="p1", codec="h264_nvenc", crf=24
            )

        self.assertEqual(payload["codec"], "h264_nvenc")
        self.assertEqual(payload["preset"], "p1")
        self.assertEqual(payload["vmaf"], 94.2)
        self.assertEqual(payload["vmafMean"], 94.2)
        self.assertEqual(payload["vmafP5"], 88.1)
        self.assertEqual(payload["sourceFps"], 29.97)
        self.assertEqual(payload["sourceDurationSeconds"], 60.0)
        self.assertEqual(payload["videoBitrateBps"], 4_250_000)
        self.assertEqual(payload["scoreFormulaVersion"], "7.0")
        self.assertEqual(payload["benchmarkProtocolVersion"], "7.0")
        self.assertEqual(payload["sourceSuiteVersion"], "legacy-single-sample-v1")
        self.assertEqual(payload["workloadId"], "legacy-sample-1080p")
        self.assertEqual(payload["metricModelId"], "vmaf-v1-sdr-1080p")
        self.assertIn("not General PL", payload["scoreEligibilityNote"])

    def test_compute_vmaf_metrics_parses_distribution_output(self) -> None:
        vmaf_json = {
            "frames": [
                {"metrics": {"vmaf": 90.0}},
                {"metrics": {"vmaf": 95.0}},
                {"metrics": {"vmaf": 100.0}},
            ],
            "pooled_metrics": {"vmaf": {"mean": 95.0}},
        }
        completed = mock.Mock(stdout=f"log noise\n{ffmpeg.json.dumps(vmaf_json)}\n")
        with mock.patch.object(ffmpeg, "_vmaf_filter_candidates", return_value=[{
            "filter": "libvmaf=model='path=/tmp/vmaf_v1.json':log_fmt=json:log_path=-",
            "metricModelId": "vmaf-v1-sdr-1080p",
        }]), \
                mock.patch.object(ffmpeg.subprocess, "run", return_value=completed):
            metrics = ffmpeg.compute_vmaf_metrics("reference.mp4", "distorted.mp4")

        self.assertEqual(metrics["metricModelId"], "vmaf-v1-sdr-1080p")
        self.assertEqual(metrics["vmaf"], 95.0)
        self.assertEqual(metrics["vmafMean"], 95.0)
        self.assertAlmostEqual(metrics["vmafP5"], 90.5)

    def test_hardware_command_does_not_force_yuv420p_or_allow_software(self) -> None:
        cmd = ffmpeg.build_ffmpeg_encode_cmd(
            input_path="input.mp4",
            output_path="output.mp4",
            encoder="h264_videotoolbox",
            preset_name="default",
            crf=24,
        )
        self.assertNotIn("-allow_sw", cmd)
        self.assertNotIn("allow_sw", " ".join(cmd))
        self.assertNotIn("-pix_fmt", cmd)
        self.assertNotIn("yuv420p", " ".join(cmd))
        self.assertIn("-progress", cmd)
        self.assertIn("pipe:1", cmd)
        self.assertIn("-nostats", cmd)

    def test_sanitize_payload_for_server_keeps_v7_fields(self) -> None:
        payload = config.sanitize_payload_for_server({
            "scoreFormulaVersion": "7.0",
            "benchmarkProtocolVersion": "7.0",
            "sourceSuiteVersion": "legacy-single-sample-v1",
            "workloadId": "legacy-sample-1080p",
            "metricModelId": "vmaf-v1-sdr-1080p",
            "vmafMean": 94.0,
            "vmafP5": 88.0,
            "sourceFps": 30.0,
            "sourceDurationSeconds": 60.0,
            "videoBitrateBps": 4_000_000,
        })
        self.assertEqual(payload["scoreFormulaVersion"], "7.0")
        self.assertEqual(payload["benchmarkProtocolVersion"], "7.0")
        self.assertEqual(payload["sourceSuiteVersion"], "legacy-single-sample-v1")
        self.assertEqual(payload["workloadId"], "legacy-sample-1080p")
        self.assertEqual(payload["metricModelId"], "vmaf-v1-sdr-1080p")
        self.assertNotIn("vmafMean", payload)
        self.assertEqual(payload["vmafP5"], 88.0)
        self.assertEqual(payload["sourceFps"], 30.0)
        self.assertEqual(payload["sourceDurationSeconds"], 60.0)
        self.assertEqual(payload["videoBitrateBps"], 4_000_000)


if __name__ == "__main__":
    unittest.main()
