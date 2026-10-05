"""F5 (PLA-578) + F6 (PLA-579): corrupt saved-state evidence can never be
reported as "published successfully", and one historical record's metadata
failure cannot starve healthy work.

F5: the recovery projection inspects retained artifacts INDEPENDENTLY of a
corrupt accepted marker (marker existence is not proof, corruption is not
proof), the publisher reconstructs and publishes intact work beside corrupt
markers, damaged marker bytes are preserved as superseded prior evidence, and
any corruption that remains unresolved at the end surfaces as a non-success
with the corruption listed — while healthy siblings stay recoverable.

F6: per-record reconciliation outcomes are separated: 404/410 is a permanent
per-record absence (honest reconciliation work), transport/5xx is that
record's own deferred disposition. Neither stops the healthy suffix from
staging/replaying, and neither fabricates a confirmation nor re-encodes.
"""

import dataclasses  # noqa: F401  (kept for parity with sibling fixtures)
import hashlib
import json
from pathlib import Path
from unittest import mock

import pytest
from client import acknowledgments, artifacts, main, protocol, spool
from client.campaign import atomic_json
from client.network import SubmitError
from test_spool import server_bundle


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _submission(campaign_id: str, artifact: Path, order: int) -> dict:
    blob = artifact.read_bytes()
    run_create = {"payloadHash": "a" * 64, "campaignId": campaign_id,
                  "repetitionGroupId": f"{campaign_id}:recipe-1",
                  "repetitionIndex": order,
                  "artifact": {"role": "ENCODED", "sha256": _sha(blob),
                               "byteSize": len(blob), "mediaContainer": "mp4"}}
    run_create["payloadHash"] = artifacts.build_payload_hash(run_create)
    return artifacts.build_artifact_submission_payload(
        artifact_path=str(artifact), media_container="mp4", run_create=run_create)


def _complete_journal(tmp_path: Path, *, crfs=(24,), captured_envelopes=None):
    """REAL batch with no_submit: durable attempts for one complete group,
    zero envelopes — exactly the state the review's F5 case corrupts."""
    from test_main_routing import MainRoutingTests, _DummyDashboard
    fixture = MainRoutingTests()
    clip = fixture._quick_clip()
    args = fixture._batch_args(str(tmp_path), no_submit=True)
    args.local_metrics = False
    args.campaign_seed = 77
    args.max_duration_minutes = 1.0

    def encode(**kwargs):
        artifact = Path(kwargs["out_dir"]) / kwargs["artifact_name"]
        artifact.write_bytes(b"encoded")
        return {"artifactPath": str(artifact), "encoderUsed": "libx264", "presetUsed": "fast",
                "fileSizeBytes": 7, "encodeStartMonotonicNs": 1_000_000_000,
                "encodeEndMonotonicNs": 2_000_000_000, "elapsedMs": 1000, "error": None}

    hardware = main.HardwareInfo("CPU", None, 16, "OS")
    with mock.patch.object(main, "detect_hardware", return_value=hardware), \
         mock.patch.object(main, "ensure_ffmpeg_and_ffprobe", return_value=(True, "ffmpeg test")), \
         mock.patch.object(main, "_build_protocol_config",
                           return_value=protocol.ProtocolConfig.for_version(
                               "7.1", max_adaptive_repeats=0)), \
         mock.patch.object(main, "probe_video_stream_metrics",
                           return_value={"sourceFps": 24, "sourceDurationSeconds": 5,
                                         "containerFormat": "mp4"}), \
         mock.patch.object(main, "_probe_artifact_contract",
                           side_effect=lambda path: fixture._artifact_contract()), \
         mock.patch.object(main, "_capture_protocol_environment_snapshot",
                           return_value=protocol.EnvironmentSnapshot(
                               selected_accelerator="software")), \
         mock.patch.object(main, "encode_to_artifact", side_effect=encode), \
         mock.patch.object(main, "BatchRunDashboard", _DummyDashboard):
        assert main.run_benchmark_batch(
            hardware=hardware, base_url="https://example.invalid", args=args,
            tasks=[{"encoder": "libx264", "preset": "fast", "crf": crf, "suiteClip": clip}
                   for crf in crfs]) == 0
    root = next((tmp_path / "campaigns").iterdir())
    artifacts_by_order = {}
    for path in root.glob("attempt-*.json"):
        data = json.loads(path.read_text())
        if data["schedule"]["phase"] == "measured":
            artifacts_by_order[data["schedule"]["execution_order"]] = Path(
                data["metadata"]["info"]["artifactPath"])
    measured = sorted(artifacts_by_order)
    assert len(measured) >= 2
    # Recreate the review's crash state: durable attempts + intact bytes but
    # NO envelopes yet (the live path wrote them only after the group ended).
    for path in root.glob("submission-*.json"):
        if captured_envelopes is not None:
            captured_envelopes[path.name] = json.loads(path.read_text())
        path.unlink()
    assert not list(root.glob("submission-*.json"))
    return root, measured, artifacts_by_order


