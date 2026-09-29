"""Real preparation entry points expose bounded, actionable stages."""

import time
from types import SimpleNamespace
from unittest import mock

import pytest

from client import campaign, main


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
