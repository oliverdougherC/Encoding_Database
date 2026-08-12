import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from client import suite
from scripts import finalize_test_suite_v1

ROOT_DIR = Path(__file__).resolve().parents[2]


class SuiteFinalizerTests(unittest.TestCase):
    def _expected_media(self, clip: suite.SuiteClip) -> dict:
        return {
            "allowedContainers": [str(clip.acquisition.get("container") or "mkv")],
            "allowedVideoCodecs": [str(clip.acquisition.get("videoCodec") or "ffv1")],
            "width": clip.media.width,
            "height": clip.media.height,
            "frameRate": {
                "numerator": clip.media.frame_rate_num,
                "denominator": clip.media.frame_rate_den,
            },
            "fieldOrder": clip.media.field_order,
            "pixelFormat": clip.media.pixel_format,
            "bitDepth": clip.media.bit_depth,
            "chromaSubsampling": clip.media.chroma_subsampling,
            "colorPrimaries": clip.media.color_primaries,
            "colorTransfer": clip.media.color_transfer,
            "colorMatrix": clip.media.color_matrix,
            "colorRange": clip.media.color_range,
            "hdrMetadata": clip.media.hdr_metadata,
            "frameCount": clip.media.frame_count,
            "duration": {
                "numerator": clip.media.duration_num,
                "denominator": clip.media.duration_den,
            },
        }

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
                "expectedMedia": self._expected_media(clip),
            }
            if include_local_paths:
                entry["localPath"] = str((canonical_root / clip.file_name).resolve())
            clips.append(entry)
        payload = {
            "schemaVersion": 1,
            "suiteId": "encodingdb-test-suite",
            "suiteVersion": suite.SUITE_VERSION,
            "displayName": "EncodingDB Test Suite v1",
            "defaultQuickClipId": suite.DEFAULT_QUICK_CLIP_ID,
            "suiteReview": {
                "reviewed": True,
                "reviewHash": "",
                "reviewer": "test",
                "redistributionApproved": True,
                "distributionLicense": "CC0-1.0",
                "notes": "Reviewed in test fixture.",
            },
            "clips": clips,
        }
        payload["suiteReview"]["reviewHash"] = finalize_test_suite_v1.build_review_hash(payload)
        return payload

    def _probed_media(self, clip: suite.SuiteClip) -> dict:
        expected = self._expected_media(clip)
        return {
            "container": expected["allowedContainers"][0],
            "videoCodec": expected["allowedVideoCodecs"][0],
            "frameCount": clip.media.frame_count,
            "duration": {
                "numerator": clip.media.duration_num,
                "denominator": clip.media.duration_den,
            },
            "frameRate": {
                "numerator": clip.media.frame_rate_num,
                "denominator": clip.media.frame_rate_den,
            },
            "width": clip.media.width,
            "height": clip.media.height,
            "pixelFormat": clip.media.pixel_format,
            "bitDepth": clip.media.bit_depth,
            "chromaSubsampling": clip.media.chroma_subsampling,
            "colorPrimaries": clip.media.color_primaries,
            "colorTransfer": clip.media.color_transfer,
            "colorMatrix": clip.media.color_matrix,
            "colorRange": clip.media.color_range,
            "fieldOrder": clip.media.field_order,
            "hdrMetadata": clip.media.hdr_metadata,
        }

    def test_build_suite_payload_accepts_reviewed_project_generated_cc0_sources(self) -> None:
        review = self._review_payload()
        source_paths = finalize_test_suite_v1.source_clip_paths(review, ROOT_DIR)
        manifest = suite.load_default_suite_manifest()
        probe_by_id = {clip.clip_id: self._probed_media(clip) for clip in manifest.clips}

        with mock.patch.object(
            finalize_test_suite_v1,
            "probe_media_contract",
            side_effect=lambda path: probe_by_id[Path(path).stem],
        ):
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

    def test_build_suite_payload_requires_matching_review_hash(self) -> None:
        payload = self._review_payload()
        payload["suiteReview"]["reviewHash"] = "a" * 64

        with self.assertRaisesRegex(RuntimeError, "reviewHash does not match"):
            finalize_test_suite_v1.build_suite_payload(payload, 1, finalize_test_suite_v1.source_clip_paths(payload, ROOT_DIR))

    def test_build_suite_payload_rejects_media_outside_expected_contract(self) -> None:
        payload = self._review_payload()
        payload["clips"][0]["expectedMedia"]["width"] += 1
        payload["suiteReview"]["reviewHash"] = finalize_test_suite_v1.build_review_hash(payload)
        manifest = suite.load_default_suite_manifest()
        probe_by_id = {clip.clip_id: self._probed_media(clip) for clip in manifest.clips}

        with mock.patch.object(
            finalize_test_suite_v1,
            "probe_media_contract",
            side_effect=lambda path: probe_by_id[Path(path).stem],
        ):
            with self.assertRaisesRegex(RuntimeError, "width mismatch"):
                finalize_test_suite_v1.build_suite_payload(payload, 1, finalize_test_suite_v1.source_clip_paths(payload, ROOT_DIR))

    def test_build_suite_payload_rejects_escaping_file_name(self) -> None:
        review = self._review_payload()
        review["clips"][0]["fileName"] = "../outside.mkv"
        review["suiteReview"]["reviewHash"] = finalize_test_suite_v1.build_review_hash(review)
        source_paths = finalize_test_suite_v1.source_clip_paths(review, ROOT_DIR)
        manifest = suite.load_default_suite_manifest()
        probe_by_id = {clip.clip_id: self._probed_media(clip) for clip in manifest.clips}
        with mock.patch.object(
            finalize_test_suite_v1,
            "probe_media_contract",
            side_effect=lambda path: probe_by_id[Path(path).stem],
        ):
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
        self.assertEqual(defaults["client_pack_manifest_out"], ROOT_DIR / "client" / "resources" / "test_suite_v1" / "suite-pack.json")

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

    def test_finalizer_stages_outputs_and_copies_canonical_assets_with_pack_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            client_root = root / "client" / "resources" / "test_suite_v1"
            server_root = root / "server" / "resources" / "test_suite_v1"
            client_root.mkdir(parents=True, exist_ok=True)
            server_root.mkdir(parents=True, exist_ok=True)
            source_dir = root / "sources"
            source_dir.mkdir(parents=True, exist_ok=True)
            review = self._review_payload(include_local_paths=False)
            manifest = suite.load_default_suite_manifest()
            probe_by_id = {clip.clip_id: self._probed_media(clip) for clip in manifest.clips}
            for clip in review["clips"]:
                source_name = clip["fileName"]
                origin = ROOT_DIR / "client" / "resources" / "test_suite_v1" / "canonical" / source_name
                (source_dir / source_name).write_bytes(origin.read_bytes())
            source_paths = finalize_test_suite_v1.source_clip_paths(review, ROOT_DIR, source_dir)
            with mock.patch.object(
                finalize_test_suite_v1,
                "probe_media_contract",
                side_effect=lambda path: probe_by_id[Path(path).stem],
            ), mock.patch.object(
                suite,
                "verify_suite_clip",
                side_effect=lambda path, clip: suite.ClipVerificationResult(True, "ok", {"path": path, "clipId": clip.clip_id}),
            ):
                manifest_payload = finalize_test_suite_v1.build_suite_payload(review, 1, source_paths)
                lock_payload = finalize_test_suite_v1.build_lock_payload(manifest_payload, review["suiteReview"]["reviewHash"])
                status_payload = finalize_test_suite_v1.build_status_payload("suite-lock.json", manifest_payload["suiteVersion"])

                with tempfile.TemporaryDirectory(prefix="encodingdb-suite-stage-test-") as staging_root:
                    staging_root_path = Path(staging_root)
                    for tree_label in ("client", "server"):
                        suite_root = staging_root_path / tree_label
                        suite_root.mkdir(parents=True, exist_ok=True)
                        finalize_test_suite_v1.write_json_file(suite_root / "manifest.json", manifest_payload)
                        finalize_test_suite_v1.write_json_file(suite_root / "finalization-status.json", status_payload)
                        finalize_test_suite_v1.write_json_file(suite_root / "suite-lock.json", lock_payload)
                        canonical_dir = suite_root / "canonical"
                        canonical_dir.mkdir(parents=True, exist_ok=True)
                        for clip in manifest_payload["clips"]:
                            shutil.copy2(source_paths[str(clip["id"])], canonical_dir / str(clip["fileName"]))
                        suite.write_suite_pack_metadata(str(suite_root))
                    with open(staging_root_path / "client" / "suite-pack.json", "r", encoding="utf-8") as handle:
                        pack_manifest_payload = json.load(handle)
                    replacements = finalize_test_suite_v1.stage_outputs(
                        staging_root=staging_root_path,
                        manifest_payload=manifest_payload,
                        lock_payload=lock_payload,
                        status_payload=status_payload,
                        pack_manifest_payload=pack_manifest_payload,
                        client_manifest_out=client_root / "manifest.json",
                        server_manifest_out=server_root / "manifest.json",
                        client_lock_out=client_root / "suite-lock.json",
                        server_lock_out=server_root / "suite-lock.json",
                        client_status_out=client_root / "finalization-status.json",
                        server_status_out=server_root / "finalization-status.json",
                        client_pack_manifest_out=client_root / "suite-pack.json",
                        server_pack_manifest_out=server_root / "suite-pack.json",
                        source_paths=source_paths,
                    )
                    finalize_test_suite_v1.commit_replacements(replacements)

            with open(client_root / "manifest.json", "r", encoding="utf-8") as handle:
                client_manifest = json.load(handle)
            with open(server_root / "manifest.json", "r", encoding="utf-8") as handle:
                server_manifest = json.load(handle)
            self.assertEqual(client_manifest, server_manifest)
            self.assertEqual(client_manifest["redistribution"]["spdxExpression"], "CC0-1.0")
            with open(client_root / "suite-pack.json", "r", encoding="utf-8") as handle:
                client_pack = json.load(handle)
            with open(server_root / "suite-pack.json", "r", encoding="utf-8") as handle:
                server_pack = json.load(handle)
            self.assertEqual(client_pack, server_pack)
            self.assertEqual(client_pack["distributionMode"], "external-suite-pack")
            self.assertTrue((client_root / "canonical" / client_manifest["clips"][0]["fileName"]).exists())
            self.assertTrue((server_root / "canonical" / server_manifest["clips"][0]["fileName"]).exists())


if __name__ == "__main__":
    unittest.main()