def _historical_case(tmp_path, *, retention_error):
    """Envelope 1: historical v1 marker, bytes retired. Envelope 2: healthy,
    intact bytes. The reconciliation fetch fails exactly as requested."""
    campaign_id = "campaign-000000000000f601"
    root = tmp_path / "campaigns" / campaign_id
    root.mkdir(parents=True)
    art1 = root / "measured-1.mp4"
    art1.write_bytes(b"retired-long-ago")
    digest1 = _sha(art1.read_bytes())
    run_create = {"payloadHash": "a" * 64, "campaignId": campaign_id,
                  "repetitionGroupId": f"{campaign_id}:recipe-1", "repetitionIndex": 1,
                  "artifact": {"role": "ENCODED", "sha256": digest1,
                               "byteSize": art1.stat().st_size, "mediaContainer": "mp4"}}
    run_create["payloadHash"] = artifacts.build_payload_hash(run_create)
    env1 = artifacts.build_artifact_submission_payload(
        artifact_path=str(art1), media_container="mp4", run_create=run_create)
    atomic_json(root / "submission-000001.json", env1)
    atomic_json(root / "submission-000001.accepted.json", {
        "schemaVersion": 1, "executionOrder": 1, "recipeId": "recipe-1",
        "artifactPath": str(art1), "artifactSha256": digest1,
        "benchmarkRunId": "run-ancient"})
    art1.unlink()
    art2 = root / "measured-2.mp4"
    art2.write_bytes(b"healthy-suffix")
    run_create2 = {"payloadHash": "b" * 64, "campaignId": campaign_id,
                   "repetitionGroupId": f"{campaign_id}:recipe-1", "repetitionIndex": 2,
                   "artifact": {"role": "ENCODED", "sha256": _sha(art2.read_bytes()),
                                "byteSize": 14, "mediaContainer": "mp4"}}
    run_create2["payloadHash"] = artifacts.build_payload_hash(run_create2)
    env2 = artifacts.build_artifact_submission_payload(
        artifact_path=str(art2), media_container="mp4", run_create=run_create2)
    atomic_json(root / "submission-000002.json", env2)
    staged, replays = [], []

    def stage(_queue, payload, **_kw):
        staged.append(payload["runCreate"]["repetitionIndex"])
        return f"queued-{payload['runCreate']['repetitionIndex']}", {}

    def replay(*_a, **_kw):
        replays.append(len(staged))
        return spool.ReplayStats(submitted=len(staged))

    with mock.patch.object(main, "fetch_retention_status",
                           side_effect=retention_error) as fetch, \
         mock.patch.object(main, "spool_payload", side_effect=stage), \
         mock.patch.object(main, "replay_spool", side_effect=replay), \
         mock.patch.object(main, "count_pending_entries", return_value=0):
        rc, info = main._publish_saved_campaign_gated(
            queue_dir=str(tmp_path), campaign_id=campaign_id,
            base_url="http://127.0.0.1:9", api_key="", max_storage_mb=2048)
    return rc, info, staged, replays, root, fetch


# ---------------------------------------------------------------------------
# F5
# ---------------------------------------------------------------------------

