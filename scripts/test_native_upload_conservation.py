"""Acceptance failures must include work that has never produced a receipt."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verifier = load("native-upload-conservation")
snapshotter = load("native-queue-snapshot")
server_collector = load("native-server-evidence")
ack = verifier.ack


def fixture(groups=1, measured=2, confirmed=None):
    confirmed = measured if confirmed is None else confirmed
    campaign = "campaign-0123456789abcdef"
    prefix = "campaigns/" + campaign + "/"
    files, artifacts, servers = {}, {}, []

    def add(name, value):
        files[name] = {"value": value, "sha256": "a" * 64}

    add(prefix + "manifest.json", {"protocolConfig": {"minimum_measured_runs": 2, "warmup_runs": 1},
                                 "tasks": [{"clipId": "clip-" + str(i), "encoder": "libx264", "preset": "fast", "crf": 22} for i in range(groups)]})
    add(prefix + "campaign-complete.json", {"failed": 0, "skipped": 0})
    for order in range(1, groups + measured + 1):
        warmup = order <= groups
        idx = (order - 1) if warmup else order - groups - 1
        recipe = "clip-" + str(idx % groups) + "|libx264|fast|22"
        repetition = 1 if warmup else idx // groups + 1
        sha = f"{order:064x}"
        path = "/owned/" + str(order) + ".mp4"
        record = {"schedule": {"campaign_id": campaign, "execution_order": order,
                  "phase": "warmup" if warmup else "measured", "recipe_id": recipe,
                  "repetition_index": repetition}, "overallValidity": {"state": "valid", "reasons": []},
                  "metadata": {"info": {"artifactPath": path, "artifactSha256": sha}},
                  "timing": {"elapsed_s": 1}, "skippedBeforeEncode": False}
        add(prefix + f"attempt-{order:06d}.json", record)
        if warmup:
            continue
        create = {"campaignId": campaign, "repetitionGroupId": campaign + ":" + recipe,
                  "repetitionIndex": repetition, "artifact": {"sha256": sha, "byteSize": 4, "role": "ENCODED"}}
        create["payloadHash"] = ack.build_payload_hash(create)
        envelope = {"submissionKind": ack.AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND, "artifactPath": path,
                    "artifactSha256": sha, "artifactByteSize": 4, "runCreate": create}
        add(prefix + f"submission-{order:06d}.json", envelope)
        local_hash = ack.local_payload_hash(envelope)
        if idx >= confirmed:
            add(local_hash + ".json", {"localHash": local_hash, "payload": envelope,
                                       "lastError": "run create failed (503)", "attempts": 1, "nextAttemptAt": 100})
            artifacts[path] = {"state": "present", "sha256": sha, "byteSize": 4}
            continue
        run, artifact = "run-" + str(order), "artifact-" + str(order)
        response = {"benchmarkRun": {"id": run, "payloadHash": create["payloadHash"], "status": "PENDING"},
                    "artifact": {"id": artifact, "benchmarkRunId": run, "role": "ENCODED",
                                 "sha256": sha, "byteSize": 4, "storageState": "RETAINED"}, "analyses": []}
        proof = ack.validate_upload_response(envelope, response)
        add("receipts/" + local_hash + ".json", {"schemaVersion": 2, "localHash": local_hash,
            "payloadIdentity": ack.local_hash_material(envelope), "response": response,
            "status": "uploaded_analysis_pending", "acknowledgment": proof})
        servers.append({"benchmarkRunId": run, "artifactId": artifact, "payloadHash": create["payloadHash"],
                        "artifactSha256": sha, "artifactByteSize": 4, "artifactStorageState": "RETAINED",
                        "benchmarkRunStatus": "PENDING", "analyses": []})
    return {"files": files, "artifacts": artifacts, "errors": [], "queue": "/owned", "capturedAt": "fixture"}, servers


class ConservationTests(unittest.TestCase):
    def test_1042_inventory_detects_unreceipted_valid_work(self):
        for groups, measured, confirmed, missing in [(112, 284, 150, 134), (126, 282, 280, 2), (126, 264, 264, 0), (98, 212, 212, 0)]:
            with self.subTest(groups=groups, measured=measured):
                snapshot, server = fixture(groups, measured, confirmed)
                result = verifier.verify(snapshot, server)
                self.assertEqual(result["attempts"], groups + measured)
                self.assertEqual(result["confirmed"], confirmed)
                self.assertEqual(result["unresolved"], missing)
                self.assertEqual(result["passed"], missing == 0)
                self.assertTrue(all(r.get("retainedBytesVerified") for r in result["rows"] if r["disposition"] == "queued-unresolved"))

    def test_optional_adaptive_measurement_is_still_required_to_upload(self):
        snapshot, servers = fixture(measured=3, confirmed=2)
        result = verifier.verify(snapshot, servers)
        self.assertFalse(result["passed"])
        optional = result["rows"][-1]
        self.assertFalse(optional["required"])
        self.assertEqual(optional["disposition"], "queued-unresolved")

    def test_warmup_count_cannot_replace_required_repetition_identity(self):
        snapshot, servers = fixture()
        record = next(v["value"] for n, v in snapshot["files"].items() if n.endswith("attempt-000001.json"))
        record["schedule"]["repetition_index"] = 2
        result = verifier.verify(snapshot, servers)
        self.assertFalse(result["passed"])
        self.assertTrue(any(e["error"] == "missing required repetition identity" for e in result["errors"]))

    def test_adaptive_measurement_cannot_replace_a_missing_required_member(self):
        snapshot, servers = fixture(measured=3)
        envelope_name = next(n for n in snapshot["files"] if n.endswith("submission-000002.json"))
        envelope = snapshot["files"].pop(envelope_name)["value"]
        attempt_name = next(n for n in snapshot["files"] if n.endswith("attempt-000002.json"))
        del snapshot["files"][attempt_name]
        del snapshot["files"]["receipts/" + ack.local_payload_hash(envelope) + ".json"]
        servers = [s for s in servers if s["payloadHash"] != envelope["runCreate"]["payloadHash"]]
        result = verifier.verify(snapshot, servers)
        self.assertEqual(result["confirmed"], 2)
        self.assertFalse(result["passed"])
        self.assertTrue(any(e["error"] == "missing required repetition identity" for e in result["errors"]))

    def test_terminal_and_missing_bytes_cannot_turn_into_success(self):
        snapshot, servers = fixture(confirmed=1)
        pending = next(n for n in snapshot["files"] if "/" not in n)
        snapshot["files"]["terminal/" + pending] = snapshot["files"].pop(pending)
        snapshot["artifacts"] = {}
        result = verifier.verify(snapshot, servers)
        self.assertFalse(result["passed"])
        self.assertEqual(result["rows"][-1]["disposition"], "terminal-unresolved")
        self.assertIn("unacknowledged bytes unavailable or mismatched", result["rows"][-1]["errors"])

    def test_invalid_measured_is_explicitly_excluded_but_unknown_is_not(self):
        snapshot, servers = fixture(confirmed=1)
        attempt = next(n for n in snapshot["files"] if n.endswith("attempt-000003.json"))
        env = next(n for n in snapshot["files"] if n.endswith("submission-000003.json"))
        pending = next(n for n in snapshot["files"] if "/" not in n)
        del snapshot["files"][env], snapshot["files"][pending]
        record = snapshot["files"][attempt]["value"]
        record["overallValidity"] = {"state": "invalid", "reasons": ["structural mismatch"]}
        self.assertTrue(verifier.verify(snapshot, servers)["passed"])
        for state in ("unknown", "", None):
            record["overallValidity"]["state"] = state
            self.assertFalse(verifier.verify(snapshot, servers)["passed"])

    def test_missing_current_server_evidence_is_not_native_acceptance(self):
        snapshot, servers = fixture()
        result = verifier.verify(snapshot)
        self.assertTrue(result["localConservationPassed"])
        self.assertFalse(result["passed"])
        self.assertFalse(verifier.verify(snapshot, servers[:1])["passed"])

    def test_foreign_server_identity_fails_even_with_equal_artifact_bytes(self):
        snapshot, servers = fixture()
        servers[0]["benchmarkRunId"] = "foreign"
        self.assertFalse(verifier.verify(snapshot, servers)["passed"])

    def test_duplicate_receipt_and_server_binding_fail(self):
        snapshot, servers = fixture()
        receipt_name = next(n for n in snapshot["files"] if n.startswith("receipts/"))
        snapshot["files"]["receipts/" + "b" * 64 + ".json"] = copy.deepcopy(snapshot["files"][receipt_name])
        self.assertFalse(verifier.verify(snapshot, servers)["passed"])
        snapshot, servers = fixture()
        servers.append(copy.deepcopy(servers[0]))
        self.assertFalse(verifier.verify(snapshot, servers)["passed"])

    def test_retired_envelope_uses_receipt_identity_without_fabricating_bytes(self):
        snapshot, servers = fixture()
        for name in list(snapshot["files"]):
            if "/submission-" in name:
                del snapshot["files"][name]
        self.assertTrue(verifier.verify(snapshot, servers)["passed"])

    def test_unmatched_pending_entry_cannot_hide_behind_good_receipts(self):
        snapshot, servers = fixture()
        snapshot["files"]["f" * 64 + ".json"] = {"value": {"localHash": "f" * 64, "payload": {}}, "sha256": "a" * 64}
        self.assertFalse(verifier.verify(snapshot, servers)["passed"])

    def test_malformed_attempt_and_unreadable_evidence_fail_closed(self):
        snapshot, servers = fixture()
        name = next(n for n in snapshot["files"] if "/attempt-" in n)
        snapshot["files"][name]["value"]["schedule"]["execution_order"] = True
        self.assertFalse(verifier.verify(snapshot, servers)["passed"])
        snapshot, servers = fixture()
        snapshot["errors"].append({"path": "attempt-bad.json", "error": "invalid JSON"})
        self.assertFalse(verifier.verify(snapshot, servers)["passed"])

    def test_unknown_plan_member_and_malformed_receipt_fail_closed(self):
        snapshot, servers = fixture()
        manifest = next(v["value"] for n, v in snapshot["files"].items() if n.endswith("manifest.json"))
        manifest["tasks"][0]["clipId"] = "foreign"
        self.assertFalse(verifier.verify(snapshot, servers)["passed"])
        snapshot, servers = fixture()
        receipt = next(v["value"] for n, v in snapshot["files"].items() if n.startswith("receipts/"))
        receipt["payloadIdentity"] = []
        self.assertFalse(verifier.verify(snapshot, servers)["passed"])

    def test_malformed_timing_cannot_certify_measured_data(self):
        for elapsed in (None, True, -1, 0, float("nan"), float("inf")):
            snapshot, servers = fixture()
            attempt = next(v["value"] for n, v in snapshot["files"].items() if n.endswith("attempt-000002.json"))
            attempt["timing"]["elapsed_s"] = elapsed
            self.assertFalse(verifier.verify(snapshot, servers)["passed"])

    def test_snapshot_is_read_only_and_includes_pending_root_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / ("a" * 64 + ".json")
            path.write_text('{"lastError":"503"}')
            before = path.read_bytes()
            result = snapshotter.capture(root)
            self.assertIn(path.name, result["files"])
            self.assertEqual(path.read_bytes(), before)
            (root / "bad.json").write_text("{")
            self.assertEqual(len(snapshotter.capture(root)["errors"]), 1)

    def test_server_collection_refuses_nonisolated_or_credentialed_origins(self):
        for base in ("http://127.0.0.1:3094", "https://example.com", "https://secret@127.0.0.1:3094", "https://127.0.0.1:3094/other"):
            with self.subTest(base=base), self.assertRaisesRegex(ValueError, "isolated"):
                server_collector.collect({}, base, "/not-read")

    def test_server_collection_preserves_progress_and_honors_rate_limit(self):
        snapshot = {"files": {"receipts/example.json": {"value": {"acknowledgment": {"benchmarkRunId": "run-a"}}}}}
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"benchmarkRunId":"run-a"}'
        limited = server_collector.urllib.error.HTTPError("https://127.0.0.1:3094", 429, "limited", {"Retry-After": "2"}, None)
        opener = mock.Mock()
        opener.open.side_effect = [limited, response]
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.object(server_collector.ssl, "create_default_context"), \
                mock.patch.object(server_collector.urllib.request, "build_opener", return_value=opener), \
                mock.patch.object(server_collector.time, "sleep") as sleep:
            first = server_collector.collect(snapshot, "https://127.0.0.1:3094", "/fixture-ca", temp)
            self.assertEqual(opener.open.call_count, 2)
            self.assertEqual(sleep.call_args_list, [mock.call(2.0), mock.call(1.0)])
            second = server_collector.collect(snapshot, "https://127.0.0.1:3094", "/fixture-ca", temp)
            self.assertEqual(second, first)
            self.assertEqual(opener.open.call_count, 2)
            with self.assertRaisesRegex(ValueError, "Malformed cached"):
                server_collector.collect(snapshot, "https://127.0.0.1:3199", "/fixture-ca", temp)


if __name__ == "__main__":
    unittest.main()
