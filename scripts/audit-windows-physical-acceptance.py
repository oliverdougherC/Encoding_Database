#!/usr/bin/env python3
"""Audit retained physical receipts without qualifying them as fitting data."""
import argparse
import collections
import json
import math
from pathlib import Path
import statistics


def require(condition,message):
    if not condition:raise ValueError(message)


def audit(directory,recipe,label):
    receipt=json.loads((directory/(recipe+'-receipt.json')).read_text())
    raw=json.loads((directory/('raw-journals-'+recipe+'-'+label+'.json')).read_text())
    files={x['name']:x for x in raw['files']}
    manifest=files['manifest.json']['data'];config=manifest['protocolConfig']
    require(receipt['exitCode']==0 and not receipt['forcedCleanup'],'Native invocation did not finish cleanly')
    require(receipt['evidence']['completion']['failed']==0 and receipt['evidence']['completion']['skipped']==0,'Campaign contains failed or skipped work')
    require(manifest['physicalSourceId']==receipt['installationId'],'Installation identity differs')
    require(manifest['protocolVersion']=='7.1','Unexpected protocol')
    require(config['stability_threshold_ratio']==0.03 and config['minimum_measured_runs']==2 and config['max_adaptive_repeats']==2,'Reviewed gates changed')
    records=[x['data'] for name,x in files.items() if name.startswith('attempt-')]
    for record in receipt['evidence']['attempts']:
        name=record['record'].replace('\\','/').rsplit('/',1)[1]
        require(files[name]['sha256']==record['recordSha256'],'Raw journal export hash differs from operator record')
    expected_encoder='libx264' if recipe=='x264-crf23' else 'h264_nvenc'
    expected_preset='fast' if recipe=='x264-crf23' else 'p4'
    groups=collections.defaultdict(list)
    for record in records:
        info=record['metadata']['info'];clip=record['metadata']['suiteClip']['clip_id']
        expected_frames=192 if clip.startswith('animation-') else 240
        probe=record['probe'];timing=record['timing']
        require(probe['width']==1920 and probe['height']==1080 and probe['frame_count']==expected_frames,'Incomplete or wrong-resolution media')
        require(probe['avg_frame_rate']==24 and probe['decodable'] and not probe['truncated'],'Invalid native media')
        require(probe['color_primaries']==probe['color_space']==probe['color_transfer']=='bt709','Unexpected color identity')
        require(info['encodeTimerBoundary']=='ffmpeg-process-v1','Timer boundary differs')
        require(timing['encoded_frame_count']==timing['source_frame_count']==expected_frames,'Frame coverage differs')
        require(math.isclose(timing['elapsed_s'],(timing['end_monotonic_ns']-timing['start_monotonic_ns'])/1e9,abs_tol=1e-9),'Timer arithmetic differs')
        effective=json.loads(info['effectiveRecipeJson'])
        require(effective['encoderNameEffective']==expected_encoder and effective['presetEffective']==expected_preset,'Effective recipe differs')
        rc=effective['rateControlEffective']
        if recipe=='x264-crf23':require(rc['mode']=='crf' and rc['qualityValue']==23,'Expected native CRF23')
        elif recipe=='nvenc-cq24':require(rc['mode']=='cq' and rc['qualityValue']==24,'Expected native CQ24')
        else:require(rc['mode']=='vbr' and rc['targetBitrateKbps']==6000,'Expected native VBR6000')
        if expected_encoder=='h264_nvenc':
            argv=info['executedCommand']
            require('-gpu' in argv and argv[argv.index('-gpu')+1]=='0','Executed hardware device differs')
        groups[clip].append(record)
    require(len(groups)==7,'Full-seven coverage missing')
    measured=[x for x in records if x['schedule']['phase']=='measured']
    valid_markers={'cpu_psutil_thread_window_v1','cpu_psutil_blocking_window_v1'}
    cpu_sources=collections.Counter()
    for record in measured:
        snapshot=record['environmentSnapshot'] or {}
        markers=set((snapshot.get('telemetry_sources') or '').split(',')) & valid_markers
        if record['overallValidity']['state']=='valid':
            require(markers and isinstance(snapshot.get('background_cpu_pct'),(int,float)) and math.isfinite(snapshot['background_cpu_pct']),'Valid observation lacks trustworthy CPU provenance')
        cpu_sources.update(markers or {'unknown'})
    summaries=[]
    for clip,values in sorted(groups.items()):
        require(sum(x['schedule']['phase']=='warmup' for x in values)==1,'Expected one retained warmup')
        counted=[x for x in values if x['countedForStability']]
        times=[x['timing']['elapsed_s'] for x in counted]
        spread=(max(times)-min(times))/statistics.fmean(times) if times else None
        summaries.append({'clipId':clip,'attempts':len(values),'countedAttempts':len(times),'elapsedSeconds':times,'relativeSpread':spread,'timingStable':len(times)>=2 and spread<=0.03})
        submissions=[x['data']['runCreate'] for name,x in files.items() if name.startswith('submission-') and x['data']['runCreate']['workloadId']==clip]
        for submission in submissions:
            group=submission['measurementGroup']
            expected_group=receipt['evidence']['campaignId']+':'+values[0]['schedule']['recipe_id']
            require(group['campaignId']==receipt['evidence']['campaignId'] and group['repetitionGroupId']==submission['repetitionGroupId']==expected_group,'Measurement-group identity differs')
            require(group['completed'] is True and len(group['countedAttempts'])==len(counted),'Final measurement-group membership differs')
            expected=sorted((x['schedule']['repetition_index'],x['timing']['elapsed_s']*1000) for x in counted)
            observed=sorted((x['repetitionIndex'],x['encodeWallTimeMs']) for x in group['countedAttempts'])
            require(all(e[0]==o[0] and math.isclose(e[1],o[1],abs_tol=1e-6) for e,o in zip(expected,observed)),'Measurement-group timing differs')
    selected=manifest['selectedDevices'][expected_encoder]
    if expected_encoder=='h264_nvenc':
        require(selected['deviceId']=='nvenc:0' and selected['selection']=='ffmpeg:-gpu=0' and selected['model']=='NVIDIA GeForce RTX 5090' and selected['driverVersion']=='616.92','Selected NVENC device identity differs')
    return {'status':'PASSED_PLATFORM_EXECUTION_AND_RETENTION','scope':'Physical Windows acceptance only; no fitting-data or authoritative-quality claim','recipe':recipe,'campaignId':receipt['evidence']['campaignId'],'installationId':receipt['installationId'],'exitCode':receipt['exitCode'],'wallSeconds':receipt['wallSeconds'],'attempts':len(records),'warmups':len(records)-len(measured),'measured':len(measured),'validityCounts':dict(collections.Counter(x['overallValidity']['state'] for x in records)),'validityReasons':dict(collections.Counter(r['code'] for x in records for r in x['overallValidity']['reasons'])),'sourceAndArtifactFramesVerified':sum(x['timing']['encoded_frame_count'] for x in records),'artifactHashesVerifiedByOperator':len(records),'cpuWindowSources':dict(cpu_sources),'selectedDevice':selected,'stableGroups':sum(x['timingStable'] for x in summaries),'groups':summaries,'telemetryMissing':dict(collections.Counter((x['environmentSnapshot'] or {}).get('telemetry_missing','unknown') for x in measured)),'limitations':['Unsigned physical candidate; hosted-CI binary is distinct','GUI/fault recovery and authoritative backend quality validation are separate','Every observed validity result and unstable group remains retained']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--label',required=True)
    p.add_argument('--recipe',choices=['x264-crf23','nvenc-cq24','nvenc-vbr6000'],required=True)
    a=p.parse_args();summary=audit(a.directory,a.recipe,a.label)
    (a.directory/(a.recipe+'-summary.json')).write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('groups','telemetryMissing')}))


if __name__=='__main__':main()
