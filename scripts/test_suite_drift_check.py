#!/usr/bin/env python3
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def compare(label: str, left: Path, right: Path) -> None:
    left_payload = load_json(left)
    right_payload = load_json(right)
    if left_payload != right_payload:
        raise RuntimeError(f"{label} drift detected between {left} and {right}")


def verify_notices(root: Path) -> None:
    metadata = load_json(root / "suite-pack.json")
    status = load_json(root / "finalization-status.json")
    manifest = load_json(root / "manifest.json")
    notices = metadata.get("contents", {}).get("notices", [])
    expected = {entry["fileName"]: entry for entry in notices}
    actual = {f"notices/{path.name}" for path in (root / "notices").glob("*")}
    if set(expected) != actual:
        raise RuntimeError(f"notice inventory drift detected in {root}")
    if status.get("isFrozen"):
        if not (root / "suite-lock.json").is_file():
            raise RuntimeError(f"frozen suite lock missing in {root}")
        for clip in manifest["clips"]:
            if f"notices/{clip['id']}.txt" not in expected:
                raise RuntimeError(f"frozen suite notice missing for {clip['id']}")
    for name, entry in expected.items():
        if not name.startswith("notices/") or Path(name).name != name[len("notices/"):] or ".." in name:
            raise RuntimeError("unsafe notice inventory path")
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"notice is not a regular file: {path}")
        data = path.read_bytes()
        if len(data) != entry["byteSize"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise RuntimeError(f"notice hash drift detected: {path}")


def main() -> int:
    client_root = ROOT_DIR / "client" / "resources" / "test_suite_v1"
    server_root = ROOT_DIR / "server" / "resources" / "test_suite_v1"
    compare("suite manifest", client_root / "manifest.json", server_root / "manifest.json")
    compare("finalization status", client_root / "finalization-status.json", server_root / "finalization-status.json")
    compare("suite pack metadata", client_root / "suite-pack.json", server_root / "suite-pack.json")

    client_lock = client_root / "suite-lock.json"
    server_lock = server_root / "suite-lock.json"
    if client_lock.exists() != server_lock.exists():
        raise RuntimeError("suite lock presence drift detected between client and server resources")
    if client_lock.exists():
        compare("suite lock", client_lock, server_lock)

    verify_notices(client_root)
    verify_notices(server_root)
    print("suite resources are synchronized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
