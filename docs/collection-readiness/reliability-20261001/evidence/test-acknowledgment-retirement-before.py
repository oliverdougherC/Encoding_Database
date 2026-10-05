"""F4: validated acknowledgment must authorize every retirement.

Regressions for PR #23 review finding F4: malformed/empty/wrong-identity
receipts, HTTP 200 {} bodies and unrelated acknowledgments must NEVER retire
a pending queue entry, its managed artifact bytes, or journal evidence.
Every scenario imports production modules and exercises real entry points
(spool drain/replay/admission, the actual artifact transport against a
contract-faithful local backend, publish_saved_campaign, recovery
projection). No encode and no real network occurs.
"""

import hashlib
import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar, List, Optional
from unittest import mock

import pytest

from client import acknowledgments, artifacts, campaign, main, spool
from client.campaign import atomic_json
from client.network import SubmitError


# --------------------------------------------------------------------------
# contract-faithful fixtures
# --------------------------------------------------------------------------

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run_create(*, sha: str, size: int, payload_hash: str,
                campaign_id: str = "campaign-0000000000000001", order: int = 1) -> dict:
    return {
        "payloadHash": payload_hash,
        "campaignId": campaign_id,
        "repetitionGroupId": f"{campaign_id}:recipe-{order}",
        "repetitionIndex": order,
        "artifact": {"role": "ENCODED", "sha256": sha, "byteSize": size, "mediaContainer": "mp4"},
    }


def _submission_payload(tmp_path: Path, *, name: str = "artifact.mp4", payload_hash: str,
                        campaign_id: str = "campaign-0000000000000001", order: int = 1) -> dict:
    artifact = tmp_path / name
    blob = f"synthetic bytes for {payload_hash[:8]}".encode()
    artifact.write_bytes(blob)
    run_create = _run_create(sha=_sha(blob), size=len(blob), payload_hash=payload_hash,
                             campaign_id=campaign_id, order=order)
    # Faithful contract: the stored payloadHash equals the canonical hash
    # of the runCreate object (computed over the seed identity fields).
    run_create["payloadHash"] = artifacts.build_payload_hash(run_create)
    return artifacts.build_artifact_submission_payload(
        artifact_path=str(artifact), media_container="mp4", run_create=run_create)


def _ph(payload: dict) -> str:
    """The immutable payloadHash this payload is actually bound to."""
    return payload["runCreate"]["payloadHash"]


def _receipt(queue: Path, payload: dict, *, run_id: str, storage_state: str = "RETAINED",
             status: str = "uploaded_analysis_pending", run_payload_hash: Optional[str] = None,
             foreign_run: bool = False, corrupt: Optional[str] = None) -> Path:
    from test_spool import server_bundle
    stem = spool.local_hash_for_payload(payload)
    receipt = queue / "receipts" / f"{stem}.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    if corrupt is not None:
        receipt.write_text(corrupt)
        return receipt
    run_overrides = {"payloadHash": run_payload_hash} if run_payload_hash else None
    artifact_overrides = None
    if foreign_run:
        run_overrides = {"id": f"other-{run_id}", "payloadHash": "e" * 64}
        artifact_overrides = {"benchmarkRunId": f"other-{run_id}", "id": f"artifact-other-{run_id}"}
    response = server_bundle(payload, run_id, storage_state=storage_state,
                             run_overrides=run_overrides,
                             artifact_overrides=artifact_overrides)
    receipt_value = {
        "localHash": stem,
        "uploadedAt": 1.0,
        "status": status,
        "response": response,
    }
    # Faithful production shape: the fresh commit persists the validated
    # bound acknowledgment alongside the response.
    acknowledgment = acknowledgments.validate_upload_response(payload, response)
    if acknowledgment is not None:
        receipt_value["acknowledgment"] = acknowledgment
    atomic_json(receipt, receipt_value)
    return receipt