def test_corrupt_marker_projection_recovers_intact_artifact_and_publishes(tmp_path):
    """The exact review case: intact measured bytes, MISSING envelopes and
    corrupt accepted markers. Pre-fix: zero candidates, zero reconstruction,
    exit 0 with status "published" and zero confirmed uploads. Post-fix the
    intact work is reconstructed, uploaded once, and honestly confirmed."""
    root, measured, artifacts_by_order = _complete_journal(tmp_path)
    corrupt_order = measured[0]
    marker = root / f"submission-{corrupt_order:06d}.accepted.json"
    marker.write_text("{")  # truncated/corrupt marker content
    from client.recovery_projection import project_attempt_groups
    projected = project_attempt_groups(root, root.name)
    assert [item["path"] for item in projected["corruptEntries"]] == [marker.name]
    # Intact bytes are STILL independently inspected candidates.
    assert set(measured) <= set(projected["candidateOrders"])
    sent = []

    def transport(_base, submission, **_kw):
        sent.append(submission)
        return server_bundle(submission, f"run-f5-{len(sent)}")

    with mock.patch.object(main, "check_compatibility", return_value={}), \
         mock.patch.object(main, "encode_to_artifact",
                           side_effect=AssertionError("publish must never encode")), \
         mock.patch.object(main, "ensure_ffmpeg_and_ffprobe", return_value=(True, "ffmpeg test")), \
         mock.patch.object(main, "probe_video_stream_metrics",
                           return_value={"sourceFps": 24, "sourceDurationSeconds": 5,
                                         "containerFormat": "mp4"}), \
         mock.patch.object(spool, "submit_artifact_submission", side_effect=transport):
        rc = main.main(["prog", "--publish-saved", root.name,
                        "--queue-dir", str(tmp_path), "--base-url", "https://example.invalid"])
    assert rc == 0, rc
    orders = {s["runCreate"]["repetitionIndex"] for s in sent}
    # Every measured attempt published exactly once (repetitionIndex counts
    # the measured repetitions, 1..N, not journal execution orders).
    assert len(sent) == len(measured) and orders == set(range(1, len(measured) + 1))
    # The corrupt marker was superseded by a verified v2 proof that PRESERVES
    # the damaged bytes as prior evidence.
    proof = json.loads(marker.read_text())
    assert proof["schemaVersion"] == 2 and proof["uploadConfirmed"] is True
    assert proof["superseded"]["priorEvidence"] == "{"
    assert not artifacts_by_order[corrupt_order].exists()  # retired after proof
    # Idempotent replay: accepted markers authorize; nothing re-uploads.
    with mock.patch.object(main, "check_compatibility", return_value={}), \
         mock.patch.object(main, "ensure_ffmpeg_and_ffprobe", return_value=(True, "ffmpeg test")), \
         mock.patch.object(spool, "submit_artifact_submission",
                           side_effect=AssertionError("replay must not re-upload")):
        assert main.main(["prog", "--publish-saved", root.name,
                          "--queue-dir", str(tmp_path),
                          "--base-url", "https://example.invalid"]) == 0


