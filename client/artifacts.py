import hashlib
import json
import os
import time
from typing import Any, Callable, Dict, Optional

from .network import (SubmissionCancelled, SubmitError, _event_cancelled, _load_requests,
                       _response_error_text, _run_cancellable, retry_after_seconds)

# C12: bounded, cooperatively cancellable artifact transport. Each phase runs
# its blocking HTTP call in a daemon worker so a cancel_event (threading.Event
# or duck-typed `is_set()`) is observed within ~50 ms even while the call is
# socket-blocked; the worker itself carries a socket inactivity timeout at
# most the phase budget, so a stalled peer cannot pin a worker beyond it.
# Worst-case no-cancel chain: create 30 s + auth 30 s + upload 120 s = 180 s,
# vs the old 60+60+300 s with no cancellation input at all.
CREATE_TIMEOUT_SECONDS = 30.0
AUTH_TIMEOUT_SECONDS = 30.0
UPLOAD_TIMEOUT_SECONDS = 120.0

# Progress callback signature: (phase, sent_bytes, total_bytes). GUI-safe:
# ints only, no server data.
ProgressCallback = Callable[[str, int, int], None]

AUTHORITATIVE_ARTIFACT_SUBMISSION_KIND = "authoritative-artifact-run-v1"
AUTHORITATIVE_ANALYZER_VERSION = "authoritative-analysis/v2"
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
        "requestedRateControl": _canonical_rate_control(requested.get("rateControlRequested")),
        "effectiveRateControl": _canonical_rate_control(
            effective.get("rateControlEffective") or effective.get("rateControlRequested")
        ),
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
        "fingerprint": _sha256_text(_canonical_json(identity)),
        "canonicalJson": identity,
        "identity": identity,
    }


def _canonical_rate_control(value: Any) -> Dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    return {
        "mode": str(raw.get("mode") or "other").strip().lower(),
        "qualityValue": raw.get("qualityValue"),
        "targetBitrateKbps": raw.get("targetBitrateKbps"),
        "maxBitrateKbps": raw.get("maxBitrateKbps"),
        "bufferSizeKbits": raw.get("bufferSizeKbits"),
        "qmin": raw.get("qmin"),
        "qmax": raw.get("qmax"),
        "extras": raw.get("extras"),
    }


def build_environment_bootstrap(
    *,
    environment_json: str,
    cpu_model: str,
) -> Dict[str, Any]:
    identity = json.loads(environment_json or "{}")
    environment_identity = {
        "cpuModel": " ".join(str(cpu_model).split()),
        "cpuArchitecture": _canonical_architecture(identity.get("cpuArchitecture")),
        "physicalCoreCount": _canonical_optional_int(identity.get("cpuPhysicalCores")),
        "logicalThreadCount": _canonical_optional_int(identity.get("cpuLogicalCores")),
        "physicalMemoryBytes": _canonical_optional_int(identity.get("physicalMemoryBytes")),
        "gpuModel": _canonical_optional_text(identity.get("gpuModel")),
        "selectedAcceleratorId": _canonical_optional_text(identity.get("accelerator"), lowercase=True),
        "selectedAccelerator": _canonical_optional_text(identity.get("accelerator")),
        "driverVersion": _canonical_optional_text(identity.get("driverVersion")),
        "osName": _canonical_required_text(identity.get("osName"), lowercase=True),
        "osVersion": _canonical_required_text(identity.get("osVersion"), lowercase=True),
        "ffmpegBuildFingerprint": _canonical_required_text(identity.get("ffmpegBuildFingerprint")),
        "ffmpegVersion": _canonical_required_text(identity.get("ffmpegVersion")),
        "encoderVersion": _canonical_optional_text(identity.get("encoderVersion")),
        "clientVersion": _canonical_required_text(identity.get("clientVersion")),
        **{key: identity[key] for key in ("executionArchitecture", "translationMode", "runtimeIdentity", "selectedDeviceEvidence") if identity.get(key) is not None},
    }
    return {
        "fingerprint": _sha256_text(_canonical_json(environment_identity)),
        "canonicalJson": environment_identity,
        "identity": environment_identity,
    }


