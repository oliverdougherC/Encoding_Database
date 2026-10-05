"""Owned, fsynced campaign journals. References and runtime files are never modified."""
import dataclasses
import hashlib
import json
import os
import re
import secrets
import math
import sys
import time
import subprocess
import threading
from contextvars import ContextVar
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

from . import acknowledgments, config
from .console_policy import hidden_console_kwargs
from .protocol import (ArtifactProbe, BenchmarkRunRecord, EncodeTiming, EnvironmentSnapshot,
                       ScheduledRun, ValidityReason, ValidityResult)


PREPARATION_HEARTBEAT_FILENAME = "preparation.json"
PREPARATION_STALL_SECONDS = 300.0
PROBE_PROCESS_TIMEOUT_SECONDS = 60.0
_ACQUISITION_FENCE_BUDGET_SECONDS = 120.0
JOURNAL_REOPEN_BUDGET_SECONDS = 900.0


def _default_heartbeat_path():
    """Persistent substage trail: packaged clients always, scripts by env override.

    Auto-enabling only when frozen keeps unit tests and repo scripts from
    writing into a developer-visible state directory while the packaged
    client — the surface that produced the unattended 'never got past
    preparing runtime' incident — always leaves a postmortem trail."""
    explicit = str(os.environ.get("ENCODINGDB_PREPARATION_HEARTBEAT") or "").strip()
    if explicit:
        if explicit.lower() in ("0", "false", "off", "none"):
            return None
        return os.path.abspath(explicit)
    if not bool(getattr(sys, "frozen", False)):
        return None
    return os.path.join(config.default_client_state_dir(), PREPARATION_HEARTBEAT_FILENAME)


class PreparationTimeout(RuntimeError):
    """A preparation stage exhausted its finite wall-clock budget or went silent.

    Distinct from KeyboardInterrupt (operator cancellation) and from
    MeasurementBudgetExceeded (a resumable pause): the storage, cache, or
    runtime a stage touched is unresponsive; nothing measured was lost and
    the operator can retry after freeing that resource."""
    def __init__(self, stage, seconds, kind):
        self.stage = str(stage)
        self.budget_seconds = float(seconds)
        self.kind = kind
        limit = (f"exceeded its {self.budget_seconds:g}s wall-clock budget"
                 if kind == "budget" else
                 f"went silent for {self.budget_seconds:g}s")
        super().__init__(f"preparation stage '{self.stage}' {limit}; the storage, cache, "
                         "or runtime it touched is unresponsive — retry after freeing that resource")


class PreparationBudgetExceeded(PreparationTimeout):
    def __init__(self, stage, seconds):
        super().__init__(stage, seconds, "budget")


class PreparationStalled(PreparationTimeout):
    def __init__(self, stage, seconds):
        super().__init__(stage, seconds, "stall")


@dataclasses.dataclass
class _StageFrame:
    name: str
    budget_seconds: float
    deadline: float
    stall_seconds: float
    stall_deadline: float
    parent: Optional["_StageFrame"] = None
    parent_deadline_remaining: float = 0.0
    parent_stall_remaining: float = 0.0


_ACQUISITION_READER = None
_ACQUISITION_READER_LOCK = threading.Lock()
_PREPARATION = ContextVar("encodingdb_preparation", default=None)