def test_unresolved_marker_corruption_blocks_final_published(tmp_path):
    """When corruption CANNOT be resolved (the bytes are already proven
    accepted by a durable receipt, so nothing rewrites the corrupt journal
    marker), the final result must not silently claim "published": it is a
    non-success that lists the unresolved corruption and leaves the damaged
    bytes untouched."""
    root, measured, _by_order = _complete_journal(tmp_path)
    sent = []

    def transport(_base, submission, **_kw):
        sent.append(submission)
        return server_bundle(submission, f"run-f5-{len(sent)}")

    with mock.patch.object(main, "check_compatibility", return_value={}), \
         mock.patch.object(main, "ensure_ffmpeg_and_ffprobe", return_value=(True, "ffmpeg test")), \
         mock.patch.object(main, "probe_video_stream_metrics",
                           return_value={"sourceFps": 24, "sourceDurationSeconds": 5,
                                         "containerFormat": "mp4"}), \
         mock.patch.object(spool, "submit_artifact_submission", side_effect=transport):
        assert main.main(["prog", "--publish-saved", root.name,
                          "--queue-dir", str(tmp_path),
                          "--base-url", "https://example.invalid"]) == 0
    # Damage ONE now-verified marker AFTER acceptance; the durable receipt
    # keeps the work honestly accepted, but the journal marker is corrupt.
    victim = root / f"submission-{measured[0]:06d}.accepted.json"
    victim.write_text("{corrupt after acceptance")
    with mock.patch.object(main, "check_compatibility", return_value={}), \
         mock.patch.object(main, "ensure_ffmpeg_and_ffprobe", return_value=(True, "ffmpeg test")), \
         mock.patch.object(spool, "submit_artifact_submission",
                           side_effect=AssertionError("accepted work must not re-upload")):
        rc, info = main._publish_saved_campaign_gated(
            queue_dir=str(tmp_path), campaign_id=root.name,
            base_url="https://example.invalid", api_key="", max_storage_mb=2048)
    assert rc == 1, info
    assert info["status"] == "blocked"
    assert info["failure"]["category"] == "corrupt_evidence"
    assert [item["path"] for item in info["unresolvedJournalCorruption"]] == [victim.name]
    assert victim.read_text() == "{corrupt after acceptance"  # preserved, not erased
    # Healthy siblings stay recoverable: state still proves the accepted work.
    state = main.campaign_recovery_state(str(tmp_path), root.name)
    assert state["acceptedUploads"] == len(measured)
    assert any(action["action"] == "inspect_evidence" for action in state["actions"])


def test_damaged_attempt_sibling_uploads_intact_group_but_stays_non_success(tmp_path):
    """Attempt-level damage must not HIDE or skip the intact group beside it
    — those uploads still happen and keep their confirmations — but the
    unresolved damaged attempt forbids claiming the whole publication
    succeeded."""
    root, measured, _by_order = _complete_journal(tmp_path)
    (root / "attempt-999999.json").write_text("{damaged sibling")
    sent = []

    def transport(_base, submission, **_kw):
        sent.append(submission)
        return server_bundle(submission, f"run-sib-{len(sent)}")

    with mock.patch.object(main, "check_compatibility", return_value={}), \
         mock.patch.object(main, "ensure_ffmpeg_and_ffprobe", return_value=(True, "ffmpeg test")), \
         mock.patch.object(main, "probe_video_stream_metrics",
                           return_value={"sourceFps": 24, "sourceDurationSeconds": 5,
                                         "containerFormat": "mp4"}), \
         mock.patch.object(spool, "submit_artifact_submission", side_effect=transport):
        rc, info = main._publish_saved_campaign_gated(
            queue_dir=str(tmp_path), campaign_id=root.name,
            base_url="https://example.invalid", api_key="", max_storage_mb=2048)
    # The intact group still published, once, with its confirmations kept.
    assert len(sent) == len(measured)
    assert int(info.get("submitted") or 0) == len(measured)
    # Unresolved damage is visible and the overall outcome is non-success.
    assert rc == 1, info
    assert info["status"] == "blocked"
    assert info["failure"]["category"] == "corrupt_evidence"
    assert [item["path"] for item in info["unresolvedJournalCorruption"]] == ["attempt-999999.json"]
    assert (root / "attempt-999999.json").read_text() == "{damaged sibling"
    # Verified siblings stay honestly accepted; healthy state remains usable.
    state = main.campaign_recovery_state(str(tmp_path), root.name)
    assert state["acceptedUploads"] == len(measured)
    assert any(action["action"] == "inspect_evidence" for action in state["actions"])


def test_manifest_projection_failure_is_unresolved_not_published(tmp_path):
    """A damaged frozen plan beside journaled attempts is unresolved
    projection failure: intact envelopes may upload, but the run must never
    claim 'published'."""
    root, measured, _by_order = _complete_journal(tmp_path)
    (root / "manifest.json").write_text("{truncated plan")
    sent = []

    def transport(_base, submission, **_kw):
        sent.append(submission)
        return server_bundle(submission, f"run-man-{len(sent)}")

    with mock.patch.object(main, "check_compatibility", return_value={}), \
         mock.patch.object(main, "ensure_ffmpeg_and_ffprobe", return_value=(True, "ffmpeg test")), \
         mock.patch.object(main, "probe_video_stream_metrics",
                           return_value={"sourceFps": 24, "sourceDurationSeconds": 5,
                                         "containerFormat": "mp4"}), \
         mock.patch.object(spool, "submit_artifact_submission", side_effect=transport):
        rc, info = main._publish_saved_campaign_gated(
            queue_dir=str(tmp_path), campaign_id=root.name,
            base_url="https://example.invalid", api_key="", max_storage_mb=2048)
    assert rc == 1, info
    assert info["status"] == "blocked"
    assert [item["path"] for item in info["unresolvedJournalCorruption"]] == ["manifest.json"]
    assert (root / "manifest.json").read_text() == "{truncated plan"


