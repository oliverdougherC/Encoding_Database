#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from client import runtime_lock  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Register or validate an EncodingDB FFmpeg runtime bundle against the tracked platform lock."
    )
    parser.add_argument("--platform", required=True, choices=("linux", "mac", "win"))
    parser.add_argument("--ffmpeg-path", required=True)
    parser.add_argument("--ffprobe-path", required=True)
    parser.add_argument(
        "--lock-path",
        default=str(ROOT_DIR / "client" / "resources" / "runtime" / "ffmpeg-lock.json"),
    )
    parser.add_argument(
        "--stage-runtime-dir",
        default=None,
        help="Optional destination directory for a packaged, platform-filtered runtime resource bundle.",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Probe the supplied binaries and intentionally update the tracked platform entry.",
    )
    parser.add_argument(
        "--source",
        default="operator-supplied-locked-bundle",
        help="Source label to record when --update is used.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    lock_path = os.path.abspath(args.lock_path)
    platform_key = str(args.platform)
    ffmpeg_path = os.path.abspath(args.ffmpeg_path)
    ffprobe_path = os.path.abspath(args.ffprobe_path)

    if args.update:
        payload = runtime_lock.build_runtime_lock_payload(
            platform_key=platform_key,
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
            source=str(args.source),
        )
        try:
            existing = runtime_lock.load_runtime_lock(lock_path)
        except FileNotFoundError:
            existing = None
        merged = runtime_lock.upsert_runtime_lock_platform(
            existing,
            platform_key=platform_key,
            platform_payload=payload["platforms"][platform_key],
            source=str(args.source),
        )
        runtime_lock.write_runtime_lock(merged, lock_path)
        output: Dict[str, Any] = {
            "mode": "updated",
            "lockPath": lock_path,
            "platform": platform_key,
            "ffmpegPath": ffmpeg_path,
            "ffprobePath": ffprobe_path,
        }
        if args.stage_runtime_dir:
            staged = runtime_lock.stage_runtime_resource_dir(
                destination_dir=os.path.abspath(args.stage_runtime_dir),
                lock_payload=merged,
                platform_key=platform_key,
            )
            output["stagedRuntimeDir"] = staged
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0

    verified = runtime_lock.verify_runtime_lock(
        platform_key=platform_key,
        ffmpeg_path=ffmpeg_path,
        ffprobe_path=ffprobe_path,
        lock_path=lock_path,
    )
    output = {
        "mode": "verified",
        "lockPath": verified["lockPath"],
        "platform": verified["platform"],
        "fingerprint": verified["fingerprint"],
        "ffmpegPath": verified["ffmpegPath"],
        "ffprobePath": verified["ffprobePath"],
    }
    if args.stage_runtime_dir:
        staged = runtime_lock.stage_runtime_resource_dir(
            destination_dir=os.path.abspath(args.stage_runtime_dir),
            lock_payload=verified["payload"],
            platform_key=platform_key,
        )
        output["stagedRuntimeDir"] = staged
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
