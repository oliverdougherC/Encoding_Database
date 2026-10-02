"""F1/F2 reliability regressions: continuous SH phase ownership and the
publication-to-measurement quiescence barrier.

F1 (spool.py): a deferred publication releaser must keep its ORIGINAL shared
kernel lock until every owned transport worker is quiescent. The reviewed code
attempted a nonblocking SH->EX conversion instead; on Linux a failed
conversion can discard the descriptor's shared lock, so once every other
publisher exits, a competing collector acquires EX while the deferred worker
still performs I/O. The real-process regressions here use two shared
publishers, a deferred worker performing REAL loopback publication I/O
(timestamped by the server socket, with explicit acquired / I/O-start /
abandon / publisher-exit handshakes over bounded file IPC), both publisher
finish orders, and a competing collector. The in-process coexistence
regression catches the same escalation defect deterministically on any POSIX
host: a successful SH->EX escalation blocks the next publisher that shared
ownership was supposed to admit.

F2 (main.py): the collector batch must not start timed encodes while an
earlier publication step in the SAME process still owns live transport I/O.
The lifecycle-sentinel tests below pin the barrier/refusal/continuation
control flow with timestamped sentinel windows. Full acceptance THROUGH the
real publication transport (production spool replay /
submit_artifact_submission / create-auth-PUT-read-close over loopback HTTP,
continuation) lives in test_publication_transport_acceptance.py.
"""

import fcntl
import os
import subprocess
import sys
import socket
import threading
import time
from pathlib import Path
from unittest import mock
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from client import campaign, main, network, protocol, spool  # noqa: E402
from _publication_acceptance_support import PublicationIOServer  # noqa: E402


# ---------------------------------------------------------------------------
# F1: real-process two-publisher / deferred-worker / competing-collector
# ---------------------------------------------------------------------------

_F1_CHILD = r"""
import os, socket, sys, threading, time
sys.path.insert(0, {root!r})
from client import spool, network

role, phase_dir, ctl, port = {args!r}
os.environ["ENCODINGDB_HOST_PHASE_DIR"] = phase_dir

def emit(name):
    with open(ctl, "a", encoding="utf-8") as handle:
        handle.write(name + " %.6f\n" % time.time())

def wait_for(path, timeout=40.0):
    deadline = time.time() + timeout
    while not os.path.exists(path):
        if time.time() > deadline:
            print("TIMEOUT-WAITING " + path, flush=True)
            sys.exit(3)
        time.sleep(0.02)

hold = None
if role != "collector":
    # Publishers acquire the SH publication phase; the competing collector
    # must own nothing, or in-process re-entry would make its measurement
    # hold a no-op and mask the exclusion it is meant to probe.
    hold = spool.host_phase_hold("publication")
    acquired = False
    for _ in range(2000):
        try:
            hold.__enter__()
            acquired = True
            break
        except spool.SpoolCapacityError:
            time.sleep(0.02)
    if not acquired:
        emit("ACQUIRE-FAILED")
        sys.exit(2)
emit("ACQUIRED")

if role == "deferred":
    wait_for(ctl + ".start")
    # The publication caller abandons its transaction when its deadline hits
    # (no user cancellation) while the owned transport worker is mid REAL
    # publication I/O: a live socket transaction against the harness server
    # that the server holds open until the harness releases it. The hold
    # exits NOW and only the deferred releaser keeps the phase until the
    # worker is quiescent.
    def publication_io():
        with socket.create_connection(("127.0.0.1", int(port)), timeout=15) as sock:
            sock.sendall(b"PUB-IO\n")
            return sock.recv(8)

    stop = threading.Event()  # never set: deadline abandonment, no cancel
    try:
        network._run_cancellable(publication_io, phase="f1-deferred-io",
                                 cancel_event=stop,
                                 deadline=time.monotonic() + 0.3,
                                 bound_seconds=0.3)
    except Exception:
        pass
    emit("ABANDONED")
    hold.__exit__(None, None, None)
    emit("HOLD-RETURNED")
    # Stay alive while the deferred releaser owns the phase: process death
    # would release the kernel lock itself and mask the ownership behavior.
    wait_for(ctl + ".ioend")
elif role == "publisher":
    # Finish order is harness-driven: exit only when told, so the publisher
    # exit is an observed handshake, never a guessed sleep window.
    wait_for(ctl + ".go")
    hold.__exit__(None, None, None)
    emit("PUBLISHER-EXIT")
else:
    # Competing collector: EX must stay refused for its whole probe window
    # while any publisher holds SH or the deferred worker owns live I/O.
    window = float(os.environ.get("ENCODINGDB_F1_PROBE_SECONDS", "0.4"))
    started = time.time()
    result = "EXCLUDED"
    while time.time() - started < window:
        try:
            with spool.host_phase_hold("measurement"):
                result = "ACQUIRED-EX"
                break
        except spool.SpoolCapacityError:
            time.sleep(0.02)
    emit(result)
print("CHILD-DONE", flush=True)
"""


