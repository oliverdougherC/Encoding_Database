import tempfile
import unittest
from dataclasses import replace

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

    def test_ensure_suite_clip_generates_and_verifies_valid_clip(self) -> None:
        manifest = suite.load_default_suite_manifest()
        clip = suite.get_default_quick_clip(manifest)
        with tempfile.TemporaryDirectory() as cache_root:
            prepared = suite.ensure_suite_clip(clip, cache_root=cache_root)
            verified = suite.verify_suite_clip(prepared.path, clip)

        self.assertTrue(verified.ok)
        self.assertEqual(prepared.suite_version, suite.SUITE_VERSION)
        self.assertEqual(prepared.workload_id, clip.clip_id)
        self.assertEqual(prepared.canonical_content_class, clip.canonical_content_class)

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
