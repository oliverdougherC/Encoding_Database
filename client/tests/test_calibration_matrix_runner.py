"""FAKE CLI fixtures exercise orchestration only; never calibration evidence."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/run-calibration-matrix.py'
SPEC = importlib.util.spec_from_file_location('matrix_runner', SCRIPT)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
MATRIX = runner.read(runner.DEFAULT_MATRIX)
FAKE = '''#!/usr/bin/env python3
# SYNTHETIC TEST FIXTURE, no encoder and no measured data.
import json, os, pathlib, sys
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
 (queue/'pending.json').write_text(json.dumps({'nextAttemptAt':9999999999, 'retryDeadlineAt':9999999999})); sys.exit(10)
(root/'campaign-complete.json').write_text(json.dumps({'failed':0,'skipped':0}))
'''


class MatrixRunnerTests(unittest.TestCase):
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
                '--sessions', '1', '--output', str(root/'output'), '--client-source-sha', 'a'*40]

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


if __name__ == '__main__':
    unittest.main()
