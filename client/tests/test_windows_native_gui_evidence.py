"""Synthetic verifier fixtures only; real GUI acceptance requires Windows CI."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[2] / "scripts/verify_windows_native_gui.py"
spec = importlib.util.spec_from_file_location("windows_evidence", MODULE)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class WindowsEvidenceTests(unittest.TestCase):
    def test_external_helper_cannot_pass_embedded_proof(self):
        lock = {name: {"sha256": name} for name in ("ffmpeg", "ffprobe")}
        payload = {"frozen": True, "platform": "win", "extractionRoot": r"C:\temp\_MEI123", "ffmpegPath": r"C:\temp\_MEI123\ffmpeg.exe", "ffprobePath": r"C:\temp\_MEI123\ffprobe.exe", "lockPath": r"C:\temp\_MEI123\runtime-lock.json", "identity": lock}
        verifier.verify_embedded(payload, lock)
        for field, value in (("ffmpegPath", r"C:\external\ffmpeg.exe"), ("lockPath", r"C:\external\lock.json"), ("frozen", False)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                verifier.verify_embedded({**payload, field: value}, lock)

    def campaign(self, root, completed=True):
        campaign = root / "campaigns/campaign-0123456789abcdef"
        campaign.mkdir(parents=True)
        manifest = {"protocolVersion": "7.1", "physicalSourceId": "TEST ONLY installation", "runtime": {"clientExecutionArchitecture": "x86_64", "ffmpeg": {"architectures": ["x86_64"]}, "ffprobe": {"architectures": ["x86_64"]}}, "tasks": [{"encoder": "libx264", "preset": "fast", "clipId": "clip-a"}]}
        (campaign / "manifest.json").write_text(json.dumps(manifest))
        if completed:
            (campaign / "campaign-complete.json").write_text(json.dumps({"failed": 0, "skipped": 0}))
        for number, phase in enumerate(("warmup", "measured", "measured")):
            artifact = campaign / f"artifact-{number}.mp4"
            artifact.write_bytes(b"SYNTHETIC verifier fixture, not media")
            record = {"schedule": {"campaign_id": campaign.name, "recipe_id": "recipe-a", "phase": phase}, "timing": {"elapsed_s": 2.0, "source_frame_count": 240, "encoded_frame_count": 240, "source_fps": 24}, "metadata": {"info": {"artifactPath": str(artifact), "artifactSha256": verifier.digest(artifact)}}}
            (campaign / f"attempt-{number:06d}.json").write_text(json.dumps(record))
        return campaign

    def test_complete_counts_and_canonical_coverage_are_required(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); self.campaign(root)
            summary = verifier.inspect_campaigns(root, ["clip-a"], True)
            self.assertEqual(summary["measuredAttempts"], 2)
            with self.assertRaisesRegex(ValueError, "coverage"):
                verifier.inspect_campaigns(root, ["clip-a", "clip-b"], True)

    def test_cancellation_preserves_completed_bytes_and_rejects_late_cancel(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); campaign = self.campaign(root, completed=False)
            verifier.inspect_campaigns(root, None, False)
            (campaign / "artifact-1.mp4").write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "bytes changed"):
                verifier.inspect_campaigns(root, None, False)
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); self.campaign(root)
            with self.assertRaisesRegex(ValueError, "after campaign completion"):
                verifier.inspect_campaigns(root, None, False)

    def test_missing_measured_attempt_or_invalid_timing_fails(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); campaign = self.campaign(root)
            (campaign / "attempt-000002.json").unlink()
            with self.assertRaisesRegex(ValueError, "two measured"):
                verifier.inspect_campaigns(root, None, True)
            record = json.loads((campaign / "attempt-000001.json").read_text())
            record["timing"]["elapsed_s"] = -1
            (campaign / "attempt-000001.json").write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "valid process timing"):
                verifier.inspect_campaigns(root, None, True)

    def test_preparation_stop_is_separate_from_measured_cancellation(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            queue = root / "queue"; queue.mkdir()
            pack = root / "suite.tar.gz"; pack.write_bytes(b"TEST ONLY source pack")
            for screenshot in ("source-preparation.png", "preparation-cancelled.png"):
                (root / screenshot).write_bytes(b"TEST ONLY screenshot existence fixture")
            phase = {"action": "Stop during preparation", "encoderObserved": False, "queue": str(queue), "path": str(root),
                     "preparationProbe": {"commandLine": "ffprobe -count_frames canonical.mkv", "path": r"C:\temp\_MEI123\ffprobe.exe", "sha256": "probe-hash"},
                     "sourcePackPath": str(pack), "sourcePackBefore": verifier.digest(pack), "sourcePackAfter": verifier.digest(pack)}
            locked = {"ffprobe": {"sha256": "probe-hash"}}
            result = verifier.verify_preparation_stop(phase, locked)
            self.assertEqual(result["measuredAttempts"], 0)
            self.assertTrue(result["preparationCancelled"])
            with self.assertRaisesRegex(ValueError, "after encoding"):
                verifier.verify_preparation_stop({**phase, "encoderObserved": True}, locked)
            campaign = queue / "campaigns/campaign-test"; campaign.mkdir(parents=True)
            (campaign / "manifest.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "created measured work"):
                verifier.verify_preparation_stop(phase, locked)
            (campaign / "manifest.json").unlink()
            pack.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "changed the delivered"):
                verifier.verify_preparation_stop(phase, locked)


    def test_blocked_gui_and_forced_cleanup_never_become_pass(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "receipt.json"
            path.write_text(json.dumps({"status": "BLOCKED"}))
            with self.assertRaisesRegex(ValueError, "required phases"):
                verifier.verify_receipt(path, {}, {})
            path.write_text(json.dumps({"status": "PENDING_EVIDENCE_VALIDATION", "cleanupForced": True}))
            with self.assertRaisesRegex(ValueError, "forced process cleanup"):
                verifier.verify_receipt(path, {}, {})


if __name__ == "__main__":
    unittest.main()
