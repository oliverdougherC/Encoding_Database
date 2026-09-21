import copy
import fcntl
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


AUDIT = module('audit', 'audit-artifacts.py')
FAULTS = module('faults', 'run-faults.py')


class PostTimingSafetyTests(unittest.TestCase):
    def valid_execution(self, root):
        work = root / '日本語 client trial'
        work.mkdir()
        for name in ['smoke', 'software', 'nvenc']:
            (work / (name + '-queue')).mkdir()
        return {'status': 'timing-finished', 'sourceCommit': AUDIT.PLAN['sourceCommit'],
                'packageSha256': AUDIT.PLAN['packageSha256'], 'campaigns': [
                    {'name': name, 'queue': str(work / (('smoke' if name == 'help' else name) + '-queue')),
                     'returnCode': 0, 'timedOut': False, 'cleanupForced': False,
                     'survivingOwnedPids': [], 'embeddedRuntimeVerified': True,
                     'immutableLedgerCaptured': True} for name in ['help', 'smoke', 'software', 'nvenc']]}

    def test_forced_cleanup_cannot_pass_corrupt_or_resume_natural_exit(self):
        for expected in [3, 0]:
            value = {'returnCode': expected, 'timedOut': False, 'cleanupForced': False, 'survivingOwnedPids': []}
            FAULTS.require_natural_exit(value, expected)
            for key, replacement in [('cleanupForced', True), ('timedOut', True), ('survivingOwnedPids', [123]), ('returnCode', 6)]:
                with self.subTest(expected=expected, key=key):
                    with self.assertRaises(ValueError):
                        FAULTS.require_natural_exit({**value, key: replacement}, expected)
            with self.assertRaises(ValueError):
                FAULTS.require_natural_exit({'returnCode': expected}, expected)

    def test_shared_lock_prevents_any_audit_work(self):
        with tempfile.TemporaryDirectory() as name:
            state = Path(name)
            calls = []
            with mock.patch.dict(AUDIT.PLAN, {'physicalStateRoot': str(state)}), mock.patch.object(AUDIT, 'audit_locked', lambda: calls.append('audit')):
                with (state / 'measurement.lock').open('a') as held:
                    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    with self.assertRaises(BlockingIOError):
                        AUDIT.main()
                    self.assertEqual(calls, [])
                AUDIT.main()
                self.assertEqual(calls, ['audit'])

    def test_missing_extra_or_duplicate_cases_fail(self):
        with tempfile.TemporaryDirectory() as name, mock.patch.object(AUDIT, 'ROOT', Path(name)):
            value = self.valid_execution(Path(name))
            AUDIT.validate_execution(value)
            variants = [[], value['campaigns'][:1], value['campaigns'][:-1],
                        [*value['campaigns'], value['campaigns'][-1]],
                        [*value['campaigns'][:-1], {**value['campaigns'][-1], 'name': 'unknown'}]]
            for cases in variants:
                with self.subTest(names=[case['name'] for case in cases]), self.assertRaises(ValueError):
                    AUDIT.validate_execution({**value, 'campaigns': cases})

    def test_source_package_queue_and_completion_mismatches_fail(self):
        with tempfile.TemporaryDirectory() as name, mock.patch.object(AUDIT, 'ROOT', Path(name)):
            value = self.valid_execution(Path(name))
            for key in ['sourceCommit', 'packageSha256', 'status']:
                with self.subTest(key=key), self.assertRaises(ValueError):
                    AUDIT.validate_execution({**value, key: 'wrong'})
            mutations = [('queue', str(Path(name) / 'other-queue')), ('returnCode', 11),
                         ('cleanupForced', True), ('timedOut', True), ('survivingOwnedPids', [123]),
                         ('immutableLedgerCaptured', False), ('embeddedRuntimeVerified', False)]
            for key, replacement in mutations:
                changed = copy.deepcopy(value)
                changed['campaigns'][-1][key] = replacement
                with self.subTest(key=key), self.assertRaises(ValueError):
                    AUDIT.validate_execution(changed)

    def test_symlinked_queue_cannot_impersonate_its_owned_location(self):
        with tempfile.TemporaryDirectory() as name, mock.patch.object(AUDIT, 'ROOT', Path(name)):
            root = Path(name)
            value = self.valid_execution(root)
            queue = root / '日本語 client trial/nvenc-queue'
            queue.rmdir()
            other = root / 'other'
            other.mkdir()
            queue.symlink_to(other, target_is_directory=True)
            with self.assertRaises(ValueError):
                AUDIT.validate_execution(value)

    def test_changed_package_bytes_fail_before_any_frame_probe(self):
        with tempfile.TemporaryDirectory() as name, mock.patch.object(AUDIT, 'ROOT', Path(name)):
            root = Path(name)
            value = self.valid_execution(root)
            (root / 'execution.json').write_text(json.dumps(value))
            with mock.patch.object(AUDIT, 'digest', return_value='changed'), mock.patch.object(AUDIT.subprocess, 'run') as probe:
                with self.assertRaisesRegex(ValueError, 'package bytes'):
                    AUDIT.audit_locked()
                probe.assert_not_called()


if __name__ == '__main__':
    unittest.main()
