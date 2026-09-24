"""C12 revision: phase-aware cooperative cancellation and bounded transport.

Covers: stalled create/auth/PUT, cancel during each phase, lost response after
server acceptance, idempotent replay with the same identity, redacted public
errors (no raw bodies/tokens), and GUI-safe progress reporting.
"""
import hashlib
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar, List, Optional

import pytest

from client.artifacts import SubmitError, SubmissionCancelled, build_payload_hash, submit_artifact_submission
from client.network import submit as legacy_submit


def _artifact_bytes() -> bytes:
    return b"C" * (1 << 20)  # 1 MiB


def _submission(tmp_path, run_create=None):
    path = tmp_path / "artifact.mp4"
    path.write_bytes(_artifact_bytes())
    create = run_create if run_create is not None else {
        "campaignId": "campaign-c12",
        "repetitionGroupId": "campaign-c12:recipe-1",
        "repetitionIndex": 1,
        "artifact": {"role": "ENCODED", "sha256": hashlib.sha256(_artifact_bytes()).hexdigest(),
                     "byteSize": len(_artifact_bytes()), "mediaContainer": "mp4"},
    }
    create = dict(create)
    create.setdefault("payloadHash", build_payload_hash(create))
    return {"submissionKind": "authoritative-artifact-run-v1",
            "artifactPath": str(path), "contentType": "video/mp4", "runCreate": create}


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _StallHandler(BaseHTTPRequestHandler):
    """Stalls each phase on a class-level control event."""
    phase: ClassVar[str] = "create"          # where to stall: create|auth|put
    release: ClassVar[Optional[threading.Event]] = None
    first_body_chunk: ClassVar[Optional[threading.Event]] = None
    seen: ClassVar[List[str]] = []

    def _read_body(self) -> bytes:
        n = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(n) if n else b""

    def _stall(self, phase: str) -> None:
        if type(self).phase == phase and type(self).release is not None:
            type(self).release.wait(10)

    def do_POST(self) -> None:
        body = self._read_body()
        type(self).seen.append(self.path)
        if self.path == "/v7/benchmark-runs":
            self._stall("create")
            payload = json.loads(body or b"{}")
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "benchmarkRun": {"id": "run-c12"},
                "artifact": {"storageState": "PENDING"},
                "analyses": [],
            }).encode())
            return
        if self.path.endswith("/upload-authorizations"):
            self._stall("auth")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"uploadRequired": True, "token": "tok-c12"}).encode())
            return
        self.send_response(404)
        self.end_headers()

    def do_PUT(self) -> None:
        # Read the body slowly: one chunk, then wait, so the client generator
        # keeps pulling chunks and can observe cancellation mid-upload.
        n = int(self.headers.get("Content-Length", "0"))
        remaining = n
        first = True
        while remaining > 0:
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            if first:
                first = False
                if type(self).first_body_chunk is not None:
                    type(self).first_body_chunk.set()
            self._stall("put")
            if remaining > 0:
                time.sleep(0.05)  # throttle so upload stays in-flight
        type(self).seen.append("PUT")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"benchmarkRun": {"id": "run-c12"}}).encode())

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def _start(handler):
    server = _Server(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


@pytest.fixture(autouse=True)
def _reset_handler_state():
    _StallHandler.phase = "create"
    _StallHandler.release = None
    _StallHandler.first_body_chunk = None
    _StallHandler.seen = []
    yield


def test_cancel_before_call_touches_no_network(tmp_path):
    server, base_url = _start(_StallHandler)
    try:
        cancel = threading.Event()
        cancel.set()
        with pytest.raises(SubmissionCancelled) as caught:
            submit_artifact_submission(base_url, _submission(tmp_path), cancel_event=cancel)
        assert caught.value.retryable
        assert _StallHandler.seen == []
    finally:
        server.shutdown()
        server.server_close()


def test_cancel_during_stalled_create_is_bounded(tmp_path):
    _StallHandler.phase = "create"
    _StallHandler.release = threading.Event()
    server, base_url = _start(_StallHandler)
    try:
        cancel = threading.Event()
        threading.Timer(0.3, cancel.set).start()
        started = time.monotonic()
        with pytest.raises(SubmissionCancelled) as caught:
            submit_artifact_submission(base_url, _submission(tmp_path), cancel_event=cancel)
        elapsed = time.monotonic() - started
        assert caught.value.phase == "run create"
        assert caught.value.retryable
        # Bounded shutdown: cancel observed far under the old 300 s PUT window.
        assert elapsed < 3.0
        _StallHandler.release.set()
    finally:
        server.shutdown()
        server.server_close()


def test_stalled_create_hits_phase_budget_without_cancel(tmp_path):
    _StallHandler.phase = "create"
    _StallHandler.release = threading.Event()
    server, base_url = _start(_StallHandler)
    try:
        started = time.monotonic()
        with pytest.raises(SubmitError) as caught:
            submit_artifact_submission(base_url, _submission(tmp_path), create_seconds=0.5)
        elapsed = time.monotonic() - started
        assert caught.value.retryable
        assert elapsed < 3.0  # hard bound, never the 60 s legacy timeout
        _StallHandler.release.set()
    finally:
        server.shutdown()
        server.server_close()


def test_cancel_during_stalled_auth(tmp_path):
    _StallHandler.phase = "auth"
    _StallHandler.release = threading.Event()
    server, base_url = _start(_StallHandler)
    try:
        cancel = threading.Event()
        threading.Timer(0.3, cancel.set).start()
        started = time.monotonic()
        with pytest.raises(SubmissionCancelled) as caught:
            submit_artifact_submission(base_url, _submission(tmp_path), cancel_event=cancel)
        assert caught.value.phase == "upload authorization"
        assert time.monotonic() - started < 3.0
        _StallHandler.release.set()
    finally:
        server.shutdown()
        server.server_close()


def test_cancel_during_upload_and_progress_reporting(tmp_path):
    _StallHandler.phase = "put"
    _StallHandler.release = threading.Event()
    _StallHandler.first_body_chunk = threading.Event()
    server, base_url = _start(_StallHandler)
    try:
        cancel = threading.Event()
        progress: List[tuple] = []

        def on_progress(phase, sent, total):
            progress.append((phase, sent, total))
            if sent >= 262144:  # second chunk already accepted
                cancel.set()

        started = time.monotonic()
        with pytest.raises(SubmissionCancelled) as caught:
            submit_artifact_submission(base_url, _submission(tmp_path),
                                       cancel_event=cancel, progress=on_progress,
                                       upload_seconds=5.0)
        elapsed = time.monotonic() - started
        assert caught.value.phase == "artifact upload"
        assert caught.value.retryable
        # The caller returned while the worker was still socket-blocked: the
        # transaction was genuinely in-flight (server receives bytes after the
        # cancellation returns), and shutdown was fast.
        assert _StallHandler.first_body_chunk.wait(5)
        assert elapsed < 3.0
        # GUI-safe progress: upload phase, monotonic sent, correct total.
        assert progress and all(p[0] == "artifact upload" for p in progress)
        assert [p[1] for p in progress] == sorted(p[1] for p in progress)
        assert progress[-1][2] == len(_artifact_bytes())
        _StallHandler.release.set()
    finally:
        server.shutdown()
        server.server_close()


def test_upload_stall_is_hard_bounded_below_legacy_300s(tmp_path):
    """No cancel at all: the upload phase budget alone terminates the stall."""
    class _NeverResponds(_StallHandler):
        def do_PUT(self):
            n = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(min(1024, n))  # read a little, then hang
            time.sleep(10)

    server, base_url = _start(_NeverResponds)
    try:
        started = time.monotonic()
        with pytest.raises(SubmitError) as caught:
            submit_artifact_submission(base_url, _submission(tmp_path), upload_seconds=1.0)
        elapsed = time.monotonic() - started
        assert caught.value.retryable
        assert elapsed < 8.0  # bounded ~1 s budget, not 300 s
    finally:
        server.shutdown()
        server.server_close()


def test_lost_response_after_acceptance_replays_same_identity(tmp_path):
    """Server accepts the PUT, then the response is lost. Retry with the same
    submission must reuse the existing run and skip re-upload — never create a
    second run, never discard the artifact."""
    class _IdempotentFlow(_StallHandler):
        runs: ClassVar[dict] = {}
        uploaded: ClassVar[bool] = False
        lost_once: ClassVar[bool] = False

        def do_POST(self):
            body = self._read_body()
            if self.path == "/v7/benchmark-runs":
                payload = json.loads(body or b"{}")
                key = str(payload.get("payloadHash"))
                run = _IdempotentFlow.runs.get(key)
                if run is None:
                    run = {"id": f"run-{len(_IdempotentFlow.runs) + 1}"}
                    _IdempotentFlow.runs[key] = run
                state = "RETAINED" if _IdempotentFlow.uploaded else "PENDING"
                analyses = [{"id": "analysis-1", "status": "COMPLETE"}] if _IdempotentFlow.uploaded else []
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "benchmarkRun": {"id": run["id"]},
                    "artifact": {"storageState": state},
                    "analyses": analyses,
                }).encode())
                return
            if self.path.endswith("/upload-authorizations"):
                if _IdempotentFlow.uploaded:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"uploadRequired": False}).encode())
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"uploadRequired": True, "token": "t1"}).encode())
                return
            self.send_response(404)
            self.end_headers()

        def do_PUT(self):
            n = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(n)
            _IdempotentFlow.uploaded = True
            if _IdempotentFlow.lost_once:
                _IdempotentFlow.lost_once = False
                # Accept bytes, then drop the connection without a response.
                self.close_connection = True
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                except OSError:
                    pass
                return
            super().do_PUT()

    server, base_url = _start(_IdempotentFlow)
    try:
        submission = _submission(tmp_path)
        _IdempotentFlow.lost_once = True
        with pytest.raises(SubmitError) as lost:
            submit_artifact_submission(base_url, submission)
        assert lost.value.retryable  # ambiguous: spool retains the entry

        # Replay after restart with the SAME submission identity.
        result = submit_artifact_submission(base_url, submission)
        assert result["benchmarkRun"]["id"] == "run-1"
        assert len(_IdempotentFlow.runs) == 1  # no duplicate run created
    finally:
        server.shutdown()
        server.server_close()


