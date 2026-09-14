#!/usr/bin/env python3
"""Prepare explicitly validation-only longer scenes; never edit the frozen suite.

A bounded local HTTP proxy streams verified upstream byte ranges into FFmpeg.
Original ranges are hashed, not claimed to be a complete-master checksum. Original
video packet payloads are additionally hashed while the reference is normalized.
"""
import argparse
import concurrent.futures
import hashlib
import http.server
import json
import os
import signal
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import urllib.request

CHUNK = 8 * 1024 * 1024

def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.part')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)

class Budget:
    def __init__(self, root, max_bytes, reserve_bytes):
        self.root, self.maximum, self.reserve = root, max_bytes, reserve_bytes
        self.path = root / 'download-budget.json'
        self.downloaded = json.loads(self.path.read_text())['downloadedBytes'] if self.path.exists() else 0
        self.lock = threading.Lock()

    def fetch(self, url, headers=None):
        for attempt in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=90) as response:
                    expected = int(response.headers.get('Content-Length', '0'))
                    if expected > 64 * 1024 * 1024:
                        raise RuntimeError('Refusing unbounded response')
                    with self.lock:
                        if self.downloaded + expected > self.maximum:
                            raise RuntimeError('Download budget exhausted')
                        if shutil.disk_usage(self.root).free < self.reserve:
                            raise RuntimeError('Disk reserve reached')
                        data = response.read(64 * 1024 * 1024 + 1)
                        self.downloaded += len(data)
                        write_json(self.path, {'maximumBytes': self.maximum, 'downloadedBytes': self.downloaded})
                    if len(data) > 64 * 1024 * 1024 or self.downloaded > self.maximum:
                        raise RuntimeError('Download budget exceeded')
                    return data, dict(response.headers), response.status
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)


def filters(kind):
    if kind == 'nocturne':
        return ('fps=24:start_time=0,scale=1920:1080:flags=lanczos:in_range=tv:out_range=tv:'
                'in_color_matrix=bt709:out_color_matrix=bt709,format=yuv420p,setsar=1')
    if kind == 'sol':
        return ('scale=1920:1080:flags=lanczos:in_range=tv:out_range=tv:'
                'in_color_matrix=bt709:out_color_matrix=bt709,format=yuv420p,setsar=1')
    if kind == 'chimera':
        return ('zscale=primariesin=smpte432:transferin=smpte2084:matrixin=gbr:rangein=full:'
                'primaries=smpte432:matrix=gbr:range=full:transfer=linear:npl=100,format=gbrpf32le,zscale=primaries=bt709,'
                'tonemap=tonemap=hable:desat=0:peak=40,zscale=transfer=bt709:matrix=bt709:range=limited:dither=error_diffusion,'
                'scale=1920:1012:flags=lanczos,format=yuv420p,pad=1920:1080:0:34:black,setsar=1')
    if kind == 'tos':
        return ('zscale=primariesin=bt709:transferin=iec61966-2-1:matrixin=gbr:rangein=full:'
                'primaries=bt709:transfer=bt709:matrix=bt709:range=limited:dither=error_diffusion,'
                'format=yuv420p,pad=1920:1080:0:140:black,setsar=1')
    raise ValueError('No approved normalization for source')


def run(command, log):
    with log.open('w') as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=stream, start_new_session=True)
        deadline = time.monotonic() + 3600
        while process.poll() is None:
            if time.monotonic() >= deadline or shutil.disk_usage(log.parent).free < 5 * 2**30:
                os.killpg(process.pid, signal.SIGTERM)
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL); process.wait()
                raise RuntimeError(f'Owned preparation process stopped at time/disk limit: {log}')
            time.sleep(1)
    if process.returncode:
        raise RuntimeError(f'Command failed ({process.returncode}): {log}')
    return process.returncode


