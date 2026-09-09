#!/usr/bin/env python3
"""Acquire the pinned final suite and install verified resources in both trees."""
import argparse
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
from client import suite


def materialize(repo_root: Path, cache_dir=None, pack_path=None) -> None:
    roots = [repo_root / "client/resources/test_suite_v1", repo_root / "server/resources/test_suite_v1"]
    metadata = suite.load_suite_pack_metadata(str(roots[0] / "suite-pack.json"))
    for root in roots:
        status = suite.load_finalization_status(str(root / "finalization-status.json"))
        if not status.get("isFrozen") or not (root / "suite-lock.json").is_file():
            raise RuntimeError("materialize_final_suite requires a frozen suite with a lock")
        if suite.load_suite_pack_metadata(str(root / "suite-pack.json")) != metadata:
            raise RuntimeError("client/server suite pack metadata differs")
    if pack_path:
        result = suite._verify_suite_pack_file(str(pack_path), metadata)
        if not result.ok:
            raise RuntimeError(result.message)
        archive = str(pack_path)
    else:
        archive = suite._ensure_suite_pack_available(metadata, cache_dir)
    extracted = Path(suite._extract_suite_pack(archive, metadata, cache_dir)).parent
    # Verify identity against tracked resources before changing either tree.
    for root in roots:
        for name in ("manifest.json", "finalization-status.json", "suite-lock.json"):
            if (root / name).read_bytes() != (extracted / name).read_bytes():
                raise RuntimeError(f"pinned suite differs from tracked {root / name}")
    replacements = []
    backups = []
    with tempfile.TemporaryDirectory(prefix=".suite-install-", dir=repo_root) as staging:
        try:
            for index, root in enumerate(roots):
                for name in ("canonical", "notices"):
                    staged = Path(staging) / str(index) / name
                    shutil.copytree(extracted / name, staged)
                    destination = root / name
                    backup = Path(staging) / f"backup-{index}-{name}"
                    if destination.exists():
                        os.replace(destination, backup)
                        backups.append((backup, destination))
                    os.replace(staged, destination)
                    replacements.append(destination)
        except BaseException:
            for destination in reversed(replacements):
                shutil.rmtree(destination)
            for backup, destination in reversed(backups):
                os.replace(backup, destination)
            raise
    print(f"Verified and materialized both suite trees: {metadata['suiteFingerprint']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT_DIR)
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--pack-path", type=Path, default=None)
    args = parser.parse_args()
    materialize(args.repo_root.resolve(), args.cache_dir, args.pack_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
