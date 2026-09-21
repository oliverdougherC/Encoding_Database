import hashlib
import itertools
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from unittest import mock

from client import main as client_main
from client.protocol import ArtifactProbe, EnvironmentSnapshot
from client.protocol import BenchmarkRunRecord, EncodeTiming, ProtocolConfig, ScheduledRun
from client.config import HardwareInfo
from client.suite import PreparedSuiteClip


class _DummyDashboard:
    def __init__(self, *args, **kwargs) -> None:
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def start_batch(self, *args, **kwargs) -> None:
        self.calls.append(("start_batch", args, kwargs))

    def set_description(self, *args, **kwargs) -> None:
        self.calls.append(("set_description", args, kwargs))

    def set_current_test(self, *args, **kwargs) -> None:
        self.calls.append(("set_current_test", args, kwargs))

    def update_machine_metrics(self, *args, **kwargs) -> None:
        self.calls.append(("update_machine_metrics", args, kwargs))

    def update_counters(self, *args, **kwargs) -> None:
        self.calls.append(("update_counters", args, kwargs))

    def advance_phase(self, *args, **kwargs) -> None:
        self.calls.append(("advance_phase", args, kwargs))

    def advance(self, *args, **kwargs) -> None:
        self.calls.append(("advance", args, kwargs))


