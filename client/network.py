import hashlib
import json
import re
import sys
import threading
import time
import warnings
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin

from . import config

# C12: default wall-clock bound on one submit() transaction chain (token fetches,
# POSTs, redirects and waits). Callers may pass a shorter/longer value.
SUBMIT_TRANSACTION_SECONDS = 90.0

def _load_requests():
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r".*urllib3 v2 only supports OpenSSL.*",
        )
        import requests  # type: ignore
    return requests


class SubmitError(RuntimeError):
    """Transport failure with structured fields (status_code, retry_after).

    C04/C12: public text is bounded and redacted — never raw server bodies,
    tokens or URLs. Raw response bodies stay private in `_server_body` for
    diagnostics only; they must not reach exception text or GUI events.
    """

    _MAX_MESSAGE_CHARS = 300
    _MAX_BODY_CHARS = 4096

    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        status_code: Optional[int] = None,
        body: str = "",
        retry_after: float = 0.0,
    ) -> None:
        super().__init__(str(message or "")[: self._MAX_MESSAGE_CHARS])
        self.retryable = retryable
        self.status_code = status_code
        self._server_body = str(body or "")[: self._MAX_BODY_CHARS]
        self.retry_after = retry_after


class SubmissionCancelled(SubmitError):
    """Cooperative cancellation (C12). Retryable by contract: the durable spool
    keeps the entry and its localHash identity so replay is idempotent."""

    def __init__(self, phase: str) -> None:
        super().__init__(f"submission cancelled during {phase}", retryable=True)
        self.phase = phase


def _event_cancelled(cancel_event: Optional[Any]) -> bool:
    if cancel_event is None:
        return False
    try:
        return bool(cancel_event.is_set())
    except Exception:
        return False


def _run_cancellable(func: Callable[[], Any], *, phase: str,
                     cancel_event: Optional[Any], deadline: Optional[float],
                     bound_seconds: float,
                     poll_seconds: float = 0.05) -> Any:
    """Run a blocking HTTP call in a daemon worker so cooperative cancellation
    is observed within ~poll_seconds even while the call is socket-blocked.

    The worker always carries a socket inactivity timeout at most the phase
    budget, so an abandoned worker cannot outlive that budget against a
    stalled peer — no orphan workers, no monkey-patching. If cancel wins the
    race the connection may have been fully sent (ambiguous outcome); the
    durable spool keeps the entry and replays it idempotently."""
    done = threading.Event()
    outcome: List[Any] = []

    def _worker() -> None:
        try:
            outcome.append(("ok", func()))
        except BaseException as exc:  # noqa: BLE001 — re-raised in caller
            outcome.append(("err", exc))
        finally:
            done.set()

    threading.Thread(target=_worker, name=f"encodingdb-{phase}", daemon=True).start()
    while not done.wait(poll_seconds):
        if _event_cancelled(cancel_event):
            raise SubmissionCancelled(phase)
        remaining = _remaining_seconds(deadline)
        if remaining is not None and remaining <= 0:
            raise SubmitError(f"{phase} exceeded {bound_seconds:g}s wall-clock bound",
                              retryable=True)
    kind, value = outcome[0]
    if kind == "err":
        raise value
    return value


def _remaining_seconds(deadline: Optional[float]) -> Optional[float]:
    if deadline is None:
        return None
    return deadline - time.monotonic()


def _check_transaction(cancel_event: Optional[Any], deadline: Optional[float],
                       phase: str, bound: float) -> None:
    """Cooperative cancel + wall-clock bound check between blocking steps."""
    if _event_cancelled(cancel_event):
        raise SubmissionCancelled(phase)
    remaining = _remaining_seconds(deadline)
    if remaining is not None and remaining <= 0:
        raise SubmitError(f"{phase} exceeded {bound:g}s wall-clock bound", retryable=True)


def _bounded_wait(seconds: float, cancel_event: Optional[Any], deadline: Optional[float],
                  phase: str, bound: float) -> None:
    """Backoff sleep that wakes on cancellation and respects the deadline."""
    remaining = _remaining_seconds(deadline)
    if remaining is not None:
        seconds = min(seconds, max(0.0, remaining))
    wait = getattr(cancel_event, "wait", None)
    if callable(wait):
        try:
            if wait(seconds):
                raise SubmissionCancelled(phase)
        except SubmissionCancelled:
            raise
        except Exception:
            if seconds > 0:
                time.sleep(seconds)
    elif seconds > 0:
        time.sleep(seconds)
    _check_transaction(cancel_event, deadline, phase, bound)


