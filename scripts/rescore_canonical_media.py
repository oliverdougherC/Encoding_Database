#!/usr/bin/env python3
"""Re-score retained validation encodes; never change encoding bytes or timing."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from client.ffmpeg import canonical_quality_filter
from scripts.validate_canonical_media import check_media, digest, probe, run

CONTEXT = 'libvmaf-json-distorted-first-yuv420p10le-single-thread'


def rescore(report_path, ffmpeg, ffprobe, model):
    report = json.loads(report_path.read_text())
    reference = Path(report['reference'])
    assert digest(reference) == report['sha256'], 'reference bytes changed'
    out = report_path.parent
    archive = out / 'diagnostic-wrong-alignment'
    archive.mkdir(exist_ok=True)
    (archive / 'INVALID.txt').write_text('DIAGNOSTIC INVALID: old quality metrics compare rounded MKV timestamps with exact MP4 timestamps without canonical cadence/pixel-format normalization. Never cite these as quality evidence. Encoding bytes and timings are unaffected.\n')
    if not (archive / report_path.name).exists():
        shutil.copy2(report_path, archive / report_path.name)
    ref_probe = probe(reference, ffprobe, out / 'rescore-reference-probe.log')
    count = check_media(ref_probe)
    cadence = ref_probe['streams'][0]['avg_frame_rate']
    runtime = {'path': str(ffmpeg), 'sha256': digest(ffmpeg), 'modelSha256': digest(model)}
    assert runtime['modelSha256'] == 'e4cf8c147e1368b35497d772920bc92f98c1ad7853c1033d8a836947f427140e'
    for row in report['encodes']:
        artifact = Path(row['file'])
        assert digest(artifact) == row['sha256'] and artifact.stat().st_size == row['bytes'], 'encoded bytes changed'
        label = artifact.stem
        if row.get('qualityAnalysisContext') == CONTEXT and row.get('qualityRuntime') == runtime:
            continue
        for suffix in ['vmaf.json', 'vmaf.log', 'xpsnr.log']:
            old = out / f'{label}.{suffix}'
            if old.exists() and not (archive / old.name).exists():
                shutil.copy2(old, archive / old.name)
        observed = probe(artifact, ffprobe, out / f'{label}.rescore-probe.log')
        check_media(observed, count, observed['streams'][0]['codec_name'])
        metric_path = (out / f'{label}.vmaf.corrected.json').resolve()
        metrics = [f"libvmaf=model='path={model.resolve()}':n_threads=1:log_fmt=json:log_path={metric_path}", 'xpsnr', 'ssim', 'psnr']
        graphs = [canonical_quality_filter(cadence, metric).replace('[distorted]', f'[distorted{i}]').replace('[reference]', f'[reference{i}]') + f'[out{i}]' for i, metric in enumerate(metrics)]
        command = [ffmpeg, '-nostdin', '-hide_banner', '-i', artifact, '-i', reference,
                   '-filter_complex', ';'.join(graphs)]
        for i in range(4):
            command += ['-map', f'[out{i}]']
        command += ['-f', 'null', '-']
        run(command, out / f'{label}.corrected-metrics.log')
        vmaf = json.loads(metric_path.read_text())
        assert len(vmaf['frames']) == count, 'VMAF exact frame coverage failed'
        row['vmafMean'] = vmaf['pooled_metrics']['vmaf']['mean']
        row['qualityAnalysisContext'] = CONTEXT
        row['qualityRuntime'] = runtime
        row['qualityFrameCount'] = count
        row['qualityMetricsLog'] = str(out / f'{label}.corrected-metrics.log')
        os.replace(metric_path, out / f'{label}.vmaf.json')
        for suffix in ['vmaf.log', 'xpsnr.log']:
            (out / f'{label}.{suffix}').unlink(missing_ok=True)
        staged = report_path.with_suffix('.rescore.tmp')
        staged.write_text(json.dumps(report, indent=2) + '\n')
        os.replace(staged, report_path)
        print(f'{artifact}: VMAF {row["vmafMean"]}', flush=True)
    # Keep committed visual-review decisions and immutable encoding evidence intact.
    committed = ROOT / 'docs/canonical-suite/evidence' / f'{out.name}-results.json'
    if report_path.name == 'results-extra.json':
        committed = ROOT / 'docs/canonical-suite/evidence' / f'{out.name}-additional-software.json'
    if committed.exists():
        document = json.loads(committed.read_text())
        by_hash = {row['sha256']: row for row in report['encodes']}
        for row in document['encodes']:
            corrected = by_hash.get(row['sha256'])
            if corrected:
                for key in ['vmafMean', 'qualityAnalysisContext', 'qualityRuntime', 'qualityFrameCount', 'qualityMetricsLog']:
                    row[key] = corrected[key]
        committed.write_text(json.dumps(document, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports', nargs='+', type=Path)
    parser.add_argument('--ffmpeg', type=Path, default=ROOT / 'client/bin/mac/ffmpeg')
    parser.add_argument('--ffprobe', type=Path, default=ROOT / 'client/bin/mac/ffprobe')
    parser.add_argument('--model', type=Path, default=ROOT / 'client/resources/vmaf/vmaf_v1.0.16_3d0h.json')
    args = parser.parse_args()
    for report_path in args.reports:
        rescore(report_path, args.ffmpeg, args.ffprobe, args.model)
