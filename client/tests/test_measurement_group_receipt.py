"""Synthetic encoder fixtures exercise real campaign completion and payload journals."""
import json
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import pytest

from client import main, protocol
from client.artifacts import build_payload_hash


@pytest.fixture
def campaign_driver(tmp_path):
    from test_main_routing import MainRoutingTests, _DummyDashboard
    fixture = MainRoutingTests()
    clip = fixture._quick_clip()
    args = fixture._batch_args(str(tmp_path))
    args.local_metrics = False
    args.campaign_seed = 123
    hardware = main.HardwareInfo('CPU', None, 16, 'TestOS')
    tasks = [{'encoder': 'libx264', 'preset': 'fast', 'crf': 24, 'suiteClip': clip}]
    durations = iter([1_000_000_000] * 5)
    results = []
    encodes = []
    emitted = []
    original_execute = protocol.execute_protocol_campaign

    def encode(**kwargs):
        elapsed_ns = next(durations)
        if isinstance(elapsed_ns, BaseException):
            raise elapsed_ns
        target = Path(kwargs['out_dir']) / kwargs['artifact_name']
        target.write_bytes(b'SYNTHETIC TEST ARTIFACT')
        encodes.append(str(target))
        return {'artifactPath': str(target), 'encoderUsed': 'libx264', 'presetUsed': 'fast',
                'fileSizeBytes': target.stat().st_size, 'elapsedMs': elapsed_ns / 1e6,
                'encodeStartMonotonicNs': 1_000_000_000,
                'encodeEndMonotonicNs': 1_000_000_000 + elapsed_ns,
                'frameCount': 120, 'error': None}

    def execute(**kwargs):
        result = original_execute(**kwargs)
        results.append(result)
        return result

    def run(values=None, environment=None):
        nonlocal durations
        if values is not None:
            durations = iter(values)
        with ExitStack() as stack:
            patches = {
                'ensure_ffmpeg_and_ffprobe': (True, 'FAKE_TEST_FFMPEG'),
                '_build_protocol_config': protocol.ProtocolConfig.for_version('7.1'),
                'probe_video_stream_metrics': {'sourceFps': 24.0, 'sourceDurationSeconds': 5.0, 'containerFormat': 'mp4'},
                '_probe_artifact_contract': fixture._artifact_contract(),
                'build_execution_identity_payload': {'environmentJson': json.dumps({
                    'cpuArchitecture': 'x86_64', 'osName': 'testos', 'osVersion': '1',
                    'ffmpegBuildFingerprint': 'FAKE_TEST_BUILD', 'ffmpegVersion': 'FAKE_TEST_FFMPEG',
                    'clientVersion': 'client/0.3.0'})},
                'should_skip_submission': (False, ''),
                'physical_source_id': 'installation-' + '1' * 64,
                'selected_device': {'selection': 'software', 'deviceId': 'cpu'},
            }
            for name, result in patches.items():
                stack.enter_context(mock.patch.object(main, name, return_value=result))
            stack.enter_context(mock.patch('client.identity.runtime_identity', return_value={'fixture': 'SYNTHETIC'}))
            stack.enter_context(mock.patch.object(main, '_capture_protocol_environment_snapshot',
                                side_effect=environment or (lambda **kw: protocol.EnvironmentSnapshot(selected_accelerator='software'))))
            stack.enter_context(mock.patch.object(main, 'BatchRunDashboard', _DummyDashboard))
            stack.enter_context(mock.patch.object(main, 'encode_to_artifact', side_effect=encode))
            stack.enter_context(mock.patch.object(main, 'execute_protocol_campaign', side_effect=execute))
            stack.enter_context(mock.patch.object(main, 'compute_metrics_parallel', side_effect=AssertionError('No local metrics')))
            return main.run_benchmark_batch(hardware=hardware, base_url='https://example.invalid',
                                            args=args, tasks=tasks, event_sink=emitted.append)

    return run, results, encodes, emitted