class _BackendHandler(BaseHTTPRequestHandler):
    """Minimal contract-faithful v7 backend. Run create dedupes by
    payloadHash; authorization and PUT echo bundleToResponse evidence
    (including the server-side F4 additions payloadHash/benchmarkRunId)."""
    protocol_version = "HTTP/1.1"
    runs: ClassVar[dict] = {}
    seen: ClassVar[List[str]] = []
    mode: ClassVar[str] = "ok"  # ok | empty-put | foreign-put | foreign-auth-shortcut

    def _json(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    @staticmethod
    def _bundle(run: dict) -> dict:
        uploaded = run["uploaded"]
        return {
            "benchmarkRun": {"id": run["id"], "status": "ACCEPTED" if uploaded else "PENDING",
                             "statusReason": None, "workloadId": None,
                             "payloadHash": run["payloadHash"]},
            "artifact": {"id": f"artifact-{run['id']}", "benchmarkRunId": run["id"],
                         "role": "ENCODED", "sha256": run["sha256"], "byteSize": run["byteSize"],
                         "storageState": "RETAINED" if uploaded else "PENDING",
                         "stateReason": None, "mediaContainer": "mp4",
                         "storageKey": f"objects/{run['sha256']}", "uploadedAt": None,
                         "verifiedAt": None, "retainedAt": None, "deletedAt": None},
            "analyses": [{"id": f"analysis-{run['id']}", "status": "COMPLETE"}] if uploaded else [],
        }

    @classmethod
    def _foreign(cls) -> dict:
        return cls._bundle({"id": "run-unrelated", "payloadHash": "f" * 64,
                            "sha256": "9" * 64, "byteSize": 7, "uploaded": True})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/v7/benchmark-runs":
            type(self).seen.append("create")
            key = str(body.get("payloadHash"))
            run = type(self).runs.get(key)
            if run is None:
                run = {"id": f"run-{len(type(self).runs) + 1}", "payloadHash": key,
                       "sha256": body["artifact"]["sha256"],
                       "byteSize": int(body["artifact"]["byteSize"]), "uploaded": False}
                type(self).runs[key] = run
            exposed = dict(run)
            if type(self).mode == "foreign-auth-shortcut":
                exposed["uploaded"] = False  # force the client into auth
            self._json(200 if exposed["uploaded"] else 201,
                       {"created": not exposed["uploaded"], **self._bundle(exposed)})
            return
        if self.path.endswith("/upload-authorizations"):
            type(self).seen.append("auth")
            run_id = self.path.split("/")[3]
            run = next((r for r in type(self).runs.values() if r["id"] == run_id), None)
            if run is not None and run["uploaded"]:
                if type(self).mode == "foreign-auth-shortcut":
                    self._json(200, {"uploadRequired": False, "reason": "artifact-already-bound",
                                     **self._foreign()})
                    return
                self._json(200, {"uploadRequired": False, "reason": "artifact-already-bound",
                                 **self._bundle(run)})
                return
            self._json(200, {"uploadRequired": True, "token": "tok-1",
                             "expiresAt": "2099-01-01T00:00:00.000Z"})
            return
        self._json(404, {"error": "unused"})

    def do_PUT(self):
        type(self).seen.append("put")
        remaining = int(self.headers.get("Content-Length", "0"))
        while remaining > 0:
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
        run = next(iter(type(self).runs.values()))
        run["uploaded"] = True
        if type(self).mode == "empty-put":
            self._json(200, {})
            return
        if type(self).mode == "foreign-put":
            self._json(200, self._foreign())
            return
        self._json(200, self._bundle(run))

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def _start(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


@pytest.fixture(autouse=True)
def _reset_backend():
    _BackendHandler.runs = {}
    _BackendHandler.seen = []
    _BackendHandler.mode = "ok"
    yield


def _journal(tmp_path: Path, campaign_id: str, payload: dict, *, order: int = 1) -> Path:
    root = tmp_path / "queue" / "campaigns" / campaign_id
    root.mkdir(parents=True, exist_ok=True)
    atomic_json(root / f"submission-{order:06d}.json", payload)
    return root


# --------------------------------------------------------------------------
# 1. corrupt receipts never authorize retirement (leader's repro, as regressions)
# --------------------------------------------------------------------------

def _historical_receipt_text(payload: dict) -> str:
    return json.dumps({"localHash": spool.local_hash_for_payload(payload),
                       "status": "uploaded_analysis_pending",
                       "response": {"benchmarkRun": {"id": "run-legacy-unproven"}}})


@pytest.mark.parametrize("build_corrupt", [
    lambda payload: '{"localHash":',
    lambda payload: '{}',
    lambda payload: json.dumps({"schemaVersion": 1, "localHash": "0" * 64, "response": {}}),
    _historical_receipt_text,
], ids=["truncated", "empty-object", "wrong-local-identity", "historical-run-id-only"])
def test_corrupt_receipt_retains_only_queued_copy(tmp_path, build_corrupt):
    """The mandatory fixture: only the managed queued copy survives.

    A malformed receipt must NOT retire the pending entry or the ONLY intact
    copy of the artifact bytes, and it must not delete the corrupt evidence.
    """
    queue = tmp_path / "queue"
    payload = _submission_payload(tmp_path, payload_hash="a" * 64)
    pending, entry = spool.spool_payload(str(queue), payload)
    managed = Path(entry["payload"]["artifactPath"])
    managed_bytes = managed.read_bytes()
    Path(payload["artifactPath"]).unlink()  # only the queued copy remains
    receipt = _receipt(queue, payload, run_id="unused", corrupt=build_corrupt(payload))
    before = receipt.read_bytes()
    assert spool.drain_committed_receipts(str(queue)) == 0
    assert Path(pending).exists()
    assert managed.exists()
    assert managed.read_bytes() == managed_bytes
    assert receipt.read_bytes() == before  # corrupt evidence preserved
    state = spool.receipt_reconciliation_state(str(queue))
    assert [item["path"] for item in state] == [str(receipt)]
    assert state[0]["verdict"].startswith("unverified:")
    # Stable identity: the retained entry keeps its original IDs/deadlines.
    retained = spool.load_spool_entry(pending)
    assert retained["localHash"] == entry["localHash"]
    assert retained["retryDeadlineAt"] == entry["retryDeadlineAt"]
    assert retained["nextAttemptAt"] == entry["nextAttemptAt"]
    assert retained["queuedAt"] == entry["queuedAt"]


def test_wrong_run_and_wrong_payload_hash_receipts_retain_evidence(tmp_path):
    queue = tmp_path / "queue"
    payload = _submission_payload(tmp_path, payload_hash="a" * 64)
    pending, entry = spool.spool_payload(str(queue), payload)
    _receipt(queue, payload, run_id="run-x", foreign_run=True)
    assert spool.drain_committed_receipts(str(queue)) == 0
    assert Path(pending).exists() and Path(entry["payload"]["artifactPath"]).exists()
    queue2 = tmp_path / "queue2"
    payload2 = _submission_payload(tmp_path, name="other.mp4", payload_hash="b" * 64)
    pending2, entry2 = spool.spool_payload(str(queue2), payload2)
    _receipt(queue2, payload2, run_id="run-y", run_payload_hash="c" * 64)
    assert spool.drain_committed_receipts(str(queue2)) == 0
    assert Path(pending2).exists()
    assert Path(entry2["payload"]["artifactPath"]).exists()


def test_non_upload_storage_state_is_not_an_acknowledgment(tmp_path):
    queue = tmp_path / "queue"
    payload = _submission_payload(tmp_path, payload_hash="a" * 64)
    pending, entry = spool.spool_payload(str(queue), payload)
    _receipt(queue, payload, run_id="run-p", storage_state="PENDING")
    assert spool.drain_committed_receipts(str(queue)) == 0
    assert Path(pending).exists()
    assert Path(entry["payload"]["artifactPath"]).exists()


# --------------------------------------------------------------------------
# 2. valid receipts retire exactly once; journal evidence carries full binding
# --------------------------------------------------------------------------

def test_valid_receipt_drains_and_self_publishes_bound_journal_marker(tmp_path):
    queue = tmp_path / "queue"
    campaign_id = "campaign-0000000000000002"
    payload = _submission_payload(tmp_path, payload_hash="d" * 64, campaign_id=campaign_id)
    pending, entry = spool.spool_payload(str(queue), payload)
    managed = Path(entry["payload"]["artifactPath"])
    root = _journal(tmp_path, campaign_id, payload)
    _receipt(queue, payload, run_id="run-verified")
    assert spool.drain_committed_receipts(str(queue)) == 1
    assert not Path(pending).exists()
    assert not managed.exists()
    marker = json.loads((root / "submission-000001.accepted.json").read_text())
    assert marker["schemaVersion"] == 2
    assert marker["benchmarkRunId"] == "run-verified"
    assert marker["payloadHash"] == _ph(payload)
    assert marker["artifactId"] == "artifact-run-verified"
    assert marker["artifactByteSize"] == payload["artifactByteSize"]
    assert marker["uploadConfirmed"] is True
    assert "analysisAccepted" in marker


def test_fresh_success_receipt_records_upload_confirmed_not_analysis_accepted(tmp_path):
    queue = tmp_path / "queue"
    payload = _submission_payload(tmp_path, payload_hash="a" * 64)
    path, entry = spool.spool_payload(str(queue), payload)
    from test_spool import server_bundle
    with mock.patch.object(spool, "submit_artifact_submission",
                           return_value=server_bundle(payload, "run-fresh", storage_state="UPLOADED")):
        status, message = spool.submit_spooled_path(
            path, queue_dir=str(queue), base_url="unused", api_key="", retries=0, use_token=False)
    assert status == "submitted" and message == "run-fresh"
    receipt = json.loads((queue / "receipts" / f"{entry['localHash']}.json").read_text())
    assert receipt["status"] == "uploaded_analysis_pending"
    assert receipt["response"]["benchmarkRun"]["payloadHash"] == _ph(payload)
    evidence = spool.verified_receipt_evidence(str(queue), entry["localHash"])
    assert evidence["benchmarkRunId"] == "run-fresh"
    assert evidence["artifactId"] == "artifact-run-fresh"
    assert evidence["uploadConfirmed"] is True
    assert evidence["analysisAccepted"] is False  # UPLOADED without analyses rows


# --------------------------------------------------------------------------
# 3. unverified responses never count as submitted (queue layer)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("verdict_response", [
    {},                                        # HTTP 200 {}
    {"analyses": [{"vmafMean": 95.25}]},       # unrelated metrics-only body
    {"benchmarkRun": {"id": "run-bare"}},      # historical simplified success shape
    None,
], ids=["empty-object", "metrics-only", "bare-run-id", "none"])
def test_unverified_transport_response_retains_entry_with_stable_identity(tmp_path, verdict_response):
    queue = tmp_path / "queue"
    payload = _submission_payload(tmp_path, payload_hash="a" * 64)
    path, entry = spool.spool_payload(str(queue), payload)
    managed = Path(entry["payload"]["artifactPath"])
    with mock.patch.object(spool, "submit_artifact_submission", return_value=verdict_response):
        status, message = spool.submit_spooled_path(
            path, queue_dir=str(queue), base_url="unused", api_key="", retries=0, use_token=False)
    assert status == "retained"
    assert "unverified" in message
    assert Path(path).exists() and managed.exists()
    retained = spool.load_spool_entry(path)
    assert retained["localHash"] == entry["localHash"]
    assert retained["retryDeadlineAt"] == entry["retryDeadlineAt"]
    assert not (queue / "receipts").exists()
    assert not (queue / "campaigns").exists() or not list((queue / "campaigns").rglob("*.accepted.json"))
    fields = main._submit_failure_fields("retained", message)
    assert fields["errorCategory"] == "unverified_acknowledgment"
    assert fields["recoveryAction"]


