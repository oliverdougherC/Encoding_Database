import hashlib
import json
import os
from typing import Any, Dict, Optional

from .network import SubmitError, _load_requests

AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND = "authoritative-artifact-run-v1"
AUTHORITATIVE_ANALYZER_VERSION = "authoritative-analysis/v1"
AUTHORITATIVE_SUITE_ID = "encodingdb-test-suite"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_payload_hash(run_create: Dict[str, Any]) -> str:
    canonical = {key: value for key, value in run_create.items() if key != "payloadHash"}
    return _sha256_text(_canonical_json(canonical))


def infer_content_type(*, media_container: Optional[str], artifact_path: str) -> str:
    container = str(media_container or "").strip().lower()
    if container == "mp4":
        return "video/mp4"
    if container in ("mkv", "matroska"):
        return "video/x-matroska"
    ext = os.path.splitext(artifact_path)[1].strip().lower()
    if ext == ".mp4":
        return "video/mp4"
    if ext == ".mkv":
        return "video/x-matroska"
    return "application/octet-stream"


def build_recipe_bootstrap(
    *,
    recipe_fingerprint: str,
    requested_recipe_json: str,
    effective_recipe_json: str,
) -> Dict[str, Any]:
    requested = json.loads(requested_recipe_json or "{}")
    effective = json.loads(effective_recipe_json or "{}")
    output_requested = requested.get("outputRequested") or requested.get("outputEffective") or {}
    output_effective = effective.get("outputEffective") or effective.get("outputRequested") or {}
    identity = {
        "codecFamily": effective.get("codecFamily") or requested.get("codecFamily"),
        "encoderImplementation": effective.get("encoderImplementation") or requested.get("encoderImplementation"),
        "encoderVersion": effective.get("encoderVersion") or requested.get("encoderVersion"),
        "preset": effective.get("presetEffective") or effective.get("presetRequested") or requested.get("presetRequested"),
        "tune": effective.get("tune") or requested.get("tune"),
        "profile": effective.get("profile") or requested.get("profile"),
        "level": effective.get("level") or requested.get("level"),
        "tier": effective.get("tier") or requested.get("tier"),
        "pixelFormat": output_effective.get("pixelFormat") or output_requested.get("pixelFormat"),
        "bitDepth": output_effective.get("bitDepth") or output_requested.get("bitDepth"),
        "chromaSubsampling": output_effective.get("chromaSubsampling") or output_requested.get("chromaSubsampling"),
        "containerFormat": output_effective.get("containerFormat") or output_requested.get("containerFormat"),
        "videoCodecTag": output_effective.get("videoTag") or output_requested.get("videoTag"),
        "requestedRateControl": requested.get("rateControlRequested") or {},
        "effectiveRateControl": effective.get("rateControlEffective") or effective.get("rateControlRequested") or {},
        "requestedOutputSettings": output_requested,
        "effectiveOutputSettings": output_effective,
        "normalizedRequestedOptions": requested.get("nativeOptionsRequested"),
        "normalizedEffectiveOptions": effective.get("nativeOptionsEffective") or effective.get("nativeOptionsRequested"),
        "gopSize": output_effective.get("gopFrames") or output_requested.get("gopFrames"),
        "keyframeInterval": output_effective.get("keyintMin") or output_requested.get("keyintMin"),
        "bFrames": output_effective.get("maxBFrames") or output_requested.get("maxBFrames"),
        "frameReordering": output_effective.get("bFrameReordering") if "bFrameReordering" in output_effective else output_requested.get("bFrameReordering"),
        "lookahead": output_effective.get("lookaheadFrames") or output_requested.get("lookaheadFrames"),
        "filmGrainSynthesis": (
            {"value": output_effective.get("filmGrainSynthesis")}
            if output_effective.get("filmGrainSynthesis") is not None
            else None
        ),
        "majorTools": (
            {"friendlyDescription": effective.get("friendlyDescription")}
            if effective.get("friendlyDescription")
            else None
        ),
    }
    return {
        "fingerprint": recipe_fingerprint,
        "canonicalJson": identity,
        "identity": identity,
    }


def build_environment_bootstrap(
    *,
    environment_fingerprint: str,
    environment_json: str,
    cpu_model: str,
) -> Dict[str, Any]:
    identity = json.loads(environment_json or "{}")
    environment_identity = {
        "cpuModel": cpu_model,
        "cpuArchitecture": identity.get("cpuArchitecture"),
        "physicalCoreCount": identity.get("cpuPhysicalCores"),
        "logicalThreadCount": identity.get("cpuLogicalCores"),
        "gpuModel": identity.get("gpuModel"),
        "selectedAcceleratorId": identity.get("accelerator"),
        "selectedAccelerator": identity.get("accelerator"),
        "driverVersion": identity.get("driverVersion"),
        "osName": identity.get("osName"),
        "osVersion": identity.get("osVersion"),
        "ffmpegBuildFingerprint": identity.get("ffmpegBuildFingerprint"),
        "ffmpegVersion": identity.get("ffmpegVersion"),
        "encoderVersion": identity.get("encoderVersion"),
        "clientVersion": identity.get("clientVersion"),
    }
    return {
        "fingerprint": environment_fingerprint,
        "canonicalJson": identity,
        "identity": environment_identity,
    }


