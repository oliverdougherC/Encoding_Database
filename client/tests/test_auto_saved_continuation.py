"""Normal Windows idle work must restage explicitly consented saved campaigns."""

from unittest import mock

from client import main, windows_gui as gui
from test_progress_contract import _build_gui_app
from test_windows_gui import FakeThread


def _state(campaign_id, fingerprint):
    return {
        "publicationConsent": True,
        "activeCollection": None,
        "publicationLockBusy": False,
        "publication": {"pendingEntries": 0, "dueEntries": 0,
                        "acceptedReceipts": 0, "terminalEntries": 0},
        "campaigns": [{
            "campaignId": campaign_id, "complete": True,
            "pendingUploads": 1, "queueDue": 0, "queueTerminal": 0,
            "unavailableSources": 0,
            "actions": [{"action": "publish_saved"}],
            "publicationIntent": {"active": True,
                                  "baseUrlFingerprint": fingerprint,
                                  "nextAttemptAt": 0},
        }],
    }


def test_idle_windows_restages_saved_suffix_without_another_click():
    app = _build_gui_app()
    app.no_submit_var.set(False)
    base_url = app.base_url_var.get().strip() or str(app.base_args.base_url)
    campaign_id = "campaign-0123456789abcdef"
    app._load_recovery_state = lambda: _state(
        campaign_id, main.publication_endpoint_fingerprint(base_url))
    with mock.patch.object(gui.threading, "Thread", FakeThread):
        app._idle_retry()
    assert app.upload_thread is not None
    assert app.upload_thread.target.__name__ == "_publish_saved_worker"
    assert app.upload_thread.args[0] == campaign_id


def test_idle_windows_does_not_publish_to_changed_endpoint():
    app = _build_gui_app()
    app.no_submit_var.set(False)
    app._load_recovery_state = lambda: _state(
        "campaign-0123456789abcdef", "different-endpoint-fingerprint")
    with mock.patch.object(gui.threading, "Thread", FakeThread):
        app._idle_retry()
    assert app.upload_thread is None
