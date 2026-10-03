"""Regressions for the final review's receipt and marker identity bypasses."""
import json
import pytest
from client import acknowledgments as ack, main, spool
from client.campaign import atomic_json
from test_acknowledgment_retirement import _submission_payload, _record_for
from test_spool import server_bundle


def test_receipt_without_local_identity_cannot_retire_foreign_payload(tmp_path):
    campaign = "campaign-000000000000001f"
    root = tmp_path / "campaigns" / campaign
    root.mkdir(parents=True)
    payload = _submission_payload(root, payload_hash="a" * 64, campaign_id=campaign)
    foreign = _submission_payload(tmp_path, name="foreign.mp4", payload_hash="b" * 64,
                                  campaign_id="campaign-000000000000001e")
    response = server_bundle(foreign, "foreign-run")
    local_hash = spool.local_hash_for_payload(payload)
    receipt = {"localHash": local_hash, "status": "uploaded_analysis_pending",
               "response": response, "acknowledgment": ack.validate_upload_response(foreign, response)}
    queue = tmp_path / "queue"
    atomic_json(queue / "receipts" / (local_hash + ".json"), receipt)
    assert ack.receipt_verdict(local_hash, receipt, None) != "verified"
    artifact = __import__("pathlib").Path(payload["artifactPath"])
    record = _record_for(campaign, artifact)
    main._retire_uploaded_artifact(root, record, payload["artifactSha256"], "foreign-run",
                                   queue_dir=str(queue), payload=payload)
    assert artifact.exists()
    assert json.loads((root / "submission-000001.accepted.json").read_text())["uploadConfirmed"] is False


@pytest.mark.parametrize("bad_id", [{"bad": 1}, ["bad"], True, 1])
def test_response_rejects_coerced_identifiers(tmp_path, bad_id):
    payload = _submission_payload(tmp_path, payload_hash="a" * 64)
    response = server_bundle(payload, "own-run")
    response["benchmarkRun"]["id"] = bad_id
    response["artifact"]["benchmarkRunId"] = bad_id
    assert ack.validate_upload_response(payload, response) is None


@pytest.mark.parametrize("run_status,foreign", [("PENDING", False), ("SUSPECT", False),
                                                ("ACCEPTED", True)])
def test_analysis_acceptance_requires_same_accepted_run_and_artifact(tmp_path, run_status, foreign):
    payload = _submission_payload(tmp_path, payload_hash="a" * 64)
    response = server_bundle(payload, "own-run")
    response["benchmarkRun"]["status"] = run_status
    response["analyses"] = [{"id": "analysis", "metricModelId": "model", "status": "COMPLETE",
                             "benchmarkRunId": "foreign" if foreign else "own-run",
                             "artifactId": "foreign" if foreign else response["artifact"]["id"]}]
    evidence = ack.validate_upload_response(payload, response)
    assert evidence["uploadConfirmed"] is True
    assert evidence["analysisAccepted"] is False
    response["benchmarkRun"]["status"] = "ACCEPTED"
    response["analyses"][0].update(benchmarkRunId="own-run", artifactId=response["artifact"]["id"])
    assert ack.validate_upload_response(payload, response)["analysisAccepted"] is True


def test_bare_marker_never_shortcuts_saved_publication(tmp_path):
    root = tmp_path / "campaigns" / "campaign-000000000000001f"
    root.mkdir(parents=True)
    payload = _submission_payload(root, payload_hash="a" * 64, campaign_id=root.name)
    envelope = root / "submission-000001.json"
    atomic_json(envelope, payload)
    marker = {"schemaVersion": 2, "executionOrder": 1, "recipeId": "recipe-1",
              "artifactPath": payload["artifactPath"], "artifactSha256": payload["artifactSha256"],
              "payloadHash": payload["runCreate"]["payloadHash"], "artifactByteSize": payload["artifactByteSize"],
              "benchmarkRunId": "invented", "artifactId": "invented", "uploadConfirmed": True}
    atomic_json(root / "submission-000001.accepted.json", marker)
    assert main._journal_marker_state(envelope)[0] != "verified"
    marker.update(schemaVersion=2.0, executionOrder=1.0)
    assert ack.journal_marker_verdict(marker, execution_order=1, recipe_id="recipe-1",
             artifact_path=payload["artifactPath"], artifact_sha256=payload["artifactSha256"]) != "verified"


def test_historical_markers_do_not_count_as_confirmed_upload_groups(tmp_path):
    import dataclasses
    from client import campaign, protocol
    campaign_id = "campaign-000000000000001f"
    root = tmp_path / "campaigns" / campaign_id
    root.mkdir(parents=True)
    artifacts = [root / "one.mp4", root / "two.mp4"]
    for artifact in artifacts:
        artifact.write_bytes(b"completed measured output")
    first = _record_for(campaign_id, artifacts[0])
    second = dataclasses.replace(_record_for(campaign_id, artifacts[1]),
                schedule=dataclasses.replace(first.schedule, execution_order=2, repetition_index=2))
    config = protocol.ProtocolConfig.for_version("7.1", max_adaptive_repeats=0)
    manifest = {"protocolVersion": "7.1", "seed": 1,
                "protocolConfig": dataclasses.asdict(config), "tasks": []}
    journal = campaign.CampaignJournal(str(tmp_path), campaign_id, manifest, 2048)
    journal.records = {1: first, 2: second}
    for record in (first, second):
        atomic_json(root / f"submission-{record.schedule.execution_order:06d}.accepted.json", {
            "schemaVersion": 1, "executionOrder": record.schedule.execution_order,
            "recipeId": record.schedule.recipe_id,
            "artifactPath": record.metadata["info"]["artifactPath"],
            "artifactSha256": record.metadata["info"]["artifactSha256"],
            "benchmarkRunId": f"historical-{record.schedule.execution_order}"})
    ledger = main._durable_campaign_ledger(str(tmp_path), campaign_id, journal, False)
    assert ledger["awaitingReconciliation"] == 2
    assert ledger["uploaded"] == ledger["groupsConfirmed"] == 0
