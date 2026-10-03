"""A confirmed Windows Close has one finite grace period."""

import time
from unittest import mock

import pytest

from client import windows_gui as gui
from test_progress_contract import _build_gui_app
from test_windows_gui import FakeThread


def test_close_grace_does_not_renew_forever_with_live_owned_worker():
    app = _build_gui_app()
    root = app.root
    uploader = FakeThread()
    uploader.start()
    app.upload_thread = uploader
    app._close_deadline = time.monotonic() - 1
    with mock.patch.object(gui, "_terminate_owned_children", create=True) as terminate, \
         mock.patch.object(gui.os, "_exit", side_effect=SystemExit(130)) as exit_process:
        with pytest.raises(SystemExit):
            app._close_when_stopped()
    terminate.assert_called_once()
    exit_process.assert_called_once_with(130)
    root.destroy.assert_called_once()
    assert app._close_deadline < time.monotonic()