def _get_submit_token_headers(requests: Any, base_url: str, *,
                              cancel_event: Optional[Any] = None,
                              deadline: Optional[float] = None) -> Dict[str, str]:
    """Fetch and solve a one-time token for exactly one POST attempt.

    C12: cancellation- and deadline-aware — each endpoint GET and the PoW loop
    check cancel/deadline so a Stop does not wait out the full 30 s solve."""
    headers: Dict[str, str] = {}
    try:
        base = base_url.rstrip('/')
        endpoints = [
            f"{base}/health/token",
            f"{base}/submit-token",
            f"{base}/submit/token",
        ]
        token_resp = None
        for endpoint in endpoints:
            _check_transaction(cancel_event, deadline, "token fetch", SUBMIT_TRANSACTION_SECONDS)
            try:
                remaining = _remaining_seconds(deadline)
                timeout = 10 if remaining is None else max(0.1, min(10.0, remaining))
                response = requests.get(endpoint, timeout=timeout, verify=config.REQUESTS_VERIFY)
                if response.status_code == 200:
                    token_resp = response
                    break
            except SubmissionCancelled:
                raise
            except Exception:
                continue
        if token_resp is None:
            return headers

        token_data = token_resp.json() or {}
        token = str(token_data.get('token') or '')
        if not re.fullmatch(r"[0-9a-f]{32}", token):
            return headers
        headers['x-ingest-token'] = token

        pow_info = token_data.get('pow') or {}
        try:
            difficulty = int(pow_info.get('difficulty') or 0)
        except Exception:
            difficulty = 0
        if difficulty <= 0:
            return headers

        prefix = '0' * difficulty
        nonce = 0
        max_iters = 500000
        pow_timeout = 30.0
        pow_start = time.time()
        print(f"  Solving Proof-of-Work (difficulty={difficulty})...", end='', flush=True)
        while nonce < max_iters:
            if nonce % 10000 == 0:
                if _event_cancelled(cancel_event):
                    print(" cancelled")
                    raise SubmissionCancelled("proof-of-work")
                remaining_pow = _remaining_seconds(deadline)
                if remaining_pow is not None and remaining_pow <= 0:
                    print(" deadline reached")
                    raise SubmitError("proof-of-work exceeded transaction bound",
                                      retryable=True)
                elapsed_pow = time.time() - pow_start
                if elapsed_pow > pow_timeout:
                    print(f" timeout after {elapsed_pow:.1f}s")
                    return {}
                if nonce > 0 and nonce % 100000 == 0:
                    print(f" {nonce//1000}k", end='', flush=True)
            test = hashlib.sha256(f"{token}.{nonce}".encode('utf-8')).hexdigest()
            if test.startswith(prefix):
                headers['x-ingest-nonce'] = str(nonce)
                print(f" solved (nonce={nonce})")
                return headers
            nonce += 1
        print(f" exhausted {max_iters} iterations without solution")
        return {}
    except SubmissionCancelled:
        raise
    except SubmitError:
        raise
    except Exception as exc:
        try:
            print(f"token fetch error: {type(exc).__name__}", file=sys.stderr)
        except Exception:
            pass
        return {}


def _response_error_text(requests: Any, response: Any, cancel_event: Optional[Any],
                         deadline: Optional[float], max_bytes: int = 65536) -> str:
    """Read an error body for the private field, cancellable and size-capped."""
    chunks: List[bytes] = []
    total = 0
    try:
        for chunk in response.iter_content(chunk_size=8192):
            _check_transaction(cancel_event, deadline, "response read", SUBMIT_TRANSACTION_SECONDS)
            if not chunk:
                continue
            take = max(0, max_bytes - total)
            if take:
                chunks.append(bytes(chunk[:take]))
            total += len(chunk)
    except SubmissionCancelled:
        raise
    except Exception:
        pass
    text = b"".join(chunks).decode("utf-8", "replace")
    if total > max_bytes:
        text += f"...[truncated {total - max_bytes} bytes]"
    return text


