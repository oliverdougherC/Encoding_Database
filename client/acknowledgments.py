"""F4: centralized validation of server acknowledgments and durable receipts.

A publication may only be treated as accepted (and its evidence retired) when
the server's own response proves the binding between THREE identities:

1. the local payload identity - the queue's ``localHash``, always RECOMPUTED
   from the durable submission envelope. After the queue entry and envelope
   are retired, a fresh receipt persists the canonical ``payloadIdentity``
   material (exactly the object the queue hashed) so the SAME canonical
   localHash can be recomputed later; a receipt without it can never verify
   payload-free, no matter how self-consistent its response and
   acknowledgment look - two claims of a foreign identity are not a local
   binding;
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
dicts, lists or numbers are invalid identities/statuses, not repaired.

Upload confirmation and analysis acceptance are deliberately distinct.
Upload confirmation proves the artifact bytes were accepted
(``uploaded_analysis_pending``). Analysis acceptance requires an ACCEPTED
benchmark run status AND a COMPLETE authoritative analysis row whose
``benchmarkRunId`` and ``artifactId`` name the SAME run and artifact the
response acknowledges, with a valid id and metricModelId. A COMPLETE row for
any other run/artifact is foreign noise; PENDING/SUSPECT/REJECTED/FAILED
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

# The benchmark run status that, together with a COMPLETE authoritative
# analysis row, proves analysis acceptance.
RUN_ACCEPTED_STATE = "ACCEPTED"

RECEIPT_STATUS_UPLOADED = "uploaded_analysis_pending"

# Durable receipt schema written by THIS client version: carries the bound
# acknowledgment AND the canonical payloadIdentity material so post-retirement
# validation can recompute the local identity instead of trusting one.
RECEIPT_SCHEMA_VERSION = 2

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


def local_hash_material(payload: Dict[str, Any]) -> Dict[str, Any]:
    """The exact object the queue hashes for one submission envelope.

    Authoritative payloads exclude the volatile ``artifactPath`` /
    ``artifactManaged`` fields; everything else is identity. Fresh durable
    receipts persist this material (``payloadIdentity``) so the canonical
    localHash stays recomputable after queue bytes and entries retire."""
    normalized = dict(payload)
    if normalized.get("submissionKind") == AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND:
        normalized.pop("artifactPath", None)
        normalized.pop("artifactManaged", None)
    return normalized


# Back-compatible private alias for the historical call sites.
_local_hash_material = local_hash_material


def local_payload_hash(payload: Dict[str, Any]) -> str:
    """The queue's canonical local identity for one submission envelope."""
    return _sha256_text(json.dumps(local_hash_material(payload),
                                   separators=(",", ":"), sort_keys=True))


def _hex64(value: Any) -> Optional[str]:
    """Strict 64-hex digest: strings only, never coerced from other types."""
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    return text if _HEX64_RE.match(text) else None


