import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar, Optional

from client.network import submit


class _CompatHandler(BaseHTTPRequestHandler):
    attempts: ClassVar[int] = 0
    final_body: ClassVar[Optional[dict]] = None
    issued_tokens: ClassVar[int] = 0
    posted_tokens: ClassVar[list[str]] = []

    def do_GET(self) -> None:
        type(self).issued_tokens += 1
        token = f"{type(self).issued_tokens:032x}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"token": token, "pow": {"difficulty": 0}}).encode("utf-8"))

    def do_POST(self) -> None:
        body_len = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(body_len).decode("utf-8") if body_len > 0 else "{}"
        payload = json.loads(raw)
        type(self).attempts += 1
        token = self.headers.get("x-ingest-token")
        if token:
            type(self).posted_tokens.append(token)
        if type(self).attempts == 1:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "details": {
                    "formErrors": [
                        'Unrecognized keys: "telemetrySources", "telemetryMissing", "cpuSampleCount"'
                    ]
                }
            }).encode("utf-8"))
            return

        type(self).final_body = payload
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


class SubmitCompatibilityTests(unittest.TestCase):
    def test_submit_retries_without_rejected_new_keys(self) -> None:
        _CompatHandler.attempts = 0
        _CompatHandler.final_body = None

        server = HTTPServer(("127.0.0.1", 0), _CompatHandler)
        port = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            submit(
                f"http://127.0.0.1:{port}",
                {
                    "cpuModel": "Test CPU",
                    "telemetrySources": "cpu_psutil",
                    "telemetryMissing": "battery_unavailable",
                    "cpuSampleCount": 4,
                    "gpuUtilAvg": 33.2,
                },
                retries=1,
                use_token=False,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(_CompatHandler.attempts, 2)
        self.assertEqual(_CompatHandler.final_body, {"cpuModel": "Test CPU", "gpuUtilAvg": 33.2})

    def test_token_enabled_compatibility_retry_uses_fresh_token(self) -> None:
        _CompatHandler.attempts = 0
        _CompatHandler.final_body = None
        _CompatHandler.issued_tokens = 0
        _CompatHandler.posted_tokens = []

        server = HTTPServer(("127.0.0.1", 0), _CompatHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            submit(
                f"http://127.0.0.1:{server.server_port}",
                {"cpuModel": "Test CPU", "telemetrySources": "cpu_psutil"},
                retries=1,
                use_token=True,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(_CompatHandler.attempts, 2)
        self.assertEqual(_CompatHandler.issued_tokens, 2)
        self.assertEqual(len(set(_CompatHandler.posted_tokens)), 2)


class _TransientHandler(_CompatHandler):
    def do_POST(self) -> None:
        body_len = int(self.headers.get("Content-Length", "0"))
        if body_len > 0:
            self.rfile.read(body_len)
        type(self).attempts += 1
        token = self.headers.get("x-ingest-token")
        if token:
            type(self).posted_tokens.append(token)
        self.send_response(503 if type(self).attempts == 1 else 200)
        self.end_headers()


class SubmitTransientRetryTests(unittest.TestCase):
    def test_token_enabled_transient_retry_uses_fresh_token(self) -> None:
        _TransientHandler.attempts = 0
        _TransientHandler.issued_tokens = 0
        _TransientHandler.posted_tokens = []

        server = HTTPServer(("127.0.0.1", 0), _TransientHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            submit(
                f"http://127.0.0.1:{server.server_port}",
                {"cpuModel": "Test CPU"},
                retries=2,
                backoff_seconds=0,
                use_token=True,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(_TransientHandler.attempts, 2)
        self.assertEqual(_TransientHandler.issued_tokens, 2)
        self.assertEqual(len(set(_TransientHandler.posted_tokens)), 2)


if __name__ == "__main__":
    unittest.main()
