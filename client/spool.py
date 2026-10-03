import hashlib
import errno
import json
import os
import shutil
import time
import random
import tempfile
from pathlib import Path
import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from . import network
from . import acknowledgments
from .artifacts import AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND, submit_artifact_submission
from .campaign import directory_bytes
from .network import SubmissionCancelled, SubmitError, submit

SPOOL_VERSION = 1
MANAGED_ARTIFACT_DIRNAME = "artifacts"
SPOOL_METADATA_RESERVE_BYTES = 64 * 1024
REPLAY_WINDOW = 25
REPLAY_SECONDS = 60.0

# True only inside a collector's own batch: its checkpoint uploads legitimately run
# while it holds this queue's measurement lock. External publishers must defer.
_COLLECTOR_PUBLICATION_SCOPE: contextvars.ContextVar = contextvars.ContextVar(
    "encodingdb_collector_publication", default=False)

# True while this process holds the host phase lock; nested publication passes
# (collector checkpoint uploads, publish wrapper around replay) reuse it.
_HOST_PHASE_HELD: contextvars.ContextVar = contextvars.ContextVar(
    "encodingdb_host_phase_held", default=False)


@contextmanager
def collector_publication_scope():
    """Declare that the calling process owns the live collection for this queue."""
    token = _COLLECTOR_PUBLICATION_SCOPE.set(True)
    try:
        yield
    finally:
        _COLLECTOR_PUBLICATION_SCOPE.reset(token)


def _refuse_publication_during_measurement(queue_dir: str) -> None:
    """Publication defers to a collector measuring on this queue (C11).

    The probe opens measurement.lock non-blockingly from a fresh descriptor; a
    held lock - even one owned by this same process through another descriptor -
    means authoritative collection is timing-sensitive right now. Only the
    collector's own in-batch uploads (``collector_publication_scope``) skip it."""
    if _COLLECTOR_PUBLICATION_SCOPE.get():
        return
    from .campaign import active_collection
    try:
        active = active_collection(queue_dir)
    except OSError as exc:
        raise SpoolCapacityError(f"Cannot verify publication exclusion: {exc}") from exc
    if active is not None:
        raise SpoolCapacityError(
            "A collection is measuring in this queue; publication defers to its next checkpoint")


def publication_lock_busy(queue_dir: str) -> bool:
    """True when another publisher currently owns this queue's publication lock."""
    try:
        with _spool_write_lock(queue_dir):
            return False
    except SpoolCapacityError:
        return True


def _host_phase_lock_path() -> str:
    """Host-scoped lock file shared by every queue of this user on this machine.

    C11: two different queue directories on the same host still share one disk
    and network path, so measurement timing and publication cannot overlap even
    across queues. The kernel releases flock/msvcrt ownership on process death,
    so a crash needs no stale-lock cleanup - and none is ever performed."""
    root = os.environ.get("ENCODINGDB_HOST_PHASE_DIR") or os.path.join(
        tempfile.gettempdir(), "encodingdb-host-phase-{}".format(getattr(os, "getuid", lambda: "shared")()))
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, "phase.lock")


def _host_phase_probe_held() -> bool:
    """True when some process currently owns the host phase lock (advisory).

    Fail-closed: an uninspectable lock file raises OSError; correctness never
    depends on this probe - both phases acquire the lock non-blockingly before
    doing timing-sensitive work, and the loser defers."""
    path = _host_phase_lock_path()
    try:
        with open(path, "a+b") as handle:
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"0")
                handle.flush()
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    return True
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                return False
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return False
    except OSError:
        raise


def host_phase_busy() -> bool:
    """True when another phase owner currently holds the host phase lock (C11).

    Advisory probe for start guards; the authoritative arbiter remains the
    non-blocking acquire inside ``host_phase_hold``. Re-entry by the current
    holder reports free - a collector guard runs inside its own measurement
    hold and must not refuse itself. Fails closed: an uninspectable lock file
    raises SpoolCapacityError."""
    if _HOST_PHASE_HELD.get():
        return False
    try:
        return _host_phase_probe_held()
    except OSError as exc:
        raise SpoolCapacityError(f"Cannot inspect host phase lock: {exc}") from exc


@contextmanager
def host_phase_hold(role: str = "publication"):
    """Kernel-backed host phase lock for one collector batch or one publication
    pass (C11).

    Measurement takes the lock exclusively and publication shared, so a held
    collector defers publishers and a held publisher defers the next collector,
    in either start order: the non-blocking acquire is the atomic arbiter, so
    neither side can slip between the other's probe and acquisition. Two
    publishers coexist (uploads are idempotent and time-insensitive); only
    measurement timing needs the exclusive phase. (msvcrt has no shared lock,
    so on Windows publishers serialize - deferral is always safe.) A busy lock
    raises SpoolCapacityError - publishers defer, collectors exit 6 - while any
    other inspection failure also fails closed. The kernel releases flock
    ownership on process death; no stale-lock deletion exists. Re-entry inside
    the same process/thread (collector checkpoint upload, publish wrapper
    around replay) reuses the held lock. Only acquisition errors are wrapped:
    an OSError raised by the body propagates unchanged."""
    if _HOST_PHASE_HELD.get():
        yield False
        return
    path = _host_phase_lock_path()
    try:
        handle = open(path, "a+b")
    except OSError as exc:
        raise SpoolCapacityError(f"Cannot inspect host phase lock: {exc}") from exc
    try:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"0")
            handle.flush()
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            mode = fcntl.LOCK_EX if role == "measurement" else fcntl.LOCK_SH
            fcntl.flock(handle.fileno(), mode | fcntl.LOCK_NB)
    except OSError as exc:
        busy = getattr(exc, "errno", None) in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK,
                                               errno.EDEADLK) or type(exc).__name__ == "BlockingIOError"
        try:
            handle.close()
        except OSError:
            pass
        if not busy:
            raise SpoolCapacityError(f"Cannot inspect host phase lock: {exc}") from exc
        if role == "measurement":
            raise SpoolCapacityError(
                "A publication or measurement pass owns this host right now; "
                "wait for it to finish before starting collection") from exc
        raise SpoolCapacityError(
            "A collector is measuring on this host; publication defers to its next checkpoint") from exc
    token = _HOST_PHASE_HELD.set(True)
    # R05: every transport worker started inside this hold is owned by it. On
    # release the workers are reaped (bounded sync join); if one is still
    # mid-I/O, the ORIGINAL kernel lock stays held (deferred releaser) until
    # the worker is quiescent — a collector can never start while a
    # cancelled/timed-out worker still owns live transport I/O. F1: the
    # deferred releaser never attempts an SH→EX conversion. On Linux a failed
    # nonblocking conversion can DROP the descriptor's shared lock (letting a
    # collector take EX the moment other publishers exit, while the deferred
    # worker is still doing I/O), and a successful one serializes every other
    # publisher. The retained SH already excludes measurement EX, which is
    # all quiescence needs.
    worker_phase = network.begin_owned_worker_phase()

    def _release_kernel_lock() -> None:
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    try:
        yield True
    finally:
        _HOST_PHASE_HELD.reset(token)
        network.end_owned_worker_phase(worker_phase, _release_kernel_lock)


class SpoolCapacityError(OSError):
    """Recoverable publication pause; immutable campaign artifacts remain owned."""