def submit(base_url: str, payload: Dict[str, Any], api_key: str = "", retries: int = 3,
           backoff_seconds: float = 1.0, use_token: Optional[bool] = None,
           cancel_event: Optional[Any] = None,
           transaction_seconds: float = SUBMIT_TRANSACTION_SECONDS) -> None:
    """POST a payload with bounded, cancellable retries (C12).

    `cancel_event` (threading.Event-like) and `transaction_seconds` cap the
    whole attempt chain on a monotonic wall clock: every step between blocking
    calls checks both, and each socket step gets at most the remaining budget
    as its inactivity timeout. Cancellation raises SubmissionCancelled
    (retryable) so the durable spool keeps identity."""
    requests = _load_requests()
    url = f"{base_url.rstrip('/')}/submit"
    payload_to_send: Dict[str, Any] = dict(payload)
    deadline = time.monotonic() + max(1.0, float(transaction_seconds))

    def step_timeout() -> float:
        remaining = _remaining_seconds(deadline)
        if remaining is None:
            return 30
        if remaining <= 0:
            raise SubmitError(f"submit exceeded {transaction_seconds:g}s wall-clock bound",
                              retryable=True)
        return max(0.1, min(30.0, remaining))

    base_headers: Dict[str, str] = {"Content-Type": "application/json"}
    if use_token is None:
        use_token = config._env_flag('INGEST_USE_TOKENS', False)
    # HMAC signing if secret available
    secret = config.ENV_INGEST_HMAC_SECRET

    attempt = 1
    last_hmac_timestamp = 0
    while attempt <= retries:
        _check_transaction(cancel_event, deadline, "submit", transaction_seconds)
        body = json.dumps(payload_to_send, separators=(",", ":"))
        headers = dict(base_headers)
        if use_token:
            headers.update(_get_submit_token_headers(requests, base_url,
                                                     cancel_event=cancel_event, deadline=deadline))
        if secret:
            import hmac
            ts = max(int(time.time()), last_hmac_timestamp + 1)
            last_hmac_timestamp = ts
            sig = hmac.new(secret.encode("utf-8"), f"{ts}.".encode("utf-8") + body.encode("utf-8"), hashlib.sha256).hexdigest()
            headers["x-signature"] = sig
            headers["x-timestamp"] = str(ts)
        try:
            r = _run_cancellable(
                lambda: requests.post(url, data=body, timeout=step_timeout(), headers=headers, verify=config.REQUESTS_VERIFY, allow_redirects=False, stream=True),
                phase="submit", cancel_event=cancel_event, deadline=deadline,
                bound_seconds=transaction_seconds)
            if 300 <= r.status_code < 400:
                loc = r.headers.get('Location') or r.headers.get('location')
                if loc:
                    redirect_url = urljoin(url, loc)
                    redirect_headers = dict(base_headers)
                    if use_token:
                        redirect_headers.update(_get_submit_token_headers(requests, base_url,
                                                                          cancel_event=cancel_event, deadline=deadline))
                    if secret:
                        import hmac
                        redirect_ts = max(int(time.time()), last_hmac_timestamp + 1)
                        last_hmac_timestamp = redirect_ts
                        redirect_sig = hmac.new(secret.encode("utf-8"), f"{redirect_ts}.".encode("utf-8") + body.encode("utf-8"), hashlib.sha256).hexdigest()
                        redirect_headers["x-signature"] = redirect_sig
                        redirect_headers["x-timestamp"] = str(redirect_ts)
                    _check_transaction(cancel_event, deadline, "submit redirect", transaction_seconds)
                    r = _run_cancellable(
                        lambda: requests.post(redirect_url, data=body, timeout=step_timeout(), headers=redirect_headers, verify=config.REQUESTS_VERIFY, allow_redirects=False, stream=True),
                        phase="submit redirect", cancel_event=cancel_event, deadline=deadline,
                        bound_seconds=transaction_seconds)
            if r.status_code == 429:
                try:
                    ra = r.headers.get('Retry-After')
                    delay = float(ra) if ra and str(ra).replace('.', '', 1).isdigit() else (backoff_seconds * attempt * 2)
                except Exception:
                    delay = backoff_seconds * attempt * 2
                if attempt >= retries:
                    raise SubmitError(
                        f"submit rate limited ({r.status_code})",
                        retryable=True,
                        status_code=r.status_code,
                        body=_response_error_text(requests, r, cancel_event, deadline),
                        retry_after=delay,  # durable spool keeps the server's own wait (C08)
                    )
                _bounded_wait(max(0.5, delay), cancel_event, deadline, "submit retry wait", transaction_seconds)
                attempt += 1
                continue
            if r.status_code >= 500:
                error_body = _response_error_text(requests, r, cancel_event, deadline)
                if attempt >= retries:
                    raise SubmitError(
                        f"server_error {r.status_code}",
                        retryable=True,
                        body=error_body,
                        retry_after=retry_after_seconds(r.headers),
                    )
                raise RuntimeError(f"server_error {r.status_code}")
            if r.status_code >= 400:
                raise SubmitError(
                    f"submit rejected ({r.status_code})",
                    retryable=False,
                    status_code=r.status_code,
                    body=_response_error_text(requests, r, cancel_event, deadline),
                )
            r.raise_for_status()
            return
        except SubmissionCancelled:
            raise
        except Exception as e:
            retryable = True
            status_code: Optional[int] = None
            body = ""
            if isinstance(e, SubmitError):
                retryable = e.retryable
                status_code = e.status_code
                body = e._server_body
            if attempt == retries:
                # C04: never echo server bodies; status/content-type/length only.
                status_for_print = status_code
                detail = ""
                try:
                    _req = _load_requests()
                    if isinstance(e, _req.HTTPError) and getattr(e, 'response', None) is not None:
                        resp = e.response
                        status_for_print = resp.status_code
                        detail = f" content_type={resp.headers.get('content-type', '')} bytes={len(resp.content or b'')}"
                except Exception:
                    pass
                sent_token = 'x-ingest-token' in headers
                sent_nonce = 'x-ingest-nonce' in headers
                print(
                    f"submit failed (status={status_for_print}{detail}; sent_token={sent_token}, sent_nonce={sent_nonce})",
                    file=sys.stderr,
                )
                if isinstance(e, SubmitError):
                    raise
                # Never put exception str() (may embed URLs/tokens) straight into
                # the message: type + safe shape only.
                raise SubmitError(
                    f"submit failed: {type(e).__name__}",
                    retryable=True,
                    status_code=status_code,
                ) from e
            if isinstance(e, SubmitError) and not retryable:
                raise
            _bounded_wait(backoff_seconds * attempt, cancel_event, deadline, "submit retry wait", transaction_seconds)
            attempt += 1


