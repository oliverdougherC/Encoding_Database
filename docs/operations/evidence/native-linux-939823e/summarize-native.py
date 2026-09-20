"""Read final native journals; preserve timing stability separately from validity."""
from collections import Counter
import datetime
import json
import math
from pathlib import Path

ROOT = Path('/mnt/NVME/docker/encodingdb-operations/20260920-native-939823e-untraced')
EXECUTION = json.loads((ROOT / 'execution.json').read_text())
CLIPS = {'athletic-action-1080p24-final', 'natural-detail-1080p24-final',
         'film-grain-1080p24-final', 'dark-gradients-1080p24-final',
         'animation-1080p24-final', 'screen-text-1080p24-final', 'talking-head-1080p24-final'}


def has_pair(command, key, value):
    return any(command[i:i + 2] == [key, value] for i in range(len(command) - 1))


output = {'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'sourceCommit': EXECUTION['sourceCommit'], 'packageSha256': EXECUTION['packageSha256'],
          'physicalSourceId': EXECUTION['physicalSourceId'], 'instrumented': False,
          'ordinaryCampaigns': [], 'analysisPerformed': False, 'uploadsAttempted': False}
for entry in EXECUTION['campaigns']:
    queue = Path(entry['queue'])
    records = [json.loads(p.read_text()) for p in sorted(queue.glob('campaigns/*/attempt-*.json'))]
    measured = [r for r in records if r['schedule']['phase'] == 'measured']
    evidence_paths = sorted(queue.glob('protocol-attempts/*.json'))
    evidence = json.loads(evidence_paths[0].read_text()) if len(evidence_paths) == 1 else {}
    runtime_path = ROOT / (entry['name'] + '-embedded-runtime.json')
    runtime = json.loads(runtime_path.read_text()) if runtime_path.exists() else {}
    manifests = [json.loads(p.read_text()) for p in queue.glob('campaigns/*/manifest.json')]
    groups = []
    for group in evidence.get('recipeResults', []):
        groups.append({key: group[key] for key in ['recipeId', 'stability', 'measuredRunsRequired',
                                                  'measuredRunsCompleted', 'measuredRunsCounted']})
    commands = [(r.get('metadata') or {}).get('info', {}).get('executedCommand', []) for r in records]
    seen_clips = {r['schedule']['recipe_id'].split('|')[0] for r in records}
    valid_frames = []
    for record in records:
        frames = 192 if record['schedule']['recipe_id'].startswith('animation-') else 240
        timing, probe = record.get('timing') or {}, record.get('probe') or {}
        valid_frames.append(timing.get('source_frame_count') == frames
                            and timing.get('encoded_frame_count') == frames
                            and probe.get('frame_count') == frames and probe.get('decodable') is True)
    snapshots = [r.get('environmentSnapshot') or {} for r in measured]
    known_cpu = [r for r in measured if isinstance((r.get('timing') or {}).get('ffmpeg_cpu_time_s'), (int, float))
                 and math.isfinite(r['timing']['ffmpeg_cpu_time_s'])]
    process_cpu = [r['metadata']['info'].get('ffmpegCpuUtilAvg') for r in measured]
    finite_process_cpu = [v for v in process_cpu if isinstance(v, (int, float)) and math.isfinite(v)]
    checks = {'allSevenClipsObserved': seen_clips == CLIPS,
              'allRetainedAttemptsHaveFullFrameCoverage': bool(records) and all(valid_frames),
              'allEncodeHelpersMatchEmbeddedReceipt': bool(commands) and all(c and c[0] == runtime.get('ffmpegPath') for c in commands),
              'freshCpuSourceOnEveryMeasuredSnapshot': bool(snapshots) and all(
                  isinstance(s.get('background_cpu_pct'), (int, float)) and math.isfinite(s['background_cpu_pct'])
                  and any(marker in (s.get('telemetry_sources') or '') for marker in
                      ['cpu_psutil_thread_window_v1', 'cpu_psutil_blocking_window_v1']) for s in snapshots)}
    if entry['name'] == 'nvenc':
        checks['nativeDevice0Vbr4000OnEveryCommand'] = bool(commands) and all(
            has_pair(c, '-gpu', '0') and has_pair(c, '-rc', 'vbr') and has_pair(c, '-b:v', '4000k')
            and has_pair(c, '-preset', 'p4') and has_pair(c, '-c:v', 'h264_nvenc') for c in commands)
    else:
        checks['softwareMediumCrf24OnEveryCommand'] = bool(commands) and all(
            has_pair(c, '-preset', 'medium') and has_pair(c, '-crf', '24')
            and has_pair(c, '-c:v', 'libx264') for c in commands)
    output['ordinaryCampaigns'].append({
        'name': entry['name'], 'campaignId': evidence.get('campaignId'),
        'execution': entry, 'checks': checks, 'attemptCount': len(records),
        'warmupCount': sum(r['schedule']['phase'] == 'warmup' for r in records),
        'measuredCount': len(measured), 'countedMeasuredCount': sum(bool(r.get('countedForStability')) for r in measured),
        'measuredValidityCounts': dict(Counter(r['overallValidity']['state'] for r in measured)),
        'measuredReasons': dict(Counter(reason for r in measured for reason in r['overallValidity'].get('reasons', []))),
        'knownMeasuredCpuSecondsCount': len(known_cpu),
        'positiveMeasuredCpuSecondsCount': sum(r['timing']['ffmpeg_cpu_time_s'] > 0 for r in known_cpu),
        'finiteMeasuredProcessCpuUtilizationCount': len(finite_process_cpu),
        'positiveMeasuredProcessCpuUtilizationCount': sum(v > 0 for v in finite_process_cpu),
        'freshProcessCpuSourceCount': sum('ffmpeg_psutil_process_window_v1' in
                                         (r['metadata']['info'].get('telemetrySources') or '') for r in measured),
        'processCpuUtilizationPercentRange': [min(finite_process_cpu), max(finite_process_cpu)] if finite_process_cpu else None,
        'groups': groups, 'stableGroupCount': sum(g['stability']['stable'] for g in groups),
        'runtime': runtime,
        'manifestProvenance': [{key: m.get(key) for key in ['seed', 'physicalSourceId', 'hardware', 'selectedDevices', 'runtime']} for m in manifests],
        'observedGpuSelections': sorted({s.get('selected_accelerator') or 'unknown' for s in snapshots}),
        'gpuTrustworthyMeasuredCount': sum(s.get('gpu_load_trustworthy') is True and s.get('gpu_sample_count', 0) > 0 for s in snapshots),
    })
print(json.dumps(output, indent=2))
