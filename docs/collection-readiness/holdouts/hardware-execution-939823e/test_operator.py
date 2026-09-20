"""Operator guard tests. Synthetic fixtures never become measurement evidence."""
import datetime
import importlib.util
import json
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