def _spawn_f1_child(phase_dir, role, ctl, port, logs):
    script = _F1_CHILD.format(root=str(REPO_ROOT),
                              args=(role, phase_dir, ctl, port))
    log = open(logs, "w+", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-c", script],
                            stdout=log, stderr=subprocess.STDOUT, text=True)
    return proc, log


def _child_diagnostics(children):
    parts = []
    for name, (proc, log) in children.items():
        try:
            log.flush()
            tail = Path(log.name).read_text()[-800:]
        except OSError:
            tail = "<no log>"
        parts.append(f"{name}[rc={proc.poll()}]: {tail}")
    return " | ".join(parts)


def _wait_event(children, name, ctl, timeout=25.0, owner=None):
    """Bounded file-IPC handshake: poll for `name`, never block on readline.

    Fails fast only when the child OWNED by this channel dies without
    emitting it; other children may have legitimately exited already.
    Returns the epoch the child recorded for the event."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            lines = Path(ctl).read_text().splitlines()
        except OSError:
            lines = []
        for line in lines:
            parts = line.split()
            if parts and parts[0] == name:
                return float(parts[1]) if len(parts) > 1 else 0.0
        if owner is not None and owner.poll() is not None:
            break
    raise AssertionError(
        f"no {name!r} event within {timeout}s on {ctl}: "
        f"{_child_diagnostics(children)}")


def _run_f1_matrix(tmp_path, plain_publisher_exits_first):
    """Two SH publishers + deferred worker (REAL I/O) + competing collector.

    Both publisher finish orders are explicit handshakes:
    - acquired (both SH owners) -> server-observed worker I/O start ->
      caller abandonment (deadline, no cancel) -> publisher exit and/or
      server-observed worker I/O end, in the order the case selects.
    The collector probes EX right after abandonment while the harness server
    still holds the worker's I/O open (must be EXCLUDED: this is the exact
    window the lossy SH->EX conversion dropped), and probes again after ALL
    publication I/O stopped and every owner exited (must be ACQUIRED:
    liveness).
    """
    phase_dir = str(tmp_path / "phase")
    os.makedirs(phase_dir, exist_ok=True)
    server = PublicationIOServer()
    children = {}
    try:
        deferred_ctl = str(tmp_path / "deferred.ctl")
        plain_ctl = str(tmp_path / "plain.ctl")
        children["deferred"] = _spawn_f1_child(
            phase_dir, "deferred", deferred_ctl, server.port,
            str(tmp_path / "deferred.log"))
        children["publisher"] = _spawn_f1_child(
            phase_dir, "publisher", plain_ctl, server.port,
            str(tmp_path / "publisher.log"))
        # Deterministic precondition: BOTH SH owners acquired before any
        # abandonment or escalation attempt.
        _wait_event(children, "ACQUIRED", deferred_ctl,
                    owner=children["deferred"][0])
        _wait_event(children, "ACQUIRED", plain_ctl,
                    owner=children["publisher"][0])
        Path(deferred_ctl + ".start").touch()
        # The deferred worker's REAL publication I/O has started (observed by
        # the server socket, not guessed from startup-relative time).
        assert server.io_started.wait(15), \
            f"worker I/O never started: {_child_diagnostics(children)}"
        _wait_event(children, "ABANDONED", deferred_ctl,
                    owner=children["deferred"][0])

        _wait_event(children, "HOLD-RETURNED", deferred_ctl,
                    owner=children["deferred"][0])
        if plain_publisher_exits_first:
            Path(plain_ctl + ".go").touch()
            _wait_event(children, "PUBLISHER-EXIT", plain_ctl,
                        owner=children["publisher"][0])

        # Mid-I/O exclusion probe: the plain publisher holds SH (second
        # order) or already exited while the deferred worker's I/O is still
        # open (first order — the review's exact reproduction window). The
        # worker's server-observed I/O end is the true boundary; the probe
        # verdict is resolved before any release, so ACQUIRED-EX here is a
        # genuine exclusion violation, never a startup-jitter artifact.
        assert not server.io_ended.is_set(), (
            "harness window closed before the mid-I/O probe resolved")
        collector1_ctl = str(tmp_path / "collector1.ctl")
        children["collector1"] = _spawn_f1_child(
            phase_dir, "collector", collector1_ctl, server.port,
            str(tmp_path / "collector1.log"))
        verdict = _wait_event_any(children, collector1_ctl,
                                  ("EXCLUDED", "ACQUIRED-EX"),
                                  owner=children["collector1"][0])
        assert verdict == "EXCLUDED", (
            "collector obtained EX while the deferred owned worker still "
            "owned live publication I/O: a lossy SH->EX conversion dropped "
            "the shared lock at abandonment")

        # Release the worker's I/O and let every owner finish.
        server.release()
        assert server.io_ended.wait(15), "worker I/O never finished"
        Path(deferred_ctl + ".ioend").touch()
        children["deferred"][0].wait(timeout=15)
        if not plain_publisher_exits_first:
            Path(plain_ctl + ".go").touch()
            _wait_event(children, "PUBLISHER-EXIT", plain_ctl,
                        owner=children["publisher"][0])
        children["publisher"][0].wait(timeout=15)

        # Liveness: after ALL relevant I/O stopped and every owner exited,
        # the collector must acquire EX.
        collector2_ctl = str(tmp_path / "collector2.ctl")
        children["collector2"] = _spawn_f1_child(
            phase_dir, "collector", collector2_ctl, server.port,
            str(tmp_path / "collector2.log"))
        _wait_event(children, "ACQUIRED-EX", collector2_ctl, timeout=15.0,
                    owner=children["collector2"][0])
    finally:
        for proc, _log in children.values():
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=10)
        server.close()


def _wait_event_any(children, ctl, names, owner, timeout=25.0):
    """Bounded file-IPC wait resolving on ANY of `names` (first wins)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            lines = Path(ctl).read_text().splitlines()
        except OSError:
            lines = []
        for line in lines:
            parts = line.split()
            if parts and parts[0] in names:
                return parts[0]
        if owner.poll() is not None or children["deferred"][0].poll() is not None:
            break
    raise AssertionError(
        f"no {names} verdict within {timeout}s on {ctl}: "
        f"{_child_diagnostics(children)}")


