import hashlib
import json
import re
import sys
import time
import threading
from typing import Optional, Dict, Any, List, Set

from . import config


_REJECTED_KEYS_LOCK = threading.Lock()
_SERVER_REJECTED_KEYS: Dict[str, Set[str]] = {}


def _base_key(base_url: str) -> str:
    try:
        return base_url.rstrip('/').lower()
    except Exception:
        return base_url


def _get_rejected_keys(base_url: str) -> Set[str]:
    key = _base_key(base_url)
    with _REJECTED_KEYS_LOCK:
        existing = _SERVER_REJECTED_KEYS.get(key)
        return set(existing) if existing else set()


def _remember_rejected_keys(base_url: str, keys: List[str]) -> Set[str]:
    key = _base_key(base_url)
    cleaned = [str(k).strip() for k in keys if isinstance(k, str) and str(k).strip()]
    if not cleaned:
        return _get_rejected_keys(base_url)
    with _REJECTED_KEYS_LOCK:
        bucket = _SERVER_REJECTED_KEYS.setdefault(key, set())
        bucket.update(cleaned)
        return set(bucket)


def _extract_unrecognized_keys(error_text: str) -> List[str]:
    if not error_text:
        return []
    messages: List[str] = []
    try:
        data = json.loads(error_text)
        details = data.get('details') if isinstance(data, dict) else None
        form_errors = details.get('formErrors') if isinstance(details, dict) else None
        if isinstance(form_errors, list):
            for entry in form_errors:
                if isinstance(entry, str):
                    messages.append(entry)
    except Exception:
        pass
    if not messages:
        messages = [error_text]

    out: List[str] = []
    for msg in messages:
        match = re.search(r"Unrecognized keys?:\s*(.*)", msg)
        if not match:
            continue
        key_blob = match.group(1)
        for key in re.findall(r'"([^"]+)"', key_blob):
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key):
                continue
            if key not in out:
                out.append(key)
    return out


def submit(base_url: str, payload: Dict[str, Any], api_key: str = "", retries: int = 3, backoff_seconds: float = 1.0, use_token: Optional[bool] = None) -> None:
    import requests  # lazy import
    url = f"{base_url.rstrip('/')}/submit"
    payload_to_send: Dict[str, Any] = dict(payload)
    for dropped in _get_rejected_keys(base_url):
        payload_to_send.pop(dropped, None)

    base_headers: Dict[str, str] = {"Content-Type": "application/json"}
    if use_token is None:
        use_token = config._env_flag('INGEST_USE_TOKENS', False)
    if use_token:
        try:
            base = base_url.rstrip('/')
            endpoints = [
                f"{base}/health/token",
                f"{base}/submit-token",
                f"{base}/submit/token",
            ]
            tokenResp = None
            for ep in endpoints:
                try:
                    r = requests.get(ep, timeout=10, verify=config.REQUESTS_VERIFY)
                    if r.status_code == 200:
                        tokenResp = r
                        break
                except Exception:
                    continue
            if tokenResp and tokenResp.status_code == 200:
                tokenData = tokenResp.json() or {}
                token = str(tokenData.get('token') or '')
                powInfo = tokenData.get('pow') or {}
                if token and re.fullmatch(r"[0-9a-f]{32}", token):
                    base_headers['x-ingest-token'] = token
                    try:
                        difficulty = int(powInfo.get('difficulty') or 0)
                    except Exception:
                        difficulty = 0
                    if difficulty > 0:
                        prefix = '0' * max(0, difficulty)
                        nonce = 0
                        max_iters = 500000
                        pow_timeout = 30.0
                        pow_start = time.time()
                        pow_found = False
                        print(f"  Solving Proof-of-Work (difficulty={difficulty})...", end='', flush=True)
                        while nonce < max_iters:
                            if nonce % 10000 == 0:
                                elapsed_pow = time.time() - pow_start
                                if elapsed_pow > pow_timeout:
                                    print(f" timeout after {elapsed_pow:.1f}s")
                                    break
                                if nonce > 0 and nonce % 100000 == 0:
                                    print(f" {nonce//1000}k", end='', flush=True)
                            test = hashlib.sha256(f"{token}.{nonce}".encode('utf-8')).hexdigest()
                            if test.startswith(prefix):
                                base_headers['x-ingest-nonce'] = str(nonce)
                                pow_found = True
                                print(f" solved (nonce={nonce})")
                                break
                            nonce += 1
                        if not pow_found and nonce >= max_iters:
                            print(f" exhausted {max_iters} iterations without solution")
        except Exception as te:
            try:
                print(f"token fetch error: {te}", file=sys.stderr)
            except Exception:
                pass
    # HMAC signing if secret available
    secret = config.ENV_INGEST_HMAC_SECRET

    attempt = 1
    max_compat_retries = max(1, len(payload_to_send))
    compat_retries = 0
    while attempt <= retries:
        body = json.dumps(payload_to_send, separators=(",", ":"))
        headers = dict(base_headers)
        if secret:
            import hmac
            ts = int(time.time())
            sig = hmac.new(secret.encode("utf-8"), f"{ts}.".encode("utf-8") + body.encode("utf-8"), hashlib.sha256).hexdigest()
            headers["x-signature"] = sig
            headers["x-timestamp"] = str(ts)
        try:
            r = requests.post(url, data=body, timeout=30, headers=headers, verify=config.REQUESTS_VERIFY, allow_redirects=False)
            if 300 <= r.status_code < 400:
                loc = r.headers.get('Location') or r.headers.get('location')
                if loc:
                    r = requests.post(loc, data=body, timeout=30, headers=headers, verify=config.REQUESTS_VERIFY, allow_redirects=False)
            if r.status_code == 400:
                try:
                    err_text = r.text
                except Exception:
                    err_text = ""
                unknown_keys = _extract_unrecognized_keys(err_text)
                if unknown_keys:
                    removed_now: List[str] = []
                    for key in unknown_keys:
                        if key in payload_to_send:
                            payload_to_send.pop(key, None)
                            removed_now.append(key)
                    if removed_now:
                        all_rejected = _remember_rejected_keys(base_url, removed_now)
                        print(
                            "submit compatibility: server rejected fields; retrying without: "
                            + ", ".join(sorted(all_rejected)),
                            file=sys.stderr,
                        )
                        compat_retries += 1
                        if compat_retries <= max_compat_retries:
                            continue
            if r.status_code == 429:
                try:
                    ra = r.headers.get('Retry-After')
                    delay = float(ra) if ra and str(ra).replace('.', '', 1).isdigit() else (backoff_seconds * attempt * 2)
                except Exception:
                    delay = backoff_seconds * attempt * 2
                if attempt >= retries:
                    r.raise_for_status()
                time.sleep(max(0.5, delay))
                attempt += 1
                continue
            if r.status_code >= 500:
                raise RuntimeError(f"server_error {r.status_code}")
            r.raise_for_status()
            return
        except Exception as e:
            if attempt == retries:
                try:
                    import requests as _req  # type: ignore
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
        import requests  # lazy import
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
