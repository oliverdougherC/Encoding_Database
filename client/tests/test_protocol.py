import unittest
import json
import tempfile

from client import main as client_main

from client.protocol import (
    ArtifactProbe,
    EncodeOutcome,
    EncodeTiming,
    EnvironmentSnapshot,
    ProtocolConfig,
    RecipeSpec,
    StructuralExpectation,
    execute_protocol_campaign,
    validate_environment,
    validate_structural_contract,
)


def _expectation() -> StructuralExpectation:
    return StructuralExpectation(
        duration_s=10.0,
        frame_count=300,
        width=1920,
        height=1080,
        codec="h264",
        codec_tag="avc1",
        profile="high",
        level="4.1",
        pix_fmt="yuv420p",
        bit_depth=8,
        chroma_subsampling="4:2:0",
        color_range="tv",
        color_space="bt709",
        color_transfer="bt709",
        color_primaries="bt709",
        avg_frame_rate=30.0,
        time_base=1 / 30.0,
        no_audio=True,
    )


def _probe(**overrides) -> ArtifactProbe:
    payload = {
        "decodable": True,
        "duration_s": 10.0,
        "frame_count": 300,
        "width": 1920,
        "height": 1080,
        "codec": "h264",
        "codec_tag": "avc1",
        "profile": "high",
        "level": "4.1",
        "pix_fmt": "yuv420p",
        "bit_depth": 8,
        "chroma_subsampling": "4:2:0",
        "color_range": "tv",
        "color_space": "bt709",
        "color_transfer": "bt709",
        "color_primaries": "bt709",
        "avg_frame_rate": 30.0,
        "time_base": 1 / 30.0,
        "has_audio": False,
        "size_bytes": 1_000_000,
        "truncated": False,
    }
    payload.update(overrides)
    return ArtifactProbe(**payload)


def _timing(elapsed_s: float, *, frame_count: int = 300, source_fps: float = 30.0) -> EncodeTiming:
    start_ns = 1_000_000_000
    end_ns = start_ns + int(elapsed_s * 1_000_000_000)
    return EncodeTiming.from_measurement(
        start_monotonic_ns=start_ns,
        end_monotonic_ns=end_ns,
        source_frame_count=frame_count,
        encoded_frame_count=frame_count,
        source_fps=source_fps,
        ffmpeg_cpu_time_s=elapsed_s * 0.9,
    )


