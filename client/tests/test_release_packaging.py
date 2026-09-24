import json
import os
import tempfile
import unittest
import re
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
        self.assertNotIn('ENCODINGDB_BUILD_ONLY: "1"', workflow)
        self.assertNotIn('ENCODINGDB_REGISTER_RUNTIME: "1"', workflow)
        self.assertIn("runtime_lock_evidence:", workflow)
        for platform in ("linux", "macos", "windows"):
            job = re.search(
                rf"^  client-native-{platform}-build:\n(.*?)(?=^  [\w-]+:|\Z)",
                workflow, re.MULTILINE | re.DOTALL,
            )
            self.assertIsNotNone(job)
            native_workflow = job.group(1)
            # Retain both native artifacts for every platform; unrelated
            # regression-log uploads must not change this packaging contract.
            for artifact in (f"proposed-runtime-{platform}", f"candidate-{platform}"):
                self.assertRegex(native_workflow, rf"name: {artifact}-[^\n]+\n(?:(?!\s+- name:)[^\n]*\n)*?\s+retention-days: 90")
            self.assertIn(f"candidate-{platform}-${{{{ github.sha }}}}", native_workflow)
            self.assertIn(f"proposed-runtime-{platform}-${{{{ github.sha }}}}", native_workflow)
        self.assertIn("if: ${{ !inputs.runtime_lock_evidence }}", workflow)
        self.assertNotIn("${{ runner.temp }}", workflow)
        self.assertNotIn("| head -n 1", workflow)
        self.assertEqual(workflow.count("find \"$PWD\" -mindepth 1 -maxdepth 1"), 3)
        self.assertIn('echo "$bundle_dir/bin" >> "$GITHUB_PATH"', workflow)

        preflight_workflow = (root / ".github/workflows/release-preflight.yml").read_text(encoding="utf-8")
        self.assertNotIn("| head -n 1", preflight_workflow)
        self.assertIn("find \"$PWD\" -mindepth 1 -maxdepth 1", preflight_workflow)
        self.assertIn('echo "$bundle_dir/bin" >> "$GITHUB_PATH"', preflight_workflow)

    def test_native_build_helpers_run_after_isolated_dependencies_are_installed(self) -> None:
        root = release_manifest_lib.ROOT_DIR
        attributes = (root / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("client/resources/test_suite_v1/*.json text eol=lf", attributes)
        self.assertIn("server/resources/test_suite_v1/*.json text eol=lf", attributes)
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
            self.assertIn('"$BUILD_PYTHON" "$ROOT_DIR/scripts/release_manifest_lib.py"', text)

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
        self.assertIn("& $buildPython @guiReleaseManifestArgs", windows)
        self.assertIn("& $buildPython @releaseManifestArgs", windows)
        self.assertLess(windows.index('Exe = "python.exe"'), windows.index('Exe = "py"'))
        self.assertIn("$pythonExe = $pythonCmd.Exe", windows)
        self.assertIn("$pythonPrefixArgs = @($pythonCmd.PrefixArgs)", windows)
        self.assertIn('"--add-data", "$clientDir\\presets.json;."', windows)
        self.assertIn('"--add-data", "$clientDir\\resources\\vmaf;resources/vmaf"', windows)

    def test_release_version_is_assigned_and_missing_version_is_rejected(self) -> None:
        metadata = json.loads((release_manifest_lib.ROOT_DIR / "release.json").read_text())
        self.assertRegex(metadata["projectVersion"], r"^\d+\.\d+\.\d+(?:-(?:beta|rc)\.\d+)?$")
        import datetime
        datetime.date.fromisoformat(metadata["releaseDate"])
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(release_manifest_lib.detect_project_version(), metadata["projectVersion"])
            with mock.patch.object(release_manifest_lib, "read_text", return_value='{"projectVersion": null}'):
                with self.assertRaisesRegex(RuntimeError, "Project release version is unassigned"):
                    release_manifest_lib.detect_project_version()

    def test_read_client_minimum_version_is_coherent(self) -> None:
        self.assertEqual(release_manifest_lib.read_client_minimum_version(), "client/0.3.0")
        self.assertEqual(release_manifest_lib.read_client_implementation_version(), "client/0.3.3")

    def test_client_patch_version_does_not_change_protocol_minimum(self) -> None:
        with mock.patch.object(release_manifest_lib, "read_text", side_effect=[
            'CLIENT_VERSION = "client/99.0.0"\nPROTOCOL_MINIMUM_CLIENT_VERSION = "client/0.3.0"',
            "SERVER_CANONICAL_MINIMUM_CLIENT_VERSION = 'client/0.3.0'",
        ]):
            self.assertEqual(release_manifest_lib.read_client_minimum_version(), "client/0.3.0")

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
            self.assertEqual(manifest["suite"]["distribution"], "reviewed-final")
            self.assertTrue(manifest["suite"]["isFrozen"])
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

    def test_primary_artifact_contracts_and_launch_wiring(self) -> None:
        root = release_manifest_lib.ROOT_DIR
        macos = (root / "scripts/build_macos_client.sh").read_text(encoding="utf-8")
        self.assertIn("scripts/macos_client_package.py", macos)
        self.assertIn("EncodingDB-macOS-arm64.dmg", macos)
        self.assertIn('"$BUILD_PYTHON" "${PACKAGE_ARGS[@]}"', macos)
        linux = (root / "scripts/build_linux_client.sh").read_text(encoding="utf-8")
        self.assertIn("scripts/linux_client_package.py", linux)
        self.assertIn("encodingdb-client-linux.tar.gz", linux)
        self.assertIn('"$BUILD_PYTHON" "${LINUX_PACKAGE_ARGS[@]}"', linux)
        windows = (root / "scripts/build_windows_client.ps1").read_text(encoding="utf-8")
        self.assertIn('$guiAppName = "encodingdb-client-windows"', windows)
        self.assertIn('$consoleAppName = "encodingdb-client-windows-console"', windows)
        self.assertIn('"--windowed"', windows)
        gui_entry = (root / "client/_pyinstaller_gui_entry.py").read_text(encoding="utf-8")
        self.assertIn('"--gui"', gui_entry)
        console_entry = (root / "client/_pyinstaller_entry.py").read_text(encoding="utf-8")
        self.assertIn("from client.main import main", console_entry)
        for relative_path in ("packaging/macos/launcher.sh",
                              "packaging/macos/EncodingDB.command",
                              "packaging/linux/start.sh"):
            mode = (root / relative_path).stat().st_mode
            self.assertTrue(mode & 0o111, f"{relative_path} must stay executable")
        macos_readme = (root / "packaging/macos/README-installer.txt").read_text(encoding="utf-8")
        self.assertIn("macOS 27", macos_readme)
        self.assertNotIn("macOS 11", macos_readme)
        self.assertIn("not notarized", macos_readme)
        self.assertIn("Open Anyway", macos_readme)
        self.assertIn("support.apple.com/en-us/102445", macos_readme)
        self.assertNotIn("Right-click", macos_readme)
        linux_readme = (root / "packaging/linux/README.md").read_text(encoding="utf-8")
        self.assertIn("./start.sh", linux_readme)
        self.assertIn("guided menu", linux_readme)
        self.assertIn("no default app", linux_readme)
        self.assertIn("sha256sum -c", linux_readme)
        from scripts import macos_client_package
        self.assertEqual(macos_client_package.format_version(
            macos_client_package.DOCUMENTED_MACOS_FLOOR), "27.0")


if __name__ == "__main__":
    unittest.main()
