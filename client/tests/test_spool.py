import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar, Optional
from unittest import mock

from client.artifacts import AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND
from client.spool import count_pending_entries, load_spool_entry, replay_spool, spool_payload


class _SpoolHandler(BaseHTTPRequestHandler):
    mode: ClassVar[str] = "ok"
    last_body: ClassVar[Optional[dict]] = None

    def do_POST(self) -> None:
        body_len = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(body_len).decode("utf-8") if body_len > 0 else "{}"
        try:
            type(self).last_body = json.loads(raw)
        except Exception:
            type(self).last_body = None

        if type(self).mode == "ok":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if type(self).mode == "retryable":
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b"retry later")
            return
        self.send_response(400)
        self.end_headers()
        self.wfile.write(b"bad request")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


class SpoolTests(unittest.TestCase):
    def _authoritative_payload(self, artifact_path: str) -> dict:
        return {
            "submissionKind": AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND,
            "artifactPath": artifact_path,
            "artifactSha256": "a" * 64,
            "artifactByteSize": 4,
            "contentType": "video/mp4",
            "runCreate": {
                "payloadHash": "b" * 64,
                "artifact": {"sha256": "a" * 64, "byteSize": 4, "mediaContainer": "mp4"},
            },
        }

    def _start_server(self) -> tuple[HTTPServer, threading.Thread, str]:
        server = HTTPServer(("127.0.0.1", 0), _SpoolHandler)
        port = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread, f"http://127.0.0.1:{port}"

    def test_spool_payload_deduplicates_by_hash(self) -> None:
        with tempfile.TemporaryDirectory() as queue_dir:
            path1, entry1 = spool_payload(queue_dir, {"cpuModel": "A", "fps": 100})
            path2, entry2 = spool_payload(queue_dir, {"fps": 100, "cpuModel": "A"})
            self.assertEqual(path1, path2)
            self.assertEqual(entry1["localHash"], entry2["localHash"])
            self.assertEqual(count_pending_entries(queue_dir), 1)

    def test_replay_spool_submits_and_deletes(self) -> None:
        _SpoolHandler.mode = "ok"
        _SpoolHandler.last_body = None
        server, thread, base_url = self._start_server()
        try:
            with tempfile.TemporaryDirectory() as queue_dir:
                spool_payload(queue_dir, {"cpuModel": "A", "fps": 100})
                stats = replay_spool(
                    queue_dir,
                    base_url=base_url,
                    api_key="",
                    retries=1,
                    use_token=False,
                )
                self.assertEqual(stats.submitted, 1)
                self.assertEqual(count_pending_entries(queue_dir), 0)
                self.assertEqual(_SpoolHandler.last_body, {"cpuModel": "A", "fps": 100})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_replay_spool_retains_retryable_failures(self) -> None:
        _SpoolHandler.mode = "retryable"
        server, thread, base_url = self._start_server()
        try:
            with tempfile.TemporaryDirectory() as queue_dir:
                path, _entry = spool_payload(queue_dir, {"cpuModel": "A", "fps": 100})
                stats = replay_spool(
                    queue_dir,
                    base_url=base_url,
                    api_key="",
                    retries=1,
                    use_token=False,
                )
                self.assertEqual(stats.retained, 1)
                self.assertEqual(count_pending_entries(queue_dir), 1)
                entry = load_spool_entry(path)
                self.assertEqual(entry["attempts"], 1)
                self.assertTrue(entry["lastError"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_replay_spool_dead_letters_permanent_failures(self) -> None:
        _SpoolHandler.mode = "permanent"
        server, thread, base_url = self._start_server()
        try:
            with tempfile.TemporaryDirectory() as queue_dir:
                spool_payload(queue_dir, {"cpuModel": "A", "fps": 100})
                stats = replay_spool(
                    queue_dir,
                    base_url=base_url,
                    api_key="",
                    retries=1,
                    use_token=False,
                )
                self.assertEqual(stats.dead_lettered, 1)
                self.assertEqual(count_pending_entries(queue_dir), 0)
                dead_dir = os.path.join(queue_dir, "dead-letter")
                self.assertEqual(len(os.listdir(dead_dir)), 1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_replay_spool_moves_corrupt_files_to_dead_letter(self) -> None:
        with tempfile.TemporaryDirectory() as queue_dir:
            corrupt_path = os.path.join(queue_dir, "broken.json")
            with open(corrupt_path, "w", encoding="utf-8") as fh:
                fh.write("{not-json")
            stats = replay_spool(
                queue_dir,
                base_url="http://127.0.0.1:9",
                api_key="",
                retries=1,
                use_token=False,
            )
            self.assertEqual(stats.corrupt, 1)
            self.assertEqual(count_pending_entries(queue_dir), 0)
            dead_dir = os.path.join(queue_dir, "dead-letter")
            self.assertEqual(len(os.listdir(dead_dir)), 1)

    def test_spool_payload_preserves_authoritative_artifact_copy(self) -> None:
        with tempfile.TemporaryDirectory() as queue_dir, tempfile.TemporaryDirectory() as source_dir:
            source_path = os.path.join(source_dir, "artifact.mp4")
            with open(source_path, "wb") as handle:
                handle.write(b"test")
            _path, entry = spool_payload(queue_dir, self._authoritative_payload(source_path))
            managed_path = entry["payload"]["artifactPath"]
            self.assertTrue(os.path.exists(managed_path))
            self.assertNotEqual(os.path.realpath(managed_path), os.path.realpath(source_path))
            self.assertEqual(count_pending_entries(queue_dir), 1)

    def test_replay_spool_dead_letters_missing_authoritative_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as queue_dir, tempfile.TemporaryDirectory() as source_dir:
            source_path = os.path.join(source_dir, "artifact.mp4")
            with open(source_path, "wb") as handle:
                handle.write(b"test")
            path, _entry = spool_payload(queue_dir, self._authoritative_payload(source_path))
            managed_path = load_spool_entry(path)["payload"]["artifactPath"]
            os.remove(managed_path)
            stats = replay_spool(
                queue_dir,
                base_url="http://127.0.0.1:9",
                api_key="",
                retries=1,
                use_token=False,
            )
            self.assertEqual(stats.dead_lettered, 1)
            dead_dir = os.path.join(queue_dir, "dead-letter")
            self.assertTrue(os.listdir(dead_dir))

    def test_replay_spool_retries_authoritative_submission_then_cleans_up_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as queue_dir, tempfile.TemporaryDirectory() as source_dir:
            source_path = os.path.join(source_dir, "artifact.mp4")
            with open(source_path, "wb") as handle:
                handle.write(b"test")
            path, _entry = spool_payload(queue_dir, self._authoritative_payload(source_path))
            managed_path = load_spool_entry(path)["payload"]["artifactPath"]
            side_effects = [
                Exception("unexpected"),
                None,
            ]

            def fake_submit(*args, **kwargs):
                outcome = side_effects.pop(0)
                if outcome is None:
                    return {"analyses": [{"vmafMean": 95.25}]}
                raise outcome

            with mock.patch("client.spool.submit_artifact_submission", side_effect=fake_submit):
                first = replay_spool(
                    queue_dir,
                    base_url="http://127.0.0.1:9",
                    api_key="",
                    retries=1,
                    use_token=False,
                )
                self.assertEqual(first.retained, 1)
                self.assertTrue(os.path.exists(managed_path))
                second = replay_spool(
                    queue_dir,
                    base_url="http://127.0.0.1:9",
                    api_key="",
                    retries=1,
                    use_token=False,
                )
            self.assertEqual(second.submitted, 1)
            self.assertEqual(count_pending_entries(queue_dir), 0)
            self.assertFalse(os.path.exists(managed_path))


if __name__ == "__main__":
    unittest.main()
