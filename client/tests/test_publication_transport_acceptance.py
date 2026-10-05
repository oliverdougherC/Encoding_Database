"""F2 publication-transport acceptance: REAL loopback HTTP through the
production spool replay / artifact create-auth-PUT-read-close chain and the
batch/main continuation entry points.

The backend answers with faithful v7 bundles (benchmarkRun.id/payloadHash/
status; artifact.id/benchmarkRunId/role/sha256/byteSize/storageState;
analyses stay DISTINCT from upload confirmation). Transport delay is
server-side: a dripped response body makes the real production reader race a
DEADLINE without operator cancellation, and the REAL Requests close is
delayed only while it runs on the production body-watcher thread. Encode
intervals are narrow deterministic sentinels (encode intervals may be
fixtures; the publication transport/queue is production code). The barrier,
ownership, retention and continuation semantics under test are all imported
production behavior — nothing here replaces replay or submit with a sleeping
mock.
"""

import json
import os
import time
from dataclasses import replace
from pathlib import Path
from unittest import mock
import pytest

from client import campaign, main, network, protocol, spool
from _publication_acceptance_support import (
    ArtifactBackend, Timeline, artifact_bytes, assert_no_encode_overlap,
    build_submission_payload, instrument_transport)


# ---------------------------------------------------------------------------
# Shared scaffolding
# ---------------------------------------------------------------------------

def _fixture_and_args(tmp_path, seed):
    from test_main_routing import MainRoutingTests
    fixture = MainRoutingTests()
    args = fixture._batch_args(str(tmp_path), no_submit=False)
    args.local_metrics = False
    args.campaign_seed = seed
    args.max_duration_minutes = 0.5
    return fixture, args


def _acceptance_encode(timeline, clock, seconds=0.05):
    """Narrow deterministic encode sentinel with REAL per-call artifact bytes.

    Timestamps the measurable encode window, advances the fake measurement
    clock, and writes distinct bytes so every attempt stages a distinct
    managed artifact (fixture allowed for ENCODE intervals only; publication
    transport stays production)."""
    state = {"n": 0}

    def encode(**kwargs):
        state["n"] += 1
        clock[0] += 5
        campaign.check_measurement_budget()
        timeline.log("encode-start")
        time.sleep(seconds)
        artifact = Path(kwargs["out_dir"]) / kwargs["artifact_name"]
        artifact.write_bytes(b"artifact-" + state["n"].to_bytes(2, "big")
                             + b"-payload")
        timeline.log("encode-end")
        return {"artifactPath": str(artifact), "encoderUsed": "libx264",
                "presetUsed": "fast", "fileSizeBytes": artifact.stat().st_size,
                "encodeStartMonotonicNs": 1_000_000_000,
                "encodeEndMonotonicNs": 2_000_000_000,
                "elapsedMs": int(seconds * 1000), "error": None}
    return encode


def _acceptance_patches(fixture, encode, extra=()):
    """Batch patches for acceptance runs: metadata preflight/baseline use a
    faithful cached/fast response; the publication path (replay, spool,
    submit, transport) is NEVER mocked."""
    from contextlib import ExitStack
    from test_main_routing import _DummyDashboard
    hardware = main.HardwareInfo("CPU", None, 16, "OS")
    stack = ExitStack()
    patches = [
        mock.patch.object(main, "detect_hardware", return_value=hardware),
        mock.patch("client.ffmpeg.get_ffmpeg_banner",
                   return_value="ffmpeg version publication-fixture"),
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
        mock.patch.object(main, "physical_source_id",
                          return_value="installation-" + "a" * 64),
        mock.patch("client.identity.runtime_identity", return_value={
            "runtimeDependencies": [],
            "ffmpeg": {"sha256": "f" * 64, "architectures": ["arm64"]},
            "ffprobe": {"sha256": "e" * 64, "architectures": ["arm64"]},
            "clientExecutionArchitecture": "arm64"}),
        mock.patch.object(main, "selected_device",
                          return_value={"deviceId": "cpu"}),
        mock.patch.object(main, "BatchRunDashboard", _DummyDashboard),
    ] + list(extra)
    for patch in patches:
        stack.enter_context(patch)
    return stack


