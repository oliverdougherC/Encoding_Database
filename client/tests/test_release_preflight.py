import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import release_manifest_lib


class ReleasePreflightTests(unittest.TestCase):
    def test_release_json_uses_canonical_suite_identity_before_freeze(self) -> None:
        payload = json.loads((release_manifest_lib.ROOT_DIR / "release.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["suiteVersion"], "encodingdb-test-suite-v1")
        self.assertIsNone(payload["projectVersion"])
        self.assertIsNone(payload["releaseDate"])

    def test_preflight_reports_every_requested_gate_and_retains_logs(self) -> None:
        script_path = release_manifest_lib.ROOT_DIR / "scripts" / "release_preflight.sh"
        bash_path = shutil.which("bash")
        self.assertIsNotNone(bash_path)

        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "scripts").mkdir(parents=True)
            (repo / "client" / "resources" / "test_suite_v1").mkdir(parents=True)
            (repo / "server" / "resources" / "test_suite_v1").mkdir(parents=True)
            (repo / "frontend").mkdir(parents=True)
            (repo / "tmp").mkdir()
            bin_dir = repo / "bin"
            bin_dir.mkdir()

            (repo / "scripts" / "release_preflight.sh").write_text(script_path.read_text(encoding="utf-8"), encoding="utf-8")
            (repo / "LICENSE").write_text("license\n", encoding="utf-8")
            (repo / "NOTICE").write_text("notice\n", encoding="utf-8")
            (repo / "README.md").write_text("EncodingDB release metadata test fixture\n", encoding="utf-8")
            (repo / "frontend" / "DEPLOYMENT.md").write_text("No deprecated Next.js references here.\n", encoding="utf-8")
            (repo / "CHANGELOG.md").write_text("## [Unreleased]\n\n- Pending freeze.\n", encoding="utf-8")
            (repo / "release.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "projectVersion": None,
                        "releaseDate": None,
                        "benchmarkProtocolVersion": "7.0",
                        "plFormulaVersion": "7.0",
                        "suiteVersion": "encodingdb-test-suite-v1",
                        "clientImplementationVersion": "client/0.2.0",
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            status_payload = {
                "distribution": "development-only",
                "finalLockPath": None,
                "isFrozen": False,
                "suiteVersion": "encodingdb-test-suite-v1",
            }
            for root_name in ("client", "server"):
                (repo / root_name / "resources" / "test_suite_v1" / "finalization-status.json").write_text(
                    json.dumps(status_payload, indent=2) + "\n",
                    encoding="utf-8",
                )

            for command_name in ("bash", "dirname", "mktemp", "python3", "rg", "rm", "sed"):
                target = shutil.which(command_name)
                self.assertIsNotNone(target, msg=f"{command_name} must be installed for this test")
                os.symlink(target, bin_dir / command_name)

            result = subprocess.run(
                [
                    bash_path,
                    str(repo / "scripts" / "release_preflight.sh"),
                    "metadata",
                    "production-compose",
                    "final-suite",
                ],
                cwd=repo,
                env={
                    "PATH": str(bin_dir),
                    "TMPDIR": str(repo / "tmp"),
                },
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("PASS metadata", result.stdout)
            self.assertIn("FAIL production-compose", result.stdout)
            self.assertIn("FAIL FINAL_TEST_SUITE_NOT_FROZEN", result.stdout)
            self.assertLess(result.stdout.index("PASS metadata"), result.stdout.index("FAIL production-compose"))
            self.assertLess(
                result.stdout.index("FAIL production-compose"),
                result.stdout.index("FAIL FINAL_TEST_SUITE_NOT_FROZEN"),
            )
            self.assertIn("Missing required command: docker", result.stderr)

            log_dir = None
            for line in result.stdout.splitlines():
                marker = "Retaining per-check logs in "
                if marker in line:
                    log_dir = Path(line.split(marker, 1)[1].strip())
                    break
            self.assertIsNotNone(log_dir)
            assert log_dir is not None
            self.assertTrue(log_dir.is_dir())
            self.assertTrue((log_dir / "metadata.log").exists())
            self.assertTrue((log_dir / "production-compose.log").exists())
            self.assertTrue((log_dir / "final-suite.log").exists())
            self.assertIn("FINAL_TEST_SUITE_NOT_FROZEN", (log_dir / "final-suite.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
