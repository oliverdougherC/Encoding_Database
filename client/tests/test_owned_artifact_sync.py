"""Exercise Windows writable-descriptor durability requirements on every host."""
import errno
import hashlib
import json
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from client import campaign, ffmpeg, main, protocol, spool
from client.artifacts import AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND
from client.hardware_monitor import HardwareMetrics


@contextmanager
def windows_file_sync_semantics():
    # Windows uses _commit/FlushFileBuffers, requiring a write-capable handle.
    # Use the real Windows function there; emulate that descriptor restriction
    # on POSIX so the platform regression also runs in Linux/macOS unit suites.
    if os.name == 'nt':
        yield
        return
    import fcntl
    original = os.fsync
    def checked(fd):
        if stat.S_ISREG(os.fstat(fd).st_mode) and fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY:
            raise OSError(errno.EBADF, 'Bad file descriptor')
        return original(fd)
    with mock.patch.object(os, 'fsync', side_effect=checked):
        yield


def test_owned_file_sync_uses_writable_handle_without_changing_bytes(tmp_path):
    path = tmp_path/'évidence.mp4'
    original = bytes(range(256))
    path.write_bytes(original)
    with windows_file_sync_semantics():
        with path.open('rb') as handle:
            with pytest.raises(OSError) as failure:
                os.fsync(handle.fileno())
        assert failure.value.errno == errno.EBADF
        campaign.sync_owned_file(path)
    assert path.read_bytes() == original


def test_owned_file_sync_never_suppresses_disk_failure_or_creates_missing_file(tmp_path):
    path = tmp_path/'artifact.mp4'
    with pytest.raises(FileNotFoundError):
        campaign.sync_owned_file(path)
    assert not path.exists()
    path.write_bytes(b'evidence')
    with mock.patch.object(os, 'fsync', side_effect=OSError(errno.ENOSPC, 'disk full')):
        with pytest.raises(OSError) as failure:
            campaign.sync_owned_file(path)
    assert failure.value.errno == errno.ENOSPC
    assert path.read_bytes() == b'evidence'


def test_process_journal_and_spool_commit_owned_artifact_with_windows_semantics(tmp_path):
    journal = campaign.CampaignJournal(str(tmp_path), 'campaign-0123456789abcdef', {'seed': 1}, 10)
    artifact = journal.root/'warmup.mp4'
    checkpoint = journal.root/'warmup.mp4.process.json'
    command = [sys.executable, '-c', 'import pathlib,sys;pathlib.Path(sys.argv[1]).write_bytes(b"encoded")', str(artifact)]
    monitor = SimpleNamespace(start=lambda: None, stop=lambda: SimpleNamespace())
    with windows_file_sync_semantics(), mock.patch.object(ffmpeg, 'HardwareMonitor', return_value=monitor):
        _, _, code, _, metrics = ffmpeg._run_monitored(command, encoder_name='libx264', checkpoint_path=str(checkpoint))
        assert code == 0
        record = protocol.BenchmarkRunRecord(
            schedule=protocol.ScheduledRun('campaign-0123456789abcdef', 'recipe', 'warmup', 1, 1),
            timing=protocol.EncodeTiming.from_measurement(start_monotonic_ns=metrics.encode_start_monotonic_ns,
                end_monotonic_ns=metrics.encode_end_monotonic_ns, source_frame_count=24, encoded_frame_count=24, source_fps=24),
            probe=protocol.ArtifactProbe(decodable=True, frame_count=24, size_bytes=7),
            metadata={'info': {'artifactPath': str(artifact)}})
        journal.save(record)
        digest = hashlib.sha256(b'encoded').hexdigest()
        queued, _ = spool.spool_payload(str(tmp_path), {'submissionKind': AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND,
            'artifactPath': str(artifact), 'artifactSha256': digest, 'artifactByteSize': 7,
            'runCreate': {'artifact': {'sha256': digest, 'byteSize': 7}}})
    assert json.loads(checkpoint.read_text())['artifactByteSize'] == 7
    restored = campaign.CampaignJournal(str(tmp_path), 'campaign-0123456789abcdef', {'seed': 1}, 10)
    assert restored.records[1].metadata['info']['artifactSha256'] == digest
    assert Path(spool.load_spool_entry(queued)['payload']['artifactPath']).read_bytes() == b'encoded'
    assert artifact.read_bytes() == b'encoded'


def test_encode_result_checkpoint_flush_obeys_windows_semantics(tmp_path):
    artifact = tmp_path/'encoded.mp4'
    hardware = HardwareMetrics()
    hardware.encode_start_monotonic_ns = 1_000_000_000
    hardware.encode_end_monotonic_ns = 2_000_000_000
    def encode(command, **kwargs):
        artifact.write_bytes(b'encoded')
        return 'frame=24', '', 0, 1.0, hardware
    probe = {'pixelFormat': 'yuv420p', 'bitDepth': 8, 'chromaSubsampling': '4:2:0',
             'containerFormat': 'mp4', 'timeBase': '1/24000', 'sourceFrameCount': 24,
             'sourceFps': 24, 'sourceDurationSeconds': 1}
    with windows_file_sync_semantics(), mock.patch.object(ffmpeg, '_run_monitored', side_effect=encode), mock.patch.object(ffmpeg, 'probe_video_stream_metrics', return_value=probe), mock.patch.object(ffmpeg, 'validate_artifact_decodability', return_value=(True, None)):
        result = ffmpeg.encode_to_artifact(input_path='unused', encoder='libx264', preset='fast', crf=24,
            out_dir=str(tmp_path), artifact_name='encoded.mp4', checkpoint_path=str(tmp_path/'result.process.json'))
    assert result['error'] is None
    assert json.loads((tmp_path/'result.process.json').read_text())['artifactSha256'] == hashlib.sha256(b'encoded').hexdigest()
    assert artifact.read_bytes() == b'encoded'


@pytest.mark.parametrize('debug', [False, True])
def test_retained_campaign_traceback_is_opt_in_and_exit_stays_failed(tmp_path, monkeypatch, capsys, debug):
    from test_main_routing import MainRoutingTests
    fixture = MainRoutingTests()
    clip = fixture._quick_clip()
    args = fixture._batch_args(str(tmp_path), no_submit=True)
    args.local_metrics = False
    monkeypatch.setenv('ENCODINGDB_DEBUG_TRACEBACK', '1' if debug else '0')
    @contextmanager
    def failed_lock():
        raise OSError(errno.EBADF, 'Bad file descriptor')
        yield
    journal = SimpleNamespace(root=tmp_path, records={}, check_budget=lambda: 1000, measurement_lock=failed_lock)
    with mock.patch.object(main, 'ensure_ffmpeg_and_ffprobe', return_value=(True, 'test')), mock.patch.object(main, '_build_protocol_recipe_specs', return_value=[protocol.RecipeSpec('recipe', protocol.StructuralExpectation())]), mock.patch.object(main, 'CampaignJournal', return_value=journal), mock.patch.object(main, 'physical_source_id', return_value='installation-'+'a'*64), mock.patch('client.identity.runtime_identity', return_value={}), mock.patch.object(main, 'selected_device', return_value={'deviceId':'cpu'}):
        code = main.run_benchmark_batch(hardware=main.HardwareInfo('CPU',None,16,'OS'), base_url='unused',
            args=args, tasks=[{'encoder':'libx264','preset':'fast','crf':24,'suiteClip':clip}])
    stderr = capsys.readouterr().err
    assert code == 6
    assert 'Campaign retained for resume: [Errno 9] Bad file descriptor' in stderr
    assert ('Traceback (most recent call last)' in stderr) is debug
