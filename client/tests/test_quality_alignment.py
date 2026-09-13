"""Regression coverage for mixed-container CFR quality alignment."""
from unittest import mock
import pytest
from client import ffmpeg


def test_fractional_reference_cadence_matches_authoritative_filter():
    graph = ffmpeg.canonical_quality_filter('30000/1001', 'ssim')
    expected = 'fps=29.97002997,settb=AVTB,setpts=N/(29.97002997*TB)'
    assert graph == f'[0:v]{expected}[distorted];[1:v]{expected}[reference];[distorted][reference]ssim'


@pytest.mark.parametrize('rate', [None, 0, -1, 'nan', 'inf', '0/0'])
def test_missing_or_invalid_cadence_cannot_silently_compare_unaligned_frames(rate):
    with pytest.raises(ValueError):
        ffmpeg.canonical_quality_filter(rate, 'ssim')


@pytest.mark.parametrize('metric,output', [('ssim', 'All:0.99'), ('psnr', 'average:42.1')])
def test_diagnostic_metrics_normalize_reference_cadence_and_keep_distorted_first(metric, output):
    with mock.patch.object(ffmpeg, 'probe_video_stream_metrics', return_value={'sourceFps': 24, 'sourceFrameCount': 240}) as probe, \
         mock.patch.object(ffmpeg.subprocess, 'run', return_value=mock.Mock(stdout=output)) as run:
        assert getattr(ffmpeg, f'compute_{metric}')('reference.mkv', 'encoded.mp4') is not None
    assert probe.call_args_list == [mock.call('reference.mkv'), mock.call('encoded.mp4')]
    command = run.call_args.args[0]
    indices = [i for i, value in enumerate(command) if value == '-i']
    assert [command[i + 1] for i in indices] == ['encoded.mp4', 'reference.mkv']
    assert command[command.index('-lavfi') + 1] == ffmpeg.canonical_quality_filter(24, metric)


@pytest.mark.parametrize('encoded', [
    {'sourceFps': 30, 'sourceFrameCount': 240},
    {'sourceFps': 24, 'sourceFrameCount': 239},
])
def test_normalization_cannot_hide_changed_cadence_or_missing_frames(encoded):
    with mock.patch.object(ffmpeg, 'probe_video_stream_metrics', side_effect=[
        {'sourceFps': 24, 'sourceFrameCount': 240}, encoded,
    ]), mock.patch.object(ffmpeg.subprocess, 'run') as run:
        assert ffmpeg.compute_ssim('reference.mkv', 'encoded.mp4') is None
    run.assert_not_called()


def test_only_vmaf_uses_canonical_ten_bit_analysis_format():
    assert ffmpeg.canonical_quality_filter(24, 'libvmaf=model=test').count('format=pix_fmts=yuv420p10le') == 2
    for metric in ['ssim', 'psnr', 'xpsnr']:
        assert 'format=' not in ffmpeg.canonical_quality_filter(24, metric)


def test_vmaf_reads_unique_json_files_without_shared_dash_path(tmp_path):
    import json
    import re
    from pathlib import Path
    paths = []

    def execute(command, **kwargs):
        graph = command[command.index('-lavfi') + 1]
        log_path = Path(re.search(r":log_path='([^']+)'", graph).group(1))
        paths.append(log_path)
        log_path.write_text(json.dumps({'frames': [{'metrics': {'vmaf': v}} for v in [90, 95, 100]], 'pooled_metrics': {'vmaf': {'mean': 95}}}))
        return mock.Mock(returncode=0, stdout='', stderr='VMAF score: 1.0')

    with mock.patch.object(ffmpeg, '_vmaf_filter_candidates', return_value=[{'filter': "libvmaf=model='path=model.json':log_fmt=json:log_path=-", 'metricModelId': 'test'}]), \
         mock.patch.object(ffmpeg, 'probe_video_stream_metrics', return_value={'sourceFps': 24, 'sourceFrameCount': 3}), \
         mock.patch.object(ffmpeg.subprocess, 'run', side_effect=execute):
        for _ in range(2):
            result = ffmpeg.compute_vmaf_metrics('reference.mkv', 'encoded.mp4')
            assert result['vmafMean'] == 95
            assert result['vmafFrameCount'] == 3
    assert paths[0] != paths[1]
    assert all(not path.exists() for path in paths)


@pytest.mark.parametrize('returncode,frame_count', [(1, 3), (0, 2), (0, 0)])
def test_vmaf_rejects_failed_execution_or_partial_distribution(returncode, frame_count):
    import json
    report = {'frames': [{'metrics': {'vmaf': 95}}] * frame_count, 'pooled_metrics': {'vmaf': {'mean': 95}}}
    with mock.patch.object(ffmpeg, '_vmaf_filter_candidates', return_value=[{'filter': "libvmaf=model='path=model.json':log_fmt=json:log_path=-", 'metricModelId': 'test'}]), \
         mock.patch.object(ffmpeg, 'probe_video_stream_metrics', return_value={'sourceFps': 24, 'sourceFrameCount': 3}), \
         mock.patch.object(ffmpeg.subprocess, 'run', return_value=mock.Mock(returncode=returncode, stdout=json.dumps(report))):
        assert ffmpeg.compute_vmaf_metrics('reference.mkv', 'encoded.mp4') == {}
