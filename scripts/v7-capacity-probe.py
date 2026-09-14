#!/usr/bin/env python3
"""Sustained, read-only load against explicitly isolated loopback API/frontend.

This measures serving capacity. It does not fabricate contribution, analysis,
queue-drain, or calibration evidence. Seed the isolated representative corpus
separately, and record its identity/count in --fixture-label.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import threading
import time
from urllib.parse import urlsplit
from urllib.request import urlopen


def loopback_url(value):
    parts = urlsplit(value)
    if parts.scheme != 'http' or parts.hostname not in {'127.0.0.1', 'localhost', '::1'} or parts.username or parts.password or parts.query or parts.fragment:
        raise argparse.ArgumentTypeError('use an isolated loopback HTTP URL without credentials/query/fragment')
    return value.rstrip('/')


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url', type=loopback_url, required=True)
    parser.add_argument('--app-url', type=loopback_url, required=True)
    parser.add_argument('--fixture-label', required=True)
    parser.add_argument('--duration-seconds', type=int, default=600)
    parser.add_argument('--concurrency', type=int, default=25)
    parser.add_argument('--think-seconds', type=float, default=0.1)
    parser.add_argument('--p95-budget-ms', type=float, default=1000)
    parser.add_argument('--container', action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 100 or not 1 <= args.duration_seconds <= 86400 or args.think_seconds < 0:
        parser.error('concurrency must be1..100, duration1..86400 seconds, think-time nonnegative')
    if args.output.exists():
        parser.error('output exists; choose a new receipt path')
    # Keep destructive/public targeting impossible; Docker is used for read-only stats.
    targets = [('corpus', args.api_url + '/corpus?limit=25'), ('catalog', args.api_url + '/test-videos'),
               ('frontend', args.app_url + '/'), ('frontend-corpus', args.app_url + '/api/corpus?limit=25')]
    lock = threading.Lock()
    metrics = {name: {'requests': 0, 'errors': 0, 'bytes': 0, 'latencyMs': [], 'lastError': None} for name, _ in targets}
    start = time.monotonic()
    stop = start + args.duration_seconds
    evidence = {'version': 1, 'startedAt': datetime.now(timezone.utc).isoformat(), 'fixture': args.fixture_label,
                'concurrency': args.concurrency, 'requestedDurationSeconds': args.duration_seconds,
                'p95BudgetMs': args.p95_budget_ms, 'scope': 'isolated read-only API/frontend load; no encode/upload claims',
                'samples': [], 'targets': dict(targets)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({**evidence, 'status': 'running'}, indent=2) + '\n')

    def visitor(number):
        index = number
        while time.monotonic() < stop:
            name, url = targets[index % len(targets)]
            began = time.monotonic()
            size, error = 0, None
            try:
                with urlopen(url, timeout=20) as response:
                    while chunk := response.read(64 * 1024):
                        size += len(chunk)
                        if size > 16 * 1024 * 1024:
                            raise ValueError('response exceeds16MiB serving bound')
            except Exception as exc:
                error = str(exc)[:300]
            elapsed = (time.monotonic() - began) * 1000
            with lock:
                item = metrics[name]
                item['requests'] += 1
                item['errors'] += int(error is not None)
                item['bytes'] += size
                item['lastError'] = error or item['lastError']
                if len(item['latencyMs']) < 1_000_000:
                    item['latencyMs'].append(elapsed)
            index += 1
            time.sleep(args.think_seconds)

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(visitor, index) for index in range(args.concurrency)]
        while time.monotonic() < stop:
            sample = {'elapsedSeconds': time.monotonic() - start}
            if args.container:
                result = subprocess.run(['docker', 'stats', '--no-stream', '--format', '{{json .}}', *args.container], capture_output=True, text=True, timeout=20)
                sample['dockerExitCode'] = result.returncode
                sample['docker'] = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            try:
                with urlopen(args.api_url + '/health/v7-evidence', timeout=20) as response:
                    sample['health'] = json.load(response)
            except Exception as exc:
                sample['healthError'] = str(exc)[:300]
            evidence['samples'].append(sample)
            time.sleep(min(5, max(0, stop - time.monotonic())))
        for future in futures:
            future.result()
    result = {}
    for name, item in metrics.items():
        values = item.pop('latencyMs')
        result[name] = {**item, 'latencySampleCount': len(values), 'p50Ms': percentile(values, .5), 'p95Ms': percentile(values, .95), 'maxMs': max(values, default=None)}
    evidence.update({'elapsedSeconds': time.monotonic() - start, 'results': result, 'finishedAt': datetime.now(timezone.utc).isoformat()})
    passed = all(item['requests'] and not item['errors'] and item['p95Ms'] <= args.p95_budget_ms for item in result.values())
    evidence['status'] = 'passed' if passed else 'failed'
    args.output.write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({'status': evidence['status'], 'receipt': str(args.output), 'results': result}))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
