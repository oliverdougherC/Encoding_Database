"""Read-only audit of the frozen corrected P910 software experiment."""
import concurrent.futures, collections, datetime, fcntl, hashlib, json, math, pathlib, subprocess, sys
root = pathlib.Path('/mnt/NVME/docker/encodingdb-operations/20260914-validation-holdouts')
lock = (root / 'host-state/measurement.lock').open('a+b')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
def sha(path):
    with pathlib.Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
plan_path = root / 'timing-evidence/corrected-cpu-software-execution-v1.json'
plan = json.loads(plan_path.read_text())
claimed = plan.pop('planHash')
assert claimed == '7c488c7d1b5cd95d38f3b2c41815970af746be41ff86feb17ae1a80a96ce4730'
assert sha(root / 'source/encodingdb-corrected-software-f3ef468.tar.gz') == plan['sourceArchiveSha256']
assert hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest() == claimed
assert sha(root / 'source/software-f3ef468/scripts/run-validation-campaign.py') == plan['runnerSha256']
assert sha(root / 'source/run-corrected-validation-phase.py') == plan['operatorDriverSha256']
# Each retained path gets its own fresh decode, including identical-byte files.
executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
def probe(ffprobe, artifact):
    command = [ffprobe, '-v', 'error', '-threads', '1', '-select_streams', 'v:0', '-count_frames', '-show_entries', 'stream=nb_read_frames,width,height,avg_frame_rate,duration', '-of', 'json', str(artifact)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=180, check=True)
    assert not result.stderr.strip(), result.stderr
    stream, = json.loads(result.stdout)['streams']
    return stream
probes = {}
for cell in plan['cells']:
    for receipt_path in pathlib.Path(cell['outputPath']).rglob('validation-campaign.json'):
        receipt = json.loads(receipt_path.read_text())
        for group in receipt['campaign']['recipeResults']:
            for run in group['runs']:
                artifact = run['metadata']['info']['artifactPath']
                probes[artifact] = executor.submit(probe, receipt['runtimeVerification']['ffprobePath'], artifact)
cells = []; sources = {}; validity = collections.Counter(); phases = collections.Counter()
for cell in plan['cells']:
    if cell['host'] != 'P910' or not cell['executionPhase'].startswith('software'): continue
    report_path = root / 'timing-evidence' / plan['executionRevision'] / (cell['cellId'] + '.json')
    report = json.loads(report_path.read_text())
    assert report['cell'] == cell and report['planHash'] == claimed
    assert report['sourceCommit'] == plan['sourceCommit'] and report['sourceArchiveSha256'] == plan['sourceArchiveSha256']
    assert report['exitCode'] in (0, 4) and report['cpuProvenanceVerified']
    reference = cell['referencePath']
    if reference not in sources:
        sources[reference] = sha(reference)
    assert sources[reference] == cell['sourceSha256']
    assert len(report['receipts']) == 1
    entry = report['receipts'][0]; receipt_path = pathlib.Path(entry['path'])
    assert sha(receipt_path) == entry['sha256']
    receipt = json.loads(receipt_path.read_text())
    assert receipt['seed'] == cell['seed'] and receipt['runnerSha256'] == plan['runnerSha256']
    assert receipt['sourceRegistrationHash'] == cell['sourceRegistrationHash']
    assert receipt['physicalSourceId'] == 'installation-3569f9d49855c02b183458161105102622a2ef46bfcfb739183eb390ba89a0b4'
    assert receipt['protocolConfig']['stability_threshold_ratio'] == 0.03
    assert receipt['protocolConfig']['minimum_measured_runs'] == 2 and receipt['protocolConfig']['max_adaptive_repeats'] == 2
    group, = receipt['campaign']['recipeResults']; attempts = []
    for run in group['runs']:
        info = run['metadata']['info']; artifact = pathlib.Path(info['artifactPath'])
        assert sha(artifact) == info['artifactSha256']
        stream = probes[str(artifact)].result()
        assert int(stream['nb_read_frames']) == 720 and stream['width'] == 1920 and stream['height'] == 1080 and stream['avg_frame_rate'] == '24/1'
        timing = run['timing']; elapsed = (timing['end_monotonic_ns'] - timing['start_monotonic_ns']) / 1e9
        assert math.isclose(elapsed, timing['elapsed_s'], rel_tol=1e-12)
        assert timing['encoded_frame_count'] == timing['source_frame_count'] == 720 and info['encodeTimerBoundary'] == 'ffmpeg-process-v1'
        assert run['probe']['frame_count'] == 720 and run['probe']['decodable'] and not run['probe']['truncated']
        snapshot = run.get('environmentSnapshot')
        if run['countedForStability']:
            assert snapshot and {'cpu_psutil_thread_window_v1', 'cpu_psutil_blocking_window_v1'}.intersection(snapshot['telemetry_sources'].split(','))
            assert math.isfinite(snapshot['background_cpu_pct']) and 0 <= snapshot['background_cpu_pct'] <= 100
        phase = run['schedule']['phase']; phases[phase] += 1; validity[run['overallValidity']['state']] += 1
        attempts.append({'phase': phase, 'repetitionIndex': run['schedule']['repetition_index'], 'countedForStability': run['countedForStability'], 'timing': timing, 'environmentSnapshot': snapshot, 'overallValidity': run['overallValidity'], 'artifactPath': str(artifact), 'artifactSha256': info['artifactSha256'], 'byteSize': artifact.stat().st_size, 'freshFrameProbe': stream})
    cells.append({'cellId': cell['cellId'], 'seed': cell['seed'], 'campaignId': receipt['campaign']['campaignId'], 'physicalSourceId': receipt['physicalSourceId'], 'sourceRegistrationHash': receipt['sourceRegistrationHash'], 'receipt': entry, 'operatorReportSha256': sha(report_path), 'exitCode': report['exitCode'], 'startedAt': report['startedAt'], 'completedAt': report['completedAt'], 'stability': group['stability'], 'attempts': attempts})
    print(f"Audited {len(cells)}/42: {cell['cellId']}", file=sys.stderr, flush=True)
assert len(cells) == 42
summary = {'status': 'COMPLETE_CORRECTED_SOFTWARE_TIMING_AUDIT', 'inspectedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'sourceCommit': plan['sourceCommit'], 'sourceArchiveSha256': plan['sourceArchiveSha256'], 'planHash': claimed, 'auditProbeConcurrency': 4, 'physicalSources': 1, 'cellCount': len(cells), 'stableCells': sum(c['stability']['stable'] for c in cells), 'unstableCells': sum(not c['stability']['stable'] for c in cells), 'phaseCounts': dict(phases), 'validityCounts': dict(validity), 'referenceSha256': sources, 'cells': cells, 'limitations': ['Historical ffmpegCpuUtilAvg/Max are observed as zero in all 136 attempts because the process sampler recreated its baseline objects. These fields are not reliable CPU-utilization evidence; no values have been backfilled.', 'Timing and byte/frame coverage only; no authoritative VMAF/XPSNR analysis, ranking, import, or human review performed by this audit.', 'Previous 17 observations from the affected sampler revision remain exploratory and excluded.', 'Hardware extension and canonical calibration matrix are separate, unexecuted phases.']}
executor.shutdown(wait=True)
print(json.dumps(summary, indent=2))
