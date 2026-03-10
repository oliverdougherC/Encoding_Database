import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar, List, Optional

from client.network import submit


class _RedirectHandler(BaseHTTPRequestHandler):
    paths: ClassVar[List[str]] = []
    final_body: ClassVar[Optional[dict]] = None

    def do_POST(self) -> None:
        body_len = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(body_len).decode("utf-8") if body_len > 0 else "{}"
        type(self).paths.append(self.path)

        if self.path == "/submit":
            self.send_response(307)
            self.send_header("Location", "/submit2")
            self.end_headers()
            return

        if self.path == "/submit2":
            try:
                type(self).final_body = json.loads(raw)
            except Exception:
                type(self).final_body = None
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


class SubmitRedirectTests(unittest.TestCase):
    def test_submit_handles_relative_redirect_location(self) -> None:
        _RedirectHandler.paths = []
        _RedirectHandler.final_body = None

        server = HTTPServer(("127.0.0.1", 0), _RedirectHandler)
        port = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            submit(
                f"http://127.0.0.1:{port}",
                {"cpuModel": "Test CPU"},
                retries=1,
                use_token=False,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(_RedirectHandler.paths, ["/submit", "/submit2"])
        self.assertEqual(_RedirectHandler.final_body, {"cpuModel": "Test CPU"})


if __name__ == "__main__":
    unittest.main()
