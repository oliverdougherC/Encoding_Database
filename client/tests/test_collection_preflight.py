"""Compatibility-contract unit tests over real local HTTP.

F3 moved `check_compatibility` onto the owned metadata child process: the
GET (DNS/connect/headers/body) runs in a short-lived child, so an in-process
fake of `_load_requests` no longer intercepts it. These tests drive the
genuine transport against loopback fault servers and assert the PARENT-side
contract enforcement (fail-closed epoch checks, retryability classes)."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from client import network
from client.suite import load_suite_pack_metadata


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    payload: bytes = b"{}"
    status: int = 200

    def do_GET(self):
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, *args):
        return


def _serve(payload, status=200):
    handler = type("Bound", (_Handler,), {"payload": payload, "status": status})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_preflight_rejects_wrong_suite_before_encoding():
    contract = {
        "protocolVersion": "7.1", "minimumClientVersion": "client/0.3.0",
        "encodeTimerBoundary": "ffmpeg-process-v1", "sourceSuiteVersion": "encodingdb-test-suite-v1",
        "suiteFingerprint": load_suite_pack_metadata()["suiteFingerprint"],
    }
    server, base_url = _serve(json.dumps(contract).encode())
    try:
        assert network.check_compatibility(base_url, "client/0.3.0") == contract
    finally:
        server.shutdown()
        server.server_close()
    server, base_url = _serve(json.dumps({**contract, "suiteFingerprint": "0" * 64}).encode())
    try:
        with pytest.raises(network.SubmitError) as mismatch:
            network.check_compatibility(base_url, "client/0.3.0")
        assert mismatch.value.retryable is False
    finally:
        server.shutdown()
        server.server_close()
    server, base_url = _serve(json.dumps({"error": "epoch mismatch"}).encode(), status=409)
    try:
        with pytest.raises(network.SubmitError) as conflict:
            network.check_compatibility(base_url, "client/0.3.0")
        assert conflict.value.retryable is True
        assert conflict.value.status_code == 409
    finally:
        server.shutdown()
        server.server_close()
    # Zero owned children may outlive any contract outcome.
    deadline = time.monotonic() + 5.0
    while network.owned_metadata_children() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert network.owned_metadata_children() == 0