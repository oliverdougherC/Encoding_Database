"""F3 (October 1 review): online bootstrap metadata transport is cancellable,
absolute-deadline bounded, size bounded, and owned.

`check_compatibility` and `fetch_baseline_rows` performed synchronous eager
Requests GETs (`timeout=10`/`timeout=15` are per-socket-inactivity, not total
response deadlines). A chunked drip kept the blocking call alive indefinitely:
GUI/CLI Stop stayed ignored while bytes arrived periodically, and the baseline
GET immediately before measurement could not be interrupted at all.

Every test here drives IMPORTED production functions through their normal
online entry points (`network.check_compatibility`, `network.fetch_baseline_rows`,
`main.run_with_args`, `main.main --upload-only`, `main.run_benchmark_batch`,
the real Windows GUI worker) against real local HTTP servers. No source
excerpts, no copied helpers.
"""
import contextlib
import io
import json
import os
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional
from unittest import mock

import pytest

from client import config, main, network, protocol, spool
from client.network import SubmissionCancelled, SubmitError
from client.suite import SUITE_VERSION, load_suite_pack_metadata


# ---------------------------------------------------------------------------
# fault servers (real local HTTP; drip patterns from the review repro)
# ---------------------------------------------------------------------------

def compat_contract() -> Dict[str, Any]:
    return {
        "protocolVersion": config.BENCHMARK_PROTOCOL_VERSION,
        "minimumClientVersion": "client/0.3.0",
        "encodeTimerBoundary": "ffmpeg-process-v1",
        "sourceSuiteVersion": SUITE_VERSION,
        "suiteFingerprint": load_suite_pack_metadata().get("suiteFingerprint"),
    }


