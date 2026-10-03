"""R03/R04/R05 (September 28 audit): real cancellation/deadline propagation through
transport admission, bounded error-body consumption, and owned-worker lifecycle.

Failing-before regressions against the September 28 code:
- R03: spool admission (hash/copy/lock) ignores cancel/deadline; artifact
  transport has no caller deadline; legacy submit has no caller deadline.
- R04: artifacts.py reads error bodies with deadline=None; the byte cap only
  limits retained text while consumption continues; blocked/drip-fed bodies
  ignore cancellation; responses are never closed.
- R05: _run_cancellable abandons daemon workers while host-phase exclusion
  ownership is released immediately, so a cancelled worker can still perform
  I/O after a collector could start. Release must reap owned workers or
  retain exclusion ownership until quiescent.
"""
import hashlib
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar, List, Optional

import pytest

from client import network, spool
from client.artifacts import (AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND,
                              submit_artifact_submission)
from client.network import SubmissionCancelled, SubmitError


# --------------------------------------------------------------------------
# fault servers
# --------------------------------------------------------------------------

class _FaultServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _FaultHandler(BaseHTTPRequestHandler):
    """Configurable fault server: stalls, blocked/drip/oversized error bodies."""
    protocol_version = "HTTP/1.1"

    mode: ClassVar[str] = "ok"
    stall: ClassVar[Optional[threading.Event]] = None
    first_body_byte: ClassVar[Optional[threading.Event]] = None
    seen: ClassVar[List[str]] = []
    body_bytes_written: ClassVar[int] = 0
    client_closed_early: ClassVar[bool] = False
    drip_seconds: ClassVar[float] = 5.0

    def _read_body(self) -> bytes:
        n = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(n) if n else b""

    def _status(self, code: int, headers: Optional[dict] = None) -> None:
        self.send_response(code)
        for key, value in (headers or {}).items():
            self.send_header(key, str(value))

    def _end(self) -> None:
        self.end_headers()
        self.wfile.flush()

    def _blocked_body(self, code: int) -> None:
        """Headers + a few bytes, then hold the socket silent for 10 s."""
        self._status(code, {"Content-Type": "text/plain", "Content-Length": "100000"})
        self._end()
        try:
            self.wfile.write(b"0123456789")
            self.wfile.flush()
        except OSError:
            self.close_connection = True
            return
        if type(self).first_body_byte is not None:
            type(self).first_body_byte.set()
        time.sleep(10.0)
        self.close_connection = True

    def _drip_body(self, code: int, extra_headers: Optional[dict] = None) -> None:
        """Chunked drip: 4 KiB every 50 ms for drip_seconds."""
        self._status(code, {"Content-Type": "text/plain",
                            "Transfer-Encoding": "chunked", **(extra_headers or {})})
        self._end()
        end = time.time() + type(self).drip_seconds
        try:
            while time.time() < end:
                chunk = b"x" * 4096
                self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                self.wfile.flush()
                type(self).body_bytes_written += len(chunk)
                time.sleep(0.05)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            type(self).client_closed_early = True
            self.close_connection = True

    def _oversized_body(self, code: int, total: int = 8 << 20) -> None:
        """Fixed-length 8 MiB body written only as fast as the client reads."""
        self._status(code, {"Content-Type": "text/plain", "Content-Length": str(total)})
        self._end()
        written = 0
        try:
            while written < total:
                chunk = b"y" * 65536
                self.wfile.write(chunk)
                self.wfile.flush()
                written += len(chunk)
                type(self).body_bytes_written = written
        except (BrokenPipeError, ConnectionResetError, OSError):
            type(self).client_closed_early = True
            self.close_connection = True

    def _json(self, code: int, value: dict) -> None:
        body = json.dumps(value).encode()
        self._status(code, {"Content-Type": "application/json",
                            "Content-Length": str(len(body))})
        self._end()
        try:
            self.wfile.write(body)
            self.wfile.flush()
        except OSError:
            self.close_connection = True

    def _stall(self) -> None:
        if type(self).stall is not None:
            type(self).stall.wait(30)

    def do_GET(self) -> None:
        type(self).seen.append(f"GET {self.path}")
        self._json(404, {"error": "unused"})

    def do_POST(self) -> None:
        body = self._read_body()
        type(self).seen.append(f"POST {self.path}")
        mode = type(self).mode
        if self.path == "/submit":
            if mode == "stall-submit":
                self._stall()
                self._json(200, {"ok": True})
            else:
                self._json(200, {"ok": True})
            return
        if self.path == "/v7/benchmark-runs":
            if mode == "stall-create":
                self._stall()
            elif mode == "blocked-create-body":
                self._blocked_body(500)
                return
            elif mode == "drip-create-5xx":
                self._drip_body(503)
                return
            elif mode == "drip-create-429":
                self._drip_body(429, {"Retry-After": "7"})
                return
            elif mode == "drip-create-400":
                self._drip_body(400)
                return
            elif mode == "oversized-create":
                self._oversized_body(500)
                return
            self._json(201, {"benchmarkRun": {"id": "run-lifecycle"},
                             "artifact": {"storageState": "PENDING"}, "analyses": []})
            return
        if self.path.endswith("/upload-authorizations"):
            if mode == "stall-auth":
                self._stall()
            self._json(200, {"uploadRequired": True, "token": "tok-lifecycle"})
            return
        self._json(404, {"error": "unused"})

    def do_PUT(self) -> None:
        remaining = int(self.headers.get("Content-Length", "0"))
        while remaining > 0:
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
        type(self).seen.append("PUT")
        self._json(200, {"benchmarkRun": {"id": "run-lifecycle"}})

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def _start(handler):
    server = _FaultServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