def test_unreadable_journal_root_never_yields_empty_corruption(tmp_path):
    """A projection that raises must surface as evidence, never as an empty
    corruptEntries list that lets 'published' slip through."""
    root, measured, _by_order = _complete_journal(tmp_path)
    sent = []

    def transport(_base, submission, **_kw):
        sent.append(submission)
        return server_bundle(submission, f"run-exc-{len(sent)}")

    real_project = main.project_attempt_groups
    calls = {"n": 0}

    def flaky_project(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] >= 5:  # before/gate-start/reconstruct/after succeed;
            raise OSError("journal unreadable")  # the FINAL re-projection fails
        return real_project(*args, **kwargs)

    with mock.patch.object(main, "check_compatibility", return_value={}), \
         mock.patch.object(main, "ensure_ffmpeg_and_ffprobe", return_value=(True, "ffmpeg test")), \
         mock.patch.object(main, "probe_video_stream_metrics",
                           return_value={"sourceFps": 24, "sourceDurationSeconds": 5,
                                         "containerFormat": "mp4"}), \
         mock.patch.object(main, "project_attempt_groups", side_effect=flaky_project), \
         mock.patch.object(spool, "submit_artifact_submission", side_effect=transport):
        rc, info = main._publish_saved_campaign_gated(
            queue_dir=str(tmp_path), campaign_id=root.name,
            base_url="https://example.invalid", api_key="", max_storage_mb=2048)
    assert rc == 1, info
    assert info["status"] == "blocked"
    assert info["unresolvedJournalCorruption"][0]["path"] == "journal"
    assert "unreadable" in info["unresolvedJournalCorruption"][0]["reason"]


# ---------------------------------------------------------------------------
# F6
# ---------------------------------------------------------------------------

def test_historical_absence_404_410_is_per_record_not_transport(tmp_path):
    """404/410 = the server says this run/artifact is GONE: honest per-record
    reconciliation work. Transport/5xx stays "unreachable" for retry. Neither
    outcome rewrites the v1 marker."""
    campaign_id = "campaign-000000000000f600"
    root = tmp_path / "campaigns" / campaign_id
    root.mkdir(parents=True)
    artifact = root / "m.mp4"
    artifact.write_bytes(b"retired")
    digest = _sha(artifact.read_bytes())
    run_create = {"payloadHash": "a" * 64, "campaignId": campaign_id,
                  "repetitionGroupId": f"{campaign_id}:recipe-1", "repetitionIndex": 1,
                  "artifact": {"role": "ENCODED", "sha256": digest,
                               "byteSize": 7, "mediaContainer": "mp4"}}
    run_create["payloadHash"] = artifacts.build_payload_hash(run_create)
    env = artifacts.build_artifact_submission_payload(
        artifact_path=str(artifact), media_container="mp4", run_create=run_create)
    artifact.unlink()  # retired bytes: reconciliation is metadata-only
    marker = {"schemaVersion": 1, "executionOrder": 1, "recipeId": "recipe-1",
              "artifactPath": str(artifact), "artifactSha256": digest,
              "benchmarkRunId": "run-ancient"}
    for code, expected in ((404, "unavailable"), (410, "unavailable"),
                           (503, "unreachable"), (None, "unreachable")):
        atomic_json(root / "submission-000001.json", env)
        atomic_json(root / "submission-000001.accepted.json", marker)
        error = SubmitError("gone", retryable=(code is None or code >= 500), status_code=code)
        with mock.patch.object(main, "fetch_retention_status", side_effect=error):
            outcome = main._reconcile_historical_envelope(
                base_url="http://unused", envelope_path=root / "submission-000001.json",
                marker=marker, envelope=env, cancel_event=None)
        assert outcome == expected, (code, outcome)
        # No fabricated confirmation, ever.
        assert json.loads((root / "submission-000001.accepted.json")
                          .read_text())["schemaVersion"] == 1