class PreparationScope:
    """Cancellation, throttled progress, per-stage wall-clock budgets and a
    persistent substage/heartbeat trail — never a measurement deadline."""
    def __init__(self, cancel_event=None, progress=None, *, heartbeat_path=None, stall_seconds=None):
        self.cancel_event = cancel_event
        self.progress = progress
        self.last_key = None
        self.last_update = 0.0
        self.stall_seconds = PREPARATION_STALL_SECONDS if stall_seconds is None else max(1.0, float(stall_seconds))
        self.heartbeat_path = _default_heartbeat_path() if heartbeat_path is None else heartbeat_path
        self.started_monotonic = time.monotonic()
        self.started_wall = time.time()
        self.stage_stack = []

    def check(self):
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise KeyboardInterrupt
        if not self.stage_stack:
            return
        frame = self.stage_stack[-1]
        now = time.monotonic()
        if now >= frame.deadline:
            raise PreparationBudgetExceeded(frame.name, frame.budget_seconds)
        if now >= frame.stall_deadline:
            raise PreparationStalled(frame.name, frame.stall_seconds)

    def report(self, stage, **details):
        self.check()
        now = time.monotonic()
        if self.stage_stack:
            frame = self.stage_stack[-1]
            frame.stall_deadline = now + frame.stall_seconds
        substage = details.pop("substage", None) or stage
        key = (substage, details.get("path"), details.get("clipId"))
        if key != self.last_key or now - self.last_update >= 1.0:
            self.last_key, self.last_update = key, now
            self._write_heartbeat(substage, "progress", now, details)
            if self.progress:
                self.progress(stage, substage=substage, **details)
        self.check()

    def _write_heartbeat(self, stage, status, now, details=None, frame=None):
        if self.heartbeat_path is None:
            return
        if frame is None:
            frame = self.stage_stack[-1] if self.stage_stack else None
        payload = {"schemaVersion": 1, "pid": os.getpid(), "status": status,
                   "stage": frame.name if frame else stage, "substage": stage,
                   "startedAt": self.started_wall,
                   "elapsedSeconds": round(now - self.started_monotonic, 3),
                   "heartbeatAt": time.time(),
                   "stageBudgetSeconds": frame.budget_seconds if frame else None,
                   "stageStallSeconds": frame.stall_seconds if frame else None}
        for key in ("path", "clipId", "completedBytes", "totalBytes", "completed", "total", "message"):
            if details is not None and details.get(key) is not None:
                payload[key] = details[key]
        try:
            atomic_json(Path(self.heartbeat_path), payload)
        except OSError:
            pass  # A heartbeat trail must never break preparation itself.

    @contextmanager
    def stage(self, name, budget_seconds, stall_seconds=None, transitions=True):
        """Bound the innermost active stage; nesting suspends the outer deadline.

        A child stage consumes only its own budget: the parent's deadline and
        stall timers freeze while the child runs and resume with their saved
        remaining time when the child exits on any path. A body that blocks
        past its own deadline without a single checkpoint is reported as an
        overrun (aborted heartbeat, PreparationBudgetExceeded) instead of a
        silent success; operator cancellation still wins over late return."""
        budget = float(budget_seconds)
        if not math.isfinite(budget) or budget <= 0:
            raise ValueError("preparation stage budget must be positive and finite")
        stall = self.stall_seconds if stall_seconds is None else float(stall_seconds)
        stall = min(max(1.0, stall), budget)
        now = time.monotonic()
        frame = _StageFrame(str(name), budget, now + budget, stall, now + stall)
        if self.stage_stack:
            parent = self.stage_stack[-1]
            frame.parent = parent
            frame.parent_deadline_remaining = max(0.0, parent.deadline - now)
            frame.parent_stall_remaining = max(0.0, parent.stall_deadline - now)
        self.stage_stack.append(frame)
        if transitions:
            self._write_heartbeat(name, "started", now, frame=frame)
        try:
            self.check()
            yield frame
        except BaseException:
            self._retire(frame, "aborted", transitions)
            raise
        late = time.monotonic() >= frame.deadline
        self._retire(frame, "aborted" if late else "completed", transitions)
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise KeyboardInterrupt
        if late:
            raise PreparationBudgetExceeded(frame.name, frame.budget_seconds)

    def _retire(self, frame, status, transitions):
        """Pop a finished frame, resume its frozen parent timers, trail the outcome."""
        self.stage_stack.pop()
        now = time.monotonic()
        if frame.parent is not None:
            frame.parent.deadline = now + frame.parent_deadline_remaining
            frame.parent.stall_deadline = now + frame.parent_stall_remaining
        if transitions:
            self._write_heartbeat(frame.name, status, now, frame=frame)

    @contextmanager
    def activate(self):
        token = _PREPARATION.set(self)
        try:
            self.check()
            # The fence bounds only the handoff from an older canceled network
            # reader; the preparation body below runs under its own stage budgets.
            with self.stage("acquisition-fence", _ACQUISITION_FENCE_BUDGET_SECONDS, transitions=False):
                wait_for_owned_acquisition()
            yield self
        finally:
            _PREPARATION.reset(token)


