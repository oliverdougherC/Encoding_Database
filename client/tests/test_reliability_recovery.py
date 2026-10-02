"""Regressions for saved work that must remain visible and publishable."""

import dataclasses
import hashlib
import json
from collections import Counter
from pathlib import Path
from unittest import mock

from client import main, protocol, recovery_projection, spool
from client.artifacts import build_payload_hash
from client.campaign import atomic_json
from test_spool import server_bundle


def _root(tmp_path: Path, suffix: int = 1) -> tuple[str, Path]:
    campaign_id = f"campaign-{suffix:016x}"
    root = tmp_path / "campaigns" / campaign_id
    root.mkdir(parents=True)
    return campaign_id, root


def test_intact_saved_envelope_publishes_with_old_runtime_and_client(tmp_path):
    campaign_id, root = _root(tmp_path)
    atomic_json(root / "manifest.json", {
        "protocolVersion": "7.1", "clientVersion": "client/0.0.0",
        "runtime": {"ffmpeg": {"sha256": "original-runtime"}},
    })
    artifact = root / "measured.mp4"
    artifact.write_bytes(b"retained original bytes")
    payload = {"artifactPath": str(artifact), "artifactSha256": "original-hash"}
    atomic_json(root / "submission-000001.json", payload)
    (root / "attempt-000002.json").write_text("{corrupt unrelated sibling")

    def accepted_replay(*_args, **_kwargs):
        local_hash = spool.local_hash_for_payload(payload)
        atomic_json(tmp_path / "receipts" / f"{local_hash}.json", {
            "localHash": local_hash,
            "status": "uploaded_analysis_pending",
            "response": None,
        })
        return spool.ReplayStats(submitted=1)

    with mock.patch.object(main, "spool_payload", return_value=("queued", {})) as stage, \
         mock.patch.object(main, "replay_spool", side_effect=accepted_replay), \
         mock.patch.object(main, "count_pending_entries", return_value=1), \
         mock.patch.object(main, "ensure_ffmpeg_and_ffprobe", side_effect=AssertionError("runtime not needed")):
        rc, info = main._publish_saved_campaign_gated(
            queue_dir=str(tmp_path), campaign_id=campaign_id,
            base_url="http://127.0.0.1:9", api_key="", max_storage_mb=2048,
        )
    assert rc == 0, info
    assert info["selectedPending"] == 0
    assert info["pending"] == 1  # An unrelated campaign remains queued.
    stage.assert_called_once_with(str(tmp_path), payload, max_storage_mb=2048)
    assert artifact.read_bytes() == b"retained original bytes"


def test_one_saved_publish_restages_after_queue_retirement(tmp_path):
    campaign_id, root = _root(tmp_path)
    for order in (1, 2):
        artifact = root / f"measured-{order}.mp4"
        artifact.write_bytes(f"saved-{order}".encode())
        atomic_json(root / f"submission-{order:06d}.json", {
            "order": order, "artifactPath": str(artifact),
            "runCreate": {"campaignId": campaign_id},
        })
    drained = False
    admissions = []
    receipted = set()

    def stage(_queue, payload, **_kwargs):
        if payload["order"] == 2 and not drained:
            raise spool.SpoolCapacityError("one-artifact headroom")
        admissions.append(payload)
        return f"queued-{payload['order']}", {}

    def replay(*_args, **_kwargs):
        nonlocal drained
        drained = True
        for payload in admissions:
            order = payload["order"]
            if order in receipted:
                continue
            local_hash = spool.local_hash_for_payload(payload)
            atomic_json(tmp_path / "receipts" / f"{local_hash}.json", {
                "localHash": local_hash,
                "status": "uploaded_analysis_pending",
                "response": None,
            })
            receipted.add(order)
        return spool.ReplayStats(submitted=len(admissions))

    with mock.patch.object(main, "spool_payload", side_effect=stage), \
         mock.patch.object(main, "replay_spool", side_effect=replay), \
         mock.patch.object(main, "count_pending_entries", return_value=0):
        rc, info = main._publish_saved_campaign_gated(
            queue_dir=str(tmp_path), campaign_id=campaign_id,
            base_url="http://127.0.0.1:9", api_key="", max_storage_mb=2048,
        )
    assert rc == 0, info
    assert Counter(payload["order"] for payload in admissions) == Counter({1: 1, 2: 1})
    assert info["unadmitted"] == 0


