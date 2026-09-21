"""Synthetic local regressions; no native process or physical-host access."""
import contextlib
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = load('prepare_operator_gates', 'windows-physical-prepare-rebuild.py')
audit = load('audit_operator_gates', 'audit-windows-physical-acceptance.py')
faults = load('fault_operator_gates', 'windows-physical-faults.py')
CLIPS = ('animation-1080p24-final', 'athletic-action-1080p24-final', 'dark-gradients-1080p24-final',
         'film-grain-1080p24-final', 'natural-detail-1080p24-final', 'screen-text-1080p24-final', 'talking-head-1080p24-final')


class OperatorGateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def preparation_args(self):
        return ['prepare', '--root', str(self.root), '--revision', 'a' * 40, '--tree', 'b' * 40, '--label', 'fixture']

    def test_preparation_cannot_hash_write_or_spawn_without_host_allocation(self):
        @contextlib.contextmanager
        def busy_lock(state):
            self.assertEqual(state, self.root / 'host-state')
            raise OSError('fixture host is busy')
            yield
        with patch.object(prepare, 'os', types.SimpleNamespace(name='nt')), patch.object(sys, 'argv', self.preparation_args()), \
             patch.object(prepare.operator, 'host_lock', busy_lock), patch.object(prepare, 'sha') as hashing, \
             patch.object(prepare.subprocess, 'run') as spawning:
            with self.assertRaisesRegex(OSError, 'host is busy'):
                prepare.main()
            hashing.assert_not_called()
            spawning.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_preparation_keeps_lock_through_hashing_and_releases_on_error(self):
        state = self.root / 'host-state'; state.mkdir()
        (state / 'physical-source-id').write_text('installation-9e7cd0a8c6158d19d179f0acf79249c6c790b988b8a48f6563952c1c00acca29')
        events = []
        @contextlib.contextmanager
        def allocated(_):
            events.append('locked')
            try:
                yield
            finally:
                events.append('released')
        def hash_failure(_):
            self.assertEqual(events, ['locked'])
            raise ValueError('fixture hashing failure')
        with patch.object(prepare, 'os', types.SimpleNamespace(name='nt')), patch.object(sys, 'argv', self.preparation_args()), \
             patch.object(prepare.operator, 'host_lock', allocated), patch.object(prepare, 'sha', hash_failure):
            with self.assertRaisesRegex(ValueError, 'hashing failure'):
                prepare.main()
        self.assertEqual(events, ['locked', 'released'])

    def fixture(self):
        manifest = {'physicalSourceId': 'synthetic-installation', 'protocolVersion': '7.1',
                    'protocolConfig': {'stability_threshold_ratio': .03, 'minimum_measured_runs': 2, 'max_adaptive_repeats': 2},
                    'selectedDevices': {'libx264': {'selection': 'synthetic'}}}
        files = [{'name': 'manifest.json', 'data': manifest}]
        receipt = {'exitCode': 0, 'forcedCleanup': False, 'installationId': 'synthetic-installation', 'wallSeconds': 1,
                   'evidence': {'campaignId': 'campaign-fixture', 'completion': {'failed': 0, 'skipped': 0}, 'attempts': []}}
        order = 0
        for clip in CLIPS:
            recipe_id = clip + '|libx264|fast|23'
            for phase, repetition in [('warmup', 1), ('measured', 1), ('measured', 2)]:
                order += 1; name = f'attempt-{order:06}.json'; artifact = f'C:/owned/{order}.mp4'; digest = f'{order:064x}'
                frames = 192 if clip == CLIPS[0] else 240
                record = {'metadata': {'suiteClip': {'clip_id': clip}, 'info': {'encodeTimerBoundary': 'ffmpeg-process-v1',
                          'effectiveRecipeJson': json.dumps({'encoderNameEffective': 'libx264', 'presetEffective': 'fast', 'rateControlEffective': {'mode': 'crf', 'qualityValue': 23}}),
                          'artifactPath': artifact, 'artifactSha256': digest}},
                          'probe': {'width': 1920, 'height': 1080, 'frame_count': frames, 'avg_frame_rate': 24, 'decodable': True, 'truncated': False,
                                    'color_primaries': 'bt709', 'color_space': 'bt709', 'color_transfer': 'bt709'},
                          'timing': {'elapsed_s': 1, 'start_monotonic_ns': 10, 'end_monotonic_ns': 1000000010, 'encoded_frame_count': frames, 'source_frame_count': frames},
                          'schedule': {'campaign_id': 'campaign-fixture', 'recipe_id': recipe_id, 'phase': phase, 'repetition_index': repetition},
                          'countedForStability': phase == 'measured', 'overallValidity': {'state': 'valid', 'reasons': []},
                          'environmentSnapshot': {'telemetry_sources': 'cpu_psutil_thread_window_v1', 'background_cpu_pct': 0}}
                files.append({'name': name, 'sha256': digest, 'data': record})
                receipt['evidence']['attempts'].append({'record': 'C:/owned/' + name, 'recordSha256': digest})
                if phase == 'measured':
                    group_id = 'campaign-fixture:' + recipe_id
                    run = {'campaignId': 'campaign-fixture', 'workloadId': clip, 'repetitionIndex': repetition, 'repetitionGroupId': group_id,
                           'encodeWallTimeMs': 1000, 'measurementGroup': {'campaignId': 'campaign-fixture', 'repetitionGroupId': group_id,
                           'completed': True, 'countedAttempts': [{'repetitionIndex': i, 'encodeWallTimeMs': 1000} for i in [1, 2]]}}
                    files.append({'name': f'submission-{order:06}.json', 'data': {'runCreate': run, 'artifactPath': artifact, 'artifactSha256': digest}})
        return receipt, {'files': files}

    def run_audit(self, receipt, raw):
        (self.root / 'x264-crf23-receipt.json').write_text(json.dumps(receipt))
        (self.root / 'raw-journals-x264-crf23-fixture.json').write_text(json.dumps(raw))
        return audit.audit(self.root, 'x264-crf23', 'fixture')

    def test_complete_exports_preserve_success_and_original_records(self):
        receipt, raw = self.fixture(); original = copy.deepcopy(raw)
        result = self.run_audit(receipt, raw)
        self.assertEqual((result['attempts'], result['measured'], result['stableGroups']), (21, 14, 7))
        self.assertEqual(raw, original)

    def test_missing_all_or_one_submission_cannot_pass(self):
        for all_missing in [True, False]:
            with self.subTest(all_missing=all_missing):
                receipt, raw = self.fixture()
                submissions = [x for x in raw['files'] if x['name'].startswith('submission-')]
                remove = {x['name'] for x in submissions} if all_missing else {submissions[0]['name']}
                raw['files'] = [x for x in raw['files'] if x['name'] not in remove]
                with self.assertRaisesRegex(ValueError, 'coverage differs'):
                    self.run_audit(receipt, raw)

    def test_submission_cannot_duplicate_another_measurement_binding(self):
        receipt, raw = self.fixture()
        submissions = [x for x in raw['files'] if x['name'].startswith('submission-')]
        submissions[1]['data'] = copy.deepcopy(submissions[0]['data'])
        with self.assertRaisesRegex(ValueError, 'bind its measured attempt'):
            self.run_audit(receipt, raw)

    def test_seven_substituted_clip_names_do_not_count_as_canonical_coverage(self):
        receipt, raw = self.fixture()
        for item in raw['files']:
            if item['name'].startswith('attempt-') and item['data']['metadata']['suiteClip']['clip_id'] == 'talking-head-1080p24-final':
                item['data']['metadata']['suiteClip']['clip_id'] = 'substituted-1080p24-final'
        with self.assertRaisesRegex(ValueError, 'Canonical full-seven'):
            self.run_audit(receipt, raw)

    def test_interrupt_receipt_failure_and_timeout_reap_only_the_owned_process(self):
        for error in [KeyboardInterrupt(), OSError('receipt write failed'), subprocess.TimeoutExpired('fixture', 1)]:
            with self.subTest(error=type(error).__name__):
                process = Mock(pid=4321); process.poll.return_value = None
                receipt = {'forcedCleanup': False}
                result = types.SimpleNamespace(returncode=0, stdout='fixture cleanup', stderr='')
                with patch.object(faults.subprocess, 'Popen', return_value=process), patch.object(faults.subprocess, 'run', return_value=result) as kill:
                    with self.assertRaises(type(error)):
                        with faults.owned_native_process(['fixture-never-executed'], receipt):
                            raise error
                kill.assert_called_once_with(['taskkill', '/PID', '4321', '/T', '/F'], capture_output=True, text=True, timeout=30)
                process.wait.assert_called_once_with(timeout=30)
                self.assertTrue(receipt['forcedCleanup'])

    def test_cleanup_command_failure_still_reaps_parent_and_fails_closed(self):
        process = Mock(pid=4321); process.poll.return_value = None
        receipt = {'forcedCleanup': False}
        with patch.object(faults.subprocess, 'Popen', return_value=process), patch.object(faults.subprocess, 'run', side_effect=OSError('fixture taskkill unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'tree cleanup failed'):
                with faults.owned_native_process(['fixture-never-executed'], receipt):
                    raise KeyboardInterrupt()
        process.kill.assert_called_once()
        process.wait.assert_called_once_with(timeout=30)
        self.assertIn('taskkill unavailable', receipt['cleanup']['error'])

    def test_clean_native_exit_is_not_force_killed(self):
        process = Mock(pid=4321); process.poll.return_value = 3
        receipt = {'forcedCleanup': False}
        with patch.object(faults.subprocess, 'Popen', return_value=process), patch.object(faults.subprocess, 'run') as kill:
            with faults.owned_native_process(['fixture-never-executed'], receipt):
                pass
        kill.assert_not_called(); process.kill.assert_not_called()
        self.assertFalse(receipt['forcedCleanup'])


if __name__ == '__main__':
    unittest.main()
