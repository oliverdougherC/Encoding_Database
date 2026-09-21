import json
import subprocess
import sys
import threading
from pathlib import Path
from unittest import mock

import pytest

from client import campaign, ffmpeg, main, protocol
from client.hardware_monitor import HardwareMetrics


@pytest.mark.parametrize('value', ['0','-1','nan','inf','1e308'])
def test_cli_rejects_unbounded_or_nonpositive_allowance_before_native_work(tmp_path,value):
    with mock.patch.object(main,'run_with_args') as encode:
        with pytest.raises(SystemExit) as failure:
            main.main(['prog','--codec','libx264','--no-submit','--max-duration-minutes',value,'--queue-dir',str(tmp_path)])
    assert failure.value.code == 2
    encode.assert_not_called()


@pytest.mark.parametrize('stage', ['encode','validation'])
@pytest.mark.parametrize('reason', ['deadline','stop'])
def test_deadline_and_gui_stop_close_cancel_owned_measurement_process(stage,reason):
    cancel = threading.Event()
    budget = campaign.MeasurementBudget(0.002 if reason == 'deadline' else 60, cancel_event=cancel)
    timer = threading.Timer(0.12,cancel.set) if reason == 'stop' else None
    command = [sys.executable,'-c','import time;time.sleep(30)']
    processes=[]
    real_popen=subprocess.Popen
    def launch(*args,**kwargs):
        process=real_popen(*args,**kwargs)
        processes.append(process)
        return process
    monitor=mock.Mock()
    monitor.stop.return_value=HardwareMetrics()
    if timer: timer.start()
    expected=KeyboardInterrupt if reason == 'stop' else campaign.MeasurementBudgetExceeded
    try:
        with mock.patch.object(ffmpeg,'HardwareMonitor',return_value=monitor), mock.patch.object(subprocess,'Popen',side_effect=launch):
            with pytest.raises(expected), budget.activate():
                if stage == 'encode':
                    ffmpeg._run_monitored(command,encoder_name='libx264',cancel_event=cancel)
                else:
                    campaign.run_measurement_process(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,check=True,timeout=60)
        assert len(processes) == 1 and processes[0].poll() is not None
        campaign.check_measurement_budget()  # The allowance cannot leak into later uploads.
    finally:
        if timer: timer.cancel()
        for process in processes:
            if process.poll() is None: process.kill()
            process.wait()


def test_budget_exhaustion_is_durable_and_explicit_resume_gets_new_allowance(tmp_path):
    from test_main_routing import MainRoutingTests, _DummyDashboard
    fixture=MainRoutingTests()
    clip=fixture._quick_clip()
    args=fixture._batch_args(str(tmp_path),no_submit=True)
    args.local_metrics=False
    args.campaign_seed=17
    args.max_duration_minutes=0.5
    clock=[0.0]
    calls=[]
    first_invocation=[True]
    def new_budget(minutes,**kwargs):
        return campaign.MeasurementBudget(minutes,clock=lambda:clock[0],**kwargs)
    def encode(**kwargs):
        calls.append(kwargs['artifact_name'])
        clock[0] += 10
        if len(calls) == 3 and first_invocation[0]:
            clock[0] += 1
        campaign.check_measurement_budget()
        artifact=Path(kwargs['out_dir'])/kwargs['artifact_name']
        artifact.write_bytes(b'encoded')
        return {'artifactPath':str(artifact),'encoderUsed':'libx264','presetUsed':'fast','fileSizeBytes':7,
                'encodeStartMonotonicNs':1_000_000_000,'encodeEndMonotonicNs':2_000_000_000,'elapsedMs':1000,'error':None}
    tasks=[{'encoder':'libx264','preset':'fast','crf':24,'suiteClip':clip}]
    hardware=main.HardwareInfo('CPU',None,16,'OS')
    with mock.patch.object(main,'MeasurementBudget',side_effect=new_budget), mock.patch.object(main,'ensure_ffmpeg_and_ffprobe',return_value=(True,'ffmpeg test')), mock.patch.object(main,'_build_protocol_config',return_value=protocol.ProtocolConfig.for_version('7.1',max_adaptive_repeats=0)), mock.patch.object(main,'probe_video_stream_metrics',return_value={'sourceFps':24,'sourceDurationSeconds':5,'containerFormat':'mp4'}), mock.patch.object(main,'_probe_artifact_contract',side_effect=lambda path:fixture._artifact_contract()), mock.patch.object(main,'_capture_protocol_environment_snapshot',return_value=protocol.EnvironmentSnapshot(selected_accelerator='software')), mock.patch.object(main,'encode_to_artifact',side_effect=encode), mock.patch.object(main,'BatchRunDashboard',_DummyDashboard), mock.patch.object(main,'_build_authoritative_run_create_request',return_value={'artifact':{'sha256':'a'*64,'byteSize':7}}), mock.patch.object(main,'build_execution_identity_payload',return_value={}), mock.patch.object(main,'physical_source_id',return_value='installation-'+'a'*64), mock.patch('client.identity.runtime_identity',return_value={}), mock.patch.object(main,'selected_device',return_value={'deviceId':'cpu'}), mock.patch.object(main,'_prepare_named_suite_clip',return_value=clip), mock.patch.object(main,'detect_hardware',return_value=hardware):
        assert main.run_benchmark_batch(hardware=hardware,base_url='unused',args=args,tasks=tasks) == 11
        root=next((tmp_path/'campaigns').iterdir())
        original={path.name:path.read_bytes() for path in root.glob('attempt-*.json')}
        assert len(original) == 2
        status=json.loads(next(root.glob('budget-exhausted-*.json')).read_text())
        assert status['status'] == 'budget_exhausted'
        assert status['maxDurationMinutes'] == 0.5
        assert status['lastStartedAttempt']['execution_order'] == 3
        first_invocation[0]=False
        clock[0]=100.0
        assert main.main(['prog','--resume-campaign',root.name,'--no-submit','--max-duration-minutes','0.5','--queue-dir',str(tmp_path)]) == 0
    assert calls == [
        '001-libx264-fast-24-warmup-r1.mp4',
        '002-libx264-fast-24-measured-r1.mp4',
        '003-libx264-fast-24-measured-r2.mp4',
        '003-libx264-fast-24-measured-r2.mp4',
    ]
    assert all((root/name).read_bytes() == content for name,content in original.items())
    manifest=json.loads((root/'manifest.json').read_text())
    assert manifest['seed'] == 17
    assert manifest['physicalSourceId'] == 'installation-'+'a'*64
    assert (root/'campaign-complete.json').exists()


def test_gui_and_cli_single_args_preserve_requested_allowance():
    base=main.build_arg_parser().parse_args(['--max-duration-minutes','0.25'])
    assert main.build_arg_parser().parse_args([]).max_duration_minutes == 60
    effective=main.build_single_effective_args(base_args=base,encoder='libx264',preset='fast',crf=24)
    assert effective.max_duration_minutes == 0.25
