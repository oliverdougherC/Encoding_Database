"""Real helper execution followed by an extraction-path change at relaunch."""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from client import campaign, config, ffmpeg, identity, protocol
from client.hardware_monitor import HardwareMetrics


@pytest.fixture(scope='module')
def helpers(tmp_path_factory):
    root = tmp_path_factory.mktemp('packaged-helper-relaunch')
    original = Path(os.environ.get('FFMPEG_EXE') or config.ffmpeg_exe()).resolve()
    first, second = root/'_MEIfirst'/original.name, root/'_MEIsecond'/original.name
    for target in (first, second):
        target.parent.mkdir()
        shutil.copy2(original, target)
        # Only the private clone is made writable for the intentional tamper case.
        target.chmod(target.stat().st_mode | 0o200)
        if (original.parent/'lib').is_dir():
            shutil.copytree(original.parent/'lib', target.parent/'lib')
        else:
            (target.parent/'lib').mkdir()
        # A private bundled dependency fixture is hashed alongside real libraries.
        (target.parent/'lib'/'checkpoint-test-dependency.bin').write_bytes(b'original dependency')
    source = root/'source.mkv'
    subprocess.run([str(first), '-v','error','-f','lavfi','-i','testsrc2=size=64x64:rate=24',
                    '-frames:v','24','-c:v','ffv1','-pix_fmt','yuv420p',str(source)],
                   capture_output=True, check=True, timeout=30)
    return first, second, source


