"""Guard the physical RTX 5090 minimum-dimension failure without widening other probes."""
from pathlib import Path
import subprocess
from unittest import mock

import pytest

from client import config, encoders


@pytest.fixture(autouse=True)
def isolated_probe_cache():
    with mock.patch.dict(config._ENCODER_USABLE_CACHE, {}, clear=True), \
         mock.patch.object(config, 'ffmpeg_exe', return_value='locked-ffmpeg'):
        yield


@pytest.mark.parametrize('encoder', ['h264_nvenc', 'hevc_nvenc', 'av1_nvenc'])
def test_nvenc_uses_canonical_dimensions_and_measured_device(encoder):
    calls = []

    def driver(cmd, **kwargs):
        calls.append((cmd, kwargs))
        # Physical RTX 5090: the old 128x128 probe returns this error; changing
        # only dimensions to 1920x1080 succeeds. This emulates that regression,
        # not a claim that a mocked subprocess proves hardware acceptance.
        if cmd[cmd.index('-i') + 1] == 'testsrc=size=128x128:rate=30':
            return subprocess.CompletedProcess(cmd, -22, '', 'InitializeEncoder failed: invalid param (8): Frame Dimension less than the minimum supported value.')
        Path(cmd[-1]).write_bytes(b'probe-output')
        return subprocess.CompletedProcess(cmd, 0, '', '')

    with mock.patch.object(encoders.subprocess, 'run', side_effect=driver) as run:
        assert encoders.is_hardware_encoder_usable(encoder)
        assert encoders.is_hardware_encoder_usable(encoder.upper())  # Existing normalized cache key.
        run.assert_called_once()
    cmd, kwargs = calls[0]
    assert cmd == ['locked-ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                   'testsrc=size=1920x1080:rate=30', '-frames:v', '8', '-pix_fmt', 'yuv420p',
                   '-c:v', encoder, '-gpu', '0', '-an', cmd[-1]]
    assert kwargs == {'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE, 'text': True, 'timeout': 8}


@pytest.mark.parametrize('encoder', ['h264_qsv', 'h264_amf', 'h264_videotoolbox', 'hevc_videotoolbox'])
def test_other_hardware_probes_keep_small_input_and_existing_options(encoder):
    def success(cmd, **kwargs):
        assert 'testsrc=size=128x128:rate=30' in cmd
        assert '-gpu' not in cmd
        assert kwargs['timeout'] == 8
        if encoder.endswith('_videotoolbox'):
            assert cmd[cmd.index('-b:v') + 1] == '3000k'
        if encoder == 'h264_videotoolbox':
            assert cmd[cmd.index('-profile:v') + 1] == 'high'
            assert cmd[cmd.index('-g') + 1] == '120'
        if encoder == 'hevc_videotoolbox':
            assert cmd[cmd.index('-tag:v') + 1] == 'hvc1'
        Path(cmd[-1]).write_bytes(b'probe-output')
        return subprocess.CompletedProcess(cmd, 0, '', '')

    with mock.patch.object(encoders.subprocess, 'run', side_effect=success):
        assert encoders.is_hardware_encoder_usable(encoder)


@pytest.mark.parametrize('available', [True, False])
def test_software_av1_does_not_acquire_a_costly_encode_probe(available):
    with mock.patch.object(encoders, 'has_encoder', return_value=available) as listed, \
         mock.patch.object(encoders.subprocess, 'run') as run:
        assert encoders.is_hardware_encoder_usable('libaom-av1') is available
        assert encoders.is_hardware_encoder_usable('libaom-av1') is available
        listed.assert_called_once_with('libaom-av1')
        run.assert_not_called()


@pytest.mark.parametrize('failure', ['driver', 'missing-output', 'empty-output', 'timeout', 'launch-error'])
def test_genuine_failures_remain_unusable_and_cached(failure):
    def fail(cmd, **kwargs):
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(cmd, 8)
        if failure == 'launch-error':
            raise OSError('cannot launch helper')
        if failure == 'driver':
            Path(cmd[-1]).write_bytes(b'partial-output')
            return subprocess.CompletedProcess(cmd, -22, '', 'No capable devices found')
        if failure == 'empty-output':
            Path(cmd[-1]).touch()
        return subprocess.CompletedProcess(cmd, 0, '', '')

    with mock.patch.object(encoders.subprocess, 'run', side_effect=fail) as run:
        assert not encoders.is_hardware_encoder_usable('h264_nvenc')
        assert not encoders.is_hardware_encoder_usable('h264_nvenc')
        run.assert_called_once()