@pytest.mark.parametrize('durations,expected_count,stable', [
    ([1_000_000_000, 1_123_456_789, 1_124_567_891], 2, True),
    ([1_000_000_000, 1_123_456_789, 2_123_456_789, 1_123_456_789, 2_123_456_789], 4, False),
])
def test_completed_campaign_receipt_matches_every_prepared_submission(campaign_driver, tmp_path, durations, expected_count, stable):
    run, results, encodes, _ = campaign_driver
    assert run(durations) == 0
    result = results[-1]
    recipe = result.recipe_results[0]
    assert recipe.stability.stable is stable
    expected = [{'repetitionIndex': r.schedule.repetition_index, 'encodeWallTimeMs': r.timing.elapsed_s * 1000.0}
                for r in recipe.runs if r.schedule.phase == 'measured' and r.counted_for_stability]
    assert len(expected) == expected_count
    payloads = [json.loads(p.read_text())['runCreate'] for p in sorted(tmp_path.glob('campaigns/*/submission-*.json'))]
    assert len(payloads) == expected_count  # Unstable individual evidence is retained too.
    groups = [p['measurementGroup'] for p in payloads]
    assert all(g == groups[0] for g in groups)
    assert groups[0] == {'schemaVersion': 'encodingdb-measurement-group/v1',
                         'campaignId': result.campaign_id,
                         'repetitionGroupId': f'{result.campaign_id}:{recipe.recipe_id}',
                         'completed': True, 'countedAttempts': expected}
    for payload in payloads:
        assert payload['payloadHash'] == build_payload_hash(payload)
        own = next(a for a in expected if a['repetitionIndex'] == payload['repetitionIndex'])
        assert own['encodeWallTimeMs'] == payload['encodeWallTimeMs']
    assert len(encodes) == expected_count + 1  # Warmup is absent from the receipt.


def test_resume_keeps_old_and_new_prepared_submission_bytes(campaign_driver, tmp_path):
    run, results, encodes, _ = campaign_driver
    assert run([1_000_000_000, 1_123_456_789, 1_124_567_891]) == 0
    paths = sorted(tmp_path.glob('campaigns/*/submission-*.json'))
    # Emulate an existing old-format prepared receipt. Upgrading the client must
    # not change this immutable payload or silently manufacture group eligibility.
    old = json.loads(paths[0].read_text())
    old['runCreate'].pop('measurementGroup')
    old['runCreate']['payloadHash'] = build_payload_hash(old['runCreate'])
    paths[0].write_text(json.dumps(old, indent=3) + '\n')
    before = {p: p.read_bytes() for p in paths}
    encode_count = len(encodes)
    assert run([]) == 0  # Exhausted fake encoder proves no new encoding on resume.
    assert len(encodes) == encode_count
    assert len(results) == 2
    assert {p: p.read_bytes() for p in paths} == before
    assert 'measurementGroup' not in json.loads(paths[0].read_text())['runCreate']


def test_receipt_excludes_invalid_attempts_and_omits_insufficient_group():
    recipe = protocol.RecipeSpec('recipe', protocol.StructuralExpectation(frame_count=24))
    def encode(schedule, _recipe):
        return protocol.EncodeOutcome(
            protocol.EncodeTiming.from_measurement(start_monotonic_ns=1, end_monotonic_ns=1_000_000_001,
                source_frame_count=24, encoded_frame_count=24, source_fps=24),
            protocol.ArtifactProbe(decodable=True, frame_count=24, size_bytes=4))
    def environment(schedule, _recipe):
        return protocol.EnvironmentSnapshot(selected_accelerator='software',
            background_cpu_pct=99 if schedule.phase == 'measured' and schedule.repetition_index == 1 else 0)
    complete = protocol.execute_protocol_campaign(recipes=[recipe], config=protocol.ProtocolConfig.for_version('7.1'),
        encode_runner=encode, environment_sampler=environment, seed=7)
    receipt = main._completed_measurement_groups(complete)['recipe']
    assert [a['repetitionIndex'] for a in receipt['countedAttempts']] == [2, 3]
    insufficient = protocol.execute_protocol_campaign(recipes=[recipe],
        config=protocol.ProtocolConfig.for_version('7.1', max_adaptive_repeats=0),
        encode_runner=encode, environment_sampler=environment, seed=7)
    assert insufficient.recipe_results[0].measured_runs_counted == 1
    assert main._completed_measurement_groups(insufficient) == {}


def test_interrupted_campaign_prepares_no_receipts_until_resume_completion(campaign_driver, tmp_path):
    run, results, encodes, _ = campaign_driver
    assert run([1_000_000_000, 1_123_456_789, KeyboardInterrupt()]) == 130
    assert results == []
    assert list(tmp_path.glob('campaigns/*/submission-*.json')) == []
    assert len(encodes) == 2
    assert run([1_124_567_891]) == 0
    assert len(encodes) == 3
    payloads = [json.loads(p.read_text())['runCreate'] for p in sorted(tmp_path.glob('campaigns/*/submission-*.json'))]
    assert len(payloads) == 2
    assert payloads[0]['measurementGroup'] == payloads[1]['measurementGroup']
    assert payloads[0]['measurementGroup']['countedAttempts'] == [
        {'repetitionIndex': 1, 'encodeWallTimeMs': 1.123456789 * 1000.0},
        {'repetitionIndex': 2, 'encodeWallTimeMs': 1.124567891 * 1000.0},
    ]
