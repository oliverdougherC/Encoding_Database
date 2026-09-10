#!/usr/bin/env python3
"""Execute the pinned VMAF model on actual media before native packaging."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def sha256(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def validate_metrics(payload, expected_frames):
    frames = payload.get('frames', [])
    if len(frames) != expected_frames or expected_frames < 1:
        raise ValueError('VMAF frame distribution is incomplete')
    for index, frame in enumerate(frames):
        if frame.get('frameNum') != index:
            raise ValueError('VMAF frame numbering is incomplete')
        score = frame.get('metrics', {}).get('vmaf')
        if not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 100:
            raise ValueError('VMAF frame score is missing, nonfinite, or outside [0,100]')
    mean = payload.get('pooled_metrics', {}).get('vmaf', {}).get('mean')
    if not isinstance(mean, (int, float)) or not math.isfinite(mean) or not 0 <= mean <= 100:
        raise ValueError('VMAF pooled mean is invalid')
    return mean


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg', default=os.environ.get('ENCODINGDB_FFMPEG_PATH', 'ffmpeg'))
    parser.add_argument('--ffprobe', default=os.environ.get('ENCODINGDB_FFPROBE_PATH', 'ffprobe'))
    parser.add_argument('--reference', type=Path, help='Explicit real reference for diagnostic execution; CI uses frozen quick clip')
    parser.add_argument('--output-dir', type=Path, default=ROOT / '.test-reports/runtime-model')
    args = parser.parse_args()
    reference = args.reference
    if reference is None:
        suite = ROOT / 'client/resources/test_suite_v1'
        if not json.loads((suite / 'finalization-status.json').read_text()).get('isFrozen'):
            raise ValueError('Runtime candidate validation requires the frozen canonical suite')
        manifest = json.loads((suite / 'manifest.json').read_text())
        clip = next(c for c in manifest['clips'] if c['id'] == manifest['defaultQuickClipId'])
        reference = suite / 'canonical' / clip['fileName']
        if sha256(reference) != clip['sha256']:
            raise ValueError('Quick reference differs from frozen manifest')
    reference = reference.resolve(strict=True)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    model_manifest = json.loads((ROOT / 'client/resources/vmaf/manifest.json').read_text())
    model = ROOT / 'client/resources/vmaf' / model_manifest['filename']
    if sha256(model) != model_manifest['sha256']:
        raise ValueError('Pinned model checksum mismatch')
    shutil.copyfile(model, output / 'model.json')
    commands = []
    def run(command, name):
        commands.append(command)
        result = subprocess.run(command, cwd=output, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        (output / (name + '.stdout.log')).write_text(result.stdout)
        (output / (name + '.stderr.log')).write_text(result.stderr)
        (output / 'commands.json').write_text(json.dumps(commands, indent=2))
        result.check_returncode()
        return result.stdout
    ffmpeg = str(Path(args.ffmpeg).resolve()) if Path(args.ffmpeg).exists() else args.ffmpeg
    ffprobe = str(Path(args.ffprobe).resolve()) if Path(args.ffprobe).exists() else args.ffprobe
    probe = json.loads(run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-count_frames', '-show_entries', 'stream=nb_read_frames', '-of', 'json', str(reference)], 'reference-probe'))
    expected = int(probe['streams'][0]['nb_read_frames'])
    run([ffmpeg, '-hide_banner', '-y', '-i', str(reference), '-map', '0:v:0', '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '24', 'encoded.mp4'], 'encode')
    run([ffmpeg, '-hide_banner', '-i', 'encoded.mp4', '-i', str(reference), '-lavfi', '[0:v]setpts=PTS-STARTPTS[d];[1:v]setpts=PTS-STARTPTS[r];[d][r]libvmaf=model=path=model.json:n_threads=2:log_fmt=json:log_path=metrics.json', '-f', 'null', '-'], 'model')
    metrics = json.loads((output / 'metrics.json').read_text())
    mean = validate_metrics(metrics, expected)
    report = {'status': 'passed', 'referenceSha256': sha256(reference), 'modelSha256': model_manifest['sha256'], 'encodedSha256': sha256(output / 'encoded.mp4'), 'frameCount': expected, 'vmafMean': mean, 'frozenQuickReference': args.reference is None}
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