def test_one_saved_publish_drains_real_staged_bytes_to_admit_suffix(tmp_path):
    from test_spool import SpoolTests

    campaign_id, root = _root(tmp_path)
    for order, byte in ((1, b"A"), (2, b"B")):
        artifact = root / f"measured-{order}.mp4"
        artifact.write_bytes(byte * (600 * 1024))
        payload = SpoolTests()._authoritative_payload(str(artifact))
        payload["runCreate"]["campaignId"] = campaign_id
        # Faithful contract: recomputed AFTER identity mutations.
        payload["runCreate"]["payloadHash"] = build_payload_hash(payload["runCreate"])
        atomic_json(root / f"submission-{order:06d}.json", payload)

    run_ids = iter(("run-1", "run-2"))
    with mock.patch.object(spool, "submit_artifact_submission",
                           side_effect=lambda _base, submission, **_kw: server_bundle(submission, next(run_ids))) as send:
        rc, info = main.publish_saved_campaign(
            queue_dir=str(tmp_path), campaign_id=campaign_id,
            base_url="http://127.0.0.1:9", api_key="", max_storage_mb=2,
        )
    assert rc == 0, info
    assert send.call_count == 2
    assert len(list((tmp_path / "receipts").glob("*.json"))) == 2
    assert info["unadmitted"] == 0


def test_blocked_publication_reports_its_cause_without_crashing(capsys):
    main._report_recovery_result({
        "status": "blocked", "campaignId": "campaign-0000000000000001",
        "failure": "saved runtime identity differs from this client",
    })
    output = capsys.readouterr()
    assert "saved runtime identity differs" in output.out + output.err


def test_windows_saved_publication_shows_typed_blocker_cause():
    from test_progress_contract import _build_gui_app

    app = _build_gui_app()
    failure = main.failure_info(
        "saved runtime identity differs from this client",
        operation="reconstruct", campaign_id="campaign-0123456789abcdef",
    )
    message = app._publication_result_text(1, {
        "status": "blocked", "terminal": 0, "failure": failure,
    })
    assert "runtime identity differs" in message
    assert "original compatible client" in message
    assert "0 terminal" not in message


def test_journal_only_finished_group_is_discoverable_for_publish(tmp_path):
    campaign_id, root = _root(tmp_path)
    cfg = protocol.ProtocolConfig.for_version("7.1", max_adaptive_repeats=0)
    atomic_json(root / "manifest.json", {
        "protocolVersion": "7.1", "protocolConfig": dataclasses.asdict(cfg),
        "tasks": [{"clipId": "clip", "encoder": "libx264", "preset": "fast", "crf": 24}],
    })
    timing = protocol.EncodeTiming.from_measurement(
        start_monotonic_ns=1, end_monotonic_ns=1_000_000_001,
        source_frame_count=24, encoded_frame_count=24, source_fps=24,
    )
    for order, phase, repetition in ((1, "warmup", 1), (2, "measured", 1), (3, "measured", 2)):
        metadata = {}
        if phase == "measured":
            artifact = root / f"measured-{order}.mp4"
            artifact.write_bytes(f"measured-{order}".encode())
            metadata = {"info": {
                "artifactPath": str(artifact),
                "artifactSha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "fileSizeBytes": artifact.stat().st_size,
                "error": None,
            }}
        record = protocol.BenchmarkRunRecord(
            schedule=protocol.ScheduledRun(campaign_id, "clip|libx264|fast|24", phase, repetition, order),
            timing=timing,
            metadata=metadata,
            counted_for_stability=phase == "measured",
        )
        atomic_json(root / f"attempt-{order:06d}.json", record.to_dict())
    (root / "attempt-000004.json").write_text("{corrupt sibling")
    projected = recovery_projection.project_attempt_groups(root, campaign_id)
    assert projected["finishedGroupIds"] == ["clip|libx264|fast|24"]
    assert projected["candidateOrders"] == [2, 3]
    assert [item["path"] for item in projected["corruptEntries"]] == ["attempt-000004.json"]
    state = main.campaign_recovery_state(str(tmp_path), campaign_id)
    assert state is not None
    assert state["completedGroups"] == 1
    assert any(action["action"] == "publish_saved" for action in state["actions"])


