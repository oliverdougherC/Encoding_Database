"""F8: damaged saved groups cannot starve independent completed measurements."""
import copy
import json
import threading
from unittest import mock

import pytest

from client import acknowledgments, main, spool
from test_publication_recovery_integrity import _complete_journal
from test_spool import server_bundle


def _snapshot_measurements(root):
    return {path.name: path.read_bytes() for path in root.iterdir()
            if path.name in ("manifest.json", "campaign-complete.json")
            or path.name.startswith(("attempt-", "environment-"))}


@pytest.mark.parametrize("damage", ["missing", "hash-mismatch"])
@pytest.mark.parametrize("bad_group_first", [True, False])
@pytest.mark.parametrize("damaged_member", [0, -1])
def test_saved_recovery_isolates_damaged_complete_group(
        tmp_path, damage, bad_group_first, damaged_member):
    # Build actual production journals and freeze the envelopes the live path
    # produced, then recreate the interruption boundary before envelope writes.
    expected = {}
    root, _, artifacts = _complete_journal(
        tmp_path, crfs=(24, 26), captured_envelopes=expected)
    groups = {}
    for path in sorted(root.glob("attempt-*.json")):
        record = json.loads(path.read_text())
        schedule = record["schedule"]
        if schedule["phase"] == "measured":
            groups.setdefault(schedule["recipe_id"], []).append(schedule["execution_order"])
    assert len(groups) == 2 and all(len(orders) == 2 for orders in groups.values())
    group_ids = list(groups)
    bad_group = group_ids[0 if bad_group_first else 1]
    healthy_group = group_ids[1 if bad_group_first else 0]
    broken_order = groups[bad_group][damaged_member]
    broken = artifacts[broken_order]
    if damage == "missing":
        broken.unlink()
    else:
        broken.write_bytes(b"damaged evidence must remain untouched")
    before = _snapshot_measurements(root)
    damaged_bytes = {order: path.read_bytes() if path.exists() else None
                     for order, path in artifacts.items() if order in groups[bad_group]}
    healthy = {expected[f"submission-{order:06d}.json"]["runCreate"]["payloadHash"]:
               expected[f"submission-{order:06d}.json"]["runCreate"]
               for order in groups[healthy_group]}
    sent = []

    def transport(_base, submission, **_kwargs):
        create = submission["runCreate"]
        assert create["payloadHash"] in healthy, "No member of the damaged group may be reconstructed"
        assert create == healthy[create["payloadHash"]], "Recovery must preserve the exact live payload identity"
        sent.append(copy.deepcopy(submission))
        return server_bundle(submission, "run-f8-" + create["payloadHash"][:12])

    with mock.patch.object(main, "encode_to_artifact", side_effect=AssertionError("Recovery must not encode")) as encode, \
         mock.patch.object(main, "_prepare_named_suite_clip", side_effect=AssertionError("Recovery must not acquire sources")) as source, \
         mock.patch.object(main, "ensure_ffmpeg_and_ffprobe", return_value=(True, "ffmpeg test")), \
         mock.patch.object(main, "probe_video_stream_metrics", return_value={
             "sourceFps": 24, "sourceDurationSeconds": 5, "containerFormat": "mp4"}), \
         mock.patch.object(spool, "submit_artifact_submission", side_effect=transport):
        for invocation in range(3):
            rc, info = main.publish_saved_campaign(
                queue_dir=str(tmp_path), campaign_id=root.name,
                base_url="https://example.invalid", api_key="", max_storage_mb=2048)
            assert len(sent) == 2, "The independent healthy group must publish in the first recovery pass"
            assert rc == 1 and info["status"] == "blocked", info
            assert info["submitted"] == (2 if invocation == 0 else 0)
            failures = info["reconstruction"]["failures"]
            assert any(f["recipeId"] == bad_group and f["executionOrder"] == broken_order for f in failures)
            assert _snapshot_measurements(root) == before
            for order in groups[bad_group]:
                assert not (root / f"submission-{order:06d}.json").exists()
                assert not (root / f"submission-{order:06d}.accepted.json").exists()
                path = artifacts[order]
                assert (path.read_bytes() if path.exists() else None) == damaged_bytes[order]
            for order in groups[healthy_group]:
                marker = json.loads((root / f"submission-{order:06d}.accepted.json").read_text())
                original = expected[f"submission-{order:06d}.json"]
                assert marker["payloadHash"] == original["runCreate"]["payloadHash"]
                assert marker["uploadConfirmed"] is True
                local_hash = spool.local_hash_for_payload(original)
                receipt = json.loads((tmp_path / "receipts" / f"{local_hash}.json").read_text())
                assert acknowledgments.receipt_verdict(local_hash, receipt, original) == "verified"
            assert spool.count_pending_entries(str(tmp_path)) == 0
    encode.assert_not_called()
    source.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("protocolVersion", "incompatible"),
    ("clientVersion", "client/0.0.0"),
    ("runtime", {"ffmpeg": {"sha256": "different-runtime"}}),
])
def test_global_frozen_identity_failure_still_stops_all_reconstruction(tmp_path, field, value):
    root, _, _ = _complete_journal(tmp_path, crfs=(24, 26))
    manifest = json.loads((root / "manifest.json").read_text())
    manifest[field] = value
    (root / "manifest.json").write_text(json.dumps(manifest))
    before = _snapshot_measurements(root)
    with mock.patch.object(main, "encode_to_artifact", side_effect=AssertionError("Must not encode")), \
         mock.patch.object(main, "probe_video_stream_metrics", side_effect=AssertionError("Global failure precedes reconstruction")):
        outcome = main._reconstruct_saved_submissions(
            queue_dir=str(tmp_path), campaign_id=root.name, max_storage_mb=2048)
    assert outcome["failure"] and outcome["reconstructed"] == 0
    assert not outcome["failures"]  # The whole frozen plan is incompatible, not one damaged group.
    assert not list(root.glob("submission-*.json"))
    assert _snapshot_measurements(root) == before