def test_admission_shortcut_requires_validated_receipt(tmp_path):
    queue = tmp_path / "queue"
    payload = _submission_payload(tmp_path, payload_hash="a" * 64)
    bad = _receipt(queue, payload, run_id="unproven",
                   corrupt=json.dumps({"benchmarkRunId": "already-submitted"}))
    admission_path, _entry = spool.spool_payload(str(queue), payload, max_storage_mb=1024)
    # Unverified receipt: admission cannot shortcut; a real pending entry forms.
    assert Path(admission_path).parent == queue
    assert bad.read_bytes() == b'{"benchmarkRunId": "already-submitted"}'


def test_admission_shortcut_valid_receipt_untouched(tmp_path):
    queue = tmp_path / "queue"
    payload = _submission_payload(tmp_path, payload_hash="a" * 64)
    receipt = _receipt(queue, payload, run_id="run-good")
    original = receipt.read_bytes()
    path, _entry = spool.spool_payload(str(queue), payload, max_storage_mb=0)
    assert path == str(receipt)
    assert receipt.read_bytes() == original


# --------------------------------------------------------------------------
# 4. the actual transport binds the created run id and the immutable payload
# --------------------------------------------------------------------------

def test_transport_accepts_faithful_flow_and_no_duplicate_run(tmp_path):
    server, base_url = _start(_BackendHandler)
    try:
        submission = _submission_payload(tmp_path, payload_hash="a" * 64)
        first = artifacts.submit_artifact_submission(base_url, submission)
        assert first["benchmarkRun"]["payloadHash"] == _ph(submission)
        second = artifacts.submit_artifact_submission(base_url, submission)
        assert second["benchmarkRun"]["id"] == first["benchmarkRun"]["id"]
        assert len(_BackendHandler.runs) == 1
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("mode", ["empty-put", "foreign-put", "foreign-auth-shortcut"])
def test_transport_rejects_unverified_acknowledgment(tmp_path, mode):
    _BackendHandler.mode = mode
    server, base_url = _start(_BackendHandler)
    try:
        submission = _submission_payload(tmp_path, payload_hash="a" * 64)
        if mode == "foreign-auth-shortcut":
            # The server already holds these bytes (uploaded) under a run;
            # create still exposes a pending state so the client must ask
            # for authorization, where the foreign ack appears.
            _BackendHandler.runs[_ph(submission)] = {
                "id": "run-preexisting", "payloadHash": _ph(submission),
                "sha256": submission["artifactSha256"],
                "byteSize": submission["artifactByteSize"], "uploaded": True}
        with pytest.raises(SubmitError) as raised:
            artifacts.submit_artifact_submission(base_url, submission)
        assert raised.value.retryable  # durable spool retains; idempotent replay
    finally:
        server.shutdown()
        server.server_close()


def test_same_bytes_other_campaign_is_not_an_acknowledgment(tmp_path):
    """Same artifact bytes under an unrelated run/campaign identity must not
    acknowledge THIS payload: validation binds runCreate.payloadHash."""
    from test_spool import server_bundle
    payload = _submission_payload(tmp_path, payload_hash="a" * 64)
    unrelated = _submission_payload(tmp_path, name="other.mp4", payload_hash="b" * 64,
                                    campaign_id="campaign-0000000000000009")
    forged = server_bundle(unrelated, "run-other-campaign")
    # Forge THIS artifact's bytes onto the unrelated run's acknowledgment.
    forged["artifact"]["sha256"] = payload["artifactSha256"]
    forged["artifact"]["byteSize"] = payload["artifactByteSize"]
    assert acknowledgments.validate_upload_response(payload, forged) is None
    assert acknowledgments.validate_upload_response(
        payload, server_bundle(payload, "run-right")) is not None


# --------------------------------------------------------------------------
# 5. crash boundaries and idempotent same-ID recovery (real transport)
# --------------------------------------------------------------------------