def test_transport_failure_defers_one_record_and_healthy_suffix_proceeds(tmp_path):
    """A 5xx on the FIRST historical record must not starve the healthy
    suffix: the suffix still stages and replay still runs; the failed record
    keeps its evidence untouched, stays visible with its own disposition, and
    the campaign is honestly deferred (never "published")."""
    rc, info, staged, replays, root, fetch = _historical_case(
        tmp_path, retention_error=SubmitError("retention lookup failed",
                                              retryable=True, status_code=503))
    assert staged == [2] and replays  # suffix staged + replayed despite record 1
    assert rc == 10 and info["status"] == "deferred"
    assert info["deferredReason"] == "reconciliation_unreachable"
    assert info["reconciliationUnreachable"] == 1
    assert info["unresolvedReconciliationPaths"] == ["submission-000001.json"]
    fetch.assert_called_once()  # one bounded GET per record per pass, no storm
    # Evidence for the unresolved record is byte-honest: still v1, no fake ack.
    assert json.loads((root / "submission-000001.accepted.json")
                      .read_text())["schemaVersion"] == 1
    assert (root / "submission-000001.json").is_file()


@pytest.mark.parametrize("code", [404, 410])
def test_permanent_absence_reports_reconciliation_work_not_transport(tmp_path, code):
    """A 404/410 through the FULL publisher (server says this run/artifact is
    gone) is counted as reconciliation work on that record only; the healthy
    suffix still stages and replays."""
    rc, info, staged, replays, root, fetch = _historical_case(
        tmp_path, retention_error=SubmitError("gone", retryable=False, status_code=code))
    assert staged == [2] and replays
    assert int(info.get("awaitingReconciliation") or 0) == 1
    assert not info.get("reconciliationUnreachable")
    assert info["unresolvedReconciliationPaths"] == ["submission-000001.json"]
    assert json.loads((root / "submission-000001.accepted.json")
                      .read_text())["schemaVersion"] == 1
    # The campaign never claims success while a record is unresolved; the
    # absence has its own visible disposition and deferral reason.
    assert rc == 10, info
    assert info["status"] == "deferred"
    assert info["deferredReason"] == "awaiting_reconciliation"


