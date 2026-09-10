#!/usr/bin/env python3
"""Execute and retain media checks; a successful technical report is not visual approval."""
import argparse
import hashlib
import json
from fractions import Fraction
from pathlib import Path
import subprocess
import time


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def run(command, log):
    started = time.monotonic()
    result = subprocess.run([str(x) for x in command], capture_output=True, text=True)
    log.write_text(json.dumps([str(x) for x in command]) + '\n' + result.stdout + '\n' + result.stderr)
    if result.returncode:
        raise RuntimeError(f'Command failed ({result.returncode}): {log}')
    return result.stdout, time.monotonic() - started


def probe(path, binary, log):
    stdout, _ = run([binary, '-v', 'error', '-count_frames', '-show_streams', '-show_format',
                     '-show_frames', '-of', 'json', path], log)
    return json.loads(stdout)


def check_media(data, count=None, codec='ffv1'):
    streams = data['streams']
    assert len(streams) == 1 and streams[0]['codec_type'] == 'video', 'unexpected streams'
    s = streams[0]
    for key, value in {'codec_name': codec, 'width': 1920, 'height': 1080,
                       'pix_fmt': 'yuv420p', 'color_range': 'tv', 'color_space': 'bt709',
                       'color_transfer': 'bt709', 'color_primaries': 'bt709'}.items():
        assert s.get(key) == value, f'{key}: {s.get(key)} != {value}'
    assert Fraction(s['avg_frame_rate']) == 24
    assert s.get('sample_aspect_ratio', '1:1') == '1:1'
    frames = data['frames']
    assert len(frames) >= 192, 'less than eight seconds of temporal coverage'
    assert int(s['nb_read_frames']) == len(frames)
    if count is not None:
        assert len(frames) == count, 'reference/distorted frame count mismatch'
    times = [Fraction(f['best_effort_timestamp_time']) for f in frames]
    assert abs(times[0]) < Fraction(1, 1000), 'nonzero start'
    for index, timestamp in enumerate(times):
        assert abs(timestamp - Fraction(index, 24)) <= Fraction(1, 1000), 'timestamp drift'
    assert all(not f.get('interlaced_frame') for f in frames), 'interlaced frames'
    hdr = ['Mastering display', 'Content light', 'DOVI', 'HDR Dynamic']
    assert not any(term.lower() in json.dumps(data).lower() for term in hdr), 'HDR metadata present'
    return len(frames)