def test_public_errors_never_leak_server_bodies_or_tokens(tmp_path):
    class _LeakyRejection(_StallHandler):
        def do_POST(self):
            self._read_body()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"bad","token":"raw-secret-token","body":"raw-secret-body"}')

    server, base_url = _start(_LeakyRejection)
    try:
        with pytest.raises(SubmitError) as caught:
            submit_artifact_submission(base_url, _submission(tmp_path))
        exc = caught.value
        assert exc.retryable is False
        assert exc.status_code == 400
        text = str(exc)
        assert "raw-secret-token" not in text
        assert "raw-secret-body" not in text
        assert "raw-secret-token" not in repr(exc)
        # Raw body is retained privately for diagnostics only.
        assert "raw-secret-body" in exc._server_body
    finally:
        server.shutdown()
        server.server_close()


def test_submit_error_message_is_bounded():
    exc = SubmitError("x" * 5000, retryable=True)
    assert len(str(exc)) <= SubmitError._MAX_MESSAGE_CHARS


def test_legacy_submit_cancel_during_retry_wait():
    """network.submit honours cancel_event while waiting out a 429 backoff."""
    class _RateLimited(_StallHandler):
        def do_POST(self):
            self._read_body()
            self.send_response(429)
            self.send_header("Retry-After", "30")
            self.end_headers()

    server, base_url = _start(_RateLimited)
    try:
        cancel = threading.Event()
        threading.Timer(0.2, cancel.set).start()
        started = time.monotonic()
        with pytest.raises(SubmissionCancelled):
            legacy_submit(base_url, {"cpuModel": "T"}, retries=3,
                          backoff_seconds=1, use_token=False, cancel_event=cancel)
        assert time.monotonic() - started < 3.0
    finally:
        server.shutdown()
        server.server_close()


def test_legacy_submit_transaction_bound_stops_stalled_attempt():
    """No cancel: the wall-clock transaction bound ends a stalled POST chain."""
    class _Silent(_StallHandler):
        def do_POST(self):
            time.sleep(10)

    server, base_url = _start(_Silent)
    try:
        started = time.monotonic()
        with pytest.raises(SubmitError) as caught:
            legacy_submit(base_url, {"cpuModel": "T"}, retries=3, backoff_seconds=0.1,
                          use_token=False, transaction_seconds=1.0)
        elapsed = time.monotonic() - started
        assert caught.value.retryable
        assert elapsed < 8.0  # far under 30 s × retries legacy behavior
    finally:
        server.shutdown()
        server.server_close()
