"""F7 (PLA-580): the WHOLE retry/maintenance lifecycle holds the host-level
publication exclusion BEFORE its first receipt/journal/filesystem mutation.

These tests use REAL distinct processes: a collector child owns the exclusive
measurement phase (possibly while working a DIFFERENT queue directory), and the
parent exercises the deferred publication path. Both acquisition orders are
covered: collector-first (retry must defer with evidence byte-identical) and
publication-first (the collector start is refused). After release, the retry
completes idempotently — the verified receipt drains exactly once and no
artifact is ever re-uploaded.
"""

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from client import acknowledgments, artifacts, main, spool
from client.campaign import atomic_json
from test_spool import server_bundle


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _snapshot(base: Path) -> dict:
    out = {}
    for path in sorted(base.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(base))] = _sha(path.read_bytes())
    return out


def _seed_receipted_queue(tmp_path: Path, campaign_id: str = "campaign-000000000000f701"):
    """A pending queue entry whose VERIFIED receipt is already committed:
    drain_committed_receipts would write the journal marker and delete the
    artifact the moment it runs — exactly the mutation F7 must gate."""
    queue = tmp_path / "queue-a"
    root = queue / "campaigns" / campaign_id
    root.mkdir(parents=True)
    artifact = root / "measured.mp4"
    artifact.write_bytes(b"upload-confirmed-bytes")
    blob = artifact.read_bytes()
    run_create = {
        "payloadHash": "a" * 64,
        "campaignId": campaign_id,
        "repetitionGroupId": f"{campaign_id}:recipe-1",
        "repetitionIndex": 1,
        "artifact": {"role": "ENCODED", "sha256": _sha(blob), "byteSize": len(blob),
                     "mediaContainer": "mp4"},
    }
    run_create["payloadHash"] = artifacts.build_payload_hash(run_create)
    payload = artifacts.build_artifact_submission_payload(
        artifact_path=str(artifact), media_container="mp4", run_create=run_create)
    atomic_json(root / "submission-000001.json", payload)
    path, _entry = spool.spool_payload(str(queue), payload)
    local_hash = spool.local_hash_for_payload(payload)
    response = server_bundle(payload, "run-f7")
    atomic_json(queue / "receipts" / f"{local_hash}.json", {
        "localHash": local_hash,
        "payloadIdentity": acknowledgments.local_hash_material(payload),
        "status": "uploaded_analysis_pending",
        "response": response,
        "acknowledgment": acknowledgments.validate_upload_response(payload, response),
    })
    return queue, root, path, local_hash


