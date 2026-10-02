"""Shared fixtures for publication acceptance regressions (F1/F2).

Nothing here replaces production transport: the HTTP backend answers with
faithful v7 bundles while the client keeps executing the real
spool.replay / submit_artifact_submission / _run_cancellable /
_read_response_body code paths. The only injected timing is server-side
transport delay (delayed/dripped responses) and a bounded delay around the
REAL Requests response close when it runs on the body-watcher thread — the
same controlled-close technique the maintained response-close regression uses.
"""

import hashlib
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from client.artifacts import build_artifact_submission_payload, build_payload_hash


class Timeline:
    """Monotonic event log: encode windows as start/end events, owned
    transport activity as explicit (kind, start, end) intervals."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.events = []
        self.intervals = []

    def log(self, kind: str) -> None:
        with self.lock:
            self.events.append((kind, time.monotonic()))

    def interval(self, kind: str, start: float, end: float) -> None:
        with self.lock:
            self.intervals.append((kind, start, end))

    def of(self, kind: str):
        with self.lock:
            return [t for k, t in self.events if k == kind]

    def spans(self, kind: str):
        if kind == "encode":
            starts = self.of("encode-start")
            ends = self.of("encode-end")
            assert len(starts) == len(ends), (
                f"unbalanced encode interval: {len(starts)} starts vs "
                f"{len(ends)} ends")
            return list(zip(starts, ends))
        with self.lock:
            return [(start, end) for k, start, end in self.intervals if k == kind]

    def encode_windows(self):
        return self.spans("encode")

    def latest_end(self):
        with self.lock:
            ends = [t for k, t in self.events if k.endswith("-end")]
            ends.extend(end for _k, _start, end in self.intervals)
        return max(ends) if ends else 0.0


def assert_no_encode_overlap(timeline: Timeline) -> None:
    """No encode interval may overlap ANY recorded owned transport interval."""
    encode_windows = timeline.encode_windows()
    assert encode_windows, "no timed encodes ran"
    for kind in ("upload", "response-read", "close"):
        for start, end in timeline.spans(kind):
            for enc_start, enc_end in encode_windows:
                assert end <= enc_start or start >= enc_end, (
                    f"owned {kind} I/O [{start:.3f},{end:.3f}] overlaps "
                    f"encode window [{enc_start:.3f},{enc_end:.3f}]")


class PublicationIOServer:
    """Real TCP server for one controlled publication I/O window.

    A client connects, sends a request line (I/O start is recorded from the
    kernel-accepted socket, not a client guess) and blocks in the transaction
    until the harness releases the window. The I/O is a real socket
    transaction on the caller's owned transport worker."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.io_started = threading.Event()
        self.io_started_at: Optional[float] = None
        self.io_ended = threading.Event()
        self.io_ended_at: Optional[float] = None
        self._release = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                self.sock.settimeout(0.2)
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                conn.settimeout(60)
                request = conn.recv(64)
                if request:
                    self.io_started_at = time.time()
                    self.io_started.set()
                    released = self._release.wait(60)
                    if released:
                        conn.sendall(b"OK\n")
                    self.io_ended_at = time.time()
                    self.io_ended.set()
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def release(self) -> None:
        self._release.set()

    def close(self) -> None:
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass
        self._thread.join(2)


def artifact_bytes(seed: bytes = b"publication-acceptance-artifact") -> bytes:
    return (seed * 97)[:1024]


