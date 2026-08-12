#!/usr/bin/env python3
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


def main() -> int:
    client_root = ROOT_DIR / "client" / "resources" / "test_suite_v1"
    server_root = ROOT_DIR / "server" / "resources" / "test_suite_v1"
    compare("suite manifest", client_root / "manifest.json", server_root / "manifest.json")
    compare("finalization status", client_root / "finalization-status.json", server_root / "finalization-status.json")

    client_lock = client_root / "suite-lock.json"
    server_lock = server_root / "suite-lock.json"
    if client_lock.exists() != server_lock.exists():
        raise RuntimeError("suite lock presence drift detected between client and server resources")
    if client_lock.exists():
        compare("suite lock", client_lock, server_lock)

    print("suite resources are synchronized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