def prepare(entry, args, budget):
    target = args.output / entry['id']
    target.mkdir(exist_ok=True)
    report_path = target / 'evidence.json'
    media = target / 'reference.mkv'
    if report_path.exists():
        existing = json.loads(report_path.read_text())
        if existing['planEntry'] != entry or existing['sha256'] != sha(media):
            raise RuntimeError(f'Existing output does not match frozen plan: {entry["id"]}')
        print(f'Verified existing {entry["id"]}', flush=True)
        return existing
    for forbidden in entry['frozenFrameRanges']:
        if max(entry['firstSourceFrame'], forbidden['start']) < min(entry['endSourceFrameExclusive'], forbidden['endExclusive']):
            raise RuntimeError('Selected source frames overlap frozen suite')
    source_records, errors = {}, []
    command_input = []
    server = None
    original_hash_path = target / 'original-packet-payload.sha256'
    if entry['kind'] == 'movie-range':
        _, headers, status = budget.fetch(entry['url'], {'Range': 'bytes=0-0'})
        if status != 206 or not re.fullmatch(r'bytes 0-0/\d+', headers.get('Content-Range', '')):
            raise RuntimeError('Exact byte ranges are required')
        size = int(headers['Content-Range'].split('/')[1])
        identity = {'url': entry['url'], 'bytes': size, 'etag': headers.get('ETag')}
        if size != entry['expectedOriginalBytes'] or identity['etag'] != entry['expectedOriginalEtag']:
            raise RuntimeError('Licensed original identity differs from retained acquisition receipt')
        identity_path = target / 'original-identity.json'
        if identity_path.exists() and json.loads(identity_path.read_text()) != identity:
            raise RuntimeError('Upstream source identity changed')
        write_json(identity_path, identity)
        lock = threading.Lock()
        cache = {}
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *unused):
                pass
            def do_GET(self):
                try:
                    match = re.fullmatch(r'bytes=(\d+)-(\d*)', self.headers.get('Range', 'bytes=0-'))
                    if not match:
                        self.send_error(400); return
                    start = int(match[1]); end = int(match[2]) if match[2] else size - 1
                    self.send_response(206)
                    self.send_header('Content-Length', str(end - start + 1))
                    self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                    self.send_header('Accept-Ranges', 'bytes'); self.end_headers()
                    while start <= end:
                        aligned = start // CHUNK * CHUNK
                        with lock:
                            if aligned not in cache:
                                finish = min(aligned + CHUNK, size) - 1
                                request_headers = {'Range': f'bytes={aligned}-{finish}'}
                                if headers.get('ETag'): request_headers['If-Match'] = headers['ETag']
                                body, hdr, code = budget.fetch(entry['url'], request_headers)
                                if code != 206 or hdr.get('Content-Range') != f'bytes {aligned}-{finish}/{size}' or len(body) != finish - aligned + 1:
                                    raise RuntimeError('Source range response mismatch')
                                record = {'start': aligned, 'endInclusive': finish, 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
                                if aligned in source_records and source_records[aligned] != record:
                                    raise RuntimeError('Previously fetched source bytes changed')
                                source_records[aligned] = record
                                cache[aligned] = body
                                while len(cache) > 3: cache.pop(next(iter(cache)))
                            body = cache[aligned]
                        part = body[start - aligned:min(len(body), end - aligned + 1)]
                        self.wfile.write(part); start += len(part)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as exc:
                    errors.append(str(exc))
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        command_input = ['-ss', str(entry['startSeconds']), '-threads', '2', '-i', f'http://127.0.0.1:{server.server_port}/source']
    elif entry['kind'] == 'png-sequence':
        checksums_path = args.plan.parent / entry['publisherChecksumsFile']
        if sha(checksums_path) != entry['publisherChecksumsSha256']:
            raise RuntimeError('Publisher checksum manifest changed')
        checksums = {line.split()[1].lstrip('*'): line.split()[0] for line in checksums_path.read_text().splitlines()}
        frames = target / 'original-frames'; frames.mkdir(exist_ok=True)
        def acquire_frame(number):
            name = f'graded_edit_final_{number:05d}.png'; frame = frames / name
            expected = checksums.get(name)
            if not expected: raise RuntimeError(f'Missing publisher frame hash {name}')
            if not frame.exists():
                data, _, _ = budget.fetch(entry['url'] + name)
                if hashlib.sha256(data).hexdigest() != expected: raise RuntimeError(f'Publisher checksum mismatch {name}')
                temporary = frame.with_suffix('.part'); temporary.write_bytes(data); temporary.replace(frame)
            if sha(frame) != expected: raise RuntimeError(f'Corrupt acquired frame {name}')
            return {'start': number - 1, 'unit': 'source-frame-zero-based', 'originalFilename': name, 'url': entry['url'] + name, 'bytes': frame.stat().st_size, 'sha256': expected, 'publisherHashVerified': True}
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            records = list(pool.map(acquire_frame, range(entry['firstSourceFrame'] + 1, entry['endSourceFrameExclusive'] + 1)))
        source_records = {record['start']: record for record in records}
        identity = {'url': entry['url'], 'publisherChecksumsSha256': entry['publisherChecksumsSha256'], 'originalFrameCount': len(records)}
        command_input = ['-framerate', '24', '-start_number', str(entry['firstSourceFrame'] + 1), '-threads', '2', '-i', str(frames / 'graded_edit_final_%05d.png')]
    elif entry['kind'] == 'tiff-sequence':
        segments = []
        for first in range(entry['firstSourceFrame'], entry['endSourceFrameExclusive'], 24):
            if (args.output / 'PAUSE').exists():
                print('Pause requested at completed TIFF segment boundary; owned segments retained.', flush=True); return None
            count = min(24, entry['endSourceFrameExclusive'] - first)
            segment = target / f'normalized-segment-{first}.mkv'
            metadata_path = segment.with_suffix('.json')
            if segment.exists() and metadata_path.exists():
                saved = json.loads(metadata_path.read_text())
                if sha(segment) != saved['sha256'] or saved.get('sourcePlanHash') != canonical_hash(entry): raise RuntimeError('Changed retained normalized segment or source plan')
                records = saved['originalFrames']
            else:
                frames = target / f'owned-tiff-frames-{first}'; frames.mkdir(exist_ok=True)
                def acquire_tiff(number):
                    name = entry['filenamePattern'] % number; file = frames / name
                    data, headers, _ = budget.fetch(entry['url'] + name)
                    temporary = file.with_suffix('.part'); temporary.write_bytes(data); temporary.replace(file)
                    return {'start': number, 'unit': 'source-frame-zero-based', 'url': entry['url'] + name, 'originalFilename': name,
                            'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'etag': headers.get('ETag'), 'publisherHashVerified': False}
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    records = list(pool.map(acquire_tiff, range(first, first + count)))
                normalize = [str(args.ffmpeg), '-hide_banner', '-nostdin', '-y', '-threads', '2', '-framerate', entry['sourceFrameRate'],
                             '-start_number', str(first), '-i', str(frames / entry['filenamePattern']), '-filter_threads', '2', '-vf', 'scale=1920:1012:flags=lanczos,setsar=1,format=gbrp16le,' + filters('chimera'),
                             '-frames:v', str(count), '-threads', '2', '-c:v', 'ffv1', '-level', '3', '-g', '1', '-slicecrc', '1', '-pix_fmt', 'yuv420p',
                             '-color_range', 'tv', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', str(segment)]
                run(normalize, target / f'segment-{first}.log')
                write_json(metadata_path, {'sha256': sha(segment), 'sourcePlanHash': canonical_hash(entry), 'originalFrames': records, 'command': normalize})
                shutil.rmtree(frames)  # only this task's newly acquired TIFF files, after verified segment persistence
            source_records.update({record['start']: record for record in records}); segments.append(segment)
            print(f'{entry["id"]}: normalized {len(source_records)} source frames', flush=True)
        listing = target / 'normalized-segments.txt'; listing.write_text(''.join(f"file '{segment.name}'\n" for segment in segments))
        command_input = ['-threads', '2', '-f', 'concat', '-safe', '0', '-i', str(listing)]
        identity = {'url': entry['url'], 'originalFrameCount': len(source_records), 'sourceFrameRate': entry['sourceFrameRate']}
        original_hash_path = target / 'normalized-intermediate-packet-payload.sha256'
    else:
        raise RuntimeError('No approved source acquisition for this plan entry')
    vf = ('fps=24:start_time=0,setsar=1' if entry['kind'] == 'tiff-sequence' else filters(entry['normalization'])) + ',setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709'
    command = [str(args.ffmpeg), '-hide_banner', '-nostdin', '-y', '-filter_threads', '2', *command_input,
               '-map', '0:v:0', '-t', str(entry['durationSeconds']), '-vf', vf,
               '-frames:v', str(entry['durationSeconds'] * 24), '-threads', '2', '-c:v', 'ffv1', '-level', '3', '-g', '1', '-slicecrc', '1',
               '-pix_fmt', 'yuv420p', '-color_range', 'tv', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709',
               '-map_metadata', '-1', '-fflags', '+bitexact', '-flags:v', '+bitexact', '-an', '-sn', '-dn', str(media),
               '-map', '0:v:0', '-t', str(entry['durationSeconds']), '-c:v', 'copy', '-f', 'hash', '-hash', 'sha256', str(original_hash_path)]
    print(f'Preparing {entry["id"]} with two decoder/filter/encoder threads', flush=True)
    try:
        run(command, target / 'prepare.log')
        if errors: raise RuntimeError(str(errors))
    finally:
        if server: server.shutdown(); server.server_close()
        if source_records: write_json(target / ('original-byte-ranges.json' if entry['kind'] == 'movie-range' else 'original-frame-hashes.json'), list(sorted(source_records.values(), key=lambda x: x['start'])))
    probe_command = [str(args.ffprobe), '-v', 'error', '-count_frames', '-show_streams', '-show_format', '-of', 'json', '-threads', '2', str(media)]
    probe = json.loads(subprocess.check_output(probe_command, timeout=3600))
    stream = probe['streams'][0]
    assert len(probe['streams']) == 1 and stream['codec_type'] == 'video'
    assert (stream['width'], stream['height'], stream['pix_fmt'], stream['avg_frame_rate']) == (1920, 1080, 'yuv420p', '24/1')
    assert int(stream['nb_read_frames']) == entry['durationSeconds'] * 24
    assert abs(float(probe['format']['duration']) - entry['durationSeconds']) < 0.002
    for field in ['color_space', 'color_transfer', 'color_primaries']: assert stream[field] == 'bt709'
    assert stream['color_range'] == 'tv'
    decode_command = [str(args.ffmpeg), '-v', 'error', '-xerror', '-threads', '2', '-i', str(media), '-map', '0:v:0', '-f', 'null', '-']
    run(decode_command, target / 'full-decode.log')
    sheet_command = [str(args.ffmpeg), '-v', 'error', '-y', '-threads', '2', '-i', str(media), '-filter_threads', '2',
                     '-vf', 'select=not(mod(n\\,120)),scale=480:270,tile=3x2', '-frames:v', '1', '-threads', '2', str(target / 'contact.jpg')]
    run(sheet_command, target / 'contact.log')
    result = {'schemaVersion': 'encodingdb-validation-scene/v1', 'status': 'TECHNICALLY_VALIDATED_REVIEW_PENDING', 'validationOnly': True,
              'planEntry': entry, 'sourceIdentity': identity, 'wholeMasterSha256': None,
              'originalPacketPayloadHash': original_hash_path.read_text().strip() if entry['kind'] != 'tiff-sequence' else None,
              'normalizedIntermediatePacketPayloadHash': original_hash_path.read_text().strip() if entry['kind'] == 'tiff-sequence' else None,
              'originalSourceManifestHash': canonical_hash(list(sorted(source_records.values(), key=lambda x: x['start']))),
              'sourceHashSemantics': 'Individually hashed original source records. Movie packet hashes cover original ProRes payloads; PNG hashes are publisher-verified. TIFF hashes cover fetched original files (no publisher hash available); normalized intermediate packet hash is not an original-source hash. No whole-master hash claimed.',
              'sha256': sha(media), 'byteSize': media.stat().st_size, 'mediaPath': str(media), 'probe': probe,
              'commands': [command, probe_command, decode_command, sheet_command], 'exitCodes': [0, 0, 0, 0],
              'runtimeSha256': sha(args.ffmpeg), 'ffprobeSha256': sha(args.ffprobe),
              'sourcePixelsPreservedAfterDeclaredNormalization': 'FFV1 lossless at1080p24 SDR; source was downsampled explicitly, no denoise/interpolation/looping.',
              'humanReviewer': None, 'humanJudgment': None, 'preparedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    write_json(report_path, result)
    print(f'Validated {entry["id"]}: {result["sha256"]}', flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ffmpeg', type=Path, required=True)
    parser.add_argument('--ffprobe', type=Path, required=True)
    parser.add_argument('--only', action='append')
    parser.add_argument('--max-download-gib', type=int, default=20)
    parser.add_argument('--reserve-gib', type=int, default=5)
    args = parser.parse_args()
    args.output = args.output.resolve(); args.output.mkdir(parents=True, exist_ok=True)
    plan = json.loads(args.plan.read_text())
    budget = Budget(args.output, args.max_download_gib * 2**30, args.reserve_gib * 2**30)
    for entry in plan['scenes']:
        if args.only and entry['id'] not in args.only: continue
        if (args.output / 'PAUSE').exists():
            print('Pause requested; completed scenes retained, no new FFmpeg started.', flush=True); return
        if sum(path.stat().st_size for path in args.output.rglob('*') if path.is_file()) > 20 * 2**30 - 3 * 2**30:
            raise RuntimeError('20GiB task storage budget lacks room for the next bounded scene')
        prepare(entry, args, budget)

if __name__ == '__main__': main()