def test_terminal_menu_does_not_hide_older_or_interrupted_publishable_work(tmp_path):
    ids = []
    for suffix in range(1, 8):
        campaign_id, root = _root(tmp_path, suffix)
        artifact = root / "measured.mp4"
        artifact.write_bytes(b"saved")
        atomic_json(root / "submission-000001.json", {"artifactPath": str(artifact)})
        if suffix != 7:
            atomic_json(root / "campaign-complete.json", {"failed": 0, "skipped": 0})
        ids.append(campaign_id)
    publishable = {item[0] for item in main._publishable_campaigns(str(tmp_path))}
    assert publishable == set(ids)


def test_terminal_menu_lists_every_incomplete_campaign(tmp_path):
    ids = []
    for suffix in range(1, 9):
        campaign_id, _ = _root(tmp_path, suffix)
        ids.append(campaign_id)
    assert {item[0] for item in main._incomplete_campaigns(str(tmp_path))} == set(ids)


def test_terminal_saved_publish_is_available_before_broken_runtime_setup(tmp_path):
    campaign_id, root = _root(tmp_path)
    artifact = root / "measured.mp4"
    artifact.write_bytes(b"saved")
    atomic_json(root / "submission-000001.json", {"artifactPath": str(artifact)})
    args = main.build_arg_parser().parse_args(["--queue-dir", str(tmp_path)])

    def choose(_title, labels, **_kwargs):
        return next(index for index, label in enumerate(labels) if "Publish saved" in label)

    with mock.patch.object(main, "ensure_ffmpeg_and_ffprobe", side_effect=AssertionError("runtime is broken")), \
         mock.patch.object(main, "prompt_choice", side_effect=choose), \
         mock.patch.object(main, "publish_saved_campaign", return_value=(0, {"status": "published", "campaignId": campaign_id})) as publish:
        assert main.interactive_menu_flow(main.build_arg_parser(), args) == 0
    assert publish.call_args.kwargs["campaign_id"] == campaign_id


def test_recovery_counts_envelope_and_spool_copy_once(tmp_path):
    campaign_id, root = _root(tmp_path)
    artifact = root / "measured.mp4"
    artifact.write_bytes(b"saved")
    payload = {"artifactPath": str(artifact), "runCreate": {"campaignId": campaign_id}}
    atomic_json(root / "submission-000001.json", payload)
    spool.spool_payload(str(tmp_path), payload)
    state = main.campaign_recovery_state(str(tmp_path), campaign_id)
    assert state is not None
    assert state["pendingUploads"] == 1
    assert state["queuePending"] == 1
    assert state["logicalPendingUploads"] == 1
    assert main._publishable_campaigns(str(tmp_path))[0][2] == 1


def test_queue_receipt_wins_over_unmarked_saved_envelope(tmp_path):
    campaign_id, root = _root(tmp_path)
    artifact = root / "measured.mp4"
    artifact.write_bytes(b"already accepted")
    payload = {"artifactPath": str(artifact), "runCreate": {"campaignId": campaign_id}}
    atomic_json(root / "submission-000001.json", payload)
    receipt_hash = spool.local_hash_for_payload(payload)
    atomic_json(tmp_path / "receipts" / f"{receipt_hash}.json", {
        "localHash": receipt_hash,
        "status": "uploaded_analysis_pending",
        "response": None,
    })
    state = main.campaign_recovery_state(str(tmp_path), campaign_id)
    assert state is not None
    assert state["acceptedUploads"] == 1
    assert state["logicalPendingUploads"] == 0
    assert not main._publishable_campaigns(str(tmp_path))


