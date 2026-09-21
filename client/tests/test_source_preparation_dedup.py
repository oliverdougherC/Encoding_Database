"""Native tiny-media regression fixtures; no retained calibration measurements."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import threading
from unittest import mock

import pytest

from client import campaign, main, suite


@contextmanager
def materialization_fixture(tmp_path):
    from test_suite_v1 import small_media_fixture
    with small_media_fixture() as (root, manifest):
        with mock.patch.object(suite, '_manifest_resource_candidates', return_value=[]), \
             mock.patch.object(suite, '_ensure_suite_pack_available', return_value='fixture-pack'), \
             mock.patch.object(suite, '_extract_suite_pack', return_value=str(root / 'canonical')), \
             mock.patch.object(suite, 'load_suite_pack_metadata', return_value={}):
            yield manifest.clips[0], str(tmp_path / 'cache')


def damage_same_length(path):
    path = Path(path)
    data = path.read_bytes()
    path.write_bytes(bytes([data[0] ^ 255]) + data[1:])


def test_materialization_rejects_bytes_changed_after_validated_atomic_rename(tmp_path):
    with materialization_fixture(tmp_path) as (clip, cache):
        rename = suite.os.replace
        def corrupt_after_rename(source, target):
            rename(source, target)
            damage_same_length(target)
        with mock.patch.object(suite.os, 'replace', side_effect=corrupt_after_rename):
            with pytest.raises(RuntimeError, match='checksum mismatch'):
                suite.ensure_suite_clip(clip, cache_root=cache)


def test_materialization_rejects_changed_copy_and_changed_contract(tmp_path):
    with materialization_fixture(tmp_path) as (clip, cache):
        copy = suite._copy_preparation_file
        def corrupt_copy(source, target):
            copy(source, target)
            damage_same_length(target)
        with mock.patch.object(suite, '_copy_preparation_file', side_effect=corrupt_copy):
            with pytest.raises(RuntimeError, match='checksum mismatch'):
                suite.ensure_suite_clip(clip, cache_root=cache)
        changed = replace(clip, media=replace(clip.media, frame_count=clip.media.frame_count + 1))
        with pytest.raises(RuntimeError, match='frameCount mismatch'):
            suite.ensure_suite_clip(changed, cache_root=cache)


def test_cancellation_after_rename_still_stops_final_validation(tmp_path):
    with materialization_fixture(tmp_path) as (clip, cache):
        stop = threading.Event()
        rename = suite.os.replace
        def cancel_after_rename(source, target):
            rename(source, target)
            stop.set()
        with campaign.PreparationScope(stop).activate(), \
             mock.patch.object(suite.os, 'replace', side_effect=cancel_after_rename):
            with pytest.raises(KeyboardInterrupt):
                suite.ensure_suite_clip(clip, cache_root=cache)


def test_materialization_has_bounded_media_probes(tmp_path):
    with materialization_fixture(tmp_path) as (clip, cache):
        with mock.patch.object(suite, '_probe_clip', wraps=suite._probe_clip) as probe, \
             mock.patch.object(suite, '_sha256_of_file', wraps=suite._sha256_of_file) as hashes:
            prepared = suite.ensure_suite_clip(clip, cache_root=cache)
        assert probe.call_count == 1  # One complete media validation; final bytes are rehashed.
        assert str(prepared.path) in [call.args[0] for call in hashes.call_args_list]
        assert any(str(call.args[0]).endswith('.staging') for call in hashes.call_args_list)


def test_recipe_source_contract_has_bounded_metrics_probes():
    from test_suite_v1 import small_media_fixture
    with small_media_fixture() as (_, manifest):
        prepared = suite.ensure_suite_clip(manifest.clips[0])
        with mock.patch.object(main, 'probe_video_stream_metrics', wraps=main.probe_video_stream_metrics) as metrics, \
             mock.patch.object(main, 'validate_artifact_decodability', wraps=main.validate_artifact_decodability) as decode:
            recipes = main._build_protocol_recipe_specs(
                [{'encoder': 'libx264', 'preset': 'fast', 'crf': 24, 'suiteClip': prepared}],
                default_input_path=prepared.path, default_input_hash=prepared.input_hash)
        assert metrics.call_count == 1  # Reuse the metrics read by the full contract helper.
        decode.assert_called_once_with(prepared.path)
        assert recipes[0].expectation.frame_count == 2
        assert recipes[0].expectation.avg_frame_rate == 24
        assert recipes[0].expectation.width == 32


def test_packaged_validation_is_repeated_on_new_call_and_rejects_changed_contract():
    from test_suite_v1 import small_media_fixture
    with small_media_fixture() as (_, manifest):
        clip = manifest.clips[0]
        with mock.patch.object(suite, '_probe_clip', wraps=suite._probe_clip) as probe:
            suite.ensure_suite_clip(clip)
            suite.ensure_suite_clip(clip)
        assert probe.call_count == 2  # One full check per invocation, no persistent validation cache.
        changed = replace(clip, media=replace(clip.media, frame_count=3))
        with pytest.raises(RuntimeError, match='frameCount mismatch'):
            suite.ensure_suite_clip(changed)


def test_packaged_final_hash_rejects_bytes_changed_after_media_validation():
    from test_suite_v1 import small_media_fixture
    with small_media_fixture() as (_, manifest):
        native_probe = suite._probe_clip
        def corrupt_after_probe(path):
            result = native_probe(path)
            damage_same_length(path)
            return result
        with mock.patch.object(suite, '_probe_clip', side_effect=corrupt_after_probe):
            with pytest.raises(RuntimeError, match='checksum mismatch'):
                suite.ensure_suite_clip(manifest.clips[0])


def test_source_contract_preserves_existing_metrics_fallback_without_extra_probe():
    import json
    import subprocess
    from client.suite import PreparedSuiteClip
    prepared = PreparedSuiteClip(suite_version=suite.SUITE_VERSION, clip_id='fixture',
        canonical_content_class='animation', payload_content_class='animation', workload_id='fixture',
        path='fixture.mkv', input_hash='a' * 64, file_name='fixture.mkv')
    native = {'streams': [{'codec_type': 'video', 'codec_name': 'ffv1', 'width': 32, 'height': 32,
                          'pix_fmt': 'yuv420p', 'nb_read_frames': '2'}], 'format': {'format_name': 'matroska', 'size': '99'}}
    with mock.patch.object(main, 'run_measurement_process', side_effect=[
        subprocess.CompletedProcess([], 0, json.dumps(native)), subprocess.CompletedProcess([], 0, '1\n0\n')]), \
         mock.patch.object(main, 'validate_artifact_decodability', return_value=(True, None)) as decode, \
         mock.patch.object(main, 'probe_video_stream_metrics', return_value={
             'sourceFps': 24.0, 'sourceDurationSeconds': 1 / 12}) as metrics:
        recipe = main._build_protocol_recipe_specs(
            [{'encoder': 'libx264', 'preset': 'fast', 'crf': 24, 'suiteClip': prepared}],
            default_input_path=prepared.path, default_input_hash=prepared.input_hash)[0]
    metrics.assert_called_once_with(prepared.path)
    decode.assert_called_once_with(prepared.path)
    assert recipe.expectation.duration_s == 1 / 12
    assert recipe.expectation.avg_frame_rate == 24
    assert recipe.expectation.frame_count == 2
