"""Owned, fsynced campaign journals. References and runtime files are never modified."""
import dataclasses
import hashlib
import json
import os
import re
import secrets
from pathlib import Path
from typing import Any

from . import config
from .protocol import (ArtifactProbe, BenchmarkRunRecord, EncodeTiming, EnvironmentSnapshot,
                       ScheduledRun, ValidityReason, ValidityResult)


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
        for path in sorted(self.root.glob("attempt-*.json")):
            record = load_record(json.loads(path.read_text()))
            info = record.metadata.get("info") or {}
            artifact = info.get("artifactPath")
            if artifact and not info.get("error"):
                candidate = Path(artifact)
                if not candidate.is_file() or self.root.resolve() not in candidate.resolve().parents:
                    raise ValueError("Journal artifact missing or outside owned campaign")
                if self.hash_file(candidate) != info.get("artifactSha256"):
                    raise ValueError("Journal artifact changed; cannot resume")
            self.records[record.schedule.execution_order] = record

    @staticmethod
    def hash_file(path):
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def check_budget(self):
        total = sum(path.stat().st_size for path in self.queue_root.rglob("*") if path.is_file())
        if total >= self.max_bytes:
            raise OSError("Campaign storage budget reached; retained attempts can be resumed after freeing space")
        return self.max_bytes - total

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
                                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False, capture_output=True, timeout=10)
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
