"""R02: every runtime probe and preparation stage owns a finite wall-clock budget,
a persistent substage/heartbeat trail, responsive cancellation, and bounded
owned-process termination. No media runtime or network required."""
import hashlib
import itertools
import json
import os
import subprocess
import sys
import threading
import time
from unittest import mock

import pytest

from client import campaign, protocol, runtime_lock


def _journal_with_artifact(tmp_path):
    campaign_id = "campaign-0123456789abcdef"
    root = campaign.journal_path(str(tmp_path), campaign_id)
    root.mkdir(parents=True)
    manifest = {"seed": 3, "tasks": [{"encoder": "libx264", "preset": "fast", "crf": 24}]}
    campaign.atomic_json(root / "manifest.json", manifest)
    artifact = root / "attempt-000000.mkv"
    artifact.write_bytes(b"a" * (1024 * 1024) + b"b" * (1024 * 1024))
    record = protocol.BenchmarkRunRecord(
        schedule=protocol.ScheduledRun(campaign_id, "clip|libx264|fast|24", "measured", 0, 0),
        metadata={"info": {"artifactPath": str(artifact),
                           "artifactSha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}},
        counted_for_stability=True)
    campaign.atomic_json(root / "attempt-000000.json", record.to_dict())
    return campaign_id, root, manifest, artifact


def _run_in_thread(action):
    outcome = []
    def body():
        try:
            outcome.append(("returned", action()))
        except BaseException as exc:  # noqa: BLE001 - surfaced to the assertion
            outcome.append(("raised", exc))
    thread = threading.Thread(target=body, daemon=True)
    started = time.monotonic()
    thread.start()
    thread.join(10)
    return thread, outcome, time.monotonic() - started


def test_hanging_runtime_probe_is_killed_with_budget_context():
    spawned = []
    real_popen = subprocess.Popen
    def launch(command, **kwargs):
        process = real_popen(command, **kwargs)
        spawned.append(process)
        return process
    with mock.patch.object(runtime_lock, "RUNTIME_PROBE_TIMEOUT_SECONDS", 1.0), \
         mock.patch.object(campaign.subprocess, "Popen", side_effect=launch):
        thread, outcome, elapsed = _run_in_thread(
            lambda: runtime_lock._run_text([sys.executable, "-c", "import time; time.sleep(30)"]))
    try:
        assert not thread.is_alive(), "a hung runtime probe outran its finite probe budget"
        assert elapsed < 10
        kind, value = outcome[0]
        assert kind == "raised" and isinstance(value, runtime_lock.RuntimeLockError)
        assert "probe budget" in str(value)
        assert len(spawned) == 1 and spawned[0].poll() is not None
    finally:
        for process in spawned:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


def test_scoped_probe_without_explicit_timeout_is_bounded_and_reaped():
    spawned = []
    real_popen = subprocess.Popen
    def launch(command, **kwargs):
        process = real_popen(command, **kwargs)
        # The patch is process-global; ignore the interpreter's own lazy
        # platform probes (uname/file) that land inside the window.
        if list(command)[0] == sys.executable:
            spawned.append(process)
        return process
    def action():
        with campaign.PreparationScope().activate():
            return campaign.run_measurement_process(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    with mock.patch.object(campaign, "PROBE_PROCESS_TIMEOUT_SECONDS", 1.0), \
         mock.patch.object(campaign.subprocess, "Popen", side_effect=launch):
        thread, outcome, elapsed = _run_in_thread(action)
    try:
        assert not thread.is_alive(), "a scoped probe with no explicit timeout hung forever"
        assert elapsed < 10
        kind, value = outcome[0]
        assert kind == "raised" and isinstance(value, subprocess.TimeoutExpired)
        assert campaign._PREPARATION.get() is None
        assert len(spawned) == 1 and spawned[0].poll() is not None, \
            "timed-out owned probe process was not terminated"
    finally:
        for process in spawned:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


def test_preparation_stage_budget_fails_closed_on_wall_clock_expiry():
    scope = campaign.PreparationScope()
    with mock.patch.object(campaign.time, "monotonic", side_effect=itertools.count(step=20)):
        with scope.activate():  # activate opens the acquisition fence; body stages nest inside
            with pytest.raises(campaign.PreparationBudgetExceeded) as raised:
                with scope.stage("runtime-verify", 30):
                    campaign.check_preparation_cancelled()
                    campaign.check_preparation_cancelled()
    assert raised.value.stage == "runtime-verify"
    assert raised.value.budget_seconds == 30
    assert scope.stage_stack == []

    outer = campaign.PreparationScope()
    with mock.patch.object(campaign.time, "monotonic", side_effect=itertools.count(step=10)):
        with outer.activate():
            with pytest.raises(campaign.PreparationBudgetExceeded) as raised:
                with outer.stage("outer", 1000):
                    with outer.stage("inner", 20):
                        campaign.check_preparation_cancelled()
                        campaign.check_preparation_cancelled()
    assert raised.value.stage == "inner"
    assert outer.stage_stack == []


def test_stage_stall_watchdog_tolerates_live_progress_but_fails_on_silence():
    events = []
    scope = campaign.PreparationScope(progress=lambda stage, **details: events.append(stage))
    with mock.patch.object(campaign.time, "monotonic", side_effect=itertools.count(step=10)):
        with scope.activate():
            with scope.stage("runtime-hash", 1000, stall_seconds=50):
                for count in range(10):
                    campaign.preparation_progress("runtime-hash", path="bundle", completedBytes=count)
            assert events == ["runtime-hash"] * 10
            with pytest.raises(campaign.PreparationStalled) as raised:
                with scope.stage("runtime-dependency-hash", 10000, stall_seconds=50):
                    for _ in range(5):
                        campaign.check_preparation_cancelled()
    assert raised.value.stage == "runtime-dependency-hash"


def test_watchdogs_never_fire_outside_an_open_stage():
    scope = campaign.PreparationScope()
    token = campaign._PREPARATION.set(scope)
    try:
        with mock.patch.object(campaign.time, "monotonic", side_effect=itertools.count(step=10000)):
            for _ in range(5):
                campaign.check_preparation_cancelled()
                campaign.preparation_progress("upload", path="x")
    finally:
        campaign._PREPARATION.reset(token)


def test_journal_reopen_is_cancellable_between_hash_chunks(tmp_path):
    campaign_id, root, manifest, artifact = _journal_with_artifact(tmp_path)
    campaign.atomic_json(root / "budget.json", {"schemaVersion": 1, "maxStorageMb": 256})
    stop = threading.Event()
    events = []
    def progress(stage, **details):
        events.append((stage, details))
        stop.set()
    def snapshot():
        # budget.json is a policy file reopen rewrites (byte-identical); the
        # evidence files a failed reopen must never touch are manifest + attempt.
        return {p.name: p.read_bytes() for p in root.iterdir() if p.name != "budget.json"}
    before = snapshot()
    with mock.patch.object(campaign.time, "monotonic", side_effect=itertools.count(step=1.0)):
        with pytest.raises(KeyboardInterrupt), campaign.PreparationScope(stop, progress).activate():
            campaign.CampaignJournal(str(tmp_path), campaign_id, manifest, 256)
    assert [stage for stage, _ in events] == ["journal-reopen"]
    assert events[0][1]["path"] == str(artifact)
    assert events[0][1]["completedBytes"] == 1024 * 1024
    assert snapshot() == before


def test_journal_reopen_heartbeat_persists_throttled_substage(tmp_path):
    campaign_id, root, manifest, artifact = _journal_with_artifact(tmp_path)
    heartbeat = tmp_path / "state" / "preparation.json"
    observed = []
    def progress(stage, **details):
        observed.append(json.loads(heartbeat.read_text()))
    scope = campaign.PreparationScope(progress=progress, heartbeat_path=str(heartbeat))
    with mock.patch.object(campaign.time, "monotonic", return_value=10):
        with scope.activate():
            campaign.CampaignJournal(str(tmp_path), campaign_id, manifest, 256)
    assert len(observed) == 1
    mid = observed[0]
    assert mid["stage"] == "journal-reopen" and mid["substage"] == "journal-reopen"
    assert mid["completedBytes"] == 1024 * 1024 and mid["pid"] == os.getpid()
    final = json.loads(heartbeat.read_text())
    assert final["stage"] == "journal-reopen" and final["status"] == "completed"
    assert final["stageBudgetSeconds"] == campaign.JOURNAL_REOPEN_BUDGET_SECONDS


def test_acquisition_fence_fails_closed_when_a_reader_never_drains():
    release = threading.Event()
    reader = threading.Thread(target=release.wait, daemon=True)
    reader.start()
    try:
        with mock.patch.object(campaign, "_ACQUISITION_READER", reader), \
             mock.patch.object(campaign, "_ACQUISITION_FENCE_BUDGET_SECONDS", 0.5), \
             mock.patch.object(campaign.time, "monotonic", side_effect=itertools.count(step=0.1)):
            def action():
                with campaign.PreparationScope().activate():
                    return "entered"
            thread, outcome, elapsed = _run_in_thread(action)
        assert not thread.is_alive(), "the acquisition fence waited forever on a stuck reader"
        assert elapsed < 10
        kind, value = outcome[0]
        assert kind == "raised" and isinstance(value, campaign.PreparationTimeout)
        assert value.stage == "acquisition-fence"
        assert campaign._PREPARATION.get() is None
    finally:
        release.set()
        reader.join(5)