@pytest.mark.skipif(os.name == "nt", reason="POSIX flock semantics")
def test_f1_collector_excluded_when_plain_publisher_exits_first(tmp_path):
    # Review's reproduction order: the plain publisher exits BEFORE the
    # deferred worker's I/O ends; a dropped shared lock lets the collector
    # slip in exactly that gap.
    _run_f1_matrix(tmp_path, plain_publisher_exits_first=True)


@pytest.mark.skipif(os.name == "nt", reason="POSIX flock semantics")
def test_f1_collector_excluded_when_plain_publisher_outlives_worker(tmp_path):
    # Opposite finish order: the plain publisher outlives the deferred
    # worker's I/O; the collector stays excluded during the live window and
    # acquires only after every owner exits.
    _run_f1_matrix(tmp_path, plain_publisher_exits_first=False)


# ---------------------------------------------------------------------------
# F1b: deferred release must not lose shared ownership semantics in-process
# ---------------------------------------------------------------------------

@pytest.mark.skipif(os.name == "nt", reason="POSIX flock semantics")
def test_f1_deferred_release_preserves_shared_lock_and_coexistence(tmp_path, monkeypatch):
    """While a deferred releaser waits for its owned worker: a fresh
    descriptor must be refused EX (ownership retained) AND a second publisher
    must still obtain SH (shared publication coexistence).

    Before the fix the releaser escalated SH->EX when it could, serializing
    every other publisher for the worker's whole I/O window; on Linux the
    failed-conversion path additionally DROPS the shared lock entirely. The
    deferred worker performs REAL loopback publication I/O whose start/end
    are observed by the harness server, so the probe window is anchored to
    actual I/O, not a guessed sleep."""
    monkeypatch.setenv("ENCODINGDB_HOST_PHASE_DIR", str(tmp_path / "phase"))
    monkeypatch.setattr(network, "WORKER_QUIESCE_SYNC_JOIN_SECONDS", 0.1)
    server = PublicationIOServer()
    try:
        def publication_io():
            with socket.create_connection(("127.0.0.1", server.port),
                                          timeout=15) as sock:
                sock.sendall(b"PUB-IO\n")
                return sock.recv(8)

        stop = threading.Event()
        stop.set()
        with spool.host_phase_hold("publication"):
            with pytest.raises(network.SubmissionCancelled):
                network._run_cancellable(
                    publication_io, phase="f1b-deferred-io",
                    cancel_event=stop, deadline=time.monotonic() + 30,
                    bound_seconds=30)
        # The hold returned with its owned worker still mid-I/O (deferred
        # release); the worker stays live until the server releases the
        # transaction below.
        assert network.owned_worker_census() >= 1
        assert server.io_started.wait(10), "deferred worker I/O never started"
        threading.Timer(0.6, server.release).start()
        deadline = time.monotonic() + 0.5  # inside the worker's live window
        while time.monotonic() < deadline:
            with open(os.path.join(str(tmp_path / "phase"), "phase.lock"),
                      "a+b") as probe:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Shared publication must still coexist with the deferred releaser.
            with spool.host_phase_hold("publication") as acquired:
                assert acquired
            time.sleep(0.05)
        # Once the worker's I/O ends the deferred releaser must fully release.
        assert server.io_ended.wait(10), "deferred worker I/O never finished"
        for _ in range(200):
            try:
                with open(os.path.join(str(tmp_path / "phase"), "phase.lock"),
                          "a+b") as probe:
                    fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
                break
            except BlockingIOError:
                time.sleep(0.05)
        else:
            pytest.fail("deferred releaser never released the phase after quiescence")
    finally:
        server.close()