def test_crash_before_receipt_commit_replays_same_identity_without_journal(tmp_path):
    queue = tmp_path / "queue"
    payload = _submission_payload(tmp_path, payload_hash="a" * 64)
    path, entry = spool.spool_payload(str(queue), payload)
    server, base_url = _start(_BackendHandler)
    try:
        # Server accepts the PUT, then the process dies BEFORE the receipt
        # commit: simulated by raising right after the transport returns.
        real = artifacts.submit_artifact_submission

        def crash_after_transport(*args, **kwargs):
            response = real(*args, **kwargs)
            raise OSError("simulated crash after transport, before receipt commit")

        with mock.patch.object(spool, "submit_artifact_submission", side_effect=crash_after_transport):
            status, _message = spool.submit_spooled_path(
                path, queue_dir=str(queue), base_url=base_url, api_key="", retries=0, use_token=False)
        assert status == "retained"
        assert not (queue / "receipts").exists()
        assert not (queue / "campaigns").exists()
        assert Path(path).exists()
        # Recovery: same durable entry, actual transport, SAME run identity.
        # Advance the retry backoff so the entry is due now.
        pending_entry = spool.load_spool_entry(path)
        pending_entry["nextAttemptAt"] = 0.0
        atomic_json(Path(path), pending_entry)
        _BackendHandler.seen = []
        stats = spool.replay_spool(str(queue), base_url=base_url, api_key="",
                                   retries=1, use_token=False)
        assert stats.submitted == 1
        assert "put" not in _BackendHandler.seen  # dedupe short-circuit, no re-upload
        receipt = json.loads((queue / "receipts" / f"{entry['localHash']}.json").read_text())
        assert receipt["response"]["benchmarkRun"]["payloadHash"] == _ph(payload)
        assert list(_BackendHandler.runs) == [_ph(payload)]  # exactly one run
    finally:
        server.shutdown()
        server.server_close()


def test_crash_after_receipt_before_journal_or_retirement_recovers_without_transport(tmp_path):
    queue = tmp_path / "queue"
    campaign_id = "campaign-0000000000000003"
    payload = _submission_payload(tmp_path, payload_hash="a" * 64, campaign_id=campaign_id)
    pending, _entry = spool.spool_payload(str(queue), payload)
    managed = Path(spool.load_spool_entry(pending)["payload"]["artifactPath"])
    root = _journal(tmp_path, campaign_id, payload)
    _receipt(queue, payload, run_id="run-committed")  # crash point: receipt durable
    with mock.patch.object(spool, "submit_artifact_submission") as send:
        assert spool.submit_spooled_path(
            pending, queue_dir=str(queue), base_url="unused", api_key="",
            retries=0, use_token=False) == ("submitted", "run-committed")
        send.assert_not_called()
    assert not Path(pending).exists()
    assert not managed.exists()
    marker = json.loads((root / "submission-000001.accepted.json").read_text())
    assert marker["benchmarkRunId"] == "run-committed" and marker["payloadHash"] == _ph(payload)


def test_crash_after_journal_before_owned_retirement_is_idempotent(tmp_path):
    queue = tmp_path / "queue"
    campaign_id = "campaign-0000000000000004"
    payload = _submission_payload(tmp_path, payload_hash="a" * 64, campaign_id=campaign_id)
    pending, entry = spool.spool_payload(str(queue), payload)
    managed = Path(entry["payload"]["artifactPath"])
    root = _journal(tmp_path, campaign_id, payload)
    receipt = _receipt(queue, payload, run_id="run-journal")
    # Crash between journal marker commit and pending unlink/artifact cleanup:
    spool._journal_self_publish(str(queue), payload, json.loads(receipt.read_text())["response"])
    marker_path = root / "submission-000001.accepted.json"
    assert marker_path.is_file() and managed.exists()
    first = json.loads(marker_path.read_text())
    assert spool.drain_committed_receipts(str(queue)) == 1
    assert not Path(pending).exists() and not managed.exists()
    assert json.loads(marker_path.read_text()) == first  # marker stable, not rewritten
    assert spool.drain_committed_receipts(str(queue)) == 0  # second pass is a no-op


def test_corrupt_receipt_recovers_original_identity_through_actual_transport(tmp_path):
    """Mandatory recovery scenario: queued-only bytes + corrupt receipt.

    Replay through the ACTUAL transport recovers the original run identity
    (payloadHash dedupe), retires exactly once, keeps zero re-encode and
    preserves the corrupt evidence inside the superseded field.
    """
    queue = tmp_path / "queue"
    payload = _submission_payload(tmp_path, payload_hash="a" * 64)
    pending, entry = spool.spool_payload(str(queue), payload)
    managed = Path(entry["payload"]["artifactPath"])
    Path(payload["artifactPath"]).unlink()  # only the queued copy survives
    # The backend already accepted these bytes earlier (same payloadHash).
    _BackendHandler.runs[_ph(payload)] = {"id": "run-original", "payloadHash": _ph(payload),
                                      "sha256": payload["artifactSha256"],
                                      "byteSize": payload["artifactByteSize"], "uploaded": True}
    receipt = _receipt(queue, payload, run_id="unused", corrupt='{"localHash":')
    corrupt_bytes = receipt.read_bytes()
    server, base_url = _start(_BackendHandler)
    try:
        with mock.patch.object(main, "run_benchmark_batch",
                               side_effect=AssertionError("recovery must never encode")):
            stats = spool.replay_spool(str(queue), base_url=base_url, api_key="",
                                       retries=1, use_token=False)
        assert stats.submitted == 1
        assert "put" not in _BackendHandler.seen  # no re-upload, no re-encode
        assert not Path(pending).exists() and not managed.exists()
        recovered = json.loads((queue / "receipts" / f"{entry['localHash']}.json").read_text())
        assert recovered["response"]["benchmarkRun"]["id"] == "run-original"
        assert recovered["superseded"]["corruptEvidence"] == corrupt_bytes.decode()
        assert list(_BackendHandler.runs) == [_ph(payload)]
    finally:
        server.shutdown()
        server.server_close()


def test_publish_saved_recovers_corrupt_receipt_without_reencode(tmp_path):
    """Normal entry point: publish_saved_campaign over envelope + corrupt
    receipt + staged copy + deleted original → recovered, zero encodes."""
    from test_spool import SpoolTests, server_bundle
    campaign_id = "campaign-0000000000000005"
    queue = tmp_path / "queue"
    root = queue / "campaigns" / campaign_id
    root.mkdir(parents=True)
    artifact = root / "measured.mp4"
    artifact.write_bytes(b"already measured bytes")
    payload = SpoolTests()._authoritative_payload(str(artifact))
    payload["runCreate"]["campaignId"] = campaign_id
    payload["runCreate"]["repetitionGroupId"] = f"{campaign_id}:recipe-1"
    payload["runCreate"]["artifact"]["sha256"] = _sha(artifact.read_bytes())
    payload["runCreate"]["artifact"]["byteSize"] = artifact.stat().st_size
    payload["artifactSha256"] = _sha(artifact.read_bytes())
    payload["artifactByteSize"] = artifact.stat().st_size
    # Faithful contract: recomputed AFTER all identity mutations.
    payload["runCreate"]["payloadHash"] = artifacts.build_payload_hash(payload["runCreate"])
    atomic_json(root / "submission-000001.json", payload)
    pending, entry = spool.spool_payload(str(queue), payload)
    artifact.unlink()  # only the queue-managed copy remains
    _receipt(queue, payload, run_id="unused", corrupt="{}")
    with mock.patch.object(main, "run_benchmark_batch",
                           side_effect=AssertionError("publish must never encode")), \
         mock.patch.object(main, "ensure_ffmpeg_and_ffprobe", return_value=(True, "ffmpeg test")), \
         mock.patch.object(spool, "submit_artifact_submission",
                           side_effect=lambda _base, submission, **_kw: server_bundle(submission, "run-recovered")):
        rc, info = main.publish_saved_campaign(
            queue_dir=str(queue), campaign_id=campaign_id,
            base_url="http://127.0.0.1:9", api_key="", max_storage_mb=64)
    assert rc == 0, info
    assert not Path(pending).exists()
    assert not Path(entry["payload"]["artifactPath"]).exists()
    marker = json.loads((root / "submission-000001.accepted.json").read_text())
    assert marker["benchmarkRunId"] == "run-recovered"
    assert marker["payloadHash"] == _ph(payload)


