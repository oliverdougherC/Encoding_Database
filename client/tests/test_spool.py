import json
import hashlib
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar, Optional
from unittest import mock

from client.artifacts import AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND
from client.spool import cleanup_spool, collector_publication_scope, count_pending_entries, due_first_queue_paths, inspect_spool, load_spool_entry, replay_spool, spool_payload


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
        artifact_bytes = open(artifact_path, "rb").read() if os.path.exists(artifact_path) else b"test"
        return {
            "submissionKind": AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND,
            "artifactPath": artifact_path,
            "artifactSha256": hashlib.sha256(artifact_bytes).hexdigest(),
            "artifactByteSize": len(artifact_bytes),
            "contentType": "video/mp4",
            "runCreate": {
                "payloadHash": "b" * 64,
                "artifact": {"sha256": hashlib.sha256(artifact_bytes).hexdigest(), "byteSize": len(artifact_bytes), "mediaContainer": "mp4"},
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

    def test_replay_rejects_tampered_or_out_of_tree_artifacts_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as queue_dir, tempfile.TemporaryDirectory() as source_dir:
            source_path = os.path.join(source_dir, "artifact.mp4")
            with open(source_path, "wb") as handle:
                handle.write(b"test")
            path, _entry = spool_payload(queue_dir, self._authoritative_payload(source_path))
            managed_path = load_spool_entry(path)["payload"]["artifactPath"]
            with open(managed_path, "wb") as handle:
                handle.write(b"evil")
            with mock.patch("client.spool.submit_artifact_submission") as submit_mock:
                stats = replay_spool(queue_dir, base_url="http://127.0.0.1:9", api_key="", retries=1, use_token=False)
            self.assertEqual(stats.dead_lettered, 1)
            submit_mock.assert_not_called()

            # This is a distinct immutable observation. Reusing the rejected
            # payload would correctly return its terminal receipt without replay.
            other_payload = self._authoritative_payload(source_path)
            other_payload["runCreate"]["payloadHash"] = "c" * 64
            path, entry = spool_payload(queue_dir, other_payload)
            entry["payload"]["artifactPath"] = source_path
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(entry, handle)
            with mock.patch("client.spool.submit_artifact_submission") as submit_mock:
                stats = replay_spool(queue_dir, base_url="http://127.0.0.1:9", api_key="", retries=1, use_token=False)
            self.assertEqual(stats.dead_lettered, 1)
            submit_mock.assert_not_called()

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
                entry = load_spool_entry(path)
                entry["nextAttemptAt"] = 0
                with open(path, "w") as handle:
                    json.dump(entry, handle)
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

    def test_inspect_and_cleanup_spool_preserve_pending_entries(self) -> None:
        _SpoolHandler.mode = "permanent"
        server, thread, base_url = self._start_server()
        try:
            with tempfile.TemporaryDirectory() as queue_dir:
                spool_payload(queue_dir, {"cpuModel": "A", "fps": 100})
                replay_spool(
                    queue_dir,
                    base_url=base_url,
                    api_key="",
                    retries=1,
                    use_token=False,
                )
                spool_payload(queue_dir, {"cpuModel": "B", "fps": 200})

                orphan_dir = os.path.join(queue_dir, "artifacts")
                os.makedirs(orphan_dir, exist_ok=True)
                orphan_path = os.path.join(orphan_dir, "orphan.bin")
                with open(orphan_path, "wb") as handle:
                    handle.write(b"orphan")

                status = inspect_spool(queue_dir)
                self.assertEqual(status.pending_entries, 1)
                self.assertGreaterEqual(status.dead_letter_files, 1)
                self.assertEqual(status.managed_artifact_files, 1)

                cleanup = cleanup_spool(queue_dir)
                self.assertEqual(cleanup.pending_entries_retained, 1)
                self.assertGreaterEqual(cleanup.removed_dead_letter_files, 1)
                self.assertEqual(cleanup.removed_orphaned_managed_artifacts, 1)
                self.assertEqual(count_pending_entries(queue_dir), 1)
                self.assertFalse(os.path.exists(orphan_path))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_unrelated_retained_campaign_does_not_block_this_upload(self) -> None:
        # Review scenario: a Large campaign retaining >2 GiB must not consume the
        # allowance of a Small run spooling its own measured artifact.
        with tempfile.TemporaryDirectory() as queue_dir, tempfile.TemporaryDirectory() as source_dir:
            other_root = os.path.join(queue_dir, "campaigns", "campaign-" + "f" * 16)
            os.makedirs(other_root)
            with open(os.path.join(other_root, "retained.bin"), "wb") as bulk:
                bulk.truncate(2100 * 1024 * 1024)
            source_path = os.path.join(queue_dir, "campaigns", "campaign-" + "a" * 16, "artifact.mp4")
            os.makedirs(os.path.dirname(source_path), exist_ok=True)
            with open(source_path, "wb") as handle:
                handle.write(b"test")
            payload = self._authoritative_payload(source_path)
            path, _entry = spool_payload(queue_dir, payload, max_storage_mb=2048)
            managed_path = load_spool_entry(path)["payload"]["artifactPath"]
            self.assertTrue(os.path.exists(managed_path))
            with mock.patch("client.spool.submit_artifact_submission",
                            return_value={"analyses": [{"vmafMean": 95.25}]}):
                stats = replay_spool(queue_dir, base_url="http://127.0.0.1:9", api_key="",
                                     retries=1, use_token=False)
            self.assertEqual(stats.submitted, 1)
            self.assertEqual(count_pending_entries(queue_dir), 0)
            self.assertFalse(os.path.exists(managed_path))  # accepted upload retires staging
            self.assertTrue(os.path.exists(os.path.join(other_root, "retained.bin")))

    def test_spool_capacity_charges_own_campaign_and_honors_free_floor(self) -> None:
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as queue_dir, tempfile.TemporaryDirectory() as source_dir:
            mine = os.path.join(queue_dir, "campaigns", "campaign-" + "a" * 16)
            os.makedirs(mine)
            bulk = os.path.join(mine, "retained.bin")
            with open(bulk, "wb") as handle:
                handle.truncate(2100 * 1024 * 1024)
            source_path = os.path.join(queue_dir, "campaigns", "campaign-" + "a" * 16, "artifact.mp4")
            os.makedirs(os.path.dirname(source_path), exist_ok=True)
            with open(source_path, "wb") as handle:
                handle.write(b"test")
            payload = self._authoritative_payload(source_path)
            with self.assertRaisesRegex(OSError, "this campaign's retained attempts"):
                spool_payload(queue_dir, payload, max_storage_mb=2048)
            os.remove(bulk)  # own campaign now small; disk floor must still protect the volume
            with mock.patch("client.spool.shutil.disk_usage",
                            return_value=SimpleNamespace(total=1024 ** 4, used=0, free=500 * 1024 * 1024)):
                with self.assertRaisesRegex(OSError, "safety"):
                    spool_payload(queue_dir, payload, max_storage_mb=2048)

    def test_publication_defers_to_a_measuring_collector(self) -> None:
        # C11, collector-first order: while measurement.lock is held, both new
        # staging and replay must defer (recoverable pause), never upload.
        import fcntl
        with tempfile.TemporaryDirectory() as queue_dir:
            source_path = os.path.join(queue_dir, "artifact.mp4")
            with open(source_path, "wb") as handle:
                handle.write(b"test")
            payload = self._authoritative_payload(source_path)
            with open(os.path.join(queue_dir, "measurement.lock"), "a+b") as held:
                fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(OSError, "publication defers"):
                    spool_payload(queue_dir, payload, max_storage_mb=2048)
                with self.assertRaisesRegex(OSError, "publication defers"):
                    replay_spool(queue_dir, base_url="http://127.0.0.1:1", api_key="", retries=1, use_token=False)
                with collector_publication_scope():
                    # The collector's own checkpoint uploads legitimately proceed.
                    path, entry = spool_payload(queue_dir, payload, max_storage_mb=2048)
            self.assertTrue(os.path.exists(path))
            self.assertFalse(entry.get("terminal"))

    def test_collector_entry_refuses_while_publisher_owns_queue(self) -> None:
        # C11 reverse order: a publisher holding publication.lock blocks the next
        # collection; releasing it lets the collector proceed.
        from client import main as client_main
        import fcntl
        with tempfile.TemporaryDirectory() as queue_dir:
            with open(os.path.join(queue_dir, "publication.lock"), "a+b") as held:
                fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                events = []
                rc = client_main.active_collection_guard(queue_dir, lambda event: events.append(event))
                self.assertEqual(rc, 6)
                self.assertTrue(any("publication pass" in str(event.get("message")) for event in events),
                                "the refusal must name the publisher, not a phantom collector")
            self.assertIsNone(client_main.active_collection_guard(queue_dir))

    def test_due_first_window_skips_delayed_and_stays_fair(self) -> None:
        # C08: delayed (Retry-After in the future) entries never enter the
        # window; due entries are admitted oldest-scheduled first and the
        # window stays bounded when more than `limit` are due.
        import time as _time
        with tempfile.TemporaryDirectory() as queue_dir:
            for index in range(25):
                path1, entry1 = spool_payload(queue_dir, {"cpuModel": f"delayed-{index}", "fps": 1})
                entry1["nextAttemptAt"] = _time.time() + 3600
                entry1["retryDeadlineAt"] = _time.time() + 86400
                with open(path1, "w") as handle:
                    json.dump(entry1, handle)
            due_paths = []
            for index in range(3):
                path2, entry2 = spool_payload(queue_dir, {"cpuModel": f"due-{index}", "fps": 1})
                entry2["nextAttemptAt"] = _time.time() - (10 - index)  # due, staggered
                with open(path2, "w") as handle:
                    json.dump(entry2, handle)
                due_paths.append(path2)
            selected, deferred = due_first_queue_paths(queue_dir, limit=25)
            self.assertEqual(sorted(selected), sorted(due_paths),
                             "only due entries may be attempted; delayed must wait")
            self.assertEqual(deferred, 25)
            # Oldest-scheduled first (fairness)
            self.assertEqual([os.path.basename(p) for p in selected],
                             [os.path.basename(p) for p in sorted(due_paths, key=lambda p: load_spool_entry(p)["nextAttemptAt"])])
            # Bound: with limit=2 the two earliest win; the third is deferred, not dropped silently
            capped, deferred2 = due_first_queue_paths(queue_dir, limit=2)
            self.assertEqual(len(capped), 2)
            self.assertEqual(deferred2, 26)

    def test_replay_cancellation_is_bounded_and_keeps_entries_durable(self) -> None:
        # C12: a cancel request stops admission between entries; every entry
        # keeps its durable file so the next pass retries idempotently, and a
        # pre-set cancel performs zero network attempts.
        with tempfile.TemporaryDirectory() as queue_dir:
            for index in range(3):
                spool_payload(queue_dir, {"cpuModel": f"p{index}", "fps": 1})
            cancelled = type("AlwaysCancelled", (), {"is_set": lambda self: True})()
            stats = replay_spool(queue_dir, base_url="http://127.0.0.1:1", api_key="",
                                 retries=1, use_token=False, cancel_event=cancelled)
            self.assertEqual(stats.submitted, 0)
            self.assertEqual(stats.cancelled, 1)
            self.assertEqual(stats.deferred, 2)
            self.assertEqual(count_pending_entries(queue_dir), 3,
                             "cancellation must never lose or duplicate durable work")

    def test_lost_response_stays_durable_and_retries_idempotently(self) -> None:
        # C12: a dropped/ambiguous network outcome must keep the exact pending
        # entry (same localHash identity) and the next pass completes it once.
        _SpoolHandler.mode = "ok"
        server, thread, base_url = self._start_server()
        try:
            with tempfile.TemporaryDirectory() as queue_dir:
                path, entry = spool_payload(queue_dir, {"cpuModel": "ambiguous", "fps": 1})
                hash_before = entry["localHash"]
                from client.spool import submit as real_submit
                calls = {"n": 0}
                def flaky(*args, **kwargs):
                    calls["n"] += 1
                    if calls["n"] == 1:
                        raise ConnectionError("response lost mid-transaction")
                    return real_submit(*args, **kwargs)
                with mock.patch("client.spool.submit", side_effect=flaky):
                    stats = replay_spool(queue_dir, base_url=base_url, api_key="", retries=1, use_token=False)
                    self.assertEqual((stats.submitted, stats.retained), (0, 1))
                    retained = load_spool_entry(path)
                    self.assertEqual(retained["localHash"], hash_before,
                                     "ambiguous outcome must not replace retry identity")
                    retained["nextAttemptAt"] = 0  # due now (test clock shortcut)
                    with open(path, "w") as handle:
                        json.dump(retained, handle)
                    stats2 = replay_spool(queue_dir, base_url=base_url, api_key="", retries=1, use_token=False)
                self.assertEqual(stats2.submitted, 1)
                self.assertEqual(count_pending_entries(queue_dir), 0)
        finally:
            server.shutdown()
            thread.join(timeout=5)


class HostPhaseExclusionTests(unittest.TestCase):
    """C11: kernel-backed host phase exclusion across distinct queue dirs."""

    def _phase_dir_like(self, tmp: str) -> str:
        root = os.path.join(tmp, "host-phase")
        os.makedirs(root, exist_ok=True)
        return root


    def test_collector_first_defers_publisher_on_other_queue(self) -> None:
        # The publisher runs on its own thread: same-thread re-entry is the
        # collector's own checkpoint-upload path and legitimately bypasses the
        # probe; a *different* publisher (thread/process) must be refused.
        from client.spool import SpoolCapacityError, host_phase_hold
        errors: list = []
        queue_b: list = []
        def publish():
            try:
                spool_payload(queue_b[0], {"cpuModel": "other-queue", "fps": 1})
            except BaseException as exc:  # noqa: BLE001 - recorded for assertion
                errors.append(exc)
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(os.environ, {"ENCODINGDB_HOST_PHASE_DIR": self._phase_dir_like(tmp)}):
            queue_b.append(os.path.join(tmp, "qb"))
            collector = host_phase_hold("measurement")
            collector.__enter__()
            try:
                thread = threading.Thread(target=publish)
                thread.start()
                thread.join(5)
                self.assertFalse(thread.is_alive())
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0], SpoolCapacityError)
                self.assertIn("measuring on this host", str(errors[0]))
            finally:
                collector.__exit__(None, None, None)
            queue_b[0] = os.path.join(tmp, "qb2")
            with mock.patch("client.spool.submit_artifact_submission", return_value={}):
                spool_payload(queue_b[0], {"cpuModel": "after-release", "fps": 1})

    def test_publisher_first_defers_collector_and_allows_second_publisher(self) -> None:
        from client.spool import SpoolCapacityError, host_phase_hold
        errors: list = []
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(os.environ, {"ENCODINGDB_HOST_PHASE_DIR": self._phase_dir_like(tmp)}):
            publisher = host_phase_hold("publication")
            publisher.__enter__()
            def collector_start():
                try:
                    hold = host_phase_hold("measurement")
                    hold.__enter__()
                except BaseException as exc:  # noqa: BLE001 - recorded for assertion
                    errors.append(exc)
                    return
                errors.append(None)
                hold.__exit__(None, None, None)
            try:
                thread = threading.Thread(target=collector_start)
                thread.start()
                thread.join(5)
                self.assertFalse(thread.is_alive())
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0], SpoolCapacityError)
                self.assertIn("owns this host right now", str(errors[0]))
                # A second publisher coexists: idempotent uploads are not a
                # timing hazard and must not deadlock each other.
                with host_phase_hold("publication"):
                    pass
            finally:
                publisher.__exit__(None, None, None)

    def test_crashed_owner_releases_host_phase_for_reopen(self) -> None:
        import signal
        import subprocess
        from client.spool import host_phase_busy, host_phase_hold
        with tempfile.TemporaryDirectory() as tmp:
            phase_dir = self._phase_dir_like(tmp)
            env = dict(os.environ, ENCODINGDB_HOST_PHASE_DIR=phase_dir)
            script = (
                "import os, fcntl, time\n"
                "path = os.path.join(os.environ['ENCODINGDB_HOST_PHASE_DIR'], 'phase.lock')\n"
                "handle = open(path, 'a+b')\n"
                "fcntl.flock(handle.fileno(), fcntl.LOCK_EX)\n"
                "print('HELD', flush=True)\n"
                "time.sleep(30)\n")
            proc = subprocess.Popen([sys.executable, "-c", script], env=env,
                                    stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(proc.stdout.readline().strip(), "HELD")
                with mock.patch.dict(os.environ, {"ENCODINGDB_HOST_PHASE_DIR": phase_dir}):
                    self.assertTrue(host_phase_busy())
                    os.kill(proc.pid, signal.SIGKILL)
                    proc.wait(5)
                    self.assertFalse(host_phase_busy(),
                                     "kernel must release a crashed owner's phase lock")
                    with host_phase_hold("measurement") as acquired:
                        self.assertTrue(acquired)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(5)

    def test_uninspectable_host_phase_lock_fails_closed(self) -> None:
        from client.spool import SpoolCapacityError, host_phase_busy
        with tempfile.TemporaryDirectory() as tmp:
            phase_dir = self._phase_dir_like(tmp)
            os.chmod(phase_dir, 0o000)
            try:
                with mock.patch.dict(os.environ, {"ENCODINGDB_HOST_PHASE_DIR": phase_dir}):
                    with self.assertRaises(SpoolCapacityError):
                        host_phase_busy()
            finally:
                os.chmod(phase_dir, 0o755)


if __name__ == "__main__":
    unittest.main()