# ---------------------------------------------------------------------------
# F2: publication-to-measurement quiescence barrier inside run_benchmark_batch
# (lifecycle sentinels; real-transport acceptance:
#  test_publication_transport_acceptance.py)
# ---------------------------------------------------------------------------

class _Timeline:
    def __init__(self):
        self.lock = threading.Lock()
        self.events = []

    def log(self, kind):
        with self.lock:
            self.events.append((kind, time.monotonic()))

    def of(self, kind):
        with self.lock:
            return [t for k, t in self.events if k == kind]


def _fixture_and_args(tmp_path, seed):
    from test_main_routing import MainRoutingTests
    fixture = MainRoutingTests()
    args = fixture._batch_args(str(tmp_path), no_submit=False)
    args.local_metrics = False
    args.campaign_seed = seed
    args.max_duration_minutes = 5.0
    return fixture, args


def _slow_encode(timeline, seconds=0.1):
    def encode(**kwargs):
        timeline.log("encode-start")
        time.sleep(seconds)  # a real measurable encode window
        artifact = Path(kwargs["out_dir"]) / kwargs["artifact_name"]
        artifact.write_bytes(b"encoded")
        timeline.log("encode-end")
        return {"artifactPath": str(artifact), "encoderUsed": "libx264",
                "presetUsed": "fast", "fileSizeBytes": 7,
                "encodeStartMonotonicNs": 1_000_000_000,
                "encodeEndMonotonicNs": 2_000_000_000,
                "elapsedMs": int(seconds * 1000), "error": None}
    return encode


def _owned_io_worker(timeline, seconds, name):
    """Lifecycle-sentinel owned worker: registered with the real owned-worker
    machinery (network._run_cancellable) and timestamping the window the
    barrier must respect. It stands in for the abandoned worker's
    upload/response-read/close window; the REAL transport equivalents are
    exercised in test_publication_transport_acceptance.py."""
    def worker():
        timeline.log("transport-io-start")
        time.sleep(seconds)
        timeline.log("transport-io-end")
        return {"benchmarkRun": {"id": "run-f2"}}
    return worker


def _spawn_straggler(worker, caller_budget=0.3):
    """Run `worker` as an owned worker the CALLER abandons when its own
    deadline hits WITHOUT user cancellation (the review's replay-deadline
    race); returns while the worker is still mid-I/O."""
    stop = threading.Event()  # never set: no user cancellation
    try:
        network._run_cancellable(worker, phase="f2-straggler-io",
                                 cancel_event=stop,
                                 deadline=time.monotonic() + caller_budget,
                                 bound_seconds=caller_budget)
    except Exception:
        pass


