"""F1/F2 reliability regressions: continuous SH phase ownership and the
publication-to-measurement quiescence barrier.

F1 (spool.py): a deferred publication releaser must keep its ORIGINAL shared
kernel lock until every owned transport worker is quiescent. The reviewed code
attempted a nonblocking SH→EX conversion instead; on Linux a failed conversion
can discard the descriptor's shared lock, so once every other publisher exits,
a competing collector acquires EX while the deferred worker still performs
I/O. The real-process regressions here use two shared publishers, a deferred
worker, both publisher finish orders and a competing collector. The in-process
coexistence regression catches the same escalation defect deterministically on
any POSIX host: a successful SH→EX escalation blocks the next publisher that
shared ownership was supposed to admit.

F2 (main.py): the collector batch must not start timed encodes while an
earlier publication step in the SAME process still owns live transport I/O.
A pre-run replay that hits its deadline (no user cancellation) retains its
entry and can return with its worker mid-I/O; the barrier must quiesce that
worker (or pause safely with the retained journal/queue) before any encode
window opens, including warmups, mid-batch publication and checkpoint
continuation.
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest import mock
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from client import campaign, main, network, protocol, spool  # noqa: E402


# ---------------------------------------------------------------------------
# F1: real-process two-publisher / deferred-worker / competing-collector
# ---------------------------------------------------------------------------

_F1_CHILD = r"""
import os, sys, threading, time
sys.path.insert(0, {root!r})
from client import spool, network

role, phase_dir, ctl, arg = {args!r}
os.environ["ENCODINGDB_HOST_PHASE_DIR"] = phase_dir

hold = None
if role != "collector":
    # Publishers acquire the SH publication phase; the competing collector
    # must own nothing, or in-process re-entry would make its measurement
    # hold a no-op and mask the exclusion it is meant to probe.
    hold = spool.host_phase_hold("publication")
    acquired = False
    for _ in range(500):
        try:
            hold.__enter__()
            acquired = True
            break
        except spool.SpoolCapacityError:
            time.sleep(0.02)
    if not acquired:
        print("ACQUIRE-FAILED", flush=True)
        sys.exit(2)
print("HELD %.6f" % time.time(), flush=True)

if role == "deferred":
    # The publication caller abandons its transaction when its deadline hits
    # (no user cancellation) while the owned transport worker is still
    # mid-I/O (its real socket timeout bounds the same window): the hold
    # exits NOW and only the deferred releaser keeps the phase until the
    # worker is quiescent.
    stop = threading.Event()
    try:
        network._run_cancellable(
            lambda: time.sleep(2.5), phase="f1-deferred-io",
            cancel_event=stop, deadline=time.monotonic() + 0.3,
            bound_seconds=0.3)
    except Exception:
        pass
    hold.__exit__(None, None, None)
    time.sleep(4.0)
elif role == "publisher":
    time.sleep(float(arg))
    hold.__exit__(None, None, None)
else:
    # Competing collector: EX must stay refused until every publisher AND the
    # deferred owned worker are done; then it must succeed (liveness).
    started, deadline = time.time(), float(arg)
    while time.time() - started < deadline:
        try:
            with spool.host_phase_hold("measurement"):
                print("ACQUIRED %.6f" % time.time(), flush=True)
                sys.exit(0)
        except spool.SpoolCapacityError:
            time.sleep(0.02)
    print("EXCLUDED %.6f" % time.time(), flush=True)
