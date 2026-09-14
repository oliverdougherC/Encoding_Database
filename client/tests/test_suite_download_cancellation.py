"""Small real HTTP/thread fixtures. No canonical media, helpers, or remote network.

Original regression: Release Preflight 34815842143, merge
f2528dc3c87c0222e681b77837e15dcb1966861b. See the retained failed-step log.
"""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time
from unittest import mock

import pytest
from client import campaign, suite


def metadata(data):
    return {'distribution': {'byteSize': len(data), 'sha256': hashlib.sha256(data).hexdigest()}}


def start_download(target, data, cancel):
    errors = []
    def download():
        try:
            with campaign.PreparationScope(cancel).activate():
                suite._download_suite_pack('https://example.invalid/pack', str(target), metadata(data))
        except BaseException as exc:
            errors.append(exc)
    caller = threading.Thread(target=download)
    caller.start()
    return caller, errors


def join(thread):
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_normal_slow_headers_and_redirect_are_tolerated(tmp_path):
    data = b'verified-pack-fixture'
    requests_seen = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            requests_seen.append(self.path)
            # Both waits exceed the old read timeout of one second.
            time.sleep(1.1)
            if self.path == '/redirect':
                self.send_response(302)
                self.send_header('Location', '/pack')
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
    server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    try:
        target = tmp_path/'pack'
        suite._download_suite_pack(f'http://127.0.0.1:{server.server_port}/redirect', str(target), metadata(data))
        assert target.read_bytes() == data
        assert requests_seen == ['/redirect','/pack']
    finally:
        server.shutdown()
        server.server_close()
        join(serving)
        campaign.wait_for_owned_acquisition()


def test_header_cancellation_is_prompt_and_late_response_cannot_consume_body(tmp_path):
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    cancel = threading.Event()
    response = mock.Mock(status_code=200)
    response.close.side_effect = closed.set
    response.iter_content.side_effect = AssertionError('cancelled response body must never be consumed')
    def get(*args, **kwargs):
        assert kwargs['timeout'] == (10,30)
        assert kwargs['allow_redirects'] is False
        entered.set()
        assert release.wait(5)
        return response
    requests = mock.Mock()
    requests.get.side_effect = get
    target = tmp_path/'pack'
    with mock.patch.object(suite, '_load_requests', return_value=requests):
        caller, errors = start_download(target, b'fixture', cancel)
        try:
            assert entered.wait(2)
            cancel.set()
            join(caller)
            assert len(errors) == 1 and isinstance(errors[0], KeyboardInterrupt)
            assert not target.exists() and not Path(str(target)+'.part').exists()
            assert not closed.is_set()  # Cancellation did not wait for the network.
        finally:
            release.set()
            assert closed.wait(2)
            campaign.wait_for_owned_acquisition()
            join(caller)
    response.iter_content.assert_not_called()
    response.close.assert_called_once()


def test_body_cancellation_preserves_written_partial_and_fences_next_preparation(tmp_path):
    body_waiting, release, closed = threading.Event(), threading.Event(), threading.Event()
    written = threading.Event()
    cancel = threading.Event()
    response = mock.Mock(status_code=200)
    response.close.side_effect = closed.set
    first = b'a' * (64*1024)
    def chunks(**kwargs):
        yield first
        body_waiting.set()
        assert release.wait(5)
        yield b'late bytes'
    response.iter_content.side_effect = chunks
    requests = mock.Mock()
    requests.get.return_value = response
    target = tmp_path/'pack'
    after_fence = threading.Event()
    second_cancel = threading.Event()
    second_errors = []
    def next_preparation():
        try:
            with campaign.PreparationScope(second_cancel).activate():
                after_fence.set()  # Cached preparation / measurement entry cannot run earlier.
                suite._download_suite_pack('https://example.invalid/pack', str(tmp_path/'second'), metadata(first+b'late bytes'))
        except BaseException as exc:
            second_errors.append(exc)
    original_progress = suite.preparation_progress
    def progress(stage, **details):
        original_progress(stage, **details)
        if details.get('completedBytes') == len(first):
            written.set()
    with mock.patch.object(suite, '_load_requests', return_value=requests), \
         mock.patch.object(suite, 'preparation_progress', side_effect=progress):
        caller, errors = start_download(target, first+b'late bytes', cancel)
        second = None
        try:
            assert body_waiting.wait(2)
            partial = Path(str(target)+'.part')
            # Buffered file bytes need only become visible when cancellation
            # closes the writer, not after each network chunk.
            assert written.wait(2)
            cancel.set()
            join(caller)
            assert isinstance(errors[0], KeyboardInterrupt)
            assert partial.read_bytes() == first and not target.exists()
            second = threading.Thread(target=next_preparation)
            second.start()
            assert not after_fence.wait(0.2)
            second_cancel.set()
            join(second)
            assert isinstance(second_errors[0], KeyboardInterrupt)
            requests.get.assert_called_once()  # No accumulating reader on repeated Stop/Start.
            release.set()
            assert closed.wait(2)
            campaign.wait_for_owned_acquisition()
            with campaign.PreparationScope().activate():
                after_fence.set()
            assert after_fence.is_set() and partial.read_bytes() == first
        finally:
            cancel.set(); second_cancel.set(); release.set()
            join(caller)
            if second is not None:
                join(second)
            campaign.wait_for_owned_acquisition()


def test_bad_completed_bytes_never_install_and_redirects_are_bounded(tmp_path):
    response = mock.Mock(status_code=200)
    response.iter_content.return_value = [b'evil']
    requests = mock.Mock()
    requests.get.return_value = response
    with mock.patch.object(suite, '_load_requests', return_value=requests):
        with pytest.raises(RuntimeError, match='checksum'):
            suite._download_suite_pack('https://example.invalid/pack', str(tmp_path/'pack'), metadata(b'good'))
        assert not (tmp_path/'pack').exists()
        response.status_code = 302
        response.headers = {'Location':'/loop'}
        requests.get.reset_mock()
        with pytest.raises(RuntimeError, match='redirect limit'):
            suite._download_suite_pack('https://example.invalid/loop', str(tmp_path/'other'), metadata(b'good'))
        assert requests.get.call_count == suite._SUITE_MAX_REDIRECTS + 1
    campaign.wait_for_owned_acquisition()
