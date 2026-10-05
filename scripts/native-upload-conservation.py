#!/usr/bin/env python3
"""Fail closed unless every valid measured attempt has an exact bound receipt.

Optional current server evidence is a JSON list of analysis-status endpoint
responses. Scientific acceptance is reported separately from upload confirmation.
This verifier never repairs, replays, encodes or changes a queue.
"""
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from client import acknowledgments as ack
from client.recipe import canonical_json


def verify(snapshot, server_evidence=None):
    errors = list(snapshot.get("errors") or [])
    rows = []
    files = {name: item["value"] for name, item in snapshot["files"].items()}
    artifacts = snapshot["artifacts"]
    receipts = {PurePosixPath(name).stem: value for name, value in files.items()
                if name.startswith("receipts/")}
    receipt_by_attempt = defaultdict(list)
    for local_hash, receipt in receipts.items():
        identity = receipt.get("payloadIdentity") or {}
        create = identity.get("runCreate") if isinstance(identity, dict) else None
        if not isinstance(create, dict):
            errors.append({"receipt": local_hash, "error": "receipt has malformed identity"})
            continue
        receipt_by_attempt[(create.get("campaignId"), create.get("repetitionGroupId"),
                            create.get("repetitionIndex"))].append((local_hash, identity))
    servers = defaultdict(list)
    for value in server_evidence or []:
        if not isinstance(value, dict):
            errors.append({"error": "malformed server evidence"})
            continue
        servers[value.get("payloadHash")].append(value)
    used_receipts, server_runs, used_envelopes, attempt_hashes = {}, {}, set(), set()
    campaigns = sorted({PurePosixPath(name).parts[1] for name in files
                        if name.startswith("campaigns/") and len(PurePosixPath(name).parts) >= 3})
    for campaign in campaigns:
        root = "campaigns/" + campaign + "/"
        manifest = files.get(root + "manifest.json")
        if not isinstance(manifest, dict):
            errors.append({"campaign": campaign, "error": "missing manifest"})
            continue
        config = manifest.get("protocolConfig") or {}
        if not isinstance(config, dict):
            errors.append({"campaign": campaign, "error": "malformed repetition policy"})
            continue
        minimum = config.get("minimum_measured_runs")
        warmup_minimum = config.get("warmup_runs")
        if type(minimum) is not int or minimum < 1 or type(warmup_minimum) is not int or warmup_minimum < 0:
            errors.append({"campaign": campaign, "error": "unknown repetition policy"})
            continue
        attempts = [(name, value) for name, value in files.items()
                    if name.startswith(root) and re.fullmatch(r"attempt-\d+\.json", PurePosixPath(name).name)]
        if not attempts:
            errors.append({"campaign": campaign, "error": "no attempt records"})
        groups = defaultdict(Counter)
        repetitions = defaultdict(lambda: defaultdict(set))
        identities = set()
        planned = manifest.get("tasks")
        planned_recipes = []
        try:
            if not isinstance(planned, list) or not planned:
                raise ValueError("missing frozen tasks")
            for task in planned:
                rate = task.get("rateControl")
                quality = canonical_json(rate) if rate else str(task.get("crf") if task.get("crf") is not None else "none")
                parts = [task.get("clipId"), task.get("encoder"), task.get("preset"), quality]
                if any(not isinstance(part, str) or not part for part in parts):
                    raise ValueError("malformed frozen task")
                planned_recipes.append("|".join(parts))
            if len(set(planned_recipes)) != len(planned_recipes):
                raise ValueError("duplicate frozen task")
        except (AttributeError, TypeError, ValueError) as exc:
            errors.append({"campaign": campaign, "error": str(exc)})
        for name, attempt in sorted(attempts):
            row = {"campaign": campaign, "attempt": PurePosixPath(name).name,
                   "disposition": "malformed-evidence", "errors": []}
            rows.append(row)
            try:
                schedule = attempt["schedule"]
                order = schedule["execution_order"]
                phase, recipe, repetition = schedule["phase"], schedule["recipe_id"], schedule["repetition_index"]
                if (type(order) is not int or order < 1 or row["attempt"] != f"attempt-{order:06d}.json"
                        or schedule["campaign_id"] != campaign or phase not in ("warmup", "measured")
                        or not isinstance(recipe, str) or not recipe or type(repetition) is not int or repetition < 1):
                    raise ValueError("invalid attempt identity")
                identity = (recipe, phase, repetition)
                if identity in identities:
                    raise ValueError("duplicate attempt identity")
                identities.add(identity)
                groups[recipe][phase] += 1
                repetitions[recipe][phase].add(repetition)
                if recipe not in planned_recipes:
                    raise ValueError("attempt recipe is outside frozen plan")
                row.update(order=order, phase=phase, recipe=recipe, repetition=repetition,
                           required=(phase == "measured" and repetition <= minimum))
                validity = attempt["overallValidity"]
                state = validity["state"]
                if state not in ("valid", "suspect", "invalid") or not isinstance(validity.get("reasons"), list):
                    raise ValueError("unknown attempt validity")
                info = attempt.get("metadata", {}).get("info", {})
                if state == "invalid":
                    if not validity["reasons"]:
                        raise ValueError("invalid attempt lacks reasons")
                    row.update(disposition="invalid-measurement", reasons=validity["reasons"])
                    continue
                if attempt.get("skippedBeforeEncode") or info.get("error"):
                    raise ValueError("valid attempt claims skipped/error execution")
                if phase == "warmup":
                    row["disposition"] = "warmup"
                    continue
                if not isinstance(attempt.get("timing"), dict):
                    raise ValueError("measured attempt lacks timing")
                elapsed = attempt["timing"].get("elapsed_s")
                if (type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed <= 0):
                    raise ValueError("measured attempt timing is not positive and finite")
                envelope = files.get(root + f"submission-{order:06d}.json")
                used_envelopes.add(root + f"submission-{order:06d}.json")
                group_id = campaign + ":" + recipe
                matches = receipt_by_attempt[(campaign, group_id, repetition)]
                if envelope is None:
                    if len(matches) != 1:
                        raise ValueError("missing envelope and no unique receipt identity")
                    _, envelope = matches[0]
                expected = ack.expected_upload_identity(envelope)
                if expected is None:
                    raise ValueError("invalid immutable envelope identity")
                create = envelope["runCreate"]
                if (create.get("campaignId") != campaign or create.get("repetitionGroupId") != group_id
                        or create.get("repetitionIndex") != repetition
                        or envelope.get("artifactSha256") != info.get("artifactSha256")):
                    raise ValueError("envelope does not bind attempt")
                local_hash = ack.local_payload_hash(envelope)
                if local_hash in attempt_hashes:
                    raise ValueError("payload identity reused by another attempt")
                attempt_hashes.add(local_hash)
                row.update(localHash=local_hash, payloadHash=expected["payloadHash"],
                           artifactSha256=expected["sha256"])
                if len(matches) > 1 or (matches and matches[0][0] != local_hash):
                    raise ValueError("duplicate or foreign receipt for attempt")
                marker = files.get(root + f"submission-{order:06d}.accepted.json")
                if marker is not None:
                    verdict = ack.journal_marker_verdict(marker, execution_order=order, recipe_id=recipe,
                        artifact_path=info.get("artifactPath", ""), artifact_sha256=info.get("artifactSha256", ""), payload=envelope)
                    if verdict != "verified":
                        row["errors"].append("unverified journal marker: " + verdict)
                receipt = receipts.get(local_hash)
                if receipt is not None:
                    verdict = ack.receipt_verdict(local_hash, receipt, envelope)
                    if verdict != "verified":
                        raise ValueError("unverified receipt: " + verdict)
                    if local_hash in used_receipts:
                        raise ValueError("receipt reused by another attempt")
                    used_receipts[local_hash] = name
                    proof = receipt["acknowledgment"]
                    run_id = proof["benchmarkRunId"]
                    if run_id in server_runs:
                        raise ValueError("server run reused by another attempt")
                    server_runs[run_id] = name
                    row.update(disposition="upload-confirmed", runId=run_id, artifactId=proof["artifactId"],
                               analysisAcceptedAtReceipt=proof["analysisAccepted"])
                    if server_evidence is not None:
                        responses = servers[expected["payloadHash"]]
                        if len(responses) != 1:
                            raise ValueError("missing or duplicate current server evidence")
                        retained = ack.validate_retention_response(envelope, proof, responses[0])
                        if retained is None:
                            raise ValueError("current server identity/retention mismatch")
                        row.update(serverRetentionVerified=True, analysisAccepted=retained["analysisAccepted"],
                                   analysisStatuses=[item.get("status") for item in responses[0].get("analyses", [])
                                       if isinstance(item, dict) and item.get("benchmarkRunId") == run_id
                                       and item.get("artifactId") == proof["artifactId"]])
                    continue
                pending = files.get(local_hash + ".json")
                terminal = files.get("terminal/" + local_hash + ".json")
                dead = [(n, d) for n, d in files.items()
                        if n.startswith("dead-letter/") and n.endswith("-" + local_hash + ".json")]
                entry = pending or terminal or (dead[0][1] if len(dead) == 1 else None)
                row["disposition"] = "retained-unsubmitted" if entry is None else (
                    "terminal-unresolved" if terminal or dead or entry.get("terminal") else "queued-unresolved")
                payload = (entry or {}).get("payload") or envelope
                if entry and (entry.get("localHash") != local_hash or ack.local_payload_hash(payload) != local_hash):
                    raise ValueError("queue identity mismatch")
                candidates = [artifacts.get(payload.get("artifactPath")), artifacts.get(info.get("artifactPath"))]
                retained = any(a and a.get("state") == "present" and a.get("sha256") == expected["sha256"]
                               and a.get("byteSize") == expected["byteSize"] for a in candidates)
                row.update(retainedBytesVerified=retained, lastError=(entry or {}).get("lastError"),
                           attempts=(entry or {}).get("attempts"), nextAttemptAt=(entry or {}).get("nextAttemptAt"))
                if not retained:
                    row["errors"].append("unacknowledged bytes unavailable or mismatched")
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                row["errors"].append(str(exc))
        for recipe, counts in groups.items():
            if counts["measured"] < minimum or counts["warmup"] < warmup_minimum:
                errors.append({"campaign": campaign, "recipe": recipe, "error": "incomplete measurement group"})
            if (not set(range(1, minimum + 1)) <= repetitions[recipe]["measured"]
                    or not set(range(1, warmup_minimum + 1)) <= repetitions[recipe]["warmup"]):
                errors.append({"campaign": campaign, "recipe": recipe, "error": "missing required repetition identity"})
        if set(planned_recipes) != set(groups):
            errors.append({"campaign": campaign, "error": "attempt groups differ from frozen plan"})
    if not campaigns:
        errors.append({"error": "no campaigns"})
    for local_hash in sorted(set(receipts) - set(used_receipts)):
        errors.append({"receipt": local_hash, "error": "receipt has no unique measured attempt"})
    for name in files:
        if re.fullmatch(r"submission-\d+\.json", PurePosixPath(name).name) and name not in used_envelopes:
            errors.append({"path": name, "error": "envelope has no eligible measured attempt"})
        if "/" not in name or name.startswith("terminal/") or name.startswith("dead-letter/"):
            value = files[name]
            local_hash = value.get("localHash")
            payload = value.get("payload")
            if (local_hash not in attempt_hashes or not isinstance(payload, dict)
                    or ack.local_payload_hash(payload) != local_hash):
                errors.append({"path": name, "error": "queue/terminal evidence has no bound measured attempt"})
    unresolved = [r for r in rows if r["disposition"] not in ("warmup", "invalid-measurement", "upload-confirmed") or r["errors"]]
    return {"kind": "native-upload-conservation-v1", "capturedAt": snapshot.get("capturedAt"),
            "queue": snapshot.get("queue"), "passed": server_evidence is not None and not errors and not unresolved,
            "localConservationPassed": not errors and not unresolved,
            "serverEvidenceProvided": server_evidence is not None,
            "counts": dict(Counter(r["disposition"] for r in rows)), "attempts": len(rows),
            "confirmed": sum(r["disposition"] == "upload-confirmed" and not r["errors"] for r in rows),
            "unresolved": len(unresolved), "errors": errors, "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--server-evidence", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = verify(json.loads(args.snapshot.read_text()),
                    json.loads(args.server_evidence.read_text()) if args.server_evidence else None)
    with args.out.open("x") as output:
        json.dump(result, output, indent=2)
        output.write("\n")
    print(json.dumps({key: result[key] for key in ("passed", "attempts", "counts", "confirmed", "unresolved")}))
    sys.exit(0 if result["passed"] else 1)
