import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from client import runtime_lock

ROOT_DIR = Path(__file__).resolve().parents[2]
CLIENT_DIR = ROOT_DIR / "client"


class RuntimeLockTests(unittest.TestCase):
    def test_checked_in_mac_runtime_lock_matches_bundled_binaries(self) -> None:
        lock_path = CLIENT_DIR / "resources" / "runtime" / "ffmpeg-lock.json"
        result = runtime_lock.verify_runtime_lock(
            platform_key="mac",
            ffmpeg_path=str(CLIENT_DIR / "bin" / "mac" / "ffmpeg"),
            ffprobe_path=str(CLIENT_DIR / "bin" / "mac" / "ffprobe"),
            lock_path=str(lock_path),
        )

        self.assertEqual(result["platform"], "mac")
        self.assertIn("libvmaf", result["identity"]["capabilities"]["filters"])
        self.assertIn("libx264", result["identity"]["capabilities"]["encoders"])

    def test_verify_runtime_lock_rejects_hash_mismatch(self) -> None:
        with (CLIENT_DIR / "resources" / "runtime" / "ffmpeg-lock.json").open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["platforms"]["mac"]["ffmpeg"]["sha256"] = "0" * 64

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            temp_path = handle.name
        self.addCleanup(lambda: os.path.exists(temp_path) and os.remove(temp_path))

        with self.assertRaises(runtime_lock.RuntimeLockError):
            runtime_lock.verify_runtime_lock(
                platform_key="mac",
                ffmpeg_path=str(CLIENT_DIR / "bin" / "mac" / "ffmpeg"),
                ffprobe_path=str(CLIENT_DIR / "bin" / "mac" / "ffprobe"),
                lock_path=temp_path,
            )

    def test_build_runtime_lock_payload_records_selected_platform(self) -> None:
        payload = runtime_lock.build_runtime_lock_payload(
            platform_key="mac",
            ffmpeg_path=str(CLIENT_DIR / "bin" / "mac" / "ffmpeg"),
            ffprobe_path=str(CLIENT_DIR / "bin" / "mac" / "ffprobe"),
        )

        self.assertEqual(payload["schemaVersion"], 1)
        self.assertIn("mac", payload["platforms"])
        self.assertEqual(payload["platforms"]["mac"]["ffmpeg"]["relativePath"], "bin/mac/ffmpeg")

    def test_stage_runtime_resource_dir_filters_to_selected_platform(self) -> None:
        lock_payload = {
            "schemaVersion": 1,
            "runtimeId": "encodingdb-ffmpeg-runtime",
            "source": "deterministically-provisioned",
            "platforms": {
                "mac": {"ffmpeg": {"relativePath": "bin/mac/ffmpeg"}, "ffprobe": {"relativePath": "bin/mac/ffprobe"}, "capabilities": {}},
                "linux": {"ffmpeg": {"relativePath": "bin/linux/ffmpeg"}, "ffprobe": {"relativePath": "bin/linux/ffprobe"}, "capabilities": {}},
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            staged = runtime_lock.stage_runtime_resource_dir(
                destination_dir=temp_dir,
                lock_payload=lock_payload,
                platform_key="linux",
            )
            with open(os.path.join(staged, "ffmpeg-lock.json"), "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        self.assertEqual(sorted(payload["platforms"].keys()), ["linux"])

    def test_register_script_verifies_and_stages_runtime_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            staged_dir = Path(temp_dir) / "runtime"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT_DIR / "scripts" / "register_ffmpeg_runtime.py"),
                    "--platform",
                    "mac",
                    "--ffmpeg-path",
                    str(CLIENT_DIR / "bin" / "mac" / "ffmpeg"),
                    "--ffprobe-path",
                    str(CLIENT_DIR / "bin" / "mac" / "ffprobe"),
                    "--stage-runtime-dir",
                    str(staged_dir),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["mode"], "verified")
            with open(staged_dir / "ffmpeg-lock.json", "r", encoding="utf-8") as handle:
                staged_lock = json.load(handle)
        self.assertEqual(sorted(staged_lock["platforms"].keys()), ["mac"])


if __name__ == "__main__":
    unittest.main()
