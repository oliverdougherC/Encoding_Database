#!/usr/bin/env python3
"""Wrap the packaged Linux CLI into encodingdb-client-linux.tar.gz.

The primary Linux download must preserve executable bits and lead straight to
the guided menu: a discoverable ``start.sh`` (0755) with no arguments, plus an
honest README. The archive is built with Python's tarfile for deterministic
bytes: sorted members, zeroed uid/gid/mtime, gzip mtime fixed at 0, so the same
inputs always produce the same SHA-256.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import shutil
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional, Sequence

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

PACKAGING_DIR = ROOT_DIR / "packaging" / "linux"
START_SCRIPT_ASSET = PACKAGING_DIR / "start.sh"
README_ASSET = PACKAGING_DIR / "README.md"

ARCHIVE_PREFIX = "encodingdb-client-linux"
CLI_MEMBER_NAME = "encodingdb-client-linux"
EXECUTABLE_MODE = 0o755
DOCUMENT_MODE = 0o644


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_archive(binary: Path, output: Path) -> Dict[str, Any]:
    if not binary.is_file():
        raise FileNotFoundError(f"CLI binary not found: {binary}")
    for asset in (START_SCRIPT_ASSET, README_ASSET):
        if not asset.is_file():
            raise FileNotFoundError(f"Missing packaging asset: {asset}")
    members = [
        (f"{ARCHIVE_PREFIX}/{CLI_MEMBER_NAME}", binary, EXECUTABLE_MODE),
        (f"{ARCHIVE_PREFIX}/start.sh", START_SCRIPT_ASSET, EXECUTABLE_MODE),
        (f"{ARCHIVE_PREFIX}/README.md", README_ASSET, DOCUMENT_MODE),
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    raw = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as archive:
            for name, source, mode in members:
                payload = source.read_bytes()
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                info.mode = mode
                info.type = tarfile.REGTYPE
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.mtime = 0
                archive.addfile(info, io.BytesIO(payload))
    output.write_bytes(raw.getvalue())
    return {
        "fileName": output.name,
        "sha256": sha256_path(output),
        "byteSize": output.stat().st_size,
        "prefix": ARCHIVE_PREFIX,
        "members": [
            {"name": name, "mode": oct(mode), "sha256": sha256_path(source)}
            for name, source, mode in members
        ],
    }


def verify_archive(output: Path) -> Dict[str, Any]:
    """Read the written archive back and enforce the launch contract."""
    expected = {
        f"{ARCHIVE_PREFIX}/{CLI_MEMBER_NAME}": EXECUTABLE_MODE,
        f"{ARCHIVE_PREFIX}/start.sh": EXECUTABLE_MODE,
        f"{ARCHIVE_PREFIX}/README.md": DOCUMENT_MODE,
    }
    observed: Dict[str, int] = {}
    with tarfile.open(output, "r:gz") as archive:
        for member in archive.getmembers():
            resolved = PurePosixPath(member.name)
            if resolved.is_absolute() or ".." in resolved.parts:
                raise RuntimeError(f"Unsafe member path in archive: {member.name}")
            if not member.isfile():
                raise RuntimeError(f"Unexpected non-file member: {member.name}")
            observed[member.name] = member.mode & 0o777
    if observed != expected:
        raise RuntimeError(f"Archive membership/modes drifted: {observed!r} != {expected!r}")
    with tarfile.open(output, "r:gz") as archive:
        start = archive.extractfile(f"{ARCHIVE_PREFIX}/start.sh")
        assert start is not None
        script = start.read().decode("utf-8")
    if 'exec "$cli" "$@"' not in script:
        raise RuntimeError("start.sh no longer forwards arguments to the guided default")
    return {"verified": True, "members": {name: oct(mode) for name, mode in observed.items()}}


def collect_source_identity() -> Dict[str, Any]:
    from scripts import release_manifest_lib

    return release_manifest_lib.source_identity()


def package(args: argparse.Namespace) -> int:
    binary = Path(args.binary)
    output = Path(args.output)
    info: Dict[str, Any] = {"schemaVersion": 1, "provisional": bool(args.provisional)}
    info["archive"] = build_archive(binary, output)
    info["verification"] = verify_archive(output)
    info["source"] = collect_source_identity()
    info_path = output.with_name(output.name + ".package-info.json")
    info_path.write_text(json.dumps(info, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
                         encoding="utf-8")
    from scripts import release_manifest_lib

    release_manifest_lib.write_sha256sums(
        output.with_name(output.name + ".SHA256SUMS"), [output])
    print(f"[Linux package] {json.dumps(info, sort_keys=True)}")
    return 0


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", help="packaged Linux CLI binary")
    parser.add_argument("output", help="tar.gz output path")
    parser.add_argument("--provisional", action="store_true",
                        help="mark the package-info as a non-publishable provisional wrapper")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    return package(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
