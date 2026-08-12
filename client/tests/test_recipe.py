import unittest

from client import recipe


class RecipeIdentityTests(unittest.TestCase):
    def test_supported_encoder_families_map_to_native_rate_control_modes(self) -> None:
        cases = [
            ("libx264", "crf", 24, None),
            ("hevc_nvenc", "cq", 24, None),
            ("av1_qsv", "icq", 26, None),
            ("hevc_amf", "qp", 24, None),
            ("h264_vaapi", "qp", 23, None),
        ]

        for encoder_name, expected_mode, quality_value, expected_target in cases:
            with self.subTest(encoder=encoder_name):
                config_value = recipe.build_rate_control_config(
                    encoder=encoder_name,
                    quality_value=quality_value,
                )
                self.assertEqual(config_value.mode, expected_mode)
                self.assertEqual(config_value.qualityValue, float(quality_value))
                self.assertEqual(config_value.targetBitrateKbps, expected_target)

    def test_videotoolbox_uses_explicit_bitrate_not_fake_crf_identity(self) -> None:
        config_value = recipe.build_rate_control_config(
            encoder="hevc_videotoolbox",
            mode="vbr",
            target_bitrate_kbps=4200,
        )

        self.assertEqual(config_value.mode, "vbr")
        self.assertEqual(config_value.targetBitrateKbps, 4200)
        self.assertEqual(config_value.nativeOptions["b:v"], "4200k")
        self.assertNotIn("crf", config_value.nativeOptions)
        self.assertEqual(recipe.describe_rate_control(config_value), "VBR 4200 kbps")

        with self.assertRaisesRegex(ValueError, "requires explicit targetBitrateKbps"):
            recipe.build_rate_control_config(encoder="hevc_videotoolbox", quality_value=28)

    def test_recipe_fingerprint_ignores_order_and_ui_aliases(self) -> None:
        requested_a = recipe.build_rate_control_config(
            encoder="libx264",
            mode="crf",
            quality_value=24,
            native_options={"preset": "slow", "profile:v": "high"},
            native_arguments=["-profile:v", "high", "-preset", "slow"],
        )
        requested_b = recipe.build_rate_control_config(
            encoder="LIBX264",
            mode="CRF",
            quality_value=24,
            native_options={"profile:v": "high", "preset": "slow"},
            native_arguments=["-preset", "slow", "-profile:v", "high"],
        )
        output_a = recipe.build_output_identity(container_format="MP4", pixel_format="YUV420P", gop_frames=120)
        output_b = recipe.build_output_identity(container_format="mp4", pixel_format="yuv420p", gop_frames=120)
        identity_a = recipe.build_recipe_identity(
            encoder_requested="libx264",
            encoder_effective="libx264",
            preset_requested="slow",
            preset_effective="slow",
            rate_control_requested=requested_a,
            output_requested=output_a,
            native_options_requested={"profile:v": "high", "preset": "slow"},
            native_arguments_requested=["-profile:v", "high", "-preset", "slow"],
        )
        identity_b = recipe.build_recipe_identity(
            encoder_requested="LIBX264",
            encoder_effective="LIBX264",
            preset_requested="SLOW",
            preset_effective="slow",
            rate_control_requested=requested_b,
            output_requested=output_b,
            native_options_requested={"preset": "slow", "profile:v": "high"},
            native_arguments_requested=["-preset", "slow", "-profile:v", "high"],
        )

        self.assertEqual(recipe.canonical_json(identity_a), recipe.canonical_json(identity_b))
        self.assertEqual(recipe.recipe_fingerprint(identity_a), recipe.recipe_fingerprint(identity_b))

    def test_recipe_fingerprint_changes_for_material_recipe_differences(self) -> None:
        requested = recipe.build_rate_control_config(encoder="hevc_nvenc", quality_value=23)
        identity_a = recipe.build_recipe_identity(
            encoder_requested="hevc_nvenc",
            encoder_effective="hevc_nvenc",
            preset_requested="p4",
            preset_effective="p4",
            rate_control_requested=requested,
            output_requested=recipe.build_output_identity(pixel_format="yuv420p", max_b_frames=3),
        )
        identity_b = recipe.build_recipe_identity(
            encoder_requested="hevc_nvenc",
            encoder_effective="hevc_nvenc",
            preset_requested="p4",
            preset_effective="p4",
            rate_control_requested=recipe.build_rate_control_config(encoder="hevc_nvenc", quality_value=27),
            output_requested=recipe.build_output_identity(pixel_format="yuv420p10le", max_b_frames=3),
        )

        self.assertNotEqual(recipe.recipe_fingerprint(identity_a), recipe.recipe_fingerprint(identity_b))

    def test_requested_and_effective_identity_are_retained_separately(self) -> None:
        requested = recipe.build_rate_control_config(
            encoder="h264_videotoolbox",
            mode="vbr",
            target_bitrate_kbps=5000,
        )
        effective = recipe.build_rate_control_config(
            encoder="h264_videotoolbox",
            mode="vbr",
            target_bitrate_kbps=5400,
        )
        identity_value = recipe.build_recipe_identity(
            encoder_requested="h264_videotoolbox",
            encoder_effective="h264_videotoolbox",
            preset_requested="slow",
            preset_effective="slow",
            rate_control_requested=requested,
            rate_control_effective=effective,
            output_requested=recipe.build_output_identity(pixel_format="yuv444p", profile="high444"),
            output_effective=recipe.build_output_identity(pixel_format="nv12", profile="high"),
        )

        self.assertEqual(identity_value.rateControlRequested.targetBitrateKbps, 5000)
        self.assertEqual(identity_value.rateControlEffective.targetBitrateKbps, 5400)
        self.assertEqual(identity_value.outputRequested.pixelFormat, "yuv444p")
        self.assertEqual(identity_value.outputEffective.pixelFormat, "nv12")
        self.assertEqual(identity_value.outputEffective.chromaSubsampling, "4:2:0")

    def test_environment_fingerprint_is_canonical_and_driver_sensitive(self) -> None:
        banner_a = "ffmpeg version 7.0\nconfiguration: --enable-gpl --enable-libx264\nlibavcodec 61.3.100"
        banner_b = "ffmpeg  version 7.0\nconfiguration:   --enable-gpl  --enable-libx264\nlibavcodec 61.3.100"
        env_a = recipe.build_environment_identity(
            cpu_architecture="ARM64",
            cpu_physical_cores=8,
            cpu_logical_cores=10,
            physical_memory_bytes=68719476736,
            accelerator="Apple M4 Max Media Engine",
            driver_version="macOS-26.0",
            ffmpeg_version="ffmpeg version 7.0",
            ffmpeg_banner=banner_a,
            encoder_version="VideoToolbox 1.0",
            client_version="client/0.3.0",
            benchmark_protocol_version="7.1",
            os_name="Darwin",
            os_version="26.0",
            gpu_model="Apple M4 Max",
        )
        env_b = recipe.build_environment_identity(
            cpu_architecture="arm64",
            cpu_physical_cores=8,
            cpu_logical_cores=10,
            physical_memory_bytes=68719476736,
            accelerator="Apple M4 Max Media Engine",
            driver_version="macOS-26.0",
            ffmpeg_version="ffmpeg version 7.0",
            ffmpeg_banner=banner_b,
            encoder_version="VideoToolbox 1.0",
            client_version="client/0.3.0",
            benchmark_protocol_version="7.1",
            os_name="Darwin",
            os_version="26.0",
            gpu_model="Apple M4 Max",
        )
        env_c = recipe.build_environment_identity(
            cpu_architecture="arm64",
            cpu_physical_cores=8,
            cpu_logical_cores=10,
            physical_memory_bytes=68719476736,
            accelerator="Apple M4 Max Media Engine",
            driver_version="macOS-26.1",
            ffmpeg_version="ffmpeg version 7.0",
            ffmpeg_banner=banner_b,
            encoder_version="VideoToolbox 1.0",
            client_version="client/0.3.0",
            benchmark_protocol_version="7.1",
            os_name="Darwin",
            os_version="26.0",
            gpu_model="Apple M4 Max",
        )
        env_d = recipe.build_environment_identity(
            cpu_architecture="arm64",
            cpu_physical_cores=8,
            cpu_logical_cores=10,
            physical_memory_bytes=34359738368,
            accelerator="Apple M4 Max Media Engine",
            driver_version="macOS-26.0",
            ffmpeg_version="ffmpeg version 7.0",
            ffmpeg_banner=banner_b,
            encoder_version="VideoToolbox 1.0",
            client_version="client/0.3.0",
            benchmark_protocol_version="7.1",
            os_name="Darwin",
            os_version="26.0",
            gpu_model="Apple M4 Max",
        )

        self.assertEqual(recipe.environment_fingerprint(env_a), recipe.environment_fingerprint(env_b))
        self.assertNotEqual(recipe.environment_fingerprint(env_a), recipe.environment_fingerprint(env_c))
        self.assertNotEqual(recipe.environment_fingerprint(env_a), recipe.environment_fingerprint(env_d))


if __name__ == "__main__":
    unittest.main()
