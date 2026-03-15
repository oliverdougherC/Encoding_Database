import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar, Optional

from client.network import submit


class _CompatHandler(BaseHTTPRequestHandler):
    attempts: ClassVar[int] = 0
    final_body: ClassVar[Optional[dict]] = None

    def do_POST(self) -> None:
        body_len = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(body_len).decode("utf-8") if body_len > 0 else "{}"
        payload = json.loads(raw)
        type(self).attempts += 1
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


if __name__ == "__main__":
    unittest.main()