@pytest.fixture
def pending_validation(tmp_path, helpers):
    first, second, source = helpers
    source_id = campaign.physical_source_id(tmp_path/'state')
    manifest = {'seed':17, 'physicalSourceId':source_id, 'runtime':identity.process_runtime_identity(str(first))}
    journal = campaign.CampaignJournal(str(tmp_path/'queue'),'campaign-0123456789abcdef',manifest,256)
    checkpoint = journal.root/'warmup.process.json'
    arguments = dict(input_path=str(source), encoder='libx264', preset='fast', crf=24,
                     out_dir=str(journal.root), artifact_name='warmup.mp4', checkpoint_path=str(checkpoint))
    monitor = mock.Mock()
    monitor.stop.return_value = HardwareMetrics()
    # Execute real FFmpeg, then interrupt immediately before validation starts.
    with mock.patch.object(config,'ffmpeg_exe',return_value=str(first)), mock.patch.object(ffmpeg,'HardwareMonitor',return_value=monitor), mock.patch.object(ffmpeg,'probe_video_stream_metrics',side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            ffmpeg.encode_to_artifact(**arguments)
    saved = json.loads(checkpoint.read_text())
    artifact = journal.root/'warmup.mp4'
    assert saved['returncode'] == 0
    assert saved['artifactSha256'] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert saved['processRuntime'] == identity.process_runtime_identity(str(second))
    probe = ffmpeg.probe_video_stream_metrics(str(artifact))
    assert probe['sourceFrameCount'] == 24
    return arguments, saved, artifact, checkpoint, manifest, source_id


def resume_without_processes(second, arguments, probe):
    with mock.patch.object(config,'ffmpeg_exe',return_value=str(second)), mock.patch.object(ffmpeg.subprocess,'Popen',side_effect=AssertionError('resume launched a process')) as popen, mock.patch.object(ffmpeg,'probe_video_stream_metrics',return_value=probe) as validation_probe, mock.patch.object(ffmpeg,'validate_artifact_decodability',return_value=(True,None)) as decode:
        result = ffmpeg.encode_to_artifact(**arguments)
    popen.assert_not_called()
    validation_probe.assert_called_once()
    decode.assert_called_once()
    return result


def test_completed_process_resumes_after_helper_relocation_without_reencoding(helpers, pending_validation, tmp_path):
    first, second, _ = helpers
    arguments, saved, artifact, checkpoint, manifest, source_id = pending_validation
    probe = ffmpeg.probe_video_stream_metrics(str(artifact))
    original_checkpoint = checkpoint.read_bytes()
    result = resume_without_processes(second, arguments, probe)
    assert result['error'] is None
    assert result['encodeStartMonotonicNs'] == saved['hardwareMetrics']['encode_start_monotonic_ns']
    assert result['encodeEndMonotonicNs'] == saved['hardwareMetrics']['encode_end_monotonic_ns']
    assert result['executedCommand'] == saved['command']
    assert result['executedCommand'][0] == str(first)
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == saved['artifactSha256']
    assert checkpoint.read_bytes() == original_checkpoint
    # GUI and CLI share this journal/encode engine; relaunch keeps source and schedule.
    new_manifest = {**manifest, 'runtime':identity.process_runtime_identity(str(second))}
    restored = campaign.CampaignJournal(str(tmp_path/'queue'),'campaign-0123456789abcdef',new_manifest,256)
    schedule = protocol.ScheduledRun('campaign-0123456789abcdef','recipe','warmup',1,1)
    record = protocol.BenchmarkRunRecord(schedule=schedule,
        timing=protocol.EncodeTiming.from_measurement(start_monotonic_ns=result['encodeStartMonotonicNs'],end_monotonic_ns=result['encodeEndMonotonicNs'],source_frame_count=24,encoded_frame_count=24,source_fps=24),
        probe=protocol.ArtifactProbe(decodable=True,frame_count=24,size_bytes=artifact.stat().st_size),
        metadata={'info':result})
    restored.save(record)
    again = campaign.CampaignJournal(str(tmp_path/'queue'),'campaign-0123456789abcdef',new_manifest,256)
    assert again.records[1].schedule == schedule
    assert new_manifest['seed'] == 17
    assert campaign.physical_source_id(tmp_path/'state') == source_id


@pytest.mark.parametrize('changed', ['executable','dependency','arguments','source_argument','artifact','missing_binding'])
def test_resume_rejects_changed_identity_before_any_process_launch(helpers,pending_validation,changed):
    _, second, source = helpers
    arguments, saved, artifact, checkpoint, _, _ = pending_validation
    target = None
    original = None
    stamp = None
    if changed in ('executable','dependency','artifact'):
        target = second if changed == 'executable' else (second.parent/'lib'/'checkpoint-test-dependency.bin' if changed == 'dependency' else artifact)
        original = target.read_bytes()
        stamp = target.stat()
        target.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    elif changed == 'arguments':
        arguments = {**arguments, 'crf':23}
    elif changed == 'source_argument':
        arguments = {**arguments, 'input_path':str(source.parent/'other-source.mkv')}
    else:
        saved.pop('processRuntime')
        checkpoint.write_text(json.dumps(saved))
    try:
        with mock.patch.object(config,'ffmpeg_exe',return_value=str(second)), mock.patch.object(ffmpeg.subprocess,'Popen',side_effect=AssertionError('invalid resume launched a process')) as popen:
            with pytest.raises(ValueError, match='checkpoint'):
                ffmpeg.encode_to_artifact(**arguments)
        popen.assert_not_called()
    finally:
        if target is not None:
            target.write_bytes(original)
            os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))


def test_runtime_hashing_happens_before_encode_clock(tmp_path):
    events=[]
    class Monitor:
        def __init__(self,**kwargs):pass
        def start(self):events.append('monitor')
        def stop(self):return HardwareMetrics()
    class Process:
        pid=123
        returncode=0
        def __init__(self,*args,**kwargs):events.append('spawn')
        def communicate(self,**kwargs):return '', ''
        def poll(self):return 0
    def fingerprint(executable):
        events.append('hash')
        return {'schemaVersion':1,'executableSha256':'a'*64,'runtimeDependencies':[]}
    ticks=iter([1_000_000_000,2_000_000_000])
    def clock():events.append('clock');return next(ticks)
    with mock.patch.object(identity,'process_runtime_identity',side_effect=fingerprint), mock.patch.object(ffmpeg,'HardwareMonitor',Monitor), mock.patch.object(ffmpeg.subprocess,'Popen',Process), mock.patch.object(ffmpeg.time,'perf_counter_ns',side_effect=clock), mock.patch('psutil.Process',side_effect=__import__('psutil').NoSuchProcess(123)):
        _,_,_,elapsed,_=ffmpeg._run_monitored(['helper',str(tmp_path/'unused')],encoder_name='libx264',checkpoint_path=str(tmp_path/'process.json'))
    assert events[:4] == ['hash','monitor','clock','spawn']
    assert elapsed == 1