@contextmanager
def _spool_write_lock(queue_dir: str):
    # Serialize all queue/managed-file mutations across CLI processes. Never unlink
    # this inode: the OS releases ownership after a process exits or crashes.
    os.makedirs(queue_dir, exist_ok=True)
    with open(os.path.join(queue_dir, "publication.lock"), "a+b") as handle:
        if os.name == "nt":
            import msvcrt
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            acquire = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            release = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            acquire = lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            release = lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        try:
            acquire()
        except OSError as exc:
            raise SpoolCapacityError("Another publisher owns this queue; retry publication later") from exc
        try:
            yield
        finally:
            release()


def _publication_bytes(queue_dir: str) -> int:
    """Shared publication store: pending entries, managed copies, receipts, dead
    letters. OTHER campaigns' retained attempts are charged to their own journal
    allowance, never to this run's budget."""
    def fail_scan(error):
        raise error
    total = 0
    for root, dirs, names in os.walk(queue_dir, onerror=fail_scan):
        if os.path.abspath(root) == os.path.abspath(queue_dir) and "campaigns" in dirs:
            dirs.remove("campaigns")
        # Stat errors fail closed rather than undercount.
        total += sum(os.stat(os.path.join(root, name)).st_size for name in names)
    return total


def _check_spool_capacity(queue_dir: str, payload: Dict[str, Any], max_storage_mb: int) -> None:
    staged = dict(payload)
    copy_bytes = 0
    source = ""
    if payload.get("submissionKind") == AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND:
        source = str(payload.get("artifactPath") or "").strip()
        sha = str(payload.get("artifactSha256") or "").strip().lower()
        if source and sha and os.path.exists(source):
            size = int(payload.get("artifactByteSize", -1))
            if size < 0 or os.path.getsize(source) != size:
                raise ValueError("Retained artifact size differs from immutable upload metadata")
            destination = _managed_artifact_path(queue_dir, sha, source)
            if not os.path.exists(destination):
                copy_bytes = size
            staged.update(artifactPath=destination, artifactManaged=True)
    metadata_bytes = len(json.dumps(_envelope_for_payload(staged), sort_keys=True).encode("utf-8"))
    used = _publication_bytes(queue_dir)
    # Submission envelopes do not carry a top-level campaignId. Account for
    # the original using its owned filesystem location, including older flat
    # campaign layouts, instead of trusting optional payload metadata.
    if source:
        campaigns = Path(queue_dir).resolve() / "campaigns"
        try:
            relative = Path(source).resolve().relative_to(campaigns)
        except (OSError, ValueError):
            relative = None
        if relative is not None and relative.parts:
            owned = campaigns / relative.parts[0]
            used += directory_bytes(str(owned)) if owned.is_dir() else owned.stat().st_size
    required = copy_bytes + metadata_bytes + SPOOL_METADATA_RESERVE_BYTES
    if used + required > max_storage_mb * 1024 * 1024:
        raise SpoolCapacityError(
            f"Publication storage budget reached: this campaign's retained attempts plus pending "
            f"uploads exceed its {max_storage_mb} MB allowance ({used // (1024 * 1024)} MB used). "
            f"Accepted uploads retire at checkpoints — wait for one, or raise --max-storage-mb if the volume allows")
    floor_mb = max(0, int(os.environ.get("ENCODINGDB_MIN_FREE_MB", "1024")))
    free = shutil.disk_usage(queue_dir).free
    if free - required < floor_mb * 1024 * 1024:
        raise SpoolCapacityError(f"Insufficient free disk for publication staging: only "
                                 f"{free // (1024 * 1024)} MB free against the {floor_mb} MB safety "
                                 f"floor; free space and resume the retained campaign")


@dataclass
class ReplayStats:
    submitted: int = 0
    retained: int = 0
    dead_lettered: int = 0
    corrupt: int = 0
    cancelled: int = 0
    deferred: int = 0


@dataclass
class QueueStatus:
    pending_entries: int = 0
    pending_bytes: int = 0
    dead_letter_files: int = 0
    dead_letter_bytes: int = 0
    managed_artifact_files: int = 0
    managed_artifact_bytes: int = 0


@dataclass
class CleanupStats:
    removed_dead_letter_files: int = 0
    removed_dead_letter_bytes: int = 0
    removed_orphaned_managed_artifacts: int = 0
    removed_orphaned_managed_artifact_bytes: int = 0
    pending_entries_retained: int = 0


def _canonical_payload_json(payload: Dict[str, Any]) -> str:
    return json.dumps(_payload_hash_material(payload), separators=(",", ":"), sort_keys=True)


