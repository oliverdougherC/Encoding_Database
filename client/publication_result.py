"""Safe, typed failure details shared by publication producers and UIs."""

import errno
import re
from typing import Any, Dict, Optional, TypedDict


class PublicationFailure(TypedDict):
    category: str
    operation: str
    retryable: bool
    reason: str
    nextAction: str
    campaignId: str
    runId: str
    statusCode: Optional[int]


_ACTIONS = {
    "rate_limited": "Keep saved work; retry after the server's delay.",
    "server_error": "Keep saved work; retry when the server is available.",
    "network": "Keep saved work; retry when the connection returns.",
    "storage": "Free working space, then publish the saved work again.",
    "publication_deferred": "Wait for the active work or storage constraint, then retry saved publication.",
    "incompatible": "Use the original compatible client for missing envelopes; intact envelopes remain publishable.",
    "corrupt_evidence": "Inspect the affected saved entry; other completed work remains available.",
    "rejected": "Inspect the terminal server verdict and preserve the rejected evidence.",
    "expired": "Inspect expired saved evidence; do not restart its retry deadline.",
    "cancelled": "Restart Publish saved when ready; recorded receipts remain durable.",
    "unexpected": "Inspect the saved campaign and keep its evidence unchanged.",
}


def _safe_reason(value: Any) -> str:
    text = str(value or "").replace("\n", " ").replace("\r", " ")
    text = re.sub(r"https?://\S+", "[endpoint]", text, flags=re.IGNORECASE)
    text = re.sub(r"(?i)\bauthorization\s*[:=]\s*bearer\s+\S+",
                  "[credential redacted]", text)
    text = re.sub(r"(?i)\b(api[_ -]?key|authorization|token)\b\s*[:=]\s*\S+",
                  "[credential redacted]", text)
    text = re.sub(r"(?i)\bbearer\s+\S+", "[credential redacted]", text)
    text = re.sub(r"(?<!\w)(?:[A-Za-z]:\\|/)[^\s:;,]+", "[saved path]", text)
    return " ".join(text.split())[:200] or "Publication could not continue."


def failure_info(
    cause: BaseException | str | Dict[str, Any],
    *,
    operation: str,
    campaign_id: str = "",
    run_id: str = "",
    category: Optional[str] = None,
    retryable: Optional[bool] = None,
) -> PublicationFailure:
    """Normalize every producer to one bounded, non-secret result shape."""
    from .network import SubmitError, SubmissionCancelled
    from .spool import SpoolCapacityError

    raw = cause if isinstance(cause, dict) else {}
    if isinstance(cause, SubmissionCancelled):
        detected = "cancelled"
    elif isinstance(cause, SubmitError):
        code = int(cause.status_code or 0)
        detected = ("rate_limited" if code == 429 else "server_error" if code >= 500
                    else "rejected" if not cause.retryable else "network")
    elif isinstance(cause, SpoolCapacityError):
        detected = "publication_deferred"
    elif isinstance(cause, OSError) and cause.errno in (errno.ENOSPC, errno.EDQUOT):
        detected = "storage"
    elif isinstance(cause, FileNotFoundError):
        detected = "corrupt_evidence"
    elif isinstance(cause, PermissionError):
        detected = "storage"
    elif isinstance(cause, (ConnectionError, TimeoutError, OSError)):
        detected = "network"
    elif isinstance(cause, (ValueError, TypeError, KeyError)):
        detected = "corrupt_evidence"
    else:
        text = str(raw.get("reason") or raw.get("safeReason") or
                   ("publication failed" if isinstance(cause, dict) else cause)).lower()
        if any(word in text for word in ("runtime identity differs", "client identity differs", "protocol identity differs")):
            detected = "incompatible"
        elif "retry_deadline_expired" in text or "retry deadline expired" in text:
            detected = "expired"
        elif any(word in text for word in ("journal", "evidence", "artifact")):
            detected = "corrupt_evidence"
        else:
            detected = "unexpected"
    chosen = str(category or raw.get("category") or detected)
    if chosen not in _ACTIONS:
        chosen = "unexpected"
    can_retry = (bool(raw.get("retryable")) if "retryable" in raw else
                 bool(retryable) if retryable is not None else
                 bool(cause.retryable) if isinstance(cause, SubmitError) else
                 chosen in {"rate_limited", "server_error", "network", "storage", "publication_deferred", "cancelled"})
    reason = _safe_reason(raw.get("reason") or raw.get("safeReason") or
                          ("Publication could not continue." if isinstance(cause, dict) else cause))
    raw_status = raw.get("statusCode") if isinstance(cause, dict) else (
        cause.status_code if isinstance(cause, SubmitError) else None)
    try:
        status_code = int(raw_status)
        if status_code < 100 or status_code > 599:
            status_code = None
    except (TypeError, ValueError):
        status_code = None
    return PublicationFailure(
        category=chosen,
        operation=str(operation)[:60],
        retryable=can_retry,
        reason=reason,
        nextAction=_ACTIONS[chosen],
        campaignId=str(campaign_id or raw.get("campaignId") or "")[:80],
        runId=str(run_id or raw.get("runId") or "")[:80],
        statusCode=status_code,
    )


def failure_text(value: Any) -> str:
    failure = failure_info(value, operation="saved_publication")
    return f"{failure['reason']} {failure['nextAction']}"