def fetch_baseline_rows(base_url: str) -> List[Dict[str, Any]]:
    with config._GLOBAL_STATE_LOCK:
        if config._BASELINE_ROWS_CACHE is not None:
            elapsed = time.time() - config._BASELINE_ROWS_CACHE_TS
            if elapsed < config._BASELINE_ROWS_CACHE_TTL:
                return config._BASELINE_ROWS_CACHE
            # TTL expired — clear cache and re-fetch
            config._BASELINE_ROWS_CACHE = None

    try:
        requests = _load_requests()
        url = f"{base_url.rstrip('/')}/query?limit=500"
        r = requests.get(url, timeout=15, verify=config.REQUESTS_VERIFY)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                with config._GLOBAL_STATE_LOCK:
                    config._BASELINE_ROWS_CACHE = data
                    config._BASELINE_ROWS_CACHE_TS = time.time()
                return data
    except Exception:
        pass

    with config._GLOBAL_STATE_LOCK:
        config._BASELINE_ROWS_CACHE = []
        config._BASELINE_ROWS_CACHE_TS = time.time()
    return []


def check_compatibility(base_url: str, client_version: str) -> Dict[str, Any]:
    from .suite import load_suite_pack_metadata, SUITE_VERSION
    response = _load_requests().get(f"{base_url.rstrip('/')}/v7/compatibility", timeout=10,
                                    verify=config.REQUESTS_VERIFY, allow_redirects=False)
    if response.status_code != 200:
        raise SubmitError(f"Compatibility endpoint returned {response.status_code}", retryable=True,
                          status_code=response.status_code)
    contract = response.json()
    def version(value):
        return tuple(int(part) for part in str(value).removeprefix("client/").split("."))
    if (contract.get("protocolVersion") != config.BENCHMARK_PROTOCOL_VERSION
            or contract.get("encodeTimerBoundary") != "ffmpeg-process-v1"
            or contract.get("sourceSuiteVersion") != SUITE_VERSION
            or contract.get("suiteFingerprint") != load_suite_pack_metadata().get("suiteFingerprint")
            or version(client_version) < version(contract.get("minimumClientVersion", "999.0.0"))):
        raise SubmitError("Client/protocol incompatible with current collection epoch; update the client", retryable=False)
    return contract


def retry_after_seconds(headers) -> float:
    from email.utils import parsedate_to_datetime
    value = str(headers.get("Retry-After") or headers.get("retry-after") or "").strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
        except (ValueError, TypeError, OverflowError):
            return 0.0
