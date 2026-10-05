#!/usr/bin/env python3
"""Independent, read-only conservation check for one V7 campaign journal.

This intentionally does not import client code. It counts frozen groups,
attempts, finalizable measured records and durable publication identities from
files, then optionally matches an exported read-only server CSV.
"""

import argparse
import csv
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def _json(path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _payload_hash(payload):
    normalized = dict(payload)
    if normalized.get("submissionKind") == "authoritative-artifact-run-v1":
        normalized.pop("artifactPath", None)
        normalized.pop("artifactManaged", None)
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def audit(queue: Path, campaign_id: str, server_csv: Path | None = None):
    root = queue / "campaigns" / campaign_id
    manifest = _json(root / "manifest.json")
    plan = manifest["protocolConfig"]
    groups_planned = len(manifest["tasks"])
    warmup_required = int(plan["warmup_runs"])
    measured_required = int(plan["minimum_measured_runs"])
    adaptive_max = int(plan["max_adaptive_repeats"])
    stability_limit = float(plan["stability_threshold_ratio"])
    issues = []
    by_group = defaultdict(list)
    attempts = {}
    for path in sorted(root.glob("attempt-*.json")):
        try:
            order = int(path.stem.split("-")[1])
            record = _json(path)
            schedule = record["schedule"]
            if (schedule["campaign_id"] != campaign_id
                    or int(schedule["execution_order"]) != order
                    or order in attempts):
                raise ValueError("attempt identity mismatch")
            attempts[order] = record
            by_group[schedule["recipe_id"]].append(record)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            issues.append(f"{path.name}: {exc}")
    if len(by_group) > groups_planned:
        issues.append("more recipe groups in attempts than in frozen plan")

    group_states = Counter()
    eligible_orders = set()
    for recipe, records in by_group.items():
        warmups = [r for r in records if r["schedule"]["phase"] == "warmup"]
        measured = [r for r in records if r["schedule"]["phase"] == "measured"]
        counted = [float(r["timing"]["elapsed_s"]) for r in measured
                   if r.get("countedForStability") and isinstance(r.get("timing"), dict)]
        stable = False
        if len(counted) >= measured_required:
            mean = statistics.fmean(counted)
            stable = mean > 0 and (max(counted) - min(counted)) / mean <= stability_limit
        finished = (len(warmups) >= warmup_required
                    and len(measured) >= measured_required
                    and (stable or len(measured) >= measured_required + adaptive_max))
        group_states["finished" if finished else "unfinished"] += 1
        if finished:
            for record in measured:
                if (record.get("skippedBeforeEncode")
                        or record.get("overallValidity", {}).get("state") == "invalid"
                        or not isinstance(record.get("timing"), dict)
                        or (record.get("metadata", {}).get("info") or {}).get("error")):
                    continue
                eligible_orders.add(int(record["schedule"]["execution_order"]))
    group_states["unstarted"] = max(0, groups_planned - len(by_group))
    if sum(group_states.values()) != groups_planned:
        issues.append("frozen group accounting does not conserve")

    envelopes = {}
    for path in sorted(root.glob("submission-*.json")):
        if path.name.endswith(".accepted.json"):
            continue
        try:
            order = int(path.stem.split("-")[1])
            envelopes[order] = _json(path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            issues.append(f"{path.name}: {exc}")
    markers = {}
    for path in sorted(root.glob("submission-*.accepted.json")):
        try:
            order = int(path.name.split("-")[1].split(".")[0])
            marker = _json(path)
            if int(marker["executionOrder"]) != order or not marker.get("benchmarkRunId"):
                raise ValueError("accepted marker identity mismatch")
            markers[order] = marker
        except (OSError, ValueError, KeyError, TypeError) as exc:
            issues.append(f"{path.name}: {exc}")
    pending_spool = {path.stem for path in queue.glob("*.json") if path.is_file()}
    queue_receipts = {path.stem for path in (queue / "receipts").glob("*.json") if path.is_file()}
    terminal_spool = {path.stem for path in (queue / "terminal").glob("*.json") if path.is_file()}
    publication = Counter()
    marker_ids = {}
    for order in sorted(eligible_orders):
        record = attempts[order]
        info = (record.get("metadata", {}).get("info") or {})
        marker = markers.get(order)
        envelope = envelopes.get(order)
        local_hash = _payload_hash(envelope) if isinstance(envelope, dict) else None
        if marker:
            if marker.get("artifactSha256") != info.get("artifactSha256"):
                issues.append(f"accepted marker {order} artifact hash mismatch")
            marker_ids[str(marker["benchmarkRunId"])] = marker.get("artifactSha256")
            publication["confirmed"] += 1
        elif local_hash and local_hash in queue_receipts:
            publication["receipted_without_journal_marker"] += 1
        elif local_hash and local_hash in terminal_spool:
            publication["terminal"] += 1
        elif local_hash and local_hash in pending_spool:
            publication["queued"] += 1
        elif envelope:
            publication["unstaged_envelope"] += 1
        else:
            publication["journal_only"] += 1
    if len(marker_ids) != publication["confirmed"]:
        issues.append("duplicate server run ID in accepted markers")
    if sum(publication.values()) != len(eligible_orders):
        issues.append("eligible publication identities do not conserve")
    extra_envelopes = set(envelopes) - eligible_orders
    extra_markers = set(markers) - eligible_orders
    if extra_envelopes:
        issues.append(f"{len(extra_envelopes)} envelopes outside eligible finalized attempts")
    if extra_markers:
        issues.append(f"{len(extra_markers)} accepted markers outside eligible finalized attempts")

    server = None
    if server_csv:
        with server_csv.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        server_ids = {row["run_id"]: row for row in rows}
        if len(server_ids) != len(rows):
            issues.append("duplicate run ID in server export")
        for run_id, sha256 in marker_ids.items():
            row = server_ids.get(run_id)
            if row is None:
                issues.append(f"accepted run {run_id} missing from server export")
            elif row.get("artifact_sha256") != sha256:
                issues.append(f"accepted run {run_id} server artifact hash mismatch")
        server = {"rows": len(rows), "matchedAcceptedMarkers": len(set(server_ids) & set(marker_ids)),
                  "serverRowsWithoutLocalMarker": len(set(server_ids) - set(marker_ids)),
                  "disposition": dict(Counter((row["run_status"], row["artifact_state"], row["analysis_status"])
                                              for row in rows))}
        server["disposition"] = {"/".join(key): value for key, value in server["disposition"].items()}

    validity = Counter(r.get("overallValidity", {}).get("state", "unknown")
                       for r in attempts.values())
    return {
        "campaignId": campaign_id,
        "frozenGroups": groups_planned,
        "groups": dict(group_states),
        "attempts": {"total": len(attempts),
                     "warmup": sum(r["schedule"]["phase"] == "warmup" for r in attempts.values()),
                     "measured": sum(r["schedule"]["phase"] == "measured" for r in attempts.values()),
                     "validity": dict(validity),
                     "skippedBeforeEncode": sum(bool(r.get("skippedBeforeEncode"))
                                                for r in attempts.values())},
        "requiredMeasured": groups_planned * measured_required,
        "eligibleFinalized": len(eligible_orders),
        "publication": dict(publication),
        "server": server,
        "issues": issues,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-dir", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--server-csv", type=Path)
    args = parser.parse_args()
    report = audit(args.queue_dir, args.campaign_id, args.server_csv)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
