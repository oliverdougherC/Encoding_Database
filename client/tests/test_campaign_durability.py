import dataclasses
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from client import ffmpeg, main, protocol, spool, runtime_lock
from client.campaign import CampaignJournal, atomic_json, physical_source_id
from client.network import SubmitError, check_compatibility, retry_after_seconds


def test_process_interval_includes_launch_and_flush_excludes_monitor():
    ticks = [0]
    class Monitor:
        def __init__(self, **kwargs): pass
        def start(self): ticks[0] += 2_000_000_000
        def stop(self):
            ticks[0] += 2_000_000_000
            return SimpleNamespace()
    class Process:
        pid = 123
        returncode = 0
        def __init__(self, *args, **kwargs): ticks[0] += 200_000_000
        def communicate(self, **kwargs):
            ticks[0] += 800_000_000
            return 'frame=240', ''
    with mock.patch.object(ffmpeg, 'HardwareMonitor', Monitor), mock.patch.object(ffmpeg.subprocess, 'Popen', Process), mock.patch.object(ffmpeg.time, 'perf_counter_ns', side_effect=lambda: ticks[0]):
        result = ffmpeg._run_monitored(['ffmpeg', 'out.mp4'], encoder_name='libx264')
    assert result[3] == 1
    assert result[4].encode_start_monotonic_ns == 2_000_000_000
    assert result[4].encode_end_monotonic_ns == 3_000_000_000
    assert ticks[0] == 5_000_000_000


def test_validation_latency_does_not_change_submitted_timing(tmp_path):
    # The canonical driver consumes only the interval returned by FFmpeg. A
    # deliberately delayed validation callback cannot stretch the reported tuple.
    from test_main_routing import MainRoutingTests, _DummyDashboard
    fixture = MainRoutingTests()
    clip = fixture._quick_clip()
    observed = []
    ticks = [10_000_000_000]
    info = {'artifactPath': str(tmp_path/'out.mp4'), 'encoderUsed': 'libx264', 'presetUsed':'fast',
            'fileSizeBytes':4, 'encodeStartMonotonicNs':1_000_000_000, 'encodeEndMonotonicNs':2_000_000_000,
            'elapsedMs':1000, 'error':None}
    def validate(path):
        ticks[0] += 2_000_000_000
        return fixture._artifact_contract()
    args = fixture._batch_args(str(tmp_path))
    args.local_metrics = False
    with mock.patch.object(main,'ensure_ffmpeg_and_ffprobe',return_value=(True,'ffmpeg 9')), mock.patch.object(main,'_probe_artifact_contract',side_effect=validate), mock.patch.object(main,'probe_video_stream_metrics',return_value={'sourceFps':24,'sourceDurationSeconds':5}), mock.patch.object(main,'encode_to_artifact',return_value=info), mock.patch.object(main,'_capture_protocol_environment_snapshot',return_value=protocol.EnvironmentSnapshot(selected_accelerator='software')), mock.patch.object(main,'BatchRunDashboard',_DummyDashboard), mock.patch.object(main,'sha256_of_file',return_value='a'*64), mock.patch.object(main,'_build_authoritative_run_create_request',side_effect=lambda **kw: observed.append(kw['record'].timing) or {'artifact':{'sha256':'a'*64,'byteSize':4}}), mock.patch.object(main,'compute_metrics_parallel') as metrics, mock.patch.object(main.time,'perf_counter_ns',side_effect=lambda:ticks[0]):
        assert main.run_benchmark_batch(hardware=main.HardwareInfo('CPU',None,16,'OS'),base_url='http://invalid',args=args,tasks=[{'encoder':'libx264','preset':'fast','crf':24,'suiteClip':clip}]) == 0
    assert len(observed) == 2
    assert all(t.elapsed_s == 1 and t.encode_fps == 120 and t.realtime_multiple == 5 for t in observed)
    metrics.assert_not_called()


def test_atomic_failure_preserves_previous_checkpoint(tmp_path):
    path = tmp_path/'record.json'
    atomic_json(path, {'before':True})
    with mock.patch('client.campaign.os.replace',side_effect=OSError('disk full')):
        with pytest.raises(OSError): atomic_json(path, {'after':True})
    assert json.loads(path.read_text()) == {'before':True}
    assert len(list(tmp_path.iterdir())) == 1


