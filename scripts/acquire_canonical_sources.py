#!/usr/bin/env python3
"""Acquire catalogued master excerpts with a bounded, verified HTTP range cache.

No whole-master checksum is claimed. Each fetched byte block is retained and
hashed; FFmpeg reads these original blocks through a local range server. Reruns
verify every cache block before reuse. Completed outputs are verified by SHA256.
"""
import argparse
import concurrent.futures
import hashlib
import http.server
import json
import pathlib
import re
import shutil
import subprocess
import threading
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'docs/canonical-sources/catalog.json'
CHUNK = 8 * 1024 * 1024


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def fetch(url, headers=None):
    error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=90) as r:
                if headers and 'Range' in headers and r.status != 206:
                    raise RuntimeError('Server ignored byte range; refusing whole-object download')
                limit = 128 * 1024 * 1024
                if int(r.headers.get('Content-Length', '0')) > limit:
                    raise RuntimeError('Response exceeds bounded acquisition request size')
                body = r.read(limit + 1)
                if len(body) > limit:
                    raise RuntimeError('Response exceeds bounded acquisition request size')
                return body, dict(r.headers), r.status
        except Exception as exc:
            error = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f'Failed after 3 attempts: {url}: {error}')


def acquire_png(source, dest, evidence, out, args):
    checksum_data, _, _ = fetch(source['checksums_url'])
    checksum_path = ROOT / 'docs/canonical-sources/notices/tears-of-steel-SHA256SUMS.txt'
    checksum_path.write_bytes(checksum_data)
    sums = {line.split()[1].lstrip('*'): line.split()[0] for line in checksum_data.decode().splitlines()}
    frames = dest / 'original-frames'
    frames.mkdir(exist_ok=True)
    def one(number):
        name = f"graded_edit_final_{number:05d}.png"
        path = frames / name
        expected = sums.get(name)
        if not expected:
            raise RuntimeError(f'No published SHA256 for {name}')
        if path.exists():
            if sha(path) != expected:
                raise RuntimeError(f'Corrupt cached original: {path}')
        else:
            if shutil.disk_usage(dest).free < args.reserve_gib * 2**30 + 64*1024**2:
                raise RuntimeError('Capacity reserve reached')
            body, _, _ = fetch(source['url'] + name)
            if hashlib.sha256(body).hexdigest() != expected:
                raise RuntimeError(f'Published SHA256 mismatch for {name}')
            tmp = path.with_suffix('.part'); tmp.write_bytes(body); tmp.replace(path)
        return {'original_filename': name, 'url': source['url']+name, 'bytes': path.stat().st_size, 'sha256': expected, 'published_sha256_verified': True}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        acquired = list(pool.map(one, range(source['start_frame'], source['start_frame']+source['frame_count'])))
    if shutil.disk_usage(dest).free < args.reserve_gib * 2**30 + sum(x['bytes'] for x in acquired) * 2:
        raise RuntimeError('Insufficient capacity for lossless excerpt plus reserve')
    command = [args.ffmpeg, '-hide_banner', '-nostdin', '-y', '-framerate', '24', '-start_number', str(source['start_frame']), '-i', str(frames/'graded_edit_final_%05d.png'), '-frames:v', str(source['frame_count']), '-c:v', 'ffv1', '-level', '3', '-pix_fmt', 'gbrp', str(out)]
    with open(dest/'acquisition.log','w') as log:
        subprocess.run(command, check=True, stdout=log, stderr=log)
    evidence.write_text(json.dumps({'source': source, 'retrieved_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()), 'original_frames':acquired, 'partial_download':False, 'whole_movie_downloaded':False, 'excerpt_path':str(out.relative_to(ROOT)), 'excerpt_sha256':sha(out), 'excerpt_bytes':out.stat().st_size, 'ffmpeg_sha256':sha(args.ffmpeg), 'command':command, 'transformation':'Original RGB PNG pixels stored losslessly as FFV1 gbrp; no resizing, color conversion, or frame rate change.'},indent=2)+'\n')
    print(f'Acquired {len(acquired)} publisher-checksummed PNG frames: {out}',flush=True)


def acquire_tiff(source, dest, evidence, out, args):
    # Small lossless segments make huge TIFF sequence acquisition resumable while
    # preserving original RGB sample values and avoiding whole-master downloads.
    records = []; segments = []
    for offset in range(0, source['frame_count'], 24):
        first = source['start_frame'] + offset
        count = min(24, source['frame_count'] - offset)
        segment = dest / f'segment-{first}.mkv'
        manifest = segment.with_suffix('.json')
        if segment.exists() and manifest.exists():
            saved = json.loads(manifest.read_text())
            if sha(segment) != saved['sha256'] or saved['source'] != source:
                raise RuntimeError('Segment cache mismatch')
            acquired = saved['original_frames']
        else:
            frames = dest / f'frames-{first}'
            frames.mkdir(exist_ok=True)
            def one(number):
                name = source['filename_pattern'] % number
                path = frames/name
                url = source['url']+name
                if shutil.disk_usage(dest).free < args.reserve_gib*2**30 + 1024**3:
                    raise RuntimeError('Insufficient capacity for bounded TIFF segment')
                body, hdr, _ = fetch(url)
                tmp=path.with_suffix('.part');tmp.write_bytes(body);tmp.replace(path)
                return {'frame':number,'url':url,'original_filename':name,'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest(),'etag':hdr.get('ETag')}
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                acquired=list(pool.map(one,range(first,first+count)))
            command=[args.ffmpeg,'-hide_banner','-nostdin','-y','-framerate',source['frame_rate'],'-start_number',str(first),'-i',str(frames/source['filename_pattern']),'-frames:v',str(count),'-vf',source.get('acquisition_filter','null'),'-c:v','ffv1','-level','3','-pix_fmt','gbrp16le',str(segment)]
            with open(dest/f'segment-{first}.log','w') as log:
                subprocess.run(command,check=True,stdout=log,stderr=log)
            manifest.write_text(json.dumps({'source':source,'command':command,'sha256':sha(segment),'original_frames':acquired},indent=2)+'\n')
            # Exact decoded RGB originals survive in the lossless segment; original
            # TIFF file/container hashes above identify the fetched source bytes.
            shutil.rmtree(frames)
        records.extend(acquired);segments.append(segment)
        print(f'Verified {len(records)}/{source["frame_count"]} TIFF frames',flush=True)
    listing=dest/'segments.txt'
    listing.write_text(''.join("file '"+p.name+"'\n" for p in segments))
    command=[args.ffmpeg,'-hide_banner','-nostdin','-y','-f','concat','-safe','0','-i',str(listing),'-map','0:v:0','-c:v','copy',str(out)]
    subprocess.run(command,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    check=subprocess.run([args.ffmpeg,'-v','error','-xerror','-i',str(out),'-f','null','-'],capture_output=True,text=True)
    if check.returncode:raise RuntimeError(check.stderr)
    evidence.write_text(json.dumps({'source':source,'retrieved_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'original_frames':records,'partial_download':False,'whole_movie_downloaded':False,'excerpt_path':str(out.relative_to(ROOT)),'excerpt_sha256':sha(out),'excerpt_bytes':out.stat().st_size,'ffmpeg_sha256':sha(args.ffmpeg),'command':command,'complete_decode_exit':check.returncode,'transformation':'Original TIFF RGB48 decoded; acquisition filter '+source.get('acquisition_filter','null')+'; resulting RGB pixels losslessly stored as FFV1 gbrp16le in 24-frame resumable segments. Container TIFF inputs removed after segment verification; exact fetched TIFF hashes retained. Lossless storage does not undo explicit spatial normalization.'},indent=2)+'\n')
    print(f'Acquired and fully decoded {out}',flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source', help='Catalog source ID')
    ap.add_argument('--ffmpeg', default=str(ROOT / 'client/bin/mac/ffmpeg'))
    ap.add_argument('--reserve-gib', type=float, default=5)
    args = ap.parse_args()
    source = json.loads(CATALOG.read_text())[args.source]
    dest = ROOT / '.build/canonical-sources' / args.source
    dest.mkdir(parents=True, exist_ok=True)
    evidence = ROOT / 'docs/canonical-sources' / (args.source + '-acquisition.json')
    out = dest / (args.source + '-source.mkv')
    if out.exists() and evidence.exists():
        old = json.loads(evidence.read_text())
        if old['source'] != source:
            raise RuntimeError('Catalog selection changed; use a new source ID or explicitly quarantine prior cache')
        if sha(out) == old['excerpt_sha256']:
            print(f'Verified completed cache: {out}', flush=True)
            return
        raise RuntimeError(f'Completed output hash mismatch: {out}; quarantine it before retry')
    if source.get('kind') == 'tiff-sequence':
        acquire_tiff(source, dest, evidence, out, args)
        return
    if source.get('kind') == 'png-sequence':
        acquire_png(source, dest, evidence, out, args)
        return
    url = source['url']
    data, headers, status = fetch(url, {'Range': 'bytes=0-0'})
    if status != 206 or not re.fullmatch(r'bytes 0-0/\d+', headers.get('Content-Range', '')):
        raise RuntimeError('Source must support exact HTTP byte ranges')
    size = int(headers['Content-Range'].split('/')[1])
    cache = dest / 'original-byte-ranges'
    cache.mkdir(exist_ok=True)
    identity_path = cache / 'source-identity.json'
    identity = {'url': url, 'bytes': size, 'etag': headers.get('ETag')}
    if identity_path.exists() and json.loads(identity_path.read_text()) != identity:
        raise RuntimeError('Remote source identity changed; cached ranges cannot be mixed')
    identity_path.write_text(json.dumps(identity, indent=2) + '\n')
    records = {}
    lock = threading.Lock()

    def block(start):
        with lock:
            end = min(start + CHUNK, size) - 1
            path = cache / f'{start}-{end}.bin'
            meta = path.with_suffix('.json')
            if path.exists() and meta.exists():
                info = json.loads(meta.read_text())
                if path.stat().st_size != end-start+1 or sha(path) != info['sha256']:
                    raise RuntimeError(f'Corrupt cached byte range: {path}')
            else:
                if shutil.disk_usage(dest).free < args.reserve_gib * 2**30 + CHUNK:
                    raise RuntimeError('Capacity reserve reached; free space before resuming')
                body, hdr, code = fetch(url, {'Range': f'bytes={start}-{end}', 'If-Match': headers['ETag']} if headers.get('ETag') else {'Range': f'bytes={start}-{end}'})
                if code != 206 or hdr.get('Content-Range') != f'bytes {start}-{end}/{size}' or len(body) != end-start+1:
                    raise RuntimeError('Remote range mismatch or truncated transfer')
                tmp = path.with_suffix('.part')
                tmp.write_bytes(body)
                tmp.replace(path)
                info = {'start': start, 'end_inclusive': end, 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
                meta.write_text(json.dumps(info, indent=2)+'\n')
            records[start] = info
            return path.read_bytes()

    errors = []
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *unused):
            pass
        def do_GET(self):
            try:
                match = re.fullmatch(r'bytes=(\d+)-(\d*)', self.headers.get('Range', 'bytes=0-'))
                if not match:
                    self.send_error(400)
                    return
                start = int(match[1]); end = int(match[2]) if match[2] else size - 1
                self.send_response(206)
                self.send_header('Content-Length', str(end-start+1))
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                self.send_header('Accept-Ranges', 'bytes')
                self.end_headers()
                while start <= end:
                    aligned = start // CHUNK * CHUNK
                    body = block(aligned)
                    part = body[start-aligned:min(len(body),end-aligned+1)]
                    self.wfile.write(part)
                    start += len(part)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:
                errors.append(str(exc))
                print(f'Acquisition error: {exc}', flush=True)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    tmp = out.with_suffix('.partial.mkv')
    command = [args.ffmpeg, '-hide_banner', '-nostdin', '-y', '-ss', str(source['start_seconds']), '-i', f'http://127.0.0.1:{server.server_port}/source', '-t', str(source['duration_seconds']), '-map', '0:v:0', '-an', '-sn', '-dn', '-c:v', 'copy', '-map_metadata', '-1', str(tmp)]
    try:
        with open(dest/'acquisition.log','w') as log:
            result = subprocess.run(command, stdout=log, stderr=log)
        if result.returncode or errors:
            raise RuntimeError(f'Acquisition failed: exit={result.returncode}; {errors}; see {dest}/acquisition.log')
    finally:
        server.shutdown()
        server.server_close()
    tmp.replace(out)
    # Independent complete decode checks packet-copy excerpt integrity.
    check = subprocess.run([args.ffmpeg, '-v', 'error', '-xerror', '-i', str(out), '-map', '0:v:0', '-f', 'null', '-'], capture_output=True, text=True)
    if check.returncode:
        raise RuntimeError(f'Full excerpt decode failed: {check.stderr}')
    info = {'source': source, 'retrieved_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'remote_original_bytes': size, 'remote_etag': headers.get('ETag'), 'whole_master_sha256': None, 'partial_download': True, 'fetched_original_byte_ranges': sorted(records.values(), key=lambda x:x['start']), 'excerpt_path': str(out.relative_to(ROOT)), 'excerpt_bytes': out.stat().st_size, 'excerpt_sha256': sha(out), 'transformation': 'Video packets copied from selected time range to Matroska; no pixel encoding, audio omitted.', 'ffmpeg_sha256': sha(args.ffmpeg), 'command': command, 'complete_decode_exit': check.returncode}
    evidence.write_text(json.dumps(info, indent=2)+'\n')
    print(f'Acquired and fully decoded {out}: {out.stat().st_size} bytes', flush=True)


if __name__ == '__main__':
    main()