class MainRoutingTests(unittest.TestCase):
    def test_runtime_environment_sampler_dependency_is_imported(self) -> None:
        self.assertEqual(client_main.HardwareMonitor.__module__, "client.hardware_monitor")

    def test_sweep_gives_videotoolbox_explicit_native_bitrates(self) -> None:
        plan = client_main.sweep_plan.plan_sweep(
            "medium", ["libx264", "h264_videotoolbox"], presets_cfg={"sweepPlans": {
                "medium": {"crfValues": [22, 26], "bitrateKbpsValues": [3000, 10000]},
            }}
        )
        vt_steps = [step for step in plan.steps if step["encoder"] == "h264_videotoolbox"]
        self.assertEqual([step["crf"] for step in vt_steps], [None, None])
        self.assertEqual([step["rateControl"] for step in vt_steps], [
            {"mode": "vbr", "targetBitrateKbps": 3000},
            {"mode": "vbr", "targetBitrateKbps": 10000},
        ])

    def test_sweep_run_binds_plan_metadata_and_probe_filtered_encoders(self) -> None:
        base_args = client_main.argparse.Namespace(
            base_url="https://example.invalid", api_key="", no_submit=True, submit=False, crf=24,
            retries=3, queue_dir="unused", menu=False, batch_size=0, use_token=False,
            max_duration_minutes=60, max_attempts=100000, max_storage_mb=2048,
        )
        captured = {}

        def fake_batch(**kwargs):
            captured.update(kwargs)
            return 0

        with mock.patch.object(client_main, "_preparation_preflight", return_value=0), \
                mock.patch.object(client_main, "list_all_available_encoders",
                                  return_value=["libx264", "h264_nvenc"]), \
                mock.patch.object(client_main, "is_hardware_encoder_usable", return_value=False), \
                mock.patch.object(client_main, "_prepare_sweep_clips", return_value=[self._quick_clip()]), \
                mock.patch.object(client_main, "detect_hardware",
                                  return_value=HardwareInfo("CPU", "GPU", 16, "TestOS")), \
                mock.patch.object(client_main, "run_benchmark_batch", side_effect=fake_batch):
            self.assertEqual(
                client_main.run_sweep_mode(mode="small", base_args=base_args, interactive=False), 0
            )
        self.assertEqual(captured["plan_metadata"]["sweepMode"], "small")
        self.assertEqual([task["encoder"] for task in captured["tasks"]], ["libx264"])
        self.assertFalse(any(task["encoder"] == "h264_nvenc" for task in captured["tasks"]))

    def _quick_clip(self) -> PreparedSuiteClip:
        return PreparedSuiteClip(
            suite_version="encodingdb-test-suite-v1",
            clip_id="athletic-action-1080p24-final",
            canonical_content_class="high-motion-sports",
            payload_content_class="action",
            workload_id="athletic-action-1080p24-final",
            path="quick-clip.mkv",
            input_hash="a" * 64,
            file_name="quick-clip.mkv",
        )

    def _artifact_contract(self, *, codec: str = "h264") -> ArtifactProbe:
        return ArtifactProbe(
            decodable=True,
            duration_s=5.0,
            frame_count=120,
            width=960,
            height=540,
            codec=codec,
            codec_tag="avc1" if codec == "h264" else codec,
            profile="high" if codec == "h264" else None,
            level="4.1" if codec == "h264" else None,
            pix_fmt="yuv420p",
            bit_depth=8,
            chroma_subsampling="4:2:0",
            color_range="tv",
            color_space="bt709",
            color_transfer="bt709",
            color_primaries="bt709",
            container_format="mp4",
            avg_frame_rate=24.0,
            time_base=1 / 24000.0,
            has_audio=False,
            size_bytes=1_000_000,
            truncated=False,
        )

    def _batch_args(self, queue_dir: str, *, no_submit: bool = True) -> client_main.argparse.Namespace:
        return client_main.argparse.Namespace(
            base_url="https://example.invalid",
            api_key="",
            codec="",
            presets="",
            no_submit=no_submit,
            local_metrics=True,
            crf=24,
            retries=1,
            queue_dir=queue_dir,
            menu=False,
            batch_size=0,
            use_token=False,
            pause_on_exit=False,
        )

    def test_direct_cli_intent_routes_to_run_with_args(self) -> None:
        with tempfile.TemporaryDirectory() as queue_dir:
            argv = [
                "prog",
                "--codec",
                "libx264",
                "--presets",
                "fast",
                "--no-submit",
                "--queue-dir",
                queue_dir,
            ]
            with mock.patch.object(client_main, "run_with_args", return_value=17) as run_mock, \
                    mock.patch.object(client_main, "interactive_menu_flow", return_value=99) as menu_mock, \
                    mock.patch.object(client_main, "run_windows_gui_flow", return_value=88) as gui_mock:
                rc = client_main.main(argv)

        self.assertEqual(rc, 17)
        run_mock.assert_called_once()
        menu_mock.assert_not_called()
        gui_mock.assert_not_called()

    def test_submit_flag_routes_direct_cli_when_run_settings_come_from_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as queue_dir:
            argv = ["prog", "--submit", "--queue-dir", queue_dir]
            with mock.patch.object(client_main, "ENV_CODEC", "libx264"), \
                    mock.patch.object(client_main, "ENV_PRESETS", "fast"), \
                    mock.patch.object(client_main, "ENV_QUEUE_DIR", queue_dir), \
                    mock.patch.object(client_main, "run_with_args", return_value=17) as run_mock, \
                    mock.patch.object(client_main, "interactive_menu_flow", return_value=99) as menu_mock, \
                    mock.patch.object(client_main, "run_windows_gui_flow", return_value=88) as gui_mock:
                rc = client_main.main(argv)

        self.assertEqual(rc, 17)
        run_mock.assert_called_once()
        menu_mock.assert_not_called()
        gui_mock.assert_not_called()
        self.assertFalse(run_mock.call_args.kwargs["interactive"])

    def test_noninteractive_submission_policy_defaults_to_dry_run_without_submit_flag(self) -> None:
        args = client_main.argparse.Namespace(no_submit=False, submit=False, queue_dir="/tmp/queue")
        updated = client_main._apply_submission_policy(args, interactive=False)
        self.assertTrue(updated.no_submit)
        self.assertFalse(updated.submit)

    def test_noninteractive_submission_policy_preserves_submit_flag(self) -> None:
        args = client_main.argparse.Namespace(no_submit=False, submit=True, queue_dir="/tmp/queue")
        updated = client_main._apply_submission_policy(args, interactive=False)
        self.assertFalse(updated.no_submit)
        self.assertTrue(updated.submit)

    def test_interactive_publication_consent_persists_after_first_accept(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            consent_path = os.path.join(state_dir, client_main.PUBLICATION_CONSENT_FILENAME)
            with mock.patch.object(client_main.config, "default_client_state_dir", return_value=state_dir), \
                    mock.patch.object(client_main, "prompt_yes_no", return_value=True) as prompt_mock:
                self.assertTrue(client_main._ensure_interactive_publication_consent(queue_dir="/tmp/queue"))
                self.assertTrue(os.path.exists(consent_path))
                self.assertTrue(client_main._ensure_interactive_publication_consent(queue_dir="/tmp/queue"))
        prompt_mock.assert_called_once()

    def test_interactive_publication_decline_switches_to_dry_run(self) -> None:
        args = client_main.argparse.Namespace(no_submit=False, submit=False, queue_dir="/tmp/queue")
        with mock.patch.object(client_main, "_ensure_interactive_publication_consent", return_value=False):
            updated = client_main._apply_submission_policy(args, interactive=True)
        self.assertTrue(updated.no_submit)

    def test_queue_status_command_exits_without_running_benchmark(self) -> None:
        with tempfile.TemporaryDirectory() as queue_dir:
            with mock.patch.object(client_main, "run_with_args", return_value=17) as run_mock:
                rc = client_main.main(["prog", "--queue-status", "--queue-dir", queue_dir])
        self.assertEqual(rc, 0)
        run_mock.assert_not_called()

    def test_authoritative_run_create_carries_canonical_energy_and_decode_evidence(self) -> None:
        record = BenchmarkRunRecord(
            schedule=ScheduledRun("campaign-a", "recipe-a", "measured", 0, 0),
            timing=EncodeTiming(
                start_monotonic_ns=0,
                end_monotonic_ns=2_000_000_000,
                elapsed_s=2.0,
                source_frame_count=120,
                encoded_frame_count=120,
                source_fps=24.0,
                encode_fps=60.0,
                realtime_multiple=2.5,
                ffmpeg_cpu_time_s=1.0,
            ),
        )
        payload = client_main._build_authoritative_run_create_request(
            prepared_clip=self._quick_clip(),
            recipe_id="recipe-a",
            record=record,
            info={
                "recipeFingerprint": "1" * 64,
                "requestedRecipeJson": "{}",
                "effectiveRecipeJson": "{}",
                "artifactSha256": "2" * 64,
                "fileSizeBytes": 1000,
                "energyDomains": [{
                    "domain": "gpu-board:0",
                    "domainType": "gpu-board",
                    "source": "nvml-total-energy",
                    "collectorVersion": "pynvml",
                    "counterUnit": "millijoule",
                    "startCounter": 10.0,
                    "endCounter": 1010.0,
                    "counterState": "ok",
                }],
                "decodeBenchmark": {
                    "supported": True,
                    "decoder": "software-default",
                    "methodology": "ffmpeg-software-decode-v1",
                    "cachePolicy": "single-pass-local-file-no-explicit-cache-flush",
                    "elapsedMs": 2000,
                    "decodeFps": 60.0,
                    "sourceFps": 24.0,
                    "cpuTimeSeconds": 1.5,
                },
            },
            metrics={"metricModelId": "vmaf-v1-sdr-sd", "vmafMean": 94.0, "vmafP5": 88.0},
            hardware=HardwareInfo("CPU", "GPU", 16, "TestOS"),
            source_probe={},
            artifact_probe={"containerFormat": "mp4", "videoBitrateBps": 1_000_000},
            ffmpeg_version="n7.1",
            client_version="7.0.0",
            execution_identity_payload={
                "environmentFingerprint": "3" * 64,
                "environmentJson": "{\"cpuArchitecture\":\"x86_64\",\"physicalMemoryBytes\":17179869184,\"osName\":\"TestOS\",\"osVersion\":\"1\",\"ffmpegBuildFingerprint\":\"f\",\"ffmpegVersion\":\"n7.1\",\"clientVersion\":\"7.0.0\"}",
            },
            protocol_config=ProtocolConfig.for_version("7.0"),
        )

        self.assertEqual(payload["energyDomains"][0]["domain"], "gpu-board")
        self.assertEqual(payload["energyDomains"][0]["counterUnit"], "millijoules")
        self.assertEqual(payload["energyDomains"][0]["counterState"], "valid")
        self.assertEqual(payload["decodeBenchmark"]["status"], "complete")
        self.assertEqual(payload["decodeBenchmark"]["executionMode"], "software")
        self.assertEqual(payload["decodeBenchmark"]["cpuTimeMs"], 1500.0)
        self.assertEqual(
            set(payload["testClip"]),
            {"suiteId", "suiteVersion", "clipKey", "workloadId", "sha256"},
        )
        self.assertNotIn("manifestVersion", payload["testClip"])
        self.assertNotIn("byteSize", payload["testClip"])
        recipe_canonical = json.dumps(payload["recipe"]["identity"], sort_keys=True, separators=(",", ":"))
        environment_canonical = json.dumps(payload["environment"]["identity"], sort_keys=True, separators=(",", ":"))
        self.assertEqual(payload["recipe"]["fingerprint"], hashlib.sha256(recipe_canonical.encode()).hexdigest())
        self.assertEqual(payload["environment"]["fingerprint"], hashlib.sha256(environment_canonical.encode()).hexdigest())
        self.assertNotEqual(payload["recipe"]["fingerprint"], "1" * 64)
        self.assertNotEqual(payload["environment"]["fingerprint"], "3" * 64)
        self.assertEqual(payload["environment"]["identity"]["physicalMemoryBytes"], 17179869184)

    def test_menu_flag_overrides_direct_cli_intent(self) -> None:
        with tempfile.TemporaryDirectory() as queue_dir:
            argv = [
                "prog",
                "--menu",
                "--codec",
                "libx264",
                "--queue-dir",
                queue_dir,
            ]
            with mock.patch.object(client_main, "run_with_args", return_value=17) as run_mock, \
                    mock.patch.object(client_main, "interactive_menu_flow", return_value=23) as menu_mock:
                rc = client_main.main(argv)

        self.assertEqual(rc, 23)
        menu_mock.assert_called_once()
        run_mock.assert_not_called()

    def test_v7_suite_clip_flag_routes_to_authoritative_noninteractive_mode(self) -> None:
        with tempfile.TemporaryDirectory() as queue_dir:
            argv = [
                "prog",
                "--v7-suite-clip",
                "athletic-action-1080p24-final",
                "--codec",
                "libx264",
                "--presets",
                "fast",
                "--queue-dir",
                queue_dir,
            ]
            with mock.patch.object(client_main, "run_v7_suite_clip_mode", return_value=31) as suite_mock, \
                    mock.patch.object(client_main, "run_with_args", return_value=17) as run_mock:
                rc = client_main.main(argv)

        self.assertEqual(rc, 31)
        suite_mock.assert_called_once()
        run_mock.assert_not_called()

    def test_run_with_args_rejects_unusable_hardware_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as queue_dir:
            args = client_main.argparse.Namespace(
                base_url="https://example.invalid",
                api_key="",
                codec="h264_nvenc",
                presets="fast",
                no_submit=True,
                crf=24,
                retries=1,
                queue_dir=queue_dir,
                menu=False,
                batch_size=0,
                use_token=False,
                pause_on_exit=False,
            )
            with mock.patch.object(client_main, "ensure_ffmpeg_and_ffprobe", return_value=(True, "ffmpeg version n7")), \
                    mock.patch.object(client_main, "_ensure_local_quality_stack", return_value=(True, 0)), \
                    mock.patch.object(client_main, "_prepare_quick_suite_clip", return_value=self._quick_clip()), \
                    mock.patch.object(client_main, "has_encoder", return_value=True), \
                    mock.patch.object(client_main, "is_hardware_encoder_usable", return_value=False), \
                    mock.patch.object(client_main, "run_single_benchmark") as bench_mock:
                rc = client_main.run_with_args(args)

        self.assertEqual(rc, 4)
        bench_mock.assert_not_called()

    def test_run_with_args_rejects_missing_pinned_vmaf_model(self) -> None:
        with tempfile.TemporaryDirectory() as queue_dir:
            args = client_main.argparse.Namespace(
                base_url="https://example.invalid",
                api_key="",
                codec="libx264",
                presets="fast",
                no_submit=True,
                crf=24,
                retries=1,
                queue_dir=queue_dir,
                menu=False,
                batch_size=0,
                use_token=False,
                pause_on_exit=False,
            )
            with mock.patch.object(client_main, "ensure_ffmpeg_and_ffprobe", return_value=(True, "ffmpeg version n7")), \
                    mock.patch.object(client_main, "_ensure_local_quality_stack", return_value=(False, 7)), \
                    mock.patch.object(
                        client_main,
                        "resolve_vmaf_model_context",
                        return_value={
                            "available": False,
                            "reason": "model-missing",
                            "metricModelId": "vmaf-v1-sdr-1080p",
                            "metricModelVersion": "v1.0.16_3d0h",
                            "modelPath": "/tmp/missing-vmaf.json",
                            "manifestPath": "/tmp/manifest.json",
                        },
                    ), \
                    mock.patch.object(client_main, "run_single_benchmark") as bench_mock:
                rc = client_main.run_legacy_diagnostic(args, show_end_screen=False)

        self.assertEqual(rc, 7)
        bench_mock.assert_not_called()

    def test_run_benchmark_batch_uses_protocol_repetitions_and_persists_notes(self) -> None:
        clip = self._quick_clip()
        tasks = [{"encoder": "libx264", "preset": "fast", "crf": 24, "suiteClip": clip}]
        captured_payloads = []
        event_log = []
        artifact_paths = [f"/tmp/protocol-{idx}.mp4" for idx in range(3)]

        def capture_skip(*, hardware, payload, background_cpu_pct, baseline_rows):
            captured_payloads.append(payload)
            return False, ""

        def probe_contract(path: str) -> ArtifactProbe:
            if path == clip.path:
                return self._artifact_contract(codec="h264")
            return self._artifact_contract(codec="h264")

        probe_metrics = {
            clip.path: {"sourceFps": 24.0, "sourceDurationSeconds": 5.0, "videoBitrateBps": 8_000_000},
            artifact_paths[0]: {"sourceFps": 24.0, "sourceDurationSeconds": 5.0, "videoBitrateBps": 2_000_000},
            artifact_paths[1]: {"sourceFps": 24.0, "sourceDurationSeconds": 5.0, "videoBitrateBps": 2_100_000},
            artifact_paths[2]: {"sourceFps": 24.0, "sourceDurationSeconds": 5.0, "videoBitrateBps": 2_050_000},
        }
        encode_infos = [
            {"artifactPath": artifact_paths[0], "encoderUsed": "libx264", "presetUsed": "fast", "fileSizeBytes": 1_000_000, "error": None, "encodeStartMonotonicNs": 1_000_000_000, "encodeEndMonotonicNs": 2_000_000_000},
            {"artifactPath": artifact_paths[1], "encoderUsed": "libx264", "presetUsed": "fast", "fileSizeBytes": 1_000_000, "error": None, "encodeStartMonotonicNs": 1_000_000_000, "encodeEndMonotonicNs": 2_000_000_000},
            {"artifactPath": artifact_paths[2], "encoderUsed": "libx264", "presetUsed": "fast", "fileSizeBytes": 1_000_000, "error": None, "encodeStartMonotonicNs": 1_000_000_000, "encodeEndMonotonicNs": 2_000_000_000},
        ]
        perf_ticks = itertools.count(start=0, step=1_000_000_000)

        with tempfile.TemporaryDirectory() as queue_dir:
            args = self._batch_args(queue_dir, no_submit=True)
            with mock.patch.object(client_main, "ensure_ffmpeg_and_ffprobe", return_value=(True, "ffmpeg version n7")), \
                    mock.patch.object(client_main, "_ensure_local_quality_stack", return_value=(True, 0)), \
                    mock.patch.object(client_main, "_build_protocol_config", return_value=client_main.ProtocolConfig.for_version("7.0", stability_threshold_ratio=1.0, max_adaptive_repeats=2)), \
                    mock.patch.object(client_main, "resolve_batch_size", return_value=1), \
                    mock.patch.object(client_main, "count_pending_entries", return_value=0), \
                    mock.patch.object(client_main, "BatchRunDashboard", _DummyDashboard), \
                    mock.patch.object(client_main, "print_batch_summary"), \
                    mock.patch.object(client_main, "print_info"), \
                    mock.patch.object(client_main, "print_warning"), \
                    mock.patch.object(client_main, "probe_video_stream_metrics", side_effect=lambda path: dict(probe_metrics[path])), \
                    mock.patch.object(client_main, "_probe_artifact_contract", side_effect=probe_contract), \
                    mock.patch.object(client_main, "_capture_protocol_environment_snapshot", return_value=EnvironmentSnapshot(
                        background_cpu_pct=6.0,
                        background_gpu_pct=None,
                        power_source="ac",
                        cpu_temp_c=55.0,
                        gpu_temp_c=None,
                        thermal_throttle=None,
                        free_memory_mb=8_192.0,
                        memory_pressure_pct=15.0,
                        selected_accelerator="software",
                        gpu_load_trustworthy=False,
                    )), \
                    mock.patch.object(client_main.time, "perf_counter_ns", side_effect=lambda: next(perf_ticks)), \
                    mock.patch.object(client_main, "encode_to_artifact", side_effect=encode_infos), \
                    mock.patch.object(
                        client_main,
                        "compute_metrics_parallel",
                        side_effect=lambda _input_path, outputs, _workers, quiet=True: {
                            outputs[0]: {"vmaf": 95.0, "vmafMean": 95.0, "vmafP5": 92.0, "metricModelId": "vmaf-v1-sdr-1080p"}
                        },
                    ), \
                    mock.patch.object(client_main, "sha256_of_file", return_value="a" * 64), \
                    mock.patch.object(client_main, "_build_authoritative_run_create_request", return_value={"artifact": {"sha256": "a" * 64, "byteSize": 1_000_000}}), \
                    mock.patch.object(client_main, "should_skip_submission", side_effect=capture_skip):
                rc = client_main.run_benchmark_batch(
                    hardware=client_main.HardwareInfo("CPU", "GPU", 16, "TestOS"),
                    base_url="https://example.invalid",
                    args=args,
                    tasks=tasks,
                    event_sink=event_log.append,
                )

        self.assertEqual(rc, 0)
        self.assertEqual(len(captured_payloads), 2)
        self.assertTrue(all("protocol_run=" in payload.get("notes", "") for payload in captured_payloads))
        self.assertTrue(all("protocol_timing=" in payload.get("notes", "") for payload in captured_payloads))
        self.assertTrue(all("protocol_validity=" in payload.get("notes", "") for payload in captured_payloads))
        self.assertTrue(all("protocol_env=" in payload.get("notes", "") for payload in captured_payloads))
        self.assertTrue(all("suite_meta=" in payload.get("notes", "") for payload in captured_payloads))
        dry_run_events = [event for event in event_log if event.get("type") == "submit_result" and event.get("status") == "locally_complete"]
        self.assertEqual(len(dry_run_events), 2)

    def test_run_benchmark_batch_retries_after_invalid_environment_gate(self) -> None:
        clip = self._quick_clip()
        tasks = [{"encoder": "libx264", "preset": "fast", "crf": 24, "suiteClip": clip}]
        event_log = []
        captured_payloads = []
        artifact_paths = [f"/tmp/env-invalid-{idx}.mp4" for idx in range(3)]
        snapshots = iter([
            EnvironmentSnapshot(
                background_cpu_pct=5.0,
                background_gpu_pct=None,
                power_source="ac",
                cpu_temp_c=55.0,
                gpu_temp_c=None,
                thermal_throttle=None,
                free_memory_mb=8_192.0,
                memory_pressure_pct=10.0,
                selected_accelerator="software",
                gpu_load_trustworthy=False,
            ),
            EnvironmentSnapshot(
                background_cpu_pct=90.0,
                background_gpu_pct=None,
                power_source="ac",
                cpu_temp_c=55.0,
                gpu_temp_c=None,
                thermal_throttle=None,
                free_memory_mb=8_192.0,
                memory_pressure_pct=10.0,
                selected_accelerator="software",
                gpu_load_trustworthy=False,
            ),
            EnvironmentSnapshot(
                background_cpu_pct=5.0,
                background_gpu_pct=None,
                power_source="ac",
                cpu_temp_c=55.0,
                gpu_temp_c=None,
                thermal_throttle=None,
                free_memory_mb=8_192.0,
                memory_pressure_pct=10.0,
                selected_accelerator="software",
                gpu_load_trustworthy=False,
            ),
            EnvironmentSnapshot(
                background_cpu_pct=5.0,
                background_gpu_pct=None,
                power_source="ac",
                cpu_temp_c=55.0,
                gpu_temp_c=None,
                thermal_throttle=None,
                free_memory_mb=8_192.0,
                memory_pressure_pct=10.0,
                selected_accelerator="software",
                gpu_load_trustworthy=False,
            ),
        ])
        encode_infos = [
            {"artifactPath": artifact_paths[0], "encoderUsed": "libx264", "presetUsed": "fast", "fileSizeBytes": 1_000_000, "error": None, "encodeStartMonotonicNs": 1_000_000_000, "encodeEndMonotonicNs": 2_000_000_000},
            {"artifactPath": artifact_paths[1], "encoderUsed": "libx264", "presetUsed": "fast", "fileSizeBytes": 1_000_000, "error": None, "encodeStartMonotonicNs": 1_000_000_000, "encodeEndMonotonicNs": 2_000_000_000},
            {"artifactPath": artifact_paths[2], "encoderUsed": "libx264", "presetUsed": "fast", "fileSizeBytes": 1_000_000, "error": None, "encodeStartMonotonicNs": 1_000_000_000, "encodeEndMonotonicNs": 2_000_000_000},
        ]
        probe_metrics = {
            clip.path: {"sourceFps": 24.0, "sourceDurationSeconds": 5.0, "videoBitrateBps": 8_000_000},
            artifact_paths[0]: {"sourceFps": 24.0, "sourceDurationSeconds": 5.0, "videoBitrateBps": 2_000_000},
            artifact_paths[1]: {"sourceFps": 24.0, "sourceDurationSeconds": 5.0, "videoBitrateBps": 2_050_000},
            artifact_paths[2]: {"sourceFps": 24.0, "sourceDurationSeconds": 5.0, "videoBitrateBps": 2_025_000},
        }

        def capture_skip(*, hardware, payload, background_cpu_pct, baseline_rows):
            captured_payloads.append((payload, background_cpu_pct))
            return False, ""

        with tempfile.TemporaryDirectory() as queue_dir:
            args = self._batch_args(queue_dir, no_submit=True)
            with mock.patch.object(client_main, "ensure_ffmpeg_and_ffprobe", return_value=(True, "ffmpeg version n7")), \
                    mock.patch.object(client_main, "_ensure_local_quality_stack", return_value=(True, 0)), \
                    mock.patch.object(client_main, "_build_protocol_config", return_value=client_main.ProtocolConfig.for_version("7.0", stability_threshold_ratio=1.0, max_adaptive_repeats=2)), \
                    mock.patch.object(client_main, "resolve_batch_size", return_value=1), \
                    mock.patch.object(client_main, "count_pending_entries", return_value=0), \
                    mock.patch.object(client_main, "BatchRunDashboard", _DummyDashboard), \
                    mock.patch.object(client_main, "print_batch_summary"), \
                    mock.patch.object(client_main, "print_info"), \
                    mock.patch.object(client_main, "print_warning"), \
                    mock.patch.object(client_main, "probe_video_stream_metrics", side_effect=lambda path: dict(probe_metrics[path])), \
                    mock.patch.object(client_main, "_probe_artifact_contract", side_effect=lambda path: self._artifact_contract(codec="h264")), \
                    mock.patch.object(client_main, "_capture_protocol_environment_snapshot", side_effect=lambda **kwargs: next(snapshots)), \
                    mock.patch.object(client_main, "encode_to_artifact", side_effect=encode_infos) as encode_mock, \
                    mock.patch.object(
                        client_main,
                        "compute_metrics_parallel",
                        side_effect=lambda _input_path, outputs, _workers, quiet=True: {
                            outputs[0]: {"vmaf": 95.0, "vmafMean": 95.0, "vmafP5": 92.0, "metricModelId": "vmaf-v1-sdr-1080p"}
                        },
                    ), \
                    mock.patch.object(client_main, "sha256_of_file", return_value="a" * 64), \
                    mock.patch.object(client_main, "_build_authoritative_run_create_request", return_value={"artifact": {"sha256": "a" * 64, "byteSize": 1_000_000}}), \
                    mock.patch.object(client_main, "should_skip_submission", side_effect=capture_skip):
                rc = client_main.run_benchmark_batch(
                    hardware=client_main.HardwareInfo("CPU", "GPU", 16, "TestOS"),
                    base_url="https://example.invalid",
                    args=args,
                    tasks=tasks,
                    event_sink=event_log.append,
                )

        self.assertEqual(rc, 1)
        self.assertEqual(encode_mock.call_count, 3)
        self.assertEqual(len(captured_payloads), 2)
        invalid_events = [
            event for event in event_log
            if event.get("type") == "submit_result" and event.get("status") == "protocol_invalid"
        ]
        self.assertEqual(len(invalid_events), 1)
        self.assertEqual(invalid_events[0].get("reasonCodes"), ["background-cpu-high"])
        self.assertTrue(all(background_cpu_pct == 5.0 for _, background_cpu_pct in captured_payloads))

    def test_run_benchmark_batch_submits_authoritative_artifact_bundle(self) -> None:
        clip = self._quick_clip()
        tasks = [{"encoder": "libx264", "preset": "fast", "crf": 24, "suiteClip": clip}]
        artifact_path = "/tmp/authoritative-artifact.mp4"
        captured_submission = {}

        encode_info = {
            "artifactPath": artifact_path,
            "encoderUsed": "libx264",
            "presetUsed": "fast",
            "fileSizeBytes": 1_000_000,
            "elapsedMs": 1_000,
            "encodeStartMonotonicNs": 1_000_000_000,
            "encodeEndMonotonicNs": 2_000_000_000,
            "frameCount": 120,
            "error": None,
            "requestedRecipeJson": '{"codecFamily":"h264","encoderImplementation":"libx264","rateControlRequested":{"mode":"crf","qualityValue":24},"outputRequested":{"pixelFormat":"yuv420p","bitDepth":8,"chromaSubsampling":"4:2:0","containerFormat":"mp4"}}',
            "effectiveRecipeJson": '{"codecFamily":"h264","encoderImplementation":"libx264","rateControlEffective":{"mode":"crf","qualityValue":24},"outputEffective":{"pixelFormat":"yuv420p","bitDepth":8,"chromaSubsampling":"4:2:0","containerFormat":"mp4"}}',
            "recipeFingerprint": "f" * 64,
        }

        def fake_submit(*, queue_dir, base_url, payload, api_key, retries, use_token, max_storage_mb):
            captured_submission.update(payload)
            return "submitted", "", 0

        with tempfile.TemporaryDirectory() as queue_dir:
            args = self._batch_args(queue_dir, no_submit=False)
            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(client_main, "check_compatibility", return_value={}))
                stack.enter_context(mock.patch.object(client_main, "ensure_ffmpeg_and_ffprobe", return_value=(True, "ffmpeg version n7")))
                stack.enter_context(mock.patch.object(client_main, "_ensure_local_quality_stack", return_value=(True, 0)))
                stack.enter_context(mock.patch.object(client_main, "_build_protocol_config", return_value=client_main.ProtocolConfig.for_version("7.0", stability_threshold_ratio=1.0, max_adaptive_repeats=0)))
                stack.enter_context(mock.patch.object(client_main, "resolve_batch_size", return_value=1))
                stack.enter_context(mock.patch.object(client_main, "count_pending_entries", return_value=0))
                stack.enter_context(mock.patch.object(client_main, "_replay_pending_uploads", return_value=0))
                stack.enter_context(mock.patch.object(client_main, "fetch_baseline_rows", return_value=[]))
                stack.enter_context(mock.patch.object(client_main, "BatchRunDashboard", _DummyDashboard))
                stack.enter_context(mock.patch.object(client_main, "print_batch_summary"))
                stack.enter_context(mock.patch.object(client_main, "print_info"))
                stack.enter_context(mock.patch.object(client_main, "print_warning"))
                stack.enter_context(mock.patch.object(client_main, "probe_video_stream_metrics", side_effect=lambda path: {
                        clip.path: {"sourceFps": 24.0, "sourceDurationSeconds": 5.0, "videoBitrateBps": 8_000_000},
                        artifact_path: {"sourceFps": 24.0, "sourceDurationSeconds": 5.0, "videoBitrateBps": 2_000_000, "containerFormat": "mp4"},
                    }[path]))
                stack.enter_context(mock.patch.object(client_main, "_probe_artifact_contract", side_effect=lambda path: self._artifact_contract(codec="h264")))
                stack.enter_context(mock.patch.object(client_main, "_capture_protocol_environment_snapshot", return_value=EnvironmentSnapshot(
                        background_cpu_pct=5.0,
                        background_gpu_pct=None,
                        power_source="ac",
                        cpu_temp_c=55.0,
                        gpu_temp_c=None,
                        thermal_throttle=None,
                        free_memory_mb=8_192.0,
                        memory_pressure_pct=10.0,
                        selected_accelerator="software",
                        gpu_load_trustworthy=False,
                    )))
                stack.enter_context(mock.patch.object(client_main, "encode_to_artifact", side_effect=[encode_info, encode_info, encode_info]))
                stack.enter_context(mock.patch.object(
                        client_main,
                        "compute_metrics_parallel",
                        side_effect=lambda _input_path, outputs, _workers, quiet=True: {
                            outputs[0]: {"vmaf": 95.0, "vmafMean": 95.0, "vmafP5": 92.0, "metricModelId": "vmaf-v1-sdr-1080p"}
                        },
                    ))
                stack.enter_context(mock.patch.object(client_main, "build_execution_identity_payload", return_value={
                        "environmentJson": '{"cpuArchitecture":"x86_64","cpuPhysicalCores":8,"cpuLogicalCores":16,"accelerator":"software","osName":"testos","osVersion":"1.0","ffmpegBuildFingerprint":"ffmpeg-build","ffmpegVersion":"ffmpeg version n7","clientVersion":"client/0.2.0"}',
                        "environmentFingerprint": "e" * 64,
                    }))
                stack.enter_context(mock.patch.object(client_main, "sha256_of_file", return_value="a" * 64))
                stack.enter_context(mock.patch.object(client_main, "should_skip_submission", return_value=(False, "")))
                stack.enter_context(mock.patch.object(client_main, "_submit_payload_with_spool", side_effect=fake_submit))
                rc = client_main.run_benchmark_batch(
                    hardware=client_main.HardwareInfo("CPU", "GPU", 16, "TestOS"),
                    base_url="https://example.invalid",
                    args=args,
                    tasks=tasks,
                )

        self.assertEqual(rc, 0)
        self.assertEqual(captured_submission["submissionKind"], "authoritative-artifact-run-v1")
        self.assertEqual(captured_submission["artifactPath"], artifact_path)
        self.assertEqual(captured_submission["runCreate"]["artifact"]["sha256"], "a" * 64)
        self.assertEqual(captured_submission["runCreate"]["clientQualityDebug"]["vmafMean"], 95.0)
        self.assertEqual(captured_submission["runCreate"]["expectedMetricModelId"], "vmaf-v1-sdr-1080p")

    def test_run_v7_suite_clip_mode_returns_nonzero_when_authoritative_submission_is_queued(self) -> None:
        clip = self._quick_clip()
        base_args = client_main.argparse.Namespace(
            base_url="https://example.invalid",
            api_key="",
            codec="libx264",
            presets="fast",
            no_submit=False,
            crf=24,
            retries=1,
            queue_dir="/tmp/queue",
            menu=False,
            batch_size=0,
            use_token=False,
            pause_on_exit=False,
            v7_suite_clip=clip.clip_id,
        )
        with mock.patch.object(client_main, "_prepare_named_suite_clip", return_value=clip), \
                mock.patch.object(client_main, "has_encoder", return_value=True), \
                mock.patch.object(client_main, "is_hardware_encoder_usable", return_value=True), \
                mock.patch.object(client_main, "detect_hardware", return_value=client_main.HardwareInfo("CPU", "GPU", 16, "TestOS")), \
                mock.patch.object(client_main, "run_benchmark_batch", return_value=1):
            rc = client_main.run_v7_suite_clip_mode(base_args=base_args)

        self.assertEqual(rc, 1)

    def test_run_v7_suite_clip_mode_rejects_unavailable_explicit_encoder_without_family_fallback(self) -> None:
        clip = self._quick_clip()
        base_args = client_main.argparse.Namespace(
            base_url="https://example.invalid", api_key="", codec="libsvtav1", presets="fast",
            no_submit=False, crf=24, target_bitrate_kbps=None, retries=1, queue_dir="/tmp/queue",
            menu=False, batch_size=0, use_token=False, pause_on_exit=False, v7_suite_clip=clip.clip_id,
        )
        with mock.patch.object(client_main, "_prepare_named_suite_clip", return_value=clip), \
                mock.patch.object(client_main, "has_encoder", return_value=False), \
                mock.patch.object(client_main, "pick_software_encoder_for_family") as pick_mock, \
                mock.patch.object(client_main, "run_benchmark_batch") as run_mock:
            rc = client_main.run_v7_suite_clip_mode(base_args=base_args)

        self.assertEqual(rc, 4)
        pick_mock.assert_not_called()
        run_mock.assert_not_called()

    def test_run_v7_suite_clip_mode_allows_generic_family_selection(self) -> None:
        clip = self._quick_clip()
        base_args = client_main.argparse.Namespace(
            base_url="https://example.invalid", api_key="", codec="av1", presets="fast",
            no_submit=True, crf=24, target_bitrate_kbps=None, retries=1, queue_dir="/tmp/queue",
            menu=False, batch_size=0, use_token=False, pause_on_exit=False, v7_suite_clip=clip.clip_id,
        )
        with mock.patch.object(client_main, "_prepare_named_suite_clip", return_value=clip), \
                mock.patch.object(client_main, "has_encoder", side_effect=lambda encoder: encoder == "libaom-av1"), \
                mock.patch.object(client_main, "pick_software_encoder_for_family", return_value="libaom-av1") as pick_mock, \
                mock.patch.object(client_main, "detect_hardware", return_value=client_main.HardwareInfo("CPU", "GPU", 16, "TestOS")), \
                mock.patch.object(client_main, "run_benchmark_batch", return_value=0) as run_mock:
            rc = client_main.run_v7_suite_clip_mode(base_args=base_args)

        self.assertEqual(rc, 0)
        pick_mock.assert_called_once_with("av1")
        self.assertEqual(run_mock.call_args.kwargs["tasks"][0]["encoder"], "libaom-av1")


