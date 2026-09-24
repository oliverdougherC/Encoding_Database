"""Publication capacity never consumes additional media bytes before admission."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from client import main, spool
from client.campaign import atomic_json

MIB = 1024 * 1024


def test_saved_publish_never_reports_success_with_unadmitted_envelopes(tmp_path):
    campaign_id = 'campaign-0123456789abcdef'
    root = tmp_path / 'campaigns' / campaign_id
    root.mkdir(parents=True)
    atomic_json(root / 'submission-000001.json', {'saved': 'immutable'})
    with mock.patch.object(main, 'drain_committed_receipts', return_value=0), \
         mock.patch.object(main, 'spool_payload', side_effect=spool.SpoolCapacityError('volume full')), \
         mock.patch.object(main, 'replay_spool', return_value=spool.ReplayStats()):
        rc, info = main.publish_saved_campaign(
            queue_dir=str(tmp_path), campaign_id=campaign_id,
            base_url='http://127.0.0.1:9', api_key='', max_storage_mb=2048,
        )
    assert rc == 10
    assert info['status'] == 'deferred'
    assert info['unadmitted'] == 1
    assert info['pending'] == 0


def payload_at(path, size=400 * 1024):
    from test_spool import SpoolTests
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'X' * size)
    return SpoolTests()._authoritative_payload(str(path))


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('retained_folder', ['receipts', 'terminal', 'dead-letter', 'artifacts'])
def test_aggregate_counts_all_retained_data_before_copy(tmp_path, retained_folder):
    queue = tmp_path / 'queue'
    prior = queue / retained_folder / 'retained.dat'
    prior.parent.mkdir(parents=True)
    prior.write_bytes(b'R' * (700 * 1024))
    payload = payload_at(tmp_path / 'source.mp4')
    # Create the durable lock before observing exact no-write refusal.
    with spool._spool_write_lock(str(queue)):
        pass
    before = snapshot(queue)
    with pytest.raises(spool.SpoolCapacityError, match='storage budget'):
        spool.spool_payload(str(queue), payload, max_storage_mb=1)
    assert snapshot(queue) == before
    assert Path(payload['artifactPath']).read_bytes() == b'X' * (400 * 1024)
    path, entry = spool.spool_payload(str(queue), payload, max_storage_mb=2)
    assert Path(path).is_file()
    assert Path(entry['payload']['artifactPath']).read_bytes() == b'X' * (400 * 1024)
    assert sum(p.stat().st_size for p in queue.rglob('*') if p.is_file()) < 2 * MIB


def test_actual_filesystem_free_space_is_checked_before_copy(tmp_path):
    queue = tmp_path / 'queue'
    payload = payload_at(tmp_path / 'source.mp4')
    with mock.patch.object(spool.shutil, 'disk_usage', return_value=SimpleNamespace(free=400 * 1024)) as disk:
        with pytest.raises(spool.SpoolCapacityError, match='free disk'):
            spool.spool_payload(str(queue), payload, max_storage_mb=2)
    disk.assert_called_once_with(str(queue))
    assert not (queue / 'artifacts').exists()
    assert not list(queue.glob('*.json'))
    path, _ = spool.spool_payload(str(queue), payload, max_storage_mb=2)
    assert Path(path).is_file()


def test_pending_receipted_and_terminal_payloads_ignore_new_capacity_without_reset(tmp_path):
    queue = tmp_path / 'queue'
    payload = payload_at(tmp_path / 'source.mp4', 5)
    path, entry = spool.spool_payload(str(queue), payload)
    entry.update(retryDeadlineAt=123456, nextAttemptAt=12345, attempts=7)
    atomic_json(Path(path), entry)
    with mock.patch.object(spool, '_check_spool_capacity', side_effect=AssertionError('must reuse identity')):
        assert spool.spool_payload(str(queue), payload, max_storage_mb=0) == (path, entry)
        spool.move_to_dead_letter(str(queue), path, entry, 'expired')
        terminal_path, terminal = spool.spool_payload(str(queue), payload, max_storage_mb=0)
        assert terminal['retryDeadlineAt'] == 123456
        assert terminal['attempts'] == 7
        assert Path(terminal_path).parent.name == 'terminal'
        receipt_payload = dict(payload, runCreate={'payloadHash': 'other-receipt'})
        receipt = queue / 'receipts' / (spool.local_hash_for_payload(receipt_payload) + '.json')
        atomic_json(receipt, {'benchmarkRunId': 'already-submitted'})
        original = receipt.read_bytes()
        assert spool.spool_payload(str(queue), receipt_payload, max_storage_mb=0)[0] == str(receipt)
        assert receipt.read_bytes() == original


def test_shared_managed_artifact_is_not_charged_or_copied_twice(tmp_path):
    queue = tmp_path / 'queue'
    payload = payload_at(tmp_path / 'source.mp4', 600 * 1024)
    _, first = spool.spool_payload(str(queue), payload, max_storage_mb=1)
    second = dict(payload, runCreate={'payloadHash': 'another-measurement'})
    _, second_entry = spool.spool_payload(str(queue), second, max_storage_mb=1)
    assert first['payload']['artifactPath'] == second_entry['payload']['artifactPath']
    assert len(list((queue / 'artifacts').iterdir())) == 1


def test_ordinary_submission_passes_budget_and_can_resume_without_copy_on_refusal(tmp_path):
    queue = tmp_path / 'queue'
    payload = payload_at(queue / 'campaigns' / 'retained.mp4', 600 * 1024)
    arguments = dict(queue_dir=str(queue), base_url='unused', payload=payload,
                     api_key='', retries=0, use_token=False)
    with mock.patch.object(main, 'submit_spooled_path', return_value=('retained', 'later')) as send:
        with pytest.raises(spool.SpoolCapacityError):
            main._submit_payload_with_spool(**arguments, max_storage_mb=1)
        send.assert_not_called()
        assert not (queue / 'artifacts').exists()
        assert main._submit_payload_with_spool(**arguments, max_storage_mb=2)[0] == 'retained'
    assert Path(payload['artifactPath']).stat().st_size == 600 * 1024


def test_upload_only_capacity_pause_preserves_pending_deadline_and_resumes_without_encoding(tmp_path):
    queue = tmp_path / 'queue'
    campaign_id = 'campaign-0123456789abcdef'
    root = queue / 'campaigns' / campaign_id
    payload = payload_at(root / 'retained.mp4', 600 * 1024)
    atomic_json(root / 'campaign-complete.json', {'failed': 0, 'skipped': 0})
    atomic_json(root / 'submission-000001.json', payload)
    # Prior queued work remains due later and cannot acquire a new deadline.
    prior, entry = spool.spool_payload(str(queue), {'cpuModel': 'fixture', 'fps': 1})
    entry.update(nextAttemptAt=9999999999, retryDeadlineAt=10000000000, attempts=3)
    atomic_json(Path(prior), entry)
    before = snapshot(root)
    argv = ['prog', '--upload-only', '--resume-campaign', campaign_id, '--queue-dir', str(queue)]
    with mock.patch.object(main, 'check_compatibility'), \
         mock.patch.object(main, 'run_benchmark_batch') as encode, \
         mock.patch.object(spool, 'submit_artifact_submission', return_value='test-run') as send:
        assert main.main(argv + ['--max-storage-mb', '1']) == 10
        send.assert_not_called()
        assert not (queue / 'artifacts').exists()
        assert not (queue / 'terminal').exists()
        assert spool.load_spool_entry(prior) == entry
        assert main.main(argv + ['--max-storage-mb', '2']) == 10  # the original future retry is still pending
        send.assert_called_once()
        encode.assert_not_called()
    assert snapshot(root) == before
    assert spool.load_spool_entry(prior) == entry
    assert len(list((queue / 'receipts').glob('*.json'))) == 1


def test_queue_admission_is_fenced_against_another_publisher(tmp_path):
    queue = tmp_path / 'queue'
    payload = payload_at(tmp_path / 'source.mp4', 5)
    with spool._spool_write_lock(str(queue)):
        with pytest.raises(spool.SpoolCapacityError, match='Another publisher'):
            spool.spool_payload(str(queue), payload, max_storage_mb=1)
    assert not (queue / 'artifacts').exists()
    spool.spool_payload(str(queue), payload, max_storage_mb=1)


def test_disk_full_during_copy_removes_partial_bytes_and_remains_recoverable(tmp_path):
    import builtins
    import errno
    queue = tmp_path / 'queue'
    payload = payload_at(tmp_path / 'source.mp4', 5)
    original_open = builtins.open
    def full_target(path, mode='r', *args, **kwargs):
        if mode == 'xb':
            raise OSError(errno.ENOSPC, 'synthetic disk-full boundary')
        return original_open(path, mode, *args, **kwargs)
    with mock.patch.object(spool, 'open', side_effect=full_target):
        with pytest.raises(spool.SpoolCapacityError, match='ran out of disk space'):
            spool.spool_payload(str(queue), payload, max_storage_mb=1)
    assert not list((queue / 'artifacts').iterdir())
    assert not list(queue.glob('*.json'))
    spool.spool_payload(str(queue), payload, max_storage_mb=1)


def test_canonical_publication_capacity_pause_keeps_completed_attempts_for_resume(tmp_path):
    from client import protocol
    from test_main_routing import MainRoutingTests, _DummyDashboard
    fixture = MainRoutingTests()
    args = fixture._batch_args(str(tmp_path))
    args.no_submit = False
    args.submit = True
    args.local_metrics = False
    clip = fixture._quick_clip()
    artifact = tmp_path / 'out.mp4'
    artifact.write_bytes(b'test')
    info = {'artifactPath': str(artifact), 'encoderUsed': 'libx264', 'presetUsed': 'fast',
            'fileSizeBytes': 4, 'encodeStartMonotonicNs': 1_000_000_000, 'encodeEndMonotonicNs': 2_000_000_000,
            'elapsedMs': 1000, 'error': None}
    def retained_encode(**kwargs):
        owned = Path(kwargs['out_dir']) / kwargs['artifact_name']
        owned.write_bytes(b'test')
        return dict(info, artifactPath=str(owned))
    with mock.patch.object(main, 'check_compatibility'), \
         mock.patch.object(main, 'ensure_ffmpeg_and_ffprobe', return_value=(True, 'ffmpeg 9')), \
         mock.patch.object(main, '_probe_artifact_contract', return_value=fixture._artifact_contract()), \
         mock.patch.object(main, 'probe_video_stream_metrics', return_value={'sourceFps': 24, 'sourceDurationSeconds': 5}), \
         mock.patch.object(main, 'encode_to_artifact', side_effect=retained_encode) as encode, \
         mock.patch.object(main, '_capture_protocol_environment_snapshot', return_value=protocol.EnvironmentSnapshot(selected_accelerator='software')), \
         mock.patch.object(main, 'BatchRunDashboard', _DummyDashboard), \
         mock.patch.object(main, 'sha256_of_file', return_value='a' * 64), \
         mock.patch.object(main, '_build_authoritative_run_create_request', return_value={'artifact': {'sha256': 'a' * 64, 'byteSize': 4}}), \
         mock.patch.object(main, '_replay_pending_uploads', return_value=0), \
         mock.patch.object(main, '_submit_payload_with_spool', side_effect=spool.SpoolCapacityError('synthetic capacity boundary')) as submit:
        arguments = dict(hardware=main.HardwareInfo('CPU', None, 16, 'OS'), base_url='http://invalid', args=args,
                         tasks=[{'encoder': 'libx264', 'preset': 'fast', 'crf': 24, 'suiteClip': clip}])
        assert main.run_benchmark_batch(**arguments) == 6
        root = next((tmp_path / 'campaigns').glob('campaign-*'))
        attempts = {p.name: p.read_bytes() for p in root.glob('attempt-*.json')}
        assert len(attempts) == 3
        assert not (root / 'campaign-complete.json').exists()
        args.resume_campaign = root.name
        prior_calls = encode.call_count
        submit.side_effect = None
        submit.return_value = ('submitted', 'fixture-run', 0)
        with mock.patch.object(main, '_prepare_named_suite_clip', return_value=clip), \
             mock.patch.object(main, 'detect_hardware', return_value=arguments['hardware']):
            assert main._resume_campaign(args) == 0
        assert encode.call_count == prior_calls
        assert {p.name: p.read_bytes() for p in root.glob('attempt-*.json')} == attempts
        assert json.loads((root / 'campaign-complete.json').read_text())['failed'] == 0


@pytest.mark.parametrize('mutation', ['cleanup', 'replay', 'dead_letter'])
def test_shared_artifact_cannot_be_removed_between_admission_and_entry_commit(tmp_path, mutation):
    import threading
    queue = str(tmp_path / 'queue')
    payload = payload_at(tmp_path / 'source.mp4', 5)
    first_path, first_entry = spool.spool_payload(queue, payload)
    second = dict(payload, runCreate={'payloadHash': 'second-shared-measurement'})
    staged, release = threading.Event(), threading.Event()
    admitted, failures = [], []
    preserve = spool._preserve_artifact_for_spool
    def pause_after_preserve(*args, **kwargs):
        value = preserve(*args, **kwargs)
        staged.set()
        if not release.wait(5):
            raise AssertionError('test admission was not released')
        return value
    def admission():
        try:
            admitted.append(spool.spool_payload(queue, second))
        except BaseException as exc:
            failures.append(exc)
    thread = threading.Thread(target=admission)
    with mock.patch.object(spool, '_preserve_artifact_for_spool', side_effect=pause_after_preserve), \
         mock.patch.object(spool, 'submit_artifact_submission', return_value={}) as send:
        thread.start()
        try:
            assert staged.wait(5)
            if mutation == 'cleanup':
                with pytest.raises(spool.SpoolCapacityError):
                    spool.cleanup_spool(queue)
            elif mutation == 'dead_letter':
                with pytest.raises(spool.SpoolCapacityError):
                    spool.move_to_dead_letter(queue, first_path, first_entry, 'fixture-rejection')
            else:
                assert spool.submit_spooled_path(first_path, queue_dir=queue, base_url='unused',
                    api_key='', retries=0, use_token=False)[0] == 'retained'
                send.assert_not_called()
            assert Path(first_entry['payload']['artifactPath']).read_bytes() == b'X' * 5
        finally:
            release.set()
            thread.join(5)
    assert not thread.is_alive()
    assert not failures
    new_path, new_entry = admitted[0]
    if mutation == 'cleanup':
        spool.cleanup_spool(queue)
    elif mutation == 'dead_letter':
        spool.move_to_dead_letter(queue, first_path, first_entry, 'fixture-rejection')
    else:
        with mock.patch.object(spool, 'submit_artifact_submission', return_value={}):
            assert spool.submit_spooled_path(first_path, queue_dir=queue, base_url='unused',
                api_key='', retries=0, use_token=False)[0] == 'submitted'
    assert Path(new_path).is_file()
    assert Path(new_entry['payload']['artifactPath']).read_bytes() == b'X' * 5
    spool._validate_managed_artifact_for_replay(queue, new_entry['payload'])


def test_cleanup_cannot_delete_new_staged_artifact_before_its_queue_entry(tmp_path):
    queue = str(tmp_path / 'queue')
    payload = payload_at(tmp_path / 'source.mp4', 5)
    preserve = spool._preserve_artifact_for_spool
    def concurrent_cleanup(*args, **kwargs):
        value = preserve(*args, **kwargs)
        # Separate OS lock acquisition fails even in the same calling thread.
        with pytest.raises(spool.SpoolCapacityError):
            spool.cleanup_spool(queue)
        return value
    with mock.patch.object(spool, '_preserve_artifact_for_spool', side_effect=concurrent_cleanup):
        path, entry = spool.spool_payload(queue, payload)
    assert Path(path).is_file()
    assert Path(entry['payload']['artifactPath']).read_bytes() == b'X' * 5


def test_replay_finishing_during_admission_defers_commit_without_deleting_shared_media(tmp_path):
    import threading
    queue = str(tmp_path / 'queue')
    payload = payload_at(tmp_path / 'source.mp4', 5)
    first_path, first = spool.spool_payload(queue, payload)
    second = dict(payload, runCreate={'payloadHash': 'second'})
    sending, finish = threading.Event(), threading.Event()
    results = []
    def network(*args, **kwargs):
        sending.set()
        if not finish.wait(5):
            raise AssertionError('test network was not released')
        return {'benchmarkRun': {'id': 'first'}}
    def replay():
        results.append(spool.submit_spooled_path(first_path, queue_dir=queue, base_url='unused',
                       api_key='', retries=0, use_token=False))
    preserve = spool._preserve_artifact_for_spool
    def pause_for_network_finish(*args, **kwargs):
        value = preserve(*args, **kwargs)
        finish.set()
        thread.join(5)
        assert not thread.is_alive()
        assert results[0][0] == 'retained'
        assert Path(first['payload']['artifactPath']).read_bytes() == b'X' * 5
        return value
    thread = threading.Thread(target=replay)
    with mock.patch.object(spool, 'submit_artifact_submission', side_effect=network):
        thread.start()
        try:
            assert sending.wait(5)
            with mock.patch.object(spool, '_preserve_artifact_for_spool', side_effect=pause_for_network_finish):
                second_path, second_entry = spool.spool_payload(queue, second)
        finally:
            finish.set()
            thread.join(5)
    assert spool.load_spool_entry(first_path)['retryDeadlineAt'] == first['retryDeadlineAt']
    with mock.patch.object(spool, 'submit_artifact_submission', return_value={}):
        assert spool.submit_spooled_path(first_path, queue_dir=queue, base_url='unused',
            api_key='', retries=0, use_token=False)[0] == 'submitted'
    assert Path(second_path).is_file()
    assert Path(second_entry['payload']['artifactPath']).read_bytes() == b'X' * 5


@pytest.mark.parametrize('verdict', ['receipt', 'terminal'])
def test_stale_network_response_cannot_replace_committed_publication_verdict(tmp_path, verdict):
    from client.network import SubmitError
    queue = str(tmp_path / 'queue')
    payload = payload_at(tmp_path / 'source.mp4', 5)
    path, entry = spool.spool_payload(queue, payload)
    calls = []
    def network(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            if verdict == 'terminal':
                spool.move_to_dead_letter(queue, path, entry, 'fixture-terminal')
            else:
                assert spool.submit_spooled_path(path, queue_dir=queue, base_url='unused',
                    api_key='', retries=0, use_token=False)[0] == 'submitted'
            raise SubmitError('stale failure', retryable=True)
        return {'benchmarkRun': {'id': 'fixture-receipt'}}
    with mock.patch.object(spool, 'submit_artifact_submission', side_effect=network):
        status, _ = spool.submit_spooled_path(path, queue_dir=queue, base_url='unused',
            api_key='', retries=0, use_token=False)
    assert status == ('submitted' if verdict == 'receipt' else 'dead_lettered')
    assert not Path(path).exists()
    if verdict == 'receipt':
        assert not (Path(queue) / 'terminal').exists()
    else:
        assert not (Path(queue) / 'receipts').exists()
        assert spool.terminal_spool_entry(queue, entry['localHash'])[1]['retryDeadlineAt'] == entry['retryDeadlineAt']


def test_replay_recovers_receipt_committed_before_pending_cleanup(tmp_path):
    queue = str(tmp_path / 'queue')
    payload = payload_at(tmp_path / 'source.mp4', 5)
    path, entry = spool.spool_payload(queue, payload)
    receipt = Path(queue) / 'receipts' / Path(path).name
    atomic_json(receipt, {'response': {'benchmarkRun': {'id': 'committed-before-crash'}}})
    with mock.patch.object(spool, 'submit_artifact_submission') as send:
        assert spool.submit_spooled_path(path, queue_dir=queue, base_url='unused',
            api_key='', retries=0, use_token=False) == ('submitted', 'committed-before-crash')
    send.assert_not_called()
    assert not Path(path).exists()
    assert not Path(entry['payload']['artifactPath']).exists()
    assert receipt.exists()


def test_stale_retry_failure_cannot_shorten_concurrent_server_backoff(tmp_path):
    from client.network import SubmitError
    queue = str(tmp_path / 'queue')
    payload = payload_at(tmp_path / 'source.mp4', 5)
    path, entry = spool.spool_payload(queue, payload)
    calls = []
    server_deadline = []
    def network(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            assert spool.submit_spooled_path(path, queue_dir=queue, base_url='unused',
                api_key='', retries=0, use_token=False)[0] == 'retained'
            server_deadline.append(spool.load_spool_entry(path)['nextAttemptAt'])
            raise SubmitError('older generic failure', retryable=True)
        raise SubmitError('server requires backoff', retryable=True, retry_after=1000)
    with mock.patch.object(spool, 'submit_artifact_submission', side_effect=network):
        assert spool.submit_spooled_path(path, queue_dir=queue, base_url='unused',
            api_key='', retries=0, use_token=False)[0] == 'retained'
    retained = spool.load_spool_entry(path)
    assert retained['nextAttemptAt'] >= server_deadline[0]
    assert retained['attempts'] == 2
    assert retained['retryDeadlineAt'] == entry['retryDeadlineAt']