def test_installation_identity_is_persistent_distinct_and_private(tmp_path):
    first = physical_source_id(tmp_path/'one')
    assert first == physical_source_id(tmp_path/'one')
    assert first != physical_source_id(tmp_path/'two')
    assert len(first) == len('installation-') + 64
    assert not any(text in first for text in ('CPU','GPU','hostname'))


def test_journal_resume_keeps_skipped_warmup_and_adaptive_schedule(tmp_path):
    recipe = protocol.RecipeSpec('r', protocol.StructuralExpectation(frame_count=24))
    cfg = protocol.ProtocolConfig.for_version('7.1', max_adaptive_repeats=2)
    campaign_id = protocol.generate_campaign_id('7.1',['r'],123)
    journal = CampaignJournal(str(tmp_path),campaign_id,{'seed':123},10)
    calls = []
    def encode(schedule, recipe):
        calls.append(schedule.execution_order)
        if schedule.execution_order == 4:
            raise KeyboardInterrupt
        return protocol.EncodeOutcome(protocol.EncodeTiming.from_measurement(start_monotonic_ns=1,end_monotonic_ns=1_000_000_001,source_frame_count=24,encoded_frame_count=24,source_fps=24), protocol.ArtifactProbe(decodable=True,frame_count=24,size_bytes=4))
    def sample(schedule, recipe):
        return protocol.EnvironmentSnapshot(selected_accelerator='software',background_cpu_pct=90 if schedule.execution_order == 2 else 0)
    with pytest.raises(KeyboardInterrupt):
        protocol.execute_protocol_campaign(recipes=[recipe],config=cfg,encode_runner=encode,environment_sampler=sample,seed=123,record_sink=journal.save)
    assert sorted(journal.records) == [1,2,3]
    restored = CampaignJournal(str(tmp_path),campaign_id,{'seed':123},10)
    def finish(schedule, recipe):
        assert schedule.execution_order == 4
        return protocol.EncodeOutcome(protocol.EncodeTiming.from_measurement(start_monotonic_ns=1,end_monotonic_ns=1_000_000_001,source_frame_count=24,encoded_frame_count=24,source_fps=24), protocol.ArtifactProbe(decodable=True,frame_count=24,size_bytes=4))
    result = protocol.execute_protocol_campaign(recipes=[recipe],config=cfg,encode_runner=finish,environment_sampler=sample,seed=123,record_sink=restored.save,resumed_records=restored.records)
    assert result.campaign_id == campaign_id
    assert len(result.recipe_results[0].runs) == 4
    assert result.recipe_results[0].runs[1].skipped_before_encode
    assert result.recipe_results[0].stability.stable


def test_retry_after_survives_restart_and_deadline_expires(tmp_path):
    path, _ = spool.spool_payload(str(tmp_path),{'codec':'libx264'})
    with mock.patch.object(spool,'submit',side_effect=SubmitError('busy',retryable=True,retry_after=120)) as submit:
        assert spool.submit_spooled_path(path,queue_dir=str(tmp_path),base_url='unused',api_key='',retries=1,use_token=False)[0] == 'retained'
        assert spool.load_spool_entry(path)['nextAttemptAt'] >= spool.time.time()+119
        spool.replay_spool(str(tmp_path),base_url='unused',api_key='',retries=1,use_token=False)
        assert submit.call_count == 1
    entry = spool.load_spool_entry(path)
    entry['retryDeadlineAt'] = 1
    atomic_json(Path(path),entry)
    assert spool.submit_spooled_path(path,queue_dir=str(tmp_path),base_url='unused',api_key='',retries=1,use_token=False)[0] == 'dead_lettered'


def test_compatibility_refuses_old_epoch_before_campaign(tmp_path):
    response = SimpleNamespace(status_code=200,json=lambda:{'protocolVersion':'7.0','minimumClientVersion':'client/0.2.0','encodeTimerBoundary':'old'})
    with mock.patch('client.network._load_requests',return_value=SimpleNamespace(get=lambda *a,**k:response)):
        with pytest.raises(SubmitError): check_compatibility('http://example.invalid','client/0.3.0')


