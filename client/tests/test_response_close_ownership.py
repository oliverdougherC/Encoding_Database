"""Response-close I/O must remain owned after a response deadline."""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import pytest
import requests

from client import main, network, spool


class _DrippedBody(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "8192")
        self.end_headers()
        try:
            for _ in range(8192):
                self.wfile.write(b"x")
                self.wfile.flush()
                time.sleep(0.01)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


class _DelayedClose:
    """A real HTTP response with controlled connection-close completion."""

    def __init__(self, response):
        self.response = response
        self.started = threading.Event()
        self.finish = threading.Event()
        self.finished = threading.Event()
        self.lock = threading.Lock()

    def __getattr__(self, name):
        return getattr(self.response, name)

    def close(self):
        with self.lock:
            first = not self.started.is_set()
            if first:
                self.started.set()
        if first:
            try:
                assert self.finish.wait(8), "test did not release its close worker"
                self.response.close()
            finally:
                self.finished.set()


def test_response_deadline_retains_close_worker_and_host_exclusion(tmp_path, monkeypatch):
    monkeypatch.setenv("ENCODINGDB_HOST_PHASE_DIR", str(tmp_path / "host-phase"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DrippedBody)
    server.daemon_threads = True
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    delayed = None
    try:
        with spool.host_phase_hold("measurement"):
            response = network._run_cancellable(
                lambda: requests.get(f"http://127.0.0.1:{server.server_port}/body",
                                     stream=True, timeout=3),
                phase="close-test-headers", cancel_event=None,
                deadline=time.monotonic() + 3, bound_seconds=3)
            delayed = _DelayedClose(response)
            # No operator cancellation: the absolute response deadline starts
            # the background closer while real dripped socket data arrives.
            with pytest.raises(network.SubmitError):
                network._read_response_body(requests, delayed, None,
                                            time.monotonic() + 0.1)
            assert delayed.started.is_set() and not delayed.finished.is_set()
            assert not network.await_owned_worker_quiescence(0)
            with mock.patch.object(main, "PUBLICATION_QUIESCENCE_BARRIER_SECONDS", 0.05):
                with pytest.raises(spool.SpoolCapacityError, match="quiescence"):
                    main._await_publication_quiescence("an encode")

        # The synchronous join window has ended. A fresh phase must still be
        # excluded while the deferred closer owns the live HTTP response.
        assert not delayed.finished.is_set()
        with pytest.raises(spool.SpoolCapacityError):
            with spool.host_phase_hold("measurement"):
                pass
        delayed.finish.set()
        assert delayed.finished.wait(2)
        deadline = time.monotonic() + 2
        while spool.host_phase_busy() and time.monotonic() < deadline:
            time.sleep(0.01)
        with spool.host_phase_hold("measurement"):
            pass
    finally:
        if delayed is not None:
            delayed.finish.set()
            assert delayed.finished.wait(2)
        server.shutdown()
        server.server_close()
        serving.join(2)
