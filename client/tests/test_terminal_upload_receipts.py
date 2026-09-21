"""Terminal publication identities survive resume, crashes and explicit cleanup."""
import json
from pathlib import Path
from unittest import mock

import pytest

from client import main, spool
from client.campaign import atomic_json
from client.network import SubmitError


def make_entry(tmp_path):
    from test_spool import SpoolTests
    artifact = tmp_path/'retained.mp4'
    artifact.write_bytes(b'SYNTHETIC TEST ARTIFACT')
    payload = SpoolTests()._authoritative_payload(str(artifact))
    queue = str(tmp_path/'queue')
    path, entry = spool.spool_payload(queue, payload)
    return queue, path, entry, payload


@pytest.mark.parametrize('reason', ['rejected', 'expired'])
def test_terminal_identity_prevents_new_deadline_after_resume_and_cleanup(tmp_path, reason):
    queue, path, entry, payload = make_entry(tmp_path)
    original_deadline = entry['retryDeadlineAt']
    if reason == 'expired':
        entry['retryDeadlineAt'] = 1
        original_deadline = 1
        atomic_json(Path(path), entry)
    with mock.patch.object(spool, 'submit_artifact_submission', side_effect=SubmitError('rejected', retryable=False)) as send:
        assert spool.submit_spooled_path(path, queue_dir=queue, base_url='unused', api_key='', retries=0, use_token=False)[0] == 'dead_lettered'
        sent = send.call_count
        for cleanup in (False, True):
            if cleanup:
                spool.cleanup_spool(queue)
            terminal_path, terminal = spool.spool_payload(queue, payload)
            assert terminal['terminal'] is True
            assert terminal['retryDeadlineAt'] == original_deadline
            assert spool.submit_spooled_path(terminal_path, queue_dir=queue, base_url='unused', api_key='', retries=0, use_token=False)[0] == 'dead_lettered'
            assert spool.count_pending_entries(queue) == 0
            assert send.call_count == sent
    assert (tmp_path/'retained.mp4').read_bytes() == b'SYNTHETIC TEST ARTIFACT'


def test_crash_after_terminal_commit_before_artifact_move_cannot_republish(tmp_path):
    queue, path, entry, payload = make_entry(tmp_path)
    with mock.patch.object(spool, '_move_managed_artifact_to_dead_letter', side_effect=OSError('crash boundary')):
        with pytest.raises(OSError):
            spool.move_to_dead_letter(queue, path, entry, 'rejected')
    assert Path(path).exists()
    terminal_path, terminal = spool.spool_payload(queue, payload)
    assert terminal['retryDeadlineAt'] == entry['retryDeadlineAt']
    assert Path(terminal_path).parent.name == 'terminal'
    with mock.patch.object(spool, 'submit_artifact_submission') as send:
        stats = spool.replay_spool(queue, base_url='unused', api_key='', retries=0, use_token=False)
    send.assert_not_called()
    assert stats.dead_lettered == 1
    assert not Path(path).exists()


def test_legacy_dead_letter_is_indexed_before_cleanup_or_resume(tmp_path):
    queue, path, entry, payload = make_entry(tmp_path)
    legacy = Path(queue)/'dead-letter'/('123-'+Path(path).name)
    legacy.parent.mkdir()
    entry['lastError'] = 'old rejection'
    entry['retryDeadlineAt'] = 12345
    atomic_json(legacy, entry)
    Path(path).unlink()
    spool.cleanup_spool(queue)
    terminal_path, terminal = spool.spool_payload(queue, payload)
    assert Path(terminal_path).parent.name == 'terminal'
    assert terminal['retryDeadlineAt'] == 12345
    assert terminal['lastError'] == 'old rejection'
    assert not legacy.exists()


def test_upload_only_reports_terminal_retained_campaign_without_reencoding(tmp_path):
    queue, path, entry, payload = make_entry(tmp_path)
    spool.move_to_dead_letter(queue, path, entry, 'rejected')
    campaign_id = 'campaign-0123456789abcdef'
    root = Path(queue)/'campaigns'/campaign_id
    atomic_json(root/'campaign-complete.json', {'failed':0, 'skipped':0})
    atomic_json(root/'submission-000001.json', payload)
    before = (root/'submission-000001.json').read_bytes()
    with mock.patch.object(main, 'check_compatibility'), mock.patch.object(spool, 'submit_artifact_submission') as send, \
         mock.patch.object(main, 'run_benchmark_batch') as encode:
        for _ in range(2):
            assert main.main(['prog', '--upload-only', '--resume-campaign', campaign_id, '--queue-dir', queue]) == 1
    send.assert_not_called()
    encode.assert_not_called()
    assert (root/'submission-000001.json').read_bytes() == before


def test_corrupt_existing_queue_becomes_terminal_instead_of_getting_new_deadline(tmp_path):
    queue, path, entry, payload = make_entry(tmp_path)
    Path(path).write_text('incomplete JSON')
    terminal_path, terminal = spool.spool_payload(queue, payload)
    assert Path(terminal_path).parent.name == 'terminal'
    assert terminal['terminal'] is True
    assert not Path(path).exists()
    assert spool.spool_payload(queue, payload)[0] == terminal_path


def test_upload_copy_cannot_exceed_immutable_artifact_size(tmp_path):
    queue, path, entry, payload = make_entry(tmp_path)
    # Use another queue so there is no existing owned copy to reuse.
    changed = dict(payload, artifactByteSize=1)
    with pytest.raises(ValueError, match='size differs'):
        spool.spool_payload(str(tmp_path/'other-queue'), changed)
    assert list((tmp_path/'other-queue').glob('artifacts/*')) == []


def test_crash_after_dead_artifact_move_recovers_exact_evidence_pointer(tmp_path):
    queue, path, entry, payload = make_entry(tmp_path)
    write = spool._write_json_atomic
    def crash_receipt(target, value):
        if Path(target).parent.name == 'dead-letter':
            raise OSError('crash after artifact rename')
        return write(target, value)
    with mock.patch.object(spool, '_write_json_atomic', side_effect=crash_receipt):
        with pytest.raises(OSError):
            spool.move_to_dead_letter(queue, path, entry, 'rejected')
    with mock.patch.object(spool, 'submit_artifact_submission') as send:
        stats = spool.replay_spool(queue, base_url='unused', api_key='', retries=0, use_token=False)
    send.assert_not_called()
    assert stats.dead_lettered == 1
    dead = json.loads(next((Path(queue)/'dead-letter').glob('*.json')).read_text())
    assert Path(dead['payload']['artifactPath']).read_bytes() == b'SYNTHETIC TEST ARTIFACT'
    assert dead['retryDeadlineAt'] == entry['retryDeadlineAt']
