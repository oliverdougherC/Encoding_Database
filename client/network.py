import base64
import contextvars
import hashlib
import json
import os
import re
import socket
import subprocess
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

# R05: owned-worker lifecycle. Transport workers are registered process-wide;
# an operation that owns a phase/exclusion scope reaps its workers on release
# (bounded sync join up to WORKER_QUIESCE_SYNC_JOIN_SECONDS). If a worker is
# still mid-I/O past that window, the scope's exclusion ownership is retained
# (deferred releaser) until the worker is quiescent, so a cancelled or
# timed-out worker can never perform I/O after ownership moved on.
WORKER_QUIESCE_SYNC_JOIN_SECONDS = 1.0

# R04: hard cap on bytes CONSUMED from an error/aux response body (the
# retained text is additionally truncated by SubmitError). Consumption stops
# at the cap, the actual deadline, or cancellation — then the response is
# closed to interrupt any blocked read and return the connection.
ERROR_BODY_HARD_CAP_BYTES = 65536
JSON_BODY_HARD_CAP_BYTES = 1 << 22
# F3: bounded synchronous quiescence wait offered to the measurement barrier
# before any timed encode (retained metadata cleanup windows).
METADATA_QUIESCE_WAIT_SECONDS = 5.0

# F3: default wall-clock bound on ONE online bootstrap metadata GET
# (compatibility/baseline) — DNS, connect, headers and body TOGETHER. Unlike
# a requests per-inactivity timeout, this absolute deadline is enforced even
# while bytes keep arriving, and Stop interrupts it at any phase.
METADATA_TRANSACTION_SECONDS = 10.0


_OWNED_WORKERS: set = set()
_OWNED_WORKERS_LOCK = threading.Lock()
_ACTIVE_WORKER_PHASE: contextvars.ContextVar = contextvars.ContextVar(
    "encodingdb_owned_worker_phase", default=None)


def owned_worker_census() -> int:
    """Process-wide count of live transport workers (ownership census, R05)."""
    with _OWNED_WORKERS_LOCK:
        return sum(1 for record in _OWNED_WORKERS if record.alive)


class _WorkerRecord:
    """One owned transport worker: thread + completion latch."""

    def __init__(self, phase: str) -> None:
        self.phase = phase
        self.thread: Optional[threading.Thread] = None
        self.done = threading.Event()
        # Set by the caller exactly when it abandons the call (cancel or
        # deadline). The worker checks it after func() returns so a response
        # that will never be delivered is closed by the worker itself.
        self.abandoned = False

    @property
    def alive(self) -> bool:
        return not self.done.is_set()


class WorkerGroup:
    """Workers owned by one operation scope (R05).

    Release semantics: the scope holder calls `end_owned_worker_phase` which
    reaps owned workers with a bounded sync join (WORKER_QUIESCE_SYNC_JOIN_
    SECONDS). If any worker is still mid-I/O past that window it is handed to
    a background releaser that joins it (its own socket timeout bounds the
    wait) and only then invokes the scope's release callback — so exclusion
    ownership is retained, never released, while an owned worker can still
    perform I/O."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: List[_WorkerRecord] = []
        self.token: Optional[Any] = None

    def _register(self, record: _WorkerRecord) -> None:
        with self._lock:
            self._records.append(record)

    def await_quiescence(self, sync_join_seconds: float) -> bool:
        """True when every owned worker finished within the join window."""
        deadline = time.monotonic() + max(0.0, float(sync_join_seconds))
        while True:
            with self._lock:
                pending = [record for record in self._records if not record.done.is_set()]
            if not pending:
                return True
            for record in pending:
                record.thread.join(max(0.001, deadline - time.monotonic()))
            if time.monotonic() >= deadline:
                with self._lock:
                    return not any(record.done.is_set() is False
                                   for record in self._records)

    def stragglers(self) -> List[_WorkerRecord]:
        with self._lock:
            return [record for record in self._records if not record.done.is_set()]

    def _release_when_quiescent(self, records: List[_WorkerRecord],
                                release: Callable[[], None]) -> None:
        try:
            for record in records:
                # Bounded by the worker's own socket timeout: an abandoned
                # worker cannot outlive its phase budget against a stalled peer.
                record.thread.join()
        finally:
            release()


def begin_owned_worker_phase() -> Optional[WorkerGroup]:
    """Open an owned-worker phase on the calling thread (R05).

    Returns the group to close with `end_owned_worker_phase`, or None when an
    outer phase is already active in this thread — nested operations
    (collector checkpoint uploads inside a held batch, per-entry submits
    inside a replay pass) register with the outer phase, which owns
    quiescence."""
    if _ACTIVE_WORKER_PHASE.get() is not None:
        return None
    group = WorkerGroup()
    group.token = _ACTIVE_WORKER_PHASE.set(group)
    return group


def await_owned_worker_quiescence(timeout_seconds: float) -> bool:
    """F2 barrier: bounded wait until the calling thread's active owned-worker
    phase is quiescent.

    True when every worker registered with the active phase finished within
    the window; False when a straggler is still mid-I/O (upload, response
    read or connection close). A caller about to start timing-sensitive work
    must not proceed on False — it defers/pauses instead, keeping the
    durable queue and journal intact. No active phase means quiescence:
    workers owned by a closed phase are already retained by their deferred
    releaser, which holds that phase's exclusion until they finish."""
    group = _ACTIVE_WORKER_PHASE.get()
    if group is None:
        return True
    return group.await_quiescence(timeout_seconds)