def _drain_workers(timeout=20.0):
    deadline = time.monotonic() + timeout
    while network.owned_worker_census() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert network.owned_worker_census() == 0, "owned workers never quiesced"


def _pending(queue_dir):
    return {name for name in os.listdir(queue_dir)
            if name.endswith(".json")
            and os.path.isfile(os.path.join(queue_dir, name))}


def _retained_entry(queue_dir, payload):
    local_hash = spool.local_hash_for_payload(payload)
    entry = spool.load_spool_entry(os.path.join(queue_dir, f"{local_hash}.json"))
    return local_hash, entry


def _managed_artifact_bytes(queue_dir, payload):
    path = str(payload.get("artifactPath") or "")
    return Path(path).read_bytes() if path and os.path.exists(path) else None


# ---------------------------------------------------------------------------
# Acceptance 1: pre-run replay deadline (no cancel) + delayed transport +
# delayed watcher close — real spool replay before production encodes.
# ---------------------------------------------------------------------------

def test_f2_real_replay_deadline_straggler_never_overlaps_encodes(tmp_path, monkeypatch):
    """Production `_replay_pending_uploads` replays a durable entry through
    real create-auth-PUT transport against loopback HTTP. The create response
    is dripped, so the deadline (WITHOUT user cancellation) aborts the real
    bounded reader while the owned body-watcher is still closing the
    connection. The batch barrier must quiesce that close before ANY encode
    window opens; the retained entry keeps its identity/bytes/deadline; a
    later production retry uploads it exactly once and retires the bytes."""
    fixture, args = _fixture_and_args(tmp_path, 61)
    backend = ArtifactBackend()
    timeline = Timeline()
    clock = [0.0]
    try:
        monkeypatch.setenv("ENCODINGDB_HOST_PHASE_DIR", str(tmp_path / "phase"))
        # A near-expiry publication deadline (production reads this at call
        # time); the drip outlasts it so the real reader hits its deadline.
        monkeypatch.setattr(main, "ACTIVE_PUBLICATION_DEADLINE_SECONDS", 1.0)
        instrument_transport(monkeypatch, timeline, watcher_close_delay=1.2)
        backend.drip_first_create(2.2)

        artifact = tmp_path / "queued-artifact.mp4"
        artifact.write_bytes(artifact_bytes())
        payload = build_submission_payload(
            artifact_path=artifact, campaign_id="campaign-real",
            recipe_id="recipe-queued", repetition_index=1)
        spool.spool_payload(str(tmp_path), payload)
        local_hash, entry = _retained_entry(str(tmp_path), payload)
        deadline_before = entry["retryDeadlineAt"]
        queued_bytes = _managed_artifact_bytes(
            str(tmp_path), entry["payload"])
        assert queued_bytes == artifact_bytes()

        events = []
        replay_started_epoch = time.time()
        with _acceptance_patches(fixture, _acceptance_encode(timeline, clock)):
            rc = main.run_benchmark_batch(
                hardware=main.HardwareInfo("CPU", None, 16, "OS"),
                base_url=backend.base_url, args=args, event_sink=events.append,
                tasks=[{"encoder": "libx264", "preset": "fast", "crf": 24,
                        "suiteClip": fixture._quick_clip()}])
        # The replayed entry is retained (retryable deadline, no cancel), so
        # the batch honestly reports queued work; encodes still completed.
        assert rc in (0, 10), events[-5:]

        # Deadline forced WITHOUT operator cancellation: the real bounded
        # reader ran and the real connection close ran.
        assert timeline.spans("response-read"), "real reader never ran"
        assert timeline.spans("close"), "real connection close never ran"
        run_id = backend.wait_for_run(0)
        run = next(r for r in backend.runs.values() if r["id"] == run_id)
        assert run["uploaded"] is False  # create response was never parsed

        # Safe pause of the replayed payload: entry + stable IDs + bytes +
        # retry deadline survive; nothing was double-submitted.
        _hash2, retained = _retained_entry(str(tmp_path), payload)
        assert _hash2 == local_hash
        assert retained["payload"]["runCreate"]["payloadHash"] == \
            payload["runCreate"]["payloadHash"]
        assert retained["retryDeadlineAt"] == deadline_before
        # Absolute retry time is preserved even if the subsequent batch
        # lasts longer than the backoff; it must follow this replay attempt.
        assert retained["nextAttemptAt"] > replay_started_epoch
        assert _managed_artifact_bytes(str(tmp_path),
                                       retained["payload"]) == queued_bytes

        # No encode interval overlaps owned upload / response-read / close.
        assert_no_encode_overlap(timeline)

        # Continuation of the retained payload through the production retry
        # entry point: uploads once, receipt with the server run id, distinct
        # analysis confirmation (empty analyses), bytes retired. The real
        # backoff retained the entry beyond this run (asserted above); the
        # retry is made due by moving ONLY nextAttemptAt, never identity or
        # retryDeadlineAt.
        retained["nextAttemptAt"] = time.time() - 1
        _entry_path = os.path.join(str(tmp_path), f"{local_hash}.json")
        with open(_entry_path, "w", encoding="utf-8") as handle:
            json.dump(retained, handle)
        rc2, info = main.retry_due_uploads(
            queue_dir=str(tmp_path), base_url=backend.base_url,
            api_key="", retries=1)
        assert rc2 == 0, info
        assert info["submitted"] == 1
        assert local_hash not in _pending(str(tmp_path))
        receipt = json.loads((Path(tmp_path) / "receipts" /
                              f"{local_hash}.json").read_text())
        assert receipt["response"]["benchmarkRun"]["id"] == run_id
        assert receipt["response"]["artifact"]["storageState"] == "RETAINED"
        assert receipt["response"]["analyses"] == []  # upload != analysis
        assert backend.upload_attempts.get(run_id, 0) == 1
        assert _managed_artifact_bytes(str(tmp_path),
                                       retained["payload"]) is None
        _drain_workers()
    finally:
        backend.close()


