"""Normal collection must use the same cancellation as manual Retry."""

import threading
from unittest import mock

from client import main, spool
from client.network import SubmissionCancelled


def test_live_batch_submission_passes_its_stop_event_to_network_replay(tmp_path):
    stop = threading.Event()
    with mock.patch.object(main, "spool_payload", return_value=("saved", {})), \
         mock.patch.object(main, "submit_spooled_path", return_value=("retained", "cancelled")) as send, \
         mock.patch.object(main, "count_pending_entries", return_value=1):
        main._submit_payload_with_spool(
            queue_dir=str(tmp_path), base_url="http://127.0.0.1:9",
            payload={"runCreate": {"payloadHash": "a" * 64}}, api_key="",
            retries=1, use_token=False, cancel_event=stop,
        )
    assert send.call_args.kwargs["cancel_event"] is stop


def test_checkpoint_queue_replay_passes_the_collection_stop_event(tmp_path):
    stop = threading.Event()
    with mock.patch.object(main, "replay_spool", return_value=spool.ReplayStats()) as replay, \
         mock.patch.object(main, "count_pending_entries", return_value=0):
        main._replay_pending_uploads(
            queue_dir=str(tmp_path), base_url="http://127.0.0.1:9",
            api_key="", retries=1, use_token=False, cancel_event=stop,
        )
    assert replay.call_args.kwargs["cancel_event"] is stop


def test_real_batch_upload_uses_the_gui_stop_event_and_retains_queue(tmp_path):
    from test_progress_contract import _run_batch

    stop = threading.Event()
    observed = []

    def cancelled_create(_base_url, _payload, **kwargs):
        observed.append(kwargs.get("cancel_event") is stop)
        observed.append(isinstance(kwargs.get("deadline"), float))
        stop.set()
        raise SubmissionCancelled("run create")

    events = []
    rc = _run_batch(tmp_path, seed=712, events=events,
                    transport=cancelled_create, no_submit=False,
                    cancel_event=stop)
    assert rc == 130
    assert observed == [True, True]
    assert spool.count_pending_entries(str(tmp_path)) >= 1
    assert any(event.get("type") == "run_interrupted" for event in events)