def end_owned_worker_phase(group: Optional[WorkerGroup],
                           release: Callable[[], None]) -> bool:
    """Close an owned-worker phase; run `release` only once owned workers are
    quiescent. Returns True when released synchronously, False when the
    release was deferred to a background joiner (exclusion stays held).

    The phase contextvar is always reset on the path that owns it, so a
    later phase on the same thread opens a fresh group instead of silently
    attaching to a closed one (which would release exclusion while its own
    cancelled worker was still mid-I/O)."""
    if group is None:
        release()
        return True
    try:
        if group.await_quiescence(WORKER_QUIESCE_SYNC_JOIN_SECONDS):
            release()
            return True
        stragglers = group.stragglers()
        threading.Thread(target=group._release_when_quiescent,
                         args=(stragglers, release),
                         name="encodingdb-worker-releaser", daemon=True).start()
        return False
    finally:
        _ACTIVE_WORKER_PHASE.reset(group.token)


def _register_worker(record: _WorkerRecord) -> None:
    with _OWNED_WORKERS_LOCK:
        _OWNED_WORKERS.add(record)
    group = _ACTIVE_WORKER_PHASE.get()
    if group is not None:
        group._register(record)


def _unregister_worker(record: _WorkerRecord) -> None:
    with _OWNED_WORKERS_LOCK:
        _OWNED_WORKERS.discard(record)


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