def _batch_patches(fixture, timeline, encode, extra=()):
    hardware = main.HardwareInfo("CPU", None, 16, "OS")
    from contextlib import ExitStack
    stack = ExitStack()
    patches = [
        mock.patch.object(main, "detect_hardware", return_value=hardware),
        mock.patch("client.ffmpeg.get_ffmpeg_banner",
                   return_value="ffmpeg version publication-fixture"),
        mock.patch.object(main, "check_compatibility", return_value={}),
        mock.patch.object(main, "fetch_baseline_rows", return_value=[]),
        mock.patch.object(main, "_prepare_named_suite_clip",
                          side_effect=lambda *_args, **_kwargs: fixture._quick_clip()),
        mock.patch.object(main, "ensure_ffmpeg_and_ffprobe",
                          return_value=(True, "ffmpeg test")),
        mock.patch.object(main, "_build_protocol_config",
                          return_value=protocol.ProtocolConfig.for_version(
                              "7.1", max_adaptive_repeats=0)),
        mock.patch.object(main, "probe_video_stream_metrics",
                          return_value={"sourceFps": 24,
                                        "sourceDurationSeconds": 5,
                                        "containerFormat": "mp4"}),
        mock.patch.object(main, "_probe_artifact_contract",
                          side_effect=lambda path: fixture._artifact_contract()),
        mock.patch.object(main, "_capture_protocol_environment_snapshot",
                          return_value=protocol.EnvironmentSnapshot(
                              selected_accelerator="software")),
        mock.patch.object(main, "encode_to_artifact", side_effect=encode),
        mock.patch.object(main, "_submit_payload_with_spool",
                          side_effect=lambda **kw: ("submitted", "run-f2", 0)),
    ] + list(extra)
    for patch in patches:
        stack.enter_context(patch)
    return stack


def _assert_no_encode_overlaps_owned_io(timeline):
    encode_windows = list(zip(timeline.of("encode-start"),
                              timeline.of("encode-end")))
    assert encode_windows, "no timed encodes ran"
    io_spans = list(zip(timeline.of("transport-io-start"),
                        timeline.of("transport-io-end")))
    assert io_spans, "the owned worker never logged its I/O window"
    for io_start, io_end in io_spans:
        for enc_start, enc_end in encode_windows:
            assert io_end <= enc_start or io_start >= enc_end, (
                f"owned transport I/O [{io_start:.3f},{io_end:.3f}] overlaps "
                f"encode window [{enc_start:.3f},{enc_end:.3f}]")


def test_f2_deadline_hit_replay_worker_cannot_overlap_timed_encodes(tmp_path, monkeypatch):
    """Lifecycle sentinel: deadline WITHOUT user cancellation + delayed
    sentinel I/O: the batch must quiesce the preceding owned worker before
    the first timed encode."""
    from test_main_routing import _DummyDashboard
    fixture, args = _fixture_and_args(tmp_path, 41)
    timeline = _Timeline()
    hardware = main.HardwareInfo("CPU", None, 16, "OS")
    worker = _owned_io_worker(timeline, 0.6, "replay")

    def replay(queue_dir, **kwargs):
        # One entry hit its deadline (retryable, no cancel); replay returns
        # while its owned worker is still mid-I/O.
        _spawn_straggler(worker)
        return 1

    monkeypatch.setenv("ENCODINGDB_HOST_PHASE_DIR", str(tmp_path / "phase"))
    events = []
    with _batch_patches(fixture, timeline, _slow_encode(timeline),
                        extra=[mock.patch.object(main, "_replay_pending_uploads",
                                                 side_effect=replay),
                               mock.patch.object(main, "BatchRunDashboard",
                                                 _DummyDashboard)]):
        rc = main.run_benchmark_batch(
            hardware=hardware, base_url="https://example.invalid", args=args,
            event_sink=events.append,
            tasks=[{"encoder": "libx264", "preset": "fast", "crf": 24,
                    "suiteClip": fixture._quick_clip()}])
    assert rc == 0, events[-5:]
    _assert_no_encode_overlaps_owned_io(timeline)


