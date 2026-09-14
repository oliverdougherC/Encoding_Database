"""Metadata-only preservation; never open an encoded artifact or source-media file."""
import collections
import hashlib
import json
import math
import pathlib
import shutil
import statistics
import sys

root = pathlib.Path(sys.argv[1])
out = pathlib.Path(__file__).parent
source = root / '.build/native-seven-mac'
inventory = []
def read(path):
    return json.loads(path.read_text())
def preserve(path, relative):
    data = path.read_bytes()  # Call sites are explicitly metadata/log files only.
    target = out / 'evidence' / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    inventory.append({'source': str(path.relative_to(root)), 'copy': str(target.relative_to(out)),
                      'byteSize': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    return hashlib.sha256(data).hexdigest()
receipt = read(source/'receipt.json')
preserve(source/'receipt.json', 'receipt.json')
preserve(source/'run.py', 'original-run.py')
frozen = read(root/'client/resources/test_suite_v1/manifest.json')
preserve(root/'client/resources/test_suite_v1/manifest.json', 'frozen-suite-manifest.json')
clips = {clip['id']:clip for clip in frozen['clips']}
report = {'status':'EXPLORATORY_INELIGIBLE_FOR_FINAL_CALIBRATION',
          'sourceCommit':'65a07d843c26f331c77270188ae9e3732df13117',
          'binaryHashVerification':'Recorded execution receipt only; binary bytes not re-read during this audit.',
          'artifactVerification':'Stored probe/hash metadata plus current file presence/size; no media hashing or probing.',
          'executableSha256Recorded':receipt['executableSha256'], 'cases':[]}
for case in receipt['cases']:
    name = case['name']; directory = source/name
    campaign = directory/'queue/campaigns'/case['campaigns'][0]
    manifest = read(campaign/'manifest.json')
    runtime = read(directory/'embedded-runtime.json')
    protocol_file = directory/'queue/protocol-attempts'/f'{campaign.name}.json'
    protocol = read(protocol_file)
    for path, dest in [(directory/'client.log',f'{name}/client.log.txt'),
                       (directory/'embedded-runtime.json',f'{name}/embedded-runtime.json'),
                       (campaign/'manifest.json',f'{name}/manifest.json'),
                       (campaign/'campaign-complete.json',f'{name}/campaign-complete.json'),
                       (protocol_file,f'{name}/protocol-attempts.json')]:
        preserve(path,dest)
    records = sorted((read(p) for p in campaign.glob('attempt-*.json')), key=lambda v:v['schedule']['execution_order'])
    # Protocol's unmodified runs retain the full attempt objects; compare them
    # against the separate journal files before avoiding a duplicate copy.
    protocol_records = sorted([run for group in protocol['recipeResults'] for run in group['runs']],
                              key=lambda v:v['schedule']['execution_order'])
    assert protocol_records == records
    rows = []
    for record in records:
        info = record['metadata']['info']; timing = record['timing']; probe = record['probe']
        clip_id = record['metadata']['suiteClip']['clip_id']; clip = clips[clip_id]
        artifact = pathlib.Path(info['artifactPath'])
        process_path = pathlib.Path(str(artifact)+'.process.json')
        process = read(process_path)
        snapshot = record['environmentSnapshot']
        assert record['metadata']['inputHash'] == clip['sha256']
        assert timing['source_frame_count'] == timing['encoded_frame_count'] == clip['media']['frameCount']
        assert probe['frame_count'] == clip['media']['frameCount'] and probe['decodable'] is True
        assert info['encodeTimerBoundary'] == 'ffmpeg-process-v1'
        assert math.isclose(timing['elapsed_s'], (timing['end_monotonic_ns']-timing['start_monotonic_ns'])/1e9, abs_tol=1e-12)
        assert process['artifactSha256'] == info['artifactSha256']
        assert process['command'] == info['executedCommand']
        assert process['returncode'] == 0
        assert artifact.is_file() and artifact.stat().st_size == info['fileSizeBytes'] == probe['size_bytes']
        actual_runtime = process['processRuntime']
        rows.append({'executionOrder':record['schedule']['execution_order'], 'phase':record['schedule']['phase'],
                     'repetitionIndex':record['schedule']['repetition_index'], 'clipId':clip_id,
                     'countedForStabilityOriginal':record['countedForStability'],
                     'overallValidityOriginal':record['overallValidity'], 'environmentSnapshotOriginal':snapshot,
                     'sourceSha256Recorded':clip['sha256'], 'sourceFramesRecorded':timing['source_frame_count'],
                     'artifactFile':artifact.name, 'artifactSha256Recorded':info['artifactSha256'],
                     'artifactByteSize':info['fileSizeBytes'], 'artifactExistsAndSizeMatches':True,
                     'fullProbeRecorded':probe, 'timingOriginal':timing,
                     'executedCommandOriginal':info['executedCommand'],
                     'processRuntimeRecorded':{k:v for k,v in actual_runtime.items() if k != 'runtimeDependencies'},
                     'processDependencyRecordsMatchManifest':actual_runtime.get('runtimeDependencies') == manifest['runtime']['runtimeDependencies']})
    groups=[]
    for group in protocol['recipeResults']:
        counted=[r for r in group['runs'] if r['countedForStability']]
        elapsed=[r['timing']['elapsed_s'] for r in counted]
        spread=(max(elapsed)-min(elapsed))/statistics.mean(elapsed)
        assert math.isclose(spread,group['stability']['elapsed_relative_spread'],abs_tol=1e-12)
        assert group['stability']['stable'] == (spread <= manifest['protocolConfig']['stability_threshold_ratio'])
        groups.append({k:v for k,v in group.items() if k!='runs'})
    submissions=[read(p) for p in campaign.glob('submission-*.json')]
    submission_rows=[]
    for sub in submissions:
        run=sub['runCreate']; matching=[r for r in records if r['metadata']['info']['artifactPath']==sub['artifactPath']]
        assert len(matching)==1
        record=matching[0]
        assert sub['artifactSha256']==record['metadata']['info']['artifactSha256']
        assert math.isclose(run['encodeWallTimeMs'],record['timing']['elapsed_s']*1000,abs_tol=1e-9)
        assert run['preRunEnvironmentCheck']['snapshot']==record['environmentSnapshot']
        submission_rows.append({'artifactFile':pathlib.Path(sub['artifactPath']).name,
            'artifactSha256':sub['artifactSha256'], 'encodeWallTimeMs':run['encodeWallTimeMs'],
            'measurementGroupOriginal':run.get('measurementGroup'), 'payloadHash':run.get('payloadHash')})
    log_hash=hashlib.sha256((directory/'client.log').read_bytes()).hexdigest()
    assert log_hash==case['logSha256']
    data={'name':name,'campaignId':campaign.name,'exitCodeRecorded':case['exitCode'], 'seed':manifest['seed'],
          'counts':{'attempts':len(records),'warmup':sum(r['schedule']['phase']=='warmup' for r in records),
                    'measured':sum(r['schedule']['phase']=='measured' for r in records),
                    'countedOriginal':sum(r['countedForStability'] for r in records),
                    'validityOriginal':dict(collections.Counter(r['overallValidity']['state'] for r in records)),
                    'structuralValidityOriginal':dict(collections.Counter(r['structuralValidity']['state'] for r in records)),
                    'submissionFilesLocallyRetained':len(submissions),
                    'correctedCpuMarkerSnapshots':sum(any(m in (r['environmentSnapshot'] or {}).get('telemetry_sources','') for m in ['cpu_psutil_thread_window_v1','cpu_psutil_blocking_window_v1']) for r in records)},
          'campaignCompleteOriginal':read(campaign/'campaign-complete.json'), 'groupsOriginal':groups,
          'runtime':{'extractionRoot':runtime['extractionRoot'], 'ffmpegPath':runtime['ffmpegPath'],
                     'ffprobePath':runtime['ffprobePath'],'frozen':runtime['frozen'],
                     'runtimeLockFingerprint':runtime['runtimeLockFingerprint'],
                     'ffmpeg':runtime['identity']['ffmpeg'],'ffprobe':runtime['identity']['ffprobe'],
                     'dependencyCount':len(runtime['identity']['runtimeDependencies']),
                     'dependencyRecordsMatchManifest':runtime['identity']['runtimeDependencies']==manifest['runtime']['runtimeDependencies']},
          'logHashMatchesReceipt':True,'attempts':rows,'locallyRetainedSubmissions':submission_rows}
    report['cases'].append(data)
(out/'audit.json').write_text(json.dumps(report,indent=2)+'\n')
(out/'evidence-inventory.json').write_text(json.dumps(inventory,indent=2)+'\n')
print(json.dumps({'cases':[{k:v for k,v in c.items() if k in ('name','counts','runtime')} for c in report['cases']],
                  'preservedMetadataBytes':sum(i['byteSize'] for i in inventory)},indent=2))