# ---------------------------------------------------------------------------
# Acceptance 2: straggler outlives the bounded barrier -> safe pause with the
# durable queue retained (bytes/stable IDs/deadlines), bounded, never timed.
# ---------------------------------------------------------------------------

def test_f2_real_transport_pause_retains_queue_bytes_and_ids(tmp_path, monkeypatch):
    """Same real transport, but the dripped response + delayed watcher close
    outlive the bounded quiescence barrier: the batch must pause (rc 6,
    typed message) WITHOUT timing any encode, bounded, and the queued entry
    must survive with its bytes, stable IDs and retry deadline intact."""
    fixture, args = _fixture_and_args(tmp_path, 62)
    backend = ArtifactBackend()
    timeline = Timeline()
    clock = [0.0]
    try:
        monkeypatch.setenv("ENCODINGDB_HOST_PHASE_DIR", str(tmp_path / "phase"))
        monkeypatch.setattr(main, "ACTIVE_PUBLICATION_DEADLINE_SECONDS", 0.8)
        instrument_transport(monkeypatch, timeline, watcher_close_delay=2.6)
        backend.drip_first_create(6.0)

        artifact = tmp_path / "queued-artifact.mp4"
        artifact.write_bytes(artifact_bytes(b"pause-payload"))
        payload = build_submission_payload(
            artifact_path=artifact, campaign_id="campaign-real",
            recipe_id="recipe-queued", repetition_index=1)
        spool.spool_payload(str(tmp_path), payload)
        local_hash, entry = _retained_entry(str(tmp_path), payload)
        deadline_before = entry["retryDeadlineAt"]
        queued_bytes = _managed_artifact_bytes(str(tmp_path), entry["payload"])

        events = []
        started = time.monotonic()
        with _acceptance_patches(fixture,
                                 lambda **kw: pytest.fail("no encode may run")):
            rc = main.run_benchmark_batch(
                hardware=main.HardwareInfo("CPU", None, 16, "OS"),
                base_url=backend.base_url, args=args, event_sink=events.append,
                tasks=[{"encoder": "libx264", "preset": "fast", "crf": 24,
                        "suiteClip": fixture._quick_clip()}])
        elapsed = time.monotonic() - started
        assert rc == 6, events[-5:]
        assert elapsed < 4.0, "the safe pause must be bounded, not the full I/O"
        pause = [e for e in events if e.get("type") == "run_error"
                 and e.get("code") == 6]
        assert pause and "quiescence" in pause[0]["message"], pause
        assert not timeline.of("encode-start")

        # Safe pause retains the payload: entry + stable identity + bytes +
        # retry deadline, and the straggler's read/close really happened.
        _hash2, retained = _retained_entry(str(tmp_path), payload)
        assert _hash2 == local_hash
        assert retained["payload"]["runCreate"]["payloadHash"] == \
            payload["runCreate"]["payloadHash"]
        assert retained["retryDeadlineAt"] == deadline_before
        assert _managed_artifact_bytes(str(tmp_path),
                                       retained["payload"]) == queued_bytes
        assert timeline.spans("response-read")
        assert timeline.spans("close")
        _drain_workers()
    finally:
        backend.close()


