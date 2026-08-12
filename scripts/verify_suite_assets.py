#!/usr/bin/env python3
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
        payload = handle.read()
    manifest = suite.load_default_suite_manifest() if manifest_path == suite.get_manifest_path() else None
    if manifest is None:
        import json
        raw = json.loads(payload)
        clips = []
        for clip in raw.get("clips", []):
            clips.append(
                suite.SuiteClip(
                    clip_id=str(clip["id"]),
                    display_name=str(clip["displayName"]),
                    canonical_content_class=str(clip["contentClass"]),
                    payload_content_class=str(clip.get("payloadContentClass") or clip["contentClass"]),
                    file_name=str(clip["fileName"]),
                    sha256=str(clip["sha256"]),
                    byte_size=int(clip["byteSize"]),
                    acquisition=dict(clip.get("acquisition") or {}),
                    description=str(clip.get("description") or ""),
                    provenance=dict(clip.get("source") or {}),
                    media=suite._manifest_media_from_dict(dict(clip["media"])),
                )
            )
        manifest = suite.SuiteManifest(
            suite_version=str(raw["suiteVersion"]),
            display_name=str(raw["displayName"]),
            manifest_version=int(raw["manifestVersion"]),
            default_quick_clip_id=str(raw["defaultQuickClipId"]),
            required_content_classes=tuple(str(value) for value in raw.get("requiredContentClasses", [])),
            clips=tuple(clips),
        )
    for clip in manifest.clips:
        path = os.path.join(suite_root, "canonical", clip.file_name)
        result = suite.verify_suite_clip(path, clip)
        if not result.ok:
            raise RuntimeError(f"canonical suite asset failed verification: {clip.clip_id}: {result.message}")
    print(f"verified {len(manifest.clips)} canonical suite assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