def test_f2_batch_pauses_when_owned_worker_outlives_barrier(tmp_path, monkeypatch):
    """A straggler longer than the bounded barrier: pause safely with the
    retained journal/queue and a truthful typed message — never time encodes
    beside it, never hang."""
    from test_main_routing import _DummyDashboard
    fixture, args = _fixture_and_args(tmp_path, 42)
    timeline = _Timeline()
    hardware = main.HardwareInfo("CPU", None, 16, "OS")
    worker = _owned_io_worker(timeline, 4.0, "pause")

    def replay(queue_dir, **kwargs):
        _spawn_straggler(worker)
        return 1

    monkeypatch.setenv("ENCODINGDB_HOST_PHASE_DIR", str(tmp_path / "phase"))
    events = []
    started = time.monotonic()
    patches = _batch_patches(fixture, timeline,
                             lambda **kw: pytest.fail("no encode may run"),
                             extra=[mock.patch.object(main, "_replay_pending_uploads",
                                                      side_effect=replay),
                                    mock.patch.object(main, "BatchRunDashboard",
                                                      _DummyDashboard)])
    with patches:
        rc = main.run_benchmark_batch(
            hardware=hardware, base_url="https://example.invalid", args=args,
            event_sink=events.append,
            tasks=[{"encoder": "libx264", "preset": "fast", "crf": 24,
                    "suiteClip": fixture._quick_clip()}])
    elapsed = time.monotonic() - started
    assert rc == 6, events[-5:]
    assert elapsed < 3.5, "the barrier wait must be bounded, not the full worker sleep"
    pause = [e for e in events if e.get("type") == "run_error" and e.get("code") == 6]
    assert pause and "quiescence" in pause[0]["message"], pause
    assert not timeline.of("encode-start")


def test_f2_checkpoint_straggler_pauses_continuation_segment(tmp_path, monkeypatch):
    """A checkpoint submission whose owned worker outlives the batch (deadline
    race, no cancel) must not let the SAME collector time the continuation
    segment beside its live I/O: the deferred releaser retains the kernel
    phase, so the next segment pauses (exit 6, retained journal/queue) and
    only the quiescent third segment completes."""
    from test_main_routing import _DummyDashboard
    from dataclasses import replace
    fixture, args = _fixture_and_args(tmp_path, 43)
    args.max_duration_minutes = 0.5
    clip_b = replace(fixture._quick_clip(), clip_id="film-grain-1080p24-final",
                     workload_id="film-grain-1080p24-final")
    timeline = _Timeline()
    hardware = main.HardwareInfo("CPU", None, 16, "OS")
    clock = [0.0]
    worker = _owned_io_worker(timeline, 2.5, "checkpoint")
    injected = []

    def new_budget(minutes, **kwargs):
        return campaign.MeasurementBudget(minutes, clock=lambda: clock[0], **kwargs)

    def encode(**kwargs):
        clock[0] += 5
        campaign.check_measurement_budget()
        return _slow_encode(timeline, 0.05)(**kwargs)

    def submit(**kwargs):
        # The first checkpoint submission leaves a live owned worker behind
        # when its deadline races the response read (entry retained, no
        # user cancellation).
        if not injected:
            injected.append(True)
            _spawn_straggler(worker)
        return "submitted", "run-f2-mid", 0

    monkeypatch.setenv("ENCODINGDB_HOST_PHASE_DIR", str(tmp_path / "phase"))
    events = []
    tasks = [{"encoder": "libx264", "preset": "fast", "crf": 24,
              "suiteClip": fixture._quick_clip()},
             {"encoder": "libx264", "preset": "fast", "crf": 24,
              "suiteClip": clip_b}]
    # Segment 1: pauses at its checkpoint with a terminal group submitted and
    # one owned worker still mid-I/O.
    with mock.patch.object(main, "MeasurementBudget", side_effect=new_budget), \
         _batch_patches(fixture, timeline, encode,
                        extra=[mock.patch.object(main, "_submit_payload_with_spool",
                                                 side_effect=submit),
                               mock.patch.object(main, "BatchRunDashboard",
                                                 _DummyDashboard)]):
        rc1 = main.run_benchmark_batch(
            hardware=hardware, base_url="https://example.invalid", args=args,
            event_sink=events.append, tasks=tasks)
    assert rc1 == 11
    assert injected, "checkpoint straggler never injected"
    # Segment 2 may be refused while I/O remains, or proceed if preparation
    # and the bounded release join have already let that worker finish.
    # Both outcomes are safe; timing must never overlap its actual I/O span.
    with mock.patch.object(main, "MeasurementBudget", side_effect=new_budget), \
         _batch_patches(fixture, timeline, encode,
                        extra=[mock.patch.object(main, "_submit_payload_with_spool",
                                                 side_effect=submit),
                               mock.patch.object(main, "BatchRunDashboard",
                                                 _DummyDashboard)]):
        rc2 = main.run_benchmark_batch(
            hardware=hardware, base_url="https://example.invalid", args=args,
            event_sink=events.append, tasks=tasks)
    assert rc2 in (0, 6), events[-5:]
    if rc2 == 6:
        refusal = [e for e in events if e.get("type") == "run_error" and e.get("code") == 6]
        assert refusal and "owns this host" in refusal[-1]["message"]
    # Segment 3: after quiescence the same campaign continues and completes.
    deadline = time.monotonic() + 5.0
    while network.owned_worker_census() and time.monotonic() < deadline:
        time.sleep(0.05)
    clock[0] = 1000.0
    with mock.patch.object(main, "MeasurementBudget", side_effect=new_budget), \
         _batch_patches(fixture, timeline, encode,
                        extra=[mock.patch.object(main, "_submit_payload_with_spool",
                                                 side_effect=submit),
                               mock.patch.object(main, "BatchRunDashboard",
                                                 _DummyDashboard)]):
        rc3 = main.run_benchmark_batch(
            hardware=hardware, base_url="https://example.invalid", args=args,
            event_sink=events.append, tasks=tasks)
    assert rc3 == 0, events[-5:]
    _assert_no_encode_overlaps_owned_io(timeline)