@pytest.fixture(autouse=True)
def _reset_fault_state():
    _FaultHandler.mode = "ok"
    _FaultHandler.stall = None
    _FaultHandler.first_body_byte = None
    _FaultHandler.seen = []
    _FaultHandler.body_bytes_written = 0
    _FaultHandler.client_closed_early = False
    _FaultHandler.drip_seconds = 5.0
    yield


def _submission(tmp_path):
    path = tmp_path / "artifact.mp4"
    path.write_bytes(b"C" * (1 << 16))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    create = {"campaignId": "c-lifecycle", "payloadHash": "h-1",
              "artifact": {"sha256": digest, "byteSize": path.stat().st_size}}
    return {"artifactPath": str(path), "contentType": "video/mp4",
            "submissionKind": AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND,
            "artifactSha256": digest, "artifactByteSize": path.stat().st_size,
            "runCreate": create}


def _wait_until(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# --------------------------------------------------------------------------
# R04 — error-body bounds: byte cap, real deadline, cancellation, close
# --------------------------------------------------------------------------

def test_oversized_error_body_stops_at_byte_cap_and_closes(tmp_path):
    """An 8 MiB 5xx body must be consumed only up to the hard read cap; the
    current code keeps draining the whole body after the retained-text cap."""
    _FaultHandler.mode = "oversized-create"
    server, base_url = _start(_FaultHandler)
    try:
        started = time.monotonic()
        with pytest.raises(SubmitError) as raised:
            submit_artifact_submission(base_url, _submission(tmp_path), create_seconds=20.0)
        assert time.monotonic() - started < 15.0
        assert raised.value.status_code == 500
        assert raised.value.retryable
        # Consumption is bounded: the client stopped reading at the cap and
        # closed, so the server could not write the full 8 MiB.
        assert _wait_until(lambda: _FaultHandler.client_closed_early, timeout=5.0), \
            "client never closed the oversized response"
        assert _FaultHandler.body_bytes_written <= (65536 + (3 << 20))
    finally:
        server.server_close()


def test_drip_fed_error_body_stops_at_phase_deadline(tmp_path):
    """A 5 s drip must still stop at the phase deadline. The current code
    passes deadline=None and waits out the whole drip."""
    _FaultHandler.mode = "drip-create-5xx"
    server, base_url = _start(_FaultHandler)
    try:
        started = time.monotonic()
        with pytest.raises(SubmitError) as raised:
            submit_artifact_submission(base_url, _submission(tmp_path), create_seconds=1.0)
        elapsed = time.monotonic() - started
        assert elapsed < 3.0, f"drip-fed body was consumed for {elapsed:.1f}s"
        assert raised.value.retryable
    finally:
        server.server_close()


def test_permanent_rejection_with_endless_body_is_bounded(tmp_path):
    """400 with an endless chunked body: still a bounded, permanent verdict."""
    _FaultHandler.mode = "drip-create-400"
    server, base_url = _start(_FaultHandler)
    try:
        started = time.monotonic()
        with pytest.raises(SubmitError) as raised:
            submit_artifact_submission(base_url, _submission(tmp_path), create_seconds=1.0)
        elapsed = time.monotonic() - started
        assert elapsed < 3.0, f"permanent-rejection body ran for {elapsed:.1f}s"
        assert raised.value.retryable is False
        assert raised.value.status_code == 400
    finally:
        server.server_close()


def test_429_retry_after_survives_hostile_body(tmp_path):
    """429 + Retry-After must be preserved even when the body is hostile."""
    _FaultHandler.mode = "drip-create-429"
    server, base_url = _start(_FaultHandler)
    try:
        started = time.monotonic()
        with pytest.raises(SubmitError) as raised:
            submit_artifact_submission(base_url, _submission(tmp_path), create_seconds=1.0)
        elapsed = time.monotonic() - started
        assert elapsed < 3.0, f"429 body ran for {elapsed:.1f}s"
        assert raised.value.retryable
        assert raised.value.retry_after == pytest.approx(7.0)
    finally:
        server.server_close()


def test_cancel_during_blocked_error_body_is_bounded(tmp_path):
    """Cancel must interrupt a blocked error-body read within ~poll, not wait
    for the socket timeout; the old code only checked cancel between chunks."""
    _FaultHandler.mode = "blocked-create-body"
    arrived = threading.Event()
    _FaultHandler.first_body_byte = arrived
    server, base_url = _start(_FaultHandler)
    try:
        cancel = threading.Event()
        outcome: List[BaseException] = []

        def _call() -> None:
            try:
                submit_artifact_submission(base_url, _submission(tmp_path),
                                           create_seconds=8.0, cancel_event=cancel)
            except BaseException as exc:  # noqa: BLE001 - relayed below
                outcome.append(exc)

        caller = threading.Thread(target=_call, daemon=True)
        started = time.monotonic()
        caller.start()
        assert arrived.wait(5), "server never sent the first blocked-body byte"
        cancel.set()
        caller.join(5)
        elapsed = time.monotonic() - started
        assert not caller.is_alive(), "cancel never interrupted the blocked read"
        assert elapsed < 2.5, f"cancel took {elapsed:.1f}s"
        assert len(outcome) == 1 and isinstance(outcome[0], SubmissionCancelled), outcome
    finally:
        server.server_close()


def test_legacy_submit_stall_honours_caller_deadline(tmp_path):
    """network.submit must accept a real caller deadline (monotonic) that
    bounds a stalled POST; today there is no such parameter."""
    _FaultHandler.mode = "stall-submit"
    stall = threading.Event()
    _FaultHandler.stall = stall
    server, base_url = _start(_FaultHandler)
    try:
        started = time.monotonic()
        with pytest.raises(SubmitError) as raised:
            network.submit(base_url, {"fps": 1}, retries=1, use_token=False,
                           deadline=time.monotonic() + 0.7)
        assert raised.value.retryable
        assert time.monotonic() - started < 3.0
    finally:
        stall.set()
        server.server_close()


# --------------------------------------------------------------------------
# R03 — cancellation/deadline through admission, hashing, create/auth/PUT
# --------------------------------------------------------------------------

def test_spool_admission_honours_cancel(tmp_path):
    """A cancelled Stop must not stage new work: no queue entry, no copy."""
    queue = str(tmp_path / "queue")
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(SubmissionCancelled):
        spool.spool_payload(queue, {"cpuModel": "A", "fps": 1}, cancel_event=cancel)
    assert spool.count_pending_entries(queue) == 0


def test_spool_admission_honours_deadline(tmp_path):
    queue = str(tmp_path / "queue")
    with pytest.raises(SubmitError) as raised:
        spool.spool_payload(queue, {"cpuModel": "A", "fps": 1},
                            deadline=time.monotonic() - 0.001)
    assert raised.value.retryable
    assert spool.count_pending_entries(queue) == 0


class _ReadWatchProxy:
    """File proxy: invokes a callback on each read (io objects reject attrs)."""

    def __init__(self, handle, on_read) -> None:
        self._handle = handle
        self._on_read = on_read

    def read(self, *args, **kwargs):
        self._on_read()
        return self._handle.read(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._handle, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self._handle.__exit__(*exc)


def test_spool_admission_cancel_during_staging_aborts_copy(tmp_path):
    """Cancellation observed mid-copy must abort staging with no residue."""
    queue_dir = tmp_path / "queue"
    queue = str(queue_dir)
    source = tmp_path / "artifact.bin"
    source.write_bytes(b"Z" * (4 << 20))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    payload = {"submissionKind": AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND,
               "artifactPath": str(source), "artifactSha256": digest,
               "artifactByteSize": source.stat().st_size,
               "runCreate": {"artifact": {"sha256": digest,
                                          "byteSize": source.stat().st_size}}}
    cancel = threading.Event()
    real_open = open
    state = {"n": 0}

    def on_read():
        state["n"] += 1
        if state["n"] == 2:
            cancel.set()

    def watched_open(file, *args, **kwargs):
        handle = real_open(file, *args, **kwargs)
        if str(file) == str(source):
            return _ReadWatchProxy(handle, on_read)
        return handle

    with pytest.MonkeyPatch.context() as patch:
        # `open` lives in builtins; injecting it into module globals shadows it
        # for the staging copy loop's name resolution.
        patch.setattr(spool, "open", watched_open, raising=False)
        with pytest.raises(SubmissionCancelled):
            spool.spool_payload(queue, payload, cancel_event=cancel)
    assert spool.count_pending_entries(queue) == 0
    staged = list((queue_dir / "artifacts").glob("*")) if (queue_dir / "artifacts").exists() else []
    assert staged == []


def test_submit_spooled_path_deadline_prevents_network(tmp_path):
    """A timed-out call must not perform I/O: no request leaves the host."""
    server, base_url = _start(_FaultHandler)
    queue = str(tmp_path / "queue")
    path, _entry = spool.spool_payload(queue, {"cpuModel": "A", "fps": 1})
    try:
        status, _message = spool.submit_spooled_path(
            path, queue_dir=queue, base_url=base_url, api_key="", retries=1,
            use_token=False, deadline=time.monotonic() - 0.001)
        assert status == "retained"
        assert _FaultHandler.seen == []
        assert spool.count_pending_entries(queue) == 1
    finally:
        server.server_close()


def test_replay_spool_deadline_admits_nothing(tmp_path):
    server, base_url = _start(_FaultHandler)
    queue = str(tmp_path / "queue")
    spool.spool_payload(queue, {"cpuModel": "A", "fps": 1})
    try:
        stats = spool.replay_spool(queue, base_url=base_url, api_key="", retries=1,
                                   use_token=False, deadline=time.monotonic() - 0.001)
        assert stats.submitted == 0
        assert _FaultHandler.seen == []
        assert spool.count_pending_entries(queue) == 1
    finally:
        server.server_close()


def test_artifact_transport_external_deadline_during_auth(tmp_path):
    """A caller deadline must stop a stalled auth phase (and never reach PUT)."""
    _FaultHandler.mode = "stall-auth"
    stall = threading.Event()
    _FaultHandler.stall = stall
    server, base_url = _start(_FaultHandler)
    try:
        started = time.monotonic()
        with pytest.raises(SubmitError) as raised:
            submit_artifact_submission(base_url, _submission(tmp_path),
                                       deadline=time.monotonic() + 0.8)
        assert time.monotonic() - started < 3.0
        assert raised.value.retryable
        assert "PUT" not in _FaultHandler.seen
    finally:
        stall.set()
        server.server_close()


def test_checkpoint_replay_cancel_keeps_entry(tmp_path):
    """Stop during a checkpoint upload: entry retained, pass ends promptly."""
    _FaultHandler.mode = "stall-submit"
    stall = threading.Event()
    _FaultHandler.stall = stall
    server, base_url = _start(_FaultHandler)
    queue = str(tmp_path / "queue")
    path, _entry = spool.spool_payload(queue, {"cpuModel": "A", "fps": 1})
    try:
        cancel = threading.Event()
        outcome = {}

        def result():
            try:
                outcome["stats"] = spool.replay_spool(
                    queue, base_url=base_url, api_key="", retries=1,
                    use_token=False, cancel_event=cancel)
            except BaseException as exc:  # noqa: BLE001 - recorded for assertion
                outcome["error"] = exc
        runner = threading.Thread(target=result, daemon=True)
        runner.start()
        assert _wait_until(lambda: any("POST" in s for s in _FaultHandler.seen))
        cancel.set()
        runner.join(8)
        assert not runner.is_alive(), "replay did not stop within 8s of cancel"
        assert outcome.get("error") is None
        assert spool.count_pending_entries(queue) == 1
        assert os.path.isfile(path)
    finally:
        stall.set()
        server.server_close()


# --------------------------------------------------------------------------
# R05 — owned lifecycle: reap on release, or retain exclusion until quiescent
# --------------------------------------------------------------------------

def test_hold_release_reaps_owned_worker_before_returning(tmp_path, monkeypatch):
    """Ownership release must not return while an owned worker is still doing
    I/O: the releasing call reaps it (bounded sync join) before finishing."""
    monkeypatch.setattr(network, "WORKER_QUIESCE_SYNC_JOIN_SECONDS", 10.0, raising=False)
    monkeypatch.setenv("ENCODINGDB_HOST_PHASE_DIR", str(tmp_path / "phase"))
    _FaultHandler.mode = "stall-submit"
    stall = threading.Event()
    _FaultHandler.stall = stall
    server, base_url = _start(_FaultHandler)
    queue = str(tmp_path / "queue")
    path, _entry = spool.spool_payload(queue, {"cpuModel": "A", "fps": 1})
    results = {}
    cancel = threading.Event()
    try:
        def body():
            try:
                results["value"] = spool.submit_spooled_path(
                    path, queue_dir=queue, base_url=base_url, api_key="",
                    retries=1, use_token=False, cancel_event=cancel)
            except BaseException as exc:  # noqa: BLE001 - recorded for assertion
                results["error"] = exc
        runner = threading.Thread(target=body, daemon=True)
        runner.start()
        assert _wait_until(lambda: any("POST" in s for s in _FaultHandler.seen))
        cancel.set()
        # The caller has raised, but the owned worker is still stalled inside
        # its request: the releasing call must NOT have returned yet.
        time.sleep(0.5)
        assert runner.is_alive(), "release returned while an owned worker was still doing I/O"
        stall.set()
        runner.join(10)
        assert not runner.is_alive()
        assert results.get("error") is None
        assert results["value"][0] == "retained"
        assert network.owned_worker_census() == 0
        assert spool.count_pending_entries(queue) == 1  # cancelled -> retained
    finally:
        stall.set()
        server.server_close()


def test_nonquiescent_release_retains_exclusion(tmp_path, monkeypatch):
    """If reaping is not yet complete, the host phase exclusion must stay held
    until the owned worker is quiescent — a collector cannot start while a
    cancelled worker still owns live transport I/O."""
    monkeypatch.setattr(network, "WORKER_QUIESCE_SYNC_JOIN_SECONDS", 0.1, raising=False)
    phase_dir = str(tmp_path / "phase")
    monkeypatch.setenv("ENCODINGDB_HOST_PHASE_DIR", phase_dir)
    _FaultHandler.mode = "stall-submit"
    stall = threading.Event()
    _FaultHandler.stall = stall
    server, base_url = _start(_FaultHandler)
    queue = str(tmp_path / "queue")
    path, _entry = spool.spool_payload(queue, {"cpuModel": "A", "fps": 1})
    results = {}
    cancel = threading.Event()
    try:
        def body():
            try:
                results["value"] = spool.submit_spooled_path(
                    path, queue_dir=queue, base_url=base_url, api_key="",
                    retries=1, use_token=False, cancel_event=cancel)
            except BaseException as exc:  # noqa: BLE001 - recorded for assertion
                results["error"] = exc
        runner = threading.Thread(target=body, daemon=True)
        runner.start()
        assert _wait_until(lambda: any("POST" in s for s in _FaultHandler.seen))
        cancel.set()
        # Drain grace (0.1 s) expires while the worker is still stalled; the
        # releasing call returns, but exclusion must NOT be released yet.
        runner.join(5)
        assert not runner.is_alive(), "release should not block past the drain grace"
        assert results.get("error") is None
        assert network.owned_worker_census() >= 1

        probe = {}

        def probe_phase():
            try:
                with spool.host_phase_hold("measurement"):
                    probe["acquired"] = True
            except spool.SpoolCapacityError:
                probe["acquired"] = False
        watcher = threading.Thread(target=probe_phase, daemon=True)
        watcher.start()
        watcher.join(5)
        assert probe.get("acquired") is False, (
            "host phase exclusion was released while an owned worker still "
            "performed transport I/O")

        stall.set()
        assert _wait_until(lambda: network.owned_worker_census() == 0, timeout=10)
        assert _wait_until(lambda: not spool.host_phase_busy(), timeout=10)
        # The cancelled worker finished its single in-flight request; it must
        # not start new I/O after release.
        assert _FaultHandler.seen.count("POST /submit") == 1
    finally:
        stall.set()
        server.server_close()


def test_census_reports_no_owned_workers_without_activity():
    assert network.owned_worker_census() == 0