class ProtocolEngineTests(unittest.TestCase):
    def test_stable_campaign_keeps_warmup_explicit_and_counterbalances_order(self) -> None:
        config = ProtocolConfig.for_version("7.0", stability_threshold_ratio=0.05, max_adaptive_repeats=2)
        recipes = [
            RecipeSpec(recipe_id="slow", expectation=_expectation()),
            RecipeSpec(recipe_id="fast", expectation=_expectation()),
        ]
        call_order = []

        def environment_sampler(schedule, recipe):
            return EnvironmentSnapshot(
                background_cpu_pct=8.0,
                background_gpu_pct=5.0,
                power_source="ac",
                cpu_temp_c=55.0,
                gpu_temp_c=50.0,
                free_memory_mb=8_192.0,
                memory_pressure_pct=20.0,
                selected_accelerator=recipe.recipe_id,
            )

        def encode_runner(schedule, recipe):
            call_order.append((schedule.phase, schedule.repetition_index, schedule.execution_order, recipe.recipe_id))
            elapsed = 10.0 if recipe.recipe_id == "slow" else 9.9
            return EncodeOutcome(timing=_timing(elapsed), probe=_probe())

        result = execute_protocol_campaign(
            recipes=recipes,
            config=config,
            encode_runner=encode_runner,
            environment_sampler=environment_sampler,
            seed=11,
        )

        self.assertEqual(len(result.recipe_results), 2)
        self.assertEqual(call_order[0][0], "warmup")
        self.assertEqual(call_order[1][0], "warmup")
        self.assertEqual(call_order[2][0], "measured")
        self.assertEqual(call_order[3][0], "measured")
        first_measured_order = [recipe_id for phase, repetition, _, recipe_id in call_order if phase == "measured" and repetition == 1]
        second_measured_order = [recipe_id for phase, repetition, _, recipe_id in call_order if phase == "measured" and repetition == 2]
        self.assertEqual(second_measured_order, list(reversed(first_measured_order)))
        for recipe_result in result.recipe_results:
            self.assertTrue(recipe_result.stability.stable)
            self.assertEqual(recipe_result.measured_runs_completed, 2)
            self.assertEqual(recipe_result.measured_runs_counted, 2)
            measured_orders = [run.schedule.execution_order for run in recipe_result.runs if run.schedule.phase == "measured"]
            self.assertEqual(len(measured_orders), 2)
            self.assertTrue(all(run.schedule.campaign_id == result.campaign_id for run in recipe_result.runs))

    def test_unstable_campaign_adds_bounded_adaptive_repeats(self) -> None:
        config = ProtocolConfig.for_version("7.0", stability_threshold_ratio=0.01, max_adaptive_repeats=2)
        recipe = RecipeSpec(recipe_id="swingy", expectation=_expectation())
        elapsed_values = iter([10.2, 10.0, 13.0, 10.5, 9.8])

        def environment_sampler(schedule, _recipe):
            return EnvironmentSnapshot(
                background_cpu_pct=5.0,
                background_gpu_pct=3.0,
                power_source="ac",
                cpu_temp_c=50.0,
                gpu_temp_c=45.0,
                free_memory_mb=16_384.0,
                memory_pressure_pct=10.0,
                selected_accelerator=schedule.recipe_id,
            )

        def encode_runner(_schedule, _recipe):
            return EncodeOutcome(timing=_timing(next(elapsed_values)), probe=_probe())

        result = execute_protocol_campaign(
            recipes=[recipe],
            config=config,
            encode_runner=encode_runner,
            environment_sampler=environment_sampler,
            seed=7,
        )

        recipe_result = result.recipe_results[0]
        measured = [run for run in recipe_result.runs if run.schedule.phase == "measured"]
        self.assertEqual(len(measured), 4)
        self.assertFalse(recipe_result.stability.stable)
        self.assertEqual(recipe_result.measured_runs_completed, 4)
        self.assertEqual(recipe_result.measured_runs_counted, 4)

    def test_invalid_environment_repetition_is_persisted_and_skipped_before_encode(self) -> None:
        config = ProtocolConfig.for_version("7.0", stability_threshold_ratio=0.05, max_adaptive_repeats=1)
        recipe = RecipeSpec(recipe_id="env-invalid", expectation=_expectation())
        encode_calls = 0

        def environment_sampler(schedule, _recipe):
            cpu_pct = 90.0 if schedule.phase == "measured" and schedule.repetition_index == 1 else 5.0
            return EnvironmentSnapshot(
                background_cpu_pct=cpu_pct,
                background_gpu_pct=3.0,
                power_source="ac",
                cpu_temp_c=50.0,
                gpu_temp_c=45.0,
                free_memory_mb=16_384.0,
                memory_pressure_pct=10.0,
                selected_accelerator=schedule.recipe_id,
            )

        def encode_runner(_schedule, _recipe):
            nonlocal encode_calls
            encode_calls += 1
            return EncodeOutcome(timing=_timing(10.0), probe=_probe())

        result = execute_protocol_campaign(
            recipes=[recipe],
            config=config,
            encode_runner=encode_runner,
            environment_sampler=environment_sampler,
            seed=5,
        )

        recipe_result = result.recipe_results[0]
        invalid_run = next(run for run in recipe_result.runs if run.schedule.phase == "measured" and run.schedule.repetition_index == 1)
        self.assertTrue(invalid_run.skipped_before_encode)
        self.assertEqual(invalid_run.overall_validity.state, "invalid")
        self.assertEqual(invalid_run.overall_validity.reasons[0].code, "background-cpu-high")
        self.assertEqual(recipe_result.measured_runs_completed, 3)
        self.assertEqual(recipe_result.measured_runs_counted, 2)
        self.assertTrue(recipe_result.stability.stable)
        self.assertEqual(encode_calls, 3)

    def test_environment_gate_marks_battery_and_thermal_context(self) -> None:
        suspect_snapshot = EnvironmentSnapshot(
            background_cpu_pct=20.0,
            background_gpu_pct=12.0,
            power_source="battery",
            cpu_temp_c=86.0,
            gpu_temp_c=50.0,
            thermal_throttle=False,
            free_memory_mb=3_000.0,
            memory_pressure_pct=20.0,
            selected_accelerator="nvenc0",
        )
        suspect = validate_environment(suspect_snapshot, ProtocolConfig.for_version("7.0").environment)
        self.assertEqual(suspect.state, "suspect")
        self.assertEqual([reason.code for reason in suspect.reasons], ["power-source-battery", "cpu-temp-suspect"])

        thermal_snapshot = EnvironmentSnapshot(
            background_cpu_pct=5.0,
            background_gpu_pct=5.0,
            power_source="ac",
            cpu_temp_c=60.0,
            gpu_temp_c=55.0,
            thermal_throttle=True,
            free_memory_mb=8_192.0,
            memory_pressure_pct=10.0,
            selected_accelerator="nvenc0",
        )
        thermal = validate_environment(thermal_snapshot, ProtocolConfig.for_version("7.0").environment)
        self.assertEqual(thermal.state, "invalid")
        self.assertEqual([reason.code for reason in thermal.reasons], ["thermal-throttle"])

    def test_structural_validation_rejects_mismatched_output_semantics(self) -> None:
        probe = _probe(
            duration_s=8.5,
            frame_count=280,
            codec_tag="hvc1",
            pix_fmt="yuv444p",
            has_audio=True,
            truncated=True,
        )

        result = validate_structural_contract(
            probe,
            _expectation(),
            ProtocolConfig.for_version("7.0").structural_tolerance,
        )

        self.assertEqual(result.state, "invalid")
        codes = [reason.code for reason in result.reasons]
        self.assertIn("artifact-truncated", codes)
        self.assertIn("audio-stream-present", codes)
        self.assertIn("duration-mismatch", codes)
        self.assertIn("frame-count-mismatch", codes)
        self.assertIn("codec-tag-mismatch", codes)
        self.assertIn("pixfmt-mismatch", codes)

    def test_structural_validation_covers_stream_decode_color_container_and_gop_contract(self) -> None:
        expectation = _expectation()
        expectation = StructuralExpectation(
            **{
                **expectation.__dict__,
                "container_format": "mp4",
                "gop_frames": 120,
                "keyint_min": 60,
                "max_b_frames": 3,
                "b_frame_reordering": True,
            }
        )
        result = validate_structural_contract(
            _probe(
                container_format="mkv",
                keyframe_interval_min=30,
                keyframe_interval_max=240,
                max_b_frames=0,
                b_frame_reordering=False,
                video_stream_count=2,
                auxiliary_stream_count=1,
            ),
            expectation,
            ProtocolConfig.for_version("7.0").structural_tolerance,
        )
        self.assertEqual(result.state, "invalid")
        self.assertEqual(
            {reason.code for reason in result.reasons},
            {
                "video-stream-count-mismatch",
                "auxiliary-stream-present",
                "container-mismatch",
                "bframes-mismatch",
                "frame-reordering-mismatch",
                "gop-mismatch",
                "keyint-min-mismatch",
            },
        )

    def test_omitted_seed_creates_fresh_persisted_campaign_seed(self) -> None:
        recipe = RecipeSpec(recipe_id="seeded", expectation=_expectation())

        def encode_runner(_schedule, _recipe):
            return EncodeOutcome(timing=_timing(10.0), probe=_probe())

        first = execute_protocol_campaign(
            recipes=[recipe],
            config=ProtocolConfig.for_version("7.0"),
            encode_runner=encode_runner,
        )
        second = execute_protocol_campaign(
            recipes=[recipe],
            config=ProtocolConfig.for_version("7.0"),
            encode_runner=encode_runner,
        )
        self.assertIsInstance(first.seed, int)
        self.assertNotEqual(first.seed, second.seed)
        self.assertNotEqual(first.campaign_id, second.campaign_id)

        with tempfile.TemporaryDirectory() as queue_dir:
            evidence_path = client_main._persist_protocol_attempt_evidence(queue_dir, first)
            with open(evidence_path, "r", encoding="utf-8") as handle:
                evidence = json.load(handle)
            self.assertEqual(evidence["campaignId"], first.campaign_id)
            self.assertEqual(evidence["seed"], first.seed)
            self.assertEqual(evidence["recipeResults"][0]["runs"][0]["schedule"]["phase"], "warmup")

    def test_hardware_environment_without_gpu_observation_is_suspect(self) -> None:
        result = validate_environment(
            EnvironmentSnapshot(
                background_cpu_pct=5.0,
                power_source="ac",
                free_memory_mb=8192,
                selected_accelerator="hevc_videotoolbox",
                accelerator_is_hardware=True,
                gpu_load_trustworthy=False,
                gpu_sample_count=0,
            ),
            ProtocolConfig.for_version("7.0").environment,
        )
        self.assertEqual(result.state, "suspect")
        self.assertIn("gpu-environment-unobserved", [reason.code for reason in result.reasons])

    def test_encode_timing_requires_monotonic_encode_only_measurement(self) -> None:
        timing = EncodeTiming.from_measurement(
            start_monotonic_ns=100,
            end_monotonic_ns=10_000_000_100,
            source_frame_count=300,
            encoded_frame_count=300,
            source_fps=30.0,
            ffmpeg_cpu_time_s=8.0,
        )
        self.assertAlmostEqual(timing.elapsed_s, 10.0)
        self.assertAlmostEqual(timing.encode_fps, 30.0)
        self.assertAlmostEqual(timing.realtime_multiple, 1.0)

        with self.assertRaisesRegex(ValueError, "increasing monotonic timestamps"):
            EncodeTiming.from_measurement(
                start_monotonic_ns=1_000,
                end_monotonic_ns=999,
                source_frame_count=300,
                encoded_frame_count=300,
                source_fps=30.0,
            )


if __name__ == "__main__":
    unittest.main()
