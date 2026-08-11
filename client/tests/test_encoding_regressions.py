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

        self.assertEqual(client_main.CLIENT_VERSION, "client/0.1.1")

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

    def test_hardware_fallback_reports_software_effective_preset(self) -> None:
        commands = []

        def run_monitored(cmd, **_kwargs):
            commands.append(cmd)
            output_path = cmd[-1]
            if len(commands) == 2:
                with open(output_path, "wb") as artifact:
                    artifact.write(b"encoded")
                return "", "frame= 30", 0, 1.0, HardwareMetrics()
            return "", "hardware failed", 1, 1.0, HardwareMetrics()

        with tempfile.TemporaryDirectory() as out_dir, \
                mock.patch.object(ffmpeg, "_run_monitored", side_effect=run_monitored), \
                mock.patch.object(ffmpeg, "pick_software_encoder_for_family", return_value="libx264"), \
                mock.patch.object(ffmpeg, "has_encoder", return_value=True):
            result = ffmpeg.encode_to_artifact(
                input_path="input.mp4",
                encoder="h264_nvenc",
                preset="p1",
                crf=24,
                out_dir=out_dir,
                artifact_name="output.mp4",
            )

        self.assertEqual(result["encoderRequested"], "h264_nvenc")
        self.assertEqual(result["encoderUsed"], "libx264")
        self.assertEqual(result["presetRequested"], "p1")
        self.assertEqual(result["presetUsed"], "medium")
        self.assertIn("medium", commands[1])

    def test_single_payload_uses_effective_fallback_preset(self) -> None:
        hardware = config.HardwareInfo("CPU", "GPU", 16, "Test OS")
        info = {
            "artifactPath": "unused.mp4",
            "encoderUsed": "libx264",
            "presetUsed": "medium",
            "elapsedMs": 1000,
            "fps": 30.0,
            "fileSizeBytes": 100,
            "error": None,
        }
        with mock.patch.object(ffmpeg, "encode_to_artifact", return_value=info), \
                mock.patch.object(ffmpeg, "compute_vmaf", return_value=None), \
                mock.patch.object(ffmpeg, "compute_ssim", return_value=None), \
                mock.patch.object(ffmpeg, "compute_psnr", return_value=None):
            payload = ffmpeg.run_single_benchmark(
                hardware, "input.mp4", preset="p1", codec="h264_nvenc", crf=24
            )

        self.assertEqual(payload["codec"], "libx264")
        self.assertEqual(payload["preset"], "medium")

    def test_videotoolbox_command_does_not_allow_software(self) -> None:
        cmd = ffmpeg.build_ffmpeg_encode_cmd(
            input_path="input.mp4",
            output_path="output.mp4",
            encoder="h264_videotoolbox",
            preset_name="default",
            crf=24,
        )
        self.assertNotIn("-allow_sw", cmd)
        self.assertNotIn("allow_sw", " ".join(cmd))


if __name__ == "__main__":
    unittest.main()