def preparation_progress(stage, **details):
    scope = _PREPARATION.get()
    if scope is not None:
        scope.report(stage, **details)


def preparation_heartbeat(*, substage=None, **details):
    """Progress pulse for the open stage, if any; silent outside stages.

    Long silent computes (binary hashing) emit through this so stall
    watchdogs see forward motion and the persistent trail names the exact
    file being hashed; cancel checks stay unconditional at call sites.
    Gating on an open stage keeps measurement-phase hashing (journal save)
    from being mislabelled as a preparation stage in the GUI."""
    scope = _PREPARATION.get()
    if scope is not None and scope.stage_stack:
        scope.report(scope.stage_stack[-1].name, substage=substage, **details)


@contextmanager
def preparation_stage(name, budget_seconds, stall_seconds=None, transitions=True):
    """Stage budget that degrades to a no-op outside a preparation scope."""
    scope = _PREPARATION.get()
    if scope is None:
        yield None
        return
    with scope.stage(name, budget_seconds, stall_seconds, transitions) as frame:
        yield frame


def check_preparation_cancelled():
    scope = _PREPARATION.get()
    if scope is not None:
        scope.check()


def wait_for_owned_acquisition():
    """Fence subsequent preparation/timing from an older canceled network read."""
    while True:
        check_preparation_cancelled()
        with _ACQUISITION_READER_LOCK:
            reader = _ACQUISITION_READER
        if reader is None or not reader.is_alive():
            return
        preparation_progress("download-closing")
        reader.join(timeout=0.1)


def start_owned_acquisition(reader):
    """At most one network reader per client process, including canceled work."""
    global _ACQUISITION_READER
    while True:
        wait_for_owned_acquisition()
        with _ACQUISITION_READER_LOCK:
            previous = _ACQUISITION_READER
            if previous is not None and previous.is_alive():
                continue
            check_preparation_cancelled()
            _ACQUISITION_READER = reader
            reader.start()
            return


_MEASUREMENT_BUDGET = ContextVar("encodingdb_measurement_budget", default=None)


class MeasurementBudgetExceeded(BaseException):
    """A resumable pause, not invalid scientific evidence or a probe failure."""
    def __init__(self, budget):
        self.budget = budget
        super().__init__(f"Measurement time budget of {budget.minutes:g} minutes exhausted")


class MeasurementBudget:
    def __init__(self, minutes=60, *, cancel_event=None, clock=None):
        self.minutes = float(minutes)
        if not math.isfinite(self.minutes) or not math.isfinite(self.minutes * 60) or self.minutes <= 0:
            raise ValueError("--max-duration-minutes must be positive and finite")
        self.clock = clock or time.monotonic
        self.started = self.clock()
        self.deadline = self.started + self.minutes * 60
        self.cancel_event = cancel_event

    def remaining_seconds(self):
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise KeyboardInterrupt
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise MeasurementBudgetExceeded(self)
        return remaining

    def check(self):
        self.remaining_seconds()

    @contextmanager
    def activate(self):
        token = _MEASUREMENT_BUDGET.set(self)
        try:
            self.check()
            yield self
        finally:
            _MEASUREMENT_BUDGET.reset(token)


def check_measurement_budget():
    check_preparation_cancelled()
    budget = _MEASUREMENT_BUDGET.get()
    if budget is not None:
        budget.check()


def measurement_timeout(maximum):
    budget = _MEASUREMENT_BUDGET.get()
    return maximum if budget is None else min(maximum, budget.remaining_seconds())


