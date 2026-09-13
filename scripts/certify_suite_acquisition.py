#!/usr/bin/env python3
"""Exercise actual frozen-pack recovery using a fault-injecting loopback server."""
import argparse
from datetime import datetime, timezone
import http.server
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from client import suite


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack', type=Path, default=ROOT / '.build/candidate-artifacts/encodingdb-test-suite-v1.tar.gz')
    parser.add_argument('--metadata', type=Path, default=ROOT / 'client/resources/test_suite_v1/suite-pack.json')
    parser.add_argument('--work-dir', type=Path, default=ROOT / '.build/acquisition-certification')
    parser.add_argument('--report', type=Path, default=ROOT / 'docs/canonical-suite/evidence/acquisition-recovery.json')
    args = parser.parse_args()
    pack = args.pack.resolve()
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        raise RuntimeError('Certification work directory must be empty; choose a new --work-dir.')
    metadata = suite.load_suite_pack_metadata(str(args.metadata))
    baseline_cache_seconds = None
    if args.report.exists():
        previous = json.loads(args.report.read_text())
        if previous.get('archiveSha256') == metadata['distribution']['sha256']:
            by_check = {event['check']: event for event in previous.get('events', [])}
            prior_cache = by_check.get('cache_reuse_without_archive_verified', {})
            if prior_cache.get('allClipTechnicalContractsReverified'):
                baseline_cache_seconds = round(prior_cache['elapsedSeconds'] - by_check['actual_media_extraction_verified']['elapsedSeconds'], 3)
    started = time.monotonic()
    events = []
    requests = []
    log_path = work / 'execution.jsonl'

    def record(name, **details):
        event = {'check': name, 'timestamp': datetime.now(timezone.utc).isoformat(), 'elapsedSeconds': round(time.monotonic() - started, 3), **details}
        events.append(event)
        with log_path.open('a') as log:
            log.write(json.dumps(event, sort_keys=True) + '\n')
        print(json.dumps(event, sort_keys=True), flush=True)

    result = suite._verify_suite_pack_file(str(pack), metadata)
    if not result.ok:
        raise RuntimeError(result.message)
    size = pack.stat().st_size
    record('pinned_source_archive_verified', sha256=metadata['distribution']['sha256'], byteSize=size)
    truncated = work / 'truncated.tar.gz'
    with pack.open('rb') as source:
        truncated.write_bytes(source.read(1024 * 1024))
    result = suite._verify_suite_pack_file(str(truncated), metadata)
    assert not result.ok and 'size mismatch' in result.message
    record('truncated_archive_rejected', reason=result.message, byteSize=truncated.stat().st_size)
    sparse = work / 'corrupt.tar.gz'
    with sparse.open('wb') as handle:
        handle.write(b'corrupt')
        handle.truncate(size)
    result = suite._verify_suite_pack_file(str(sparse), metadata)
    assert not result.ok and 'checksum mismatch' in result.message
    sparse.unlink()
    record('same_size_corrupt_archive_rejected', reason=result.message, byteSize=size, construction='sparse corrupt archive; full checksum executed')
    failed_cache = work / 'failed-cache'
    try:
        suite._extract_suite_pack(str(truncated), metadata, str(failed_cache))
    except Exception as error:
        record('interrupted_extraction_rejected', errorType=type(error).__name__, error=str(error))
    else:
        raise AssertionError('Truncated archive extraction unexpectedly succeeded')
    target = Path(suite._suite_pack_extract_root(metadata, str(failed_cache)))
    assert not target.exists()
    assert not list(target.parent.glob('suite-pack-*'))
    record('failed_extraction_is_atomic', publishedCacheExists=False, stagingDirectoriesRemain=False)
    truncated.unlink()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *unused):
            pass

        def do_GET(self):
            if self.path != '/suite.tar.gz':
                self.send_error(404)
                return
            range_header = self.headers.get('Range')
            offset = int(range_header[6:-1]) if range_header else 0
            interrupt = len(requests) == 0
            event = {'range': range_header, 'offset': offset, 'interrupted': interrupt, 'bytesSent': 0}
            requests.append(event)
            self.send_response(206 if range_header else 200)
            self.send_header('Content-Length', str(size - offset))
            if range_header:
                self.send_header('Content-Range', f'bytes {offset}-{size - 1}/{size}')
            self.end_headers()
            with pack.open('rb') as source:
                source.seek(offset)
                remaining = min(4 * 1024 * 1024, size - offset) if interrupt else size - offset
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
                    event['bytesSent'] += len(chunk)
            self.wfile.flush()
            if interrupt:
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()

    server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}/suite.tar.gz'
    downloaded = work / 'downloaded.tar.gz'
    partial = Path(str(downloaded) + '.part')
    try:
        try:
            suite._download_suite_pack(url, str(downloaded), metadata)
        except Exception as error:
            record('network_interruption_detected', errorType=type(error).__name__, error=str(error))
        else:
            raise AssertionError('Injected network interruption did not fail acquisition')
        assert not downloaded.exists()
        retained = partial.stat().st_size
        assert 0 < retained < size
        record('partial_download_retained_without_publication', partialBytes=retained, destinationExists=False)
        suite._download_suite_pack(url, str(downloaded), metadata)
        assert downloaded.is_file() and not partial.exists()
        assert len(requests) == 2 and requests[1]['offset'] == retained
        result = suite._verify_suite_pack_file(str(downloaded), metadata)
        assert result.ok, result.message
        record('range_resume_completed_and_verified', requests=requests, sha256=metadata['distribution']['sha256'], byteSize=downloaded.stat().st_size, partialExists=False)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()

    cache = work / 'cache'
    canonical = Path(suite._extract_suite_pack(str(downloaded), metadata, str(cache)))
    manifest = suite.manifest_from_payload(json.loads((canonical.parent / 'manifest.json').read_text()))
    record('actual_media_extraction_verified', clips=[{'clipId': clip.clip_id, 'sha256': clip.sha256, 'byteSize': clip.byte_size} for clip in manifest.clips], noticesVerified=True, clipTechnicalContractsVerified=True)
    # Cache reuse must succeed even when the requested archive does not exist.
    downloaded.unlink()
    cache_started = time.monotonic()
    reused = suite._extract_suite_pack(str(downloaded), metadata, str(cache))
    cache_seconds = round(time.monotonic() - cache_started, 3)
    assert reused == str(canonical) and not downloaded.exists()
    record('cache_reuse_without_archive_verified', durationSeconds=cache_seconds, archiveExists=False, allClipBytesReverified=True, initialTechnicalValidationBoundByExactHashes=True)
    damaged_clip = manifest.clips[0]
    damaged_path = canonical / damaged_clip.file_name
    with damaged_path.open('r+b') as handle:
        handle.seek(128)
        original = handle.read(1)
        handle.seek(128)
        handle.write(bytes([original[0] ^ 255]))
        handle.flush()
        os.fsync(handle.fileno())
    result = suite.verify_suite_clip(str(damaged_path), damaged_clip)
    assert not result.ok and 'checksum mismatch' in result.message
    record('tampered_cached_clip_rejected', clipId=damaged_clip.clip_id, reason=result.message, fileSizeUnchanged=damaged_path.stat().st_size == damaged_clip.byte_size)
    repaired = suite._extract_suite_pack(str(pack), metadata, str(cache))
    assert repaired == str(canonical)
    assert suite._sha256_of_file(str(damaged_path)) == damaged_clip.sha256
    record('automatic_cache_repair_verified', clipId=damaged_clip.clip_id, restoredSha256=damaged_clip.sha256, allClipTechnicalContractsReverified=True, source='verified original candidate archive')
    elapsed = round(time.monotonic() - started, 3)
    report = {'schemaVersion': 1, 'status': 'passed', 'suiteVersion': metadata['suiteVersion'], 'suiteFingerprint': metadata['suiteFingerprint'], 'archiveSha256': metadata['distribution']['sha256'], 'archiveByteSize': size, 'elapsedSeconds': elapsed, 'cachedValidationSeconds': cache_seconds, 'priorFullProbeCachedValidationSeconds': baseline_cache_seconds, 'transportScope': 'Loopback fault injection with actual pinned candidate pack; public remote clean acquisition is separately certified.', 'validation': 'Actual archive hashes, notice hashes, per-clip hashes and ffprobe media contracts; no mocks or synthetic media.', 'maximumAdditionalMediaStorageBytes': size * 2, 'executionLog': str(log_path.relative_to(ROOT)) if log_path.is_relative_to(ROOT) else str(log_path), 'events': events}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    temp_report = args.report.with_suffix('.json.tmp')
    temp_report.write_text(json.dumps(report, indent=2) + '\n')
    os.replace(temp_report, args.report)
    print(f'PASS acquisition recovery; {elapsed}s; report: {args.report}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
