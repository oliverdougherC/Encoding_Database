#!/usr/bin/env python3
"""Fetch current bound retention evidence over verified isolated-loopback TLS."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import ssl
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def collect(snapshot, base_url, ca_file, cache_dir=None, min_interval=1.0):
    target = urlsplit(base_url)
    if (target.scheme != "https" or target.hostname != "127.0.0.1" or target.username
            or target.password or target.path not in ("", "/") or target.query or target.fragment):
        raise ValueError("Require explicit isolated HTTPS loopback origin")
    context = ssl.create_default_context(cafile=str(ca_file))
    if min_interval < .25:
        raise ValueError("Retain headroom below the isolated backend request limit")
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
    runs = set()
    for name, item in snapshot["files"].items():
        if name.startswith("receipts/"):
            run = (item["value"].get("acknowledgment") or {}).get("benchmarkRunId")
            if not isinstance(run, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", run):
                raise ValueError("Receipt lacks safe server run identity")
            runs.add(run)

    def fetch(run):
        request = urllib.request.Request(base_url.rstrip("/") + "/v7/benchmark-runs/" + run + "/artifacts/ENCODED/analysis-status")
        # Never follow a redirect outside the pinned isolated origin.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=context), NoRedirect())
        for attempt in range(3):
            try:
                with opener.open(request, timeout=20) as response:
                    raw = response.read(1024 * 1024 + 1)
                    if len(raw) > 1024 * 1024:
                        raise ValueError("Oversized server evidence")
                    result = json.loads(raw)
                    if not isinstance(result, dict) or result.get("benchmarkRunId") != run:
                        raise ValueError("Server response does not bind requested run")
                    result["_evidenceObservedAt"] = datetime.now(timezone.utc).isoformat()
                    result["_evidenceOrigin"] = base_url.rstrip("/")
                    return result
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or attempt == 2:
                    raise
                delay = float(exc.headers.get("Retry-After", "60"))
                if not 0 <= delay <= 120:
                    raise ValueError("Rate-limit delay exceeds bounded collector retry") from exc
                exc.close()
                time.sleep(max(delay, 1))

    results = []
    for run in sorted(runs):
        cached = cache_dir / (run + ".json") if cache_dir else None
        if cached and cached.is_file():
            value = json.loads(cached.read_text())
            if (not isinstance(value, dict) or value.get("benchmarkRunId") != run or not value.get("_evidenceObservedAt")
                    or value.get("_evidenceOrigin") != base_url.rstrip("/")):
                raise ValueError("Malformed cached evidence; preserve and use a new cache directory")
        else:
            value = fetch(run)
            if cached:
                with cached.open("x") as output:
                    json.dump(value, output)
            time.sleep(min_interval)
        results.append(value)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--ca", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, help="Owned per-run evidence cache for resumable rate-limited collection")
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Evidence output already exists; preserve it and choose a new name")
    result = collect(json.loads(args.snapshot.read_text()), args.base_url, args.ca,
                     args.cache_dir or args.out.with_suffix(".responses"))
    with args.out.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"responses": len(result), "out": str(args.out)}))
