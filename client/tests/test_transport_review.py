"""Independent review regressions for transport worker ownership."""

import threading
import time

import pytest

from client import network, spool


def test_body_reader_never_consumes_past_its_hard_cap():
    class Response:
        def __init__(self):
            self.consumed = 0
            self.closed = False

        def iter_content(self, chunk_size):
            while True:
                self.consumed += chunk_size
                yield b"x" * chunk_size

        def close(self):
            self.closed = True

    response = Response()
    network._read_response_body(None, response, None, time.monotonic() + 2,
                                max_bytes=65536)
    assert response.consumed <= 65536
    assert response.closed


def test_second_publication_retains_host_lock_for_its_straggler(tmp_path, monkeypatch):
    monkeypatch.setenv("ENCODINGDB_HOST_PHASE_DIR", str(tmp_path))
    with spool.host_phase_hold("publication"):
        pass  # The first phase must not own workers started by a later phase.

    stop = threading.Event()
    started = threading.Event()
    finish = threading.Event()

    def blocked():
        started.set()
        finish.wait(5)
        return None

    def cancel_after_start():
        assert started.wait(1)
        stop.set()

    canceller = threading.Thread(target=cancel_after_start)
    canceller.start()
    try:
        with pytest.raises(network.SubmissionCancelled):
            with spool.host_phase_hold("publication"):
                network._run_cancellable(
                    blocked, phase="review-blocked", cancel_event=stop,
                    deadline=time.monotonic() + 5, bound_seconds=5,
                )
        assert network.owned_worker_census() >= 1
        with pytest.raises(spool.SpoolCapacityError):
            with spool.host_phase_hold("measurement"):
                pass
    finally:
        finish.set()
        canceller.join(1)
    deadline = time.monotonic() + 2
    while network.owned_worker_census() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert network.owned_worker_census() == 0


def test_abandoned_response_is_closed_when_worker_finishes(tmp_path, monkeypatch):
    monkeypatch.setenv("ENCODINGDB_HOST_PHASE_DIR", str(tmp_path))
    started = threading.Event()
    finish = threading.Event()
    stop = threading.Event()

    class Response:
        closed = False

        def close(self):
            self.closed = True

    response = Response()

    def late_response():
        started.set()
        finish.wait(5)
        return response

    def cancel_after_start():
        assert started.wait(1)
        stop.set()

    canceller = threading.Thread(target=cancel_after_start)
    canceller.start()
    try:
        with pytest.raises(network.SubmissionCancelled):
            with spool.host_phase_hold("publication"):
                network._run_cancellable(
                    late_response, phase="review-response", cancel_event=stop,
                    deadline=time.monotonic() + 5, bound_seconds=5,
                )
    finally:
        finish.set()
        canceller.join(1)
    deadline = time.monotonic() + 2
    while not response.closed and time.monotonic() < deadline:
        time.sleep(0.01)
    assert response.closed


def test_host_lock_covers_late_response_close_io(tmp_path, monkeypatch):
    monkeypatch.setenv("ENCODINGDB_HOST_PHASE_DIR", str(tmp_path))
    started = threading.Event()
    stop = threading.Event()
    return_response = threading.Event()
    closing = threading.Event()
    allow_close = threading.Event()

    class Response:
        def close(self):
            closing.set()
            allow_close.wait(5)

    def late_response():
        started.set()
        return_response.wait(5)
        return Response()

    def release_after_cancel():
        assert started.wait(1)
        stop.set()
        time.sleep(0.1)
        return_response.set()

    releaser = threading.Thread(target=release_after_cancel)
    releaser.start()
    try:
        with pytest.raises(network.SubmissionCancelled):
            with spool.host_phase_hold("publication"):
                network._run_cancellable(
                    late_response, phase="review-close-io", cancel_event=stop,
                    deadline=time.monotonic() + 5, bound_seconds=5,
                )
        assert closing.wait(2)
        with pytest.raises(spool.SpoolCapacityError):
            with spool.host_phase_hold("measurement"):
                pass
    finally:
        allow_close.set()
        return_response.set()
        releaser.join(1)