def test_cancellation_prevents_materializing_or_uploading_buffered_groups(tmp_path):
    root, _, _ = _complete_journal(tmp_path, crfs=(24, 26))
    before = _snapshot_measurements(root)
    stop = threading.Event()

    def cancel_probe(_path):
        stop.set()
        return {"sourceFps": 24, "sourceDurationSeconds": 5, "containerFormat": "mp4"}

    with mock.patch.object(main, "ensure_ffmpeg_and_ffprobe", return_value=(True, "ffmpeg test")), \
         mock.patch.object(main, "probe_video_stream_metrics", side_effect=cancel_probe), \
         mock.patch.object(main, "encode_to_artifact", side_effect=AssertionError("Must not encode")), \
         mock.patch.object(spool, "submit_artifact_submission", side_effect=AssertionError("Cancelled recovery must not upload")):
        rc, info = main.publish_saved_campaign(
            queue_dir=str(tmp_path), campaign_id=root.name, base_url="https://example.invalid",
            api_key="", max_storage_mb=2048, cancel_event=stop)
    assert rc == 10 and info["status"] == "cancelled"
    assert info["reconstruction"]["cancelled"]
    assert not list(root.glob("submission-*.json"))
    assert _snapshot_measurements(root) == before


def test_one_group_envelope_write_failure_does_not_hide_new_healthy_envelopes(tmp_path):
    expected = {}
    root, _, _ = _complete_journal(tmp_path, crfs=(24, 26), captured_envelopes=expected)
    first_name = sorted(expected)[0]
    blocked_group = expected[first_name]["runCreate"]["repetitionGroupId"]
    original_write = main.atomic_json
    sent = []

    def write(path, payload):
        if path.name == first_name:
            raise OSError("controlled envelope persistence failure")
        return original_write(path, payload)

    def transport(_base, submission, **_kwargs):
        assert submission["runCreate"]["repetitionGroupId"] != blocked_group
        sent.append(submission)
        return server_bundle(submission, f"run-f8-write-{len(sent)}")

    with mock.patch.object(main, "atomic_json", side_effect=write), \
         mock.patch.object(main, "ensure_ffmpeg_and_ffprobe", return_value=(True, "ffmpeg test")), \
         mock.patch.object(main, "probe_video_stream_metrics", return_value={
             "sourceFps": 24, "sourceDurationSeconds": 5, "containerFormat": "mp4"}), \
         mock.patch.object(main, "encode_to_artifact", side_effect=AssertionError("Must not encode")), \
         mock.patch.object(spool, "submit_artifact_submission", side_effect=transport):
        rc, info = main.publish_saved_campaign(
            queue_dir=str(tmp_path), campaign_id=root.name, base_url="https://example.invalid",
            api_key="", max_storage_mb=2048)
    assert rc == 1 and info["status"] == "blocked"
    assert len(sent) == info["submitted"] == 2
    assert info["reconstruction"]["failures"][0]["path"] == first_name
