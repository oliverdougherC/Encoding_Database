"""Standalone metadata retention must exclude a competing collector."""

import time
from unittest import mock

import pytest

from client import network, spool
from test_online_metadata_transport import _StubbornProc, _await_quiescent


def test_standalone_metadata_retains_kernel_exclusion_until_child_is_dead(tmp_path, monkeypatch):
    monkeypatch.setenv("ENCODINGDB_HOST_PHASE_DIR", str(tmp_path / "phase"))
    proc = _StubbornProc()
    try:
        with mock.patch.object(network.subprocess, "Popen", return_value=proc):
            with pytest.raises(network.MetadataRetentionHeld):
                network.check_compatibility("http://127.0.0.1:9", "client/0.3.8",
                                            transaction_seconds=0.1)
        assert network.owned_metadata_children() == 1
        with pytest.raises(spool.SpoolCapacityError):
            with spool.host_phase_hold("measurement"):
                pass
    finally:
        proc.dead = True
        assert _await_quiescent(timeout=8)
    deadline = time.monotonic() + 2
    while spool.host_phase_busy() and time.monotonic() < deadline:
        time.sleep(0.01)
    with spool.host_phase_hold("measurement"):
        pass
