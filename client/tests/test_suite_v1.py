import json
import subprocess
from contextlib import contextmanager
import tempfile
import tarfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from client import suite


@contextmanager
def small_media_fixture():
    """Synthetic unit-test media only; never writes production suite resources."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "canonical").mkdir()
        payload = suite._build_manifest_seed()
        payload["defaultQuickClipId"] = payload["clips"][0]["id"]
        prototype = root / "prototype.mkv"
        subprocess.run(suite._generation_command("color=size=32x32:rate=24", str(prototype), 2), check=True)
        for clip in payload["clips"]:
            path = root / "canonical" / clip["fileName"]
            path.write_bytes(prototype.read_bytes())
            clip["sha256"] = suite._sha256_of_file(str(path))
            clip["byteSize"] = path.stat().st_size
            clip["media"].update(width=32, height=32, frameCount=2, duration={"numerator": 1, "denominator": 12})
        (root / "manifest.json").write_text(json.dumps(payload))
        (root / "finalization-status.json").write_text(json.dumps({"isFrozen": False, "distribution": "development-only"}))
        suite.write_suite_pack_metadata(str(root))
        with mock.patch.object(suite, "_manifest_resource_candidates", return_value=[str(root / "manifest.json")]):
            yield root, suite.manifest_from_payload(payload)


class SuiteV1Tests(unittest.TestCase):
    def test_manifest_declares_all_required_classes(self) -> None:
        manifest = suite.load_default_suite_manifest()
        self.assertEqual(manifest.suite_version, suite.SUITE_VERSION)
        self.assertEqual(len(manifest.clips), 7)
        self.assertEqual(
            {clip.canonical_content_class for clip in manifest.clips},
            set(suite.REQUIRED_CONTENT_CLASSES),
        )

    def test_finalization_status_declares_frozen_reviewed_suite(self) -> None:
        status = suite.load_finalization_status()
        self.assertTrue(status["isFrozen"])
        self.assertEqual(status["finalLockPath"], "suite-lock.json")
        lock = suite.load_suite_lock()
        self.assertEqual(lock["suiteVersion"], suite.SUITE_VERSION)
        import hashlib
        fingerprint = lock["fingerprint"]
        unsigned = {key: value for key, value in lock.items() if key != "fingerprint"}
        self.assertEqual(fingerprint, hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest())
        raw_manifest = json.loads(Path(suite.get_manifest_path()).read_text())
        self.assertEqual(lock["manifestSha256"], hashlib.sha256(json.dumps(raw_manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest())
        manifest = suite.load_default_suite_manifest()
        for clip in manifest.clips:
            self.assertEqual(clip.acquisition["kind"], "retained-original")
            self.assertNotIn("ffmpegLavfi", clip.acquisition)
            self.assertTrue(clip.provenance["reviewed"])
            self.assertTrue(clip.provenance["redistributionApproved"])

    def test_verify_suite_clip_reports_missing_clip(self) -> None:
        manifest = suite.load_default_suite_manifest()
        clip = manifest.clips[0]
        result = suite.verify_suite_clip("/tmp/does-not-exist-suite-v1.mkv", clip)
        self.assertFalse(result.ok)
        self.assertIn("not found", result.message)

    def test_verify_suite_clip_reports_hash_mismatch(self) -> None:
        with small_media_fixture() as (fixture_root, manifest):
            clip = manifest.clips[0]
            with tempfile.TemporaryDirectory() as cache_root:
                prepared = suite.ensure_suite_clip(clip, cache_root=cache_root)
                mismatched = replace(clip, sha256="0" * 64)
                result = suite.verify_suite_clip(prepared.path, mismatched)

            self.assertFalse(result.ok)
            self.assertIn("checksum mismatch", result.message)


    def test_verify_suite_clip_reports_metadata_mismatch(self) -> None:
        with small_media_fixture() as (fixture_root, manifest):
            clip = manifest.clips[0]
            with tempfile.TemporaryDirectory() as cache_root:
                prepared = suite.ensure_suite_clip(clip, cache_root=cache_root)
                mismatched = replace(clip, media=replace(clip.media, frame_count=clip.media.frame_count + 1))
                result = suite.verify_suite_clip(prepared.path, mismatched)

            self.assertFalse(result.ok)
            self.assertIn("frameCount mismatch", result.message)


    def test_ensure_suite_clip_copies_and_verifies_frozen_packaged_clip(self) -> None:
        with small_media_fixture() as (fixture_root, manifest):
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

    def test_suite_pack_uses_platform_stable_stored_gzip(self) -> None:
        with small_media_fixture() as (fixture_root, manifest):
            source_suite_root = Path(suite.get_manifest_path()).parent
            with tempfile.TemporaryDirectory() as temp_dir:
                first = Path(temp_dir) / "first.tar.gz"
                second = Path(temp_dir) / "second.tar.gz"
                suite.build_suite_pack_archive(str(source_suite_root), str(first))
                suite.build_suite_pack_archive(str(source_suite_root), str(second))

                self.assertEqual(first.read_bytes(), second.read_bytes())
                # XFL=0 identifies stored/no-compression gzip output; OS=255 is portable.
                self.assertEqual(first.read_bytes()[8:10], b"\x00\xff")
                with tarfile.open(first, "r:gz") as archive:
                    self.assertIn("manifest.json", archive.getnames())


    def test_ensure_suite_clip_can_materialize_from_external_suite_pack_without_packaged_canonical_media(self) -> None:
        with small_media_fixture() as (fixture_root, manifest):
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



class SuiteDistributionFailureTests(unittest.TestCase):
    def _metadata(self, data):
        import hashlib
        return {"distribution": {"byteSize": len(data), "sha256": hashlib.sha256(data).hexdigest()}}

    def test_missing_and_corrupt_archive_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pack"
            self.assertFalse(suite._verify_suite_pack_file(str(path), self._metadata(b"good")).ok)
            path.write_bytes(b"evil")
            self.assertFalse(suite._verify_suite_pack_file(str(path), self._metadata(b"good")).ok)

    def test_interrupted_download_resumes_without_exposing_partial_destination(self):
        data = b"firstsecond"
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "pack"
            def interrupted(**kwargs):
                yield b"first"
                raise ConnectionError("interrupted")
            first = mock.Mock(status_code=200)
            first.iter_content.side_effect = interrupted
            second = mock.Mock(status_code=206)
            second.iter_content.return_value = [b"second"]
            requests = mock.Mock()
            requests.get.side_effect = [first, second]
            with mock.patch.object(suite, "_load_requests", return_value=requests):
                with self.assertRaises(ConnectionError):
                    suite._download_suite_pack("https://example.org/pack", str(destination), self._metadata(data))
                self.assertFalse(destination.exists())
                suite._download_suite_pack("https://example.org/pack", str(destination), self._metadata(data))
            self.assertEqual(destination.read_bytes(), data)
            self.assertEqual(requests.get.call_args.kwargs["headers"], {"Range": "bytes=5-"})
            self.assertFalse(Path(str(destination) + ".part").exists())

    def test_unsafe_archive_never_materializes(self):
        import io
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.tar.gz"
            with tarfile.open(path, "w:gz") as archive:
                entry = tarfile.TarInfo("../escaped")
                entry.size = 1
                archive.addfile(entry, io.BytesIO(b"x"))
            with self.assertRaisesRegex(RuntimeError, "unsafe"):
                suite._extract_suite_pack(str(path), {"suiteFingerprint": "test"}, directory)
            self.assertFalse((Path(directory) / ".suite-pack/test").exists())
            self.assertFalse((Path(directory) / ".suite-pack/escaped").exists())

    def test_frozen_notices_required_and_inventory_bound(self):
        import json
        manifest = suite.load_default_suite_manifest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "finalization-status.json").write_text(json.dumps({"isFrozen": True}))
            with self.assertRaisesRegex(RuntimeError, "notice"):
                suite._suite_notice_entries(manifest, directory)
            (root / "notices").mkdir()
            for clip in manifest.clips:
                (root / "notices" / f"{clip.clip_id}.txt").write_text("Attribution and license")
            entries = suite._suite_notice_entries(manifest, directory)
            self.assertEqual(len(entries), 7)
            with self.assertRaisesRegex(RuntimeError, "frozen"):
                suite.write_manifest(str(root / "manifest.json"))

    def test_notice_tampering_rejected_and_valid_extraction_reused(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            root.mkdir()
            payload = json.loads(Path(suite.get_manifest_path()).read_text())
            import hashlib
            for clip in payload["clips"]:
                clip["sha256"] = hashlib.sha256(b"fixture").hexdigest()
                clip["byteSize"] = len(b"fixture")
            (root / "manifest.json").write_text(json.dumps(payload))
            (root / "finalization-status.json").write_text(json.dumps({"isFrozen": True}))
            (root / "notices").mkdir()
            (root / "canonical").mkdir()
            for clip in payload["clips"]:
                (root / "notices" / f"{clip['id']}.txt").write_text("Fixture license notice")
                (root / "canonical" / clip["fileName"]).write_bytes(b"fixture")
            metadata = suite.build_suite_pack_metadata(str(root))
            archive = Path(directory) / "suite.tar.gz"
            suite.build_suite_pack_archive(str(root), str(archive))
            with mock.patch.object(suite, "verify_suite_clip", return_value=suite.ClipVerificationResult(True, "fixture media verification", {})):
                canonical = Path(suite._extract_suite_pack(str(archive), metadata, directory))
                with mock.patch.object(tarfile, "open", side_effect=AssertionError("must reuse verified cache")):
                    self.assertEqual(suite._extract_suite_pack(str(archive), metadata, directory), str(canonical))
                notice = next((canonical.parent / "notices").iterdir())
                notice.write_text("corrupt")
                with self.assertRaisesRegex(RuntimeError, "notice hash mismatch"):
                    suite._verify_extracted_suite_pack(str(canonical.parent), metadata)
                suite._extract_suite_pack(str(archive), metadata, directory)
                self.assertEqual(notice.read_text(), "Fixture license notice")

    def test_cached_pack_checks_all_bytes_without_reprobing_and_repairs_corruption(self):
        with small_media_fixture() as (root, manifest):
            (root / "suite-lock.json").write_text('{}')
            (root / "notices").mkdir()
            (root / "notices/fixture.txt").write_text('Fixture notice')
            suite.write_suite_pack_metadata(str(root))
            metadata = suite.load_suite_pack_metadata(str(root / "suite-pack.json"))
            archive = root / "fixture.tar.gz"
            suite.build_suite_pack_archive(str(root), str(archive))
            cache = root / "cache"
            with mock.patch.object(suite, "_probe_clip", wraps=suite._probe_clip) as probe:
                canonical = Path(suite._extract_suite_pack(str(archive), metadata, str(cache)))
                self.assertEqual(probe.call_count, len(manifest.clips))
            with mock.patch.object(suite, "_probe_clip", side_effect=AssertionError("identical cached bytes must not be re-probed")), mock.patch.object(suite, "_sha256_of_file", wraps=suite._sha256_of_file) as hashes:
                suite._extract_suite_pack(str(archive), metadata, str(cache))
                hashed_paths = {call.args[0] for call in hashes.call_args_list}
                for clip in manifest.clips:
                    self.assertIn(str(canonical / clip.file_name), hashed_paths)
                self.assertIn(str(canonical.parent / "manifest.json"), hashed_paths)
                self.assertIn(str(canonical.parent / "finalization-status.json"), hashed_paths)
            damaged = canonical / manifest.clips[-1].file_name
            data = damaged.read_bytes()
            damaged.write_bytes(bytes([data[0] ^ 255]) + data[1:])
            with mock.patch.object(suite, "_probe_clip", wraps=suite._probe_clip) as probe:
                suite._extract_suite_pack(str(archive), metadata, str(cache))
                self.assertEqual(probe.call_count, len(manifest.clips))
            self.assertEqual(damaged.read_bytes(), data)
            for name in ("manifest.json", "finalization-status.json", "suite-lock.json", "notices/fixture.txt"):
                path = canonical.parent / name
                original = path.read_bytes()
                path.write_bytes(bytes([original[0] ^ 255]) + original[1:])
                with mock.patch.object(suite, "_probe_clip", wraps=suite._probe_clip) as probe:
                    suite._extract_suite_pack(str(archive), metadata, str(cache))
                    self.assertEqual(probe.call_count, len(manifest.clips))
                self.assertEqual(path.read_bytes(), original)
            requested = manifest.clips[0]
            invalid_contract = replace(requested, media=replace(requested.media, width=requested.media.width + 1))
            result = suite.verify_suite_clip(str(canonical / requested.file_name), invalid_contract)
            self.assertFalse(result.ok)
            self.assertIn("width mismatch", result.message)
            with mock.patch.dict("os.environ", {"ENCODINGDB_SUITE_PACK_PATH": str(archive)}, clear=False):
                with self.assertRaisesRegex(RuntimeError, "width mismatch"):
                    suite._materialize_clip_from_suite_pack(invalid_contract, metadata, str(cache))

    def test_initial_extraction_rejects_wrong_media_contract_even_with_matching_hashes(self):
        with small_media_fixture() as (root, manifest):
            payload = json.loads((root / "manifest.json").read_text())
            payload["clips"][0]["media"]["width"] += 1
            (root / "manifest.json").write_text(json.dumps(payload))
            metadata = suite.build_suite_pack_metadata(str(root))
            archive = root / "invalid-contract.tar.gz"
            suite.build_suite_pack_archive(str(root), str(archive))
            with self.assertRaisesRegex(RuntimeError, "width mismatch"):
                suite._extract_suite_pack(str(archive), metadata, str(root / "cache"))
            self.assertFalse(Path(suite._suite_pack_extract_root(metadata, str(root / "cache"))).exists())

    def test_materializer_installs_both_trees_and_rejects_metadata_mismatch(self):
        import json
        import shutil
        from scripts import materialize_final_suite
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            roots = [repo / "client/resources/test_suite_v1", repo / "server/resources/test_suite_v1"]
            extracted = repo / "extracted"
            extracted.mkdir()
            (extracted / "canonical").mkdir()
            (extracted / "canonical/clip.mkv").write_bytes(b"verified fixture")
            (extracted / "notices").mkdir()
            (extracted / "notices/clip.txt").write_text("Attribution")
            metadata = {"suiteFingerprint": "fixture"}
            for name, data in (("manifest.json", {}), ("suite-lock.json", {}), ("finalization-status.json", {"isFrozen": True})):
                (extracted / name).write_text(json.dumps(data))
            for root in roots:
                root.mkdir(parents=True)
                for name in ("manifest.json", "suite-lock.json", "finalization-status.json"):
                    shutil.copyfile(extracted / name, root / name)
                (root / "suite-pack.json").write_text(json.dumps(metadata))
            with mock.patch.object(suite, "_ensure_suite_pack_available", return_value="verified-pack"), mock.patch.object(suite, "_extract_suite_pack", return_value=str(extracted / "canonical")):
                materialize_final_suite.materialize(repo)
                materialize_final_suite.materialize(repo)
                for root in roots:
                    self.assertEqual((root / "canonical/clip.mkv").read_bytes(), b"verified fixture")
                    self.assertEqual((root / "notices/clip.txt").read_text(), "Attribution")
                original_replace = materialize_final_suite.os.replace
                calls = []
                def fail_during_install(source, destination):
                    calls.append(str(source))
                    if len(calls) == 3:
                        raise OSError("simulated installation interruption")
                    return original_replace(source, destination)
                with mock.patch.object(materialize_final_suite.os, "replace", side_effect=fail_during_install):
                    with self.assertRaisesRegex(OSError, "interruption"):
                        materialize_final_suite.materialize(repo)
                for root in roots:
                    self.assertEqual((root / "canonical/clip.mkv").read_bytes(), b"verified fixture")
                    self.assertEqual((root / "notices/clip.txt").read_text(), "Attribution")
                (roots[1] / "suite-pack.json").write_text("{}")
                with self.assertRaisesRegex(RuntimeError, "metadata differs"):
                    materialize_final_suite.materialize(repo)


if __name__ == "__main__":
    unittest.main()
