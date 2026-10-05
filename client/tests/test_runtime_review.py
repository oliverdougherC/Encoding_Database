"""Independent review of preparation stage deadline accounting."""

import time

import pytest

from client.campaign import PreparationBudgetExceeded, PreparationScope


def test_stage_reports_overrun_when_blocking_step_returns_after_budget():
    scope = PreparationScope(heartbeat_path=None, stall_seconds=10)
    with scope.activate():
        with pytest.raises(PreparationBudgetExceeded):
            with scope.stage("review-blocking-step", 0.05):
                time.sleep(0.08)


def test_nested_stage_does_not_consume_parent_independent_budget():
    scope = PreparationScope(heartbeat_path=None, stall_seconds=10)
    with scope.activate():
        with scope.stage("review-parent", 0.07):
            with scope.stage("review-child", 0.2):
                time.sleep(0.09)
            scope.check()