def _strict_ident(value: Any) -> Optional[str]:
    """A real identity/status string: dict/list/bool/number is INVALID."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _strict_int(value: Any) -> Optional[int]:
    """Exact integer: ints (not bools) and decimal strings only - floats,
    bools and containers are never coerced into a byte size or order."""
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


def _analysis_disposition(analyses: Any, *, run_id: Optional[str],
                          artifact_id: Optional[str]) -> Dict[str, Any]:
    """Honest analysis disposition bound to the acknowledged run/artifact.

    Never bool(rows): PENDING/SUSPECT/REJECTED/FAILED evidence stays a
    separate disposition the caller can report, and an empty list means the
    analysis is still pending - not accepted, not failed. A COMPLETE row
    only counts when its id and metricModelId are real strings AND its
    benchmarkRunId/artifactId name the SAME run and artifact the response
    acknowledges; a COMPLETE row for anything else is foreign noise.
    """
    rows: List[Dict[str, Any]] = [row for row in analyses
                                  if isinstance(row, dict)] if isinstance(analyses, list) else []
    accepted = False
    statuses: List[str] = []
    for row in rows:
        row_status = _strict_ident(row.get("status"))
        statuses.append((row_status or "UNKNOWN").upper())
        if ((row_status or "").upper() == ANALYSIS_ACCEPTED_STATE
                and _strict_ident(row.get("id")) is not None
                and _strict_ident(row.get("metricModelId")) is not None
                and run_id is not None
                and _strict_ident(row.get("benchmarkRunId")) == run_id
                and artifact_id is not None
                and _strict_ident(row.get("artifactId")) == artifact_id):
            accepted = True
    if accepted:
        return {"analysisAccepted": True, "analysisStatus": ANALYSIS_ACCEPTED_STATE}
    if not rows:
        return {"analysisAccepted": False, "analysisStatus": "NONE"}
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
    artifact id is rejected even when run/hash/size match. Identity fields
    are validated with strict types; dicts/lists/numbers are never coerced.

    The returned evidence proves upload confirmation only. `analysisAccepted`
    additionally requires an ACCEPTED benchmark run status and a COMPLETE
    authoritative analysis row bound to the same run AND artifact;
    retirement MUST NOT depend on it.
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
    run_id = _strict_ident(run.get("id"))
    if run_id is None:
        return None
    if bound_run_id and run_id != bound_run_id.strip():
        return None
    if _hex64(run.get("payloadHash")) != expected["payloadHash"]:
        return None
    artifact_id = _strict_ident(artifact.get("id"))
    if artifact_id is None:
        return None
    if bound_artifact_id and artifact_id != bound_artifact_id.strip():
        return None
    if _strict_ident(artifact.get("benchmarkRunId")) != run_id:
        return None
    role = _strict_ident(artifact.get("role"))
    if role is None or role.upper() != "ENCODED":
        return None
    if _hex64(artifact.get("sha256")) != expected["sha256"]:
        return None
    byte_size = _strict_int(artifact.get("byteSize"))
    if byte_size is None or byte_size != expected["byteSize"]:
        return None
    storage_state = _strict_ident(artifact.get("storageState"))
    if storage_state is None or storage_state.upper() not in UPLOAD_CONFIRMED_STATES:
        return None
    disposition = _analysis_disposition(response.get("analyses"),
                                        run_id=run_id, artifact_id=artifact_id)
    run_status = _strict_ident(run.get("status"))
    analysis_accepted = (disposition["analysisAccepted"]
                         and run_status is not None
                         and run_status.upper() == RUN_ACCEPTED_STATE)
    analysis_status = disposition["analysisStatus"]
    if disposition["analysisAccepted"] and not analysis_accepted:
        # A COMPLETE bound row on a run the server has not ACCEPTED yet is
        # honestly reported at the run's own pending disposition.
        analysis_status = (run_status or "PENDING").upper()
    return {
        "benchmarkRunId": run_id,
        "artifactId": artifact_id,
        "payloadHash": expected["payloadHash"],
        "artifactSha256": expected["sha256"],
        "artifactByteSize": expected["byteSize"],
        "storageState": storage_state.upper(),
        "uploadConfirmed": True,
        "analysisAccepted": analysis_accepted,
        "analysisStatus": analysis_status,
    }


def validate_acknowledgment(acknowledgment: Any, *, payload: Dict[str, Any],
                            response: Any) -> bool:
    """Validate a persisted bound acknowledgment against payload + response.

    Fresh production receipts and journal markers persist this evidence
    (schema identity) so post-retirement validation never has to re-derive
    trust payload-free. The acknowledgment must exactly match the identity
    the embedded response states AND the recomputed analysis disposition;
    trusting a stored ``analysisAccepted`` flag without revalidating it is
    exactly how a stale or forged flag would slip through.
    """
    if not isinstance(acknowledgment, dict):
        return False
    if acknowledgment.get("uploadConfirmed") is not True:
        return False
    ack_status = acknowledgment.get("status")
    if ack_status is not None and ack_status != RECEIPT_STATUS_UPLOADED:
        return False
    if not isinstance(response, dict):
        return False
    run = response.get("benchmarkRun")
    artifact = response.get("artifact")
    if not isinstance(run, dict) or not isinstance(artifact, dict):
        return False
    run_id = _strict_ident(run.get("id"))
    if run_id is None or _strict_ident(acknowledgment.get("benchmarkRunId")) != run_id:
        return False
    artifact_id = _strict_ident(artifact.get("id"))
    if artifact_id is None or _strict_ident(acknowledgment.get("artifactId")) != artifact_id:
        return False
    if _hex64(run.get("payloadHash")) != _hex64(acknowledgment.get("payloadHash")):
        return False
    if _hex64(artifact.get("sha256")) != _hex64(acknowledgment.get("artifactSha256")):
        return False
    artifact_size = _strict_int(artifact.get("byteSize"))
    ack_size = _strict_int(acknowledgment.get("artifactByteSize"))
    if artifact_size is None or ack_size is None or artifact_size != ack_size:
        return False
    storage_state = _strict_ident(artifact.get("storageState"))
    if storage_state is None or storage_state.upper() not in UPLOAD_CONFIRMED_STATES:
        return False
    # Recompute the analysis disposition instead of trusting the stored flag.
    evidence = validate_upload_response(payload, response)
    if evidence is None:
        return False
    if acknowledgment.get("analysisAccepted") is not evidence["analysisAccepted"]:
        return False
    ack_analysis_status = acknowledgment.get("analysisStatus")
    if ack_analysis_status is not None and ack_analysis_status != evidence["analysisStatus"]:
        return False
    return True


def receipt_acknowledgment_matches(receipt: Dict[str, Any]) -> bool:
    """Cross-check a receipt's persisted bound acknowledgment vs its response.

    Kept as the receipt-scoped wrapper of `validate_acknowledgment`: the
    payload it binds to is the receipt's own persisted ``payloadIdentity``
    when present (the canonical material the queue hashed)."""
    acknowledgment = receipt.get("acknowledgment")
    response = receipt.get("response")
    identity = receipt.get("payloadIdentity")
    if not isinstance(identity, dict):
        return False
    return validate_acknowledgment(acknowledgment, payload=identity, response=response)


def receipt_verdict(local_hash: str, receipt: Any,
                    payload: Optional[Dict[str, Any]] = None) -> str:
    """Classify a durable queue receipt: ``verified``, ``orphan`` or
    ``unverified:<why>``.

    `local_hash` is the receipt filename stem and is NEVER trusted on its
    own: the canonical local hash is RECOMPUTED from `payload` (the owning
    envelope) or, once that is retired, from the receipt's own persisted
    ``payloadIdentity`` - and either must equal the stem. An authoritative
    payload must additionally see its full run/artifact identity proven by
    the response AND carry a consistent persisted acknowledgment. Legacy
    (non-authoritative submission kind) receipts stay faithful:
    ``{localHash, status, response: None}`` is exactly what production
    writes after a successful ``/submit`` chain, where no run identity
    exists at that endpoint. A receipt without ANY recomputable canonical
    identity (no envelope, no payloadIdentity) is honest repair work -
    never a verified local acknowledgment, however self-consistent its
    response and acknowledgment look against each other.
    """
    stem_hash = _hex64(local_hash)
    if stem_hash is None:
        return "unverified:receipt-name-is-not-a-payload-hash"
    if not isinstance(receipt, dict):
        return "unverified:receipt-is-not-an-object"
    if _hex64(receipt.get("localHash")) != stem_hash:
        return "unverified:localHash-does-not-match-receipt-name"
    if _strict_ident(receipt.get("status")) != RECEIPT_STATUS_UPLOADED:
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
        if not validate_acknowledgment(receipt.get("acknowledgment"), payload=payload, response=response):
            return "unverified:receipt-acknowledgment-missing-or-inconsistent"
        return "verified"
    # No envelope at hand: ONLY the receipt's persisted payloadIdentity can
    # rebind this receipt to a canonical local identity. Self-consistency
    # between a response and an acknowledgment is two claims of the SAME
    # (possibly foreign) identity - it proves nothing about local bytes.
    identity = receipt.get("payloadIdentity")
    if not isinstance(identity, dict):
        if response is None and not isinstance(receipt.get("acknowledgment"), dict):
            return "orphan:receipt-has-no-bound-acknowledgment-evidence"
        return "unverified:receipt-lacks-recomputable-payload-identity"
    if local_payload_hash(identity) != stem_hash:
        return "unverified:payloadIdentity-differs-from-recomputed-canonical-hash"
    if not is_authoritative_submission(identity):
        if response is None:
            return "verified"
        return "unverified:legacy-receipt-carries-untrusted-response"
    if expected_upload_identity(identity) is None:
        return "unverified:authoritative-envelope-identity-is-malformed"
    if validate_upload_response(identity, response) is None:
        return "unverified:response-does-not-bind-this-payload-s-run-and-artifact"
    if not receipt_acknowledgment_matches(receipt):
        return "unverified:receipt-acknowledgment-missing-or-inconsistent"
    return "verified"


# Verdicts that mean "evidence is honest but insufficient": reconciliation
# work, never corruption and never a fresh verified claim.
RECONCILIATION_MARKER_VERDICTS = frozenset({
    "unverified:journal-marker-envelope-identity-missing-or-malformed",
    "unverified:journal-marker-missing-acknowledgment",
})


def journal_marker_verdict(marker: Any, *, execution_order: int, recipe_id: str,
                           artifact_path: str, artifact_sha256: str,
                           envelope_identity: Optional[Dict[str, Any]] = None,
                           payload_hash: Optional[str] = None,
                           payload: Optional[Dict[str, Any]] = None) -> str:
    """Classify a campaign journal ``submission-*.accepted.json`` marker.

    Returns one of:

    * ``verified`` - full fresh proof (schemaVersion 2): EXACT integer
      schema/order (bool/float invalid), nonempty string recipe/path/run/
      artifact ids, execution order/recipe/path/SHA binding to the attempt,
      AND the saved immutable envelope's ``envelope_identity`` (the real
      ``expected_upload_identity`` result, never a bare hash claim) binding
      payloadHash + artifact byte size, PLUS a persisted ``acknowledgment``
      whose identity matches the marker and envelope. Only this verdict
      authorizes skipping publication, draining or counting a retirement
      as freshly verified.
    * ``historical`` - schemaVersion 1 provenance written before F4: order,
      recipe, path, SHA-256 and a run id match. Historical evidence stays
      readable and already-completed attempts keep their identity, but this
      verdict NEVER authorizes a fresh success claim; consumers must
      reconcile it against the server before treating it as verified.
    * ``unverified:<why>`` - corrupt, coerced or insufficient evidence.
      Envelope-missing/malformed and acknowledgment-missing variants are
      reconciliation work (see RECONCILIATION_MARKER_VERDICTS), not proof.
    """
    if not isinstance(marker, dict):
        return "unverified:journal-marker-is-not-an-object"
    schema = marker.get("schemaVersion")
    if schema is None and "schemaVersion" not in marker:
        return "unverified:journal-marker-schemaVersion"
    if type(schema) is not int or schema not in (1, 2):
        return "unverified:journal-marker-schemaVersion"
    if type(marker.get("executionOrder")) is not int or marker.get("executionOrder") != execution_order:
        return "unverified:journal-marker-executionOrder"
    marker_recipe = _strict_ident(marker.get("recipeId"))
    if marker_recipe is None or marker_recipe != _strict_ident(recipe_id):
        return "unverified:journal-marker-recipeId"
    marker_path = _strict_ident(marker.get("artifactPath"))
    if marker_path is None or marker_path != _strict_ident(artifact_path):
        return "unverified:journal-marker-artifactPath"
    marker_sha = _hex64(marker.get("artifactSha256"))
    if marker_sha is None or marker_sha != _hex64(artifact_sha256):
        return "unverified:journal-marker-artifactSha256"
    if _strict_ident(marker.get("benchmarkRunId")) is None:
        return "unverified:journal-marker-missing-benchmarkRunId"
    if schema == 1:
        return "historical"
    envelope_identity = expected_upload_identity(payload)
    # v2: the saved immutable envelope must carry a REAL validated identity;
    # a missing/malformed envelope is never silently optional.
    if not isinstance(envelope_identity, dict) or \
            _hex64(envelope_identity.get("payloadHash")) is None or \
            _hex64(envelope_identity.get("sha256")) is None or \
            _strict_int(envelope_identity.get("byteSize")) is None:
        return "unverified:journal-marker-envelope-identity-missing-or-malformed"
    if payload_hash is not None and _hex64(payload_hash) is not None \
            and _hex64(payload_hash) != _hex64(envelope_identity.get("payloadHash")):
        return "unverified:journal-marker-payloadHash-differs-from-envelope"
    if _hex64(marker.get("payloadHash")) != _hex64(envelope_identity.get("payloadHash")):
        return "unverified:journal-marker-missing-payloadHash"
    if _strict_ident(marker.get("artifactId")) is None:
        return "unverified:journal-marker-missing-artifactId"
    if marker.get("uploadConfirmed") is not True:
        return "unverified:journal-marker-uploadConfirmed-not-explicit"
    marker_size = _strict_int(marker.get("artifactByteSize"))
    if marker_size is None or marker_size < 0 \
            or marker_size != _strict_int(envelope_identity.get("byteSize")):
        return "unverified:journal-marker-artifactByteSize-differs-from-envelope"
    if _hex64(marker.get("artifactSha256")) != _hex64(envelope_identity.get("sha256")):
        return "unverified:journal-marker-artifactSha256-differs-from-envelope"
    # Full proof requires the ACTUAL acknowledged evidence, not bare id
    # claims: the marker persists the validated acknowledgment (retirement,
    # journal self-publish and metadata-only retention upgrades all write
    # it) and revalidation checks it against marker + envelope + itself.
    acknowledgment = marker.get("acknowledgment")
    if not isinstance(acknowledgment, dict):
        return "unverified:journal-marker-missing-acknowledgment"
    if acknowledgment.get("uploadConfirmed") is not True:
        return "unverified:journal-marker-acknowledgment-uploadConfirmed"
    if _strict_ident(acknowledgment.get("benchmarkRunId")) != \
            _strict_ident(marker.get("benchmarkRunId")):
        return "unverified:journal-marker-acknowledgment-benchmarkRunId"
    if _strict_ident(acknowledgment.get("artifactId")) != \
            _strict_ident(marker.get("artifactId")):
        return "unverified:journal-marker-acknowledgment-artifactId"
    if _hex64(acknowledgment.get("payloadHash")) != \
            _hex64(envelope_identity.get("payloadHash")):
        return "unverified:journal-marker-acknowledgment-payloadHash"
    if _hex64(acknowledgment.get("artifactSha256")) != \
            _hex64(envelope_identity.get("sha256")):
        return "unverified:journal-marker-acknowledgment-artifactSha256"
    ack_size = _strict_int(acknowledgment.get("artifactByteSize"))
    if ack_size is None or ack_size != _strict_int(envelope_identity.get("byteSize")):
        return "unverified:journal-marker-acknowledgment-artifactByteSize"
    if acknowledgment.get("analysisAccepted") is not True \
            and acknowledgment.get("analysisAccepted") is not False:
        return "unverified:journal-marker-acknowledgment-analysisAccepted-not-boolean"
    if "retentionResponse" in marker:
        evidence = validate_retention_response(payload, marker, marker["retentionResponse"])
    else:
        evidence = validate_upload_response(payload, marker.get("response"),
                    bound_run_id=marker["benchmarkRunId"], bound_artifact_id=marker["artifactId"])
    if evidence is None or any(type(acknowledgment.get(k)) is not type(v)
                               or acknowledgment.get(k) != v for k, v in evidence.items()):
        return "unverified:journal-marker-acknowledgment-response"
    return "verified"


def acknowledgment_from_evidence(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """The durable acknowledgment object markers persist from validated
    evidence (upload confirmation; analysis acceptance kept distinct)."""
    return {
        "benchmarkRunId": evidence["benchmarkRunId"],
        "artifactId": evidence["artifactId"],
        "payloadHash": evidence["payloadHash"],
        "artifactSha256": evidence["artifactSha256"],
        "artifactByteSize": evidence["artifactByteSize"],
        "storageState": evidence["storageState"],
        "uploadConfirmed": True,
        "analysisAccepted": bool(evidence.get("analysisAccepted")),
        "analysisStatus": evidence.get("analysisStatus"),
    }


def validate_retention_response(payload: Dict[str, Any], marker: Dict[str, Any],
                                status_body: Any) -> Optional[Dict[str, Any]]:
    """Bind a server analysis-status body to a saved envelope + historical
    marker (metadata-only reconciliation of an already-accepted run).

    Proves the server still holds THIS artifact for THIS run with THIS
    immutable payloadHash, so a historical marker can be upgraded to full
    v2 proof without artifact bytes ever leaving the (possibly retired)
    local copy. Analysis acceptance follows the same strict rule as a live
    response: ACCEPTED run status + COMPLETE row bound to the same
    run/artifact. Returns evidence, or None when the server body does not
    prove the binding.
    """
    expected = expected_upload_identity(payload)
    if expected is None or not isinstance(marker, dict):
        return None
    if not isinstance(status_body, dict):
        return None
    run_id = _strict_ident(marker.get("benchmarkRunId"))
    if not run_id or _strict_ident(status_body.get("benchmarkRunId")) != run_id:
        return None
    artifact_id = _strict_ident(status_body.get("artifactId"))
    if artifact_id is None:
        return None
    storage_state = _strict_ident(status_body.get("artifactStorageState"))
    if storage_state is None or storage_state.upper() not in UPLOAD_CONFIRMED_STATES:
        return None
    if _hex64(status_body.get("payloadHash")) != expected["payloadHash"]:
        return None
    if _hex64(status_body.get("artifactSha256")) != expected["sha256"]:
        return None
    byte_size = _strict_int(status_body.get("artifactByteSize"))
    if byte_size is None or byte_size != expected["byteSize"]:
        return None
    if marker.get("artifactId") and marker.get("artifactId") != artifact_id:
        return None
    disposition = _analysis_disposition(status_body.get("analyses"),
                                        run_id=run_id, artifact_id=artifact_id)
    run_status = _strict_ident(status_body.get("benchmarkRunStatus"))
    analysis_accepted = (disposition["analysisAccepted"]
                         and run_status is not None
                         and run_status.upper() == RUN_ACCEPTED_STATE)
    analysis_status = disposition["analysisStatus"]
    if disposition["analysisAccepted"] and not analysis_accepted:
        analysis_status = (run_status or "PENDING").upper()
    return {
        "benchmarkRunId": run_id,
        "artifactId": artifact_id,
        "payloadHash": expected["payloadHash"],
        "artifactSha256": expected["sha256"],
        "artifactByteSize": expected["byteSize"],
        "storageState": storage_state.upper(),
        "uploadConfirmed": True,
        "analysisAccepted": analysis_accepted,
        "analysisStatus": analysis_status,
    }