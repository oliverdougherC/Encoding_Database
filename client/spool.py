import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .network import SubmitError, submit

SPOOL_VERSION = 1


@dataclass
class ReplayStats:
    submitted: int = 0
    retained: int = 0
    dead_lettered: int = 0
    corrupt: int = 0


def _canonical_payload_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def local_hash_for_payload(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_payload_json(payload).encode("utf-8")).hexdigest()


def _queue_path(queue_dir: str, local_hash: str) -> str:
    return os.path.join(queue_dir, f"{local_hash}.json")


def _dead_letter_dir(queue_dir: str) -> str:
    return os.path.join(queue_dir, "dead-letter")


def count_pending_entries(queue_dir: str) -> int:
    try:
        return len([
            name for name in os.listdir(queue_dir)
            if name.endswith(".json") and os.path.isfile(os.path.join(queue_dir, name))
        ])
    except Exception:
        return 0


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


def spool_payload(queue_dir: str, payload: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    envelope = _envelope_for_payload(payload)
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
    _write_json_atomic(dead_path, updated)
    try:
        if os.path.exists(source_path):
            os.remove(source_path)
    except Exception:
        pass
    return dead_path, updated


def _retain_entry(path: str, entry: Dict[str, Any], error: str) -> None:
    _write_json_atomic(path, _update_entry_for_attempt(entry, error=error))


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
        submit(
            base_url,
            entry["payload"],
            api_key=api_key,
            retries=retries,
            use_token=use_token,
        )
        try:
            os.remove(path)
        except Exception:
            pass
        return "submitted", ""
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