class GuidedFlowTests(unittest.TestCase):
    def args(self, **changes):
        values = dict(
            base_url="https://example.invalid", api_key="", no_submit=False, submit=False, crf=24,
            retries=3, queue_dir="unused", menu=False, batch_size=0, use_token=False,
            target_bitrate_kbps=None, max_duration_minutes=60, max_attempts=100,
            max_storage_mb=2048, pause_on_exit=False,
        )
        values.update(changes)
        return client_main.argparse.Namespace(**values)

    def _menu_patches(self, extra=None):
        stack = [
            mock.patch.object(client_main, "ensure_ffmpeg_and_ffprobe", return_value=(True, "ffmpeg test")),
            mock.patch.object(client_main, "detect_hardware",
                              return_value=client_main.HardwareInfo("CPU", "GPU", 16, "TestOS")),
            mock.patch.object(client_main, "list_all_available_encoders", return_value=["libx264"]),
            mock.patch.object(client_main, "_incomplete_campaigns", return_value=[]),
        ]
        stack.extend(extra or [])
        return stack

    def test_no_argument_launch_opens_guided_tui(self) -> None:
        with mock.patch.object(client_main, "validate_queue_dir", side_effect=lambda path: path), \
                mock.patch.object(client_main, "interactive_menu_flow", return_value=0) as menu_mock, \
                mock.patch.object(client_main, "run_with_args") as run_mock, \
                mock.patch.object(client_main, "run_windows_gui_flow") as gui_mock:
            rc = client_main.main(["prog"])
        self.assertEqual(rc, 0)
        menu_mock.assert_called_once()
        run_mock.assert_not_called()
        gui_mock.assert_not_called()

    def test_guided_choice_small_runs_sweep_after_readiness(self) -> None:
        with ExitStack() as stack:
            for patcher in self._menu_patches():
                stack.enter_context(patcher)
            stack.enter_context(mock.patch.object(client_main, "prompt_choice", return_value=0))
            stack.enter_context(mock.patch.object(client_main, "confirm_benchmark_readiness", return_value=True))
            sweep_mock = stack.enter_context(mock.patch.object(client_main, "run_sweep_mode", return_value=0))
            rc = client_main.interactive_menu_flow(client_main.build_arg_parser(), self.args())
        self.assertEqual(rc, 0)
        self.assertEqual(sweep_mock.call_args.kwargs["mode"], "small")

    def test_guided_aborted_readiness_does_not_run(self) -> None:
        with ExitStack() as stack:
            for patcher in self._menu_patches():
                stack.enter_context(patcher)
            stack.enter_context(mock.patch.object(client_main, "prompt_choice", return_value=1))
            stack.enter_context(mock.patch.object(client_main, "confirm_benchmark_readiness", return_value=False))
            sweep_mock = stack.enter_context(mock.patch.object(client_main, "run_sweep_mode"))
            rc = client_main.interactive_menu_flow(client_main.build_arg_parser(), self.args())
        self.assertEqual(rc, 0)
        sweep_mock.assert_not_called()

    def test_guided_resume_offer_continues_saved_campaign(self) -> None:
        args = self.args()
        with ExitStack() as stack:
            for patcher in self._menu_patches([
                mock.patch.object(client_main, "_incomplete_campaigns",
                                  return_value=[("campaign-0123456789abcdef", 1_760_000_000.0)]),
            ]):
                stack.enter_context(patcher)
            stack.enter_context(mock.patch.object(client_main, "prompt_choice", return_value=0))
            resume_mock = stack.enter_context(mock.patch.object(client_main, "_resume_campaign", return_value=0))
            sweep_mock = stack.enter_context(mock.patch.object(client_main, "run_sweep_mode"))
            self.assertEqual(client_main.interactive_menu_flow(client_main.build_arg_parser(), args), 0)
        resume_mock.assert_called_once()
        self.assertEqual(args.resume_campaign, "campaign-0123456789abcdef")
        sweep_mock.assert_not_called()

    def test_advanced_single_still_runs_manual_recipe(self) -> None:
        with ExitStack() as stack:
            for patcher in self._menu_patches():
                stack.enter_context(patcher)
            stack.enter_context(mock.patch.object(client_main, "prompt_choice", side_effect=[4, 0, 6]))
            stack.enter_context(mock.patch.object(client_main, "prompt_text", return_value="22"))
            stack.enter_context(mock.patch.object(client_main, "_apply_submission_policy",
                                                  side_effect=lambda a, **kw: a))
            stack.enter_context(mock.patch.object(client_main, "_preparation_preflight", return_value=0))
            run_mock = stack.enter_context(mock.patch.object(client_main, "run_with_args", return_value=0))
            rc = client_main.interactive_menu_flow(client_main.build_arg_parser(), self.args())
        self.assertEqual(rc, 0)
        effective = run_mock.call_args.args[0]
        self.assertEqual(effective.codec, "libx264")
        self.assertEqual(effective.crf, 22)
        self.assertEqual(effective.presets, "slow")

    def test_advanced_single_uses_native_bitrate_for_videotoolbox(self) -> None:
        with ExitStack() as stack:
            for patcher in self._menu_patches([
                mock.patch.object(client_main, "list_all_available_encoders",
                                  return_value=["h264_videotoolbox"]),
            ]):
                stack.enter_context(patcher)
            stack.enter_context(mock.patch.object(client_main, "prompt_choice", side_effect=[4, 0, 0]))
            stack.enter_context(mock.patch.object(client_main, "prompt_text", return_value="5000"))
            stack.enter_context(mock.patch.object(client_main, "_apply_submission_policy",
                                                  side_effect=lambda a, **kw: a))
            stack.enter_context(mock.patch.object(client_main, "_preparation_preflight", return_value=0))
            stack.enter_context(mock.patch.object(client_main, "is_hardware_encoder_usable", return_value=True))
            run_mock = stack.enter_context(mock.patch.object(client_main, "run_with_args", return_value=0))
            rc = client_main.interactive_menu_flow(client_main.build_arg_parser(), self.args())
        self.assertEqual(rc, 0)
        effective = run_mock.call_args.args[0]
        self.assertEqual(effective.codec, "h264_videotoolbox")
        self.assertIsNone(effective.crf)
        self.assertEqual(effective.target_bitrate_kbps, 5000)

    def test_sweep_interactive_submits_after_persisted_consent(self) -> None:
        captured = {}

        def fake_batch(**kwargs):
            captured.update(kwargs)
            return 0

        with mock.patch.object(client_main, "_ensure_interactive_publication_consent", return_value=True), \
                mock.patch.object(client_main, "_preparation_preflight", return_value=0), \
                mock.patch.object(client_main, "list_all_available_encoders", return_value=["libx264"]), \
                mock.patch.object(client_main, "_prepare_sweep_clips",
                                  return_value=[MainRoutingTests("_quick_clip")._quick_clip()]), \
                mock.patch.object(client_main, "detect_hardware",
                                  return_value=client_main.HardwareInfo("CPU", "GPU", 16, "TestOS")), \
                mock.patch.object(client_main, "run_benchmark_batch", side_effect=fake_batch):
            self.assertEqual(
                client_main.run_sweep_mode(mode="small", base_args=self.args(), interactive=True), 0
            )
        self.assertFalse(captured["args"].no_submit)
        self.assertEqual(captured["plan_metadata"]["sweepMode"], "small")

    def test_resume_replays_saved_sweep_tasks_without_replanning(self) -> None:
        with tempfile.TemporaryDirectory() as queue_dir:
            root = client_main.journal_path(queue_dir, "campaign-0123456789abcdef")
            root.mkdir(parents=True)
            saved_task = {"encoder": "libx264", "preset": "fast", "crf": 24,
                          "rateControl": None, "clipId": "athletic-action-1080p24-final"}
            (root / "manifest.json").write_text(json.dumps({"seed": 7, "tasks": [saved_task]}))
            args = self.args(queue_dir=queue_dir, resume_campaign="campaign-0123456789abcdef")
            clip = MainRoutingTests("_quick_clip")._quick_clip()
            with mock.patch.object(client_main, "_preparation_preflight", return_value=0), \
                    mock.patch.object(client_main.sweep_plan, "plan_sweep",
                                      side_effect=AssertionError("resume must not re-plan")), \
                    mock.patch.object(client_main, "_prepare_named_suite_clip", return_value=clip), \
                    mock.patch.object(client_main, "detect_hardware",
                                      return_value=client_main.HardwareInfo("CPU", "GPU", 16, "TestOS")), \
                    mock.patch.object(client_main, "run_benchmark_batch", return_value=0) as batch_mock:
                self.assertEqual(client_main._resume_campaign(args), 0)
        task = batch_mock.call_args.kwargs["tasks"][0]
        self.assertEqual(task["encoder"], "libx264")
        self.assertIs(task["suiteClip"], clip)
        self.assertEqual(batch_mock.call_args.kwargs["args"].campaign_seed, 7)
        self.assertIsNone(batch_mock.call_args.kwargs["plan_metadata"])

    def _saved_sweep_journal(self, queue_dir, tasks, *, mode="small", seed=4242):
        root = client_main.journal_path(queue_dir, "campaign-0123456789abcdef")
        root.mkdir(parents=True)
        manifest = {"seed": seed, "tasks": tasks, "sweepMode": mode, "plannerVersion": 1,
                    "clipPolicy": "quick", "sweepEncoders": ["libx264"], "sweepSkipped": []}
        (root / "manifest.json").write_text(json.dumps(manifest))
        return manifest

    def _sweep_run_patches(self, queue_dir, captured):
        def fake_batch(**kwargs):
            captured.update(kwargs)
            return 0

        return [
            mock.patch.object(client_main, "_preparation_preflight", return_value=0),
            mock.patch.object(client_main, "list_all_available_encoders", return_value=["libx264"]),
            mock.patch.object(client_main, "_prepare_sweep_clips",
                              return_value=[MainRoutingTests("_quick_clip")._quick_clip()]),
            mock.patch.object(client_main, "detect_hardware",
                              return_value=client_main.HardwareInfo("CPU", "GPU", 16, "TestOS")),
            mock.patch.object(client_main, "run_benchmark_batch", side_effect=fake_batch),
        ]

    def test_sweep_auto_resumes_saved_campaign_with_matching_plan(self) -> None:
        clip = MainRoutingTests("_quick_clip")._quick_clip()
        plan = client_main.sweep_plan.plan_sweep("small", ["libx264"], presets_cfg={})
        saved_tasks = [{"encoder": step["encoder"], "preset": step["preset"], "crf": step["crf"],
                        "rateControl": step["rateControl"], "clipId": clip.clip_id} for step in plan.steps]
        with tempfile.TemporaryDirectory() as queue_dir:
            self._saved_sweep_journal(queue_dir, saved_tasks)
            captured = {}
            with ExitStack() as stack:
                for patcher in self._sweep_run_patches(queue_dir, captured):
                    stack.enter_context(patcher)
                rc = client_main.run_sweep_mode(mode="small", base_args=self.args(queue_dir=queue_dir),
                                                show_end_screen=False, interactive=False, presets_cfg={})
        self.assertEqual(rc, 0)
        self.assertEqual(captured["args"].campaign_seed, 4242)
        self.assertEqual(captured["plan_metadata"]["sweepMode"], "small")

    def test_sweep_starts_fresh_when_saved_plan_differs(self) -> None:
        with tempfile.TemporaryDirectory() as queue_dir:
            stale = {"encoder": "libx264", "preset": "slow", "crf": 30,
                     "rateControl": None, "clipId": "athletic-action-1080p24-final"}
            self._saved_sweep_journal(queue_dir, [stale])
            captured = {}
            with ExitStack() as stack:
                for patcher in self._sweep_run_patches(queue_dir, captured):
                    stack.enter_context(patcher)
                rc = client_main.run_sweep_mode(mode="small", base_args=self.args(queue_dir=queue_dir),
                                                show_end_screen=False, interactive=False, presets_cfg={})
        self.assertEqual(rc, 0)
        self.assertIsNone(captured["args"].campaign_seed)

    def test_resume_campaign_passes_saved_sweep_metadata_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as queue_dir:
            saved_task = {"encoder": "libx264", "preset": "fast", "crf": 24,
                          "rateControl": None, "clipId": "athletic-action-1080p24-final"}
            manifest = self._saved_sweep_journal(queue_dir, [saved_task], seed=99)
            args = self.args(queue_dir=queue_dir, resume_campaign="campaign-0123456789abcdef")
            clip = MainRoutingTests("_quick_clip")._quick_clip()
            with mock.patch.object(client_main, "_preparation_preflight", return_value=0), \
                    mock.patch.object(client_main, "_prepare_named_suite_clip", return_value=clip), \
                    mock.patch.object(client_main, "detect_hardware",
                                      return_value=client_main.HardwareInfo("CPU", "GPU", 16, "TestOS")), \
                    mock.patch.object(client_main, "run_benchmark_batch", return_value=0) as batch_mock:
                self.assertEqual(client_main._resume_campaign(args), 0)
        passed = batch_mock.call_args.kwargs["plan_metadata"]
        for key in client_main.sweep_plan.MANIFEST_KEYS:
            self.assertEqual(passed[key], manifest[key])


if __name__ == "__main__":
    unittest.main()
