"""F4: centralized validation of server acknowledgments and durable receipts.

A publication may only be treated as accepted (and its evidence retired) when
the server's own response proves the binding between THREE identities:

1. the local payload identity - the queue's ``localHash``, always RECOMPUTED
   from the durable submission envelope (never trusted from a filename or a
   receipt field alone);
2. the immutable run-create payload - ``runCreate.payloadHash`` must equal the
   canonical hash of the run-create contract itself (the same digest the
   server stores), and the server must echo it as
   ``benchmarkRun.payloadHash``;
3. the server-side run/artifact identities - ``benchmarkRun.id`` bound to
   ``artifact.benchmarkRunId`` and ``artifact.id``, with the artifact's role,
   SHA-256 and byte size matching the bytes this client actually uploaded.

Same bytes alone never authorize an unrelated run/campaign acknowledgment:
the payload hash and the run/artifact binding must match too. Legacy
``/submit`` ingest semantics are chosen ONLY by the actual submission kind -
an authoritative envelope with a malformed identity is unverified, never
reclassified as legacy. Identity fields are never coerced: booleans, floats,
dicts or wrong types are invalid, not repaired.

Upload confirmation and analysis acceptance are deliberately distinct.
Upload confirmation proves the artifact bytes were accepted
(``uploaded_analysis_pending``). Analysis acceptance requires a COMPLETE
authoritative analysis row for the same run; PENDING/SUSPECT/REJECTED/FAILED
rows keep their honest separate disposition and never imply acceptance.
"""

import hashlib
import json
import re
from typing import Any, Dict, List, Optional

AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND = "authoritative-artifact-run-v1"

# Storage states that prove the server holds the artifact bytes. PENDING and
# REJECTED never acknowledge an upload; DELETED is retention history, not a
# fresh acceptance for retirement purposes.
UPLOAD_CONFIRMED_STATES = frozenset({"UPLOADED", "VERIFIED", "RETAINED"})

RECEIPT_STATUS_UPLOADED = "uploaded_analysis_pending"

# Analysis rows only prove acceptance in this state; anything else is an
# honest separate disposition, never "accepted".
ANALYSIS_ACCEPTED_STATE = "COMPLETE"