class _FaultServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _MetadataHandler(BaseHTTPRequestHandler):
    """Configurable metadata fault server for /v7/compatibility and /query."""
    protocol_version = "HTTP/1.1"

    mode: ClassVar[str] = "ok"
    seen: ClassVar[List[str]] = []
    drip_seconds: ClassVar[float] = 30.0
    body: ClassVar[Optional[bytes]] = None
    client_gone: ClassVar[Optional[threading.Event]] = None
    written: ClassVar[int] = 0

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _drip_headers(self) -> None:
        # Status line + a fresh header line every 0.4 s: the socket-level read
        # timeout resets forever and urllib3's total deadline is not enforced
        # across header reads.
        self.wfile.write(b"HTTP/1.1 200 OK\r\n")
        self.wfile.flush()
        stop = time.monotonic() + type(self).drip_seconds
        while time.monotonic() < stop:
            time.sleep(0.4)
            self.wfile.write(b"X-Drip: 1\r\n")
            self.wfile.flush()
        self.close_connection = True

    def _drip_body(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        stop = time.monotonic() + type(self).drip_seconds
        try:
            while time.monotonic() < stop:
                self.wfile.write(b"2\r\n{}\r\n")
                self.wfile.flush()
                time.sleep(0.4)
        except OSError:
            if type(self).client_gone is not None:
                type(self).client_gone.set()
        self.close_connection = True

    def _stall_body(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", "100000")
        self.end_headers()
        try:
            self.wfile.write(b"[")
            self.wfile.flush()
            time.sleep(type(self).drip_seconds)
        except OSError:
            if type(self).client_gone is not None:
                type(self).client_gone.set()
        self.close_connection = True

    def _oversized_body(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(9 << 20))
        self.end_headers()
        stop = time.monotonic() + type(self).drip_seconds
        try:
            while time.monotonic() < stop:
                self.wfile.write(b"a" * 65536)
                self.wfile.flush()
                time.sleep(0.05)
        except OSError:
            if type(self).client_gone is not None:
                type(self).client_gone.set()
        self.close_connection = True

    def _error_huge_body(self) -> None:
        # 503 with a drip-fed multi-MiB error body: the child must stop
        # consuming at ERROR_BODY_HARD_CAP_BYTES and close the connection,
        # so the server EPIPEs after ~the cap (written-bytes accounting is
        # the deterministic proof; the old eager read streamed ~4 MiB).
        self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        stop = time.monotonic() + type(self).drip_seconds
        try:
            while time.monotonic() < stop:
                payload = b"10000\r\n" + b"e" * 65536 + b"\r\n"
                self.wfile.write(payload)
                self.wfile.flush()
                type(self).written += len(payload)
                time.sleep(0.05)
        except OSError:
            if type(self).client_gone is not None:
                type(self).client_gone.set()
        self.close_connection = True

    def _exact_body(self) -> None:
        # A 200 body of EXACTLY the caller's maxBytes: budget = cap+1 must
        # still deliver (and parse) it whole.
        body = type(self).body or b"[]"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _oversized_chunked(self) -> None:
        # No trustworthy Content-Length: only CONSUMED-byte accounting can
        # enforce the cap (the child must stop at exactly cap+1).
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        stop = time.monotonic() + type(self).drip_seconds
        try:
            while time.monotonic() < stop:
                self.wfile.write(b"10000\r\n" + b"a" * 65536 + b"\r\n")
                self.wfile.flush()
        except OSError:
            if type(self).client_gone is not None:
                type(self).client_gone.set()
        self.close_connection = True

    def _redirect(self) -> None:
        self.send_response(302)
        self.send_header("Location", "/elsewhere")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        type(self).seen.append(self.path)
        mode = type(self).mode
        if self.path.startswith("/v7/compatibility"):
            if mode == "ok":
                return self._json(type(self).body if type(self).body is not None
                                  else compat_contract())
            if mode == "drip-headers":
                return self._drip_headers()
            if mode == "drip-body":
                return self._drip_body()
            if mode == "stall-body":
                return self._stall_body()
            if mode == "oversized":
                return self._oversized_body()
            if mode == "oversized-chunked":
                return self._oversized_chunked()
            if mode == "redirect":
                return self._redirect()
            if mode == "garbage":
                return self._json(b"\x00not-json\x01\x02")
            if mode == "error":
                return self._json({"error": "unavailable"}, status=503)
            if mode == "error-huge":
                return self._error_huge_body()
            if mode == "exact":
                return self._exact_body()
        if self.path.startswith("/query"):
            if mode == "ok":
                return self._json([{"id": 1, "encoder": "libx264"}])
            if mode in ("drip-body", "drip-headers"):
                return self._drip_body()
            if mode == "stall-body":
                return self._stall_body()
            if mode == "error":
                return self._json({"error": "unavailable"}, status=500)
            if mode == "redirect":
                return self._redirect()
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def _start(handler) -> Any:
    server = _FaultServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _reset(handler, mode: str, **attrs) -> None:
    handler.mode = mode
    handler.seen = []
    handler.body = None
    handler.written = 0
    handler.client_gone = threading.Event()
    for key, value in attrs.items():
        setattr(handler, key, value)


def _wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _await_quiescent(timeout: float = 5.0) -> bool:
    """No owned transport I/O may outlive a metadata fetch: zero worker
    threads AND zero live metadata child processes (the F3 ownership
    invariant on every return/deadline/Stop/exception path)."""
    return _wait_until(lambda: network.owned_worker_census() == 0
                       and network.owned_metadata_children() == 0,
                       timeout=timeout)


@contextlib.contextmanager
def _no_baseline_cache():
    prior = (config._BASELINE_ROWS_CACHE, config._BASELINE_ROWS_CACHE_TS)
    config._BASELINE_ROWS_CACHE = None
    config._BASELINE_ROWS_CACHE_TS = 0.0
    try:
        yield
    finally:
        config._BASELINE_ROWS_CACHE, config._BASELINE_ROWS_CACHE_TS = prior


def _call_bounded(function, *, timeout: float, stop_after: Any = None):
    """Run `function` on a daemon thread; the FAILING-BEFORE uncancellable GET
    must not hang the suite: the join bound is the test assertion, and closing
    the fault server in the caller's finally lets the daemon wake on socket
    error instead of leaking. `stop_after=(delay, fire)` arms the user Stop
    CONCURRENTLY — setting it after this join would never interrupt the call."""
    outcome: Dict[str, Any] = {}

    def _run() -> None:
        try:
            outcome["value"] = function()
        except BaseException as exc:  # noqa: BLE001 - recorded for assertion
            outcome["error"] = exc
        outcome["done"] = time.monotonic()

    started = time.monotonic()
    caller = threading.Thread(target=_run, daemon=True)
    caller.start()
    timer = None
    if stop_after is not None:
        delay, fire = stop_after
        timer = threading.Timer(delay, fire)
        timer.daemon = True
        timer.start()
    caller.join(timeout)
    if timer is not None:
        timer.cancel()
    outcome["elapsed"] = time.monotonic() - started
    return outcome


# ---------------------------------------------------------------------------
# stable contract through real local HTTP (passes before and after)
# ---------------------------------------------------------------------------

def test_fast_compat_and_baseline_contract_over_real_http():
    _reset(_MetadataHandler, "ok")
    server, base_url = _start(_MetadataHandler)
    try:
        contract = network.check_compatibility(base_url, "client/0.3.0")
        assert contract["protocolVersion"] == config.BENCHMARK_PROTOCOL_VERSION
        with _no_baseline_cache():
            rows = network.fetch_baseline_rows(base_url)
            assert rows == [{"id": 1, "encoder": "libx264"}]
            # Cache holds the successful lookup: the server is not re-hit.
            assert network.fetch_baseline_rows(base_url) == rows
        assert _MetadataHandler.seen.count("/v7/compatibility") == 1
        assert _MetadataHandler.seen.count("/query?limit=500") == 1
    finally:
        server.shutdown()
        server.server_close()


def test_redirects_are_not_followed():
    _reset(_MetadataHandler, "redirect")
    server, base_url = _start(_MetadataHandler)
    try:
        with pytest.raises(SubmitError):
            network.check_compatibility(base_url, "client/0.3.0")
        with _no_baseline_cache():
            with pytest.raises(SubmitError):
                network.fetch_baseline_rows(base_url)
        assert "/elsewhere" not in _MetadataHandler.seen
    finally:
        server.shutdown()
        server.server_close()


def test_incompatible_contract_stays_fail_closed():
    _reset(_MetadataHandler, "ok", body={**compat_contract(), "protocolVersion": "6.0"})
    server, base_url = _start(_MetadataHandler)
    try:
        with pytest.raises(SubmitError) as raised:
            network.check_compatibility(base_url, "client/0.3.0")
        assert raised.value.retryable is False
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# F3 failing-before: drip-fed bodies/headers ignore every bound and Stop
# ---------------------------------------------------------------------------

def test_compat_dripped_body_absolute_deadline_is_enforced_while_data_arrives():
    """Review repro: chunked drip kept the eager GET alive indefinitely."""
    _reset(_MetadataHandler, "drip-body", drip_seconds=30.0)
    server, base_url = _start(_MetadataHandler)
    try:
        outcome = _call_bounded(
            lambda: network.check_compatibility(
                base_url, "client/0.3.0", transaction_seconds=1.5),
            timeout=8.0)
        assert outcome.get("done"), (
            "check_compatibility ignored its absolute deadline for 8s while "
            "chunked body bytes kept arriving")
        assert outcome["elapsed"] < 4.0, outcome["elapsed"]
        error = outcome.get("error")
        assert isinstance(error, SubmitError), error
        assert error.retryable is True
        assert _await_quiescent(), \
            "timed-out metadata fetch left unowned transport I/O"
    finally:
        server.shutdown()
        server.server_close()


def test_compat_slow_headers_stop_cancels_promptly():
    """GUI Stop must interrupt a blocked header read within ~poll+close."""
    _reset(_MetadataHandler, "drip-headers", drip_seconds=30.0)
    server, base_url = _start(_MetadataHandler)
    stop = threading.Event()
    try:
        outcome = _call_bounded(
            lambda: network.check_compatibility(
                base_url, "client/0.3.0", cancel_event=stop),
            timeout=8.0, stop_after=(0.4, stop.set))
        assert outcome.get("done"), (
            "Stop remained ignored for 8s while header bytes arrived "
            "periodically (the review's 11.203s repro)")
        assert outcome["elapsed"] < 4.0, outcome["elapsed"]
        assert isinstance(outcome.get("error"), SubmissionCancelled), outcome.get("error")
        assert _await_quiescent(), \
            "abandoned metadata fetch left unowned transport I/O"
    finally:
        stop.set()
        server.shutdown()
        server.server_close()


def test_compat_stalled_body_deadline_without_user_stop():
    """Headers arrive, then silence: the absolute deadline still returns."""
    _reset(_MetadataHandler, "stall-body", drip_seconds=30.0)
    server, base_url = _start(_MetadataHandler)
    try:
        outcome = _call_bounded(
            lambda: network.check_compatibility(
                base_url, "client/0.3.0", transaction_seconds=1.5),
            timeout=8.0)
        assert outcome.get("done"), "stalled body blocked past any deadline"
        assert outcome["elapsed"] < 4.0, outcome["elapsed"]
        assert isinstance(outcome.get("error"), SubmitError), outcome.get("error")
    finally:
        server.shutdown()
        server.server_close()


def test_compat_oversized_body_is_size_bounded_and_rejected():
    """A 9 MiB drip is stopped at the hard JSON cap, not consumed eagerly."""
    _reset(_MetadataHandler, "oversized", drip_seconds=30.0)
    server, base_url = _start(_MetadataHandler)
    try:
        outcome = _call_bounded(
            lambda: network.check_compatibility(
                base_url, "client/0.3.0", transaction_seconds=2.0),
            timeout=8.0)
        assert outcome.get("done"), "oversized body was consumed without a cap"
        assert outcome["elapsed"] < 5.0, outcome["elapsed"]
        assert isinstance(outcome.get("error"), SubmitError), outcome.get("error")
    finally:
        server.shutdown()
        server.server_close()


def test_dns_failure_is_bounded_and_redacted():
    with pytest.raises(SubmitError) as raised:
        network.check_compatibility("http://encodingdb-f3-invalid.invalid",
                                    "client/0.3.0", transaction_seconds=2.0)
    assert raised.value.retryable is True
    assert "encodingdb-f3-invalid.invalid" not in str(raised.value)
    assert _await_quiescent()


def test_connect_refusal_is_bounded_and_redacted():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    with pytest.raises(SubmitError) as raised:
        network.check_compatibility(f"http://127.0.0.1:{port}",
                                    "client/0.3.0", transaction_seconds=2.0)
    assert raised.value.retryable is True
    assert str(port) not in str(raised.value)
    assert _await_quiescent()


# ---------------------------------------------------------------------------
# optional baseline must never block useful contribution
# ---------------------------------------------------------------------------

def test_baseline_failure_is_optional_and_does_not_poison_cache():
    _reset(_MetadataHandler, "error")
    server, base_url = _start(_MetadataHandler)
    try:
        with _no_baseline_cache():
            with pytest.raises(SubmitError):
                network.fetch_baseline_rows(base_url)
            # A failed lookup must not be cached: the next batch retries.
            assert config._BASELINE_ROWS_CACHE is None
    finally:
        server.shutdown()
        server.server_close()


def test_baseline_drip_is_bounded_without_user_stop():
    _reset(_MetadataHandler, "drip-body", drip_seconds=30.0)
    server, base_url = _start(_MetadataHandler)
    try:
        with _no_baseline_cache():
            outcome = _call_bounded(
                lambda: network.fetch_baseline_rows(
                    base_url, transaction_seconds=1.5),
                timeout=8.0)
        assert outcome.get("done"), (
            "fetch_baseline_rows blocked past any deadline while drip-fed "
            "(15s per-inactivity timeout reset forever)")
        assert outcome["elapsed"] < 4.0, outcome["elapsed"]
        assert isinstance(outcome.get("error"), SubmitError), outcome.get("error")
    finally:
        server.shutdown()
        server.server_close()


def test_baseline_stop_is_prompt():
    _reset(_MetadataHandler, "drip-body", drip_seconds=30.0)
    server, base_url = _start(_MetadataHandler)
    stop = threading.Event()
    try:
        with _no_baseline_cache():
            outcome = _call_bounded(
                lambda: network.fetch_baseline_rows(base_url, cancel_event=stop),
                timeout=8.0, stop_after=(0.4, stop.set))
        assert outcome.get("done"), "Stop could not interrupt the baseline GET"
        assert outcome["elapsed"] < 4.0, outcome["elapsed"]
        assert isinstance(outcome.get("error"), SubmissionCancelled), outcome.get("error")
    finally:
        stop.set()
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# normal online entry points: CLI run, CLI --upload-only, batch, GUI worker
# ---------------------------------------------------------------------------

def _client_args(tmp_path, base_url):
    return main.build_arg_parser().parse_args(
        ["--submit", "--base-url", base_url, "--queue-dir", str(tmp_path)])


def test_cli_online_run_stop_during_compatibility_returns_130(tmp_path):
    """`main.run_with_args(..., --submit)` is the normal online CLI entry."""
    _reset(_MetadataHandler, "drip-headers", drip_seconds=30.0)
    server, base_url = _start(_MetadataHandler)
    stop = threading.Event()
    events: List[Dict[str, Any]] = []
    try:
        def _run():
            return main.run_with_args(_client_args(tmp_path, base_url),
                                      event_sink=events.append,
                                      cancel_event=stop, interactive=False)
        outcome = _call_bounded(_run, timeout=10.0, stop_after=(0.4, stop.set))
        assert outcome.get("done"), (
            "Stop was ignored for 10s by the compatibility GET inside the "
            "normal online CLI preparation path")
        assert outcome["elapsed"] < 5.0, outcome["elapsed"]
        assert outcome.get("value") == 130, outcome
        assert any(event.get("type") == "run_interrupted" for event in events)
    finally:
        stop.set()
        server.shutdown()
        server.server_close()


def test_cli_upload_only_deadline_bounds_drip_without_user_stop(tmp_path):
    """Deadline with NO user Stop must return a bounded deferred result."""
    _reset(_MetadataHandler, "drip-body", drip_seconds=25.0)
    server, base_url = _start(_MetadataHandler)
    try:
        outcome = _call_bounded(
            lambda: main.main(["prog", "--upload-only", "--base-url", base_url,
                               "--queue-dir", str(tmp_path)]),
            timeout=16.0)
        assert outcome.get("done"), (
            "--upload-only compatibility GET never returned while bytes "
            "arrived; there is no absolute deadline without a user Stop")
        assert outcome["elapsed"] < 14.0, outcome["elapsed"]
        assert outcome.get("value") == 10, outcome  # deferred, never crash
    finally:
        server.shutdown()
        server.server_close()


def _batch_patches(fixture, tmp_path, encode_side_effect):
    from test_main_routing import _DummyDashboard
    return [
        mock.patch.object(main, "ensure_ffmpeg_and_ffprobe", return_value=(True, "ffmpeg test")),
        mock.patch.object(main, "_build_protocol_config",
                          return_value=protocol.ProtocolConfig.for_version(
                              "7.1", max_adaptive_repeats=0)),
        mock.patch.object(main, "probe_video_stream_metrics",
                          return_value={"sourceFps": 24, "sourceDurationSeconds": 5,
                                        "containerFormat": "mp4"}),
        mock.patch.object(main, "_probe_artifact_contract",
                          side_effect=lambda path: fixture._artifact_contract()),
        mock.patch.object(main, "_capture_protocol_environment_snapshot",
                          return_value=protocol.EnvironmentSnapshot(
                              selected_accelerator="software")),
        mock.patch.object(main, "encode_to_artifact", side_effect=encode_side_effect),
        mock.patch.object(main, "BatchRunDashboard", _DummyDashboard),
        mock.patch.object(main, "_replay_pending_uploads", return_value=0),
        mock.patch.object(spool, "submit_artifact_submission",
                          return_value=("retained", "cancelled")),
    ]


def _batch_fixture(tmp_path, monkeypatch):
    from test_main_routing import MainRoutingTests
    monkeypatch.setenv("ENCODINGDB_HOST_PHASE_DIR", str(tmp_path / "phase"))
    fixture = MainRoutingTests()
    clip = fixture._quick_clip()
    args = fixture._batch_args(str(tmp_path), no_submit=False)
    args.local_metrics = False
    args.campaign_seed = 91
    args.max_duration_minutes = 1.0
    return fixture, clip, args


def test_batch_stop_during_baseline_honors_stop_and_never_encodes(tmp_path, monkeypatch):
    """The baseline GET runs immediately before measurement; Stop must land."""
    _reset(_MetadataHandler, "drip-body", drip_seconds=30.0)
    server, base_url = _start(_MetadataHandler)
    stop = threading.Event()
    events: List[Dict[str, Any]] = []
    encodes: List[str] = []
    try:
        fixture, clip, args = _batch_fixture(tmp_path, monkeypatch)

        def encode(**kwargs):
            encodes.append(kwargs["artifact_name"])
            raise AssertionError("a stopped batch must never start an encode")

        hardware = main.HardwareInfo("CPU", None, 16, "OS")
        patches = _batch_patches(fixture, tmp_path, encode)
        patches.append(mock.patch.object(main, "check_compatibility", return_value={}))
        patches.append(mock.patch.object(main, "detect_hardware", return_value=hardware))
        for patcher in patches:
            patcher.start()
        try:
            with _no_baseline_cache():
                outcome = _call_bounded(
                    lambda: main.run_benchmark_batch(
                        hardware=hardware, base_url=base_url, args=args,
                        tasks=[{"encoder": "libx264", "preset": "fast", "crf": 24,
                                "suiteClip": clip}],
                        event_sink=events.append, cancel_event=stop),
                    timeout=10.0, stop_after=(0.4, stop.set))
        finally:
            for patcher in patches:
                patcher.stop()
        assert outcome.get("done"), (
            "Stop was ignored for 10s by the pre-measurement baseline GET "
            "inside run_benchmark_batch")
        assert outcome["elapsed"] < 5.0, outcome["elapsed"]
        assert outcome.get("value") == 130, outcome
        assert not encodes
        assert any(event.get("type") == "run_interrupted" for event in events)
        assert _await_quiescent(), \
            "the cancelled baseline fetch left unowned transport I/O"
    finally:
        stop.set()
        server.shutdown()
        server.server_close()


def test_batch_baseline_deadline_keeps_contribution_alive(tmp_path, monkeypatch):
    """No Stop: a timed-out optional baseline must not block the encodes."""
    _reset(_MetadataHandler, "drip-body", drip_seconds=30.0)
    server, base_url = _start(_MetadataHandler)
    stop = threading.Event()
    events: List[Dict[str, Any]] = []
    encodes: List[float] = []
    try:
        monkeypatch.setattr(network, "METADATA_TRANSACTION_SECONDS", 1.5, raising=False)
        fixture, clip, args = _batch_fixture(tmp_path, monkeypatch)

        def encode(**kwargs):
            encodes.append(time.monotonic())
            artifact = Path(kwargs["out_dir"]) / kwargs["artifact_name"]
            artifact.write_bytes(b"encoded")
            stop.set()  # one encode is enough to prove contribution resumed
            return {"artifactPath": str(artifact), "encoderUsed": "libx264",
                    "presetUsed": "fast", "fileSizeBytes": 7,
                    "encodeStartMonotonicNs": 1_000_000_000,
                    "encodeEndMonotonicNs": 2_000_000_000,
                    "elapsedMs": 1000, "error": None}

        hardware = main.HardwareInfo("CPU", None, 16, "OS")
        patches = _batch_patches(fixture, tmp_path, encode)
        patches.append(mock.patch.object(main, "check_compatibility", return_value={}))
        patches.append(mock.patch.object(main, "detect_hardware", return_value=hardware))
        for patcher in patches:
            patcher.start()
        try:
            with _no_baseline_cache():
                started = time.monotonic()
                outcome = _call_bounded(
                    lambda: main.run_benchmark_batch(
                        hardware=hardware, base_url=base_url, args=args,
                        tasks=[{"encoder": "libx264", "preset": "fast", "crf": 24,
                                "suiteClip": clip}],
                        event_sink=events.append, cancel_event=stop),
                    timeout=15.0)
                outcome["wall"] = time.monotonic() - started
        finally:
            for patcher in patches:
                patcher.stop()
        assert outcome.get("done"), "a dead baseline GET blocked the batch forever"
        assert outcome["wall"] < 12.0, outcome["wall"]
        assert encodes, "timed-out optional baseline prevented useful contribution"
        assert outcome.get("value") == 130, outcome
    finally:
        stop.set()
        server.shutdown()
        server.server_close()


def test_gui_online_stop_during_compatibility(tmp_path, monkeypatch):
    """The real GUI worker + the real Stop button path during online prep."""
    from test_progress_contract import _build_gui_app
    _reset(_MetadataHandler, "drip-headers", drip_seconds=30.0)
    server, base_url = _start(_MetadataHandler)
    try:
        app = _build_gui_app()
        monkeypatch.setattr(main, "_ensure_interactive_publication_consent",
                            lambda **kwargs: True)
        run_args = _client_args(tmp_path, base_url)
        run_args.no_submit = False
        run_args.local_metrics = False
        monkeypatch.setenv("ENCODINGDB_HOST_PHASE_DIR", str(tmp_path / "phase"))

        def _worker():
            app._run_worker(run_args, "Small", "small")

        app.running = True  # the state _stop_run guards on after a real start
        caller = threading.Thread(target=_worker, daemon=True)
        caller.start()
        time.sleep(0.5)
        app._stop_run()  # the real Stop button command
        caller.join(8.0)
        assert not caller.is_alive(), (
            "GUI Stop remained ignored for 8s by the compatibility GET on the "
            "online run worker thread")
        done = None
        while not app.event_queue.empty():
            kind, payload = app.event_queue.get_nowait()
            if kind == "done":
                done = payload
        assert done == 130, done
        assert _await_quiescent()
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# owned-subprocess containment: stalled DNS/connect windows, late socket
# allocation, Close-time reaping (the review's late-DNS IO repro)
# ---------------------------------------------------------------------------

def _stalled_env(tmp_path, *, release_after=None):
    """Env for a child that stalls BEFORE any socket exists (the deterministic
    core of a hung resolver / stalled connect). 'forever' = killable only by
    the parent (EOF/SIGKILL); a file path = delayed socket allocation."""
    env = dict(network.os.environ)
    if release_after is None:
        env[network.METADATA_CHILD_STALL_ENV] = "forever"
    else:
        env[network.METADATA_CHILD_STALL_ENV] = str(release_after)
    return env


def test_stalled_dns_window_hard_deadline_kills_child_zero_late_io(tmp_path, monkeypatch):
    """Review late-DNS repro (in-process design): a worker parked in
    getaddrinfo past the deadline later CONNECTED and issued a real GET
    during measurement. The owned child has no in-process thread to park —
    the hard deadline kills the whole process, so nothing can arrive late."""
    _reset(_MetadataHandler, "ok")
    server, base_url = _start(_MetadataHandler)
    monkeypatch.setenv(network.METADATA_CHILD_STALL_ENV, "forever")
    try:
        outcome = _call_bounded(
            lambda: network.check_compatibility(base_url, "client/0.3.0",
                                                transaction_seconds=1.0),
            timeout=8.0)
        assert outcome.get("done"), "a stalled-resolver child blocked the deadline"
        assert outcome["elapsed"] < 4.0, outcome["elapsed"]
        assert isinstance(outcome.get("error"), SubmitError), outcome.get("error")
        assert _await_quiescent(), "the stalled child outlived its deadline"
        time.sleep(0.75)  # a late connect would land here in the old design
        assert not _MetadataHandler.seen, "late DNS/connect I/O after the deadline"
    finally:
        server.shutdown()
        server.server_close()


def test_stalled_dns_window_stop_kills_child_promptly(tmp_path, monkeypatch):
    """Stop during the pre-socket window must not create an abandoned worker:
    the child is killed and reaped, census zero."""
    _reset(_MetadataHandler, "ok")
    server, base_url = _start(_MetadataHandler)
    monkeypatch.setenv(network.METADATA_CHILD_STALL_ENV, "forever")
    stop = threading.Event()
    try:
        outcome = _call_bounded(
            lambda: network.check_compatibility(base_url, "client/0.3.0",
                                                cancel_event=stop),
            timeout=8.0, stop_after=(0.4, stop.set))
        assert outcome.get("done"), "Stop could not interrupt a stalled child"
        assert outcome["elapsed"] < 4.0, outcome["elapsed"]
        assert isinstance(outcome.get("error"), SubmissionCancelled), outcome.get("error")
        assert _await_quiescent(), "the Stop-abandoned child was left alive"
        assert not _MetadataHandler.seen
    finally:
        server.shutdown()
        server.server_close()


def test_delayed_socket_allocation_after_deadline_cannot_send(tmp_path):
    """Late-connect window: the child's resolver/connect is released AFTER
    the parent's deadline has already fired and reaped. Because ownership
    killed the process, the late socket is never allocated and the server
    receives nothing — the exact behavior the review's repro inverted."""
    _reset(_MetadataHandler, "ok")
    server, base_url = _start(_MetadataHandler)
    gate = tmp_path / "resolver-release"
    monkeypatch_env = _stalled_env(tmp_path, release_after=gate)
    with mock.patch.dict(network.os.environ, monkeypatch_env):
        try:
            outcome = _call_bounded(
                lambda: network.check_compatibility(base_url, "client/0.3.0",
                                                    transaction_seconds=1.0),
                timeout=8.0)
            assert outcome.get("done") and isinstance(outcome.get("error"), SubmitError)
            assert _await_quiescent()
            gate.touch()  # "resolver answers" only after the fetch is over
            time.sleep(1.0)
            assert not _MetadataHandler.seen, (
                "a reaped child still reached the network after the deadline")
        finally:
            server.shutdown()
            server.server_close()


def test_cli_upload_only_stalled_dns_no_late_io_during_measurement(tmp_path, monkeypatch):
    """FAITHFUL conversion of reproduce-f3-late-dns-io.py through the normal
    production CLI: deadline must return rc 10, and after the CLI returns,
    the host measurement EX must be acquirable with ZERO metadata requests
    arriving during the hold (before/after the stall is released)."""
    _reset(_MetadataHandler, "ok")
    server, base_url = _start(_MetadataHandler)
    monkeypatch.setenv("ENCODINGDB_HOST_PHASE_DIR", str(tmp_path / "phase"))
    monkeypatch.setenv(network.METADATA_CHILD_STALL_ENV, "forever")
    monkeypatch.setattr(network, "METADATA_TRANSACTION_SECONDS", 0.5, raising=False)
    try:
        outcome = _call_bounded(
            lambda: main.main(["prog", "--upload-only", "--base-url", base_url,
                               "--queue-dir", str(tmp_path / "queue")]),
            timeout=10.0)
        assert outcome.get("done"), "the stalled-resolver CLI never returned"
        assert outcome.get("value") == 10, outcome  # bounded deferred, never crash
        assert outcome["elapsed"] < 6.0, outcome["elapsed"]
        assert network.owned_metadata_children() == 0, (
            "ownedWorkersAfterDeadline: the metadata child outlived the CLI deadline")
        acquired = False
        measuring = threading.Event()
        received: List[bool] = []
        original_do_GET = _MetadataHandler.do_GET

        def _spy(self):
            received.append(measuring.is_set())
            return original_do_GET(self)
        _MetadataHandler.do_GET = _spy
        try:
            with spool.host_phase_hold("measurement"):
                acquired = True
                measuring.set()
                monkeypatch.delenv(network.METADATA_CHILD_STALL_ENV, raising=False)
                time.sleep(1.0)  # a surviving child would connect+GET now
                measuring.clear()
        finally:
            _MetadataHandler.do_GET = original_do_GET
        assert acquired, "a dead metadata child still held host exclusion"
        assert not any(received), (
            "httpRequestAfterDeadlineDuringMeasurement: metadata I/O during timed work")
        assert network.owned_metadata_children() == 0
    finally:
        _reset(_MetadataHandler, "ok")
        server.shutdown()
        server.server_close()


def test_close_grace_reaper_kills_hung_metadata_child(tmp_path, monkeypatch):
    """GUI Close grace expiry reaps descendants through the REAL
    `_terminate_owned_children` (psutil recursive children): a hung metadata
    child must die with it — Stop/Close never leaves an abandoned worker."""
    from client.windows_gui import _terminate_owned_children
    env = _stalled_env(tmp_path)
    with mock.patch.dict(network.os.environ, env):
        proc = None
        try:
            proc = subprocess.Popen(
                [network.sys.executable, "-m", "client", network.METADATA_CHILD_ARGV,
                 "compatibility"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=env)
            proc.stdin.write(json.dumps({"url": "http://127.0.0.1:9/x",
                                         "maxBytes": 1024,
                                         "boundSeconds": 30.0}).encode())
            proc.stdin.flush()
            network._register_metadata_child(proc)
            assert network.owned_metadata_children() == 1
            _terminate_owned_children()  # the production Close-expiry reaper
            proc.wait(5)
            assert proc.poll() is not None, "hung metadata child survived Close reaping"
        finally:
            if proc is not None:
                network._unregister_metadata_child(proc)
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(5)


def test_child_bootstrap_dispatch_is_startup_only():
    """`python -m client --metadata-child` is dispatched BEFORE argument
    parsing/GUI/campaign routing: empty stdin exits immediately (code 2)
    instead of opening a run, a queue or a GUI."""
    started = time.monotonic()
    proc = subprocess.run([network.sys.executable, "-m", "client",
                           network.METADATA_CHILD_ARGV, "compatibility"],
                          input=b"", capture_output=True, timeout=30,
                          cwd=str(Path(network.__file__).resolve().parent.parent))
    assert proc.returncode == 2, proc.stderr[-400:]
    assert time.monotonic() - started < 20.0


def test_child_bootstrap_rejects_oversized_request():
    proc = subprocess.run([network.sys.executable, "-m", "client",
                           network.METADATA_CHILD_ARGV, "compatibility"],
                          input=b"x" * 70000, capture_output=True, timeout=30,
                          cwd=str(Path(network.__file__).resolve().parent.parent))
    assert proc.returncode == 2


def test_gui_online_close_during_compatibility_kills_child(tmp_path, monkeypatch):
    """Close during online preparation must stop the online entry AND leave
    no owned metadata child: Close sets the same cancel event the transport
    polls, the child is killed and reaped, and the Close grace path then
    finds the worker quiescent (normal destroy, no forced os._exit)."""
    from test_progress_contract import _build_gui_app
    _reset(_MetadataHandler, "ok")
    server, base_url = _start(_MetadataHandler)
    monkeypatch.setenv(network.METADATA_CHILD_STALL_ENV, "forever")
    try:
        app = _build_gui_app()
        monkeypatch.setattr(main, "_ensure_interactive_publication_consent",
                            lambda **kwargs: True)
        run_args = _client_args(tmp_path, base_url)
        run_args.no_submit = False
        run_args.local_metrics = False
        monkeypatch.setenv("ENCODINGDB_HOST_PHASE_DIR", str(tmp_path / "phase"))
        monkeypatch.setattr(network, "METADATA_TRANSACTION_SECONDS", 30.0, raising=False)

        def _worker():
            app._run_worker(run_args, "Small", "small")

        app.running = True
        caller = threading.Thread(target=_worker, daemon=True)
        app.worker_thread = caller
        caller.start()
        # The metadata child must actually exist (hung resolver window)
        # before Close runs — otherwise this proves nothing about reaping.
        assert _wait_until(lambda: network.owned_metadata_children() == 1, timeout=5.0), \
            "the online preparation child never entered the pre-socket window"
        app._on_close()  # confirmed Close: same cancel event as Stop
        caller.join(8.0)
        assert not caller.is_alive(), "Close could not stop the online entry"
        assert _await_quiescent(), "Close left the metadata child alive"
        done = None
        while not app.event_queue.empty():
            kind, payload = app.event_queue.get_nowait()
            if kind == "done":
                done = payload
        assert done == 130, done
        # Grace path with a quiescent worker: destroy, never os._exit.
        app.worker_thread = None
        app._close_deadline = time.monotonic() + 60.0
        app._close_when_stopped()
        app.root.destroy.assert_called()
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# final-review hardening: single cleanup owner, fail-closed retention,
# child-side hard consumption caps, anchored child dispatch
# ---------------------------------------------------------------------------

class _BlockedPipe:
    """stdout stand-in: read() blocks until close() (a real pipe EOF)."""

    def __init__(self) -> None:
        self._gate = threading.Event()

    def read(self, _size: int) -> bytes:
        self._gate.wait(30.0)
        return b""

    def close(self) -> None:
        self._gate.set()


class _StubbornProc:
    """Pathological child: kill() is ignored and wait() never confirms —
    exactly the SIGKILL-ignored case the retention path must fail closed on."""

    def __init__(self) -> None:
        self.stdin = io.BytesIO()
        self.stdout = _BlockedPipe()
        self.dead = False

    def poll(self):
        return 0 if self.dead else None

    def kill(self) -> None:
        return None  # ignored

    def wait(self, timeout=None):
        raise subprocess.TimeoutExpired("stubborn", timeout or 0)


class _DeadOnKillProc(_StubbornProc):
    def kill(self) -> None:
        self.dead = True

    def wait(self, timeout=None):
        return 0


def _child_request(url: str = "http://127.0.0.1:9/x") -> Dict[str, Any]:
    return {"url": url, "phase": "compatibility", "maxBytes": 4096,
            "remainingSeconds": 5.0, "boundSeconds": 5.0}


def test_popen_failure_raises_retryable_and_registers_nothing():
    with mock.patch.object(network.subprocess, "Popen",
                           side_effect=OSError("no fork left")):
        with pytest.raises(SubmitError) as raised:
            network._run_owned_metadata_child(_child_request(), phase="compatibility",
                                              cancel_event=None, deadline=None,
                                              bound_seconds=5.0)
    assert raised.value.retryable is True
    assert "OSError" in str(raised.value)
    assert network.owned_metadata_children() == 0
    assert network.owned_worker_census() == 0


def test_keyboard_interrupt_after_spawn_still_reaps_child():
    """The review's gap: an interrupt between spawn and the polling loop
    used to leave a REGISTERED live child with no cleanup owner."""
    proc = _DeadOnKillProc()

    class _InterruptingStdin(io.BytesIO):
        def write(self, _data):
            raise KeyboardInterrupt

    proc.stdin = _InterruptingStdin()
    with mock.patch.object(network.subprocess, "Popen", return_value=proc):
        with pytest.raises(KeyboardInterrupt):
            network._run_owned_metadata_child(_child_request(), phase="compatibility",
                                              cancel_event=None, deadline=None,
                                              bound_seconds=5.0)
    assert proc.dead is True, "cleanup owner did not kill the spawned child"
    assert network.owned_metadata_children() == 0
    assert network.owned_worker_census() == 0


def test_retained_child_fails_closed_and_defers_quiescence():
    """kill/wait cannot confirm death -> child stays REGISTERED, a deferred
    reaper becomes an owned worker, and the caller gets MetadataRetentionHeld
    (a pause, never a silent 'no baseline')."""
    proc = _StubbornProc()
    with mock.patch.object(network.subprocess, "Popen", return_value=proc):
        with pytest.raises(network.MetadataRetentionHeld):
            network._run_owned_metadata_child(_child_request(), phase="compatibility",
                                              cancel_event=None,
                                              deadline=time.monotonic() + 1.0,
                                              bound_seconds=1.0)
    try:
        assert network.owned_metadata_children() == 1, \
            "unconfirmed-dead child was unregistered anyway"
        assert network.owned_worker_census() >= 1, \
            "deferred reaper is not an owned worker"
        assert not network.wait_for_metadata_quiescence(0.3), \
            "measurement barrier passed while a retained child was live"
    finally:
        proc.dead = True  # the child finally dies; the reaper confirms it
    assert _await_quiescent(timeout=8.0), \
        "deferred reaper never confirmed death / unregistered the child"
    assert network.wait_for_metadata_quiescence(0.1)


def test_batch_never_encodes_after_non_quiescent_optional_lookup(tmp_path, monkeypatch):
    """A retention pause must surface as an interrupt (130) with ZERO timed
    encodes — never degraded into 'no baseline, keep going'."""
    _reset(_MetadataHandler, "ok")
    server, base_url = _start(_MetadataHandler)
    events: List[Dict[str, Any]] = []
    encodes: List[str] = []
    try:
        fixture, clip, args = _batch_fixture(tmp_path, monkeypatch)

        def encode(**kwargs):
            encodes.append(kwargs["artifact_name"])
            raise AssertionError("encoding started after a non-quiescent lookup")

        hardware = main.HardwareInfo("CPU", None, 16, "OS")
        patches = _batch_patches(fixture, tmp_path, encode)
        patches.append(mock.patch.object(main, "check_compatibility", return_value={}))
        patches.append(mock.patch.object(main, "detect_hardware", return_value=hardware))
        patches.append(mock.patch.object(main, "fetch_baseline_rows",
                                         side_effect=network.MetadataRetentionHeld(
                                             "baseline query")))
        for patcher in patches:
            patcher.start()
        try:
            outcome = _call_bounded(
                lambda: main.run_benchmark_batch(
                    hardware=hardware, base_url=base_url, args=args,
                    tasks=[{"encoder": "libx264", "preset": "fast", "crf": 24,
                            "suiteClip": clip}],
                    event_sink=events.append, cancel_event=None),
                timeout=10.0)
        finally:
            for patcher in patches:
                patcher.stop()
        assert outcome.get("done"), "retention pause did not return"
        assert outcome.get("value") == 130, outcome
        assert not encodes
        assert any(event.get("type") == "run_interrupted" for event in events)
    finally:
        server.shutdown()
        server.server_close()


def test_measurement_barrier_waits_for_confirmed_child_death():
    """The F3 barrier must WAIT (bounded) for a live child to be confirmed
    dead, and must honor Stop rather than waiting out the bound."""
    live = _StubbornProc()
    network._register_metadata_child(live)
    try:
        started = time.monotonic()
        threading.Timer(0.6, lambda: setattr(live, "dead", True)).start()
        assert network.wait_for_metadata_quiescence(4.0) is True
        waited = time.monotonic() - started
        assert 0.4 < waited < 3.0, waited  # waited for death, did not spin-out
        stop = threading.Event()
        live.dead = False
        threading.Timer(0.3, stop.set).start()
        started = time.monotonic()
        assert network.wait_for_metadata_quiescence(9.0, cancel_event=stop) is False
        assert time.monotonic() - started < 2.0, "Stop did not abort the barrier"
    finally:
        live.dead = True
        network._unregister_metadata_child(live)


def test_child_consumes_error_body_only_to_the_hard_cap():
    """Non-200 drip: the CHILD stops consuming at ERROR_BODY_HARD_CAP_BYTES
    and closes, so the server sees EPIPE promptly — even though the absolute
    deadline is still 20 s away (old eager read would stream the whole body)."""
    _reset(_MetadataHandler, "error-huge", drip_seconds=25.0)
    server, base_url = _start(_MetadataHandler)
    try:
        outcome = _call_bounded(
            lambda: network.check_compatibility(
                base_url, "client/0.3.0", transaction_seconds=20.0),
            timeout=12.0)
        assert outcome.get("done"), "error-body drip was consumed unbounded"
        assert outcome["elapsed"] < 8.0, outcome["elapsed"]
        error = outcome.get("error")
        assert isinstance(error, SubmitError), error
        assert error.status_code == 503, error.status_code
        assert _MetadataHandler.client_gone.wait(5.0), \
            "child never stopped reading/closed late — the cap is not enforced"
        assert _await_quiescent()
        # Deterministic consumption bound: the server stopped (EPIPE) after
        # roughly the child's 64 KiB cap plus socket buffers — an eager read
        # would have streamed toward the full 4 MiB JSON cap.
        assert _MetadataHandler.written < 1 << 20, _MetadataHandler.written
    finally:
        server.shutdown()
        server.server_close()


def test_child_body_budget_consumes_exactly_cap_plus_one():
    """HARD consumption bound in the CHILD: a 9 MiB drip with maxBytes=1 MiB
    yields EXACTLY cap+1 consumed bytes (the +1 is overflow proof) and the
    child closes immediately — the server sees EPIPE, not the full dribble.
    (The prior design consumed a whole 64 KiB chunk past the cap.)"""
    import base64 as _b64
    _reset(_MetadataHandler, "oversized-chunked", drip_seconds=25.0)
    server, base_url = _start(_MetadataHandler)
    cap = 1 << 20
    try:
        envelope = network._child_perform_get(
            {"url": f"{base_url}/v7/compatibility", "phase": "budget",
             "maxBytes": cap, "remainingSeconds": 20.0, "boundSeconds": 20.0})
        assert envelope.get("truncated") is True
        assert len(_b64.b64decode(envelope["body"])) == cap + 1, \
            "child did not stop at exactly cap+1 consumed bytes"
        assert _MetadataHandler.client_gone.wait(5.0), \
            "child kept the connection open after the cap"
    finally:
        server.shutdown()
        server.server_close()


def test_exactly_cap_sized_json_body_still_parses():
    """Budget = cap+1, not cap: an exactly-cap body must NOT be truncated
    away (the +1 byte is the overflow proof, not a quota steal)."""
    body = b'[{"id": 1}]'
    body = body + b" " * (96 - len(body))  # exactly 96 bytes of valid JSON
    _reset(_MetadataHandler, "exact", body=body)
    server, base_url = _start(_MetadataHandler)
    try:
        rows = network._fetch_metadata_json(
            base_url, "/v7/compatibility", phase="exact-cap",
            cancel_event=None, deadline=None, transaction_seconds=8.0,
            max_bytes=len(body))
        assert rows == [{"id": 1}]
        assert _await_quiescent()
    finally:
        server.shutdown()
        server.server_close()


def test_collector_and_metadata_orders_are_interchangeable(tmp_path, monkeypatch):
    """Both startup orders of the existing collector hold vs normal metadata
    operations: metadata transport holds NO host exclusion and never blocks
    the collector; the collector's hold never blocks metadata correctness."""
    monkeypatch.setenv("ENCODINGDB_HOST_PHASE_DIR", str(tmp_path / "phase"))
    # Order A: collector holds measurement first; metadata still completes.
    _reset(_MetadataHandler, "ok")
    server, base_url = _start(_MetadataHandler)
    try:
        with spool.host_phase_hold("measurement"):
            payload = network._fetch_metadata_json(
                base_url, "/v7/compatibility", phase="order-a",
                cancel_event=None, deadline=None, transaction_seconds=8.0)
            assert payload.get("protocolVersion")
        assert _await_quiescent()
    finally:
        server.shutdown()
        server.server_close()
    # Order B: metadata child active first; the collector must NOT be blocked
    # by it (metadata owns no kernel lock; the child dies on its own bound).
    _reset(_MetadataHandler, "ok")
    server, base_url = _start(_MetadataHandler)
    env = _stalled_env(tmp_path / "b")
    try:
        with mock.patch.dict(network.os.environ, env):
            outcome = _call_bounded(
                lambda: network.check_compatibility(
                    base_url, "client/0.3.0", transaction_seconds=2.0),
                timeout=10.0)
        assert outcome.get("done") and isinstance(outcome.get("error"), SubmitError)
        started = time.monotonic()
        with spool.host_phase_hold("measurement"):
            assert time.monotonic() - started < 2.0, \
                "metadata transport blocked the collector's host exclusion"
        assert _await_quiescent()
    finally:
        server.shutdown()
        server.server_close()


def test_dispatch_shape_is_position_anchored():
    """Ordinary CLI values can never enter the child helper (and block on
    stdin): only the exact `[exe, --metadata-child, <phase>]` shape counts."""
    marker = network.METADATA_CHILD_ARGV
    assert network.metadata_child_invocation_phase(["x", marker, "compatibility"]) \
        == "compatibility"
    for argv in (["x", marker],                       # missing phase
                 ["x", "--base-url", marker],         # value position
                 ["x", "--gui", marker, "compatibility"],  # wrapped shape
                 ["x", marker, "compatibility", "extra"],  # trailing junk
                 ["x", marker, "-bad"],               # flag-shaped phase
                 ["x", "--queue-dir", "d", marker]):
        assert network.metadata_child_invocation_phase(argv) is None, argv


def test_value_position_marker_reaches_argparse_not_the_child():
    """`--base-url <url> --metadata-child` must be an argparse rejection,
    NOT a child dispatch waiting on stdin (the review's blocking hazard)."""
    proc = subprocess.run(
        [network.sys.executable, "-m", "client", "--base-url",
         "http://127.0.0.1:9", network.METADATA_CHILD_ARGV],
        input=b"", capture_output=True, timeout=30,
        cwd=str(Path(network.__file__).resolve().parent.parent))
    assert proc.returncode == 2
    assert b"unrecognized" in proc.stderr, proc.stderr[-300:]


def test_gui_entry_dispatches_raw_child_shape_before_wrapping():
    """The GUI entry checks the RAW OS argv before prepending `--gui`, so a
    child re-executing the GUI executable dispatches without the wrapper's
    rewrite confusing the anchored shape."""
    root = Path(network.__file__).resolve().parent.parent
    entry = root / "client" / "_pyinstaller_gui_entry.py"
    env = dict(os.environ, PYTHONPATH=str(root))
    started = time.monotonic()
    proc = subprocess.run(
        [network.sys.executable, str(entry), network.METADATA_CHILD_ARGV,
         "compatibility"],
        input=b"", capture_output=True, timeout=30, env=env, cwd=str(root))
    assert proc.returncode == 2, proc.stderr[-300:]  # child: empty stdin -> 2
    assert time.monotonic() - started < 20.0
    assert b"unrecognized" not in proc.stderr