# --------------------------------------------------------------------------
# 6. counters distinguish unverified evidence from accepted receipts
# --------------------------------------------------------------------------

def test_counters_report_repair_state_not_acceptance(tmp_path):
    queue = tmp_path / "queue"
    campaign_id = "campaign-0000000000000006"
    good = _submission_payload(tmp_path, name="g.mp4", payload_hash="a" * 64, campaign_id=campaign_id)
    bad = _submission_payload(tmp_path, name="b.mp4", payload_hash="b" * 64, campaign_id=campaign_id)
    _journal(tmp_path, campaign_id, good, order=1)
    _journal(tmp_path, campaign_id, bad, order=2)
    _receipt(queue, good, run_id="run-good")
    _receipt(queue, bad, run_id="run-bad", corrupt='{"localHash":')
    summary = spool.campaign_queue_summary(str(queue), campaign_id)
    assert summary["acceptedReceipts"] == 1
    assert summary["unverifiedReceipts"] == 1
    recovery = spool.queue_recovery_summary(str(queue))
    assert recovery["acceptedReceipts"] == 1
    assert recovery["unverifiedReceipts"] == 1


def test_recovery_projection_never_counts_unproven_receipt_as_accepted(tmp_path):
    campaign_id = "campaign-0000000000000007"
    root = tmp_path / "campaigns" / campaign_id
    root.mkdir(parents=True)
    atomic_json(root / "manifest.json", {
        "protocolVersion": "7.1", "clientVersion": "client/0.0.0",
        "runtime": {"ffmpeg": {"sha256": "r"}}})
    artifact = root / "measured.mp4"
    artifact.write_bytes(b"saved")
    payload = {"artifactPath": str(artifact), "runCreate": {"campaignId": campaign_id}}
    atomic_json(root / "submission-000001.json", payload)
    receipt_hash = spool.local_hash_for_payload(payload)
    atomic_json(tmp_path / "receipts" / f"{receipt_hash}.json", {
        "localHash": receipt_hash,
        "response": {"benchmarkRun": {"id": "run-already-accepted"}},
    })
    state = main.campaign_recovery_state(str(tmp_path), campaign_id)
    assert state is not None
    assert state["acceptedUploads"] == 0
    assert state["unverifiedReceipts"] == 1
    assert state["logicalPendingUploads"] == 1


# --------------------------------------------------------------------------
# 7. journal markers: v1 provenance preserved, v2 binding enforced
# --------------------------------------------------------------------------

def _record_for(campaign_id: str, artifact: Path, order: int = 1):
    from client import protocol
    return protocol.BenchmarkRunRecord(
        schedule=protocol.ScheduledRun(campaign_id, "clip|enc|fast|24", "measured", order, 1),
        timing=protocol.EncodeTiming.from_measurement(
            start_monotonic_ns=1, end_monotonic_ns=1_000_000_001,
            source_frame_count=24, encoded_frame_count=24, source_fps=24),
        metadata={"info": {"artifactPath": str(artifact),
                           "artifactSha256": _sha(artifact.read_bytes())}},
        counted_for_stability=True)


def test_journal_marker_v1_still_validates_v2_tampering_fails(tmp_path):
    campaign_id = "campaign-0000000000000009"
    root = tmp_path / "campaigns" / campaign_id
    root.mkdir(parents=True)
    artifact = root / "m.mp4"
    artifact.write_bytes(b"measured")
    digest = _sha(artifact.read_bytes())
    record = _record_for(campaign_id, artifact)
    manifest = {"protocolVersion": "7.1", "seed": 1, "protocolConfig": {}, "tasks": []}
    journal = campaign.CampaignJournal(str(tmp_path), campaign_id, manifest, 2048)
    journal.records[record.schedule.execution_order] = record
    # Historical v1 marker (strict local binding, no server payloadHash):
    atomic_json(root / "submission-000001.accepted.json", {
        "schemaVersion": 1, "executionOrder": 1, "recipeId": record.schedule.recipe_id,
        "artifactPath": str(artifact), "artifactSha256": digest, "benchmarkRunId": "run-v1"})
    assert journal.accepted_receipt(record) is not None
    # v2 marker binds the payload hash when the envelope provides it:
    atomic_json(root / "submission-000001.json", {"runCreate": {"payloadHash": "a" * 64}})
    atomic_json(root / "submission-000001.accepted.json", {
        "schemaVersion": 2, "executionOrder": 1, "recipeId": record.schedule.recipe_id,
        "artifactPath": str(artifact), "artifactSha256": digest, "benchmarkRunId": "run-v2",
        "payloadHash": "b" * 64, "artifactId": "artifact-run-v2",
        "artifactByteSize": artifact.stat().st_size, "uploadConfirmed": True})
    assert journal.accepted_receipt(record) is None  # envelope payloadHash mismatch
    atomic_json(root / "submission-000001.accepted.json", {
        "schemaVersion": 2, "executionOrder": 1, "recipeId": record.schedule.recipe_id,
        "artifactPath": str(artifact), "artifactSha256": digest, "benchmarkRunId": "run-v2",
        "payloadHash": "a" * 64, "artifactId": "artifact-run-v2",
        "artifactByteSize": artifact.stat().st_size, "uploadConfirmed": True})
    assert journal.accepted_receipt(record) is not None
    tampered = json.loads((root / "submission-000001.accepted.json").read_text())
    tampered["artifactSha256"] = "0" * 64
    atomic_json(root / "submission-000001.accepted.json", tampered)
    assert journal.accepted_receipt(record) is None


def test_journal_self_publish_ignores_unverified_response(tmp_path):
    queue = tmp_path / "queue"
    campaign_id = "campaign-000000000000000a"
    payload = _submission_payload(tmp_path, payload_hash="a" * 64, campaign_id=campaign_id)
    root = _journal(tmp_path, campaign_id, payload)
    spool._journal_self_publish(str(queue), payload, {"benchmarkRun": {"id": "run-bare"}})
    assert not (root / "submission-000001.accepted.json").exists()
    spool._journal_self_publish(str(queue), payload,
                                {"benchmarkRun": {"id": "r", "payloadHash": "a" * 64},
                                 "artifact": {"id": "x", "benchmarkRunId": "OTHER",
                                              "role": "ENCODED", "sha256": payload["artifactSha256"],
                                              "byteSize": payload["artifactByteSize"],
                                              "storageState": "RETAINED"}})
    assert not (root / "submission-000001.accepted.json").exists()