# ---------------------------------------------------------------------------
# Acceptance 3: checkpoint continuation through the real CLI — a checkpoint
# upload abandoned mid-PUT (deadline, no cancel) never overlaps encodes, and
# the continuation replays it idempotently with ZERO repeated encodes.
# ---------------------------------------------------------------------------

def test_f2_real_checkpoint_upload_continuation_zero_repeated_encodes(tmp_path, monkeypatch):
    """Two recipes; the fake measurement clock pauses the batch right after
    recipe A's group is terminal (rc 11 checkpoint). Recipe A's first
    checkpoint upload runs the REAL create-auth-PUT chain against loopback
    HTTP with a dripped PUT response: the deadline (no user cancellation)
    abandons it mid-transport while the owned worker is still live; the
    second upload succeeds fast. The CLI continuation segment replays the
    retained entry to the SAME server run (idempotent, zero re-upload) and
    completes recipe B — with zero repeated completed encodes."""
    fixture, args = _fixture_and_args(tmp_path, 63)
    clip_b = replace(fixture._quick_clip(), clip_id="film-grain-1080p24-final",
                     workload_id="film-grain-1080p24-final")
    backend = ArtifactBackend()
    timeline = Timeline()
    clock = [0.0]
    try:
        monkeypatch.setenv("ENCODINGDB_HOST_PHASE_DIR", str(tmp_path / "phase"))
        monkeypatch.setattr(main, "ACTIVE_PUBLICATION_DEADLINE_SECONDS", 1.2)
        instrument_transport(monkeypatch, timeline, watcher_close_delay=0.0)
        backend.drip_first_upload(2.6)

        def new_budget(minutes, **kwargs):
            return campaign.MeasurementBudget(minutes,
                                              clock=lambda: clock[0], **kwargs)

        tasks = [{"encoder": "libx264", "preset": "fast", "crf": 24,
                  "suiteClip": fixture._quick_clip()},
                 {"encoder": "libx264", "preset": "fast", "crf": 24,
                  "suiteClip": clip_b}]
        events = []
        with mock.patch.object(main, "MeasurementBudget", side_effect=new_budget), \
                _acceptance_patches(fixture, _acceptance_encode(timeline, clock)):
            rc1 = main.run_benchmark_batch(
                hardware=main.HardwareInfo("CPU", None, 16, "OS"),
                base_url=backend.base_url, args=args, event_sink=events.append,
                tasks=tasks)
        assert rc1 == 11, events[-5:]
        encodes_segment1 = len(timeline.encode_windows())
        assert encodes_segment1 == 5, "recipe A terminal + recipe B partial"

        # Recipe A upload #1 abandoned mid-PUT (deadline, no cancel): the
        # entry is retained with stable IDs; upload #2 succeeded fast.
        pending = _pending(str(tmp_path))
        assert len(pending) == 1, pending
        retained_hash = pending.pop()[:-len(".json")]
        retained = spool.load_spool_entry(
            os.path.join(str(tmp_path), f"{retained_hash}.json"))
        stable_hash = spool.local_hash_for_payload(retained["payload"])
        assert stable_hash == retained_hash
        queued_bytes = _managed_artifact_bytes(str(tmp_path),
                                               retained["payload"])
        assert queued_bytes is not None
        assert retained["retryDeadlineAt"] > time.time()
        assert timeline.spans("upload") and timeline.spans("close")
        assert_no_encode_overlap(timeline)

        # The abandoned PUT really landed server-side once; the retained
        # entry references the same run identity for idempotent replay.
        run_ids = list(backend.run_order)
        assert len(run_ids) == 2, run_ids
        assert sum(backend.upload_attempts.values()) == 2

        campaign_id = next((tmp_path / "campaigns").iterdir()).name
        _drain_workers()
        # Make the retained entry due for the continuation's pre-run replay
        # by moving ONLY nextAttemptAt (identity/retryDeadline untouched);
        # the retention assertions above already proved the real backoff
        # kept the payload durable.
        retained["nextAttemptAt"] = time.time() - 1
        with open(os.path.join(str(tmp_path), f"{retained_hash}.json"),
                  "w", encoding="utf-8") as handle:
            json.dump(retained, handle)
        clock[0] = 1000.0  # the continuation segment gets a fresh window
        monkeypatch.setattr(main, "ACTIVE_PUBLICATION_DEADLINE_SECONDS", 60.0)
        with mock.patch.object(
                main, "_prepare_named_suite_clip",
                side_effect=lambda clip_id: (fixture._quick_clip()
                                             if clip_id == "athletic-action-1080p24-final"
                                             else clip_b)), \
                mock.patch.object(main, "MeasurementBudget", side_effect=new_budget), \
                _acceptance_patches(fixture, _acceptance_encode(timeline, clock)):
            rc2 = main.main(["prog", "--resume-campaign", campaign_id,
                             "--submit", "--max-duration-minutes", "0.5",
                             "--base-url", backend.base_url,
                             "--queue-dir", str(tmp_path)])
        assert rc2 == 0, rc2

        # Continuation: the retained checkpoint entry reached the SAME run
        # idempotently (server saw it as already uploaded — zero re-PUT),
        # and the total completed encode count never repeated an attempt.
        assert not _pending(str(tmp_path))
        receipts = sorted(p.stem for p in (Path(tmp_path) / "receipts").glob("*.json"))
        assert retained_hash in receipts
        receipt_for_retained = json.loads(
            (Path(tmp_path) / "receipts" / f"{retained_hash}.json").read_text())
        replayed_run = receipt_for_retained["response"]["benchmarkRun"]["id"]
        assert replayed_run in run_ids
        assert backend.upload_attempts[replayed_run] == 1  # never re-PUT
        journal_root = tmp_path / "campaigns" / campaign_id
        accepted = sorted(p.name for p in journal_root.glob("submission-*.accepted.json"))
        # A (abandoned-then-replayed + fast) and B (two checkpoint uploads):
        # 4 accepted measured attempts, zero duplicates.
        assert len(accepted) == 4, accepted
        # Zero repeated completed encodes: 5 (segment 1) + exactly 1 new
        # attempt (recipe B's missing measured run) = 6 encode windows.
        assert len(timeline.encode_windows()) == encodes_segment1 + 1
        assert_no_encode_overlap(timeline)
        _drain_workers()
    finally:
        backend.close()