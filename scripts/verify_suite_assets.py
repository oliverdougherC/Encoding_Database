#!/usr/bin/env python3
import hashlib
import json
import os
import sys


def main() -> int:
    suite_root = os.path.abspath(sys.argv[1])
    manifest_path = os.path.join(suite_root, "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    for clip in manifest["clips"]:
        path = os.path.join(suite_root, "canonical", clip["fileName"])
        with open(path, "rb") as handle:
            payload = handle.read()
        observed_hash = hashlib.sha256(payload).hexdigest()
        if len(payload) != clip["byteSize"] or observed_hash != clip["sha256"]:
            raise RuntimeError(f"canonical suite asset failed verification: {clip['id']}")
    print(f"verified {len(manifest['clips'])} canonical suite assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