def validate(path, args):
    out = args.output / path.stem
    out.mkdir(parents=True, exist_ok=True)
    data = probe(path, args.ffprobe, out / 'reference-probe.json.log')
    count = check_media(data)
    _, decode_seconds = run([args.ffmpeg, '-hide_banner', '-v', 'error', '-xerror', '-i', path,
                             '-map', '0:v:0', '-f', 'null', '-'], out / 'full-decode.log')
    md5, _ = run([args.ffmpeg, '-v', 'error', '-i', path, '-f', 'framemd5', '-'], out / 'framemd5.log')
    hashes = [line.split(',')[-1].strip() for line in md5.splitlines() if line and not line.startswith('#')]
    duplicates = sum(a == b for a, b in zip(hashes, hashes[1:]))
    run([args.ffmpeg, '-hide_banner', '-i', path, '-vf', 'blackdetect=d=0.1:pix_th=0.02,signalstats',
         '-an', '-f', 'null', '-'], out / 'signal-black-detection.log')
    run([args.ffmpeg, '-y', '-v', 'error', '-i', path, '-vf',
         'fps=1,scale=480:270,tile=5x2', '-frames:v', '1', out / 'contact-sheet.png'], out / 'contact-sheet.log')
    run([args.ffmpeg, '-y', '-v', 'error', '-ss', '3', '-i', path,
         '-frames:v', '1', out / 'detail-frame.png'], out / 'detail-frame.log')
    report = {'reference': str(path), 'sha256': digest(path), 'byteSize': path.stat().st_size,
              'frameCount': count, 'durationSeconds': count / 24, 'decodeSeconds': decode_seconds,
              'decodeRealtimeRatio': count / 24 / decode_seconds,
              'adjacentDuplicateFrames': duplicates, 'visualReview': 'PENDING', 'encodes': []}
    cases = [('libx264', q, args.ffmpeg) for q in (20, 28, 36)]
    cases += [('libx265', 28, args.ffmpeg)]
    if args.svt_ffmpeg:
        cases.append(('libsvtav1', 32, args.svt_ffmpeg))
    if args.hardware:
        cases.append((args.hardware, 2500, args.ffmpeg))
    for encoder, quality, binary in cases:
        label = f'{encoder}-{quality}'
        target = out / f'{label}.mp4'
        rate = ['-b:v', f'{quality}k'] if 'videotoolbox' in encoder else ['-crf', str(quality)]
        preset = [] if 'videotoolbox' in encoder else ['-preset', '8' if encoder == 'libsvtav1' else 'fast']
        _, elapsed = run([binary, '-y', '-hide_banner', '-i', path, '-map', '0:v:0', '-an',
                          '-c:v', encoder, *preset, *rate, '-pix_fmt', 'yuv420p',
                          '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
                          '-color_range', 'tv', '-video_track_timescale', '24000', target], out / f'{label}.encode.log')
        actual_codec = 'h264' if encoder.startswith(('libx264', 'h264')) else 'hevc' if encoder.startswith(('libx265', 'hevc')) else 'av1'
        encoded = probe(target, args.ffprobe, out / f'{label}.probe.log')
        check_media(encoded, count, actual_codec)
        metric_path = (out / f'{label}.vmaf.json').resolve()
        filtergraph = f'[0:v]setpts=PTS-STARTPTS[d];[1:v]setpts=PTS-STARTPTS[r];[d][r]libvmaf=model=path={args.model}:n_threads=2:log_fmt=json:log_path={metric_path}'
        run([args.ffmpeg, '-hide_banner', '-i', target, '-i', path, '-lavfi', filtergraph,
             '-f', 'null', '-'], out / f'{label}.vmaf.log')
        metrics = json.loads(metric_path.read_text())
        assert len(metrics['frames']) == count, 'VMAF alignment/frame coverage mismatch'
        run([args.ffmpeg, '-hide_banner', '-i', target, '-i', path,
             '-lavfi', '[0:v]setpts=PTS-STARTPTS[d];[1:v]setpts=PTS-STARTPTS[r];[d][r]xpsnr',
             '-f', 'null', '-'], out / f'{label}.xpsnr.log')
        packets, _ = run([args.ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_packets',
                          '-show_entries', 'packet=size', '-of', 'json', target], out / f'{label}.packets.log')
        video_bytes = sum(int(p['size']) for p in json.loads(packets)['packets'])
        report['encodes'].append({'encoder': encoder, 'nativeRateValue': quality, 'runtime': str(binary),
                                 'file': str(target), 'sha256': digest(target), 'bytes': target.stat().st_size,
                                 'videoBytes': video_bytes, 'videoBitrateBps': video_bytes * 8 * 24 / count,
                                 'elapsedSeconds': elapsed, 'encodeFps': count / elapsed,
                                 'vmafMean': metrics['pooled_metrics']['vmaf']['mean']})
        (out / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('references', nargs='+', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--ffmpeg', type=Path, default=Path('client/bin/mac/ffmpeg'))
    p.add_argument('--ffprobe', type=Path, default=Path('client/bin/mac/ffprobe'))
    p.add_argument('--svt-ffmpeg', type=Path)
    p.add_argument('--hardware')
    p.add_argument('--model', type=Path, default=Path('client/resources/vmaf/vmaf_v1.0.16_3d0h.json'))
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    assert digest(args.model) == 'e4cf8c147e1368b35497d772920bc92f98c1ad7853c1033d8a836947f427140e'
    runtimes = {}
    for path in [args.ffmpeg, args.ffprobe, args.svt_ffmpeg]:
        if path:
            runtimes[str(path)] = {'sha256': digest(path), 'version': subprocess.check_output([str(path), '-version'], text=True)}
    (args.output / 'toolchain.json').write_text(json.dumps(runtimes, indent=2) + '\n')
    for path in args.references:
        result = validate(path.resolve(), args)
        print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