def run_measurement_process(*args, **kwargs):
    """Own validation tools during preparation and the measured campaign allowance."""
    for key, value in hidden_console_kwargs().items():
        kwargs.setdefault(key, value)
    budget = _MEASUREMENT_BUDGET.get()
    if budget is None and _PREPARATION.get() is None:
        return subprocess.run(*args, **kwargs)
    check_measurement_budget()
    timeout = kwargs.pop("timeout", None)
    if timeout is None:
        # A scoped validation probe always owns a finite wall-clock deadline:
        # the measurement allowance clamps it further when one is active, and
        # preparation-only callers fall back to the probe default so a hung
        # ffmpeg/ffprobe can never pin preparation forever.
        timeout = (min(60, budget.remaining_seconds()) if budget is not None
                   else PROBE_PROCESS_TIMEOUT_SECONDS)
    check = kwargs.pop("check", False)
    command = args[0] if args else kwargs.get("args")
    deadline = time.monotonic() + timeout if timeout is not None else None
    kwargs.setdefault("start_new_session", os.name != "nt")
    with subprocess.Popen(*args, **kwargs) as process:
        try:
            while True:
                try:
                    poll_seconds = 0.2 if deadline is None else min(0.2, max(0.001, deadline - time.monotonic()))
                    stdout, stderr = process.communicate(timeout=measurement_timeout(poll_seconds))
                    break
                except subprocess.TimeoutExpired:
                    check_measurement_budget()
                    if deadline is not None and time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(command, timeout)
            check_measurement_budget()
            if check and process.returncode:
                raise subprocess.CalledProcessError(process.returncode, command, output=stdout, stderr=stderr)
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        except BaseException:
            from .ffmpeg import _terminate_owned_process
            _terminate_owned_process(process)
            raise


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + secrets.token_hex(8))
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, default=lambda obj: dataclasses.asdict(obj))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def sync_owned_file(path) -> None:
    """Flush an owned artifact without changing bytes or truncating the file.

    Windows os.fsync calls CRT _commit/FlushFileBuffers, which requires a
    write-capable handle. Reopening in rb works on POSIX but fails on Windows.
    """
    with open(path, "r+b") as handle:
        os.fsync(handle.fileno())


def physical_source_id(state_dir=None) -> str:
    root = Path(state_dir or config.default_client_state_dir())
    root.mkdir(parents=True, exist_ok=True)
    path = root / "physical-source-id"
    if not path.exists():
        temporary = root / (".identity-" + secrets.token_hex(8))
        try:
            with temporary.open("x", encoding="ascii") as handle:
                handle.write("installation-" + secrets.token_hex(32))
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            try:
                os.link(temporary, path)  # create-if-absent, complete contents visible atomically
            except FileExistsError:
                pass
        finally:
            temporary.unlink(missing_ok=True)
    value = path.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"installation-[0-9a-f]{64}", value):
        raise ValueError("Installation identity is corrupt; restore it before collecting")
    return value


def journal_path(queue_dir: str, campaign_id: str) -> Path:
    if not re.fullmatch(r"campaign-[0-9a-f]{16}", campaign_id):
        raise ValueError("Invalid campaign ID")
    return Path(queue_dir) / "campaigns" / campaign_id


def load_record(value: dict) -> BenchmarkRunRecord:
    def validity(key):
        raw = value[key]
        return ValidityResult(raw["state"], [ValidityReason(**reason) for reason in raw["reasons"]])
    return BenchmarkRunRecord(
        schedule=ScheduledRun(**value["schedule"]),
        environment_snapshot=EnvironmentSnapshot(**value["environmentSnapshot"]) if value["environmentSnapshot"] else None,
        environment_validity=validity("environmentValidity"),
        structural_validity=validity("structuralValidity"), overall_validity=validity("overallValidity"),
        timing=EncodeTiming(**value["timing"]) if value["timing"] else None,
        probe=ArtifactProbe(**value["probe"]) if value["probe"] else None,
        metadata=value["metadata"], counted_for_stability=value["countedForStability"],
        skipped_before_encode=value["skippedBeforeEncode"],
    )