def build_artifact_submission_payload(
    *,
    artifact_path: str,
    media_container: Optional[str],
    run_create: Dict[str, Any],
) -> Dict[str, Any]:
    submission = {
        "submissionKind": AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND,
        "artifactPath": artifact_path,
        "artifactSha256": str(run_create["artifact"]["sha256"]),
        "artifactByteSize": int(run_create["artifact"]["byteSize"]),
        "contentType": infer_content_type(media_container=media_container, artifact_path=artifact_path),
        "runCreate": dict(run_create),
    }
    return submission


def submit_artifact_submission(
    base_url: str,
    submission: Dict[str, Any],
    *,
    retries: int = 3,
) -> Dict[str, Any]:
    artifact_path = str(submission.get("artifactPath") or "").strip()
    if not artifact_path:
        raise SubmitError("artifact submission missing artifactPath", retryable=False)
    if not os.path.exists(artifact_path):
        raise SubmitError(f"artifact missing at {artifact_path}", retryable=False)

    run_create = submission.get("runCreate")
    if not isinstance(run_create, dict):
        raise SubmitError("artifact submission missing runCreate", retryable=False)

    requests = _load_requests()
    create_url = f"{base_url.rstrip('/')}/v7/benchmark-runs"
    auth_content_type = str(submission.get("contentType") or "application/octet-stream")
    last_error: Optional[SubmitError] = None

    for attempt in range(1, max(1, retries) + 1):
        try:
            create_response = requests.post(
                create_url,
                json=run_create,
                timeout=60,
                allow_redirects=False,
            )
        except Exception as exc:
            last_error = SubmitError(str(exc), retryable=True)
            continue

        if create_response.status_code in (429,) or create_response.status_code >= 500:
            last_error = SubmitError(
                f"run create failed ({create_response.status_code})",
                retryable=True,
                status_code=create_response.status_code,
                body=create_response.text or "",
            )
            continue
        if create_response.status_code >= 400:
            raise SubmitError(
                f"run create rejected ({create_response.status_code})",
                retryable=False,
                status_code=create_response.status_code,
                body=create_response.text or "",
            )

        try:
            create_json = create_response.json()
        except Exception as exc:
            last_error = SubmitError(f"run create response invalid JSON: {exc}", retryable=True)
            continue

        benchmark_run = create_json.get("benchmarkRun") if isinstance(create_json, dict) else None
        run_id = str((benchmark_run or {}).get("id") or "").strip()
        if not run_id:
            last_error = SubmitError("run create response missing benchmarkRun.id", retryable=True)
            continue

        artifact = create_json.get("artifact") if isinstance(create_json, dict) else None
        artifact_state = str((artifact or {}).get("storageState") or "").strip().upper()
        analyses = create_json.get("analyses") if isinstance(create_json, dict) else None
        if artifact_state in ("RETAINED", "VERIFIED") and isinstance(analyses, list) and analyses:
            return create_json

        auth_response = requests.post(
            f"{base_url.rstrip('/')}/v7/benchmark-runs/{run_id}/artifacts/ENCODED/upload-authorizations",
            json={
                "sha256": run_create["artifact"]["sha256"],
                "byteSize": run_create["artifact"]["byteSize"],
                "contentType": auth_content_type,
            },
            timeout=60,
            allow_redirects=False,
        )
        if auth_response.status_code in (429,) or auth_response.status_code >= 500:
            last_error = SubmitError(
                f"upload authorization failed ({auth_response.status_code})",
                retryable=True,
                status_code=auth_response.status_code,
                body=auth_response.text or "",
            )
            continue
        if auth_response.status_code >= 400:
            raise SubmitError(
                f"upload authorization rejected ({auth_response.status_code})",
                retryable=False,
                status_code=auth_response.status_code,
                body=auth_response.text or "",
            )
        auth_json = auth_response.json()
        if not isinstance(auth_json, dict):
            last_error = SubmitError("upload authorization response invalid JSON", retryable=True)
            continue
        if auth_json.get("uploadRequired") is False:
            return auth_json

        token = str(auth_json.get("token") or "").strip()
        if not token:
            last_error = SubmitError("upload authorization missing token", retryable=True)
            continue

        try:
            with open(artifact_path, "rb") as handle:
                upload_response = requests.put(
                    f"{base_url.rstrip('/')}/v7/artifact-uploads/{token}",
                    data=handle,
                    headers={"Content-Type": auth_content_type},
                    timeout=300,
                    allow_redirects=False,
                )
        except Exception as exc:
            last_error = SubmitError(str(exc), retryable=True)
            continue

        if upload_response.status_code in (429,) or upload_response.status_code >= 500:
            last_error = SubmitError(
                f"artifact upload failed ({upload_response.status_code})",
                retryable=True,
                status_code=upload_response.status_code,
                body=upload_response.text or "",
            )
            continue
        if upload_response.status_code >= 400:
            raise SubmitError(
                f"artifact upload rejected ({upload_response.status_code})",
                retryable=False,
                status_code=upload_response.status_code,
                body=upload_response.text or "",
            )
        try:
            return upload_response.json()
        except Exception as exc:
            last_error = SubmitError(f"artifact upload response invalid JSON: {exc}", retryable=True)

    if last_error is not None:
      raise last_error
    raise SubmitError("artifact submission failed", retryable=True)