def _collector_child(phase_dir: Path, other_queue: Path):
    """Real second process: holds the exclusive measurement phase (a collector
    working a DIFFERENT queue still owns the host phase)."""
    script = (
        "import os, sys, time\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "from client.spool import host_phase_hold\n"
        "hold = host_phase_hold('measurement')\n"
        "hold.__enter__()\n"
        "print('HELD', flush=True)\n"
        "time.sleep(30)\n")
    env = dict(os.environ, ENCODINGDB_HOST_PHASE_DIR=str(phase_dir),
               ENCODINGDB_QUEUE_DIR=str(other_queue))
    proc = subprocess.Popen([sys.executable, "-c", script], env=env,
                            stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "HELD", "collector child never acquired phase"
    return proc


@pytest.mark.parametrize("collector_queue", ["same", "different"])
def test_retry_due_uploads_defers_before_any_mutation_when_collector_holds_first(
        tmp_path, collector_queue):
    """A collector owns the exclusive measurement phase (kernel host lock) —
    either while working THIS queue or a DIFFERENT one; both layouts share
    the host phase, and neither may see a single byte mutated by retry."""
    phase_dir = tmp_path / "host-phase"
    phase_dir.mkdir()
    other_queue = (tmp_path / "queue-a" if collector_queue == "same"
                   else tmp_path / "queue-b")  # the collector's own queue
    other_queue.mkdir()
    queue, root, entry_path, _hash = _seed_receipted_queue(tmp_path)
    proc = _collector_child(phase_dir, other_queue)
    try:
        before = _snapshot(tmp_path)
        with mock.patch.dict(os.environ, {"ENCODINGDB_HOST_PHASE_DIR": str(phase_dir)}), \
             mock.patch.object(spool, "submit_artifact_submission",
                               side_effect=AssertionError("deferred retry must not upload")):
            rc, info = main.retry_due_uploads(
                queue_dir=str(queue), base_url="http://127.0.0.1:9", api_key="", retries=1)
        assert rc == 10, info
        assert info["status"] == "deferred"
        assert info["deferredReason"] == "measurement_exclusion"
        assert info["drainedResiduals"] == 0
        # The deferred path left EVERY byte unchanged: no receipt drain, no
        # journal marker, no artifact or queue-entry deletion.
        assert _snapshot(tmp_path) == before
        assert Path(entry_path).is_file()
        assert not (root / "submission-000001.accepted.json").exists()
    finally:
        proc.kill()
        proc.wait(5)


def test_retry_completes_after_release_and_is_idempotent(tmp_path):
    phase_dir = tmp_path / "host-phase"
    phase_dir.mkdir()
    queue, root, entry_path, _hash = _seed_receipted_queue(tmp_path)
    proc = _collector_child(phase_dir, tmp_path / "queue-b")
    with mock.patch.dict(os.environ, {"ENCODINGDB_HOST_PHASE_DIR": str(phase_dir)}):
        rc, info = main.retry_due_uploads(
            queue_dir=str(queue), base_url="http://127.0.0.1:9", api_key="", retries=1)
    assert rc == 10 and info["status"] == "deferred"
    proc.kill()
    proc.wait(5)
    deadline = time.monotonic() + 5
    while spool.host_phase_busy() and time.monotonic() < deadline:
        time.sleep(0.01)
    with mock.patch.dict(os.environ, {"ENCODINGDB_HOST_PHASE_DIR": str(phase_dir)}), \
         mock.patch.object(spool, "submit_artifact_submission",
                           side_effect=AssertionError("verified receipt: no re-upload")):
        rc2, info2 = main.retry_due_uploads(
            queue_dir=str(queue), base_url="http://127.0.0.1:9", api_key="", retries=1)
    assert rc2 == 0, info2
    assert info2["status"] == "published"
    assert info2["drainedResiduals"] == 1
    marker = json.loads((root / "submission-000001.accepted.json").read_text())
    assert marker["uploadConfirmed"] is True and marker["schemaVersion"] == 2
    assert not Path(entry_path).is_file()
    # Repeating after release is idempotent: nothing left to drain, nothing
    # re-uploaded (the transport mock would have raised).
    with mock.patch.dict(os.environ, {"ENCODINGDB_HOST_PHASE_DIR": str(phase_dir)}), \
         mock.patch.object(spool, "submit_artifact_submission",
                           side_effect=AssertionError("idempotent retry: no re-upload")):
        rc3, info3 = main.retry_due_uploads(
            queue_dir=str(queue), base_url="http://127.0.0.1:9", api_key="", retries=1)
    assert rc3 == 0 and info3["status"] == "published"
    assert info3["drainedResiduals"] == 0


def test_collector_start_is_refused_while_publication_holds_first(tmp_path):
    """Opposite acquisition order: a publication pass that started first keeps
    a collector from entering its measurement phase on this host."""
    phase_dir = tmp_path / "host-phase"
    phase_dir.mkdir()
    with mock.patch.dict(os.environ, {"ENCODINGDB_HOST_PHASE_DIR": str(phase_dir)}):
        with spool.host_phase_hold("publication"):
            script = (
                "import os, sys\n"
                f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
                "from client.spool import SpoolCapacityError, host_phase_hold\n"
                "try:\n"
                "    with host_phase_hold('measurement'):\n"
                "        print('ACQUIRED', flush=True)\n"
                "except SpoolCapacityError:\n"
                "    print('REFUSED', flush=True)\n")
            proc = subprocess.Popen([sys.executable, "-c", script],
                                    stdout=subprocess.PIPE, text=True)
            try:
                assert proc.stdout.readline().strip() == "REFUSED"
            finally:
                proc.wait(10)


def test_cleanup_spool_waits_for_the_measurement_exclusion(tmp_path):
    """Sibling cleanup path: cleanup deletes dead-letter media and orphaned
    managed artifacts, so it must defer (raising) while a collector measures,
    leaving every file intact."""
    phase_dir = tmp_path / "host-phase"
    phase_dir.mkdir()
    queue = tmp_path / "queue-a"
    queue.mkdir()
    dead = queue / "dead-letter"
    dead.mkdir()
    (dead / "reject-abcdef.json").write_text('{"reason": "fixture"}')
    (dead / "abcdef.mp4").write_bytes(b"terminal media")
    proc = _collector_child(phase_dir, tmp_path / "queue-b")
    try:
        before = _snapshot(queue)
        with mock.patch.dict(os.environ, {"ENCODINGDB_HOST_PHASE_DIR": str(phase_dir)}):
            with pytest.raises(spool.SpoolCapacityError):
                spool.cleanup_spool(str(queue))
        assert _snapshot(queue) == before
    finally:
        proc.kill()
        proc.wait(5)
    deadline = time.monotonic() + 5
    while spool.host_phase_busy() and time.monotonic() < deadline:
        time.sleep(0.01)
    with mock.patch.dict(os.environ, {"ENCODINGDB_HOST_PHASE_DIR": str(phase_dir)}):
        stats = spool.cleanup_spool(str(queue))
    assert stats.removed_dead_letter_files >= 1


def test_windows_gui_retry_worker_routes_through_the_gate(tmp_path):
    """The actual Windows GUI Retry/idle consumer (`_retry_uploads_worker`)
    calls the IMPORTED gated `retry_due_uploads`: with a real collector child
    holding the measurement phase, the worker reports a deferred status and
    the queue/journal bytes stay untouched."""
    from test_windows_gui import GuiLifecycleTests
    phase_dir = tmp_path / "host-phase"
    phase_dir.mkdir()
    queue, root, entry_path, _hash = _seed_receipted_queue(tmp_path)
    proc = _collector_child(phase_dir, tmp_path / "queue-b")
    try:
        before = _snapshot(tmp_path)
        app, _root, _bindings, _tk = GuiLifecycleTests().build()
        with mock.patch.dict(os.environ, {"ENCODINGDB_HOST_PHASE_DIR": str(phase_dir)}):
            app._retry_uploads_worker(str(queue), "http://127.0.0.1:9", "", 1)
        kind, message = app.event_queue.get_nowait()
        assert kind == "upload_status"
        assert "status=deferred" in message, message
        assert _snapshot(tmp_path) == before
        assert Path(entry_path).is_file()
        assert not (root / "submission-000001.accepted.json").exists()
    finally:
        proc.kill()
        proc.wait(5)