#!/usr/bin/env python3
import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from client import suite  # noqa: E402


def copy_if_exists(source: Path, destination: Path) -> None:
    if source.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def prepare_distribution(
    *,
    source_suite_dir: Path,
    staged_resource_dir: Path,
    pack_out: Path,
) -> None:
    source_suite_dir = source_suite_dir.resolve()
    staged_resource_dir = staged_resource_dir.resolve()
    pack_out = pack_out.resolve()

    metadata_path = source_suite_dir / "suite-pack.json"
    metadata = suite.load_suite_pack_metadata(str(metadata_path))
    suite.verify_suite_pack_metadata(str(source_suite_dir), metadata)
    suite.build_suite_pack_archive(str(source_suite_dir), str(pack_out))
    distribution = dict(metadata.get("distribution") or {})
    expected_name = str(distribution.get("fileName") or suite.DEFAULT_SUITE_PACK_FILE_NAME)
    if pack_out.name != expected_name:
        raise RuntimeError(f"suite pack output file name must be {expected_name}")
    verification = suite._verify_suite_pack_file(str(pack_out), metadata)
    if not verification.ok:
        raise RuntimeError(verification.message)

    shutil.rmtree(staged_resource_dir, ignore_errors=True)
    staged_resource_dir.mkdir(parents=True, exist_ok=True)
    for name in ("manifest.json", "finalization-status.json", "suite-pack.json", "suite-lock.json"):
        copy_if_exists(source_suite_dir / name, staged_resource_dir / name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the external EncodingDB suite pack and stage client suite resources without embedded canonical media.")
    parser.add_argument("--source-suite-dir", default=str(ROOT_DIR / "client" / "resources" / "test_suite_v1"))
    parser.add_argument("--staged-resource-dir", required=True)
    parser.add_argument("--pack-out", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    prepare_distribution(
        source_suite_dir=Path(args.source_suite_dir),
        staged_resource_dir=Path(args.staged_resource_dir),
        pack_out=Path(args.pack_out),
    )
    print(f"staged suite resources: {os.path.abspath(args.staged_resource_dir)}")
    print(f"suite pack: {os.path.abspath(args.pack_out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
