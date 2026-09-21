"""Reproduce the x264 receipt audit; original journal/artifact files stay unchanged."""
import collections
import json
import math
from pathlib import Path

base=Path(__file__).resolve().parent
raw=json.loads((base/'raw-journals-x264-crf23.json').read_text())
files={x['name']:x for x in raw['files']}
records=[x['data'] for name,x in files.items() if name.startswith('attempt-')]
receipt=json.loads((base/'x264-crf23-receipt.json').read_text())
for record in receipt['evidence']['attempts']:
    name=record['record'].replace('\\','/').rsplit('/',1)[1]
    assert files[name]['sha256']==record['recordSha256']
groups=collections.defaultdict(list)
for record in records:
    info=record['metadata']['info']
    clip=record['metadata']['suiteClip']['clip_id']
    expected=192 if clip.startswith('animation-') else 240
    timing=record['timing']
    assert info['artifactProbe']['sourceFrameCount']==expected==timing['encoded_frame_count']
    assert info['artifactProbe']['decodable'] and info['encodeTimerBoundary']=='ffmpeg-process-v1'
    assert math.isclose(timing['elapsed_s'],(timing['end_monotonic_ns']-timing['start_monotonic_ns'])/1e9,abs_tol=1e-9)
    recipe=json.loads(info['effectiveRecipeJson'])
    assert recipe['encoderNameEffective']=='libx264' and recipe['presetEffective']=='fast'
    assert recipe['rateControlEffective']['qualityValue']==23
    if record['schedule']['phase']=='measured':
        assert {'cpu_psutil_thread_window_v1','cpu_psutil_blocking_window_v1'} & set(record['environmentSnapshot']['telemetry_sources'].split(','))
    if record['countedForStability']:
        groups[clip].append(record)
measured=[x for x in records if x['schedule']['phase']=='measured']
summary={
    'status':'PASSED_PLATFORM_EXECUTION_AND_RETENTION',
    'scope':'Physical Windows x264 acceptance only; not calibration fitting or authoritative quality validation',
    'campaignId':receipt['evidence']['campaignId'],'installationId':receipt['installationId'],
    'exitCode':receipt['exitCode'],'wallSeconds':receipt['wallSeconds'],'attempts':len(records),
    'warmups':len(records)-len(measured),'measured':len(measured),
    'validityCounts':dict(collections.Counter(x['overallValidity']['state'] for x in records)),
    'artifactsHashVerifiedByOperator':len(records),
    'sourceAndArtifactFramesVerified':sum(x['timing']['encoded_frame_count'] for x in records),
    'measuredCpuBackgroundRangePct':[min(x['environmentSnapshot']['background_cpu_pct'] for x in measured),max(x['environmentSnapshot']['background_cpu_pct'] for x in measured)],
    'cpuWindowSources':dict(collections.Counter(next(tag for tag in x['environmentSnapshot']['telemetry_sources'].split(',') if tag in {'cpu_psutil_thread_window_v1','cpu_psutil_blocking_window_v1'}) for x in measured)),
    'groups':[],
    'limitations':['Windows GPU performance-counter timeout retained; NVML remained available',
                   'CPU temperature, battery and FFmpeg CPU-time telemetry unavailable; no values fabricated',
                   'Warmups have no pre-measurement environment snapshot',
                   'Unsigned candidate; GUI and authoritative backend quality validation remain separate'],
}
for clip,values in sorted(groups.items()):
    times=[x['timing']['elapsed_s'] for x in values]
    spread=(max(times)-min(times))/(sum(times)/len(times))
    assert len(times)==2 and spread<=.03
    summary['groups'].append({'clipId':clip,'countedAttempts':2,'elapsedSeconds':times,'relativeSpread':spread,'timingStable':True})
assert len(summary['groups'])==7
(base/'x264-crf23-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k!='groups'},indent=2))