def _canonical_optional_text(value: Any, *, lowercase: bool = False) -> Optional[str]:
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    if not normalized:
        return None
    return normalized.lower() if lowercase else normalized


def _canonical_required_text(value: Any, *, lowercase: bool = False) -> str:
    normalized = _canonical_optional_text(value, lowercase=lowercase)
    if normalized is None:
        raise ValueError("required environment identity field is missing")
    return normalized


def _canonical_optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    return int(value)


def _canonical_architecture(value: Any) -> str:
    architecture = _canonical_required_text(value, lowercase=True)
    return {"aarch64": "arm64", "amd64": "x86_64", "x64": "x86_64"}.get(architecture, architecture)


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


class _PhaseBudget:
    """Monotonic wall-clock budget for one transport phase (C12)."""

    def __init__(self, seconds: float) -> None:
        self.seconds = max(0.05, float(seconds))
        self.deadline = time.monotonic() + self.seconds

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def timeout(self, phase: str) -> float:
        """Socket inactivity timeout clamped to the remaining budget.

        A stalled transaction therefore self-limits to at most the phase
        budget even if no cancel ever arrives."""
        remaining = self.remaining()
        if remaining <= 0:
            raise SubmitError(f"{phase} exceeded {self.seconds:g}s phase budget", retryable=True)
        return max(0.1, min(self.seconds, remaining))


def _phase_guard(budget: _PhaseBudget, cancel_event: Optional[Any], phase: str) -> None:
    if _event_cancelled(cancel_event):
        raise SubmissionCancelled(phase)
    if budget.remaining() <= 0:
        raise SubmitError(f"{phase} exceeded {budget.seconds:g}s phase budget", retryable=True)


def _safe_request_error(exc: Exception) -> SubmitError:
    """Sanitized retryable wrapper: exception type only, never str(exc) (may
    embed URLs, upload tokens or bodies)."""
    return SubmitError(f"artifact transport failed: {type(exc).__name__}", retryable=True)


class _UploadBody:
    """Sized streaming PUT body with cancel/deadline checks and progress (C12).

    Exposes `__len__` so requests keeps the original Content-Length framing
    (no chunked-encoding wire change) while urllib3 still sends it chunk by
    chunk; each chunk pull re-checks cancel and the phase budget, so a GUI
    Stop ends the upload at the next chunk boundary (or, if the server stops
    reading and the socket send blocks, within the armed send timeout —
    bounded by the upload phase budget)."""

    def __init__(self, path: str, *, phase: str, budget: _PhaseBudget,
                 cancel_event: Optional[Any], progress: Optional[ProgressCallback]) -> None:
        self._path = path
        self._phase = phase
        self._budget = budget
        self._cancel_event = cancel_event
        self._progress = progress
        self._total = os.path.getsize(path)

    def __len__(self) -> int:
        return self._total

    def __iter__(self):
        sent = 0
        chunk_size = 262144
        with open(self._path, "rb") as handle:
            while True:
                _phase_guard(self._budget, self._cancel_event, self._phase)
                try:
                    chunk = handle.read(chunk_size)
                except Exception as exc:
                    raise _safe_request_error(exc) from exc
                if not chunk:
                    break
                sent += len(chunk)
                if self._progress is not None:
                    try:
                        self._progress(self._phase, sent, self._total)
                    except Exception:
                        pass
                yield chunk


def _read_json_bounded(response: Any, *, phase: str, budget: _PhaseBudget,
                       cancel_event: Optional[Any]) -> Any:
    """Parse a JSON response body with cancel checks and a size cap."""
    text = _response_error_text(_load_requests(), response, cancel_event, budget.deadline,
                                max_bytes=1 << 22)
    try:
        return json.loads(text)
    except Exception:
        return None


