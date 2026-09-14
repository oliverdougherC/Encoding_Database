"""FAKE CLI fixtures exercise orchestration only; never calibration evidence."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/run-calibration-matrix.py'
SPEC = importlib.util.spec_from_file_location('matrix_runner', SCRIPT)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
MATRIX = runner.read(runner.DEFAULT_MATRIX)
FAKE = '''#!/usr/bin/env python3
# SYNTHETIC TEST FIXTURE, no encoder and no measured data.
import hashlib, json, os, pathlib, sys
args=sys.argv[1:]
if '--help' in args:
 print('--max-duration-minutes --upload-only --resume-campaign --v7-suite-clip'); sys.exit(0)
def value(key): return args[args.index(key)+1]
queue=pathlib.Path(value('--queue-dir')); queue.mkdir(parents=True, exist_ok=True)
root=queue/'campaigns'/'campaign-0123456789abcdef'; root.mkdir(parents=True,exist_ok=True)
with (queue/'commands.log').open('a') as f: f.write(json.dumps(args)+'\\n')
if '--resume-campaign' not in args:
 (root/'manifest.json').write_text(json.dumps({'seed':int(os.environ['ENCODINGDB_PROTOCOL_SEED']), 'physicalSourceId':'FAKE_TEST_ONLY', 'runtime':{'fixture':'FAKE_TEST_ONLY'}, 'tasks':[{'encoder':value('--codec'),'preset':value('--presets'),'clipId':value('--v7-suite-clip'),'crf':int(value('--crf')),'rateControl':None}]}))
 (root/'encoded-once.txt').write_text('FAKE TEST FIXTURE')
 sys.exit(130)
if '--upload-only' in args:
 if os.environ.get('FAKE_TERMINAL'):
  (queue/'terminal').mkdir(exist_ok=True); (queue/'terminal'/'fixture.json').write_text('{}'); sys.exit(1)
 if os.environ.get('FAKE_UPLOADED'): sys.exit(0)
 (queue/'pending.json').write_text(json.dumps({'nextAttemptAt':9999999999, 'retryDeadlineAt':9999999999})); sys.exit(10)
artifact=root/'encoded-once.txt'
for index in range(2):
 payload={'submissionKind':'authoritative-artifact-run-v1','artifactPath':str(artifact),'artifactSha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),'artifactByteSize':artifact.stat().st_size,'runCreate':{'repetitionIndex':index}}
 (root/f'submission-{index}.json').write_text(json.dumps(payload))
(root/'campaign-complete.json').write_text(json.dumps({'failed':0,'skipped':0,'fixtureStable':False}))
'''


class MatrixRunnerTests(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.TemporaryDirectory()
        self.addCleanup(self.state.cleanup)
        patch = mock.patch.dict(os.environ, {'ENCODINGDB_STATE_DIR': self.state.name})
        patch.start()
        self.addCleanup(patch.stop)

    def test_entire_matrix_slots_sessions_and_determinism(self):
        self.assertEqual(len(MATRIX['cells']), 252)
        mac = runner.plan(MATRIX, ['source-a', 'videotoolbox-host'], [1, 2], 9, Path('/tmp/test'))
        other = runner.plan(MATRIX, ['videotoolbox-host', 'source-a'], [2, 1], 9, Path('/tmp/test'))
        self.assertEqual(mac, other)
        self.assertEqual(len(mac), 392)
        self.assertEqual(len({i['seed'] for i in mac}), len(mac))
        self.assertEqual([x['session'] for x in mac], sorted(x['session'] for x in mac))
        self.assertEqual(len(runner.plan(MATRIX, ['source-b', 'nvenc-host'], [1, 2], 9, Path('/tmp/test'))), 448)

    def test_exact_native_commands_all_cells(self):
        for slot in MATRIX['sourceSlots']:
            for item in runner.plan(MATRIX, [slot], [1, 2], 9, Path('/tmp/test')):
                cmd = runner.command('/fake/cli', item, 100, 2)
                cell = item['cell']
                for flag, value in [('--codec', cell['encoderImplementation']), ('--presets', cell['preset']),
                                    ('--v7-suite-clip', cell['workloadId'])]:
                    self.assertEqual(cmd[cmd.index(flag)+1], value)
                rc = cell['nativeRateControl']
                flag, value = ('--crf', rc['qualityValue']) if rc['mode'] == 'crf' else ('--target-bitrate-kbps', rc['targetBitrateKbps'])
                self.assertEqual(cmd[cmd.index(flag)+1], str(value))
                self.assertIn('--no-submit', cmd)
                self.assertNotIn('--submit', cmd)
                self.assertNotIn('--local-metrics', cmd)
                self.assertEqual(cmd[cmd.index('--max-attempts')+1], '5')

    def test_reject_cross_host_and_invalid_sessions(self):
        with self.assertRaises(ValueError):
            runner.plan(MATRIX, ['source-a', 'source-b'], [1], 9, Path('/tmp/test'))
        with self.assertRaises(ValueError):
            runner.plan(MATRIX, ['source-a'], [3], 9, Path('/tmp/test'))

    def setup_fixture(self, temp):
        root = Path(temp)
        fake = root / 'fake-cli'
        fake.write_text(FAKE)
        fake.chmod(0o755)
        matrix = root / 'matrix.json'
        matrix.write_text(json.dumps(dict(MATRIX, cells=MATRIX['cells'][:1])))
        return ['--cli', str(fake), '--matrix', str(matrix), '--source-slot', 'source-a',
                '--sessions', '1', '--output', str(root/'output'), '--client-source-sha', 'a'*40,
                '--cell-storage-mb', '1', '--disk-reserve-mb', '1']

    def test_default_plan_has_no_writes_or_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.setup_fixture(tmp)
            result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['status'], 'PLAN_ONLY_UNEXECUTED')
            self.assertFalse((Path(tmp)/'output').exists())

    def test_fake_crash_resume_completed_skip_and_upload_backoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.setup_fixture(tmp) + ['--execute']
            self.assertEqual(runner.main(args), 130)
            ledger_path = Path(tmp)/'output'/'ledger.json'
            first = runner.read(ledger_path)
            row = next(iter(first['cells'].values()))
            self.assertEqual(row['evidence']['campaignId'], 'campaign-0123456789abcdef')
            self.assertEqual(runner.main(args), 0)
            row = next(iter(runner.read(ledger_path)['cells'].values()))
            self.assertIn('--resume-campaign', row['calls'][1]['command'])
            self.assertEqual(runner.main(args), 0)
            self.assertEqual(len(next(iter(runner.read(ledger_path)['cells'].values()))['calls']), 2)
            upload = args + ['--phase', 'upload', '--all-host-timing-complete', '--base-url', 'http://test.invalid']
            self.assertEqual(runner.main(upload), 10)
            self.assertEqual(runner.main(upload), 10)
            row = next(iter(runner.read(ledger_path)['cells'].values()))
            self.assertEqual(len(row['calls']), 3)
            self.assertEqual(row['calls'][2]['storage']['stagingBytes'], len(b'FAKE TEST FIXTURE'))
            self.assertIn('--upload-only', row['calls'][2]['command'])
            self.assertNotIn('--no-submit', row['calls'][2]['command'])
            self.assertEqual(runner.main(args), 6)  # no timing after publication began

    def test_upload_requires_every_session_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.setup_fixture(tmp) + ['--execute', '--phase', 'upload',
                    '--all-host-timing-complete', '--base-url', 'http://test.invalid']
            self.assertEqual(runner.main(args), 6)
            self.assertFalse((Path(tmp)/'output'/'ledger.json').exists())

    def test_reject_client_drift_on_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.setup_fixture(tmp) + ['--execute']
            self.assertEqual(runner.main(args), 130)
            fake = Path(tmp)/'fake-cli'
            fake.write_text(FAKE + '\n# changed binary\n')
            self.assertEqual(runner.main(args), 6)

    def test_root_lock_blocks_other_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            with runner.exclusive(Path(tmp)):
                with self.assertRaises(ValueError):
                    with runner.exclusive(Path(tmp)):
                        pass

    def test_different_output_roots_share_host_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.setup_fixture(tmp) + ['--execute']
            with runner.exclusive(Path(self.state.name), 'measurement.lock'):
                self.assertEqual(runner.main(args), 6)
            self.assertFalse((Path(tmp)/'output'/'ledger.json').exists())

    def test_child_keeps_host_lock_after_parent_closes_its_descriptor(self):
        with runner.exclusive(Path(self.state.name), 'measurement.lock') as lock:
            child = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'], pass_fds=(lock.fileno(),))
        try:
            with self.assertRaises(ValueError):
                with runner.exclusive(Path(self.state.name), 'measurement.lock'):
                    pass
        finally:
            child.terminate()
            child.wait()

    def test_real_free_space_and_upload_copy_budget_are_reserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue = root/'queue'
            with mock.patch.object(runner.shutil, 'disk_usage', return_value=mock.Mock(free=1024*runner.MIB)):
                with self.assertRaisesRegex(ValueError, 'free disk'):
                    runner.storage_allowance(root, queue, 16384, 1024, 2048)
            with mock.patch.object(runner.shutil, 'disk_usage', return_value=mock.Mock(free=10000*runner.MIB)):
                with self.assertRaisesRegex(ValueError, 'upload staging'):
                    runner.storage_allowance(root, queue, 100, 10, 1, staging_bytes=11*runner.MIB)
                with self.assertRaisesRegex(ValueError, 'upload staging'):
                    runner.storage_allowance(root, queue, 20, 10, 1, staging_bytes=10*runner.MIB)

    def test_terminal_upload_and_failed_timing_are_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.setup_fixture(tmp) + ['--execute']
            self.assertEqual(runner.main(args), 130)
            self.assertEqual(runner.main(args), 0)
            upload = args + ['--phase', 'upload', '--all-host-timing-complete', '--base-url', 'http://test.invalid']
            with mock.patch.dict(os.environ, {'FAKE_TERMINAL': '1'}):
                self.assertEqual(runner.main(upload), 1)
            ledger = Path(tmp)/'output'/'ledger.json'
            before = len(next(iter(runner.read(ledger)['cells'].values()))['calls'])
            self.assertEqual(runner.main(upload), 1)
            self.assertEqual(len(next(iter(runner.read(ledger)['cells'].values()))['calls']), before)
        with tempfile.TemporaryDirectory() as tmp:
            args = self.setup_fixture(tmp) + ['--execute']
            self.assertEqual(runner.main(args), 130)
            marker = next((Path(tmp)/'output').glob('queues/**/manifest.json')).parent/'campaign-complete.json'
            marker.write_text(json.dumps({'failed': 1, 'skipped': 0}))
            self.assertEqual(runner.main(args), 1)
            self.assertEqual(runner.main(args), 1)
            row = next(iter(runner.read(Path(tmp)/'output'/'ledger.json')['cells'].values()))
            self.assertEqual(len(row['calls']), 1)

    def test_completed_unstable_cell_uploads_once_and_pins_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.setup_fixture(tmp) + ['--execute']
            self.assertEqual(runner.main(args), 130)
            self.assertEqual(runner.main(args), 0)
            upload = args + ['--phase', 'upload', '--all-host-timing-complete', '--base-url', 'http://test.invalid']
            with mock.patch.dict(os.environ, {'FAKE_UPLOADED': '1'}):
                self.assertEqual(runner.main(upload), 0)
                self.assertEqual(runner.main(upload), 0)
            row = next(iter(runner.read(Path(tmp)/'output'/'ledger.json')['cells'].values()))
            self.assertEqual(len(row['calls']), 3)
            self.assertEqual(runner.main(upload[:-1] + ['http://different.invalid']), 6)

    def test_child_clears_only_protocol_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.setup_fixture(tmp) + ['--execute']
            with mock.patch.dict(os.environ, {'ENCODINGDB_PROTOCOL_STABILITY_THRESHOLD': '1',
                    'ENCODINGDB_PROTOCOL_MAX_ADAPTIVE_REPEATS': '0', 'SSL_CERT_FILE': '/fixture/ca'}), \
                 mock.patch.object(runner, 'run_child', wraps=runner.run_child) as child:
                self.assertEqual(runner.main(args), 130)
            env = child.call_args.args[1]
            self.assertNotIn('ENCODINGDB_PROTOCOL_STABILITY_THRESHOLD', env)
            self.assertNotIn('ENCODINGDB_PROTOCOL_MAX_ADAPTIVE_REPEATS', env)
            self.assertEqual(env['SSL_CERT_FILE'], '/fixture/ca')
            self.assertEqual(env['ENCODINGDB_STATE_DIR'], str(Path(self.state.name).resolve()))


if __name__ == '__main__':
    unittest.main()
