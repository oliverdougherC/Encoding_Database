"""Preparation gate and cancellation regressions; no media tools or network."""
import argparse
import itertools
import json
import io
import tarfile
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

from client import campaign, main, suite, runtime_lock


class PreparationTests(unittest.TestCase):
    def args(self, **changes):
        values = dict(no_submit=False, submit=True, base_url='https://invalid.example',
                      codec='libx264', campaign='quick', v7_suite_clip='', queue_dir='unused',
                      resume_campaign='campaign-0123456789abcdef')
        values.update(changes)
        return argparse.Namespace(**values)

    def test_fresh_mismatch_precedes_every_source_runtime_and_helper_call(self):
        with mock.patch.object(main, 'check_compatibility', side_effect=RuntimeError('unsupported')), \
             mock.patch.object(main, '_prepare_quick_suite_clip') as prepare, \
             mock.patch.object(main, 'has_encoder') as helper, \
             mock.patch.object(runtime_lock, 'verify_runtime_lock') as integrity, \
             mock.patch.object(suite, '_ensure_suite_pack_available') as acquire:
            self.assertEqual(main.run_v7_suite_clip_mode(base_args=self.args()), 5)
        for function in (prepare, helper, integrity, acquire):
            function.assert_not_called()

    def test_resume_mismatch_precedes_journal_and_source_access(self):
        with mock.patch.object(main, 'check_compatibility', side_effect=RuntimeError('unsupported')), \
             mock.patch.object(main, 'journal_path') as journal, \
             mock.patch.object(main, '_prepare_named_suite_clip') as prepare, \
             mock.patch.object(runtime_lock, 'verify_runtime_lock') as integrity:
            self.assertEqual(main._resume_campaign(self.args()), 5)
        for function in (journal, prepare, integrity):
            function.assert_not_called()

    def test_effective_local_policy_skips_compatibility_but_gates_runtime_before_source(self):
        order = []
        def prepare():
            order.append('source')
            raise KeyboardInterrupt
        with mock.patch.object(main, 'check_compatibility') as compatibility, \
             mock.patch.object(main.sys, 'frozen', True, create=True), \
             mock.patch.object(runtime_lock, 'verify_runtime_lock', side_effect=lambda **kw: order.append('runtime')), \
             mock.patch.object(main, '_prepare_quick_suite_clip', side_effect=prepare):
            self.assertEqual(main.run_v7_suite_clip_mode(base_args=self.args(submit=False)), 130)
        compatibility.assert_not_called()
        self.assertEqual(order, ['runtime', 'source'])

    def test_upload_only_never_enters_runtime_or_source_preparation(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(main, 'check_compatibility'), \
             mock.patch.object(main, 'replay_spool', return_value=mock.Mock(dead_lettered=0, corrupt=0)), \
             mock.patch.object(main, 'count_pending_entries', return_value=0), \
             mock.patch.object(main, '_preparation_runtime_integrity') as runtime, \
             mock.patch.object(main, '_prepare_quick_suite_clip') as prepare:
            self.assertEqual(main.main(['prog', '--upload-only', '--queue-dir', directory]), 0)
        runtime.assert_not_called()
        prepare.assert_not_called()

    def test_explicit_upload_only_with_resume_and_submit_never_falls_through_to_encoding(self):
        # Without campaign-complete.json the marker inference must not silently
        # downgrade the typed --upload-only contract into an encoding resume.
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(main, 'check_compatibility'), \
             mock.patch.object(main, 'replay_spool', return_value=mock.Mock(dead_lettered=0, corrupt=0)), \
             mock.patch.object(main, 'count_pending_entries', return_value=0), \
             mock.patch.object(main, 'run_benchmark_batch') as batch, \
             mock.patch.object(main, '_prepare_quick_suite_clip') as prepare, \
             mock.patch.object(main, '_preparation_runtime_integrity') as runtime:
            self.assertEqual(main.main(['prog', '--upload-only', '--resume-campaign', 'campaign-0123456789abcdef',
                                        '--submit', '--queue-dir', directory]), 0)
        batch.assert_not_called()
        prepare.assert_not_called()
        runtime.assert_not_called()

    def test_menu_exit_does_not_prepare_sources_or_discover_helpers(self):
        with mock.patch.object(main, 'prompt_choice', return_value=4), \
             mock.patch.object(main, 'build_mode_estimates', return_value={'smallMinutes': 1, 'mediumHours': 1, 'fullHours': 1}), \
             mock.patch.object(main.sys, 'stdin', None), \
             mock.patch.object(main, '_prepare_quick_suite_clip') as prepare, \
             mock.patch.object(main, 'list_all_available_encoders') as discover:
            self.assertEqual(main.interactive_menu_flow(main.build_arg_parser(), self.args()), 0)
        prepare.assert_not_called()
        discover.assert_not_called()

    def test_full_interactive_mismatch_precedes_encoder_discovery(self):
        with mock.patch.object(main, 'check_compatibility', side_effect=RuntimeError('unsupported')), \
             mock.patch.object(main, '_prepare_full_suite') as prepare, \
             mock.patch.object(main, 'list_all_available_encoders') as discover:
            self.assertEqual(main.run_batch_mode(mode='full', base_args=self.args(), interactive=False), 5)
        prepare.assert_not_called()
        discover.assert_not_called()

    def test_gui_bound_stop_before_encode_reports_interruption_without_measurement_budget(self):
        stopped = threading.Event()
        events = []
        def sink(event):
            events.append(event)
            if event['type'] == 'preparation_progress' and event['stage'] == 'probe':
                stopped.set()
        def prepare():
            self.assertIsNone(campaign._MEASUREMENT_BUDGET.get())
            campaign.preparation_progress('probe', path='owned source')
            self.fail('Stop must unwind source preparation')
        with mock.patch.object(main, '_prepare_quick_suite_clip', side_effect=prepare), \
             mock.patch.object(main, 'run_benchmark_batch') as encode:
            rc = main.run_with_args(self.args(no_submit=True), event_sink=sink, cancel_event=stopped, interactive=False)
        self.assertEqual(rc, 130)
        encode.assert_not_called()
        self.assertEqual(events[-1]['type'], 'run_interrupted')
        self.assertEqual(events[-1]['scope'], 'preparation')

    def test_hash_copy_and_runtime_hash_observe_stop_between_chunks(self):
        stop = threading.Event()
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'source'
            source.write_bytes(b'x' * (2 * 1024 * 1024))
            for action in (lambda: suite._sha256_of_file(str(source)),
                           lambda: suite._copy_preparation_file(str(source), str(Path(root) / 'copy')),
                           lambda: runtime_lock._sha256_path(str(source))):
                stop.set()
                with self.assertRaises(KeyboardInterrupt):
                    with campaign.PreparationScope(stop).activate():
                        action()
            stop.clear()
            def progress(stage, **details):
                if details.get('completedBytes', 0) >= 1024 * 1024:
                    stop.set()
            with mock.patch.object(campaign.time, "monotonic", side_effect=itertools.count()), \
                    self.assertRaises(KeyboardInterrupt), campaign.PreparationScope(stop, progress).activate():
                suite._copy_preparation_file(str(source), str(Path(root) / 'partial'))
            self.assertEqual((Path(root) / 'partial').stat().st_size, 1024 * 1024)

    def test_stalled_probe_cancels_owned_process_on_first_poll(self):
        stop = threading.Event()
        process = mock.MagicMock()
        process.__enter__.return_value = process
        def communicate(**kwargs):
            self.assertLessEqual(kwargs['timeout'], 0.2)
            stop.set()
            raise subprocess.TimeoutExpired(['probe'], kwargs['timeout'])
        process.communicate.side_effect = communicate
        with mock.patch.object(campaign.subprocess, 'Popen', return_value=process), \
             mock.patch('client.ffmpeg._terminate_owned_process') as terminate:
            with self.assertRaises(KeyboardInterrupt), campaign.PreparationScope(stop).activate():
                campaign.run_measurement_process(['probe'], stdout=subprocess.PIPE)
        terminate.assert_called_once_with(process)

    def test_cancelled_resume_preparation_preserves_original_journal_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.args(no_submit=True, queue_dir=directory)
            root = campaign.journal_path(directory, args.resume_campaign)
            root.mkdir(parents=True)
            manifest = {'seed': 17, 'tasks': [{'encoder': 'libx264', 'preset': 'fast',
                'crf': 24, 'rateControl': None, 'clipId': 'athletic'}]}
            (root / 'manifest.json').write_text(json.dumps(manifest))
            (root / 'attempt-001.json').write_bytes(b'prior durable record')
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            with mock.patch.object(main, '_prepare_named_suite_clip', side_effect=KeyboardInterrupt), \
                 mock.patch.object(main, 'run_benchmark_batch') as batch:
                self.assertEqual(main._resume_campaign(args), 130)
            batch.assert_not_called()
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)

    def test_cancelled_extraction_preserves_pack_and_prior_cache_cleans_staging(self):
        stop = threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            pack = Path(directory) / 'pack.tar.gz'
            with tarfile.open(pack, 'w:gz') as archive:
                entry = tarfile.TarInfo('canonical/test.mkv')
                entry.size = 4
                archive.addfile(entry, io.BytesIO(b'test'))
            original = pack.read_bytes()
            target = Path(suite._suite_pack_extract_root({'suiteFingerprint': 'test'}, directory))
            target.mkdir(parents=True)
            (target / 'prior').write_bytes(b'prior cache')
            def progress(stage, **details):
                if stage == 'copy':
                    stop.set()
            with self.assertRaises(KeyboardInterrupt), campaign.PreparationScope(stop, progress).activate():
                suite._extract_suite_pack(str(pack), {'suiteFingerprint': 'test'}, directory)
            self.assertEqual(pack.read_bytes(), original)
            self.assertEqual((target / 'prior').read_bytes(), b'prior cache')
            self.assertEqual(list(target.parent.glob('suite-pack-*')), [])

    def test_progress_is_throttled_and_does_not_start_budget(self):
        progress = mock.Mock()
        with mock.patch.object(campaign.time, 'monotonic', return_value=10), campaign.PreparationScope(progress=progress).activate():
            for count in range(100):
                campaign.preparation_progress('hash', path='same', completedBytes=count)
            self.assertIsNone(campaign._MEASUREMENT_BUDGET.get())
        progress.assert_called_once()


if __name__ == '__main__':
    unittest.main()