def test_retire_uploaded_artifact_requires_verified_receipt_evidence(tmp_path):
    """Releasing the ONLY local copy needs a verified receipt naming the
    same run AND artifact; without it the marker records honest repair
    state, the bytes survive, and no acknowledgment is fabricated."""
    campaign_id = "campaign-000000000000000b"
    root = tmp_path / "campaigns" / campaign_id
    root.mkdir(parents=True)
    artifact = root / "m.mp4"
    artifact.write_bytes(b"accepted bytes")
    record = _record_for(campaign_id, artifact)
    run_create = _run_create(sha=_sha(artifact.read_bytes()), size=artifact.stat().st_size,
                             payload_hash="a" * 64, campaign_id=campaign_id)
    run_create["payloadHash"] = artifacts.build_payload_hash(run_create)
    payload = artifacts.build_artifact_submission_payload(
        artifact_path=str(artifact), media_container="mp4", run_create=run_create)
    atomic_json(root / "submission-000001.json", payload)
    queue = tmp_path / "queue"
    # No durable receipt: unproven acknowledgment keeps the artifact.
    main._retire_uploaded_artifact(root, record, _sha(artifact.read_bytes()), "run-live",
                                   queue_dir=str(queue), payload=payload)
    marker = json.loads((root / "submission-000001.accepted.json").read_text())
    assert marker["schemaVersion"] == 2
    assert marker["payloadHash"] == _ph(payload)
    assert marker["benchmarkRunId"] == "run-live"
    assert marker["uploadConfirmed"] is False
    assert "artifactId" not in marker
    assert marker["reconciliationState"] == "awaiting-verified-receipt"
    assert artifact.exists()  # the ONLY copy is never released unproven
    # Now the durable verified receipt exists: same call upgrades the
    # marker to full v2 proof and retires the owned copy.
    _receipt(queue, payload, run_id="run-live")
    main._retire_uploaded_artifact(root, record, _sha(artifact.read_bytes()), "run-live",
                                   queue_dir=str(queue), payload=payload)
    marker = json.loads((root / "submission-000001.accepted.json").read_text())
    assert marker["uploadConfirmed"] is True
    assert marker["artifactId"] == "artifact-run-live"
    assert "reconciliationState" not in marker
    assert not artifact.exists()  # owned copy retired behind the bound receipt
    # Without a server run id the function fabricates nothing:
    artifact.write_bytes(b"again")
    (root / "submission-000001.accepted.json").unlink()
    main._retire_uploaded_artifact(root, record, _sha(artifact.read_bytes()), "   ",
                                   queue_dir=str(queue), payload=payload)
    assert artifact.exists()
    assert not (root / "submission-000001.accepted.json").exists()


# --------------------------------------------------------------------------
# 8. bypass regressions from the review (identity/schema/analysis/marker)
# --------------------------------------------------------------------------

def test_wrong_artifact_id_and_schema_never_verify(tmp_path):
    """The PUT may name a DIFFERENT artifact under the same run; the bound
    contract rejects it, and a receipt response with a foreign artifact id
    never verifies."""
    payload = _submission_payload(tmp_path, payload_hash="a" * 64)
    from test_spool import server_bundle
    hijacked = server_bundle(payload, "run-right",
                             artifact_overrides={"id": "artifact-of-another-run"})
    assert acknowledgments.validate_upload_response(payload, hijacked) is not None  # unbound
    assert acknowledgments.validate_upload_response(
        payload, hijacked, bound_run_id="run-right",
        bound_artifact_id="artifact-run-right") is None  # bound: foreign id rejected
    assert acknowledgments.validate_upload_response(
        payload, hijacked, bound_artifact_id="artifact-run-right") is None


def test_authoritative_with_malformed_identity_is_never_legacy(tmp_path):
    """A broken authoritative payload is unverified repair work, NOT a
    faithful legacy ingest receipt, even with the legacy receipt shape."""
    queue = tmp_path / "queue"
    malformed = {"submissionKind": artifacts.AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND,
                 "artifactPath": str(tmp_path / "gone.mp4"),
                 "artifactSha256": "z" * 64,  # not hex64
                 "artifactByteSize": -5,
                 "runCreate": {"artifact": {"sha256": "z" * 64}}}
    local_hash = spool.local_hash_for_payload(malformed)
    receipt = queue / "receipts" / f"{local_hash}.json"
    receipt.parent.mkdir(parents=True)
    atomic_json(receipt, {"localHash": local_hash,
                          "status": "uploaded_analysis_pending", "response": None})
    verdict = spool.receipt_verdict(str(receipt), malformed)
    assert verdict == "unverified:authoritative-envelope-identity-is-malformed"
    # Without the envelope, a response-less receipt is honest repair work:
    assert spool.receipt_verdict(str(receipt), None).startswith("orphan:")


def test_legacy_ingest_receipt_stays_verifiable(tmp_path):
    """Faithful legacy {localHash,status,response:None} receipts keep their
    historical verification path; the strict contract targets authoritative
    submissions only."""
    queue = tmp_path / "queue"
    legacy = {"cpuModel": "fixture", "fps": 1}
    local_hash = spool.local_hash_for_payload(legacy)
    receipt = queue / "receipts" / f"{local_hash}.json"
    receipt.parent.mkdir(parents=True)
    atomic_json(receipt, {"localHash": local_hash,
                          "status": "uploaded_analysis_pending", "response": None})
    assert spool.receipt_verdict(str(receipt), legacy) == "verified"


@pytest.mark.parametrize("row_status", ["PENDING", "SUSPECT", "REJECTED", "FAILED"])
def test_non_complete_analysis_rows_never_claim_accepted(tmp_path, row_status):
    """uploadConfirmed and analysisAccepted are distinct dispositions: a
    retained artifact with pending/suspect/rejected analysis is honestly
    reported as NOT accepted."""
    from test_spool import server_bundle
    payload = _submission_payload(tmp_path, name=f"a-{row_status}.mp4", payload_hash="a" * 64)
    response = server_bundle(payload, "run-a", storage_state="RETAINED")
    response["analyses"] = [{"id": "analysis-1", "status": row_status,
                             "metricModelId": "vmaf/v1"}]
    evidence = acknowledgments.validate_upload_response(payload, response)
    assert evidence is not None  # upload itself IS confirmed
    assert evidence["uploadConfirmed"] is True
    assert evidence["analysisAccepted"] is False
    assert evidence["analysisStatus"] == row_status