def build_submission_payload(*, artifact_path: Path, campaign_id: str,
                             recipe_id: str, repetition_index: int) -> Dict[str, Any]:
    """Faithful authoritative-artifact submission payload over REAL bytes."""
    data = artifact_path.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    run_create: Dict[str, Any] = {
        "benchmarkProtocol": {
            "protocolVersion": "7.1",
            "sourceSuiteVersion": "encodingdb-test-suite-v1",
            "minimumClientVersion": "client/0.3.0",
            "canonicalRecipeRules": {"artifactUploadRequired": True},
            "canonicalOutputRules": {"singleVideoStream": True, "noAudio": True},
            "metricWorkerVersion": "authoritative-analysis/v2",
        },
        "testClip": {
            "suiteId": "encodingdb-test-suite",
            "suiteVersion": "encodingdb-test-suite-v1",
            "clipKey": "athletic-action-1080p24-final",
            "sha256": "a" * 64,
            "workloadId": "athletic-action-1080p24-final",
        },
        "recipe": {
            "fingerprint": hashlib.sha256(recipe_id.encode()).hexdigest(),
            "canonicalJson": {"codecFamily": "h264"},
            "identity": {
                "codecFamily": "h264",
                "encoderImplementation": "libx264",
                "pixelFormat": "yuv420p",
                "bitDepth": 8,
                "chromaSubsampling": "4:2:0",
                "requestedRateControl": {"mode": "crf", "qualityValue": 24},
                "effectiveRateControl": {"mode": "crf", "qualityValue": 24},
            },
        },
        "environment": {
            "fingerprint": "c" * 64,
            "canonicalJson": {"cpuModel": "CPU"},
            "identity": {
                "cpuModel": "CPU",
                "cpuArchitecture": "arm64",
                "physicalMemoryBytes": 17179869184,
                "ffmpegBuildFingerprint": "ffmpeg-build",
                "ffmpegVersion": "ffmpeg version n7",
                "clientVersion": "client/0.3.8",
                "osName": "testos",
                "osVersion": "1.0",
            },
        },
        "workloadId": "athletic-action-1080p24-final",
        "expectedMetricModelId": "vmaf-v1-sdr-1080p",
        "inputHash": "d" * 64,
        "campaignId": campaign_id,
        "repetitionGroupId": f"{campaign_id}:{recipe_id}",
        "repetitionIndex": repetition_index,
        "encodeWallTimeMs": 100,
        "encodeFps": 120.0,
        "sourceFps": 24.0,
        "realTimeRatio": 5.0,
        "sourceFrameCount": 120,
        "encodedFrameCount": 120,
        "telemetry": {"cpuUtilAvg": 15.0},
        "telemetrySources": {"hardwareMonitor": ["cpuUtilAvg"]},
        "telemetryMissing": [],
        "preRunEnvironmentCheck": {"snapshot": {"background_cpu_pct": 5.0}},
        "ffmpegProgressTelemetry": {"elapsedMs": 100, "frameCount": 120},
        "clientQualityDebug": {"vmafMean": 0.1, "vmafP5": 0.05},
        "artifact": {
            "role": "ENCODED",
            "sha256": sha256,
            "byteSize": len(data),
            "mediaContainer": "mp4",
        },
    }
    run_create["payloadHash"] = build_payload_hash(run_create)
    return build_artifact_submission_payload(
        artifact_path=str(artifact_path), media_container="mp4",
        run_create=run_create)


