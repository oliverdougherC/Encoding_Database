#!/usr/bin/env python3
import argparse
import hashlib
import json
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
    for name in ("manifest.json", "finalization-status.json", "suite-pack.json", "suite-lock.json", "clip-distribution.json"):
        copy_if_exists(source_suite_dir / name, staged_resource_dir / name)

    if (source_suite_dir / "notices").exists():
        shutil.copytree(source_suite_dir / "notices", staged_resource_dir / "notices")


def build_clip_bundle(*, source_suite_dir: Path, bundle_out: Path, base_url: str = "",
                      release_tag: str | None = None, published: bool = False) -> None:
    """Stage the separately addressable per-clip bundle (no upload performed).

    The bundle root contains flat, unique ``downloadName`` files suitable for
    GitHub release assets, plus clip-distribution.json. Logical per-clip paths
    remain in the metadata. Bytes come from the frozen canonical tree.
    """
    source_suite_dir = source_suite_dir.resolve()
    bundle_out = bundle_out.resolve()
    manifest = suite.load_default_suite_manifest()
    metadata = suite.build_clip_distribution_metadata(
        str(source_suite_dir), manifest=manifest, base_url=base_url,
        release_tag=release_tag, published=published,
    )
    shutil.rmtree(bundle_out, ignore_errors=True)
    bundle_out.mkdir(parents=True, exist_ok=True)
    for clip_id, entry in metadata["clips"].items():
        for asset in entry["assets"]:
            relative = str(asset["path"])
            if str(asset["role"]) == "clip":
                source = source_suite_dir / "canonical" / entry["fileName"]
            else:
                source = source_suite_dir / "notices" / relative.rsplit("notices/", 1)[-1]
            if not source.is_file():
                raise RuntimeError(f"canonical asset missing for staged bundle: {source}")
            destination = bundle_out / str(asset["downloadName"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            digest = hashlib.sha256(destination.read_bytes()).hexdigest()
            if digest != asset["sha256"] or destination.stat().st_size != asset["byteSize"]:
                raise RuntimeError(f"staged bundle asset does not match frozen identity: {relative}")
    with open(bundle_out / "clip-distribution.json", "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, sort_keys=False)
        handle.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the external EncodingDB suite pack and stage client suite resources without embedded canonical media.")
    parser.add_argument("--source-suite-dir", default=str(ROOT_DIR / "client" / "resources" / "test_suite_v1"))
    parser.add_argument("--staged-resource-dir", required=True)
    parser.add_argument("--pack-out", required=True)
    parser.add_argument("--clip-bundle-out", default=None,
                        help="Also stage the per-clip publishable bundle in this directory")
    parser.add_argument("--clip-base-url", default="",
                        help="Public base URL for the per-clip bundle (empty until published)")
    parser.add_argument("--clip-release-tag", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    prepare_distribution(
        source_suite_dir=Path(args.source_suite_dir),
        staged_resource_dir=Path(args.staged_resource_dir),
        pack_out=Path(args.pack_out),
    )
    if args.clip_bundle_out:
        build_clip_bundle(
            source_suite_dir=Path(args.source_suite_dir),
            bundle_out=Path(args.clip_bundle_out),
            base_url=args.clip_base_url,
            release_tag=args.clip_release_tag,
            published=bool(args.clip_base_url),
        )
        print(f"staged per-clip bundle (not uploaded): {os.path.abspath(args.clip_bundle_out)}")
    print(f"staged suite resources: {os.path.abspath(args.staged_resource_dir)}")
    print(f"suite pack: {os.path.abspath(args.pack_out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