def test_verified_retired_prefix_does_not_block_transient_historical_defer(tmp_path):
    """A previously accepted (verified, receipt-bound) entry whose bytes were
    LEGITIMATELY retired must not be misclassified as missing evidence when a
    DIFFERENT historical record hits a transient 503. The healthy suffix
    stages/replays, the accepted prefix stays accepted with stable IDs, zero
    encodes, zero re-uploads, and the run defers on the unresolved record."""
    campaign_id = "campaign-000000000000f602"
    queue = tmp_path / "queue"
    root = queue / "campaigns" / campaign_id
    root.mkdir(parents=True)
    # Order 1: verified accepted earlier; its artifact was retired normally.
    art1 = root / "measured-1.mp4"
    art1.write_bytes(b"accepted-and-retired")
    env1 = _submission(campaign_id, art1, 1)
    atomic_json(root / "submission-000001.json", env1)
    response1 = server_bundle(env1, "run-accepted")
    local1 = spool.local_hash_for_payload(env1)
    atomic_json(queue / "receipts" / f"{local1}.json", {
        "localHash": local1,
        "payloadIdentity": acknowledgments.local_hash_material(env1),
        "status": "uploaded_analysis_pending",
        "response": response1,
        "acknowledgment": acknowledgments.validate_upload_response(env1, response1)})
    ack1 = acknowledgments.validate_upload_response(env1, response1)
    atomic_json(root / "submission-000001.accepted.json", {
        "schemaVersion": 2, "executionOrder": 1, "recipeId": "recipe-1",
        "artifactPath": str(art1), "artifactSha256": _sha(art1.read_bytes()),
        "benchmarkRunId": "run-accepted",
        "payloadHash": env1["runCreate"]["payloadHash"],
        "artifactId": "artifact-run-accepted", "uploadConfirmed": True,
        "artifactByteSize": art1.stat().st_size,
        "acknowledgment": ack1, "response": response1})
    art1.unlink()
    # Order 2: historical v1 marker, retired bytes, retention fetch FAILS 503.
    art2 = root / "measured-2.mp4"
    art2.write_bytes(b"historical-unknown")
    env2 = _submission(campaign_id, art2, 2)
    atomic_json(root / "submission-000002.json", env2)
    atomic_json(root / "submission-000002.accepted.json", {
        "schemaVersion": 1, "executionOrder": 2, "recipeId": "recipe-1",
        "artifactPath": str(art2), "artifactSha256": _sha(art2.read_bytes()),
        "benchmarkRunId": "run-ancient"})
    art2.unlink()
    # Order 3: healthy suffix with intact bytes.
    art3 = root / "measured-3.mp4"
    art3.write_bytes(b"healthy-suffix")
    env3 = _submission(campaign_id, art3, 3)
    atomic_json(root / "submission-000003.json", env3)
    staged, replays, encodes = [], [], []

    def stage(_queue, payload, **_kw):
        staged.append(payload["runCreate"]["repetitionIndex"])
        return f"queued-{payload['runCreate']['repetitionIndex']}", {}

    def replay(*_a, **_kw):
        replays.append(len(staged))
        return spool.ReplayStats(submitted=len(staged))

    errors = []
    def retention(*_a, **_kw):
        errors.append(SubmitError("retention lookup failed", retryable=True,
                                  status_code=503))
        raise errors[-1]

    with mock.patch.object(main, "fetch_retention_status", side_effect=retention), \
         mock.patch.object(main, "spool_payload", side_effect=stage), \
         mock.patch.object(main, "replay_spool", side_effect=replay), \
         mock.patch.object(main, "encode_to_artifact", side_effect=encodes.append), \
         mock.patch.object(main, "count_pending_entries", return_value=0):
        rc, info = main._publish_saved_campaign_gated(
            queue_dir=str(queue), campaign_id=campaign_id,
            base_url="http://127.0.0.1:9", api_key="", max_storage_mb=2048)
    assert not encodes  # zero encodes, ever
    assert staged == [3] and replays  # healthy suffix staged and replayed
    assert rc == 10, info
    assert info["status"] == "deferred"
    assert info["deferredReason"] == "reconciliation_unreachable"
    assert info["unresolvedReconciliationPaths"] == ["submission-000002.json"]
    # The verified prefix keeps its identity: same run id, same marker,
    # honestly accepted, never re-classified as missing evidence.
    state = main.campaign_recovery_state(str(queue), campaign_id)
    assert state["acceptedUploads"] == 1
    marker1 = json.loads((root / "submission-000001.accepted.json").read_text())
    assert marker1["benchmarkRunId"] == "run-accepted" and marker1["uploadConfirmed"] is True
    # A second pass (reopen) keeps the same stable IDs and re-attempts the
    # unresolved record exactly once more — no evidence drift, no re-upload.
    with mock.patch.object(main, "fetch_retention_status", side_effect=retention), \
         mock.patch.object(main, "spool_payload", side_effect=stage), \
         mock.patch.object(main, "replay_spool", side_effect=replay), \
         mock.patch.object(main, "encode_to_artifact", side_effect=encodes.append), \
         mock.patch.object(main, "count_pending_entries", return_value=0):
        rc2, info2 = main._publish_saved_campaign_gated(
            queue_dir=str(queue), campaign_id=campaign_id,
            base_url="http://127.0.0.1:9", api_key="", max_storage_mb=2048)
    assert rc2 == 10 and info2["deferredReason"] == "reconciliation_unreachable"
    assert json.loads((root / "submission-000001.accepted.json").read_text()) == marker1
    assert len(errors) == 2  # one bounded retry per pass, not a storm
