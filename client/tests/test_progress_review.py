"""Independent GUI final-state and durable receipt checks."""

import dataclasses
import hashlib
import json
from unittest import mock

from client import main, protocol, spool
from client.campaign import CampaignJournal, atomic_json
from test_progress_contract import (_build_gui_app, _campaign_root, _drive_gui,
                                    _encode, _journal_for, _run_batch)


def _finish(app, rc):
    app.event_queue.put(("done", rc))
    app._poll_events()


def test_final_exit_failure_cannot_leave_gui_stage_complete():
    app = _build_gui_app()
    app._handle_event({"type": "run_complete", "scope": "batch",
                       "completed": 0, "failed": 0, "skipped": 0, "queued": 0})
    assert app.stage_var.get() == "Complete"
    _finish(app, 1)
    assert app.stage_var.get() == "Error"
    assert "failed" in app.summary_var.get().lower()


def test_final_queue_exit_sets_pending_stage():
    app = _build_gui_app()
    app._handle_event({"type": "run_complete", "scope": "batch",
                       "completed": 1, "failed": 0, "skipped": 0, "queued": 1})
    _finish(app, 10)
    assert app.stage_var.get() == "Pending uploads"
    assert "queued" in app.summary_var.get().lower()


def test_checkpoint_exit_sets_paused_stage():
    app = _build_gui_app()
    app._handle_event({"type": "run_budget_exhausted", "scope": "batch",
                       "status": "budget_exhausted"})
    _finish(app, 11)
    assert app.stage_var.get() == "Paused"
    assert "campaign saved" in app.summary_var.get().lower()


def test_end_ledger_counts_queue_receipt_when_old_journal_marker_is_missing(tmp_path):
    events = []
    assert _run_batch(tmp_path, seed=501, events=events) == 0
    root = _campaign_root(tmp_path)
    for index, path in enumerate(sorted(root.glob("submission-*.json")), start=1):
        payload = json.loads(path.read_text())
        local_hash = spool.local_hash_for_payload(payload)
        atomic_json(tmp_path / "receipts" / f"{local_hash}.json", {
            "localHash": local_hash,
            "response": {"benchmarkRun": {"id": f"run-older-{index}"}},
        })
    ledger = main._durable_campaign_ledger(
        str(tmp_path), root.name, _journal_for(tmp_path, root), False,
    )
    assert ledger["uploaded"] == 2
    assert ledger["groupsConfirmed"] == 1
    assert ledger["queued"] == 0


def test_adaptive_group_bars_wait_for_actual_terminal_attempt(tmp_path):
    original_factory = protocol.ProtocolConfig.for_version
    calls = [0]

    def variable_encode(**kwargs):
        calls[0] += 1
        result = _encode(**kwargs)
        result["encodeEndMonotonicNs"] = 1_000_000_000 + calls[0] * 1_000_000_000
        return result

    events = []
    with mock.patch.object(protocol.ProtocolConfig, "for_version",
                           side_effect=lambda version, **_kwargs: original_factory(
                               version, max_adaptive_repeats=2,
                               stability_threshold_ratio=0.03)):
        assert _run_batch(tmp_path, seed=502, events=events,
                          encode_side_effect=variable_encode) == 0
    root = _campaign_root(tmp_path)
    assert len(list(root.glob("attempt-*.json"))) == 5  # warmup + four measured
    progress = [event for event in events if event.get("type") == "campaign_progress"]
    assert progress[-1]["done"] == progress[-1]["total"] == 5
    assert any(0 < event["done"] < event["total"] for event in progress)
    app = _drive_gui(_build_gui_app(), events)
    assert app.overall_pb.options["maximum"] == 5
    assert app.overall_pb.options["value"] == 5
    assert app.batch_pb.options["maximum"] == 5
    assert app.batch_pb.options["value"] == 5


def test_durable_ledger_never_calls_one_repetition_a_finished_group(tmp_path):
    campaign_id = "campaign-0123456789abcdef"
    root = tmp_path / "campaigns" / campaign_id
    root.mkdir(parents=True)
    config = protocol.ProtocolConfig.for_version("7.1", max_adaptive_repeats=2)
    manifest = {"protocolVersion": "7.1", "seed": 1,
                "protocolConfig": dataclasses.asdict(config),
                "tasks": [{"clipId": "clip", "encoder": "libx264", "preset": "fast", "crf": 24}]}
    artifact = root / "measured.mp4"
    artifact.write_bytes(b"durable original")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    record = protocol.BenchmarkRunRecord(
        schedule=protocol.ScheduledRun(campaign_id, "clip|libx264|fast|24", "measured", 1, 1),
        timing=protocol.EncodeTiming.from_measurement(
            start_monotonic_ns=1, end_monotonic_ns=1_000_000_001,
            source_frame_count=24, encoded_frame_count=24, source_fps=24),
        metadata={"info": {"artifactPath": str(artifact), "artifactSha256": digest}},
        counted_for_stability=True,
    )
    atomic_json(root / "manifest.json", manifest)
    atomic_json(root / "attempt-000001.json", record.to_dict())
    atomic_json(root / "submission-000001.accepted.json", {
        "schemaVersion": 1, "executionOrder": 1,
        "recipeId": record.schedule.recipe_id,
        "artifactPath": str(artifact), "artifactSha256": digest,
        "benchmarkRunId": "run-confirmed",
    })
    journal = CampaignJournal(str(tmp_path), campaign_id, manifest, 2048)
    ledger = main._durable_campaign_ledger(str(tmp_path), campaign_id, journal, False)
    assert ledger["uploaded"] == 1
    assert ledger["groupsTotal"] == 1
    assert ledger["groupsConfirmed"] == 0
    assert ledger["requiredMeasured"] == 2
