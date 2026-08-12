import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .artifacts import AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND, submit_artifact_submission
from .network import SubmitError, submit

SPOOL_VERSION = 1
MANAGED_ARTIFACT_DIRNAME = "artifacts"


@dataclass
class ReplayStats:
    submitted: int = 0
    retained: int = 0
    dead_lettered: int = 0
    corrupt: int = 0


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
    return hashlib.sha256(_canonical_payload_json(payload).encode("utf-8")).hexdigest()


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
    stats = CleanupStats(pending_entries_retained=count_pending_entries(queue_dir))

    dead_letter_root = _dead_letter_dir(queue_dir)
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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp-{os.getpid()}-{int(time.time() * 1000)}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"), sort_keys=True)
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def _envelope_for_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    now = int(time.time())
    return {
        "version": SPOOL_VERSION,
        "localHash": local_hash_for_payload(payload),
        "payload": dict(payload),
        "queuedAt": now,
        "attempts": 0,
        "lastAttemptAt": None,
        "lastError": "",
    }


def _managed_artifact_path(queue_dir: str, artifact_sha256: str, source_path: str) -> str:
    ext = os.path.splitext(source_path)[1] or ".bin"
    return os.path.join(_managed_artifact_dir(queue_dir), f"{artifact_sha256}{ext.lower()}")


def _preserve_artifact_for_spool(queue_dir: str, payload: Dict[str, Any]) -> Dict[str, Any]:
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
                shutil.copy2(artifact_path, tmp_path)
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


def spool_payload(queue_dir: str, payload: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    spool_payload_value = _preserve_artifact_for_spool(queue_dir, payload)
    envelope = _envelope_for_payload(spool_payload_value)
    path = _queue_path(queue_dir, envelope["localHash"])
    if not os.path.exists(path):
        _write_json_atomic(path, envelope)
        return path, envelope
    try:
        existing = load_spool_entry(path)
        return path, existing
    except Exception:
        dead_letter_path, _ = move_to_dead_letter(queue_dir, path, None, "corrupt_existing_spool")
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
    os.makedirs(_dead_letter_dir(queue_dir), exist_ok=True)
    basename = os.path.basename(source_path)
    dead_name = f"{int(time.time() * 1000)}-{basename}"
    dead_path = os.path.join(_dead_letter_dir(queue_dir), dead_name)
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


def _validate_managed_artifact_for_replay(queue_dir: str, payload: Dict[str, Any]) -> None:
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
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            observed_size += len(chunk)
            digest.update(chunk)
    if observed_size != expected_size or digest.hexdigest() != expected_hash:
        raise SubmitError("spooled artifact hash or size no longer matches immutable metadata", retryable=False)


def _move_managed_artifact_to_dead_letter(queue_dir: str, source_entry_path: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    artifact_path = _entry_artifact_path(entry)
    if not artifact_path or not os.path.exists(artifact_path) or not _is_managed_artifact_path(queue_dir, artifact_path):
        return entry
    if _managed_artifact_is_referenced(queue_dir, artifact_path, excluding_entry_path=source_entry_path):
        return entry
    dead_artifact_dir = os.path.join(_dead_letter_dir(queue_dir), MANAGED_ARTIFACT_DIRNAME)
    os.makedirs(dead_artifact_dir, exist_ok=True)
    destination = os.path.join(dead_artifact_dir, os.path.basename(artifact_path))
    try:
        os.replace(artifact_path, destination)
    except Exception:
        return entry
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


def _retain_entry(path: str, entry: Dict[str, Any], error: str) -> None:
    _write_json_atomic(path, _update_entry_for_attempt(entry, error=error))


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


def submit_spooled_path(
    path: str,
    *,
    queue_dir: str,
    base_url: str,
    api_key: str,
    retries: int,
    use_token: bool,
) -> Tuple[str, str]:
    try:
        entry = load_spool_entry(path)
    except Exception as exc:
        move_to_dead_letter(queue_dir, path, None, f"corrupt_spool:{exc}")
        return "corrupt", str(exc)
    try:
        payload = entry["payload"]
        response: Any = None
        if payload.get("submissionKind") == AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND:
            artifact_path = str(payload.get("artifactPath") or "").strip()
            if not artifact_path or not os.path.exists(artifact_path):
                move_to_dead_letter(queue_dir, path, entry, "missing_spooled_artifact")
                return "dead_lettered", "missing_spooled_artifact"
            _validate_managed_artifact_for_replay(queue_dir, payload)
            response = submit_artifact_submission(
                base_url,
                payload,
                retries=retries,
            )
        else:
            submit(
                base_url,
                payload,
                api_key=api_key,
                retries=retries,
                use_token=use_token,
            )
        _cleanup_managed_artifact_if_unreferenced(queue_dir, entry, excluding_entry_path=path)
        try:
            os.remove(path)
        except Exception:
            pass
        return "submitted", _submission_success_message(payload, response)
    except SubmitError as exc:
        if exc.retryable:
            _retain_entry(path, entry, str(exc))
            return "retained", str(exc)
        move_to_dead_letter(queue_dir, path, entry, str(exc))
        return "dead_lettered", str(exc)
    except Exception as exc:
        _retain_entry(path, entry, str(exc))
        return "retained", str(exc)


def replay_spool(
    queue_dir: str,
    *,
    base_url: str,
    api_key: str,
    retries: int,
    use_token: bool,
) -> ReplayStats:
    stats = ReplayStats()
    try:
        files: List[str] = sorted([
            os.path.join(queue_dir, name)
            for name in os.listdir(queue_dir)
            if name.endswith(".json") and os.path.isfile(os.path.join(queue_dir, name))
        ])
    except Exception:
        return stats

    for path in files:
        status, _message = submit_spooled_path(
            path,
            queue_dir=queue_dir,
            base_url=base_url,
            api_key=api_key,
            retries=retries,
            use_token=use_token,
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
