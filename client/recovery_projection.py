"""Read-only projection of durable attempt journals for normal recovery UI."""

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Dict

from . import acknowledgments
from .campaign import load_record
from .protocol import (
    EnvironmentThresholds,
    ProtocolConfig,
    RecipeSpec,
    StructuralExpectation,
    StructuralTolerance,
    campaign_result_from_records,
)


def protocol_config_from_manifest(manifest: Dict[str, Any]) -> ProtocolConfig:
    saved = dict(manifest.get("protocolConfig") or {})
    return ProtocolConfig(
        version=str(saved.get("version") or manifest.get("protocolVersion") or ""),
        warmup_runs=int(saved.get("warmup_runs", 1)),
        minimum_measured_runs=int(saved.get("minimum_measured_runs", 2)),
        stability_threshold_ratio=float(saved.get("stability_threshold_ratio", 0.03)),
        max_adaptive_repeats=int(saved.get("max_adaptive_repeats", 2)),
        environment=EnvironmentThresholds(**dict(saved.get("environment") or {})),
        structural_tolerance=StructuralTolerance(**dict(saved.get("structural_tolerance") or {})),
    )


def project_attempt_groups(root: Path, campaign_id: str) -> Dict[str, Any]:
    """Find finalizable groups without changing a journal or requiring FFmpeg.

    A damaged attempt is reported and skipped individually. This projection
    only identifies candidate evidence: publication still verifies exact
    retained bytes and provenance before creating an immutable envelope.
    """
    result: Dict[str, Any] = {
        "plannedGroups": 0,
        "attempts": 0,
        "finishedGroupIds": [],
        "historicalOrders": [],
        "acceptedOrders": [],
        "candidateOrders": [],
        "unavailableOrders": [],
        "incompleteGroupIds": [],
        "corruptEntries": [],
        "failure": None,
    }
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest is not an object")
        config = protocol_config_from_manifest(manifest)
        if config.version not in ("7.0", "7.1"):
            raise ValueError("unsupported saved protocol")
        if config.warmup_runs < 0 or config.minimum_measured_runs < 1 or config.max_adaptive_repeats < 0:
            raise ValueError("invalid saved repetition plan")
        result["plannedGroups"] = len(manifest.get("tasks") or [])
    except (OSError, ValueError, TypeError, KeyError) as exc:
        result["failure"] = f"saved plan cannot be read: {exc}"[:200]
        return result

    records = {}
    for path in sorted(root.glob("attempt-*.json")):
        try:
            order = int(path.stem.removeprefix("attempt-"))
            record = load_record(json.loads(path.read_text(encoding="utf-8")))
            if (record.schedule.campaign_id != campaign_id
                    or record.schedule.execution_order != order
                    or order in records
                    or record.schedule.phase not in ("warmup", "measured")
                    or not record.schedule.recipe_id
                    or not isinstance(record.metadata, dict)):
                raise ValueError("attempt identity or phase mismatch")
            if record.timing is not None:
                elapsed = float(record.timing.elapsed_s)
                if not math.isfinite(elapsed) or elapsed <= 0:
                    raise ValueError("attempt timing is not positive and finite")
            records[order] = record
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            result["corruptEntries"].append({"path": path.name, "reason": str(exc)[:120]})
    result["attempts"] = len(records)
    recipe_ids = sorted({record.schedule.recipe_id for record in records.values()})
    if not recipe_ids:
        return result
    if result["plannedGroups"] and len(recipe_ids) > result["plannedGroups"]:
        result["failure"] = "saved attempts contain more groups than the frozen plan"
    try:
        projected = campaign_result_from_records(
            campaign_id=campaign_id,
            config=config,
            seed=int(manifest.get("seed") or 0),
            recipes=[RecipeSpec(recipe_id=recipe_id, expectation=StructuralExpectation())
                     for recipe_id in recipe_ids],
            records=records,
        )
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        result["failure"] = f"saved attempt groups cannot be projected: {exc}"[:200]
        return result
    root_resolved = root.resolve()
    for recipe in projected.recipe_results:
        phase_counts = Counter(record.schedule.phase for record in recipe.runs)
        if (recipe.recipe_id in projected.unfinished_recipes
                or phase_counts["warmup"] < config.warmup_runs
                or phase_counts["measured"] < config.minimum_measured_runs):
            result["incompleteGroupIds"].append(recipe.recipe_id)
            continue
        result["finishedGroupIds"].append(recipe.recipe_id)
        for record in recipe.runs:
            if record.schedule.phase != "measured" or record.skipped_before_encode:
                continue
            info = record.metadata.get("info") or {}
            if not isinstance(info, dict):
                result["corruptEntries"].append({
                    "path": f"attempt-{record.schedule.execution_order:06d}.json",
                    "reason": "attempt info is not an object",
                })
                continue
            if (record.timing is None or record.overall_validity.state == "invalid"
                    or info.get("error")):
                continue
            order = record.schedule.execution_order
            receipt_path = root / f"submission-{order:06d}.accepted.json"
            if receipt_path.is_file():
                try:
                    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                    envelope_payload_hash = None
                    envelope = None
                    if isinstance(receipt, dict) and receipt.get("schemaVersion") == 2:
                        try:
                            envelope = json.loads((root / f"submission-{order:06d}.json").read_text(encoding="utf-8"))
                            if isinstance(envelope, dict) and isinstance(envelope.get("runCreate"), dict):
                                candidate = str(envelope["runCreate"].get("payloadHash") or "").strip().lower()
                                envelope_payload_hash = candidate or None
                        except (OSError, ValueError):
                            envelope_payload_hash = None
                    verdict = acknowledgments.journal_marker_verdict(
                            receipt, execution_order=order, recipe_id=recipe.recipe_id,
                            artifact_path=str(info.get("artifactPath") or ""),
                            artifact_sha256=str(info.get("artifactSha256") or ""),
                            payload_hash=envelope_payload_hash, payload=envelope)
                    if verdict == "verified":
                        result["acceptedOrders"].append(order)
                        continue
                    if verdict == "historical":
                        # F4: v1 provenance keeps the attempt readable and
                        # its identity intact, but it is NOT a fresh verified
                        # acknowledgment. The attempt stays publishable (the
                        # normal byte/receipt path reconciles it, or the
                        # metadata-only retention check upgrades the marker
                        # before staging) and it is surfaced separately
                        # instead of silently counted as verified.
                        result["historicalOrders"].append(order)
                    # A retirement marker honestly awaiting a verified
                    # receipt carries reconciliationState: reconciliation
                    # work, not corruption; it falls through to the
                    # byte/receipt checks below. Any other failed v2 marker
                    # that cannot even record its state is corrupt.
                    elif not str(receipt.get("reconciliationState") or ""):
                        raise ValueError(f"accepted marker does not match attempt: {verdict}")
                except (OSError, ValueError, TypeError, AttributeError) as exc:
                    # F5: a corrupt accepted marker is recorded, but it does
                    # NOT authorize skipping the rest of this attempt. The
                    # retained artifact is still inspected independently:
                    # intact bytes stay recoverable candidates (marker
                    # existence is not proof, and corruption is not proof).
                    result["corruptEntries"].append({"path": receipt_path.name, "reason": str(exc)[:120]})
            artifact = Path(str(info.get("artifactPath") or ""))
            try:
                available = artifact.is_file() and root_resolved in artifact.resolve().parents
            except (OSError, ValueError):
                available = False
            result["candidateOrders" if available else "unavailableOrders"].append(order)
    return result
