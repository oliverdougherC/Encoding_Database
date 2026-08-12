import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from client import suite
from scripts import release_manifest_lib


class ReleasePackagingTests(unittest.TestCase):
    def test_native_build_validation_is_distinct_from_final_release_packaging(self) -> None:
        root = release_manifest_lib.ROOT_DIR
        for relative_path in (
            "scripts/build_linux_client.sh",
            "scripts/build_macos_client.sh",
            "scripts/build_windows_client.ps1",
        ):
            text = (root / relative_path).read_text(encoding="utf-8")
            self.assertIn("ENCODINGDB_BUILD_ONLY", text)
            self.assertIn("release_manifest_lib.py", text)

        workflow = (root / ".github/workflows/build.yml").read_text(encoding="utf-8")
        self.assertEqual(workflow.count('ENCODINGDB_BUILD_ONLY: "1"'), 3)
        self.assertNotIn("${{ runner.temp }}", workflow)
        self.assertNotIn("| head -n 1", workflow)
        self.assertEqual(workflow.count("find \"$PWD\" -mindepth 1 -maxdepth 1"), 3)

        preflight_workflow = (root / ".github/workflows/release-preflight.yml").read_text(encoding="utf-8")
        self.assertNotIn("| head -n 1", preflight_workflow)
        self.assertIn("find \"$PWD\" -mindepth 1 -maxdepth 1", preflight_workflow)

    def test_native_build_helpers_run_after_isolated_dependencies_are_installed(self) -> None:
        root = release_manifest_lib.ROOT_DIR
        for relative_path in ("scripts/build_linux_client.sh", "scripts/build_macos_client.sh"):
            text = (root / relative_path).read_text(encoding="utf-8")
            install_at = text.index("-m pip install")
            verify_at = text.index("scripts/verify_suite_assets.py")
            register_at = text.index("scripts/register_ffmpeg_runtime.py")
            self.assertLess(install_at, verify_at)
            self.assertLess(install_at, register_at)
            self.assertIn('FFMPEG_EXE="$FFMPEG_PATH" FFPROBE_EXE="$FFPROBE_PATH"', text)
            self.assertIn('"$BUILD_PYTHON" "$ROOT_DIR/scripts/verify_suite_assets.py"', text)
            self.assertIn('"$BUILD_PYTHON" "$ROOT_DIR/scripts/register_ffmpeg_runtime.py"', text)

        windows = (root / "scripts/build_windows_client.ps1").read_text(encoding="utf-8")
        install_at = windows.index("-m pip install")
        verify_at = windows.index('"scripts\\verify_suite_assets.py"')
        register_at = windows.index('"scripts\\register_ffmpeg_runtime.py"')
        self.assertLess(install_at, verify_at)
        self.assertLess(install_at, register_at)
        self.assertIn("$env:FFMPEG_EXE = $ffmpegPath", windows)
        self.assertIn("$env:FFPROBE_EXE = $ffprobePath", windows)
        self.assertIn("& $buildPython @verifyArgs", windows)
        self.assertIn("& $buildPython @runtimeRegisterArgs", windows)

    def test_project_version_remains_explicitly_unassigned_before_release(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Project release version is unassigned"):
                release_manifest_lib.detect_project_version()

    def test_read_client_minimum_version_is_coherent(self) -> None:
        self.assertEqual(release_manifest_lib.read_client_minimum_version(), "client/0.2.0")

    def test_finalize_release_writes_expected_sidecars(self) -> None:
        runtime_payload = {
            "schemaVersion": 1,
            "runtimeId": "encodingdb-ffmpeg-runtime",
            "source": "deterministically-provisioned",
            "platforms": {
                "mac": {
                    "ffmpeg": {
                        "relativePath": "bin/mac/ffmpeg",
                        "sha256": "a" * 64,
                        "byteSize": 1,
                        "versionLine": "ffmpeg version test",
                        "buildFingerprint": "b" * 64,
                    },
                    "ffprobe": {
                        "relativePath": "bin/mac/ffprobe",
                        "sha256": "c" * 64,
                        "byteSize": 1,
                        "versionLine": "ffprobe version test",
                        "buildFingerprint": "d" * 64,
                    },
                    "capabilities": {
                        "ffprobe": True,
                        "filters": ["libvmaf", "xpsnr"],
                        "encoders": ["libx264"],
                    },
                }
            },
        }
        smoke_payload = {
            "schemaVersion": 1,
            "submissionMode": "no-submit",
            "commands": [
                {"name": "help", "argv": ["artifact", "--help"], "returnCode": 0},
                {"name": "no-submit-suite", "argv": ["artifact", "--no-submit"], "returnCode": 0},
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            artifact_path = temp_root / "encodingdb-client-macos"
            artifact_path.write_bytes(b"artifact-bytes")
            suite_pack_path = temp_root / suite.DEFAULT_SUITE_PACK_FILE_NAME
            suite_pack_path.write_bytes(b"suite-pack-bytes")
            suite_pack_metadata = {
                "distributionMode": "external-suite-pack",
                "suiteFingerprint": "f" * 64,
                "distribution": {
                    "fileName": suite_pack_path.name,
                    "sha256": release_manifest_lib.sha256_path(suite_pack_path),
                    "byteSize": suite_pack_path.stat().st_size,
                    "format": "tar.gz",
                    "downloadUrls": [],
                },
            }

            with mock.patch.object(
                release_manifest_lib.runtime_lock,
                "verify_runtime_lock",
                return_value={
                    "platform": "mac",
                    "lockPath": str(temp_root / "ffmpeg-lock.json"),
                    "ffmpegPath": str(artifact_path),
                    "ffprobePath": str(artifact_path),
                    "fingerprint": "z" * 64,
                    "payload": runtime_payload,
                    "identity": {},
                },
            ), \
                    mock.patch.object(release_manifest_lib.suite, "load_suite_pack_metadata", return_value=suite_pack_metadata), \
                    mock.patch.object(release_manifest_lib, "detect_project_version", return_value="1.1.0"), \
                    mock.patch.object(release_manifest_lib, "run_smoke_check", return_value=smoke_payload):
                sidecars = release_manifest_lib.finalize_release(
                    artifact_path=artifact_path,
                    platform="mac",
                    ffmpeg_path=artifact_path,
                    ffprobe_path=artifact_path,
                    output_dir=temp_root,
                    signing_status="unsigned",
                    signing_evidence_path=None,
                    suite_pack_path=suite_pack_path,
                )

            manifest_path = sidecars["release_manifest"]
            sha_path = sidecars["sha256sums"]
            smoke_path = sidecars["smoke"]
            self.assertTrue(manifest_path.exists())
            self.assertTrue(sha_path.exists())
            self.assertTrue(smoke_path.exists())

            with manifest_path.open("r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            self.assertEqual(manifest["platform"], "mac")
            self.assertEqual(manifest["suite"]["distribution"], "development-only")
            self.assertFalse(manifest["suite"]["isFrozen"])
            self.assertEqual(manifest["suite"]["distributionMode"], "external-suite-pack")
            self.assertEqual(manifest["suite"]["pack"]["fileName"], suite_pack_path.name)
            self.assertEqual(manifest["signing"]["status"], "unsigned")
            with sidecars["runtime_lock"].open("r", encoding="utf-8") as handle:
                staged_lock = json.load(handle)
            self.assertEqual(sorted(staged_lock["platforms"].keys()), ["mac"])

            sha_lines = sha_path.read_text(encoding="utf-8").splitlines()
            self.assertTrue(any(line.endswith(f"  {artifact_path.name}") for line in sha_lines))
            self.assertTrue(any(line.endswith(f"  {smoke_path.name}") for line in sha_lines))
            self.assertTrue(any(line.endswith(f"  {suite_pack_path.name}") for line in sha_lines))


if __name__ == "__main__":
    unittest.main()
