"""Sweep planner regressions: capability filtering, mode progression, native rate control."""
import unittest

from client import sweep_plan
from client.encoders import enumerate_supported_presets_for_encoder

MIXED_ENCODERS = [
    "libx264", "libopenh264", "libx265", "libsvtav1", "libaom-av1", "libvpx-vp9",
    "h264_nvenc", "h264_qsv", "h264_amf", "h264_videotoolbox",
    "hevc_nvenc", "hevc_videotoolbox", "av1_nvenc", "av1_videotoolbox",
]

CFG = {"sweepPlans": {
    "small": {"crfValues": [24], "nativeQualityValues": [23], "bitrateKbpsValues": [6000]},
    "medium": {"crfValues": [22, 26], "nativeQualityValues": [20, 27], "bitrateKbpsValues": [3000, 10000]},
    "large": {"crfValues": [20, 24, 28], "nativeQualityValues": [18, 23, 29], "bitrateKbpsValues": [2000, 6000, 15000]},
    "full": {
        "crfValues": [12, 14, 16, 18, 20, 22, 24, 26, 28, 30],
        "nativeQualityValues": [12, 14, 16, 18, 20, 22, 24, 26, 28, 30],
        "bitrateKbpsValues": [1000, 2000, 4000, 6000, 9000, 13000, 18000],
    },
}}


def steps_for(plan, encoder):
    return [step for step in plan.steps if step["encoder"] == encoder]


