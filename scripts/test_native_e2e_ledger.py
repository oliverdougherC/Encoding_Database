import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('ledger', Path(__file__).with_name('native-e2e-ledger.py'))
ledger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger)


class LedgerTests(unittest.TestCase):
    def fixture(self, root):
        campaign = root / 'campaigns' / 'campaign-0123456789abcdef'
        campaign.mkdir(parents=True)
        (campaign / 'manifest.json').write_text('{"physicalSourceId":"fixture-only"}')
        (campaign / 'campaign-complete.json').write_text('{}')
        artifact = campaign / 'encoded.mp4'
        artifact.write_bytes(b'fixture-only-not-media')
        record = {'metadata': {'info': {'artifactPath': str(artifact), 'artifactSha256': ledger.digest(artifact)}}}
        (campaign / 'attempt-000001.json').write_text(json.dumps(record))
        return campaign, artifact

    def test_replay_can_consume_spool_but_never_rewrite_measurements(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            campaign, artifact = self.fixture(root)
            before = ledger.capture(root)
            (root / 'spool-entry.json').write_text('{"retryAfter":10}')
            ledger.assert_unchanged(before, ledger.capture(root))
            (campaign / 'manifest.json').write_text('{"physicalSourceId":"changed"}')
            with self.assertRaises(ValueError): ledger.assert_unchanged(before, ledger.capture(root))
            artifact.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'journal'): ledger.capture(root)

    def test_incomplete_or_unowned_evidence_fails(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            campaign, artifact = self.fixture(root)
            (campaign / 'campaign-complete.json').unlink()
            with self.assertRaisesRegex(ValueError, 'Complete'): ledger.capture(root)
            (campaign / 'campaign-complete.json').write_text('{}')
            outside = root / 'outside.mp4'
            outside.write_bytes(b'outside')
            (campaign / 'attempt-000001.json').write_text(json.dumps({'metadata': {'info': {'artifactPath': str(outside), 'artifactSha256': ledger.digest(outside)}}}))
            with self.assertRaisesRegex(ValueError, 'outside'): ledger.capture(root)

    def test_completion_changes_and_symlinked_records_fail(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            campaign, _ = self.fixture(root)
            before = ledger.capture(root)
            (campaign / 'campaign-complete.json').write_text('{"failed":1}')
            with self.assertRaises(ValueError): ledger.assert_unchanged(before, ledger.capture(root))
            outside = root / 'external-record.json'
            outside.write_text('{}')
            (campaign / 'attempt-000001.json').unlink()
            (campaign / 'attempt-000001.json').symlink_to(outside)
            with self.assertRaisesRegex(ValueError, 'outside'): ledger.capture(root)

    def test_added_attempt_is_not_an_upload_only_replay(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            campaign, _ = self.fixture(root)
            before = ledger.capture(root)
            (campaign / 'attempt-000002.json').write_text('{}')
            with self.assertRaises(ValueError): ledger.assert_unchanged(before, ledger.capture(root))


if __name__ == '__main__': unittest.main()
