import argparse
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest import mock

from client import main


class QuickSummaryTests(unittest.TestCase):
    def exercise(self, no_submit, status='submitted'):
        args = argparse.Namespace(codec='libx264', presets='fast', crf=24, base_url='https://example.invalid', api_key='', no_submit=no_submit, queue_dir='unused', retries=1, use_token=False, pause_on_exit=False)
        clip = SimpleNamespace(path='reference.mkv', input_hash='a'*64, suite_version='test-suite', workload_id='test-clip', payload_content_class='action')
        hardware = SimpleNamespace(cpuModel='CPU', gpuModel='GPU', ramGB=16, os='test')
        events = []
        with ExitStack() as stack:
            for name, value in {'_apply_submission_policy':args, 'ensure_ffmpeg_and_ffprobe':(True,'ffmpeg test'), '_ensure_local_quality_stack':(True,0), '_prepare_quick_suite_clip':clip, 'has_encoder':True, 'is_hardware_encoder_name':False, 'detect_hardware':hardware, 'count_pending_entries':0, '_replay_pending_uploads':0, '_suite_identity_note':'fixture', '_submit_payload_with_spool':(status,'fixture',0), 'run_single_benchmark':{'fps':30,'fileSizeBytes':100,'codec':'libx264','preset':'fast'}}.items():
                stack.enter_context(mock.patch.object(main,name,return_value=value))
            stack.enter_context(mock.patch.object(main,'_apply_v7_score_contract'))
            stack.enter_context(mock.patch.object(main,'sanitize_payload_for_server',side_effect=lambda p:p))
            stack.enter_context(mock.patch.object(main,'BenchmarkProgress'))
            stack.enter_context(mock.patch.object(main,'print_benchmark_result'))
            stack.enter_context(mock.patch.object(main,'_clear_screen'))
            stack.enter_context(mock.patch.object(main.config,'_BATCH_ACTIVE',False))
            stack.enter_context(mock.patch.object(main.time,'perf_counter',side_effect=[100.0,105.5]))
            stack.enter_context(mock.patch.object(main.time,'time',return_value=1_800_000_000.0))
            info = stack.enter_context(mock.patch.object(main,'print_info'))
            end = stack.enter_context(mock.patch.object(main,'print_end_screen'))
            self.assertEqual(main.run_with_args(args,event_sink=events.append),0)
            self.assertEqual(next(e for e in events if e['type']=='run_complete')['elapsedSeconds'],5.5)
            return info.call_args_list,end.call_args_list

    def test_dry_run_reports_completed_without_submitted_claim(self):
        info,end=self.exercise(True)
        self.assertEqual(end,[])
        self.assertIn(mock.call('Benchmark complete. Completed 1 encodes in 5.5s. Dry-run: no data submitted.'),info)

    def test_only_successful_submissions_are_counted(self):
        for status,count in [('submitted',1),('retained',0),('failed',0)]:
            with self.subTest(status=status):
                _,end=self.exercise(False,status)
                self.assertEqual(end,[mock.call(count,5.5)])