print("CHILD-DONE", flush=True)
"""


def _spawn_child(phase_dir, role, ctl, arg):
    return subprocess.Popen(
        [sys.executable, "-c",
         _F1_CHILD.format(root=str(REPO_ROOT), args=(role, phase_dir, ctl, arg))],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def _read_lines_until(proc, prefix, timeout=25.0):
    """Drain stdout until a line with `prefix`; return (epoch, buffered)."""
    deadline = time.monotonic() + timeout
    buffered = []
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        if line.startswith(prefix):
            return float(line.split()[1]), buffered
        buffered.append(line)
    raise AssertionError(f"no {prefix!r} line from {proc.pid}: {buffered}")


def _run_f1_matrix(tmp_path, publisher_sleep, collector_deadline, expect_acquired):
    """Two SH publishers + deferred worker + competing collector.

    ``publisher_sleep`` selects the publisher finish order relative to the
    deferred worker's 2.5 s I/O window; ``collector_deadline`` bounds how long
    the collector keeps trying. The collector must NEVER acquire EX while any
    publisher holds SH or the deferred worker owns live I/O (worker window
    ends >= held_epoch + 2.5 + sync-join; sync join is 1.0 s and the releaser
    joins exactly at worker end, so the phase frees at ~= held + 2.5).
    """
    phase_dir = str(tmp_path / "phase")
    os.makedirs(phase_dir, exist_ok=True)
    deferred = _spawn_child(phase_dir, "deferred", str(tmp_path / "d.ctl"), "")
    publisher = _spawn_child(phase_dir, "publisher", str(tmp_path / "p.ctl"),
                             str(publisher_sleep))
    children = {"deferred": deferred, "publisher": publisher}
    try:
        held_epochs = {}
        for name, proc in (("deferred", deferred), ("publisher", publisher)):
            held_epochs[name], _ = _read_lines_until(proc, "HELD")
        held = max(held_epochs.values())
        collector = _spawn_child(phase_dir, "collector", str(tmp_path / "c.ctl"),
                                 str(collector_deadline))
        children["collector"] = collector
        # Collect the collector's outcome by absolute epoch, not its own boot.
        started = time.monotonic()
        outcome, buffered = None, []
        while time.monotonic() - started < collector_deadline + 20:
            line = collector.stdout.readline()
            if not line:
                break
            if line.startswith(("ACQUIRED", "EXCLUDED")):
                outcome = (line.split()[0], float(line.split()[1]))
                break
            buffered.append(line)
        assert outcome is not None, f"collector produced no outcome: {buffered}"
        kind, when = outcome
        elapsed = when - held
        if kind == "ACQUIRED":
            # Exclusion invariant: never before the deferred worker's I/O
            # window closed (held + 2.5 s worker sleep; allow a small margin
            # for worker-start jitter after the HELD line).
            assert elapsed >= 2.4, (
                "collector obtained EX while the deferred owned worker still "
                f"owned I/O (acquired at +{elapsed:.2f}s < +2.5s): lossy "
                "SH->EX conversion dropped the shared lock")
        assert (kind == "ACQUIRED") == expect_acquired, (
            f"collector outcome {kind} at +{elapsed:.2f}s, expected "
            f"{'ACQUIRED' if expect_acquired else 'EXCLUDED'}")
    finally:
        for proc in children.values():
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=10)


@pytest.mark.skipif(os.name == "nt", reason="POSIX flock semantics")
def test_f1_two_publishers_collector_excluded_until_deferred_worker_done(tmp_path):
    # Publisher exits at +2.0s, BEFORE the deferred worker's I/O ends at
    # +2.5s (the review's reproduction order): a lossy SH->EX conversion lets
    # the collector slip in the +2.0..+2.5 gap. Liveness: acquisition must
    # still succeed once the worker is quiescent.
    _run_f1_matrix(tmp_path, publisher_sleep=2.0, collector_deadline=4.0,
                   expect_acquired=True)


@pytest.mark.skipif(os.name == "nt", reason="POSIX flock semantics")
def test_f1_collector_excluded_when_publisher_outlives_deferred_worker(tmp_path):
    # Opposite finish order: the plain publisher outlives the deferred
    # worker; the collector must stay excluded for the whole window.
    _run_f1_matrix(tmp_path, publisher_sleep=3.2, collector_deadline=2.2,
                   expect_acquired=False)


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
    failed-conversion path additionally DROPS the shared lock entirely."""
    import fcntl
    monkeypatch.setenv("ENCODINGDB_HOST_PHASE_DIR", str(tmp_path / "phase"))
    monkeypatch.setattr(network, "WORKER_QUIESCE_SYNC_JOIN_SECONDS", 0.1)
    stop = threading.Event()
    stop.set()
    with spool.host_phase_hold("publication"):
        with pytest.raises(network.SubmissionCancelled):
            network._run_cancellable(
                lambda: time.sleep(0.8), phase="f1b-deferred-io",
                cancel_event=stop, deadline=time.monotonic() + 30,
                bound_seconds=30)
    # The hold returned with its owned worker still mid-I/O (deferred release).
    assert network.owned_worker_census() >= 1
    deadline = time.monotonic() + 0.4  # inside the worker's remaining window
    while time.monotonic() < deadline:
        with open(os.path.join(str(tmp_path / "phase"), "phase.lock"), "a+b") as probe:
            with pytest.raises(BlockingIOError):
                fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Shared publication must still coexist with the deferred releaser.
        with spool.host_phase_hold("publication") as acquired:
            assert acquired
        time.sleep(0.05)
    # Once the worker is quiescent the deferred releaser must fully release.
    for _ in range(200):
        try:
            with open(os.path.join(str(tmp_path / "phase"), "phase.lock"), "a+b") as probe:
                fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
            break
        except BlockingIOError:
            time.sleep(0.05)
    else:
        pytest.fail("deferred releaser never released the phase after quiescence")


# ---------------------------------------------------------------------------
# F2: publication-to-measurement quiescence barrier inside run_benchmark_batch
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
    """A real owned transport worker (network._run_cancellable) that stays
    mid-I/O for `seconds`, logging its live window (upload + response read +
    connection close all happen inside that abandoned worker)."""
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
        mock.patch.object(main, "check_compatibility", return_value={}),
        mock.patch.object(main, "fetch_baseline_rows", return_value=[]),
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
    """Deadline WITHOUT user cancellation + delayed transport I/O: the batch
    must quiesce the preceding owned worker before the first timed encode."""
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
    # Segment 2 (continuation, same process, immediately): the deferred
    # releaser still owns the kernel phase, so measurement must refuse to
    # start — safe pause, truthful typed event, no timed work.
    with mock.patch.object(main, "MeasurementBudget", side_effect=new_budget), \
         _batch_patches(fixture, timeline,
                        lambda **kw: pytest.fail("no continuation encode may "
                                                 "run beside live I/O"),
                        extra=[mock.patch.object(main, "_submit_payload_with_spool",
                                                 side_effect=submit),
                               mock.patch.object(main, "BatchRunDashboard",
                                                 _DummyDashboard)]):
        rc2 = main.run_benchmark_batch(
            hardware=hardware, base_url="https://example.invalid", args=args,
            event_sink=events.append, tasks=tasks)
    assert rc2 == 6, events[-5:]
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
    """Checkpoint continuation through the normal CLI entry: segment 1 pauses
    at its time budget; the resumed segment's pre-run replay may not begin
    timed encodes while its own owned worker is still mid-I/O."""
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