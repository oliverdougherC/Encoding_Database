"""Small fixture checks for the physical operator; these are not native evidence."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('physical_acceptance', Path(__file__).with_name('windows-physical-acceptance.py'))
operator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operator)


class OperatorChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.payload = self.root / 'payload'
        self.payload.mkdir()
        self.source = 'a' * 40
        exe = self.payload / 'encodingdb-client-windows-console.exe'
        exe.write_bytes(b'fixture executable; never executed')
        pack = self.payload / 'encodingdb-test-suite-v1.tar.gz'
        pack.write_bytes(b'fixture pack')
        self.manifest = {'source': {'revision': self.source, 'trackedChanges': False},
                         'artifact': {'sha256': operator.sha(exe)},
                         'suite': {'suiteFingerprint': 'fixture-suite', 'pack': {'sha256': operator.sha(pack)}},
                         'runtime': {'payload': {'platforms': {'win': {'ffmpeg': {'sha256': 'm'}, 'ffprobe': {'sha256': 'p'}}}}}}
        operator.save(self.payload / (exe.name + '.release-manifest.json'), self.manifest)
        operator.save(self.payload / (exe.name + '.runtime-lock.json'), {'fixture': True})
        self.pins = {'actualBuildRevision': self.source, 'suiteFingerprint': 'fixture-suite',
                     'files': {path.name: operator.sha(path) for path in self.payload.iterdir()}}

    def test_pin_validation_requires_unchanged_independently_pinned_bytes(self):
        exe, manifest = operator.verify_payload(self.payload, self.pins)
        self.assertEqual(manifest, self.manifest)
        exe.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            operator.verify_payload(self.payload, self.pins)

    def test_pin_validation_rejects_source_mismatch_and_missing_pin(self):
        self.pins['actualBuildRevision'] = 'b' * 40
        with self.assertRaisesRegex(ValueError, 'source'):
            operator.verify_payload(self.payload, self.pins)
        self.pins['actualBuildRevision'] = self.source
        del self.pins['files']['encodingdb-test-suite-v1.tar.gz']
        with self.assertRaisesRegex(ValueError, 'Missing independent file pin'):
            operator.verify_payload(self.payload, self.pins)

    def test_pin_validation_rejects_path_escape_even_when_hash_matches(self):
        outside = self.root / 'outside'
        outside.write_bytes(b'outside')
        self.pins['files']['../outside'] = operator.sha(outside)
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            operator.verify_payload(self.payload, self.pins)

    @unittest.skipUnless(sys.platform == 'win32', 'Requires actual Windows msvcrt locking')
    def test_operator_lock_excludes_second_holder_and_releases(self):
        state = self.root / 'host-state'
        with operator.host_lock(state):
            with self.assertRaises(OSError):
                with operator.host_lock(state):
                    self.fail('Concurrent physical host allocation was accepted')
        with operator.host_lock(state):
            self.assertTrue((state / 'physical-operator.lock').is_file())

    def test_plan_does_not_verify_execute_or_create_output(self):
        pins = self.root / 'pins.json'
        operator.save(pins, self.pins)
        target = self.root / 'must-not-exist'
        argv = ['operator', '--payload', str(self.payload), '--pins', str(pins), '--root', str(target), '--recipe', 'nvenc-vbr6000']
        output = io.StringIO()
        with patch.object(operator, 'os', types.SimpleNamespace(name='nt')), patch.object(sys, 'argv', argv), patch.object(operator, 'verify_payload', side_effect=AssertionError('plan must not hash payload')), contextlib.redirect_stdout(output):
            operator.main()
        plan = json.loads(output.getvalue())
        self.assertEqual(plan['mode'], 'plan-only')
        self.assertIn('--no-submit', plan['arguments'])
        self.assertEqual(plan['arguments'][-2:], ['--target-bitrate-kbps', '6000'])
        self.assertFalse(target.exists())

    def make_campaign(self):
        phase = self.root / 'phase'
        campaign = phase / 'queue' / 'campaigns' / 'campaign-fixture'
        campaign.mkdir(parents=True)
        operator.save(campaign / 'campaign-complete.json', {'fixture': 'complete'})
        operator.save(campaign / 'manifest.json', {'fixture': 'manifest'})
        artifact = campaign / 'encoded.mkv'
        artifact.write_bytes(b'fixture bytes')
        operator.save(campaign / 'attempt-000001.json', {'schedule': {'phase': 'measured'}, 'countedForStability': False,
            'overallValidity': {'state': 'suspect', 'reasons': [{'code': 'fixture-background-load'}]},
            'environmentSnapshot': {'background_cpu_pct': 47.0},
            'metadata': {'integrity': 'SUSPECT', 'info': {'artifactPath': str(artifact), 'artifactSha256': operator.sha(artifact)}}})
        extraction = phase / '_MEIfixture'
        runtime = {'frozen': True, 'platform': 'win', 'extractionRoot': str(extraction),
            'ffmpegPath': str(extraction / 'ffmpeg.exe'), 'ffprobePath': str(extraction / 'ffprobe.exe'),
            'identity': {'ffmpeg': {'sha256': 'm'}, 'ffprobe': {'sha256': 'p'}}}
        operator.save(phase / 'embedded-runtime.json', runtime)
        return phase, campaign, artifact, runtime

    def test_audit_retains_suspect_record_and_detects_changed_artifact(self):
        phase, campaign, artifact, _ = self.make_campaign()
        result = operator.audit(phase / 'queue', phase, self.manifest)
        self.assertFalse(result['attempts'][0]['countedForStability'])
        self.assertEqual(result['attempts'][0]['metadata']['integrity'], 'SUSPECT')
        self.assertEqual(result['attempts'][0]['overallValidity']['state'], 'suspect')
        self.assertEqual(result['attempts'][0]['environmentSnapshot']['background_cpu_pct'], 47.0)
        artifact.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Retained artifact differs'):
            operator.audit(phase / 'queue', phase, self.manifest)

    def test_audit_rejects_external_helpers_and_incomplete_campaign(self):
        phase, campaign, _, runtime = self.make_campaign()
        runtime['ffmpegPath'] = str(self.root / 'external.exe')
        operator.save(phase / 'embedded-runtime.json', runtime)
        with self.assertRaisesRegex(ValueError, 'external media helper'):
            operator.audit(phase / 'queue', phase, self.manifest)
        (campaign / 'campaign-complete.json').unlink()
        with self.assertRaisesRegex(ValueError, 'complete durably'):
            operator.audit(phase / 'queue', phase, self.manifest)


if __name__ == '__main__':
    unittest.main()
