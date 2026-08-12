import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from client import suite


class SuiteV1Tests(unittest.TestCase):
    def test_manifest_declares_all_required_classes(self) -> None:
        manifest = suite.load_default_suite_manifest()
        self.assertEqual(manifest.suite_version, suite.SUITE_VERSION)
        self.assertEqual(len(manifest.clips), 7)
        self.assertEqual(
            {clip.canonical_content_class for clip in manifest.clips},
            set(suite.REQUIRED_CONTENT_CLASSES),
        )

    def test_finalization_status_declares_development_only_unfrozen_suite(self) -> None:
        status = suite.load_finalization_status()
        self.assertEqual(status["distribution"], "development-only")
        self.assertFalse(status["isFrozen"])
        self.assertIsNone(status["finalLockPath"])

    def test_verify_suite_clip_reports_missing_clip(self) -> None:
        manifest = suite.load_default_suite_manifest()
        clip = manifest.clips[0]
        result = suite.verify_suite_clip("/tmp/does-not-exist-suite-v1.mkv", clip)
        self.assertFalse(result.ok)
        self.assertIn("not found", result.message)

    def test_verify_suite_clip_reports_hash_mismatch(self) -> None:
        manifest = suite.load_default_suite_manifest()
        clip = manifest.clips[0]
        with tempfile.TemporaryDirectory() as cache_root:
            prepared = suite.ensure_suite_clip(clip, cache_root=cache_root)
            mismatched = replace(clip, sha256="0" * 64)
            result = suite.verify_suite_clip(prepared.path, mismatched)

        self.assertFalse(result.ok)
        self.assertIn("checksum mismatch", result.message)

    def test_verify_suite_clip_reports_metadata_mismatch(self) -> None:
        manifest = suite.load_default_suite_manifest()
        clip = manifest.clips[0]
        with tempfile.TemporaryDirectory() as cache_root:
            prepared = suite.ensure_suite_clip(clip, cache_root=cache_root)
            mismatched = replace(clip, media=replace(clip.media, frame_count=clip.media.frame_count + 1))
            result = suite.verify_suite_clip(prepared.path, mismatched)

        self.assertFalse(result.ok)
        self.assertIn("frameCount mismatch", result.message)

    def test_ensure_suite_clip_copies_and_verifies_frozen_packaged_clip(self) -> None:
        manifest = suite.load_default_suite_manifest()
        clip = suite.get_default_quick_clip(manifest)
        with tempfile.TemporaryDirectory() as cache_root:
            prepared = suite.ensure_suite_clip(clip, cache_root=cache_root)
            verified = suite.verify_suite_clip(prepared.path, clip)

        self.assertTrue(verified.ok)
        self.assertEqual(prepared.suite_version, suite.SUITE_VERSION)
        self.assertEqual(prepared.workload_id, clip.clip_id)
        self.assertEqual(prepared.canonical_content_class, clip.canonical_content_class)

    def test_all_packaged_canonical_assets_match_the_frozen_manifest(self) -> None:
        manifest = suite.load_default_suite_manifest()
        prepared = suite.ensure_suite(manifest)

        self.assertEqual(len(prepared), 7)
        for prepared_clip, manifest_clip in zip(prepared, manifest.clips):
            self.assertIn("resources/test_suite_v1/canonical", prepared_clip.path.replace("\\", "/"))
            self.assertTrue(suite.verify_suite_clip(prepared_clip.path, manifest_clip).ok)

    def test_checked_in_suite_pack_metadata_matches_current_suite_resources(self) -> None:
        suite.verify_suite_pack_metadata(
            str(Path(suite.get_manifest_path()).parent),
            suite.load_suite_pack_metadata(),
        )

    def test_ensure_suite_clip_can_materialize_from_external_suite_pack_without_packaged_canonical_media(self) -> None:
        manifest = suite.load_default_suite_manifest()
        clip = manifest.clips[0]
        source_suite_root = Path(suite.get_manifest_path()).parent
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            packaged_resources = root / "resources" / "test_suite_v1"
            packaged_resources.mkdir(parents=True, exist_ok=True)
            for name in ("manifest.json", "finalization-status.json", "suite-pack.json"):
                (packaged_resources / name).write_bytes((source_suite_root / name).read_bytes())
            pack_path = root / suite.DEFAULT_SUITE_PACK_FILE_NAME
            suite.build_suite_pack_archive(str(source_suite_root), str(pack_path))
            with mock.patch.object(suite, "_manifest_resource_candidates", return_value=[str(packaged_resources / "manifest.json")]), \
                    mock.patch.dict("os.environ", {"ENCODINGDB_SUITE_PACK_PATH": str(pack_path)}, clear=False):
                prepared = suite.ensure_suite_clip(clip, cache_root=str(root / "cache"))

            self.assertIn("/cache/canonical/", prepared.path.replace("\\", "/"))
            self.assertTrue(Path(prepared.path).exists())
            self.assertTrue(suite.verify_suite_clip(prepared.path, clip).ok)

    def test_general_pl_coverage_requires_all_declared_classes(self) -> None:
        prepared = [
            suite.PreparedSuiteClip(
                suite_version=suite.SUITE_VERSION,
                clip_id=str(clip_id),
                canonical_content_class=content_class,
                payload_content_class="placeholder",
                workload_id=str(clip_id),
                path=f"/tmp/{clip_id}.mkv",
                input_hash="a" * 64,
                file_name=f"{clip_id}.mkv",
            )
            for clip_id, content_class in enumerate(suite.REQUIRED_CONTENT_CLASSES, start=1)
        ]
        self.assertTrue(suite.has_general_pl_coverage(prepared))
        self.assertFalse(suite.has_general_pl_coverage(prepared[:-1]))


if __name__ == "__main__":
    unittest.main()