_DECIMAL_INT = re.compile(r"^[0-9]+$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_payload_hash(run_create: Dict[str, Any]) -> str:
    """Canonical immutable identity of a run-create contract (server-stored)."""
    canonical = {key: value for key, value in run_create.items() if key != "payloadHash"}
    return _sha256_text(_canonical_json(canonical))


def _local_hash_material(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(payload)
    if normalized.get("submissionKind") == AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND:
        normalized.pop("artifactPath", None)
        normalized.pop("artifactManaged", None)
    return normalized


def local_payload_hash(payload: Dict[str, Any]) -> str:
    """The queue's canonical local identity for one submission envelope."""
    return _sha256_text(json.dumps(_local_hash_material(payload),
                                   separators=(",", ":"), sort_keys=True))


def _hex64(value: Any) -> Optional[str]:
    """Strict 64-hex digest: strings only, never coerced from other types."""
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    return text if _HEX64_RE.match(text) else None


def _ident(value: Any) -> str:
    return str(value or "").strip()


def _strict_int(value: Any) -> Optional[int]:
    """Exact integer: ints (not bools) and decimal strings only - floats,
    bools and containers are never coerced into a byte size."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and _DECIMAL_INT.match(value.strip()):
        return int(value.strip())
    return None


def expected_upload_identity(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Immutable identity this client is bound to, from its own payload.

    Returns None for a NON-authoritative submission (legacy /submit ingest,
    which has no run/artifact identity to bind) AND for an authoritative
    envelope whose identity contract is malformed - callers must distinguish
    those by submission kind, never by this return value alone.
    """
    if not isinstance(payload, dict):
        return None
    if payload.get("submissionKind") != AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND:
        return None
    run_create = payload.get("runCreate")
    if not isinstance(run_create, dict):
        return None
    payload_hash = _hex64(run_create.get("payloadHash"))
    if payload_hash is None:
        return None
    # The declared digest must equal the canonical hash of the contract it
    # claims to identify: a malformed/missing/mismatched payloadHash can
    # never produce a verifiable authoritative identity.
    if build_payload_hash(run_create) != payload_hash:
        return None
    artifact = run_create.get("artifact")
    artifact = artifact if isinstance(artifact, dict) else {}
    outer_sha = _hex64(payload.get("artifactSha256"))
    inner_sha = _hex64(artifact.get("sha256"))
    if outer_sha is None or inner_sha is None or outer_sha != inner_sha:
        return None
    outer_size = _strict_int(payload.get("artifactByteSize"))
    inner_size = _strict_int(artifact.get("byteSize"))
    if outer_size is None or inner_size is None or outer_size != inner_size or outer_size < 0:
        return None
    return {"payloadHash": payload_hash, "sha256": outer_sha, "byteSize": outer_size}


def is_authoritative_submission(payload: Any) -> bool:
    return (isinstance(payload, dict)
            and payload.get("submissionKind") == AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND)


def _analysis_disposition(analyses: Any) -> Dict[str, Any]:
    """Honest analysis disposition; acceptance needs a COMPLETE row.

    Never bool(rows): PENDING/SUSPECT/REJECTED/FAILED evidence stays a
    separate disposition the caller can report, and an empty list means the
    analysis is still pending - not accepted, not failed.
    """
    rows: List[Dict[str, Any]] = [row for row in analyses
                                  if isinstance(row, dict)] if isinstance(analyses, list) else []
    complete = [row for row in rows
                if _ident(row.get("status")).upper() == ANALYSIS_ACCEPTED_STATE
                and _ident(row.get("id")) and _ident(row.get("metricModelId"))]
    if complete:
        return {"analysisAccepted": True, "analysisStatus": ANALYSIS_ACCEPTED_STATE}
    if not rows:
        return {"analysisAccepted": False, "analysisStatus": "NONE"}
    statuses = [_ident(row.get("status")).upper() or "UNKNOWN" for row in rows]
    # Report the most consequential honest disposition of the foreign rows.
    for consequence in ("REJECTED", "FAILED", "SUSPECT", "PENDING"):
        if consequence in statuses:
            return {"analysisAccepted": False, "analysisStatus": consequence}
    return {"analysisAccepted": False, "analysisStatus": "UNKNOWN"}


def validate_upload_response(payload: Dict[str, Any], response: Any,
                             *, bound_run_id: Optional[str] = None,
                             bound_artifact_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return bound acknowledgment evidence, or None when unverified.

    `payload` is the durable authoritative submission; `response` is a live
    server body (create short-circuit, uploadRequired=false, or the PUT
    bundle). `bound_run_id` is the run id the transport created and
    `bound_artifact_id` the artifact id it first saw: every later phase must
    acknowledge the SAME run AND artifact, so a response naming a different
    artifact id is rejected even when run/hash/size match.

    The returned evidence proves upload confirmation only. `analysisAccepted`
    requires a COMPLETE authoritative analysis row; retirement MUST NOT
    depend on it.
    """
    expected = expected_upload_identity(payload)
    if expected is None:
        return None
    if not isinstance(response, dict):
        return None
    run = response.get("benchmarkRun")
    artifact = response.get("artifact")
    if not isinstance(run, dict) or not isinstance(artifact, dict):
        return None
    run_id = _ident(run.get("id"))
    if not run_id:
        return None
    if bound_run_id and run_id != _ident(bound_run_id):
        return None
    if _hex64(run.get("payloadHash")) != expected["payloadHash"]:
        return None
    artifact_id = _ident(artifact.get("id"))
    if not artifact_id:
        return None
    if bound_artifact_id and artifact_id != _ident(bound_artifact_id):
        return None
    if _ident(artifact.get("benchmarkRunId")) != run_id:
        return None
    if _ident(artifact.get("role")).upper() != "ENCODED":
        return None
    if _hex64(artifact.get("sha256")) != expected["sha256"]:
        return None
    byte_size = _strict_int(artifact.get("byteSize"))
    if byte_size is None or byte_size != expected["byteSize"]:
        return None
    if _ident(artifact.get("storageState")).upper() not in UPLOAD_CONFIRMED_STATES:
        return None
    disposition = _analysis_disposition(response.get("analyses"))
    return {
        "benchmarkRunId": run_id,
        "artifactId": artifact_id,
        "payloadHash": expected["payloadHash"],
        "artifactSha256": expected["sha256"],
        "artifactByteSize": expected["byteSize"],
        "storageState": _ident(artifact.get("storageState")).upper(),
        "uploadConfirmed": True,
        "analysisAccepted": disposition["analysisAccepted"],
        "analysisStatus": disposition["analysisStatus"],
    }


def receipt_acknowledgment_matches(receipt: Dict[str, Any]) -> bool:
    """Cross-check a receipt's persisted bound acknowledgment vs its response.

    Fresh production receipts persist the validated acknowledgment (schema
    identity) so post-retirement validation never has to re-derive trust
    payload-free. The acknowledgment must exactly match the identity the
    embedded response states; a receipt pairing an acknowledgment with
    foreign response bytes fails here, and such receipts are repair state.
    """
    acknowledgment = receipt.get("acknowledgment")
    if not isinstance(acknowledgment, dict):
        return False
    if acknowledgment.get("uploadConfirmed") is not True:
        return False
    if _ident(acknowledgment.get("status") if "status" in acknowledgment else RECEIPT_STATUS_UPLOADED) \
            != RECEIPT_STATUS_UPLOADED:
        return False
    response = receipt.get("response")
    if not isinstance(response, dict):
        return False
    run = response.get("benchmarkRun")
    artifact = response.get("artifact")
    if not isinstance(run, dict) or not isinstance(artifact, dict):
        return False
    run_id = _ident(run.get("id"))
    if not run_id or _ident(acknowledgment.get("benchmarkRunId")) != run_id:
        return False
    if _ident(artifact.get("id")) != _ident(acknowledgment.get("artifactId")):
        return False
    if _hex64(run.get("payloadHash")) != _hex64(acknowledgment.get("payloadHash")):
        return False
    if _hex64(artifact.get("sha256")) != _hex64(acknowledgment.get("artifactSha256")):
        return False
    artifact_size = _strict_int(artifact.get("byteSize"))
    ack_size = _strict_int(acknowledgment.get("artifactByteSize"))
    if artifact_size is None or ack_size is None or artifact_size != ack_size:
        return False
    return _ident(artifact.get("storageState")).upper() in UPLOAD_CONFIRMED_STATES


def receipt_verdict(local_hash: str, receipt: Any,
                    payload: Optional[Dict[str, Any]] = None) -> str:
    """Classify a durable queue receipt: ``verified``, ``orphan`` or
    ``unverified:<why>``.

    `local_hash` is the receipt filename stem. When `payload` is provided it
    is the owning envelope: the receipt must rebind to the RECOMPUTED
    canonical local hash (filename and stored field both), and an
    authoritative payload must additionally see its full run/artifact
    identity proven by the response. Legacy (non-authoritative submission
    kind) receipts stay faithful: ``{localHash, status, response: None}`` is
    exactly what production writes after a successful ``/submit`` chain,
    where no run identity exists at that endpoint. Without any payload only
    the receipt's own persisted bound acknowledgment is trustworthy, and an
    orphan receipt (neither response nor acknowledgment) is honestly
    reported as repair work, never as acceptance.
    """
    stem_hash = _hex64(local_hash)
    if stem_hash is None:
        return "unverified:receipt-name-is-not-a-payload-hash"
    if not isinstance(receipt, dict):
        return "unverified:receipt-is-not-an-object"
    if _hex64(receipt.get("localHash")) != stem_hash:
        return "unverified:localHash-does-not-match-receipt-name"
    if _ident(receipt.get("status")) != RECEIPT_STATUS_UPLOADED:
        return "unverified:status-is-not-" + RECEIPT_STATUS_UPLOADED
    response = receipt.get("response")
    if payload is not None:
        if not isinstance(payload, dict):
            return "unverified:owning-envelope-is-not-an-object"
        recomputed = local_payload_hash(payload)
        if recomputed != stem_hash:
            return "unverified:localHash-differs-from-recomputed-envelope-identity"
        if not is_authoritative_submission(payload):
            # Legacy ingest submission: /submit has no run/artifact identity
            # and production persists exactly {localHash, status,
            # response: None} on success. That faithful shape stays
            # verifiable; anything else on a legacy receipt is untrusted.
            if response is None:
                return "verified"
            return "unverified:legacy-receipt-carries-untrusted-response"
        if expected_upload_identity(payload) is None:
            return "unverified:authoritative-envelope-identity-is-malformed"
        if validate_upload_response(payload, response) is None:
            return "unverified:response-does-not-bind-this-payload-s-run-and-artifact"
        if not receipt_acknowledgment_matches(receipt):
            return "unverified:receipt-acknowledgment-missing-or-inconsistent"
        return "verified"
    # No envelope at hand: only the receipt's own persisted, response-cross-
    # checked acknowledgment is trustworthy. A response without one (or a
    # bare foreign bundle) can never be counted as a verified local ack.
    if receipt_acknowledgment_matches(receipt):
        return "verified"
    if response is None and not isinstance(receipt.get("acknowledgment"), dict):
        return "orphan:receipt-has-no-bound-acknowledgment-evidence"
    return "unverified:receipt-lacks-persisted-bound-acknowledgment"


def journal_marker_verdict(marker: Any, *, execution_order: int, recipe_id: str,
                           artifact_path: str, artifact_sha256: str,
                           payload_hash: Optional[str] = None) -> str:
    """Classify a campaign journal ``submission-*.accepted.json`` marker.

    Returns one of:

    * ``verified`` - full fresh proof (schemaVersion 2): binds execution
      order, recipe, exact artifact path/SHA-256, the server run id AND the
      server artifact id, an explicit ``uploadConfirmed: true``, the
      immutable runCreate payloadHash and the artifact byte size. Only this
      verdict authorizes skipping publication, draining or counting a
      retirement as freshly verified.
    * ``historical`` - schemaVersion 1 provenance written before F4: order,
      recipe, path, SHA-256 and a run id match. Historical evidence stays
      readable and already-completed attempts keep their identity, but this
      verdict NEVER authorizes a fresh success claim; consumers must
      reconcile it against the server before treating it as verified.
    * ``unverified:<why>`` - corrupt or mismatched evidence.
    """
    if not isinstance(marker, dict):
        return "unverified:journal-marker-is-not-an-object"
    schema = marker.get("schemaVersion")
    if schema not in (1, 2):
        return "unverified:journal-marker-schemaVersion"
    if marker.get("executionOrder") != execution_order:
        return "unverified:journal-marker-executionOrder"
    if _ident(marker.get("recipeId")) != _ident(recipe_id):
        return "unverified:journal-marker-recipeId"
    if _ident(marker.get("artifactPath")) != _ident(artifact_path):
        return "unverified:journal-marker-artifactPath"
    marker_sha = _hex64(marker.get("artifactSha256"))
    if marker_sha is None or marker_sha != _hex64(artifact_sha256):
        return "unverified:journal-marker-artifactSha256"
    if not _ident(marker.get("benchmarkRunId")):
        return "unverified:journal-marker-missing-benchmarkRunId"
    if schema == 1:
        return "historical"
    if _hex64(marker.get("payloadHash")) is None:
        return "unverified:journal-marker-missing-payloadHash"
    if payload_hash is not None and _hex64(marker.get("payloadHash")) != _hex64(payload_hash):
        return "unverified:journal-marker-payloadHash-differs-from-envelope"
    if not _ident(marker.get("artifactId")):
        return "unverified:journal-marker-missing-artifactId"
    if marker.get("uploadConfirmed") is not True:
        return "unverified:journal-marker-uploadConfirmed-not-explicit"
    if _strict_int(marker.get("artifactByteSize")) is None:
        return "unverified:journal-marker-missing-artifactByteSize"
    return "verified"


def validate_retention_response(payload: Dict[str, Any], marker: Dict[str, Any],
                                status_body: Any) -> Optional[Dict[str, Any]]:
    """Bind a server analysis-status body to a saved envelope + historical
    marker (metadata-only reconciliation of an already-accepted run).

    Proves the server still holds THIS artifact for THIS run with THIS
    immutable payloadHash, so a historical marker can be upgraded to full
    v2 proof without artifact bytes ever leaving the (possibly retired)
    local copy. Returns evidence, or None when the server body does not
    prove the binding.
    """
    expected = expected_upload_identity(payload)
    if expected is None or not isinstance(marker, dict):
        return None
    if not isinstance(status_body, dict):
        return None
    run_id = _ident(marker.get("benchmarkRunId"))
    if not run_id or _ident(status_body.get("benchmarkRunId")) != run_id:
        return None
    artifact_id = _ident(status_body.get("artifactId"))
    if not artifact_id:
        return None
    if _ident(status_body.get("artifactStorageState")).upper() not in UPLOAD_CONFIRMED_STATES:
        return None
    if _hex64(status_body.get("payloadHash")) != expected["payloadHash"]:
        return None
    if _hex64(status_body.get("artifactSha256")) != expected["sha256"]:
        return None
    byte_size = _strict_int(status_body.get("artifactByteSize"))
    if byte_size is None or byte_size != expected["byteSize"]:
        return None
    disposition = _analysis_disposition(status_body.get("analyses"))
    return {
        "benchmarkRunId": run_id,
        "artifactId": artifact_id,
        "payloadHash": expected["payloadHash"],
        "artifactSha256": expected["sha256"],
        "artifactByteSize": expected["byteSize"],
        "storageState": _ident(status_body.get("artifactStorageState")).upper(),
        "uploadConfirmed": True,
        "analysisAccepted": disposition["analysisAccepted"],
        "analysisStatus": disposition["analysisStatus"],
    }