import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from client import suite
from scripts import finalize_test_suite_v1

ROOT_DIR = Path(__file__).resolve().parents[2]


class SuiteFinalizerTests(unittest.TestCase):
    def _review_payload(self, *, include_local_paths: bool = True) -> dict:
        manifest = suite.load_default_suite_manifest()
        clips = []
        canonical_root = ROOT_DIR / "client" / "resources" / "test_suite_v1" / "canonical"
        for clip in manifest.clips:
            entry = {
                "id": clip.clip_id,
                "fileName": clip.file_name,
                "displayName": clip.display_name,
                "contentClass": clip.canonical_content_class,
                "payloadContentClass": clip.payload_content_class,
                "description": clip.description,
                "source": {
                    "kind": str(clip.provenance.get("kind") or "project-generated"),
                    "provenance": str(clip.provenance.get("provenance") or "Reviewed project-owned reference."),
                    "license": str(clip.provenance.get("license") or "CC0-1.0"),
                    "reviewed": True,
                    "redistributionApproved": True,
                },
            }
            if include_local_paths:
                entry["localPath"] = str((canonical_root / clip.file_name).resolve())
            clips.append(entry)
        return {
            "schemaVersion": 1,
            "suiteId": "encodingdb-test-suite",
            "suiteVersion": suite.SUITE_VERSION,
            "displayName": "EncodingDB Test Suite v1",
            "defaultQuickClipId": suite.DEFAULT_QUICK_CLIP_ID,
            "suiteReview": {
                "reviewed": True,
                "reviewHash": "a" * 64,
                "reviewer": "test",
                "redistributionApproved": True,
                "distributionLicense": "CC0-1.0",
                "notes": "Reviewed in test fixture.",
            },
            "clips": clips,
        }

    def test_build_suite_payload_accepts_reviewed_project_generated_cc0_sources(self) -> None:
        review = self._review_payload()
        source_paths = finalize_test_suite_v1.source_clip_paths(review, ROOT_DIR)
        payload = finalize_test_suite_v1.build_suite_payload(review, 1, source_paths)

        self.assertEqual(len(payload["clips"]), 7)
        self.assertEqual(payload["clips"][0]["source"]["license"], "CC0-1.0")
        self.assertEqual(payload["clips"][0]["acquisition"]["kind"], "retained-original")
        self.assertNotIn("ffmpegLavfi", payload["clips"][0]["acquisition"])

    def test_build_suite_payload_requires_distribution_license(self) -> None:
        payload = self._review_payload()
        payload["suiteReview"]["distributionLicense"] = ""
        with self.assertRaises(RuntimeError):
            finalize_test_suite_v1.build_suite_payload(payload, 1, finalize_test_suite_v1.source_clip_paths(payload, ROOT_DIR))

    def test_build_suite_payload_rejects_escaping_file_name(self) -> None:
        review = self._review_payload()
        review["clips"][0]["fileName"] = "../outside.mkv"
        source_paths = finalize_test_suite_v1.source_clip_paths(review, ROOT_DIR)
        with self.assertRaisesRegex(RuntimeError, "safe basename"):
            finalize_test_suite_v1.build_suite_payload(review, 1, source_paths)

    def test_source_clip_paths_resolves_from_source_dir_without_local_paths(self) -> None:
        review = self._review_payload(include_local_paths=False)
        source_dir = ROOT_DIR / "client" / "resources" / "test_suite_v1" / "canonical"

        resolved = finalize_test_suite_v1.source_clip_paths(review, ROOT_DIR, source_dir)

        self.assertEqual(len(resolved), 7)
        self.assertTrue(all(path.exists() for path in resolved.values()))

    def test_default_output_paths_target_repo_resources(self) -> None:
        defaults = finalize_test_suite_v1.default_output_paths()
        self.assertEqual(defaults["client_manifest_out"], ROOT_DIR / "client" / "resources" / "test_suite_v1" / "manifest.json")
        self.assertEqual(defaults["server_lock_out"], ROOT_DIR / "server" / "resources" / "test_suite_v1" / "suite-lock.json")

    def test_write_json_file_overwrites_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "existing.json"
            path.write_text("{}", encoding="utf-8")
            finalize_test_suite_v1.write_json_file(path, {"value": 1})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"value": 1})

    def test_suite_drift_checker_passes_for_current_repo_state(self) -> None:
        subprocess.run(
            [sys.executable, str(ROOT_DIR / "scripts" / "test_suite_drift_check.py")],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_finalizer_replaces_outputs_and_copies_canonical_assets_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            client_root = root / "client" / "resources" / "test_suite_v1"
            server_root = root / "server" / "resources" / "test_suite_v1"
            client_root.mkdir(parents=True, exist_ok=True)
            server_root.mkdir(parents=True, exist_ok=True)
            source_dir = root / "sources"
            source_dir.mkdir(parents=True, exist_ok=True)
            review = self._review_payload(include_local_paths=False)
            for clip in review["clips"]:
                source_name = clip["fileName"]
                origin = ROOT_DIR / "client" / "resources" / "test_suite_v1" / "canonical" / source_name
                (source_dir / source_name).write_bytes(origin.read_bytes())
            review_path = root / "review.json"
            review_path.write_text(json.dumps(review), encoding="utf-8")

            command = [
                sys.executable,
                str(ROOT_DIR / "scripts" / "finalize_test_suite_v1.py"),
                "--review-json",
                str(review_path),
                "--source-dir",
                str(source_dir),
                "--client-manifest-out",
                str(client_root / "manifest.json"),
                "--server-manifest-out",
                str(server_root / "manifest.json"),
                "--client-lock-out",
                str(client_root / "suite-lock.json"),
                "--server-lock-out",
                str(server_root / "suite-lock.json"),
                "--client-status-out",
                str(client_root / "finalization-status.json"),
                "--server-status-out",
                str(server_root / "finalization-status.json"),
            ]

            subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            with open(client_root / "manifest.json", "r", encoding="utf-8") as handle:
                client_manifest = json.load(handle)
            with open(server_root / "manifest.json", "r", encoding="utf-8") as handle:
                server_manifest = json.load(handle)
            self.assertEqual(client_manifest, server_manifest)
            self.assertEqual(client_manifest["redistribution"]["spdxExpression"], "CC0-1.0")
            self.assertTrue((client_root / "canonical" / client_manifest["clips"][0]["fileName"]).exists())
            self.assertTrue((server_root / "canonical" / server_manifest["clips"][0]["fileName"]).exists())


if __name__ == "__main__":
    unittest.main()