class MetadataRetentionHeld(SubmitError):
    """F3 fail-closed: metadata child cleanup could NOT confirm actual
    child/reader quiescence (kill/wait/close failed). The child stays
    registered and its deferred reaper is an owned worker, so the caller
    must pause rather than treat the lookup as merely absent — a retryable
    transport failure must never let timed encodes start against live
    owned transport I/O."""

    def __init__(self, phase: str) -> None:
        super().__init__(f"{phase} retained owned transport work; pausing",
                         retryable=True)
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
    stalled peer. R05: the worker is registered in the process-wide census and
    in the caller thread's WorkerGroup (when one is active), so the scope that
    owns exclusion rights reaps it on release — or retains ownership until it
    is quiescent. If cancel wins the race the connection may have been fully
    sent (ambiguous outcome); the durable spool keeps the entry and replays it
    idempotently."""
    outcome: List[Any] = []
    record = _WorkerRecord(phase)
    handoff = threading.Lock()
    _register_worker(record)
    def _close_late(value: Any) -> None:
        closer = getattr(value, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass

    def _worker() -> None:
        try:
            value = func()
            outcome.append(("ok", value))
        except BaseException as exc:  # noqa: BLE001 — re-raised in caller
            outcome.append(("err", exc))
        finally:
            try:
                # Closing an abandoned response is still owned transport I/O.
                # Keep the worker live until it finishes so the host phase
                # cannot release its exclusion lock during close().
                with handoff:
                    if record.abandoned and outcome and outcome[0][0] == "ok":
                        _close_late(outcome[0][1])
            finally:
                record.done.set()
                _unregister_worker(record)
    record.thread = threading.Thread(target=_worker, name=f"encodingdb-{phase}",
                                     daemon=True)
    record.thread.start()
    try:
        while not record.done.wait(poll_seconds):
            if _event_cancelled(cancel_event):
                raise SubmissionCancelled(phase)
            remaining = _remaining_seconds(deadline)
            if remaining is not None and remaining <= 0:
                raise SubmitError(f"{phase} exceeded {bound_seconds:g}s wall-clock bound",
                                  retryable=True)
    except BaseException:
        # R05: this call is abandoned. Under `handoff` either the worker has
        # not produced a response yet (flag closes any late one when it
        # lands) or it already has (closed here, now). The owning WorkerGroup
        # reaps the thread before exclusion is released.
        with handoff:
            record.abandoned = True
            if outcome and outcome[0][0] == "ok":
                _close_late(outcome[0][1])
        raise
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
                response.close()
            except SubmissionCancelled:
                raise
            except Exception:
                continue
        if token_resp is None:
            return headers

        try:
            token_data = token_resp.json() or {}
        finally:
            token_resp.close()
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


def _read_response_body(requests: Any, response: Any, cancel_event: Optional[Any],
                        deadline: Optional[float],
                        max_bytes: int = ERROR_BODY_HARD_CAP_BYTES) -> str:
    """Consume an error/aux body under the ACTUAL deadline (R04).

    Consumption stops at the hard byte cap, the caller's real remaining
    deadline, or cancellation — whichever comes first — and the response is
    always closed. A separate monitor thread closes the socket when a chunk
    read blocks past the deadline/cancel (iter_content only checks between
    chunks, so a drip-fed or silent peer would otherwise pin the read).
    Raises SubmissionCancelled on cancel and SubmitError (retryable) on
    deadline; other socket errors end the read with what was consumed."""
    state = {"cancelled": False, "deadline": False}
    done = threading.Event()

    def _close() -> None:
        # Interrupt a peer-blocked read immediately: response.close() alone only
        # returns after the socket timeout (the kernel recv is already parked).
        # shutdown(SHUT_RDWR) on the live socket wakes it in ~0 ms; close then
        # releases the connection. Every step is best-effort — a finished or
        # half-torn-down connection raising here is normal.
        raw = getattr(response, "raw", None)
        sock = getattr(getattr(raw, "connection", None), "sock", None)
        if sock is None:
            orig = getattr(raw, "_original_response", None)
            fp = getattr(orig, "fp", None)
            candidate = getattr(getattr(fp, "raw", None), "_sock", None)
            sock = candidate if isinstance(candidate, socket.socket) else None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        try:
            response.close()
        except Exception:
            pass

    def _watch() -> None:
        poll = 0.05
        while not done.wait(poll):
            if _event_cancelled(cancel_event):
                state["cancelled"] = True
                _close()
                return
            remaining = _remaining_seconds(deadline)
            if remaining is not None and remaining <= 0:
                state["deadline"] = True
                _close()
                return

    watcher = None
    if cancel_event is not None or deadline is not None:
        # The watcher can still be closing the connection after its bounded
        # join returns. Register it in the caller's phase before starting it,
        # so measurement and phase release wait for that close as well.
        record = _WorkerRecord("response read close")

        def _owned_watch() -> None:
            try:
                _watch()
            finally:
                record.done.set()
                _unregister_worker(record)

        watcher = threading.Thread(target=_owned_watch,
                                   name="encodingdb-error-body-watch", daemon=True)
        record.thread = watcher
        _register_worker(record)
        try:
            watcher.start()
        except BaseException:
            record.done.set()
            _unregister_worker(record)
            raise
    chunks: List[bytes] = []
    total = 0
    overshoot = 0
    try:
        # R04: hard consumed-byte cap. Request exactly the remaining budget so
        # a compliant producer never reads past it, and stop consuming the
        # moment the cap is crossed even if a producer yields more than asked.
        iterator = iter(response.iter_content(chunk_size=max(1, max_bytes)))
        while total < max_bytes:
            if state["cancelled"]:
                break
            try:
                chunk = next(iterator)
            except StopIteration:
                break
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                overshoot = total - max_bytes
                chunk = chunk[:max_bytes - (total - len(chunk))]
            chunks.append(bytes(chunk))
    except Exception:
        pass
    finally:
        done.set()
        _close()
        if watcher is not None:
            watcher.join(0.5)
    if state["cancelled"]:
        raise SubmissionCancelled("response read")
    if state["deadline"]:
        raise SubmitError("response read exceeded remaining deadline", retryable=True)
    text = b"".join(chunks).decode("utf-8", "replace")
    if overshoot:
        text += f"...[truncated {overshoot} bytes]"
    return text






def _bounded_error_body(requests: Any, response: Any, cancel_event: Optional[Any],
                        deadline: Optional[float],
                        max_bytes: int = ERROR_BODY_HARD_CAP_BYTES) -> str:
    """Error body for a structured error that is already decided from headers.

    Deadline exhaustion while reading discards the body (""), preserving the
    status/retry_after verdict; cancellation still propagates so the caller
    records a cancelled phase."""
    try:
        return _read_response_body(requests, response, cancel_event, deadline,
                                   max_bytes=max_bytes)
    except SubmissionCancelled:
        raise
    except SubmitError:
        return ""


def submit(base_url: str, payload: Dict[str, Any], api_key: str = "", retries: int = 3,
           backoff_seconds: float = 1.0, use_token: Optional[bool] = None,
           cancel_event: Optional[Any] = None,
           transaction_seconds: float = SUBMIT_TRANSACTION_SECONDS,
           deadline: Optional[float] = None) -> None:
    """POST a payload with bounded, cancellable retries (C12).

    `cancel_event` (threading.Event-like) and `transaction_seconds` cap the
    whole attempt chain on a monotonic wall clock: every step between blocking
    calls checks both, and each socket step gets at most the remaining budget
    as its inactivity timeout. `deadline` (monotonic) lets a caller impose a
    tighter real deadline than the transaction budget; the effective deadline
    is the earlier of the two. Cancellation raises SubmissionCancelled
    (retryable) so the durable spool keeps identity. Every response object is
    closed on every path (R04)."""
    requests = _load_requests()
    url = f"{base_url.rstrip('/')}/submit"
    payload_to_send: Dict[str, Any] = dict(payload)
    bound_deadline = time.monotonic() + max(1.0, float(transaction_seconds))
    deadline = bound_deadline if deadline is None else min(deadline, bound_deadline)

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
        resp_for_close: List[Any] = []
        try:
            r = _run_cancellable(
                lambda: requests.post(url, data=body, timeout=step_timeout(), headers=headers, verify=config.REQUESTS_VERIFY, allow_redirects=False, stream=True),
                phase="submit", cancel_event=cancel_event, deadline=deadline,
                bound_seconds=transaction_seconds)
            resp_for_close.append(r)
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
                    prev = r
                    r = _run_cancellable(
                        lambda: requests.post(redirect_url, data=body, timeout=step_timeout(), headers=redirect_headers, verify=config.REQUESTS_VERIFY, allow_redirects=False, stream=True),
                        phase="submit redirect", cancel_event=cancel_event, deadline=deadline,
                        bound_seconds=transaction_seconds)
                    try:
                        prev.close()
                    except Exception:
                        pass
                    resp_for_close.append(r)
            if r.status_code == 429:
                # The server's own wait is decided from headers BEFORE the
                # body: a hostile body must not erase retry_after (C08/R04).
                delay = retry_after_seconds(r.headers)
                if delay <= 0:
                    delay = backoff_seconds * attempt * 2
                if attempt >= retries:
                    raise SubmitError(
                        f"submit rate limited ({r.status_code})",
                        retryable=True,
                        status_code=r.status_code,
                        body=_bounded_error_body(requests, r, cancel_event, deadline),
                        retry_after=delay,  # durable spool keeps the server's own wait (C08)
                    )
                _bounded_wait(max(0.5, delay), cancel_event, deadline, "submit retry wait", transaction_seconds)
                attempt += 1
                continue
            if r.status_code >= 500:
                error_body = _bounded_error_body(requests, r, cancel_event, deadline)
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
                    body=_bounded_error_body(requests, r, cancel_event, deadline),
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
                # C04: never echo server bodies; status/content-type only —
                # no resp.content drain (R04: unbounded body consumption).
                status_for_print = status_code
                detail = ""
                try:
                    _req = _load_requests()
                    if isinstance(e, _req.HTTPError) and getattr(e, 'response', None) is not None:
                        resp = e.response
                        status_for_print = resp.status_code
                        detail = f" content_type={resp.headers.get('content-type', '')}"
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
        finally:
            for resp in resp_for_close:
                try:
                    resp.close()
                except Exception:
                    pass


METADATA_CHILD_ARGV = "--metadata-child"
_OWNED_METADATA_CHILDREN: set = set()
_OWNED_METADATA_CHILDREN_LOCK = threading.Lock()


def owned_metadata_children() -> int:
    """Live owned metadata child processes (quiescence census for F3)."""
    with _OWNED_METADATA_CHILDREN_LOCK:
        return sum(1 for proc in _OWNED_METADATA_CHILDREN if proc.poll() is None)


def _register_metadata_child(proc: Any) -> None:
    with _OWNED_METADATA_CHILDREN_LOCK:
        _OWNED_METADATA_CHILDREN.add(proc)


def _unregister_metadata_child(proc: Any) -> None:
    with _OWNED_METADATA_CHILDREN_LOCK:
        _OWNED_METADATA_CHILDREN.discard(proc)


def metadata_child_invocation_phase(argv: List[str]) -> Optional[str]:
    """Recognize the private child-dispatch shape at startup (F3).

    Position-anchored and length-exact — exactly `[executable,
    --metadata-child, <phase>]` as spawned by `_run_owned_metadata_child`
    — checked against the RAW OS argv of each entry point BEFORE the GUI
    wrapper prepends `--gui`. Ordinary CLI values can never enter the
    helper and block on stdin: `--base-url --metadata-child`, a bare
    trailing marker, or a marker behind `--gui` is rejected and reaches
    argparse as an unknown argument instead."""
    if len(argv) != 3 or argv[1] != METADATA_CHILD_ARGV:
        return None
    phase = argv[2]
    if not phase or phase.startswith("-"):
        return None
    return phase


def wait_for_metadata_quiescence(timeout_seconds: float,
                                 cancel_event: Optional[Any] = None) -> bool:
    """True once every owned metadata child is CONFIRMED dead (census 0).

    The measurement-side F3 barrier: children unregister only after actual
    death is observed, so census 0 means no owned metadata transport I/O
    can still be in flight. Used before any timed encode starts. Returns
    False on operator Stop so the caller surfaces the interrupt rather than
    waiting out the bound."""
    until = time.monotonic() + max(0.0, float(timeout_seconds))
    while True:
        if owned_metadata_children() == 0:
            return True
        if _event_cancelled(cancel_event):
            return False
        if time.monotonic() >= until:
            return owned_metadata_children() == 0
        time.sleep(0.05)


def _reap_metadata_child(proc: Any, reader: Optional[threading.Thread],
                         record: "_WorkerRecord") -> None:
    """Deferred cleanup owner for one RETAINED metadata child.

    Reached only when synchronous cleanup could not confirm actual child
    death (kill/wait failed — SIGKILL-ignored or pathological). Keeps
    polling until proc.poll() reports a real exit, joins the pipe reader
    (it quiesces at child death / EOF), and only then unregisters from
    the children census, so the census never undercounts live transport
    work. The record's done latch is set only after confirmed death, so
    the owning WorkerGroup defers its release (and the measurement
    barrier keeps waiting) until this reap finishes."""
    try:
        while proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                time.sleep(0.25)  # a stubbed/pathological wait may raise instantly
                continue
            except Exception:
                time.sleep(0.25)
        if reader is not None:
            reader.join()
    finally:
        _unregister_metadata_child(proc)
        _unregister_worker(record)
        record.done.set()


def _retain_metadata_child(proc: Any, reader: Optional[threading.Thread],
                           phase: str) -> None:
    """Fail-closed retention: hand an unconfirmed-dead child to a deferred
    reaper registered as an OWNED WORKER (F1 group semantics).

    If a WorkerGroup is active on this thread (collector publication hold /
    preparation transport), the reaper record joins it, so releasing that
    phase — including the kernel host-phase lock — is deferred until the
    reaper confirms actual child death. The children census keeps counting
    the child until then, so the F3 measurement barrier (`wait_for_metadata_
    quiescence`) refuses to start timed encodes against it. Registration is
    safe from concurrent joins: the group's owner thread is the caller and
    cannot be inside `await_quiescence` while this runs."""
    record = _WorkerRecord(phase)
    reaper = threading.Thread(target=_reap_metadata_child,
                              args=(proc, reader, record),
                              name=f"encodingdb-metadata-reap-{phase}",
                              daemon=True)
    record.thread = reaper
    _register_worker(record)
    reaper.start()


METADATA_CHILD_STALL_ENV = "ENCODINGDB_METADATA_CHILD_STALL_FILE"


def _child_maybe_stall() -> None:
    """TEST-ONLY fault hook: when ENCODINGDB_METADATA_CHILD_STALL_FILE names
    a control file, wait until that file appears before issuing the GET.
    It emulates the deterministic core of a hung resolver / stalled connect:
    a phase with NO allocated socket, which only killing this process can
    stop. Production never sets the variable; the hook is inert otherwise."""
    control = os.environ.get(METADATA_CHILD_STALL_ENV)
    if not control:
        return
    deadline = time.monotonic() + 60.0
    while not os.path.exists(control) and time.monotonic() < deadline:
        time.sleep(0.02)


def _child_perform_get(request: Dict[str, Any]) -> Dict[str, Any]:
    """One streaming metadata GET inside the owned child process.

    Trust boundaries are unchanged: original URL (so hostname, SNI and
    certificate verification are exactly requests' own), `verify=
    config.REQUESTS_VERIFY` (bundled certifi / CA-bundle pin) and
    `allow_redirects=False`. Proxy behavior is requests' default: the child
    inherits the parent environment, so HTTP(S)_PROXY/NO_PROXY apply as
    before. Errors leave as TYPE NAME only (C04 redaction)."""
    _child_maybe_stall()
    requests = _load_requests()
    url = str(request["url"])
    max_bytes = int(request["maxBytes"])
    remaining = float(request.get("remainingSeconds") or 0.0)
    timeout = max(0.1, min(5.0, remaining)) if remaining > 0 else 5.0
    session = requests.Session()
    try:
        response = session.get(url, timeout=timeout, stream=True,
                               verify=config.REQUESTS_VERIFY,
                               allow_redirects=False)
        try:
            status = int(response.status_code)
            # HARD consumption cap (F3): the child reads AT MOST this many
            # body bytes via raw.read(amt) — never one full chunk past the
            # cap. One byte past the JSON cap is proof of overflow, so an
            # exactly-cap body still parses. Non-200 bodies are diagnostic
            # only and capped at ERROR_BODY_HARD_CAP_BYTES. Consumption
            # stops at the cap; the finally below closes the socket, so a
            # server still writing sees EPIPE (no unbounded dribble).
            budget = max_bytes + 1 if status == 200 else ERROR_BODY_HARD_CAP_BYTES
            declared = str(response.headers.get("Content-Length") or "").strip()
            try:
                declared_over = bool(declared) and int(declared) > max_bytes
            except ValueError:
                declared_over = False
            if status == 200 and declared_over:
                # Fail closed from headers alone — never stream the body.
                return {"status": status,
                        "headers": {str(k): str(v) for k, v in response.headers.items()},
                        "body": "", "truncated": True}
            chunks: List[bytes] = []
            total = 0
            raw = response.raw
            while total < budget:
                piece = raw.read(min(65536, budget - total), decode_content=True)
                if not piece:
                    break
                chunks.append(piece)
                total += len(piece)
            truncated = total > max_bytes if status == 200 else total >= budget
            return {"status": status,
                    "headers": {str(k): str(v) for k, v in response.headers.items()},
                    "body": base64.b64encode(b"".join(chunks)).decode("ascii"),
                    "truncated": truncated}
        finally:
            try:
                response.close()
            except Exception:
                pass
    except BaseException as exc:  # noqa: BLE001 — envelope, never a traceback
        return {"transportError": {"kind": type(exc).__name__}}
    finally:
        try:
            session.close()
        except Exception:
            pass


def metadata_child_main() -> int:
    """Startup-only bootstrap for the owned metadata child process.

    Dispatched from main() BEFORE any argument parsing, GUI launch or
    campaign routing, so a re-executed frozen executable (any of the four
    packages or source entry points) can never recursively open a GUI, a
    run or a queue. Reads one JSON request from stdin until EOF, performs
    exactly one bounded GET, writes one JSON envelope to fd 1 and
    `os._exit`s — skipping interpreter shutdown keeps the exit immediate
    even if a daemon thread lingered. A watchdog self-terminates an orphan
    (parent died before kill) at bound+5s; stdin EOF with no request exits
    at once."""
    # Startup watchdog: an orphan (parent hard-crashed before EOF/kill)
    # must never linger blocked on stdin. Generous: a healthy child parses
    # the request and completes the GET within the transaction bound.
    startup = threading.Timer(30.0, lambda: os._exit(6))
    startup.daemon = True
    startup.start()
    data = b""
    while True:
        try:
            chunk = os.read(0, 65536)
        except OSError:
            chunk = b""
        if not chunk:
            break
        data += chunk
        if len(data) > 65536:
            os._exit(2)
    if not data:
        os._exit(2)
    try:
        request = json.loads(data.decode("utf-8"))
        assert isinstance(request, dict) and request.get("url")
    except Exception:
        os._exit(2)
    bound = float(request.get("boundSeconds") or METADATA_TRANSACTION_SECONDS)
    watchdog = threading.Timer(bound + 5.0, lambda: os._exit(3))
    watchdog.daemon = True
    watchdog.start()
    envelope = _child_perform_get(request)
    payload = json.dumps(envelope).encode("utf-8")
    try:
        view = memoryview(payload)
        while view:
            written = os.write(1, view)
            view = view[written:]
    except OSError:
        os._exit(4)
    os._exit(0)


def _run_owned_metadata_child(request: Dict[str, Any], *, phase: str,
                              cancel_event: Optional[Any],
                              deadline: Optional[float],
                              bound_seconds: float) -> Dict[str, Any]:
    """Run one metadata GET in an owned child process with a HARD total
    deadline (F3 acceptance): DNS, connect, headers and body all die with
    `kill()` — including a hung resolver or a connect whose socket has not
    been allocated yet, which no in-process thread interrupt can stop.

    ONE cleanup owner covers EVERY post-spawn path (success, Stop, deadline,
    oversize, stdin/reader setup failure, exception): kill → bounded wait →
    reader join → pipe close. The child leaves the owned-children census
    ONLY after its death is CONFIRMED. If kill/wait cannot confirm death
    (pathological SIGKILL-ignored process), the child stays registered and
    a deferred reaper — registered as an owned worker in the ambient
    WorkerGroup, the same F1 deferral that keeps the host phase lock held —
    finishes the reap; this call then raises `MetadataRetentionHeld` so the
    caller pauses instead of treating the lookup as merely absent. A Close
    grace timeout additionally reaps live children through
    `_terminate_owned_children` (psutil recursive children)."""
    from .console_policy import hidden_console_kwargs
    # Frozen (any of the four PyInstaller packages): re-executing
    # `sys.executable` re-enters the packaged entry, whose startup dispatch
    # (before any GUI/campaign routing) claims `--metadata-child`. Source:
    # `python -m client` with the package parent pinned on PYTHONPATH, so
    # the child works regardless of the parent's cwd or install layout.
    child_env = os.environ.copy()
    if getattr(sys, "frozen", False):
        argv = [sys.executable, METADATA_CHILD_ARGV, phase]
    else:
        executable = sys.executable
        if not executable:
            raise SubmitError(f"{phase} metadata transport unavailable: no interpreter",
                              retryable=True)
        package_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        existing = child_env.get("PYTHONPATH") or ""
        child_env["PYTHONPATH"] = (package_parent + os.pathsep + existing
                                   if existing else package_parent)
        argv = [executable, "-m", "client", METADATA_CHILD_ARGV, phase]
    request_bytes = json.dumps(request).encode("utf-8")
    # Tiny by construction (URL + caps). Bound it BEFORE spawn so the stdin
    # write can never block on a full pipe outside any deadline owner.
    if len(request_bytes) > 2048 or len(str(request.get("url") or "")) > 1024:
        raise SubmitError(f"{phase} metadata request exceeds the transport cap",
                          retryable=False)
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, env=child_env,
                                **hidden_console_kwargs())
    except OSError as exc:
        # C04: type name only (never a path or command line).
        raise SubmitError(f"{phase} failed: {type(exc).__name__}",
                          retryable=True) from exc
    _register_metadata_child(proc)
    limit = int(request["maxBytes"]) * 2 + 65536  # base64 + envelope headroom
    chunks: List[bytes] = []
    overflow = {"flag": False}
    state = {"retained": False}
    outcome: Optional[str] = None
    reader: Optional[threading.Thread] = None

    def _reader() -> None:
        total = 0
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > limit:
                    overflow["flag"] = True
                    break
        except (OSError, ValueError):
            pass  # pipe closed by the abandon path — outcome already decided

    def _cleanup() -> None:
        """Single owner for every post-spawn path; runs exactly once."""
        dead = proc.poll() is not None
        if not dead:
            try:
                proc.kill()
            except ProcessLookupError:
                dead = True
            except OSError:
                pass  # kill failed; retention decision below
            if not dead:
                try:
                    proc.wait(timeout=5)
                    dead = True
                except (subprocess.TimeoutExpired, OSError):
                    pass
        if reader is not None and reader.ident is not None:
            reader.join(2.0)
        try:
            proc.stdout.close()
        except Exception:
            pass
        if reader is not None and reader.ident is not None:
            # Closing the pipe interrupts a reader still blocked on I/O.
            reader.join(2.0)
            if reader.is_alive():
                dead = False
        if dead:
            _unregister_metadata_child(proc)
        else:
            state["retained"] = True
            _retain_metadata_child(proc, reader, phase)

    try:
        try:
            proc.stdin.write(request_bytes)
        except OSError:
            pass  # child died early; the reader sees EOF and we report below
        try:
            proc.stdin.close()
        except OSError:
            pass
        reader = threading.Thread(target=_reader,
                                  name=f"encodingdb-metadata-read-{phase}",
                                  daemon=True)
        reader.start()
        while reader.is_alive():
            if _event_cancelled(cancel_event):
                outcome = "cancelled"
                break
            remaining = _remaining_seconds(deadline)
            if remaining is not None and remaining <= 0:
                outcome = "deadline"
                break
            reader.join(0.05)
        if outcome is None and overflow["flag"]:
            outcome = "oversize"
    finally:
        _cleanup()
    if state["retained"]:
        raise MetadataRetentionHeld(phase)
    if outcome == "cancelled":
        raise SubmissionCancelled(phase)
    if outcome == "deadline":
        raise SubmitError(f"{phase} exceeded {bound_seconds:g}s wall-clock bound",
                          retryable=True)
    if outcome == "oversize":
        raise SubmitError(f"{phase} response exceeds the transport byte cap",
                          retryable=False)
    data = b"".join(chunks)
    if not data:
        raise SubmitError(f"{phase} failed: child-exited", retryable=True)
    try:
        envelope = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise SubmitError(f"{phase} failed: malformed-transport-envelope",
                          retryable=True) from exc
    if not isinstance(envelope, dict):
        raise SubmitError(f"{phase} failed: malformed-transport-envelope",
                          retryable=True)
    return envelope


def _fetch_metadata_json(base_url: str, path: str, *, phase: str,
                         cancel_event: Optional[Any],
                         deadline: Optional[float],
                         transaction_seconds: Optional[float] = None,
                         max_bytes: int = JSON_BODY_HARD_CAP_BYTES) -> Any:
    """One owned, cancellable, HARD-deadline, size-bounded metadata GET.

    F3 replaces the synchronous eager `requests.get(timeout=10/15)` used by
    compatibility/baseline (per-inactivity timeouts reset forever while a
    peer dribbles bytes, and Stop/DNS/connect could not be interrupted).
    The GET runs in an owned child process (see
    `_run_owned_metadata_child`); this function enforces the contract on
    the returned envelope: fail-closed size cap, non-200 -> retryable
    SubmitError, malformed JSON -> non-retryable SubmitError, transport
    faults -> retryable SubmitError (type name only), Stop ->
    SubmissionCancelled. Contract validation stays in the parent."""
    transaction_seconds = (METADATA_TRANSACTION_SECONDS if transaction_seconds is None
                           else float(transaction_seconds))
    bound_deadline = time.monotonic() + max(1.0, transaction_seconds)
    deadline = bound_deadline if deadline is None else min(deadline, bound_deadline)
    _check_transaction(cancel_event, deadline, phase, transaction_seconds)
    remaining = _remaining_seconds(deadline) or 0.0
    request = {"url": f"{base_url.rstrip('/')}{path}", "phase": phase,
               "maxBytes": int(max_bytes), "remainingSeconds": remaining,
               "boundSeconds": transaction_seconds}
    # Standalone bootstrap also owns real host exclusion. A retained reaper
    # must keep that lock until death is confirmed, including outside a batch.
    from .spool import host_phase_hold
    with host_phase_hold("publication"):
        envelope = _run_owned_metadata_child(request, phase=phase,
                                             cancel_event=cancel_event,
                                             deadline=deadline,
                                             bound_seconds=transaction_seconds)
    transport_error = envelope.get("transportError")
    if isinstance(transport_error, dict):
        raise SubmitError(f"{phase} failed: {transport_error.get('kind') or 'unknown'}",
                          retryable=True)
    status = int(envelope.get("status") or 0)
    headers = envelope.get("headers") or {}
    try:
        body = base64.b64decode(envelope.get("body") or "")
    except Exception as exc:
        raise SubmitError(f"{phase} failed: malformed-transport-envelope",
                          retryable=True) from exc
    if status != 200:
        raise SubmitError(f"{phase} returned {status}", retryable=True,
                          status_code=status,
                          body=body[:ERROR_BODY_HARD_CAP_BYTES].decode("utf-8", "replace"))
    declared = str(headers.get("Content-Length") or "").strip()
    try:
        if declared and int(declared) > max_bytes:
            raise SubmitError(f"{phase} response exceeds {max_bytes} bytes",
                              retryable=False)
    except ValueError:
        pass
    if envelope.get("truncated") or len(body) > max_bytes:
        raise SubmitError(f"{phase} response exceeds {max_bytes} bytes",
                          retryable=False)
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except ValueError as exc:
        raise SubmitError(f"{phase} returned malformed JSON", retryable=False) from exc


def fetch_baseline_rows(base_url: str, *, cancel_event: Optional[Any] = None,
                        deadline: Optional[float] = None,
                        transaction_seconds: Optional[float] = None
                        ) -> List[Dict[str, Any]]:
    """Optional baseline lookup: bounded and cancellable (F3), never fatal.

    Raises SubmitError/SubmissionCancelled for the caller to treat as
    "no baseline this round"; a FAILED lookup is never cached, so it cannot
    poison the TTL window — only a genuine 200 list is."""
    with config._GLOBAL_STATE_LOCK:
        if config._BASELINE_ROWS_CACHE is not None:
            elapsed = time.time() - config._BASELINE_ROWS_CACHE_TS
            if elapsed < config._BASELINE_ROWS_CACHE_TTL:
                return config._BASELINE_ROWS_CACHE
            # TTL expired — clear cache and re-fetch
            config._BASELINE_ROWS_CACHE = None

    data = _fetch_metadata_json(base_url, "/query?limit=500",
                                phase="baseline query",
                                cancel_event=cancel_event, deadline=deadline,
                                transaction_seconds=transaction_seconds)
    if not isinstance(data, list):
        raise SubmitError("baseline query returned a non-list body", retryable=False)
    with config._GLOBAL_STATE_LOCK:
        config._BASELINE_ROWS_CACHE = data
        config._BASELINE_ROWS_CACHE_TS = time.time()
    return data


def check_compatibility(base_url: str, client_version: str, *,
                        cancel_event: Optional[Any] = None,
                        deadline: Optional[float] = None,
                        transaction_seconds: Optional[float] = None
                        ) -> Dict[str, Any]:
    from .suite import load_suite_pack_metadata, SUITE_VERSION
    contract = _fetch_metadata_json(base_url, "/v7/compatibility",
                                    phase="compatibility check",
                                    cancel_event=cancel_event, deadline=deadline,
                                    transaction_seconds=transaction_seconds)
    if not isinstance(contract, dict):
        raise SubmitError("Compatibility endpoint returned a non-object body",
                          retryable=False)
    def version(value):
        try:
            return tuple(int(part) for part in str(value).removeprefix("client/").split("."))
        except ValueError as exc:
            raise SubmitError("Client/protocol incompatible with current collection epoch; update the client", retryable=False) from exc
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