def test_empty_analyses_is_pending_not_accepted(tmp_path):
    """`bool(rows)` was the old bug: an empty list means analysis pending."""
    from test_spool import server_bundle
    payload = _submission_payload(tmp_path, name="empty-rows.mp4", payload_hash="a" * 64)
    response = server_bundle(payload, "run-a", storage_state="RETAINED")
    evidence = acknowledgments.validate_upload_response(payload, response)
    assert evidence["analysisAccepted"] is False
    assert evidence["analysisStatus"] == "NONE"
    response["analyses"] = [{"id": "analysis-1", "status": "COMPLETE",
                             "metricModelId": "vmaf/v1"}]
    evidence = acknowledgments.validate_upload_response(payload, response)
    assert evidence["analysisAccepted"] is True
    assert evidence["analysisStatus"] == "COMPLETE"


def test_receipt_acknowledgment_crosscheck_rejects_mismatched_pair(tmp_path):
    """A receipt that pairs a bound acknowledgment with a DIFFERENT embedded
    response is payload-free forgery and never verifies."""
    from test_spool import server_bundle
    payload = _submission_payload(tmp_path, name="crosscheck.mp4", payload_hash="a" * 64)
    good_response = server_bundle(payload, "run-true")
    ack = acknowledgments.validate_upload_response(payload, good_response)
    assert ack is not None
    forged = {"localHash": spool.local_hash_for_payload(payload),
              "status": "uploaded_analysis_pending",
              "response": server_bundle(payload, "run-other"),
              "acknowledgment": ack}
    assert not acknowledgments.receipt_acknowledgment_matches(forged)
    assert acknowledgments.receipt_verdict(
        forged["localHash"], forged, payload) == \
        "unverified:receipt-acknowledgment-missing-or-inconsistent"
    # A foreign bundle alone (no acknowledgment) never counts payload-free:
    foreign = {"localHash": spool.local_hash_for_payload(payload),
               "status": "uploaded_analysis_pending",
               "response": good_response}
    assert acknowledgments.receipt_verdict(
        foreign["localHash"], foreign, None) == \
        "unverified:receipt-lacks-persisted-bound-acknowledgment"


def test_forged_v1_marker_never_shortcuts_publish(tmp_path):
    """A v1 marker alone cannot authorize the publish-saved skip; only a
    v2 marker with full server-bound proof does."""
    campaign_id = "campaign-000000000000000c"
    root = tmp_path / "campaigns" / campaign_id
    root.mkdir(parents=True)
    artifact = root / "m.mp4"
    artifact.write_bytes(b"saved bytes")
    digest = _sha(artifact.read_bytes())
    run_create = _run_create(sha=digest, size=artifact.stat().st_size,
                             payload_hash="a" * 64, campaign_id=campaign_id)
    run_create["payloadHash"] = artifacts.build_payload_hash(run_create)
    payload = artifacts.build_artifact_submission_payload(
        artifact_path=str(artifact), media_container="mp4", run_create=run_create)
    atomic_json(root / "submission-000001.json", payload)
    atomic_json(root / "submission-000001.accepted.json", {
        "schemaVersion": 1, "executionOrder": 1, "recipeId": "recipe-1",
        "artifactPath": str(artifact), "artifactSha256": digest,
        "benchmarkRunId": "run-forged"})
    assert main._journal_marker_state(root / "submission-000001.json")[0] == "historical"
    atomic_json(root / "submission-000001.accepted.json", {
        "schemaVersion": 2, "executionOrder": 1, "recipeId": "recipe-1",
        "artifactPath": str(artifact), "artifactSha256": digest,
        "benchmarkRunId": "run-real", "payloadHash": _ph(payload),
        "artifactId": "artifact-run-real",
        "artifactByteSize": artifact.stat().st_size, "uploadConfirmed": True})
    assert main._journal_marker_state(root / "submission-000001.json")[0] == "verified"


def test_projection_surfaces_historical_and_pending_markers_without_corruption(tmp_path):
    """v1 markers and awaiting-reconciliation v2 markers stay publishable
    reconciliation work; they never corrupt the projection nor claim
    acceptance."""
    import dataclasses
    from client import protocol
    from client.recovery_projection import project_attempt_groups
    campaign_id = "campaign-000000000000000d"
    root = tmp_path / "campaigns" / campaign_id
    root.mkdir(parents=True)
    cfg = protocol.ProtocolConfig.for_version("7.1", max_adaptive_repeats=0)
    atomic_json(root / "manifest.json", {
        "protocolVersion": "7.1", "clientVersion": "client/0.0.0", "seed": 1,
        "protocolConfig": dataclasses.asdict(cfg),
        "tasks": [{"clipId": "clip", "encoder": "libx264", "preset": "fast", "crf": 24}],
        "runtime": {"ffmpeg": {"sha256": "r"}}})
    timing = protocol.EncodeTiming.from_measurement(
        start_monotonic_ns=1, end_monotonic_ns=1_000_000_001,
        source_frame_count=24, encoded_frame_count=24, source_fps=24)
    digests = {}
    for order, phase, repetition in ((1, "warmup", 1), (2, "measured", 1), (3, "measured", 2)):
        metadata = {}
        if phase == "measured":
            artifact = root / f"measured-{order}.mp4"
            artifact.write_bytes(f"measured-{order}".encode())
            digests[order] = _sha(artifact.read_bytes())
            metadata = {"info": {"artifactPath": str(artifact),
                                 "artifactSha256": digests[order]}}
        record = protocol.BenchmarkRunRecord(
            schedule=protocol.ScheduledRun(campaign_id, "clip|libx264|fast|24",
                                           phase, repetition, order),
            timing=timing, metadata=metadata,
            counted_for_stability=phase == "measured")
        atomic_json(root / f"attempt-{order:06d}.json", record.to_dict())
    recipe_id = "clip|libx264|fast|24"
    artifact2 = root / "measured-2.mp4"
    # v1 marker: historical; attempt stays a candidate (bytes exist).
    atomic_json(root / "submission-000002.accepted.json", {
        "schemaVersion": 1, "executionOrder": 2, "recipeId": recipe_id,
        "artifactPath": str(artifact2), "artifactSha256": digests[2],
        "benchmarkRunId": "run-v1"})
    projected = project_attempt_groups(root, campaign_id)
    assert projected["historicalOrders"] == [2]
    assert projected["acceptedOrders"] == []
    assert projected["corruptEntries"] == []
    assert projected["candidateOrders"] == [2, 3]
    # v2 marker awaiting a verified receipt: reconciliation state, not corrupt.
    atomic_json(root / "submission-000002.accepted.json", {
        "schemaVersion": 2, "executionOrder": 2, "recipeId": recipe_id,
        "artifactPath": str(artifact2), "artifactSha256": digests[2],
        "benchmarkRunId": "run-pending", "uploadConfirmed": False,
        "reconciliationState": "awaiting-verified-receipt"})
    projected = project_attempt_groups(root, campaign_id)
    assert projected["corruptEntries"] == []
    assert projected["acceptedOrders"] == []
    assert projected["candidateOrders"] == [2, 3]
    # A failed v2 marker WITHOUT any reconciliation state IS corrupt.
    atomic_json(root / "submission-000002.accepted.json", {
        "schemaVersion": 2, "executionOrder": 2, "recipeId": recipe_id,
        "artifactPath": str(artifact2), "artifactSha256": "0" * 64,
        "benchmarkRunId": "run-broken"})
    projected = project_attempt_groups(root, campaign_id)
    assert [item["path"] for item in projected["corruptEntries"]] == \
        ["submission-000002.accepted.json"]


