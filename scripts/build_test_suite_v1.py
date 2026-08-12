#!/usr/bin/env python3
import argparse
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from client import suite  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Materialize or rewrite EncodingDB Test Suite v1.")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to populate with verified suite clips. Defaults to the client cache root.",
    )
    parser.add_argument(
        "--rewrite-manifest",
        action="store_true",
        help="Regenerate the checked-in manifest from the deterministic clip recipes before verification.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = os.path.join(ROOT_DIR, "client", "resources", "test_suite_v1", "manifest.json")
    if args.rewrite_manifest:
        suite.write_manifest(manifest_path)
        print(f"Rewrote manifest: {manifest_path}")

    manifest = suite.load_default_suite_manifest()
    prepared = suite.ensure_suite(manifest, cache_root=args.output_dir)
    print(f"Verified {len(prepared)} clips for {manifest.suite_version}")
    for clip in prepared:
        print(f"{clip.clip_id} -> {clip.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
