#!/usr/bin/env python3
import json
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from client import suite  # noqa: E402


def main() -> int:
    suite_root = os.path.abspath(sys.argv[1])
    manifest_path = os.path.join(suite_root, "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    manifest = suite.load_default_suite_manifest() if manifest_path == suite.get_manifest_path() else suite.manifest_from_payload(raw)
    for clip in manifest.clips:
        path = os.path.join(suite_root, "canonical", clip.file_name)
        result = suite.verify_suite_clip(path, clip)
        if not result.ok:
            raise RuntimeError(f"canonical suite asset failed verification: {clip.clip_id}: {result.message}")
    suite.verify_suite_pack_metadata(suite_root, suite.load_suite_pack_metadata(os.path.join(suite_root, "suite-pack.json")))
    print(f"verified {len(manifest.clips)} canonical suite assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