class CampaignJournal:
    def __init__(self, queue_dir: str, campaign_id: str, manifest: dict, max_storage_mb: int):
        self.root = journal_path(queue_dir, campaign_id)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_storage_mb * 1024 * 1024
        self.queue_root = Path(queue_dir)
        self.records = {}
        manifest_path = self.root / "manifest.json"
        if manifest_path.exists():
            existing = json.loads(manifest_path.read_text())
            if existing != manifest:
                raise ValueError("Campaign environment, recipes or protocol changed; start a new campaign")
        else:
            atomic_json(manifest_path, manifest)
        # The retention allowance is campaign policy, not plan identity: it persists
        # beside the manifest so resumes keep the original budget without making the
        # frozen manifest drift for journals written before this separation existed.
        budget_path = self.root / "budget.json"
        # Entry points restore the saved allowance only when the caller has not
        # supplied an explicit limit. Honor their resolved policy here, including
        # deliberate increases or decreases, without changing campaign identity.
        atomic_json(budget_path, {"schemaVersion": 1, "maxStorageMb": int(max_storage_mb)})
        # Reopen hashes every retained artifact on resumable storage; a hung
        # disk must fail the stage with a name instead of pinning preparation
        # open forever, and operator cancel must land between hash chunks.
        with preparation_stage("journal-reopen", JOURNAL_REOPEN_BUDGET_SECONDS):
            for path in sorted(self.root.glob("attempt-*.json")):
                record = load_record(json.loads(path.read_text()))
                info = record.metadata.get("info") or {}
                artifact = info.get("artifactPath")
                if artifact and not info.get("error"):
                    candidate = Path(artifact)
                    if candidate.is_file():
                        if self.root.resolve() not in candidate.resolve().parents:
                            raise ValueError("Journal artifact missing or outside owned campaign")
                        if self.hash_file(candidate) != info.get("artifactSha256"):
                            raise ValueError("Journal artifact changed; cannot resume")
                    elif record.schedule.phase == "warmup":
                        if not self._warmup_released(record):
                            raise ValueError("Warmup artifact missing without verified release evidence")
                    elif not self.accepted_receipt(record):
                        raise ValueError("Journal artifact missing or outside owned campaign")
                self.records[record.schedule.execution_order] = record

    @staticmethod
    def hash_file(path):
        digest = hashlib.sha256()
        completed = 0
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                check_preparation_cancelled()
                digest.update(chunk)
                completed += len(chunk)
                preparation_heartbeat(path=str(path), completedBytes=completed)
        return digest.hexdigest()

    def _receipt_path(self, execution_order: int) -> Path:
        return self.root / f"submission-{execution_order:06d}.accepted.json"

    def accepted_receipt(self, record):
        """Return the accepted-upload receipt when it is faithful to the attempt.

        A v1 receipt counts when it names the same execution order, recipe,
        exact artifact path and SHA-256 as the journaled record and carries
        the server's run id (historical provenance stays valid). A v2 receipt
        additionally binds the immutable runCreate payloadHash to the saved
        envelope plus the server artifact identity (F4). Corrupt, empty,
        partial or mismatched receipts never authorize skipping an upload or
        trusting a released artifact. Historical (v1) markers keep the
        attempt readable and its released bytes explainable, but consumers
        that need a FRESH verified acknowledgment must gate on
        ``accepted_receipt_verdict(record) == "verified"`` instead.
        """
        return self.accepted_receipt_for_verdict(record, "verified", "historical")

    def accepted_receipt_verdict(self, record) -> str:
        """``verified`` / ``historical`` / ``unverified:<why>`` for the record."""
        receipt = self.accepted_receipt_for_verdict(record, "verified", "historical")
        if receipt is None:
            return "unverified:journal-receipt-missing-or-unfaithful"
        verdict = self._receipt_verdict(record, receipt)
        return verdict

    def accepted_receipt_for_verdict(self, record, *verdicts: str):
        """Return the marker only when its verdict is one of `verdicts`."""
        info = record.metadata.get("info") or {}
        artifact_path = str(info.get("artifactPath") or "").strip()
        artifact_sha = info.get("artifactSha256")
        if not artifact_path or not artifact_sha:
            return None
        try:
            receipt = json.loads(self._receipt_path(record.schedule.execution_order).read_text())
        except (OSError, ValueError):
            return None
        if not isinstance(receipt, dict) or receipt.get("schemaVersion") not in (1, 2):
            return None
        if self._receipt_verdict(record, receipt) not in verdicts:
            return None
        return receipt

    def _receipt_verdict(self, record, receipt):
        info = record.metadata.get("info") or {}
        envelope_payload_hash: Optional[str] = None
        envelope = None
        if receipt.get("schemaVersion") == 2:
            try:
                envelope = json.loads((self.root / f"submission-{record.schedule.execution_order:06d}.json").read_text())
                if isinstance(envelope, dict) and isinstance(envelope.get("runCreate"), dict):
                    candidate = str(envelope["runCreate"].get("payloadHash") or "").strip().lower()
                    envelope_payload_hash = candidate or None
            except (OSError, ValueError):
                envelope_payload_hash = None
        return acknowledgments.journal_marker_verdict(
            receipt, execution_order=record.schedule.execution_order,
            recipe_id=record.schedule.recipe_id,
            artifact_path=str(info.get("artifactPath") or ""),
            artifact_sha256=str(info.get("artifactSha256") or ""),
            payload_hash=envelope_payload_hash if receipt.get("schemaVersion") == 2 else None,
            payload=envelope)

    def _warmup_released(self, record) -> bool:
        info = record.metadata.get("info") or {}
        try:
            evidence = json.loads((self.root / f"warmup-{record.schedule.execution_order:06d}.released.json").read_text())
        except (OSError, ValueError):
            return False
        return (isinstance(evidence, dict)
                and evidence.get("schemaVersion") == 1
                and evidence.get("executionOrder") == record.schedule.execution_order
                and evidence.get("recipeId") == record.schedule.recipe_id
                and evidence.get("artifactPath") == str(info.get("artifactPath") or "").strip()
                and evidence.get("artifactSha256") == info.get("artifactSha256"))

    def release_warmup_artifact(self, record) -> bool:
        """Delete a hash-verified warmup output whose bytes have no consumer.

        Warmups tune encoders before measurement; they are never uploaded and
        never re-read once the attempt (with its SHA-256) is durable. Release
        evidence keeps the journal reopenable without the bytes; any hash
        mismatch keeps the file in place so the budget check fails honestly."""
        info = record.metadata.get("info") or {}
        artifact = str(info.get("artifactPath") or "").strip()
        sha = info.get("artifactSha256")
        if record.schedule.phase != "warmup" or not artifact or not sha:
            return False
        candidate = Path(artifact)
        if self.root.resolve() not in candidate.resolve().parents or not candidate.is_file():
            return False
        if self.hash_file(candidate) != sha:
            return False
        atomic_json(self.root / f"warmup-{record.schedule.execution_order:06d}.released.json",
                    {"schemaVersion": 1,
                     "executionOrder": record.schedule.execution_order,
                     "recipeId": record.schedule.recipe_id,
                     "artifactPath": artifact,
                     "artifactSha256": sha,
                     "releasedAt": time.time()})
        candidate.unlink()
        return True

    def campaign_bytes(self):
        return directory_bytes(str(self.root))

    def check_budget(self):
        """This campaign's retention allowance plus a whole-volume safety floor.

        One campaign's retained bytes never block a different campaign: the
        allowance below is charged to THIS journal only. The floor is global
        protection for the disk itself and applies to every run."""
        used = self.campaign_bytes()
        if used >= self.max_bytes:
            raise OSError(f"this campaign retained {used // (1024 * 1024)} MB of its "
                          f"{self.max_bytes // (1024 * 1024)} MB allowance; accepted uploads retire "
                          f"automatically at checkpoints — wait for one, remove finished campaigns, "
                          f"or raise --max-storage-mb if the volume allows")
        from shutil import disk_usage
        floor_mb = max(0, int(os.environ.get("ENCODINGDB_MIN_FREE_MB", "1024")))
        free = disk_usage(str(self.queue_root)).free
        if free < floor_mb * 1024 * 1024:
            raise OSError(f"volume free space {free // (1024 * 1024)} MB is below the "
                          f"{floor_mb} MB safety floor reserved for the system; free space and retry")
        return min(self.max_bytes - used, free - floor_mb * 1024 * 1024)

    def save(self, record):
        info = record.metadata.get("info") or {}
        artifact = info.get("artifactPath")
        if artifact and Path(artifact).is_file():
            sync_owned_file(artifact)
            info["artifactSha256"] = self.hash_file(artifact)
        atomic_json(self.root / f"attempt-{record.schedule.execution_order:06d}.json", record.to_dict())
        self.records[record.schedule.execution_order] = record


    def measurement_lock(self):
        """The OS releases this lock after kill/crash; never unlink a live lock inode."""
        from contextlib import contextmanager
        @contextmanager
        def locked():
            path = self.queue_root / "measurement.lock"
            with path.open("a+b") as handle:
                handle.seek(0)
                handle.write(b"0")
                handle.flush()
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                try:
                    # A SIGKILL cannot run client cleanup. Recover only processes
                    # whose PID creation time and complete command match our receipt.
                    for receipt in self.root.glob("*.active.json"):
                        import psutil
                        raw = json.loads(receipt.read_text())
                        try:
                            process = psutil.Process(raw["pid"])
                            matches = process.create_time() == raw["createdAt"] and process.cmdline() == raw["command"]
                            artifact = Path(raw["command"][-1]).resolve()
                            if matches and self.root.resolve() in artifact.parents:
                                from .ffmpeg import _terminate_owned_process
                                if os.name == "nt":
                                    import subprocess
                                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False, capture_output=True, timeout=10,
                                                   **hidden_console_kwargs())
                                else:
                                    import signal
                                    if os.getpgid(process.pid) != process.pid:
                                        raise RuntimeError("Interrupted encoder process group changed")
                                    os.killpg(process.pid, signal.SIGKILL)
                                try:
                                    process.wait(timeout=5)
                                except psutil.TimeoutExpired:
                                    raise RuntimeError("Interrupted encoder did not stop")
                        except psutil.NoSuchProcess:
                            pass
                        receipt.unlink()
                    yield
                finally:
                    if os.name == "nt":
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return locked()