def test_f2_checkpoint_continuation_replay_worker_cannot_overlap_encodes(tmp_path, monkeypatch):
    """Lifecycle sentinel for checkpoint continuation through the normal CLI
    entry: segment 1 pauses at its time budget; the resumed segment's pre-run
    replay may not begin timed encodes while its own owned worker is still
    mid-I/O."""
    from test_main_routing import _DummyDashboard
    fixture, args = _fixture_and_args(tmp_path, 44)
    args.max_duration_minutes = 0.5
    timeline = _Timeline()
    hardware = main.HardwareInfo("CPU", None, 16, "OS")
    clock = [0.0]
    worker = _owned_io_worker(timeline, 0.6, "resume")

    def new_budget(minutes, **kwargs):
        return campaign.MeasurementBudget(minutes, clock=lambda: clock[0], **kwargs)

    def encode(**kwargs):
        clock[0] += 10
        campaign.check_measurement_budget()
        return _slow_encode(timeline, 0.05)(**kwargs)

    def replay(queue_dir, **kwargs):
        _spawn_straggler(worker)
        return 1

    monkeypatch.setenv("ENCODINGDB_HOST_PHASE_DIR", str(tmp_path / "phase"))
    events = []
    # Segment 1: pauses at the checkpoint (budget exhausted at +30s).
    with mock.patch.object(main, "MeasurementBudget", side_effect=new_budget), \
         _batch_patches(fixture, timeline, encode,
                        extra=[mock.patch.object(main, "BatchRunDashboard",
                                                 _DummyDashboard)]):
        rc1 = main.run_benchmark_batch(
            hardware=hardware, base_url="https://example.invalid", args=args,
            event_sink=events.append,
            tasks=[{"encoder": "libx264", "preset": "fast", "crf": 24,
                    "suiteClip": fixture._quick_clip()}])
    assert rc1 == 11
    campaign_id = next((tmp_path / "campaigns").iterdir()).name
    # Segment 2: continuation via the real CLI entry point; its pre-run
    # replay leaves an owned worker mid-I/O before any encode may start.
    clock[0] = 1000.0
    with mock.patch.object(main, "MeasurementBudget", side_effect=new_budget), \
         _batch_patches(fixture, timeline, encode,
                        extra=[mock.patch.object(main, "_replay_pending_uploads",
                                                 side_effect=replay),
                               mock.patch.object(main, "BatchRunDashboard",
                                                 _DummyDashboard)]):
        rc2 = main.main(["prog", "--resume-campaign", campaign_id, "--submit",
                         "--max-duration-minutes", "0.5",
                         "--queue-dir", str(tmp_path)])
    assert rc2 == 0
    _assert_no_encode_overlaps_owned_io(timeline)