def test_retention_response_binds_historical_marker_without_bytes(tmp_path):
    """Metadata-only reconciliation: the server status body must prove THIS
    payloadHash/artifact for the marker's run before a v1 marker upgrades."""
    campaign_id = "campaign-000000000000000e"
    root = tmp_path / "campaigns" / campaign_id
    root.mkdir(parents=True)
    artifact = root / "m.mp4"
    artifact.write_bytes(b"long retired")
    digest = _sha(artifact.read_bytes())
    run_create = _run_create(sha=digest, size=artifact.stat().st_size,
                             payload_hash="a" * 64, campaign_id=campaign_id)
    run_create["payloadHash"] = artifacts.build_payload_hash(run_create)
    payload = artifacts.build_artifact_submission_payload(
        artifact_path=str(artifact), media_container="mp4", run_create=run_create)
    marker = {"schemaVersion": 1, "executionOrder": 1, "recipeId": "recipe-1",
              "artifactPath": str(artifact), "artifactSha256": digest,
              "benchmarkRunId": "run-retired"}
    status = {"artifactId": "artifact-run-retired", "benchmarkRunId": "run-retired",
              "artifactStorageState": "RETAINED", "benchmarkRunStatus": "ACCEPTED",
              "payloadHash": _ph(payload), "artifactSha256": digest,
              "artifactByteSize": artifact.stat().st_size,
              "analyses": [{"id": "a1", "status": "COMPLETE", "metricModelId": "vmaf/v1"}]}
    evidence = acknowledgments.validate_retention_response(payload, marker, status)
    assert evidence is not None
    assert evidence["uploadConfirmed"] is True
    assert evidence["artifactId"] == "artifact-run-retired"
    assert evidence["analysisAccepted"] is True
    # A body for different bytes never proves retention of THESE bytes:
    assert acknowledgments.validate_retention_response(
        payload, marker, {**status, "payloadHash": "f" * 64}) is None
    assert acknowledgments.validate_retention_response(
        payload, marker, {**status, "artifactStorageState": "PENDING"}) is None
    assert acknowledgments.validate_retention_response(
        payload, marker, {**status, "benchmarkRunId": "run-other"}) is None


def test_publish_saved_reconciles_historical_marker_metadata_only(tmp_path):
    """Historical v1 marker + retired bytes: publish attempts ONE bounded
    analysis-status GET; on proof it upgrades the marker and skips upload
    with zero bytes and zero re-encode; on failure it reports reconciliation
    work without deleting anything."""
    campaign_id = "campaign-000000000000000f"
    with tempfile.TemporaryDirectory() as td:
        queue = Path(td) / "queue"
        root = queue / "campaigns" / campaign_id
        root.mkdir(parents=True)
        artifact = root / "measured.mp4"
        artifact.write_bytes(b"already uploaded long ago")
        digest = _sha(artifact.read_bytes())
        run_create = _run_create(sha=digest, size=artifact.stat().st_size,
                                 payload_hash="a" * 64, campaign_id=campaign_id)
        run_create["payloadHash"] = artifacts.build_payload_hash(run_create)
        payload = artifacts.build_artifact_submission_payload(
            artifact_path=str(artifact), media_container="mp4", run_create=run_create)
        atomic_json(root / "submission-000001.json", payload)
        atomic_json(root / "submission-000001.accepted.json", {
            "schemaVersion": 1, "executionOrder": 1, "recipeId": "recipe-1",
            "artifactPath": str(artifact), "artifactSha256": digest,
            "benchmarkRunId": "run-ancient"})
        artifact.unlink()  # bytes retired by the historical upload
        status_body = {"artifactId": "artifact-run-ancient",
                       "benchmarkRunId": "run-ancient",
                       "artifactStorageState": "RETAINED", "benchmarkRunStatus": "ACCEPTED",
                       "payloadHash": _ph(payload), "artifactSha256": digest,
                       "artifactByteSize": len(b"already uploaded long ago"),
                       "analyses": []}
        # Server cannot prove retention -> honest reconciliation state.
        with mock.patch.object(main, "fetch_retention_status", return_value=None) as fetch:
            outcome = main._reconcile_historical_envelope(
                base_url="http://unused", envelope_path=root / "submission-000001.json",
                marker=json.loads((root / "submission-000001.accepted.json").read_text()),
                envelope=payload, cancel_event=None)
        assert outcome == "unavailable"
        fetch.assert_called_once()
        assert json.loads((root / "submission-000001.accepted.json").read_text())["schemaVersion"] == 1
        # Server proves retention -> marker upgrades to v2 (idempotent proof).
        with mock.patch.object(main, "fetch_retention_status", return_value=status_body):
            outcome = main._reconcile_historical_envelope(
                base_url="http://unused", envelope_path=root / "submission-000001.json",
                marker=json.loads((root / "submission-000001.accepted.json").read_text()),
                envelope=payload, cancel_event=None)
        assert outcome == "verified"
        upgraded = json.loads((root / "submission-000001.accepted.json").read_text())
        assert upgraded["schemaVersion"] == 2 and upgraded["uploadConfirmed"] is True
        assert upgraded["artifactId"] == "artifact-run-ancient"
        # Idempotent: a second pass on the v2 marker stays verified.
        assert main._journal_marker_state(root / "submission-000001.json")[0] == "verified"
        # Transient network failure -> unreachable, evidence untouched.
        atomic_json(root / "submission-000002.json", payload)
        atomic_json(root / "submission-000002.accepted.json", {
            "schemaVersion": 1, "executionOrder": 2, "recipeId": "recipe-1",
            "artifactPath": str(artifact), "artifactSha256": digest,
            "benchmarkRunId": "run-ancient"})
        with mock.patch.object(main, "fetch_retention_status",
                               side_effect=SubmitError("network down", retryable=True)):
            outcome = main._reconcile_historical_envelope(
                base_url="http://unused", envelope_path=root / "submission-000002.json",
                marker=json.loads((root / "submission-000002.accepted.json").read_text()),
                envelope=payload, cancel_event=None)
        assert outcome == "unreachable"
        assert json.loads((root / "submission-000002.accepted.json").read_text())["schemaVersion"] == 1