def _payload_hash_material(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(payload)
    if normalized.get("submissionKind") == AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND:
        normalized.pop("artifactPath", None)
        normalized.pop("artifactManaged", None)
    return normalized


def local_hash_for_payload(payload: Dict[str, Any]) -> str:
    # Single canonical implementation lives in the F4 validator so receipt
    # binding and queue identity can never drift apart.
    return acknowledgments.local_payload_hash(payload)


def _queue_path(queue_dir: str, local_hash: str) -> str:
    return os.path.join(queue_dir, f"{local_hash}.json")


def _dead_letter_dir(queue_dir: str) -> str:
    return os.path.join(queue_dir, "dead-letter")


def _managed_artifact_dir(queue_dir: str) -> str:
    return os.path.join(queue_dir, MANAGED_ARTIFACT_DIRNAME)


def count_pending_entries(queue_dir: str) -> int:
    try:
        return len([
            name for name in os.listdir(queue_dir)
            if name.endswith(".json") and os.path.isfile(os.path.join(queue_dir, name))
        ])
    except Exception:
        return 0


def due_first_queue_paths(queue_dir: str, *, limit: int = REPLAY_WINDOW) -> Tuple[List[str], int]:
    """Fair bounded due-first selection (C08).

    Returns (paths, deferred). Entries whose Retry-After has arrived - or whose
    retry deadline has expired, so the verdict can be finalized - are due; the
    window admits only due entries, oldest-scheduled first, so a failing prefix
    can never starve healthy entries behind it. Delayed entries are counted as
    deferred, never attempted early."""
    now = time.time()
    due: List[Tuple[float, int, str, str]] = []
    deferred = 0
    try:
        names = sorted(os.listdir(queue_dir))
    except OSError:
        return [], 0
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(queue_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            entry = load_spool_entry(path)
            next_at = float(entry.get("nextAttemptAt") or 0)
            deadline = float(entry.get("retryDeadlineAt") or 0)
            queued = int(entry.get("queuedAt") or 0)
        except Exception:
            # Corrupt files are due immediately: the cheap terminal verdict
            # retires them before healthy traffic waits behind them.
            due.append((float("-inf"), 0, name, path))
            continue
        if next_at <= now or deadline <= now:
            due.append((next_at, queued, name, path))
        else:
            deferred += 1
    due.sort(key=lambda item: (item[0], item[1], item[2]))
    selected = [item[3] for item in due[:max(0, limit)]]
    return selected, deferred + max(0, len(due) - len(selected))


def _iter_files(root: str) -> List[str]:
    files: List[str] = []
    if not os.path.isdir(root):
        return files
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            path = os.path.join(dirpath, filename)
            if os.path.isfile(path):
                files.append(path)
    return files


def _sum_file_sizes(paths: List[str]) -> int:
    total = 0
    for path in paths:
        try:
            total += int(os.path.getsize(path))
        except Exception:
            continue
    return total


def inspect_spool(queue_dir: str) -> QueueStatus:
    status = QueueStatus()
    try:
        pending_files = sorted([
            os.path.join(queue_dir, name)
            for name in os.listdir(queue_dir)
            if name.endswith(".json") and os.path.isfile(os.path.join(queue_dir, name))
        ])
    except Exception:
        pending_files = []
    status.pending_entries = len(pending_files)
    status.pending_bytes = _sum_file_sizes(pending_files)

    dead_letter_files = _iter_files(_dead_letter_dir(queue_dir))
    status.dead_letter_files = len(dead_letter_files)
    status.dead_letter_bytes = _sum_file_sizes(dead_letter_files)

    managed_files = _iter_files(_managed_artifact_dir(queue_dir))
    status.managed_artifact_files = len(managed_files)
    status.managed_artifact_bytes = _sum_file_sizes(managed_files)
    return status


def cleanup_spool(queue_dir: str) -> CleanupStats:
    # F7: cleanup deletes dead-letter media and orphaned managed artifacts.
    # Like every other publication-side mutation it must hold the host-level
    # publication exclusion FIRST, so a collector's measurement phase on this
    # host can never race file removal out from under a timing-sensitive run.
    with host_phase_hold("publication"):
        with _spool_write_lock(queue_dir):
            return _cleanup_spool_locked(queue_dir)


def _cleanup_spool_locked(queue_dir: str) -> CleanupStats:
    stats = CleanupStats(pending_entries_retained=count_pending_entries(queue_dir))

    dead_letter_root = _dead_letter_dir(queue_dir)
    # Explicit cleanup may delete terminal media, but must not erase the verdict.
    for old in Path(dead_letter_root).glob("*.json"):
        local_hash = old.stem.rsplit("-", 1)[-1]
        if len(local_hash) == 64 and all(c in "0123456789abcdef" for c in local_hash):
            _terminal_spool_entry_locked(queue_dir, local_hash)
    for path in _iter_files(dead_letter_root):
        try:
            file_size = int(os.path.getsize(path))
        except Exception:
            file_size = 0
        try:
            os.remove(path)
            stats.removed_dead_letter_files += 1
            stats.removed_dead_letter_bytes += file_size
        except Exception:
            continue
    for dirpath, dirnames, _filenames in os.walk(dead_letter_root, topdown=False):
        for dirname in dirnames:
            candidate = os.path.join(dirpath, dirname)
            try:
                os.rmdir(candidate)
            except Exception:
                pass
    try:
        os.rmdir(dead_letter_root)
    except Exception:
        pass

    managed_root = _managed_artifact_dir(queue_dir)
    for path in _iter_files(managed_root):
        if _managed_artifact_is_referenced(queue_dir, path):
            continue
        try:
            file_size = int(os.path.getsize(path))
        except Exception:
            file_size = 0
        try:
            os.remove(path)
            stats.removed_orphaned_managed_artifacts += 1
            stats.removed_orphaned_managed_artifact_bytes += file_size
        except Exception:
            continue
    for dirpath, dirnames, _filenames in os.walk(managed_root, topdown=False):
        for dirname in dirnames:
            candidate = os.path.join(dirpath, dirname)
            try:
                os.rmdir(candidate)
            except Exception:
                pass
    try:
        os.rmdir(managed_root)
    except Exception:
        pass

    return stats


def _write_json_atomic(path: str, payload: Dict[str, Any]) -> None:
    from .campaign import atomic_json
    atomic_json(Path(path), payload)


def _envelope_for_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    now = int(time.time())
    return {
        "version": SPOOL_VERSION,
        "localHash": local_hash_for_payload(payload),
        "payload": dict(payload),
        "queuedAt": now,
        "retryDeadlineAt": now + 7 * 24 * 3600,
        "nextAttemptAt": now,
        "attempts": 0,
        "lastAttemptAt": None,
        "lastError": "",
    }


def _managed_artifact_path(queue_dir: str, artifact_sha256: str, source_path: str) -> str:
    ext = os.path.splitext(source_path)[1] or ".bin"
    return os.path.join(_managed_artifact_dir(queue_dir), f"{artifact_sha256}{ext.lower()}")


def _admission_guard(cancel_event: Optional[Any], deadline: Optional[float],
                     phase: str) -> None:
    """R03: cooperative cancel + real caller deadline between blocking local
    steps (capacity scan, artifact staging copy, replay hashing)."""
    if _event_cancelled(cancel_event):
        raise SubmissionCancelled(phase)
    if deadline is not None and time.monotonic() >= deadline:
        raise SubmitError(f"{phase} exceeded caller deadline", retryable=True)


def spool_payload(queue_dir: str, payload: Dict[str, Any], *, max_storage_mb: int = 2048,
                  cancel_event: Optional[Any] = None,
                  deadline: Optional[float] = None) -> Tuple[str, Dict[str, Any]]:
    _admission_guard(cancel_event, deadline, "queue admission")
    try:
        with host_phase_hold("publication"):
            _refuse_publication_during_measurement(queue_dir)
            with _spool_write_lock(queue_dir):
                return _spool_payload_locked(queue_dir, payload, max_storage_mb=max_storage_mb,
                                             cancel_event=cancel_event, deadline=deadline)
    except OSError as exc:
        if exc.errno in (errno.ENOSPC, errno.EDQUOT):
            raise SpoolCapacityError("Publication ran out of disk space; free space and resume the retained campaign") from exc
        raise


def _preserve_artifact_for_spool(queue_dir: str, payload: Dict[str, Any], *,
                                 cancel_event: Optional[Any] = None,
                                 deadline: Optional[float] = None) -> Dict[str, Any]:
    if payload.get("submissionKind") != AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND:
        return dict(payload)
    artifact_path = str(payload.get("artifactPath") or "").strip()
    artifact_sha256 = str(payload.get("artifactSha256") or "").strip().lower()
    if not artifact_path or not artifact_sha256 or not os.path.exists(artifact_path):
        return dict(payload)
    destination = _managed_artifact_path(queue_dir, artifact_sha256, artifact_path)
    resolved_source = os.path.realpath(artifact_path)
    resolved_destination = os.path.realpath(destination)
    if resolved_source != resolved_destination:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        if not os.path.exists(destination):
            tmp_path = f"{destination}.tmp-{os.getpid()}-{int(time.time() * 1000)}"
            try:
                expected_size = int(payload.get("artifactByteSize", -1))
                if expected_size < 0 or os.path.getsize(artifact_path) != expected_size:
                    raise ValueError("Retained artifact size differs from immutable upload metadata")
                copied = 0
                with open(artifact_path, "rb") as source, open(tmp_path, "xb") as target:
                    while True:
                        _admission_guard(cancel_event, deadline, "artifact staging")
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        copied += len(chunk)
                        if copied > expected_size:
                            raise ValueError("Retained artifact grew during bounded upload staging")
                        target.write(chunk)
                if copied != expected_size:
                    raise ValueError("Retained artifact shrank during upload staging")
                shutil.copystat(artifact_path, tmp_path)
                from .campaign import sync_owned_file
                sync_owned_file(tmp_path)
                os.replace(tmp_path, destination)
            finally:
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass
    updated = dict(payload)
    updated["artifactPath"] = destination
    updated["artifactManaged"] = True
    return updated


def terminal_spool_entry(queue_dir: str, local_hash: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    with _spool_write_lock(queue_dir):
        return _terminal_spool_entry_locked(queue_dir, local_hash)


def _terminal_spool_entry_locked(queue_dir: str, local_hash: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Durable terminal identity; legacy dead letters are indexed before reuse."""
    path = os.path.join(queue_dir, "terminal", f"{local_hash}.json")
    if os.path.isfile(path):
        return path, json.loads(Path(path).read_text())
    for old in sorted(Path(_dead_letter_dir(queue_dir)).glob(f"*-{local_hash}.json")):
        try:
            entry = json.loads(old.read_text())
        except (OSError, ValueError):
            entry = {"lastError": "corrupt_legacy_dead_letter"}
        if not isinstance(entry, dict):
            entry = {"lastError": "corrupt_legacy_dead_letter"}
        entry.update(terminal=True, localHash=local_hash, deadLetterPath=str(old))
        _write_json_atomic(path, entry)
        return path, entry
    return None




def _spool_payload_locked(queue_dir: str, payload: Dict[str, Any], *, max_storage_mb: int,
                          cancel_event: Optional[Any] = None,
                          deadline: Optional[float] = None) -> Tuple[str, Dict[str, Any]]:
    local_hash = local_hash_for_payload(payload)
    receipt_path = os.path.join(queue_dir, "receipts", f"{local_hash}.json")
    if os.path.isfile(receipt_path):
        # F4: only a VERIFIED receipt may short-circuit admission. An
        # unverified one is retained as evidence while the real pending entry
        # (re)forms so replay reconciles the same localHash idempotently.
        if receipt_verdict(receipt_path, payload).startswith("verified"):
            return receipt_path, _envelope_for_payload(payload)
        queue_path = _queue_path(queue_dir, local_hash)
        if os.path.isfile(queue_path):
            try:
                return queue_path, load_spool_entry(queue_path)
            except Exception:
                pass
    terminal = _terminal_spool_entry_locked(queue_dir, local_hash)
    if terminal is not None:
        return terminal
    path = _queue_path(queue_dir, local_hash)
    if os.path.exists(path):
        try:
            return path, load_spool_entry(path)
        except Exception:
            _move_to_dead_letter_locked(queue_dir, path, None, "corrupt_existing_spool")
            terminal = _terminal_spool_entry_locked(queue_dir, local_hash)
            if terminal is None:
                raise ValueError("Corrupt upload could not retain terminal identity")
            return terminal
    _check_spool_capacity(queue_dir, payload, max_storage_mb)
    _admission_guard(cancel_event, deadline, "queue admission")
    spool_payload_value = _preserve_artifact_for_spool(queue_dir, payload,
                                                       cancel_event=cancel_event,
                                                       deadline=deadline)
    envelope = _envelope_for_payload(spool_payload_value)
    _write_json_atomic(path, envelope)
    return path, envelope


def load_spool_entry(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    if not isinstance(raw, dict):
        raise ValueError("spool entry must be a JSON object")
    if "payload" in raw:
        payload = raw.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("spool payload must be a JSON object")
        return {
            "version": int(raw.get("version") or 0),
            "localHash": str(raw.get("localHash") or local_hash_for_payload(payload)),
            "payload": payload,
            "queuedAt": int(raw.get("queuedAt") or int(time.time())),
            "attempts": int(raw.get("attempts") or 0),
            "lastAttemptAt": raw.get("lastAttemptAt"),
            "lastError": str(raw.get("lastError") or ""),
            "retryDeadlineAt": raw.get("retryDeadlineAt", int(raw.get("queuedAt") or time.time()) + 7 * 24 * 3600),
            "nextAttemptAt": raw.get("nextAttemptAt", 0),
        }
    # Legacy queue file: raw payload only.
    return {
        "version": 0,
        "localHash": local_hash_for_payload(raw),
        "payload": raw,
        "queuedAt": int(time.time()),
        "attempts": 0,
        "lastAttemptAt": None,
        "lastError": "",
    }


def _update_entry_for_attempt(entry: Dict[str, Any], *, error: str = "") -> Dict[str, Any]:
    updated = dict(entry)
    updated["attempts"] = int(updated.get("attempts") or 0) + 1
    updated["lastAttemptAt"] = int(time.time())
    updated["lastError"] = error[:500] if error else ""
    return updated


def move_to_dead_letter(
    queue_dir: str,
    source_path: str,
    entry: Optional[Dict[str, Any]],
    reason: str,
) -> Tuple[str, Dict[str, Any]]:
    with _spool_write_lock(queue_dir):
        return _move_to_dead_letter_locked(queue_dir, source_path, entry, reason)


def _move_to_dead_letter_locked(
    queue_dir: str,
    source_path: str,
    entry: Optional[Dict[str, Any]],
    reason: str,
) -> Tuple[str, Dict[str, Any]]:
    os.makedirs(_dead_letter_dir(queue_dir), exist_ok=True)
    basename = os.path.basename(source_path)
    dead_name = f"{int(time.time() * 1000)}-{basename}"
    dead_path = os.path.join(_dead_letter_dir(queue_dir), dead_name)
    # Commit terminal identity BEFORE moving evidence or deleting the active item.
    # A crash in either operation must not make resume assign a fresh deadline.
    local_hash = str((entry or {}).get("localHash") or Path(basename).stem)
    if len(local_hash) == 64 and all(c in "0123456789abcdef" for c in local_hash):
        terminal = _terminal_spool_entry_locked(queue_dir, local_hash)
        if terminal is None:
            terminal_value = dict(entry or {})
            terminal_value.update(terminal=True, localHash=local_hash, lastError=reason[:500],
                                  terminalAt=time.time(), deadLetterPath=dead_path)
            _write_json_atomic(os.path.join(queue_dir, "terminal", f"{local_hash}.json"), terminal_value)
        else:
            dead_path = terminal[1].get("deadLetterPath") or dead_path
    if entry is None:
        try:
            os.replace(source_path, dead_path)
            return dead_path, {"lastError": reason}
        except Exception:
            _write_json_atomic(dead_path, {"version": SPOOL_VERSION, "lastError": reason})
            try:
                if os.path.exists(source_path):
                    os.remove(source_path)
            except Exception:
                pass
            return dead_path, {"lastError": reason}
    updated = _update_entry_for_attempt(entry, error=reason)
    updated = _move_managed_artifact_to_dead_letter(queue_dir, source_path, updated)
    _write_json_atomic(dead_path, updated)
    try:
        if os.path.exists(source_path):
            os.remove(source_path)
    except Exception:
        pass
    return dead_path, updated


def _entry_artifact_path(entry: Dict[str, Any]) -> Optional[str]:
    payload = entry.get("payload")
    if not isinstance(payload, dict):
        return None
    artifact_path = str(payload.get("artifactPath") or "").strip()
    return artifact_path or None


def _is_managed_artifact_path(queue_dir: str, artifact_path: str) -> bool:
    try:
        managed_root = os.path.realpath(_managed_artifact_dir(queue_dir))
        candidate = os.path.realpath(artifact_path)
        common = os.path.commonpath([managed_root, candidate])
    except Exception:
        return False
    return common == managed_root


def _validate_managed_artifact_for_replay(queue_dir: str, payload: Dict[str, Any], *,
                                          cancel_event: Optional[Any] = None,
                                          deadline: Optional[float] = None) -> None:
    artifact_path = str(payload.get("artifactPath") or "").strip()
    if not artifact_path or not _is_managed_artifact_path(queue_dir, artifact_path):
        raise SubmitError("spooled artifact path is outside the managed queue", retryable=False)
    if os.path.islink(artifact_path) or not os.path.isfile(artifact_path):
        raise SubmitError("spooled artifact must be a regular managed file", retryable=False)
    expected_hash = str(payload.get("artifactSha256") or "").strip().lower()
    expected_size = int(payload.get("artifactByteSize") or -1)
    digest = hashlib.sha256()
    observed_size = 0
    with open(artifact_path, "rb") as handle:
        while True:
            # R03: replay hashing can run over multi-GB artifacts; check
            # cancel/deadline between chunks so a Stop does not wait for the
            # full hash. Raised errors are retryable -> entry is retained.
            _admission_guard(cancel_event, deadline, "replay artifact validation")
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            observed_size += len(chunk)
            digest.update(chunk)
    if observed_size != expected_size or digest.hexdigest() != expected_hash:
        raise SubmitError("spooled artifact hash or size no longer matches immutable metadata", retryable=False)


def _move_managed_artifact_to_dead_letter(queue_dir: str, source_entry_path: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    artifact_path = _entry_artifact_path(entry)
    if not artifact_path or not _is_managed_artifact_path(queue_dir, artifact_path):
        return entry
    if _managed_artifact_is_referenced(queue_dir, artifact_path, excluding_entry_path=source_entry_path):
        return entry
    dead_artifact_dir = os.path.join(_dead_letter_dir(queue_dir), MANAGED_ARTIFACT_DIRNAME)
    destination = os.path.join(dead_artifact_dir, os.path.basename(artifact_path))
    if os.path.exists(artifact_path):
        os.makedirs(dead_artifact_dir, exist_ok=True)
        try:
            os.replace(artifact_path, destination)
        except Exception:
            return entry
    elif not os.path.exists(destination):
        return entry
    # Recover a crash after the artifact rename but before its JSON receipt commit.
    payload = dict(entry.get("payload") or {})
    payload["artifactPath"] = destination
    updated = dict(entry)
    updated["payload"] = payload
    return updated


def _managed_artifact_is_referenced(queue_dir: str, artifact_path: str, *, excluding_entry_path: Optional[str] = None) -> bool:
    target = os.path.realpath(artifact_path)
    try:
        names = os.listdir(queue_dir)
    except Exception:
        return False
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(queue_dir, name)
        if excluding_entry_path and os.path.realpath(path) == os.path.realpath(excluding_entry_path):
            continue
        if not os.path.isfile(path):
            continue
        try:
            entry = load_spool_entry(path)
        except Exception:
            continue
        candidate = _entry_artifact_path(entry)
        if candidate and os.path.exists(candidate) and os.path.realpath(candidate) == target:
            return True
    return False


def _cleanup_managed_artifact_if_unreferenced(queue_dir: str, entry: Dict[str, Any], *, excluding_entry_path: Optional[str] = None) -> None:
    artifact_path = _entry_artifact_path(entry)
    if not artifact_path or not os.path.exists(artifact_path) or not _is_managed_artifact_path(queue_dir, artifact_path):
        return
    if _managed_artifact_is_referenced(queue_dir, artifact_path, excluding_entry_path=excluding_entry_path):
        return
    try:
        os.remove(artifact_path)
    except Exception:
        pass


def _retain_entry(path: str, entry: Dict[str, Any], error: str, retry_after: float = 0.0) -> None:
    updated = _update_entry_for_attempt(entry, error=error)
    delay = max(retry_after, min(3600.0, 2 ** min(updated["attempts"], 12)) * random.uniform(0.75, 1.25))
    updated["nextAttemptAt"] = max(float(entry.get("nextAttemptAt") or 0), time.time() + delay)
    _write_json_atomic(path, updated)


def _submission_success_message(payload: Dict[str, Any], response: Any) -> str:
    if payload.get("submissionKind") != AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND:
        return ""
    if isinstance(response, dict):
        benchmark_run = response.get("benchmarkRun")
        if isinstance(benchmark_run, dict):
            run_id = str(benchmark_run.get("id") or "").strip()
            if run_id:
                return run_id
    return ""


def _load_receipt(receipt_path: str) -> Optional[Any]:
    try:
        return json.loads(Path(receipt_path).read_text())
    except (OSError, ValueError):
        return None


def receipt_verdict(receipt_path: str, payload: Optional[Dict[str, Any]]) -> str:
    """F4: classify a durable receipt against the payload it claims to cover.

    ``verified`` is returned only when the receipt rebinds the queue's
    localHash AND the server response proves the run/artifact identity for
    that payload together with the receipt's own persisted bound
    acknowledgment (or is a faithful legacy ingest receipt with no response
    body). Everything else is ``unverified:<why>`` / ``orphan:<why>`` and
    authorizes nothing.
    """
    receipt = _load_receipt(receipt_path)
    return acknowledgments.receipt_verdict(Path(receipt_path).stem, receipt, payload)


def _envelope_payload_for(queue_dir: str, local_hash: str) -> Optional[Dict[str, Any]]:
    """The saved campaign envelope whose canonical local identity is this
    hash, when one exists. Historical/retired receipts reconcile against
    this immutable identity instead of trusting response bytes payload-free.
    """
    try:
        campaigns = Path(queue_dir) / "campaigns"
        for envelope_file in sorted(campaigns.glob("*/submission-*.json")):
            if envelope_file.name.endswith(".accepted.json"):
                continue
            try:
                envelope = json.loads(envelope_file.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(envelope, dict) and acknowledgments.local_payload_hash(envelope) == local_hash:
                return envelope
    except OSError:
        return None
    return None


def verified_receipt_evidence(queue_dir: str, local_hash: str,
                              payload: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Bound acknowledgment evidence of a verified receipt, else None.

    Only the receipt's own persisted acknowledgment (cross-checked against
    its embedded response) qualifies; a response without that proof is
    never trusted payload-free.
    """
    receipt_path = os.path.join(queue_dir, "receipts", f"{local_hash}.json")
    if not os.path.isfile(receipt_path):
        return None
    pending_path = os.path.join(queue_dir, f"{local_hash}.json")
    if payload is None and os.path.isfile(pending_path):
        try:
            payload = load_spool_entry(pending_path).get("payload")
        except Exception:
            payload = None
    if payload is None:
        payload = _envelope_payload_for(queue_dir, local_hash)
    if not receipt_verdict(receipt_path, payload).startswith("verified"):
        return None
    receipt = _load_receipt(receipt_path) or {}
    acknowledgment = receipt.get("acknowledgment")
    if isinstance(acknowledgment, dict) and acknowledgments.validate_acknowledgment(
            acknowledgment, payload=payload or receipt.get("payloadIdentity"),
            response=receipt.get("response")):
        return acknowledgment
    return None


def receipt_reconciliation_state(queue_dir: str) -> List[Dict[str, Any]]:
    """Receipts that cannot prove acknowledgment: actionable repair state.

    Pending entries and managed artifacts behind these receipts are retained
    with stable IDs; replay supersedes them idempotently once the server
    re-acknowledges the same payloadHash. Nothing here deletes evidence.
    """
    items: List[Dict[str, Any]] = []
    receipts_dir = Path(queue_dir) / "receipts"
    try:
        files = sorted(receipts_dir.glob("*.json"))
    except OSError:
        return items
    for receipt_file in files:
        payload: Optional[Dict[str, Any]] = None
        pending_path = Path(queue_dir) / receipt_file.name
        if pending_path.is_file():
            try:
                payload = load_spool_entry(str(pending_path)).get("payload")
            except Exception:
                payload = None
        verdict = receipt_verdict(str(receipt_file), payload)
        if not verdict.startswith("verified"):
            items.append({"path": str(receipt_file), "localHash": receipt_file.stem,
                          "verdict": verdict})
    return items


def _journal_self_publish(queue_dir: str, payload: Dict[str, Any], response: Any) -> None:
    """Commit journal acceptance evidence for a completed queue upload (C11).

    A checkpoint upload that finishes outside a live batch (standalone replay,
    --upload-only, GUI retry) must still write the campaign journal's own receipt
    and retire the owned artifact, so a crash between server acceptance and
    journal commit cannot resurrect an uploaded group for re-encode or re-upload.
    Without a server run id nothing is treated as accepted; an existing faithful
    receipt simply wins (idempotent replay)."""
    if payload.get("submissionKind") != AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND:
        return
    acknowledgment = acknowledgments.validate_upload_response(payload, response)
    if acknowledgment is None:
        return
    run_id = acknowledgment["benchmarkRunId"]
    local_hash = local_hash_for_payload(payload)
    campaigns = Path(queue_dir) / "campaigns"
    run_create = payload.get("runCreate") if isinstance(payload.get("runCreate"), dict) else {}
    scoped = str(run_create.get("campaignId") or "")
    try:
        # The payload carries its campaign identity; scope the faithful-identity scan
        # to that journal instead of parsing every campaign's submissions.
        if scoped and (campaigns / scoped).is_dir():
            candidates = sorted((campaigns / scoped).glob("submission-*.json"))
        else:
            candidates = sorted(campaigns.glob("*/submission-*.json"))
    except OSError:
        return
    for candidate in candidates:
        if candidate.name.endswith(".accepted.json"):
            continue
        try:
            journal_payload = json.loads(candidate.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(journal_payload, dict) or local_hash_for_payload(journal_payload) != local_hash:
            continue
        run_create = journal_payload.get("runCreate")
        repetition_group = str((run_create or {}).get("repetitionGroupId") or "") if isinstance(run_create, dict) else ""
        artifact_path = str(journal_payload.get("artifactPath") or "").strip()
        artifact_sha = str(journal_payload.get("artifactSha256") or "").strip()
        try:
            order_value = int(candidate.stem.split("-", 1)[1])
        except (ValueError, IndexError):
            continue
        if (not artifact_path or not artifact_sha or ":" not in repetition_group
                or str((run_create or {}).get("campaignId") or "") != candidate.parent.name):
            continue
        marker_path = candidate.with_name(f"submission-{order_value:06d}.accepted.json")
        receipt_payload_hash = acknowledgment["payloadHash"]
        marker = {"schemaVersion": 2,
                  "executionOrder": order_value,
                  "recipeId": repetition_group.split(":", 1)[1],
                  "artifactPath": artifact_path,
                  "artifactSha256": artifact_sha,
                  "benchmarkRunId": run_id,
                  "payloadHash": receipt_payload_hash,
                  "artifactId": acknowledgment["artifactId"],
                  "artifactByteSize": acknowledgment["artifactByteSize"],
                  "uploadConfirmed": True,
                  "analysisAccepted": acknowledgment["analysisAccepted"],
                  "acknowledgment": acknowledgment, "response": response,
                  "acceptedAt": time.time()}
        prior_bytes = None
        if marker_path.is_file():
            try:
                prior_bytes = marker_path.read_text()
                prior = json.loads(prior_bytes)
            except (OSError, ValueError):
                prior = None
            if acknowledgments.journal_marker_verdict(
                    prior, execution_order=order_value,
                    recipe_id=repetition_group.split(":", 1)[1],
                    artifact_path=artifact_path, artifact_sha256=artifact_sha,
                    payload_hash=receipt_payload_hash, payload=journal_payload) == "verified" \
                    and str((prior or {}).get("benchmarkRunId") or "") == run_id:
                marker = prior  # faithful receipt already wins; never rewrite
            elif prior_bytes is not None:
                # Corrupt/unrelated marker: supersede with proof, keep evidence.
                marker["superseded"] = {"priorEvidence": prior_bytes}
        _write_json_atomic(str(marker_path), marker)
        owned = Path(artifact_path).resolve()
        if candidate.parent.resolve() in owned.parents and owned.is_file():
            try:
                owned.unlink()
            except OSError:
                pass
        return


def drain_committed_receipts(queue_dir: str) -> int:
    """Retire pending entries whose VERIFIED acceptance receipt is committed (C10/F4).

    A crash between receipt commit and entry unlink leaves both files; a
    receipt that provably binds the server run/artifact identity to this
    payload is terminal evidence, so the entry (and its managed staging copy)
    must drain BEFORE new staging consumes the storage budget. Journal
    self-publish runs here too, covering a crash inside the other process.
    F4: an unverified receipt (malformed, empty, wrong local identity, or an
    acknowledgment for unrelated bytes) authorizes NOTHING - the pending
    entry, managed artifact and the corrupt receipt evidence all survive with
    stable IDs so replay can reconcile idempotently."""
    drained = 0
    with _spool_write_lock(queue_dir):
        try:
            names = os.listdir(queue_dir)
        except OSError:
            return 0
        for name in names:
            if not name.endswith(".json") or not os.path.isfile(os.path.join(queue_dir, name)):
                continue
            receipt_path = os.path.join(queue_dir, "receipts", name)
            if not os.path.isfile(receipt_path):
                continue
            path = os.path.join(queue_dir, name)
            try:
                entry = load_spool_entry(path)
            except Exception:
                entry = None
            if entry is None:
                continue
            payload = entry.get("payload")
            if not receipt_verdict(receipt_path, payload).startswith("verified"):
                continue  # retain everything; reconciliation state reports this
            if entry is not None:
                receipt = _load_receipt(receipt_path) or {}
                _journal_self_publish(queue_dir, payload or {}, receipt.get("response"))
                _cleanup_managed_artifact_if_unreferenced(queue_dir, entry, excluding_entry_path=path)
            try:
                os.remove(path)
                drained += 1
            except OSError:
                pass
    return drained


def campaign_queue_summary(queue_dir: str, campaign_id: str) -> Dict[str, Any]:
    """Reconciled publication counters for ONE campaign across queue+receipts+terminal.

    Counts entries by durable identity: pending staging, accepted receipts,
    terminal dead letters. Measurement counters live in the journal; this view
    shows what publication actually holds for the campaign right now."""
    summary = {"pendingEntries": 0, "pendingBytes": 0, "dueEntries": 0, "acceptedReceipts": 0,
               "unverifiedReceipts": 0, "terminalEntries": 0, "nextAttemptAt": None}
    now = time.time()
    def belongs(payload: Any) -> bool:
        run_create = payload.get("runCreate") if isinstance(payload, dict) else None
        return isinstance(run_create, dict) and str(run_create.get("campaignId") or "") == campaign_id
    try:
        names = sorted(os.listdir(queue_dir))
    except OSError:
        return summary
    for name in names:
        path = os.path.join(queue_dir, name)
        if not name.endswith(".json") or not os.path.isfile(path):
            continue
        try:
            entry = load_spool_entry(path)
        except Exception:
            continue
        if not belongs(entry.get("payload")):
            continue
        summary["pendingEntries"] += 1
        summary["pendingBytes"] += os.path.getsize(path)
        if float(entry.get("nextAttemptAt") or 0) <= now:
            summary["dueEntries"] += 1
        else:
            next_at = float(entry.get("nextAttemptAt") or 0)
            if summary["nextAttemptAt"] is None or next_at < summary["nextAttemptAt"]:
                summary["nextAttemptAt"] = next_at
    receipts = Path(queue_dir) / "receipts"
    envelopes: Dict[str, Dict[str, Any]] = {}
    try:
        for envelope_file in sorted((Path(queue_dir) / "campaigns" / campaign_id)
                                    .glob("submission-*.json")):
            if envelope_file.name.endswith(".accepted.json"):
                continue
            try:
                envelope = json.loads(envelope_file.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(envelope, dict):
                try:
                    envelopes[local_hash_for_payload(envelope)] = envelope
                except Exception:
                    continue
    except OSError:
        envelopes = {}
    try:
        for receipt_file in sorted(receipts.glob("*.json")):
            # F4: bind to this campaign's envelope when one exists; otherwise
            # only internal self-consistency is provable. Unverified receipts
            # are repair work, never acceptance.
            if receipt_file.stem not in envelopes:
                continue
            verdict = receipt_verdict(str(receipt_file), envelopes[receipt_file.stem])
            if verdict.startswith("verified"):
                summary["acceptedReceipts"] += 1
            else:
                summary["unverifiedReceipts"] += 1
    except OSError:
        pass
    terminal_dir = Path(queue_dir) / "terminal"
    try:
        for terminal_file in sorted(terminal_dir.glob("*.json")):
            try:
                terminal = json.loads(terminal_file.read_text())
            except (OSError, ValueError):
                continue
            if belongs((terminal or {}).get("payload")):
                summary["terminalEntries"] += 1
    except OSError:
        pass
    return summary


def _receipt_matches_campaign(queue_dir: str, local_hash: str, campaign_id: str) -> bool:
    """A queue receipt names only its hash; the journal holds the campaign link."""
    root = Path(queue_dir) / "campaigns" / campaign_id
    if not root.is_dir():
        return False
    for submission in root.glob("submission-*.json"):
        if submission.name.endswith(".accepted.json"):
            continue
        try:
            payload = json.loads(submission.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict) and local_hash_for_payload(payload) == local_hash:
            return True
    return False


def queue_recovery_summary(queue_dir: str) -> Dict[str, Any]:
    """Read-only queue-wide publication view for status/recovery projection (C06)."""
    summary = {"pendingEntries": 0, "pendingBytes": 0, "dueEntries": 0, "acceptedReceipts": 0,
               "unverifiedReceipts": 0, "terminalEntries": 0, "nextAttemptAt": None}
    now = time.time()
    try:
        names = sorted(os.listdir(queue_dir))
    except OSError:
        names = []
    for name in names:
        path = os.path.join(queue_dir, name)
        if not name.endswith(".json") or not os.path.isfile(path):
            continue
        summary["pendingEntries"] += 1
        try:
            summary["pendingBytes"] += os.path.getsize(path)
        except OSError:
            pass
        try:
            entry = load_spool_entry(path)
            next_at = float(entry.get("nextAttemptAt") or 0)
        except Exception:
            continue
        if next_at <= now:
            summary["dueEntries"] += 1
        elif summary["nextAttemptAt"] is None or next_at < summary["nextAttemptAt"]:
            summary["nextAttemptAt"] = next_at
    try:
        for receipt_file in sorted((Path(queue_dir) / "receipts").glob("*.json")):
            payload: Optional[Dict[str, Any]] = None
            pending_path = Path(queue_dir) / receipt_file.name
            if pending_path.is_file():
                try:
                    payload = load_spool_entry(str(pending_path)).get("payload")
                except Exception:
                    payload = None
            if receipt_verdict(str(receipt_file), payload).startswith("verified"):
                summary["acceptedReceipts"] += 1
            else:
                summary["unverifiedReceipts"] += 1
    except OSError:
        pass
    try:
        summary["terminalEntries"] = sum(1 for f in (Path(queue_dir) / "terminal").glob("*.json") if f.is_file())
    except OSError:
        pass
    return summary


def _current_spooled_entry_locked(path: str, queue_dir: str):
    # A different replay may have finished while our network transaction was in
    # progress. Its receipt/terminal verdict wins; never recreate stale entries.
    receipt_path = os.path.join(queue_dir, "receipts", os.path.basename(path))
    if os.path.isfile(receipt_path):
        pending_path = _queue_path(queue_dir, Path(path).stem)
        pending: Optional[Dict[str, Any]] = None
        if os.path.isfile(pending_path):
            try:
                pending = load_spool_entry(pending_path)
            except ValueError:
                pending = None
        verdict = receipt_verdict(receipt_path, (pending or {}).get("payload"))
        if not verdict.startswith("verified"):
            # F4: a corrupt/mismatched receipt never claims this transaction
            # complete. Retain the pending entry (stable IDs) and fall
            # through: the caller re-attempts the transport, which supersedes
            # the bad receipt idempotently with a verified one.
            try:
                return load_spool_entry(path), None
            except Exception as exc:
                _move_to_dead_letter_locked(queue_dir, path, None, f"corrupt_spool:{exc}")
                return None, ("corrupt", str(exc))
        receipt = _load_receipt(receipt_path) or {}
        if pending is not None:
            # Crash recovery (C11): the other process committed the receipt but may
            # have died before publishing journal acceptance. Replay the journal
            # receipt from the still-pending payload before releasing its bytes.
            _journal_self_publish(queue_dir, pending.get("payload") or {}, receipt.get("response"))
            _cleanup_managed_artifact_if_unreferenced(queue_dir, pending, excluding_entry_path=pending_path)
        if os.path.isfile(pending_path):
            os.remove(pending_path)
        return None, ("submitted", _submission_success_message(
            {"submissionKind": AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND}, receipt.get("response")))
    terminal = _terminal_spool_entry_locked(queue_dir, Path(path).stem)
    if terminal is not None:
        reason = str(terminal[1].get("lastError") or "terminal_upload")
        if os.path.dirname(os.path.abspath(path)) == os.path.abspath(queue_dir) and os.path.exists(path):
            try:
                entry = load_spool_entry(path)
            except (OSError, ValueError):
                entry = None
            _move_to_dead_letter_locked(queue_dir, path, entry, reason)
        return None, ("dead_lettered", reason)
    if not os.path.exists(path):
        return None, ("retained", "spool_entry_no_longer_pending")
    try:
        return load_spool_entry(path), None
    except Exception as exc:
        _move_to_dead_letter_locked(queue_dir, path, None, f"corrupt_spool:{exc}")
        return None, ("corrupt", str(exc))


def submit_spooled_path(
    path: str,
    *,
    queue_dir: str,
    base_url: str,
    api_key: str,
    retries: int,
    use_token: bool,
    cancel_event: Optional[Any] = None,
    deadline: Optional[float] = None,
) -> Tuple[str, str]:
    # C11: the whole network transaction must live inside the host publication
    # phase; otherwise a collector could start mid-upload through the very disk
    # and network path the upload is saturating. In-process re-entry (a
    # collector's checkpoint upload, or replay_spool's pass-level hold) is free.
    # R03: `deadline` (monotonic) is a real caller deadline honoured before any
    # I/O and through every transport phase; R05: the hold reaps (or defers
    # around) any worker this transaction leaves behind.
    with host_phase_hold("publication"):
        return _submit_spooled_path_unheld(
            path, queue_dir=queue_dir, base_url=base_url, api_key=api_key,
            retries=retries, use_token=use_token, cancel_event=cancel_event,
            deadline=deadline)


def _submit_spooled_path_unheld(
    path: str,
    *,
    queue_dir: str,
    base_url: str,
    api_key: str,
    retries: int,
    use_token: bool,
    cancel_event: Optional[Any] = None,
    deadline: Optional[float] = None,
) -> Tuple[str, str]:
    try:
        with _spool_write_lock(queue_dir):
            entry, outcome = _current_spooled_entry_locked(path, queue_dir)
            if outcome is not None:
                return outcome
            if time.time() >= entry.get("retryDeadlineAt", float("inf")):
                _move_to_dead_letter_locked(queue_dir, path, entry, "retry_deadline_expired")
                return "dead_lettered", "retry_deadline_expired"
            if time.time() < entry.get("nextAttemptAt", 0):
                return "retained", "retry_backoff_pending"
            payload = entry["payload"]
            if payload.get("submissionKind") == AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND:
                artifact_path = str(payload.get("artifactPath") or "").strip()
                if not artifact_path or not os.path.exists(artifact_path):
                    _move_to_dead_letter_locked(queue_dir, path, entry, "missing_spooled_artifact")
                    return "dead_lettered", "missing_spooled_artifact"
                try:
                    _validate_managed_artifact_for_replay(queue_dir, payload,
                                                          cancel_event=cancel_event,
                                                          deadline=deadline)
                except SubmitError as exc:
                    if exc.retryable:
                        # R03: cancel/deadline interrupted replay hashing —
                        # retain with identity intact, perform no network I/O.
                        _retain_entry(path, entry, str(exc))
                        return "retained", str(exc)
                    _move_to_dead_letter_locked(queue_dir, path, entry, str(exc))
                    return "dead_lettered", str(exc)
                except Exception as exc:
                    _retain_entry(path, entry, str(exc))
                    return "retained", str(exc)
        # The pending entry remains a managed-artifact reference. Network calls
        # hold no queue lock, so other admissions and cleanup remain responsive.
        response: Any = None
        error: Optional[Exception] = None
        try:
            if deadline is not None and time.monotonic() >= deadline:
                raise SubmitError("spool transport deadline reached before network",
                                  retryable=True)
            if _event_cancelled(cancel_event):
                raise SubmissionCancelled("spool transport")
            if payload.get("submissionKind") == AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND:
                response = submit_artifact_submission(base_url, payload, retries=retries,
                                                      cancel_event=cancel_event,
                                                      deadline=deadline)
            else:
                submit(base_url, payload, api_key=api_key, retries=retries, use_token=use_token,
                       cancel_event=cancel_event, deadline=deadline)
        except Exception as exc:
            error = exc
        with _spool_write_lock(queue_dir):
            entry, outcome = _current_spooled_entry_locked(path, queue_dir)
            if outcome is not None:
                return outcome
            if error is not None:
                if isinstance(error, SubmitError) and not error.retryable:
                    _move_to_dead_letter_locked(queue_dir, path, entry, str(error))
                    return "dead_lettered", str(error)
                _retain_entry(path, entry, str(error), getattr(error, "retry_after", 0.0))
                return "retained", str(error)
            acknowledgment: Optional[Dict[str, Any]] = None
            if payload.get("submissionKind") == AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND:
                # F4: an HTTP 200 alone never confirms upload. The response
                # must bind this payload's run/artifact identity; anything
                # else ({}, a bare run id, an unrelated acknowledgment)
                # retains the entry with stable IDs for idempotent replay.
                acknowledgment = acknowledgments.validate_upload_response(payload, response)
                if acknowledgment is None:
                    _retain_entry(path, entry,
                                  "unverified server acknowledgment: response does not bind "
                                  "this payload's run/artifact identity")
                    return "retained", ("unverified server acknowledgment for localHash "
                                        f"{entry['localHash']}: entry retained, no retirement")
            receipt_value: Dict[str, Any] = {
                "localHash": entry["localHash"], "uploadedAt": time.time(), "response": response,
                "payloadIdentity": acknowledgments.local_hash_material(payload),
                "status": "uploaded_analysis_pending"}
            if acknowledgment is not None:
                receipt_value["acknowledgment"] = acknowledgment
            stale_path = os.path.join(queue_dir, "receipts", os.path.basename(path))
            if os.path.isfile(stale_path):
                stale = _load_receipt(stale_path)
                if stale is None or not receipt_verdict(stale_path, payload).startswith("verified"):
                    # Never silently destroy corrupt receipt evidence: keep it
                    # inside the superseding verified receipt.
                    receipt_value["superseded"] = {
                        "reason": "unverified-receipt-replaced-by-verified-acknowledgment",
                        "supersededAt": time.time(),
                        "corruptEvidence": (Path(stale_path).read_text(errors="replace")
                                            if os.path.isfile(stale_path) else None)}
            _write_json_atomic(stale_path, receipt_value)
            # Publish journal acceptance while the pending entry still exists: a crash
            # here leaves replayable state (receipt + pending), never a journal that
            # lost its artifact without a receipt.
            _journal_self_publish(queue_dir, payload, response)
            _cleanup_managed_artifact_if_unreferenced(queue_dir, entry, excluding_entry_path=path)
            try:
                os.remove(path)
            except OSError:
                pass
            return "submitted", _submission_success_message(payload, response)
    except OSError as exc:
        # Busy ownership or failed persistence is recoverable. Do not turn a
        # publication race into a terminal rejection or replace retry identity.
        return "retained", str(exc)


def replay_spool(
    queue_dir: str,
    *,
    base_url: str,
    api_key: str,
    retries: int,
    use_token: bool,
    limit: int = REPLAY_WINDOW,
    time_budget: float = REPLAY_SECONDS,
    cancel_event: Optional[Any] = None,
    deadline: Optional[float] = None,
) -> ReplayStats:
    """Bounded, cancellable, due-first replay (C08/C11/C12).

    - The whole pass holds the host publication phase atomically: the probe and
      every upload are one phase, so a collector starting on ANY queue of this
      host cannot slip between them (kernel lock; crash releases).
    - Only entries whose Retry-After has arrived (or whose deadline lapsed) enter
      the window; a failing prefix consumes slots but never blocks later due work.
    - A cancel request stops admission between entries; an in-flight network
      transaction keeps its durable entry, so the ambiguous outcome is retried
      idempotently rather than lost or double-submitted.
    - A measuring collector on this queue defers publication (SpoolCapacityError).
    """
    with host_phase_hold("publication"):
        return _replay_spool_unheld(
            queue_dir, base_url=base_url, api_key=api_key, retries=retries,
            use_token=use_token, limit=limit, time_budget=time_budget,
            cancel_event=cancel_event, deadline=deadline)


def _replay_spool_unheld(
    queue_dir: str,
    *,
    base_url: str,
    api_key: str,
    retries: int,
    use_token: bool,
    limit: int = REPLAY_WINDOW,
    time_budget: float = REPLAY_SECONDS,
    cancel_event: Optional[Any] = None,
    deadline: Optional[float] = None,
) -> ReplayStats:
    stats = ReplayStats()
    _refuse_publication_during_measurement(queue_dir)
    files, deferred = due_first_queue_paths(queue_dir, limit=limit)
    stats.deferred += deferred
    started = time.monotonic()
    for index, path in enumerate(files):
        if _event_cancelled(cancel_event):
            # Reconciled counters (C05): this entry counts once, as cancelled;
            # only the entries behind it count as deferred.
            stats.cancelled += 1
            stats.deferred += len(files) - index - 1
            break
        if deadline is not None and time.monotonic() >= deadline:
            # R03: real caller deadline (monotonic wall-clock), distinct from
            # the per-pass throughput budget below.
            stats.deferred += len(files) - index
            break
        if time.monotonic() - started >= time_budget:
            stats.deferred += len(files) - index
            break
        status, _message = submit_spooled_path(
            path,
            queue_dir=queue_dir,
            base_url=base_url,
            api_key=api_key,
            retries=retries,
            use_token=use_token,
            cancel_event=cancel_event,
            deadline=deadline,
        )
        if status == "submitted":
            stats.submitted += 1
        elif status == "retained":
            stats.retained += 1
        elif status == "dead_lettered":
            stats.dead_lettered += 1
        elif status == "corrupt":
            stats.corrupt += 1
    return stats


def _event_cancelled(cancel_event: Optional[Any]) -> bool:
    if cancel_event is None:
        return False
    try:
        return bool(cancel_event.is_set())
    except Exception:
        return False