def test_failure_actions_preserve_evidence_without_generic_reencode_or_cleanup():
    for cause in ("retry_deadline_expired", "missing_spooled_artifact", "corrupt_existing_spool"):
        action = main._submit_failure_fields("failed", cause)["recoveryAction"].lower()
        assert "queue-cleanup" not in action
        assert "re-encode" not in action
        assert "resume or publish" not in action


def test_missing_retained_artifact_is_visible_blocker_not_published(tmp_path):
    campaign_id, root = _root(tmp_path)
    atomic_json(root / "submission-000001.json", {
        "artifactPath": str(root / "missing.mp4"),
        "runCreate": {"campaignId": campaign_id},
    })
    with mock.patch.object(main, "spool_payload", return_value=("queued", {})), \
         mock.patch.object(main, "replay_spool", return_value=spool.ReplayStats()):
        rc, info = main.publish_saved_campaign(
            queue_dir=str(tmp_path), campaign_id=campaign_id,
            base_url="http://127.0.0.1:9", api_key="", max_storage_mb=2048,
        )
    assert rc == 1
    assert info["status"] == "blocked"
    assert info["unavailableSources"] == 1
    assert "artifact" in info["failure"]["reason"].lower()


def test_missing_legacy_client_identity_cannot_be_relabelled_during_reconstruction(tmp_path):
    campaign_id, root = _root(tmp_path)
    atomic_json(root / "manifest.json", {"protocolVersion": "7.1"})
    outcome = main._reconstruct_saved_submissions(
        queue_dir=str(tmp_path), campaign_id=campaign_id, max_storage_mb=2048,
    )
    assert outcome["reconstructed"] == 0
    assert "saved client identity is missing" in outcome["failure"]
    assert not list(root.glob("submission-*.json"))


def test_consented_saved_publish_persists_continuation_until_confirmed(tmp_path):
    campaign_id, _root_dir = _root(tmp_path)
    arguments = dict(queue_dir=str(tmp_path), campaign_id=campaign_id,
                     base_url="http://127.0.0.1:9", api_key="",
                     max_storage_mb=2048, continue_when_open=True)
    with mock.patch.object(main, "_has_publication_consent", return_value=True), \
         mock.patch.object(main, "_publish_saved_campaign_gated", side_effect=[
             (10, {"campaignId": campaign_id, "status": "pending", "pending": 1}),
             (0, {"campaignId": campaign_id, "status": "published", "pending": 0}),
         ]):
        assert main.publish_saved_campaign(**arguments)[0] == 10
        pending = main.publication_intent_state(str(tmp_path), campaign_id)
        assert pending["active"] is True
        assert pending["nextAttemptAt"] >= pending["createdAt"]
        assert main.publish_saved_campaign(**arguments)[0] == 0
    confirmed = main.publication_intent_state(str(tmp_path), campaign_id)
    assert confirmed["active"] is False
    assert confirmed["status"] == "published"
    assert confirmed["baseUrlFingerprint"] == pending["baseUrlFingerprint"]


def test_legacy_attempts_without_client_identity_cannot_resume_as_new_client(tmp_path):
    from test_progress_contract import _run_batch, _campaign_root

    events = []
    assert _run_batch(tmp_path, seed=713, events=events) == 0
    root = _campaign_root(tmp_path)
    (root / "campaign-complete.json").unlink()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.pop("clientVersion")
    atomic_json(manifest_path, manifest)
    before = {path.name for path in root.glob("attempt-*.json")}
    resumed_events = []
    assert _run_batch(tmp_path, seed=713, events=resumed_events) == 6
    assert {path.name for path in root.glob("attempt-*.json")} == before
    assert any("saved client identity is missing" in str(event.get("message")).lower()
               for event in resumed_events if event.get("type") == "run_error")
    view = main.campaign_recovery_state(str(tmp_path), root.name)
    assert "original compatible client" in view["measurementBlocked"]
    assert not any(action["action"] == "resume" for action in view["actions"])