def test_runtime_dependency_changes_and_missing_files_are_rejected(tmp_path):
    binary = tmp_path/'ffmpeg'; binary.write_bytes(b'exe')
    library = tmp_path/'lib'/'library.dylib'; library.parent.mkdir(); library.write_bytes(b'good')
    expected = runtime_lock.runtime_dependency_records(str(binary))
    runtime_lock._verify_dependencies(str(binary),expected)
    library.write_bytes(b'evil')
    with pytest.raises(runtime_lock.RuntimeLockError): runtime_lock._verify_dependencies(str(binary),expected)
    library.unlink()
    with pytest.raises(runtime_lock.RuntimeLockError): runtime_lock._verify_dependencies(str(binary),expected)


def test_all_platforms_require_actual_svt_encoder():
    for platform in ('linux','mac','win'):
        requirements=runtime_lock.runtime_capability_requirements(platform)
        assert 'libsvtav1' in requirements['requiredEncoders']
        assert 'libsvtav1' in requirements['smokeTestEncoders']


def test_default_single_and_full_route_through_authoritative_campaign():
    from test_main_routing import MainRoutingTests
    fixture = MainRoutingTests()
    args = main.build_arg_parser().parse_args(['--codec','libx264','--presets','fast','--submit'])
    clips = [dataclasses.replace(fixture._quick_clip(),clip_id=f'clip-{n}') for n in range(7)]
    with mock.patch.object(main,'check_compatibility',return_value={}), mock.patch.object(main,'_prepare_quick_suite_clip',return_value=clips[0]), mock.patch.object(main,'_prepare_full_suite',return_value=clips), mock.patch.object(main,'has_encoder',return_value=True), mock.patch.object(main,'run_benchmark_batch',return_value=0) as run, mock.patch.object(main,'detect_hardware',return_value=main.HardwareInfo('CPU',None,16,'OS')):
        assert main.run_with_args(args,interactive=False) == 0
        assert len(run.call_args.kwargs['tasks']) == 1
        assert run.call_args.kwargs['args'].strict_authoritative
        args.campaign = 'full'
        assert main.run_with_args(args,interactive=False) == 0
        assert len(run.call_args.kwargs['tasks']) == 7


def test_completed_local_campaign_publishes_without_source_or_encoder(tmp_path):
    from client.campaign import journal_path
    campaign_id='campaign-0123456789abcdef'
    root=journal_path(str(tmp_path),campaign_id)
    atomic_json(root/'campaign-complete.json',{'skipped':0,'failed':0})
    payload={'retained':'immutable'}
    atomic_json(root/'submission-000001.json',payload)
    with mock.patch.object(main,'check_compatibility'), mock.patch.object(main,'spool_payload',return_value=('retained.json',{})) as save, mock.patch.object(main,'replay_spool',return_value=spool.ReplayStats(submitted=1)), mock.patch.object(main,'_prepare_named_suite_clip') as source, mock.patch.object(main,'run_benchmark_batch') as encode:
        assert main.main(['prog','--resume-campaign',campaign_id,'--submit','--queue-dir',str(tmp_path)]) == 0
    save.assert_called_once_with(str(tmp_path),payload,max_storage_mb=2048)
    source.assert_not_called()
    encode.assert_not_called()


def test_cancellation_stops_only_owned_process():
    import subprocess
    import sys
    import threading
    event=threading.Event()
    timer=threading.Timer(0.3,event.set)
    real_popen=subprocess.Popen
    owned=[]
    def launch(*args,**kwargs):
        process=real_popen(*args,**kwargs)
        owned.append(process)
        return process
    monitor=SimpleNamespace(start=lambda:None,stop=lambda:SimpleNamespace())
    timer.start()
    try:
        with mock.patch.object(ffmpeg,'HardwareMonitor',return_value=monitor), mock.patch.object(ffmpeg.subprocess,'Popen',side_effect=launch):
            with pytest.raises(KeyboardInterrupt):
                ffmpeg._run_monitored([sys.executable,'-c','import time;time.sleep(30)'],encoder_name='libx264',cancel_event=event)
        assert len(owned) == 1 and owned[0].poll() is not None
    finally:
        timer.cancel()
        for process in owned:
            if process.poll() is None:
                process.kill()
                process.wait()