def active_collection(queue_dir: str):
    """Describe the live collector holding this queue, if any.

    A held measurement lock (or a live encoder receipt during the brief
    between-segment window) means an authoritative collection is running; a
    second collector would corrupt measurement timing and is refused before
    any expensive preparation."""
    root = Path(queue_dir)
    lock = root / "measurement.lock"
    if not lock.exists():
        return None
    try:
        with lock.open("a+b") as handle:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass  # Only a denied LOCK attempt means another collector holds it.
            else:
                return None
    except OSError as exc:
        # Opening/reading the lock is a permissions or media problem, NOT evidence
        # of a running collector; report it accurately instead of mislabelling it.
        raise OSError(f"Cannot inspect this queue's measurement lock: {exc}") from exc
    import psutil
    for receipt in sorted(root.glob("campaigns/*/*.active.json")):
        try:
            raw = json.loads(receipt.read_text())
            process = psutil.Process(int(raw.get("pid", -1)))
            if process.create_time() == raw.get("createdAt"):
                return {"campaignId": receipt.parent.name, "pid": int(raw["pid"])}
        except Exception:
            continue
    return {"campaignId": None, "pid": None}


def directory_bytes(path: str) -> int:
    """Bytes retained under a directory; a retiring upload is not an error."""
    total = 0
    for root, _dirs, names in os.walk(path):
        for name in names:
            try:
                total += os.stat(os.path.join(root, name)).st_size
            except FileNotFoundError:
                continue
    return total
