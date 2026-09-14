#!/usr/bin/env python3
"""Sustained, read-only load against explicitly isolated loopback API/frontend.

This measures serving capacity. It does not fabricate contribution, analysis,
queue-drain, or calibration evidence. Seed the isolated representative corpus
separately, and record its identity/count in --fixture-label.
"""
import argparse
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
import signal
from pathlib import Path
import subprocess
import threading
import time
from urllib.parse import urlsplit
from urllib.error import HTTPError
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
    parser.add_argument('--pid', type=int, action='append', default=[], help='owned API/frontend process IDs for RSS sampling')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 100 or not 1 <= args.duration_seconds <= 86400 or args.think_seconds < 0:
        parser.error('concurrency must be 1..100, duration 1..86400 seconds, think-time nonnegative')
    if args.output.exists():
        parser.error('output exists; choose a new receipt path')
    # Keep destructive/public targeting impossible; Docker is used for read-only stats.
    targets = [('corpus', args.api_url + '/corpus?limit=25'), ('catalog', args.api_url + '/test-videos'),
               ('frontend', args.app_url + '/'), ('frontend-corpus', args.app_url + '/api/corpus?limit=25')]
    lock = threading.Lock()
    metrics = {name: {'requests': 0, 'errors': 0, 'bytes': 0, 'latencyMs': [], 'lastError': None} for name, _ in targets}
    start = time.monotonic()
    stop = start + args.duration_seconds
    interrupted = False

    def cancel(_signal, _frame):
        nonlocal stop, interrupted
        interrupted = True
        stop = time.monotonic()

    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    evidence = {'version': 1, 'probeSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'startedAt': datetime.now(timezone.utc).isoformat(), 'fixture': args.fixture_label,
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
                            raise ValueError('response exceeds 16 MiB serving bound')
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
                try:
                    result = subprocess.run(['docker', 'stats', '--no-stream', '--format', '{{json .}}', *args.container], capture_output=True, text=True, timeout=20)
                    sample['dockerExitCode'] = result.returncode
                    sample['docker'] = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
                except (subprocess.TimeoutExpired, ValueError) as exc:
                    sample['dockerError'] = str(exc)[:300]
            if args.pid:
                result = subprocess.run(['ps', '-o', 'pid=,rss=', '-p', ','.join(map(str, args.pid))], capture_output=True, text=True, timeout=5)
                sample['processRssBytes'] = {fields[0]: int(fields[1]) * 1024 for line in result.stdout.splitlines() if len(fields := line.split()) == 2}
            try:
                with urlopen(args.api_url + '/health/v7-evidence', timeout=20) as response:
                    sample['health'] = json.load(response)
                    sample['healthHttpStatus'] = response.status
            except HTTPError as exc:
                sample['healthHttpStatus'] = exc.code
                try:
                    sample['health'] = json.load(exc)
                except ValueError:
                    sample['healthError'] = str(exc)[:300]
            except Exception as exc:
                sample['healthError'] = str(exc)[:300]
            evidence['samples'].append(sample)
            with lock:
                progress = {name: {key: value for key, value in item.items() if key != 'latencyMs'} for name, item in metrics.items()}
            temporary = args.output.with_suffix(args.output.suffix + '.tmp')
            temporary.write_text(json.dumps({**evidence, 'status': 'running', 'progress': progress}, indent=2) + '\n')
            temporary.replace(args.output)
            time.sleep(min(5, max(0, stop - time.monotonic())))
        for future in futures:
            future.result()
    result = {}
    for name, item in metrics.items():
        values = item.pop('latencyMs')
        result[name] = {**item, 'latencySampleCount': len(values), 'p50Ms': percentile(values, .5), 'p95Ms': percentile(values, .95), 'maxMs': max(values, default=None)}
    evidence.update({'elapsedSeconds': time.monotonic() - start, 'results': result, 'finishedAt': datetime.now(timezone.utc).isoformat()})
    passed = all(item['requests'] and not item['errors'] and item['p95Ms'] <= args.p95_budget_ms for item in result.values())
    evidence['status'] = 'aborted' if interrupted else 'passed' if passed else 'failed'
    evidence['healthAllOk'] = all(isinstance(sample.get('health'), dict) and sample['health'].get('status') == 'ok' for sample in evidence['samples'])
    evidence['peakProcessRssBytes'] = {str(pid): max((sample.get('processRssBytes', {}).get(str(pid), 0) for sample in evidence['samples']), default=0) for pid in args.pid}
    args.output.write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({'status': evidence['status'], 'receipt': str(args.output), 'results': result}))
    return 130 if interrupted else 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
