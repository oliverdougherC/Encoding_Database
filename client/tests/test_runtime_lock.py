import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from contextlib import contextmanager

from client import config
from client import runtime_lock

ROOT_DIR = Path(__file__).resolve().parents[2]
CLIENT_DIR = ROOT_DIR / "client"


class RuntimeLockTests(unittest.TestCase):
    def _runtime_paths(self) -> tuple[str, str, str]:
        platform_key = config._platform_key()
        # Runtime integration tests must use the explicitly selected candidate,
        # even if an earlier test populated config's cached legacy helper paths.
        ffmpeg_path = os.environ.get("FFMPEG_EXE") or config.ffmpeg_exe()
        ffprobe_path = os.environ.get("FFPROBE_EXE") or config.ffprobe_exe()
        self.assertTrue(os.path.exists(ffmpeg_path), ffmpeg_path)
        self.assertTrue(os.path.exists(ffprobe_path), ffprobe_path)
        return platform_key, ffmpeg_path, ffprobe_path

    @contextmanager
    def _mock_runtime(self, *, include_svt=True):
        """Real files for hashing, mocked capability subprocess output only."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ffmpeg_path, ffprobe_path = root / "ffmpeg", root / "ffprobe"
            ffmpeg_path.write_bytes(b"mock-ffmpeg-executable")
            ffprobe_path.write_bytes(b"mock-ffprobe-executable")
            (root / "lib").mkdir()
            (root / "lib" / "codec.dylib").write_bytes(b"trusted-dependency")
            encoders = ["libaom-av1", "libvpx-vp9", "libx264", "libx265"]
            if include_svt:
                encoders.append("libsvtav1")
            def output(command):
                if command[-1] == "-version":
                    return f"{Path(command[0]).name} version test-1.0\nconfiguration: mocked-test-runtime"
                if command[-1] == "-filters":
                    return " ... libvmaf\n ... xpsnr\n"
                if command[-1] == "-encoders":
                    return "\n".join(f" V..... {encoder}" for encoder in encoders)
                self.fail(f"Unexpected mocked runtime command: {command}")
            with mock.patch.object(runtime_lock, "_run_text", side_effect=output) as runner:
                yield root, str(ffmpeg_path), str(ffprobe_path), runner

    def test_mock_runtime_requires_svt_without_substitution(self):
        with self._mock_runtime(include_svt=False) as (_, ffmpeg_path, ffprobe_path, _):
            with self.assertRaisesRegex(runtime_lock.RuntimeLockError, "libsvtav1"):
                runtime_lock.build_runtime_lock_payload(platform_key="mac", ffmpeg_path=ffmpeg_path, ffprobe_path=ffprobe_path)
        with self._mock_runtime() as (_, ffmpeg_path, ffprobe_path, _):
            payload = runtime_lock.build_runtime_lock_payload(platform_key="mac", ffmpeg_path=ffmpeg_path, ffprobe_path=ffprobe_path)
            capabilities = payload["platforms"]["mac"]["capabilities"]
            self.assertIn("libsvtav1", capabilities["requiredEncoders"])
            self.assertIn("libsvtav1", capabilities["smokeTestEncoders"])

    def test_old_lock_cannot_weaken_current_platform_requirements(self):
        for platform in ("linux", "win", "mac"):
            for missing in ("libsvtav1", "xpsnr"):
                with self.subTest(platform=platform, missing=missing), self._mock_runtime() as (root, ffmpeg, ffprobe, runner):
                    payload = runtime_lock.build_runtime_lock_payload(
                        platform_key=platform, ffmpeg_path=ffmpeg, ffprobe_path=ffprobe)
                    caps = payload["platforms"][platform]["capabilities"]
                    for key in ("requiredEncoders", "smokeTestEncoders", "encoders", "filters"):
                        caps[key] = [value for value in caps[key] if value != missing]
                    lock_path = root / "old-lock.json"
                    runtime_lock.write_runtime_lock(payload, str(lock_path))
                    observed = runtime_lock.verify_runtime_lock(
                        platform_key=platform, ffmpeg_path=ffmpeg, ffprobe_path=ffprobe,
                        lock_path=str(lock_path))
                    observed_caps = observed["identity"]["capabilities"]
                    self.assertIn(missing, observed_caps["requiredEncoders"] + observed_caps["filters"])
                    output = runner.side_effect
                    runner.side_effect = lambda command: "\n".join(
                        line for line in output(command).splitlines() if missing not in line)
                    with self.assertRaisesRegex(runtime_lock.RuntimeLockError, missing):
                        runtime_lock.verify_runtime_lock(
                            platform_key=platform, ffmpeg_path=ffmpeg, ffprobe_path=ffprobe,
                            lock_path=str(lock_path))

    def test_dependency_hash_and_membership_are_verified_before_runtime_execution(self):
        for mutation in ("same-size-tamper", "missing", "unexpected", "unbound"):
            with self.subTest(mutation=mutation), self._mock_runtime() as (root, ffmpeg_path, ffprobe_path, runner):
                payload = runtime_lock.build_runtime_lock_payload(platform_key="mac", ffmpeg_path=ffmpeg_path, ffprobe_path=ffprobe_path)
                expected = payload["platforms"]["mac"]["runtimeDependencies"]
                self.assertEqual([entry["relativePath"] for entry in expected], ["lib/codec.dylib"])
                self.assertEqual(expected[0]["sha256"], runtime_lock._sha256_path(str(root / "lib" / "codec.dylib")))
                lock_path = root / "runtime-lock.json"
                runtime_lock.write_runtime_lock(payload, str(lock_path))
                runtime_lock.verify_runtime_lock(platform_key="mac", ffmpeg_path=ffmpeg_path, ffprobe_path=ffprobe_path, lock_path=str(lock_path))
                if mutation == "same-size-tamper":
                    (root / "lib" / "codec.dylib").write_bytes(b"changed-dependency")
                elif mutation == "missing":
                    (root / "lib" / "codec.dylib").unlink()
                elif mutation == "unexpected":
                    (root / "lib" / "extra.dylib").write_bytes(b"extra")
                else:
                    del payload["platforms"]["mac"]["runtimeDependencies"]
                    runtime_lock.write_runtime_lock(payload, str(lock_path))
                runner.reset_mock()
                with self.assertRaisesRegex(runtime_lock.RuntimeLockError, "dependenc"):
                    runtime_lock.verify_runtime_lock(platform_key="mac", ffmpeg_path=ffmpeg_path, ffprobe_path=ffprobe_path, lock_path=str(lock_path))
                runner.assert_not_called()

    def test_executable_hash_is_verified_before_any_runtime_execution(self):
        for label in ("ffmpeg", "ffprobe"):
            with self.subTest(label=label), self._mock_runtime() as (root, ffmpeg_path, ffprobe_path, runner):
                payload = runtime_lock.build_runtime_lock_payload(platform_key="mac", ffmpeg_path=ffmpeg_path, ffprobe_path=ffprobe_path)
                lock = root / "runtime-lock.json"
                runtime_lock.write_runtime_lock(payload, str(lock))
                target = Path(ffmpeg_path if label == "ffmpeg" else ffprobe_path)
                original = target.read_bytes()
                target.write_bytes(bytes([original[0] ^ 255]) + original[1:])
                runner.reset_mock()
                with self.assertRaisesRegex(runtime_lock.RuntimeLockError, "SHA-256 mismatch"):
                    runtime_lock.verify_runtime_lock(platform_key="mac", ffmpeg_path=ffmpeg_path, ffprobe_path=ffprobe_path, lock_path=str(lock))
                runner.assert_not_called()

    def test_current_platform_runtime_can_be_registered_and_verified(self) -> None:
        platform_key, ffmpeg_path, ffprobe_path = self._runtime_paths()
        payload = runtime_lock.build_runtime_lock_payload(
            platform_key=platform_key,
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
        )

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            temp_path = handle.name
        self.addCleanup(lambda: os.path.exists(temp_path) and os.remove(temp_path))

        result = runtime_lock.verify_runtime_lock(
            platform_key=platform_key,
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
            lock_path=temp_path,
        )

        self.assertEqual(result["platform"], platform_key)
        self.assertIn("libvmaf", result["identity"]["capabilities"]["filters"])
        self.assertIn("libx264", result["identity"]["capabilities"]["requiredEncoders"])
        self.assertTrue(result["identity"]["capabilities"]["smokeTestEncoders"])

    def test_verify_runtime_lock_rejects_hash_mismatch(self) -> None:
        platform_key, ffmpeg_path, ffprobe_path = self._runtime_paths()
        payload = runtime_lock.build_runtime_lock_payload(
            platform_key=platform_key,
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
        )
        payload["platforms"][platform_key]["ffmpeg"]["sha256"] = "0" * 64

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            temp_path = handle.name
        self.addCleanup(lambda: os.path.exists(temp_path) and os.remove(temp_path))

        with self.assertRaises(runtime_lock.RuntimeLockError):
            runtime_lock.verify_runtime_lock(
                platform_key=platform_key,
                ffmpeg_path=ffmpeg_path,
                ffprobe_path=ffprobe_path,
                lock_path=temp_path,
            )

    def test_build_runtime_lock_payload_records_selected_platform(self) -> None:
        _platform_key, ffmpeg_path, ffprobe_path = self._runtime_paths()
        payload = runtime_lock.build_runtime_lock_payload(
            platform_key="mac",
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
        )

        self.assertEqual(payload["schemaVersion"], 1)
        self.assertIn("mac", payload["platforms"])
        self.assertEqual(payload["platforms"]["mac"]["ffmpeg"]["relativePath"], "bin/mac/ffmpeg")
        self.assertEqual(
            payload["platforms"]["mac"]["capabilities"]["requiredEncoders"],
            ["libaom-av1", "libsvtav1", "libvpx-vp9", "libx264", "libx265"],
        )
        self.assertNotIn("h264_videotoolbox", payload["platforms"]["mac"]["capabilities"]["requiredEncoders"])

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

    def test_runtime_requirements_are_platform_aware(self) -> None:
        mac = runtime_lock.runtime_capability_requirements("mac")
        linux = runtime_lock.runtime_capability_requirements("linux")
        win = runtime_lock.runtime_capability_requirements("win")

        self.assertNotIn("h264_videotoolbox", mac["requiredEncoders"])
        self.assertIn("h264_videotoolbox", mac["optionalEncoders"])
        self.assertNotIn("h264_videotoolbox", linux["requiredEncoders"])
        self.assertNotIn("h264_videotoolbox", win["requiredEncoders"])
        self.assertNotIn("h264_videotoolbox", win["optionalEncoders"])

    def test_default_runtime_lock_path_prefers_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            override = os.path.join(temp_dir, "runtime-lock.json")
            original = os.environ.get("ENCODINGDB_RUNTIME_LOCK_PATH")
            os.environ["ENCODINGDB_RUNTIME_LOCK_PATH"] = override
            try:
                self.assertEqual(runtime_lock.default_runtime_lock_path(), override)
            finally:
                if original is None:
                    os.environ.pop("ENCODINGDB_RUNTIME_LOCK_PATH", None)
                else:
                    os.environ["ENCODINGDB_RUNTIME_LOCK_PATH"] = original

    def test_checked_in_lock_declares_split_encoder_capabilities(self) -> None:
        with (CLIENT_DIR / "resources" / "runtime" / "ffmpeg-lock.json").open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        capabilities = payload["platforms"]["mac"]["capabilities"]
        self.assertIn("requiredEncoders", capabilities)
        self.assertIn("optionalEncoders", capabilities)
        self.assertIn("smokeTestEncoders", capabilities)
        self.assertNotIn("h264_videotoolbox", capabilities["requiredEncoders"])

    def test_register_script_verifies_and_stages_runtime_dir(self) -> None:
        platform_key, ffmpeg_path, ffprobe_path = self._runtime_paths()
        with tempfile.TemporaryDirectory() as temp_dir:
            staged_dir = Path(temp_dir) / "runtime"
            lock_path = Path(temp_dir) / "ffmpeg-lock.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT_DIR / "scripts" / "register_ffmpeg_runtime.py"),
                    "--platform",
                    platform_key,
                    "--ffmpeg-path",
                    ffmpeg_path,
                    "--ffprobe-path",
                    ffprobe_path,
                    "--lock-path",
                    str(lock_path),
                    "--update",
                    "--stage-runtime-dir",
                    str(staged_dir),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["mode"], "updated")
            with open(staged_dir / "ffmpeg-lock.json", "r", encoding="utf-8") as handle:
                staged_lock = json.load(handle)
        self.assertEqual(sorted(staged_lock["platforms"].keys()), [platform_key])


if __name__ == "__main__":
    unittest.main()
