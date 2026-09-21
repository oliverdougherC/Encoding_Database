"""Operator guard tests. Synthetic fixtures never become measurement evidence."""
import datetime
import importlib.util
import json
import fcntl
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('hardware_operator', Path(__file__).with_name('run.py'))
operator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operator)


class OperatorGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.plan = {'executionHash': 'frozen-plan', 'sourceCommit': 'frozen-source'}
        self.allocation = {'host': 'Mac', **self.plan, 'exclusiveTimingGranted': True,
                           'nativeAcceptanceComplete': True, 'noBuildAnalysisUploadOrSourcePreparation': True,
                           'expiresAt': (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)).isoformat()}

    def test_current_exact_allocation(self):
        operator.validate_allocation(self.allocation, self.plan, 'Mac')

    def test_allocation_cannot_transfer_hosts(self):
        with self.assertRaises(ValueError):
            operator.validate_allocation(self.allocation, self.plan, 'P910')

    def test_allocation_cannot_transfer_source(self):
        self.allocation['sourceCommit'] = 'another-source'
        with self.assertRaises(ValueError):
            operator.validate_allocation(self.allocation, self.plan, 'Mac')

    def test_expired_allocation_is_rejected(self):
        self.allocation['expiresAt'] = '2000-01-01T00:00:00+00:00'
        with self.assertRaises(ValueError):
            operator.validate_allocation(self.allocation, self.plan, 'Mac')

    def test_unstable_completed_receipt_is_reused(self):
        receipt = self.root / 'receipt.json'
        receipt.write_text('{"syntheticTestOnly":true}')
        previous = {'executionHash': 'frozen-plan', 'command': ['original'], 'status': 'COMPLETE', 'exitCode': 4,
                    'receipts': [{'path': str(receipt), 'sha256': operator.digest(receipt)}]}
        self.assertEqual(operator.validate_previous(previous, 'frozen-plan', ['original'], False), 'reuse')
        receipt.write_text('changed')
        with self.assertRaises(ValueError):
            operator.validate_previous(previous, 'frozen-plan', ['original'], True)

    def test_source_or_command_change_cannot_resume(self):
        previous = {'executionHash': 'frozen-plan', 'command': ['original'], 'status': 'RUNNING'}
        with self.assertRaises(ValueError):
            operator.validate_previous(previous, 'new-plan', ['original'], True)
        with self.assertRaises(ValueError):
            operator.validate_previous(previous, 'frozen-plan', ['changed-seed'], True)

    def test_failed_observation_is_never_automatically_retried(self):
        previous = {'executionHash': 'frozen-plan', 'command': ['original'], 'status': 'FAILED'}
        with self.assertRaises(ValueError):
            operator.validate_previous(previous, 'frozen-plan', ['original'], True)

    def test_interrupted_resume_is_explicit(self):
        previous = {'executionHash': 'frozen-plan', 'command': ['original'], 'status': 'RUNNING'}
        with self.assertRaises(ValueError):
            operator.validate_previous(previous, 'frozen-plan', ['original'], False)
        self.assertEqual(operator.validate_previous(previous, 'frozen-plan', ['original'], True), 'resume')

    def test_tampered_seal_is_rejected(self):
        path = self.root / 'plan.json'
        document = {'cells': ['one']}
        document['planHash'] = operator.canonical_hash(document)
        path.write_text(json.dumps(document))
        operator.read_sealed(path, 'planHash')
        document['cells'].append('changed')
        path.write_text(json.dumps(document))
        with self.assertRaises(ValueError):
            operator.read_sealed(path, 'planHash')

    def test_runtime_helpers_are_bound_to_actual_bytes(self):
        helper = self.root / 'ffmpeg'; helper.write_bytes(b'original-helper')
        lock = self.root / 'lock.json'; lock.write_text('{"synthetic":true}')
        host = {'runtimeLockPath': str(lock), 'runtimeLockSha256': operator.digest(lock),
                'runtimeLockFingerprint': operator.canonical_hash({'synthetic': True}),
                'runtimeFiles': [{'path': str(helper), 'byteSize': helper.stat().st_size, 'sha256': operator.digest(helper)}]}
        operator.verify_runtime(host)
        helper.write_bytes(b'changed--helper')
        with self.assertRaises(ValueError):
            operator.verify_runtime(host)

    def test_actual_frozen_cells_keep_original_commands_and_order(self):
        base = Path(__file__).parent
        plan = operator.read_sealed(base / 'execution.json', 'executionHash')
        original = operator.read_sealed(base.parent / 'timing-hardware-extension-v1.json', 'planHash')
        self.assertEqual(operator.digest(base / 'run.py'), plan['operatorSha256'])
        self.assertEqual(plan['cells'], original['cells'])
        for host_name in ('Mac', 'P910'):
            cells = [cell for cell in plan['cells'] if cell['host'] == host_name]
            self.assertEqual(len(cells), 14)
            self.assertEqual([c['order'] for c in cells], sorted(c['order'] for c in cells))
            for cell in cells:
                command = operator.command_for(plan['hosts'][host_name], cell)
                self.assertNotIn('--crf', command)
                self.assertEqual(command[command.index('--target-bitrate-kbps') + 1], str(cell['targetBitrateKbps']))
                self.assertEqual(command[command.index('--seed') + 1], str(cell['seed']))


class RecoveryGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cell = {'cellId': 'synthetic-cell', 'encoder': 'h264_nvenc', 'preset': 'p4',
                     'targetBitrateKbps': 4000, 'seed': 42, 'sourceRegistrationHash': 'registered',
                     'maximumMeasurementMinutes': 60}
        self.host = {'outputRoot': str(self.root), 'physicalSourceId': 'test-source', 'runtimeLockFingerprint': 'test-runtime'}
        self.plan = {'runnerSha256': 'test-runner'}
        recipe = {'encoder': 'h264_nvenc', 'preset': 'p4', 'crf': None,
                  'sourceRegistrationHash': 'registered', 'rateControl': {'mode': 'vbr', 'targetBitrateKbps': 4000}}
        recipe_id = operator.canonical_hash(recipe)
        campaign_id = 'campaign-' + operator.canonical_hash({'protocolVersion': '7.1', 'recipeIds': [recipe_id], 'seed': 42})[:16]
        self.journal = self.root / 'synthetic-cell' / 'campaigns' / campaign_id
        self.journal.mkdir(parents=True)
        manifest = {'seed': 42, 'runnerSha256': 'test-runner', 'physicalSourceId': 'test-source',
                    'sourceRegistrationHash': 'registered', 'runtimeVerification': {'fingerprint': 'test-runtime'},
                    'recipe': recipe, 'protocolConfig': {'warmup_runs': 1, 'minimum_measured_runs': 2,
                    'max_adaptive_repeats': 2, 'stability_threshold_ratio': .03}}
        operator.atomic_json(self.journal / 'manifest.json', manifest)
        artifact = self.journal / 'synthetic-artifact.bin'
        artifact.write_bytes(b'SYNTHETIC FIXTURE ONLY')
        attempt = {'schedule': {'campaign_id': campaign_id, 'recipe_id': recipe_id},
                   'metadata': {'info': {'artifactPath': str(artifact), 'artifactSha256': operator.digest(artifact)}}}
        self.attempt = self.journal / 'attempt-000001.json'
        operator.atomic_json(self.attempt, attempt)
        self.pause = {'status': 'PAUSED_MEASUREMENT_BUDGET', 'maximumMinutes': 60,
                      'campaignId': campaign_id, 'seed': 42, 'completedAttempts': 1,
                      'journalPath': str(self.journal.resolve())}
        operator.atomic_json(self.journal / 'validation-pause.json', self.pause)

    def paused_record(self):
        return {'executionHash': 'sealed', 'command': ['same-source', '--seed', '42'],
                'status': 'PAUSED_MEASUREMENT_BUDGET', 'exitCode': 11,
                'resumeEvidence': operator.journal_evidence(self.cell, self.host, self.plan, budget_pause=True)}

    def test_budget_pause_requires_explicit_resume_and_preserves_attempt_bytes(self):
        before = {p.name: p.read_bytes() for p in self.journal.iterdir()}
        previous = self.paused_record()
        with self.assertRaises(ValueError):
            operator.validate_previous(previous, 'sealed', previous['command'], False)
        self.assertEqual(operator.validate_previous(previous, 'sealed', previous['command'], True), 'resume')
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.journal.iterdir()})
        self.attempt.write_text('changed completed attempt')
        with self.assertRaises(ValueError):
            operator.validate_previous(previous, 'sealed', previous['command'], True)

    def test_budget_exit_without_matching_pause_is_not_resumable(self):
        (self.journal / 'validation-pause.json').unlink()
        with self.assertRaises(ValueError):
            self.paused_record()
        self.pause['seed'] = 43
        operator.atomic_json(self.journal / 'validation-pause.json', self.pause)
        with self.assertRaises(ValueError):
            self.paused_record()

    def test_budget_pause_rejects_changed_recipe_or_attempt_count(self):
        self.pause['completedAttempts'] = 0
        operator.atomic_json(self.journal / 'validation-pause.json', self.pause)
        with self.assertRaises(ValueError):
            self.paused_record()
        self.pause['completedAttempts'] = 1
        operator.atomic_json(self.journal / 'validation-pause.json', self.pause)
        manifest_path = self.journal / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['recipe']['rateControl']['targetBitrateKbps'] = 8000
        operator.atomic_json(manifest_path, manifest)
        with self.assertRaises(ValueError):
            self.paused_record()

    def test_actual_failure_does_not_become_resumable_when_pause_exists(self):
        previous = self.paused_record()
        previous.update(status='FAILED', exitCode=1)
        with self.assertRaises(ValueError):
            operator.validate_previous(previous, 'sealed', previous['command'], True)

    def test_interrupted_status_requires_operator_observation_and_explicit_resume(self):
        previous = self.paused_record()
        previous.update(status='INTERRUPTED', exitCode=None)
        with self.assertRaises(ValueError):
            operator.validate_previous(previous, 'sealed', previous['command'], True)
        previous['operatorInterrupted'] = True
        with self.assertRaises(ValueError):
            operator.validate_previous(previous, 'sealed', previous['command'], False)
        self.assertEqual(operator.validate_previous(previous, 'sealed', previous['command'], True), 'resume')
        previous['status'] = 'UNRECOGNIZED'
        with self.assertRaises(ValueError):
            operator.validate_previous(previous, 'sealed', previous['command'], True)

    def test_parent_only_sigint_keeps_host_lock_until_detached_media_cleanup(self):
        lock_path, ready, cleanup_started, allow_cleanup, media_release, cleaned, interrupted = (
            self.root / name for name in ('sigint.lock', 'media-ready', 'cleanup-started',
                                         'allow-cleanup', 'media-release', 'media-cleaned', 'interrupted'))
        media_code = """import pathlib,sys,time
release=pathlib.Path(sys.argv[1]); deadline=time.monotonic()+30
while not release.exists() and time.monotonic()<deadline: time.sleep(.02)
pathlib.Path(str(release)+'.done').touch()
"""
        runner_code = """import os,pathlib,subprocess,sys,time
ready,started,allow,release,cleaned=map(pathlib.Path,sys.argv[1:6])
media=subprocess.Popen([sys.executable,'-c',sys.argv[6],str(release)],start_new_session=True)
try:
 ready.write_text(str(media.pid))
 while True: time.sleep(.02)
except KeyboardInterrupt:
 started.touch(); deadline=time.monotonic()+10
 while not allow.exists() and time.monotonic()<deadline: time.sleep(.02)
finally:
 release.touch(); media.wait(timeout=5); cleaned.touch()
"""
        parent_code = """import fcntl,importlib.util,os,pathlib,signal,sys
spec=importlib.util.spec_from_file_location('operator_under_test',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
original=signal.getsignal(signal.SIGINT)
with open(sys.argv[2],'a+b') as lock, open(os.devnull,'w') as log:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 try: module.run_timing_child([sys.executable,'-c',sys.argv[3],*sys.argv[4:10]],pathlib.Path.cwd(),dict(os.environ),log,lock)
 except KeyboardInterrupt:
  assert signal.getsignal(signal.SIGINT)==original
  pathlib.Path(sys.argv[10]).touch()
  sys.exit(130)
"""
        parent = subprocess.Popen([sys.executable, '-c', parent_code, str(Path(operator.__file__).resolve()),
                                   str(lock_path), runner_code, str(ready), str(cleanup_started),
                                   str(allow_cleanup), str(media_release), str(cleaned), media_code, str(interrupted)],
                                  start_new_session=True)
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                self.assertIsNone(parent.poll())
                time.sleep(.02)
            self.assertTrue(ready.exists(), 'synthetic detached media did not start')
            media_pid = int(ready.read_text())
            self.assertEqual(os.getpgid(media_pid), media_pid)
            os.kill(parent.pid, signal.SIGINT)  # Parent only, not its process group.
            deadline = time.monotonic() + 3
            while not cleanup_started.exists() and parent.poll() is None and time.monotonic() < deadline:
                time.sleep(.02)
            with lock_path.open('a+b') as contender:
                os.kill(media_pid, 0)
                with self.assertRaises(BlockingIOError, msg='host lock released while detached media remains alive'):
                    fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertTrue(cleanup_started.exists(), 'runner never received graceful interruption')
                self.assertIsNone(parent.poll())
                os.kill(parent.pid, signal.SIGINT)  # A second Ctrl+C cannot interrupt cleanup.
                time.sleep(.05)
                self.assertIsNone(parent.poll())
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
                allow_cleanup.touch()
                self.assertEqual(parent.wait(timeout=5), 130)
                self.assertTrue(cleaned.exists())
                self.assertTrue(interrupted.exists())
                fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            allow_cleanup.touch()
            media_release.touch()
            try:
                parent.wait(timeout=5)
            except subprocess.TimeoutExpired:
                parent.kill()
                parent.wait(timeout=5)
            if ready.exists():
                deadline = time.monotonic() + 5
                done = Path(str(media_release) + '.done')
                while not done.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(done.exists(), 'detached synthetic media did not exit during cleanup')

    def test_normal_child_preserves_exit_status_and_parent_lock(self):
        command = [sys.executable, '-c', 'raise SystemExit(4)']
        path = self.root / 'normal.lock'
        with path.open('a+b') as lock, open(os.devnull, 'w') as log:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = operator.run_timing_child(command, self.root, dict(os.environ), log, lock)
            self.assertEqual(result.args, command)
            self.assertEqual(result.returncode, 4)
            with path.open('a+b') as contender:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_live_child_keeps_host_lock_after_operator_parent_is_killed(self):
        lock_path, ready, release = (self.root / name for name in ('host.lock', 'child-ready', 'release-child'))
        child_code = "import os,pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); " + \
                     "exec('while not pathlib.Path(sys.argv[2]).exists():\\n time.sleep(.02)')"
        parent_code = """import fcntl,importlib.util,os,pathlib,sys
spec=importlib.util.spec_from_file_location('operator_under_test',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
with open(sys.argv[2],'a+b') as lock, open(os.devnull,'w') as log:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 module.run_timing_child([sys.executable,'-c',sys.argv[3],sys.argv[4],sys.argv[5]],pathlib.Path.cwd(),dict(os.environ),log,lock)
"""
        parent = subprocess.Popen([sys.executable, '-c', parent_code, str(Path(operator.__file__).resolve()),
                                   str(lock_path), child_code, str(ready), str(release)])
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                self.assertIsNone(parent.poll())
                time.sleep(.02)
            self.assertTrue(ready.exists(), 'synthetic child did not start')
            child_pid = int(ready.read_text())
            parent.kill()
            parent.wait(timeout=5)
            os.kill(child_pid, 0)
            with lock_path.open('a+b') as contender:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
                release.touch()
                deadline = time.monotonic() + 5
                while True:
                    try:
                        fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            self.fail('host lock remained held after synthetic child exit')
                        time.sleep(.02)
        finally:
            release.touch()
            if parent.poll() is None:
                parent.kill()
            parent.wait(timeout=5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
