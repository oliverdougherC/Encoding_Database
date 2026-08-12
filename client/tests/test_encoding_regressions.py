import os
import tempfile
import unittest
from unittest import mock

from client import config
from client import ffmpeg
from client.encoders import map_preset_for_encoder, sort_presets_by_speed_desc
from client.hardware_monitor import HardwareMetrics
from client import suite


class EncodingRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        ffmpeg._VIDEO_PROBE_CACHE.clear()
        ffmpeg._VMAF_MODEL_CONTEXT_CACHE = None

    def test_corrected_metrics_use_distinguishable_client_version(self) -> None:
        from client import main as client_main

        self.assertEqual(client_main.CLIENT_VERSION, "client/0.2.0")

    def test_vmaf_passes_distorted_input_before_reference(self) -> None:
        completed = mock.Mock(stdout='{"VMAF_score": 88.5}')
        with mock.patch.object(ffmpeg, "_vmaf_filter_candidates", return_value=[{
            "filter": "libvmaf=model='path=/tmp/test-vmaf.json':log_fmt=json:log_path=-",
            "metricModelId": "vmaf-v1-sdr-1080p",
        }]), \
                mock.patch.object(ffmpeg.subprocess, "run", return_value=completed) as run_mock:
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
            "unused.mp4": {
                "sourceFps": 30.0,
                "sourceDurationSeconds": 60.0,
                "videoBitrateBps": 4_000_000,
                "videoPayloadBytes": 30_000_000,
                "containerBytes": 30_750_000,
                "ffprobeStreamBitrateBps": 4_100_000,
            },
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
                hardware,
                "input.mp4",
                preset="p1",
                codec="h264_nvenc",
                crf=24,
                source_suite_version=suite.SUITE_VERSION,
                workload_id=suite.DEFAULT_QUICK_CLIP_ID,
                content_class="action",
            )

        self.assertEqual(payload["codec"], "h264_nvenc")
        self.assertEqual(payload["preset"], "p1")
        self.assertEqual(payload["vmaf"], 94.2)
        self.assertEqual(payload["vmafMean"], 94.2)
        self.assertEqual(payload["vmafP5"], 88.1)
        self.assertEqual(payload["sourceFps"], 29.97)
        self.assertEqual(payload["sourceDurationSeconds"], 60.0)
        self.assertEqual(payload["videoBitrateBps"], 4_000_000)
        self.assertEqual(payload["scoreFormulaVersion"], "7.0")
        self.assertEqual(payload["benchmarkProtocolVersion"], "7.0")
        self.assertEqual(payload["sourceSuiteVersion"], suite.SUITE_VERSION)
        self.assertEqual(payload["workloadId"], suite.DEFAULT_QUICK_CLIP_ID)
        self.assertEqual(payload["contentClass"], "action")
        self.assertEqual(payload["metricModelId"], "vmaf-v1-sdr-1080p")
        self.assertIn("not General PL", payload["scoreEligibilityNote"])
        self.assertIn("bitrate_meta=", payload["notes"])
        self.assertIn("\"videoPayloadBytes\":30000000", payload["notes"])
        self.assertIn("\"containerBytes\":30750000", payload["notes"])
        self.assertIn("\"ffprobeStreamBitrateBps\":4100000.0", payload["notes"])

    def test_single_payload_drops_score_contract_when_payload_bitrate_cannot_be_derived(self) -> None:
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
            "unused.mp4": {
                "sourceFps": 30.0,
                "sourceDurationSeconds": 60.0,
                "videoBitrateBps": None,
                "containerBytes": 100,
                "ffprobeStreamBitrateBps": 4_250_000,
            },
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
                hardware,
                "input.mp4",
                preset="p1",
                codec="h264_nvenc",
                crf=24,
                source_suite_version=suite.SUITE_VERSION,
                workload_id=suite.DEFAULT_QUICK_CLIP_ID,
                content_class="action",
            )

        self.assertIsNone(payload["videoBitrateBps"])
        self.assertNotIn("scoreFormulaVersion", payload)
        self.assertIn("not score-eligible", payload["scoreEligibilityNote"])
        self.assertIn("\"containerBytes\":100", payload["notes"])
        self.assertIn("\"ffprobeStreamBitrateBps\":4250000.0", payload["notes"])

    def test_single_payload_keeps_energy_and_decode_evidence_outside_score_inputs(self) -> None:
        hardware = config.HardwareInfo("CPU", "GPU", 16, "Test OS")
        info = {
            "artifactPath": "unused.mp4",
            "encoderUsed": "h264_nvenc",
            "presetUsed": "p1",
            "elapsedMs": 1000,
            "fps": 30.0,
            "fileSizeBytes": 100,
            "error": None,
            "frameCount": 120,
            "energyDomains": [
                {
                    "domain": "gpu-board:0",
                    "domainType": "gpu-board",
                    "source": "nvml-total-energy",
                    "collectorVersion": "pynvml",
                    "counterUnit": "millijoule",
                    "startCounter": 10.0,
                    "endCounter": 1010.0,
                    "deltaJoules": 1.0,
                    "counterState": "ok",
                    "reason": None,
                }
            ],
        }
        probe_data = {
            "input.mp4": {"sourceFps": 30.0, "sourceDurationSeconds": 60.0, "videoBitrateBps": 17_600_000},
            "unused.mp4": {
                "sourceFps": 30.0,
                "sourceDurationSeconds": 60.0,
                "videoBitrateBps": 4_000_000,
                "videoPayloadBytes": 30_000_000,
                "containerBytes": 30_750_000,
                "ffprobeStreamBitrateBps": 4_100_000,
            },
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
                mock.patch.object(
                    ffmpeg,
                    "run_decode_benchmark",
                    return_value={
                        "supported": True,
                        "tool": "ffmpeg",
                        "decoder": "software-default",
                        "methodology": "ffmpeg-software-decode-v1",
                        "decodeFps": 60.0,
                        "realtimeMultiple": 2.0,
                        "cpuTimeSeconds": 1.5,
                    },
                ), \
                mock.patch.object(ffmpeg, "probe_video_stream_metrics", side_effect=lambda path: probe_data[path]):
            payload = ffmpeg.run_single_benchmark(
                hardware,
                "input.mp4",
                preset="p1",
                codec="h264_nvenc",
                crf=24,
                source_suite_version=suite.SUITE_VERSION,
                workload_id=suite.DEFAULT_QUICK_CLIP_ID,
                content_class="action",
            )

        self.assertNotIn("energyDomains", payload)
        self.assertNotIn("decodeBenchmark", payload)
        self.assertIn("energy={", payload["notes"])
        self.assertIn("\"joulesPerFrame\":0.008333333", payload["notes"])
        self.assertIn("\"joulesPerSourceSecond\":0.016666667", payload["notes"])
        self.assertIn("decode_benchmark={", payload["notes"])
        self.assertIn("\"decodeFps\":60.0", payload["notes"])
        self.assertEqual(payload["scoreFormulaVersion"], "7.0")

    def test_probe_video_stream_metrics_uses_video_packet_bytes_instead_of_container_overhead(self) -> None:
        metadata = mock.Mock(stdout=ffmpeg.json.dumps({
            "streams": [{"avg_frame_rate": "30000/1001", "duration": "10.0", "bit_rate": "1000000"}],
            "format": {"duration": "10.0", "size": "1500"},
        }))
        packets = mock.Mock(stdout="100\n200\n300\n")
        with mock.patch.object(ffmpeg.subprocess, "run", side_effect=[metadata, packets]):
            probe = ffmpeg.probe_video_stream_metrics("artifact.mp4")

        self.assertAlmostEqual(probe["sourceFps"], 30000 / 1001)
        self.assertEqual(probe["videoPayloadBytes"], 600)
        self.assertEqual(probe["containerBytes"], 1500)
        self.assertEqual(probe["ffprobeStreamBitrateBps"], 1_000_000.0)
        self.assertEqual(probe["videoBitrateBps"], 480.0)

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

    def test_resolve_vmaf_model_context_uses_manifest_and_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            model_path = os.path.join(td, "vmaf_v1.0.16_3d0h.json")
            manifest_path = os.path.join(td, "manifest.json")
            model_bytes = b"{\"model\":\"fixture\"}\n"
            with open(model_path, "wb") as handle:
                handle.write(model_bytes)
            model_sha = ffmpeg.hashlib.sha256(model_bytes).hexdigest()
            with open(manifest_path, "w", encoding="utf-8") as handle:
                ffmpeg.json.dump({
                    "metricModelId": "vmaf-v1-sdr-1080p",
                    "metricModelVersion": "v1.0.16_3d0h",
                    "filename": "vmaf_v1.0.16_3d0h.json",
                    "bundleRelativePath": "resources/vmaf/vmaf_v1.0.16_3d0h.json",
                    "sha256": model_sha,
                    "analysisContextId": "libvmaf-json-distorted-first-stdout",
                    "filterOptions": {"log_fmt": "json", "log_path": "-"},
                }, handle)
            with mock.patch.object(ffmpeg, "_vmaf_manifest_path", return_value=manifest_path), \
                    mock.patch.object(config, "_resource_path", return_value=model_path):
                context = ffmpeg.resolve_vmaf_model_context(force_refresh=True)

        self.assertTrue(context["available"])
        self.assertEqual(context["metricModelId"], "vmaf-v1-sdr-1080p")
        self.assertEqual(context["metricModelVersion"], "v1.0.16_3d0h")
        self.assertEqual(context["modelPath"], model_path)
        self.assertEqual(context["modelSha256"], model_sha)
        self.assertEqual(context["reason"], "ok")
        self.assertIn("libvmaf=model='path=", context["filter"])

    def test_resolve_vmaf_model_context_reports_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            model_path = os.path.join(td, "vmaf_v1.0.16_3d0h.json")
            manifest_path = os.path.join(td, "manifest.json")
            with open(model_path, "w", encoding="utf-8") as handle:
                handle.write("{\"model\":\"fixture\"}\n")
            with open(manifest_path, "w", encoding="utf-8") as handle:
                ffmpeg.json.dump({
                    "metricModelId": "vmaf-v1-sdr-1080p",
                    "metricModelVersion": "v1.0.16_3d0h",
                    "filename": "vmaf_v1.0.16_3d0h.json",
                    "bundleRelativePath": "resources/vmaf/vmaf_v1.0.16_3d0h.json",
                    "sha256": "deadbeef",
                    "analysisContextId": "libvmaf-json-distorted-first-stdout",
                    "filterOptions": {"log_fmt": "json", "log_path": "-"},
                }, handle)
            with mock.patch.object(ffmpeg, "_vmaf_manifest_path", return_value=manifest_path), \
                    mock.patch.object(config, "_resource_path", return_value=model_path):
                context = ffmpeg.resolve_vmaf_model_context(force_refresh=True)

        self.assertFalse(context["available"])
        self.assertEqual(context["reason"], "checksum-mismatch")
        self.assertEqual(context["expectedSha256"], "deadbeef")
        self.assertIsNotNone(context["modelSha256"])

    def test_hardware_command_uses_explicit_native_bitrate_and_output_contract(self) -> None:
        cmd = ffmpeg.build_ffmpeg_encode_cmd(
            input_path="input.mp4",
            output_path="output.mp4",
            encoder="h264_videotoolbox",
            preset_name="default",
            rate_control={"mode": "vbr", "targetBitrateKbps": 5000},
        )
        self.assertNotIn("-allow_sw", cmd)
        self.assertNotIn("allow_sw", " ".join(cmd))
        self.assertIn("-pix_fmt", cmd)
        self.assertIn("yuv420p", cmd)
        self.assertIn("5000k", cmd)
        self.assertIn("-progress", cmd)
        self.assertIn("pipe:1", cmd)
        self.assertIn("-nostats", cmd)

    def test_sanitize_payload_for_server_preserves_complete_evidence(self) -> None:
        payload = config.sanitize_payload_for_server({
            "scoreFormulaVersion": "7.0",
            "benchmarkProtocolVersion": "7.0",
            "sourceSuiteVersion": suite.SUITE_VERSION,
            "workloadId": suite.DEFAULT_QUICK_CLIP_ID,
            "metricModelId": "vmaf-v1-sdr-1080p",
            "vmafMean": 94.0,
            "vmafP5": 88.0,
            "sourceFps": 30.0,
            "sourceDurationSeconds": 60.0,
            "videoBitrateBps": 4_000_000,
        })
        self.assertEqual(payload["scoreFormulaVersion"], "7.0")
        self.assertEqual(payload["benchmarkProtocolVersion"], "7.0")
        self.assertEqual(payload["sourceSuiteVersion"], suite.SUITE_VERSION)
        self.assertEqual(payload["workloadId"], suite.DEFAULT_QUICK_CLIP_ID)
        self.assertEqual(payload["metricModelId"], "vmaf-v1-sdr-1080p")
        self.assertEqual(payload["vmafMean"], 94.0)
        self.assertEqual(payload["vmafP5"], 88.0)
        self.assertEqual(payload["sourceFps"], 30.0)
        self.assertEqual(payload["sourceDurationSeconds"], 60.0)
        self.assertEqual(payload["videoBitrateBps"], 4_000_000)


if __name__ == "__main__":
    unittest.main()