class SweepPlanTests(unittest.TestCase):
    def test_all_four_modes_are_distinct_and_strictly_increasing(self) -> None:
        counts = []
        policies = []
        for mode in sweep_plan.SWEEP_MODES:
            plan = sweep_plan.plan_sweep(mode, MIXED_ENCODERS, presets_cfg=CFG)
            counts.append(plan.recipe_count)
            policies.append(plan.clip_policy)
        self.assertEqual(len(set(counts)), 4)
        self.assertEqual(counts, sorted(counts))
        self.assertTrue(all(a < b for a, b in zip(counts, counts[1:])))
        self.assertEqual(policies, ["quick", "classes", "suite", "suite"])

    def test_unusable_hardware_is_dropped_and_reported(self) -> None:
        def usable(encoder: str) -> bool:
            return encoder not in ("h264_nvenc", "av1_nvenc")
        plan = sweep_plan.plan_sweep("medium", MIXED_ENCODERS, presets_cfg=CFG, is_usable=usable)
        self.assertNotIn("h264_nvenc", plan.encoders)
        self.assertNotIn("av1_nvenc", plan.encoders)
        self.assertIn("libx264", plan.encoders)  # software never probes
        self.assertIn("hevc_nvenc", plan.encoders)
        skipped_names = {name for name, _reason in plan.skipped}
        self.assertEqual(skipped_names, {"h264_nvenc", "av1_nvenc"})

    def test_native_rate_control_per_encoder_family(self) -> None:
        plan = sweep_plan.plan_sweep("medium", MIXED_ENCODERS, presets_cfg=CFG)
        x264 = steps_for(plan, "libx264")
        self.assertTrue(all(step["crf"] in (22, 26) and step["rateControl"] is None for step in x264))
        nvenc = steps_for(plan, "h264_nvenc")
        self.assertTrue(all(step["crf"] is None and step["rateControl"]["mode"] == "cq" for step in nvenc))
        self.assertEqual(sorted(step["rateControl"]["qualityValue"] for step in nvenc), [20, 27])
        qsv = steps_for(plan, "h264_qsv")
        self.assertTrue(all(step["rateControl"]["mode"] == "icq" for step in qsv))
        amf = steps_for(plan, "h264_amf")
        self.assertTrue(all(step["rateControl"]["mode"] == "qp" for step in amf))

    def test_videotoolbox_only_ever_gets_explicit_native_bitrates(self) -> None:
        for mode in sweep_plan.SWEEP_MODES:
            plan = sweep_plan.plan_sweep(mode, MIXED_ENCODERS, presets_cfg=CFG)
            for step in steps_for(plan, "h264_videotoolbox"):
                self.assertIsNone(step["crf"])
                self.assertEqual(step["rateControl"]["mode"], "vbr")
                self.assertGreater(step["rateControl"]["targetBitrateKbps"], 0)
                self.assertNotIn("qualityValue", step["rateControl"])

    def test_full_mode_covers_the_complete_supported_grid(self) -> None:
        plan = sweep_plan.plan_sweep("full", MIXED_ENCODERS, presets_cfg=CFG)
        x264_presets = {step["preset"] for step in steps_for(plan, "libx264")}
        self.assertEqual(x264_presets, set(enumerate_supported_presets_for_encoder("libx264")))
        x264_crf_values = {step["crf"] for step in steps_for(plan, "libx264")}
        self.assertEqual(x264_crf_values, set(CFG["sweepPlans"]["full"]["crfValues"]))
        vt_bitrates = {step["rateControl"]["targetBitrateKbps"] for step in steps_for(plan, "hevc_videotoolbox")}
        self.assertEqual(vt_bitrates, set(CFG["sweepPlans"]["full"]["bitrateKbpsValues"]))
        for encoder in sweep_plan.canonical_software_encoders() + sweep_plan.canonical_hardware_encoders():
            if encoder in MIXED_ENCODERS:
                self.assertTrue(steps_for(plan, encoder), f"{encoder} missing from the full grid")

    def test_small_covers_one_software_and_one_hardware_encoder_per_family(self) -> None:
        plan = sweep_plan.plan_sweep("small", MIXED_ENCODERS, presets_cfg=CFG)
        self.assertEqual(
            set(plan.encoders),
            {"libx264", "h264_nvenc", "libx265", "hevc_nvenc", "libsvtav1", "av1_nvenc", "libvpx-vp9"},
        )
        for encoder in plan.encoders:
            presets = {step["preset"] for step in steps_for(plan, encoder)}
            self.assertEqual(len(presets), 1)
            qualities = {
                step["crf"] if step["crf"] is not None
                else step["rateControl"].get("qualityValue", step["rateControl"].get("targetBitrateKbps"))
                for step in steps_for(plan, encoder)
            }
            self.assertEqual(len(qualities), 1)

    def test_plan_is_deterministic_and_input_order_invariant(self) -> None:
        first = sweep_plan.plan_sweep("large", MIXED_ENCODERS, presets_cfg=CFG)
        shuffled = list(reversed(MIXED_ENCODERS))
        second = sweep_plan.plan_sweep("large", shuffled, presets_cfg=CFG)
        third = sweep_plan.plan_sweep("large", MIXED_ENCODERS, presets_cfg=CFG)
        self.assertEqual(first.steps, second.steps)
        self.assertEqual(first.steps, third.steps)
        self.assertEqual(first.encoders, second.encoders)

    def test_estimates_report_protocol_attempt_bounds(self) -> None:
        plan = sweep_plan.plan_sweep("small", ["libx264"], presets_cfg=CFG)
        low, high = plan.estimated_encodes(warmup_runs=1, minimum_measured_runs=2, max_adaptive_repeats=2)
        self.assertEqual(low, plan.recipe_count * 3)
        self.assertEqual(high, plan.recipe_count * 5)

    def test_manifest_metadata_records_planner_provenance(self) -> None:
        plan = sweep_plan.plan_sweep("medium", ["libx264", "h264_nvenc"], presets_cfg=CFG,
                                     is_usable=lambda encoder: False if encoder.endswith("_nvenc") else True)
        metadata = plan.manifest_metadata()
        self.assertEqual(metadata["sweepMode"], "medium")
        self.assertEqual(metadata["plannerVersion"], sweep_plan.PLANNER_VERSION)
        self.assertEqual(metadata["clipPolicy"], "classes")
        self.assertEqual([item["encoder"] for item in metadata["sweepSkipped"]], ["h264_nvenc"])

    def test_unsupported_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            sweep_plan.plan_sweep("huge", MIXED_ENCODERS, presets_cfg=CFG)

    def test_nvenc_selection_keeps_its_own_preset_names_and_native_cq(self) -> None:
        large = sweep_plan.plan_sweep("large", ["h264_nvenc"], presets_cfg=CFG)
        presets = [step["preset"] for step in large.steps]
        self.assertEqual(sorted(set(presets)), ["p2", "p4", "p5"])
        self.assertTrue(all(step["crf"] is None and step["rateControl"]["mode"] == "cq" for step in large.steps))
        full = sweep_plan.plan_sweep("full", ["h264_nvenc"], presets_cfg=CFG)
        self.assertEqual(sorted({step["preset"] for step in full.steps}),
                         [f"p{index}" for index in range(1, 8)])


if __name__ == "__main__":
    unittest.main()
