"""Real preparation entry points expose bounded, actionable stages."""

import time
import subprocess
from types import SimpleNamespace
from unittest import mock

import pytest

from client import campaign, encoders, main


def test_source_acquisition_has_its_own_finite_stage_budget():
    clip = SimpleNamespace(clip_id="frozen-clip")
    manifest = SimpleNamespace(clips=[clip])
    with mock.patch.object(main, "load_default_suite_manifest", return_value=manifest), \
         mock.patch.object(main, "get_default_quick_clip", return_value=clip), \
         mock.patch.object(main, "ensure_suite_clip", side_effect=lambda _clip: time.sleep(0.08)), \
         mock.patch.object(main, "SOURCE_CLIP_BUDGET_SECONDS", 0.05, create=True):
        with campaign.PreparationScope(heartbeat_path=None).activate():
            with pytest.raises(campaign.PreparationBudgetExceeded):
                main._prepare_quick_suite_clip()


def test_preparation_budget_reports_visible_error_and_nonzero_exit():
    events = []

    @main._preparation_operation
    def prepare(*, event_sink=None):
        with campaign.preparation_stage("test-runtime", 0.05):
            time.sleep(0.08)

    assert prepare(event_sink=events.append) == 2
    assert any(event.get("type") == "run_error" and
               "test-runtime" in str(event.get("message")) for event in events)


def test_source_contract_has_independent_finite_stage_budget():
    from test_main_routing import MainRoutingTests

    clip = MainRoutingTests()._quick_clip()
    main._SOURCE_CONTRACT_CACHE.clear()
    with mock.patch.object(main, "SOURCE_CONTRACT_BUDGET_SECONDS", 0.05), \
         mock.patch.object(main, "_probe_artifact_contract", side_effect=lambda _path: time.sleep(0.08)):
        with campaign.PreparationScope(heartbeat_path=None).activate():
            with pytest.raises(campaign.PreparationBudgetExceeded, match="source-contract"):
                main._build_protocol_recipe_specs(
                    [{"encoder": "libx264", "preset": "fast", "crf": 24,
                      "suiteClip": clip}],
                    default_input_path=clip.path, default_input_hash=clip.input_hash)


@pytest.mark.parametrize("operation,stage", [
    (lambda: encoders.ensure_ffmpeg_and_ffprobe(), "encoder-version-probe"),
    (lambda: encoders._get_encoder_set(), "encoder-list-probe"),
    (lambda: encoders.has_libvmaf(), "filter-list-probe"),
])
def test_encoder_discovery_timeout_is_actionable(operation, stage):
    encoders._ENCODER_LIST_CACHE = None
    with mock.patch.object(encoders, "run_measurement_process",
                           side_effect=subprocess.TimeoutExpired("ffmpeg", 30)):
        with campaign.PreparationScope(heartbeat_path=None).activate():
            with pytest.raises(campaign.PreparationBudgetExceeded, match=stage):
                operation()


def test_cli_queue_and_local_policy_keep_guided_menu(tmp_path):
    with mock.patch.object(main, "interactive_menu_flow", return_value=37) as guided, \
         mock.patch.object(main, "run_with_args", side_effect=AssertionError("single flow")):
        assert main.main(["encodingdb", "--cli", "--no-submit",
                          "--queue-dir", str(tmp_path)]) == 37
    guided.assert_called_once()
    assert main._has_direct_single_run_intent(["--codec", "libx264", "--no-submit"])
