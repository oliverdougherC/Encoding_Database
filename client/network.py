import hashlib
import json
import re
import sys
import time
import warnings
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin

from . import config


def _load_requests():
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r".*urllib3 v2 only supports OpenSSL.*",
        )
        import requests  # type: ignore
    return requests


class SubmitError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        status_code: Optional[int] = None,
        body: str = "",
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.body = body


def _get_submit_token_headers(requests: Any, base_url: str) -> Dict[str, str]:
    """Fetch and solve a one-time token for exactly one POST attempt."""
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
            try:
                response = requests.get(endpoint, timeout=10, verify=config.REQUESTS_VERIFY)
                if response.status_code == 200:
                    token_resp = response
                    break
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
    except Exception as exc:
        try:
            print(f"token fetch error: {exc}", file=sys.stderr)
        except Exception:
            pass
        return {}


def submit(base_url: str, payload: Dict[str, Any], api_key: str = "", retries: int = 3, backoff_seconds: float = 1.0, use_token: Optional[bool] = None) -> None:
    requests = _load_requests()
    url = f"{base_url.rstrip('/')}/submit"
    payload_to_send: Dict[str, Any] = dict(payload)

    base_headers: Dict[str, str] = {"Content-Type": "application/json"}
    if use_token is None:
        use_token = config._env_flag('INGEST_USE_TOKENS', False)
    # HMAC signing if secret available
    secret = config.ENV_INGEST_HMAC_SECRET

    attempt = 1
    last_hmac_timestamp = 0
    while attempt <= retries:
        body = json.dumps(payload_to_send, separators=(",", ":"))
        headers = dict(base_headers)
        if use_token:
            headers.update(_get_submit_token_headers(requests, base_url))
        if secret:
            import hmac
            ts = max(int(time.time()), last_hmac_timestamp + 1)
            last_hmac_timestamp = ts
            sig = hmac.new(secret.encode("utf-8"), f"{ts}.".encode("utf-8") + body.encode("utf-8"), hashlib.sha256).hexdigest()
            headers["x-signature"] = sig
            headers["x-timestamp"] = str(ts)
        try:
            r = requests.post(url, data=body, timeout=30, headers=headers, verify=config.REQUESTS_VERIFY, allow_redirects=False)
            if 300 <= r.status_code < 400:
                loc = r.headers.get('Location') or r.headers.get('location')
                if loc:
                    redirect_url = urljoin(url, loc)
                    redirect_headers = dict(base_headers)
                    if use_token:
                        redirect_headers.update(_get_submit_token_headers(requests, base_url))
                    if secret:
                        import hmac
                        redirect_ts = max(int(time.time()), last_hmac_timestamp + 1)
                        last_hmac_timestamp = redirect_ts
                        redirect_sig = hmac.new(secret.encode("utf-8"), f"{redirect_ts}.".encode("utf-8") + body.encode("utf-8"), hashlib.sha256).hexdigest()
                        redirect_headers["x-signature"] = redirect_sig
                        redirect_headers["x-timestamp"] = str(redirect_ts)
                    r = requests.post(redirect_url, data=body, timeout=30, headers=redirect_headers, verify=config.REQUESTS_VERIFY, allow_redirects=False)
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
                        body=(r.text or ""),
                    )
                time.sleep(max(0.5, delay))
                attempt += 1
                continue
            if r.status_code >= 500:
                if attempt >= retries:
                    raise SubmitError(
                        f"server_error {r.status_code}",
                        retryable=True,
                        status_code=r.status_code,
                        body=(r.text or ""),
                    )
                raise RuntimeError(f"server_error {r.status_code}")
            if r.status_code >= 400:
                raise SubmitError(
                    f"submit rejected ({r.status_code})",
                    retryable=False,
                    status_code=r.status_code,
                    body=(r.text or ""),
                )
            r.raise_for_status()
            return
        except Exception as e:
            retryable = True
            status_code: Optional[int] = None
            body = ""
            if isinstance(e, SubmitError):
                retryable = e.retryable
                status_code = e.status_code
                body = e.body
            if attempt == retries:
                try:
                    _req = _load_requests()
                    if isinstance(e, _req.HTTPError) and getattr(e, 'response', None) is not None:
                        resp = e.response
                        try:
                            err_text = resp.text
                        except Exception:
                            err_text = ""
                        sent_token = 'x-ingest-token' in headers
                        sent_nonce = 'x-ingest-nonce' in headers
                        print(f"submit error body ({resp.status_code}): {err_text}\n(sent_token={sent_token}, sent_nonce={sent_nonce})", file=sys.stderr)
                except Exception:
                    pass
                if isinstance(e, SubmitError):
                    raise
                raise SubmitError(
                    str(e),
                    retryable=True,
                    status_code=status_code,
                    body=body,
                ) from e
            if isinstance(e, SubmitError) and not retryable:
                raise
            time.sleep(backoff_seconds * attempt)
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