@pytest.mark.skipif(os.name == 'nt',reason='POSIX process group crash recovery; native Windows taskkill requires Windows acceptance')
def test_orphan_after_client_kill_is_fenced_before_resume(tmp_path):
    import subprocess
    import sys
    import psutil
    journal=CampaignJournal(str(tmp_path),'campaign-0123456789abcdef',{'seed':1},10)
    command=[sys.executable,'-c','import time;time.sleep(30)',str(journal.root/'out.mp4')]
    process=subprocess.Popen(command,start_new_session=True)
    try:
        atomic_json(journal.root/'test.active.json',{'pid':process.pid,'createdAt':psutil.Process(process.pid).create_time(),'command':command})
        with journal.measurement_lock():
            assert process.poll() is not None
        assert not list(journal.root.glob('*.active.json'))
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()


def test_process_interval_waits_for_exit_after_both_pipes_close():
    import sys
    # EOF must not end the measurement: the owned process still has work to do.
    command = [sys.executable, '-c',
               'import os,time;os.close(1);os.close(2);time.sleep(0.4);os._exit(23)']
    monitor = SimpleNamespace(start=lambda: None, stop=lambda: SimpleNamespace())
    with mock.patch.object(ffmpeg, 'HardwareMonitor', return_value=monitor):
        stdout, stderr, returncode, elapsed, metrics = ffmpeg._run_monitored(command, encoder_name='libx264')
    assert stdout == stderr == ''
    assert returncode == 23
    assert elapsed >= 0.4
    assert metrics.encode_end_monotonic_ns - metrics.encode_start_monotonic_ns >= 400_000_000


def test_slow_active_process_journal_does_not_extend_encode_interval(tmp_path):
    import sys
    import time
    import client.campaign as campaign
    original = campaign.atomic_json
    writer_started = tmp_path / "writer-started"
    def slow_active_receipt(path, payload):
        if str(path).endswith('.active.json'):
            writer_started.write_text('ready')
            time.sleep(2)
        return original(path, payload)
    monitor = SimpleNamespace(start=lambda: None, stop=lambda: SimpleNamespace())
    child = f"import pathlib,time; p=pathlib.Path({str(writer_started)!r})\nwhile not p.exists(): time.sleep(0.01)\ntime.sleep(0.15)"
    command = [sys.executable, '-c', child]
    started = time.perf_counter()
    with mock.patch.object(ffmpeg, 'HardwareMonitor', return_value=monitor), mock.patch.object(campaign, 'atomic_json', side_effect=slow_active_receipt):
        _, _, returncode, elapsed, _ = ffmpeg._run_monitored(command, encoder_name='libx264', checkpoint_path=str(tmp_path / 'process.json'))
    whole_call = time.perf_counter() - started
    assert returncode == 0
    assert whole_call >= 2
    assert elapsed >= 0.15
    assert whole_call - elapsed >= 1
    assert not list(tmp_path.glob('*.active.json'))


def test_process_receipt_disk_failure_cancels_owned_encode(tmp_path):
    import subprocess
    import sys
    import client.campaign as campaign
    processes = []
    real_popen = subprocess.Popen
    def launch(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process
    monitor = SimpleNamespace(start=lambda: None, stop=lambda: SimpleNamespace())
    try:
        with mock.patch.object(ffmpeg, 'HardwareMonitor', return_value=monitor), mock.patch.object(ffmpeg.subprocess, 'Popen', side_effect=launch), mock.patch.object(campaign, 'atomic_json', side_effect=OSError('disk full')):
            with pytest.raises(OSError, match='disk full'):
                ffmpeg._run_monitored([sys.executable, '-c', 'import time;time.sleep(30)'], encoder_name='libx264', checkpoint_path=str(tmp_path/'process.json'))
        assert len(processes) == 1 and processes[0].poll() is not None
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait()