class ArtifactBackend:
    """Loopback v7 artifact backend with faithful bundles and transport delay.

    Bundles carry the identities the acceptance brief requires:
    benchmarkRun.id/payloadHash/status and artifact.id/benchmarkRunId/role/
    sha256/byteSize/storageState. `analyses` stays a DISTINCT confirmation: an
    accepted upload only moves storageState to RETAINED with an empty analyses
    list — upload confirmation is never analysis acceptance.

    Delay is transport-only: `drip_body(run_id, hold)` makes the server accept
    the FULL real upload body, send 200 headers, then drip the JSON response
    across `hold` seconds, so the real production reader races its deadline
    and the owned body-watcher performs the connection close.
    """

    def __init__(self) -> None:
        self.runs: Dict[str, Dict[str, Any]] = {}
        self.run_order = []
        self.upload_attempts: Dict[str, int] = {}
        self.body_complete_at: Dict[str, float] = {}
        self.drip_holds: Dict[str, float] = {}
        self._first_create_hold = 0.0
        self._first_upload_hold = 0.0
        self._create_count = 0
        self._upload_count = 0
        self.server_seen = threading.Condition()
        self.request_log: list = []

        backend = self  # closure target for the nested handler
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _json_body(self) -> dict:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                return json.loads(raw)

            def _bundle(self, run: Dict[str, Any]) -> Dict[str, Any]:
                uploaded = bool(run.get("uploaded"))
                return {
                    "benchmarkRun": {
                        "id": run["id"],
                        "payloadHash": run["payloadHash"],
                        "status": "ACCEPTED" if uploaded else "PENDING",
                        "statusReason": None,
                        "workloadId": run["workloadId"],
                    },
                    "artifact": {
                        "id": f"artifact-{run['id']}",
                        "benchmarkRunId": run["id"],
                        "role": "ENCODED",
                        "sha256": run["sha256"],
                        "byteSize": run["byteSize"],
                        "storageState": "RETAINED" if uploaded else "PENDING",
                        "stateReason": None,
                        "mediaContainer": "mp4",
                    },
                    "analyses": [],
                }

            def _reply(self, status: int, payload: Dict[str, Any]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                backend.request_log.append((self.command, self.path, status))
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def _drip_reply(self, status: int, payload: Dict[str, Any],
                            hold: float) -> None:
                # Transport delay: headers first, then a drip the production
                # reader must follow (its deadline/watcher close wins).
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.flush()
                try:
                    step = max(0.1, hold / 8.0)
                    elapsed = 0.0
                    sent = 0
                    while elapsed < hold:
                        time.sleep(step)
                        elapsed += step
                        part = body[sent:sent + max(1, len(body) // 8)]
                        sent += len(part)
                        self.wfile.write(part)
                        self.wfile.flush()
                    if sent < len(body):
                        self.wfile.write(body[sent:])
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass  # the owned watcher closed the connection on deadline

            def do_POST(self):  # noqa: N802
                if self.path == "/v7/benchmark-runs":
                    body = self._json_body()
                    payload_hash = str(body["payloadHash"])
                    with backend.server_seen:
                        run = backend.runs.get(payload_hash)
                        created = run is None
                        if created:
                            run = {
                                "id": f"run-{len(backend.runs) + 1}",
                                "payloadHash": payload_hash,
                                "sha256": body["artifact"]["sha256"],
                                "byteSize": int(body["artifact"]["byteSize"]),
                                "workloadId": body["workloadId"],
                                "uploaded": False,
                            }
                            backend.runs[payload_hash] = run
                            backend.run_order.append(run["id"])
                        bundle = self._bundle(run)
                        backend.server_seen.notify_all()
                        backend._create_count += 1
                        first_create = backend._create_count == 1
                    hold = backend._first_create_hold if first_create else 0.0
                    if hold > 0:
                        self._drip_reply(201 if created else 200, bundle, hold)
                        return
                    self._reply(201 if created else 200, bundle)
                    return
                if self.path.endswith("/upload-authorizations"):
                    run_id = self.path.split("/")[3]
                    run = next((r for r in backend.runs.values()
                                if r["id"] == run_id), None)
                    if run is None:
                        self._reply(404, {"error": "unknown run"})
                        return
                    if run.get("uploaded"):
                        self._reply(200, {"uploadRequired": False,
                                          **self._bundle(run)})
                        return
                    self._reply(200, {"uploadRequired": True, "token": run_id})
                    return
                self._reply(404, {"error": "not found"})

            def do_PUT(self):  # noqa: N802
                if not self.path.startswith("/v7/artifact-uploads/"):
                    self._reply(404, {"error": "not found"})
                    return
                run_id = self.path.rsplit("/", 1)[-1]
                run = next((r for r in backend.runs.values()
                            if r["id"] == run_id), None)
                if run is None:
                    self._reply(404, {"error": "unknown upload"})
                    return
                length = int(self.headers.get("Content-Length", "0"))
                uploaded = self.rfile.read(length) if length else b""
                if hashlib.sha256(uploaded).hexdigest() != run["sha256"] \
                        or len(uploaded) != run["byteSize"]:
                    self._reply(400, {"error": "artifact bytes mismatch"})
                    return
                backend.upload_attempts[run_id] = \
                    backend.upload_attempts.get(run_id, 0) + 1
                backend.body_complete_at[run_id] = time.monotonic()
                run["uploaded"] = True
                backend._upload_count += 1
                first_upload = backend._upload_count == 1
                hold = backend.drip_holds.get(run_id, 0.0)
                if first_upload and backend._first_upload_hold > 0:
                    hold = backend._first_upload_hold
                if hold > 0:
                    # Transport delay AFTER the real body landed.
                    self._drip_reply(200, self._bundle(run), hold)
                    return
                self._reply(200, self._bundle(run))

            def log_message(self, format, *args):  # noqa: A002
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._serving = threading.Thread(target=self._server.serve_forever,
                                         daemon=True)
        self._serving.start()
        self.base_url = f"http://127.0.0.1:{self._server.server_port}"

    def drip_first_create(self, hold_seconds: float) -> None:
        self._first_create_hold = hold_seconds

    def drip_first_upload(self, hold_seconds: float) -> None:
        self._first_upload_hold = hold_seconds

    def wait_for_run(self, index: int, timeout: float = 10.0) -> str:
        """Wait until the (index+1)-th distinct run was created (idempotent)."""
        with self.server_seen:
            deadline = time.monotonic() + timeout
            while len(self.run_order) <= index:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self.server_seen.wait(remaining):
                    raise AssertionError(
                        f"run #{index + 1} never created; seen {self.run_order}")
            return self.run_order[index]

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._serving.join(2)


WATCHER_THREAD_NAME = "encodingdb-error-body-watch"


def instrument_transport(monkeypatch, timeline: Timeline, *,
                         watcher_close_delay: float = 0.0) -> None:
    """Record REAL production transport activity on the timeline.

    - upload: wraps artifacts._UploadBody.__iter__ and delegates to the real
      streaming body generator (production chunking/guards still run).
    - response-read: wraps artifacts._read_json_bounded around the real
      bounded reader.
    - close: wraps requests.models.Response.close around the real close. When
      `watcher_close_delay` > 0, ONLY the close performed by the production
      body-watcher thread is delayed — exactly the unowned-close lifecycle the
      review proved, now observed at batch level through the real reader.
    """
    from client import artifacts

    real_read = artifacts._read_json_bounded

    def read_wrapper(*args, **kwargs):
        start = time.monotonic()
        try:
            return real_read(*args, **kwargs)
        finally:
            timeline.interval("response-read", start, time.monotonic())

    real_iter = artifacts._UploadBody.__iter__

    def iter_wrapper(self):
        start = time.monotonic()
        inner = real_iter(self)
        try:
            while True:
                try:
                    chunk = next(inner)
                except StopIteration:
                    break
                yield chunk
        finally:
            timeline.interval("upload", start, time.monotonic())

    real_close = requests.models.Response.close

    def close_wrapper(self):
        delayed = (watcher_close_delay > 0
                   and threading.current_thread().name == WATCHER_THREAD_NAME)
        start = time.monotonic()
        try:
            if delayed:
                time.sleep(watcher_close_delay)
            return real_close(self)
        finally:
            timeline.interval("close", start, time.monotonic())

    monkeypatch.setattr(artifacts, "_read_json_bounded", read_wrapper)
    monkeypatch.setattr(artifacts._UploadBody, "__iter__", iter_wrapper)
    monkeypatch.setattr(requests.models.Response, "close", close_wrapper)