def submit_artifact_submission(
    base_url: str,
    submission: Dict[str, Any],
    *,
    retries: int = 3,
    cancel_event: Optional[Any] = None,
    progress: Optional[ProgressCallback] = None,
    create_seconds: float = CREATE_TIMEOUT_SECONDS,
    auth_seconds: float = AUTH_TIMEOUT_SECONDS,
    upload_seconds: float = UPLOAD_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Create run → authorize → upload, each phase bounded and cancellable.

    `cancel_event` is a threading.Event (or duck-typed `is_set()`); each
    blocking phase runs in a daemon worker so cancel is observed within
    ~50 ms even mid-socket-wait, and immediately between phases/chunks. The
    worker's own socket inactivity timeout never exceeds its phase budget, so
    nothing outlives create 30 s + auth 30 s + upload 120 s even with no
    cancel. On cancel/timeout the error is retryable, so the durable spool
    keeps the entry and its localHash; an accepted-but-lost response replays
    idempotently against the same run.
    Progress: `progress(phase, sent_bytes, total_bytes)` during upload only.
    """
    artifact_path = str(submission.get("artifactPath") or "").strip()
    if not artifact_path:
        raise SubmitError("artifact submission missing artifactPath", retryable=False)
    if not os.path.exists(artifact_path):
        raise SubmitError("artifact missing on disk", retryable=False)

    run_create = submission.get("runCreate")
    if not isinstance(run_create, dict):
        raise SubmitError("artifact submission missing runCreate", retryable=False)

    requests = _load_requests()
    create_url = f"{base_url.rstrip('/')}/v7/benchmark-runs"
    auth_content_type = str(submission.get("contentType") or "application/octet-stream")
    last_error: Optional[SubmitError] = None

    # The durable spool owns retry scheduling, deadlines and backoff. One network
    # transaction per entry avoids hot retries across multiple clients.
    for attempt in range(1, 2):
        if _event_cancelled(cancel_event):
            raise SubmissionCancelled("run create")
        create_budget = _PhaseBudget(create_seconds)
        try:
            create_response = _run_cancellable(
                lambda: requests.post(
                    create_url,
                    json=run_create,
                    timeout=create_budget.timeout("run create"),
                    allow_redirects=False,
                    stream=True,
                ),
                phase="run create", cancel_event=cancel_event,
                deadline=create_budget.deadline, bound_seconds=create_budget.seconds)
        except SubmissionCancelled:
            raise
        except Exception as exc:
            last_error = _safe_request_error(exc)
            continue

        if create_response.status_code in (429,) or create_response.status_code >= 500:
            last_error = SubmitError(
                f"run create failed ({create_response.status_code})",
                retryable=True,
                status_code=create_response.status_code,
                body=_response_error_text(requests, create_response, cancel_event,
                                          None),
                retry_after=retry_after_seconds(create_response.headers),
            )
            continue
        if create_response.status_code >= 400:
            raise SubmitError(
                f"run create rejected ({create_response.status_code})",
                retryable=False,
                status_code=create_response.status_code,
                body=_response_error_text(requests, create_response, cancel_event,
                                          None),
                retry_after=retry_after_seconds(create_response.headers),
            )

        create_json = _read_json_bounded(create_response, phase="run create",
                                         budget=create_budget, cancel_event=cancel_event)
        if not isinstance(create_json, dict):
            last_error = SubmitError("run create response invalid JSON", retryable=True)
            continue

        benchmark_run = create_json.get("benchmarkRun")
        run_id = str((benchmark_run or {}).get("id") or "").strip()
        if not run_id:
            last_error = SubmitError("run create response missing benchmarkRun.id", retryable=True)
            continue

        artifact = create_json.get("artifact")
        artifact_state = str((artifact or {}).get("storageState") or "").strip().upper()
        analyses = create_json.get("analyses")
        if artifact_state in ("RETAINED", "VERIFIED") and isinstance(analyses, list) and analyses:
            return create_json

        if _event_cancelled(cancel_event):
            raise SubmissionCancelled("upload authorization")
        auth_budget = _PhaseBudget(auth_seconds)
        try:
            auth_response = _run_cancellable(
                lambda: requests.post(
                    f"{base_url.rstrip('/')}/v7/benchmark-runs/{run_id}/artifacts/ENCODED/upload-authorizations",
                    json={
                        "sha256": run_create["artifact"]["sha256"],
                        "byteSize": run_create["artifact"]["byteSize"],
                        "contentType": auth_content_type,
                    },
                    timeout=auth_budget.timeout("upload authorization"),
                    allow_redirects=False,
                    stream=True,
                ),
                phase="upload authorization", cancel_event=cancel_event,
                deadline=auth_budget.deadline, bound_seconds=auth_budget.seconds)
        except SubmissionCancelled:
            raise
        except Exception as exc:
            last_error = _safe_request_error(exc)
            continue

        if auth_response.status_code in (429,) or auth_response.status_code >= 500:
            last_error = SubmitError(
                f"upload authorization failed ({auth_response.status_code})",
                retryable=True,
                status_code=auth_response.status_code,
                body=_response_error_text(requests, auth_response, cancel_event,
                                          None),
                retry_after=retry_after_seconds(auth_response.headers),
            )
            continue
        if auth_response.status_code >= 400:
            raise SubmitError(
                f"upload authorization rejected ({auth_response.status_code})",
                retryable=False,
                status_code=auth_response.status_code,
                body=_response_error_text(requests, auth_response, cancel_event,
                                          None),
                retry_after=retry_after_seconds(auth_response.headers),
            )
        auth_json = _read_json_bounded(auth_response, phase="upload authorization",
                                       budget=auth_budget, cancel_event=cancel_event)
        if not isinstance(auth_json, dict):
            last_error = SubmitError("upload authorization response invalid JSON", retryable=True)
            continue
        if auth_json.get("uploadRequired") is False:
            return auth_json

        token = str(auth_json.get("token") or "").strip()
        if not token:
            last_error = SubmitError("upload authorization missing token", retryable=True)
            continue

        if _event_cancelled(cancel_event):
            raise SubmissionCancelled("artifact upload")
        upload_budget = _PhaseBudget(upload_seconds)
        try:
            upload_response = _run_cancellable(
                lambda: requests.put(
                    f"{base_url.rstrip('/')}/v7/artifact-uploads/{token}",
                    data=_UploadBody(artifact_path, phase="artifact upload",
                                     budget=upload_budget, cancel_event=cancel_event,
                                     progress=progress),
                    headers={"Content-Type": auth_content_type},
                    timeout=upload_budget.timeout("artifact upload"),
                    allow_redirects=False,
                    stream=True,
                ),
                phase="artifact upload", cancel_event=cancel_event,
                deadline=upload_budget.deadline, bound_seconds=upload_budget.seconds)
        except (SubmissionCancelled, SubmitError):
            raise
        except Exception as exc:
            # A cancel raised inside the streaming body can surface wrapped by
            # the HTTP stack; unwrap so the SubmissionCancelled contract holds.
            cause = exc.__cause__ or exc.__context__
            while cause is not None:
                if isinstance(cause, SubmissionCancelled):
                    raise cause from exc
                cause = getattr(cause, "__cause__", None) or getattr(cause, "__context__", None)
            last_error = _safe_request_error(exc)
            continue

        if upload_response.status_code in (429,) or upload_response.status_code >= 500:
            last_error = SubmitError(
                f"artifact upload failed ({upload_response.status_code})",
                retryable=True,
                status_code=upload_response.status_code,
                body=_response_error_text(requests, upload_response, cancel_event,
                                          None),
                retry_after=retry_after_seconds(upload_response.headers),
            )
            continue
        if upload_response.status_code >= 400:
            raise SubmitError(
                f"artifact upload rejected ({upload_response.status_code})",
                retryable=False,
                status_code=upload_response.status_code,
                body=_response_error_text(requests, upload_response, cancel_event,
                                          None),
                retry_after=retry_after_seconds(upload_response.headers),
            )
        upload_json = _read_json_bounded(upload_response, phase="artifact upload",
                                         budget=upload_budget, cancel_event=cancel_event)
        if not isinstance(upload_json, dict):
            last_error = SubmitError("artifact upload response invalid JSON", retryable=True)
            continue
        return upload_json

    if last_error is not None:
      raise last_error
    raise SubmitError("artifact submission failed", retryable=True)
