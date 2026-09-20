"""Post-defect-fix candidate phases: roll the fixed server image, drain analysis,
verify the corrected ordinary contribution path with a fresh narrow campaign,
re-assert exact membership over every prepared payload (Linux, Mac, Windows),
then restore the handback configuration.

Defect under repair (see commit 3e6bb08): validateProbeAgainstRun capped the
maximum keyframe interval at the recipe's OBSERVED MINIMUM interval, rejecting
valid scene-cut software uploads with HTTP 400. Original failures, terminal
tombstones, REJECTED artifacts and all immutable fields stay exactly as
recorded; nothing here re-encodes completed evidence or rewrites history.
"""
import hashlib
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

PLAN = json.loads(Path(__file__).with_name('plan.json').read_text())
ROOT = Path(PLAN['caseRoot'])
CANDIDATE = Path(PLAN['candidateRoot'])
STATE = Path(PLAN['physicalStateRoot'])
COMPOSE = CANDIDATE / 'candidate.compose.json'
PUB = ROOT / 'publication'
FIXED_IMAGE = 'encodingdb-candidate-server:3e6bb08'
FIXED_SOURCE = '3e6bb08'
NODE = '/mnt/NVME/docker/encodingdb-operations/20260920-projection-b3ef24a/bin/node'
CERTS = CANDIDATE / 'nginx/dev-certs'
DIRECT_URL = 'https://127.0.0.1:3094'
RELEASE_ID = 'encodingdb-candidate-730de3c'
SERVER = 'encodingdb-candidate-730de3c-server-1'
DB = 'encodingdb-candidate-730de3c-db-1'
QUEUES = {
    'software': ROOT / '日本語 client trial/software-queue',
    'nvenc': ROOT / '日本語 client trial/nvenc-queue',
    # Post-fix fresh verification queues live under WORK; membership must see
    # their submissions too.
    'verify-animation': ROOT / 'gopfix-verify/verify-animation-queue',
    'verify-athletic': ROOT / 'gopfix-verify/verify-athletic-action-queue',
}
# Sealed client-side evidence copied in for server-side membership: Mac b3
# submission payloads, Mac terminal receipts (409 unstable-group rejections),
# and the seven Windows terminal receipts.
MAC_PAYLOADS = PUB / 'mac-payloads'
MAC_TERMINAL = PUB / 'mac-terminal'
WINDOWS_TERMINAL = PUB / 'windows-terminal'
VERIFY_CLIPS = ['animation-1080p24-final', 'athletic-action-1080p24-final']
# Declared before execution: seed = first 13 hex digits of
# SHA256(sourceCommit + ':gopfix-verify:' + <name> + ':1'), mirroring the
# frozen native-acceptance derivation rule with a distinct phase namespace.
SEED_NAMESPACE = ':gopfix-verify:'
WORK = ROOT / 'gopfix-verify'
RESULTS = PUB / 'gopfix-results.json'


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def seed_for(name):
    text = PLAN['sourceCommit'] + SEED_NAMESPACE + name + ':1'
    return int(hashlib.sha256(text.encode()).hexdigest()[:13], 16)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(CANDIDATE))
sys.path.insert(0, '/mnt/NVME/docker/encodingdb-operations/20260914-native-linux-candidate/'
                   'build-venv/lib/python3.12/site-packages')
sys.path.insert(0, str(CANDIDATE))
import fcntl  # noqa: E402

RELEASE = load('native_release', CANDIDATE / 'scripts/release_manifest_lib.py')
LEDGER = load('native_ledger', CANDIDATE / 'scripts/native-e2e-ledger.py')


def load_results():
    return json.loads(RESULTS.read_text())


def save_results(state):
    temporary = RESULTS.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2) + '\n')
    os.replace(temporary, RESULTS)


def record(state, name, payload):
    state['phases'] = [phase for phase in state['phases'] if phase['name'] != name]
    state['phases'].append({'name': name, 'at': now(), **payload})
    save_results(state)


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def shell(command, *, check=True):
    completed = subprocess.run(command, shell=isinstance(command, str), capture_output=True, text=True)
    if check and completed.returncode != 0:
        raise RuntimeError(f'command failed ({completed.returncode}): {command if isinstance(command, str) else " ".join(command)}\n'
                           f'stdout={completed.stdout[:2000]}\nstderr={completed.stderr[:2000]}')
    return completed


def db(sql):
    inspect = json.loads(shell(['docker', 'inspect', DB]).stdout)[0]
    values = dict(item.split('=', 1) for item in inspect['Config']['Env'] if '=' in item)
    completed = shell(['docker', 'exec', DB, 'psql', '-U', values['POSTGRES_USER'], '-d', values['POSTGRES_DB'], '-tAc', sql], check=True)
    return [line for line in completed.stdout.splitlines() if line != '']


def inspect_summary(name):
    inspect = json.loads(shell(['docker', 'inspect', name]).stdout)[0]
    return {'id': inspect['Id'], 'startedAt': inspect['State']['StartedAt'],
            'image': inspect['Config']['Image'],
            'volumes': sorted(f"{m.get('Name') or m.get('Source')}->{m['Destination']}" for m in inspect['Mounts'])}


def production_baseline():
    return {name: inspect_summary(name) for name in
            ('encodingdb-server-1', 'encodingdb-frontend-1', 'encodingdb-db-1', 'encodingdb-nginx')}


def server_state():
    inspect = json.loads(shell(['docker', 'inspect', SERVER]).stdout)[0]
    return {'image': inspect['Config']['Image'],
            'env': {key: value for key, value in
                    (item.split('=', 1) for item in inspect['Config']['Env'] if '=' in item)
                    if key.startswith(('ARTIFACT_', 'V7_'))}}


def client_env():
    env = dict(os.environ)
    for key in list(env):
        if key.lower().endswith('_proxy') or key in ('FFMPEG_EXE', 'FFPROBE_EXE', 'ENCODINGDB_RUNTIME_LOCK_PATH',
                'ENCODINGDB_FFMPEG_PATH', 'ENCODINGDB_FFPROBE_PATH', 'ENCODINGDB_RUNTIME_BUNDLE_DIR',
                'ENCODINGDB_SUITE_PACK_PATH', 'PYTHONPATH', 'PYTHONHOME', 'LD_PRELOAD', 'LD_LIBRARY_PATH'):
            env.pop(key, None)
    env.update({'ENCODINGDB_STATE_DIR': str(STATE),
                'REQUESTS_CA_BUNDLE': str(ROOT / 'candidate-plus-public-roots.pem'),
                'CURL_CA_BUNDLE': str(ROOT / 'candidate-plus-public-roots.pem'),
                'ENCODINGDB_DEBUG_TRACEBACK': '1',
                'ENCODINGDB_SUITE_CACHE_DIR': str(WORK / 'clean-suite-cache')})
    return env


def phase_rollout(state):
    snapshot = PUB / 'candidate.compose.pre-gopfix.private.json'
    if not snapshot.is_file():
        snapshot.write_bytes(COMPOSE.read_bytes())
        os.chmod(snapshot, 0o600)
    baseline = production_baseline()
    config = json.loads(snapshot.read_bytes())
    config['services']['server']['image'] = FIXED_IMAGE
    config['services']['server'].setdefault('environment', {})['ARTIFACT_ANALYSIS_CONCURRENCY_MAX'] = '2'
    COMPOSE.write_text(json.dumps(config, indent=2) + '\n')
    volumes = shell(f'cd {shlex.quote(str(CANDIDATE))} && {shlex.quote(NODE)} scripts/verify-deployment-volumes.mjs candidate.compose.json', check=False).stdout.strip()
    shell(f'cd {shlex.quote(str(CANDIDATE))} && docker compose -p {RELEASE_ID} -f candidate.compose.json up -d --no-build --pull never server')
    deadline = time.time() + 180
    health = None
    while time.time() < deadline:
        ready = shell(f'curl --silent --show-error --fail --max-time 5 --cacert {shlex.quote(str(CERTS / "selfsigned.crt"))} {DIRECT_URL}/health/ready', check=False)
        if ready.returncode == 0:
            health = json.loads(ready.stdout)
            break
        time.sleep(3)
    assert health, 'fixed candidate server did not become ready'
    current = server_state()
    assert FIXED_IMAGE in json.dumps(current['image']) or current['image'].startswith('sha256:'), current
    assert current['env']['ARTIFACT_ANALYSIS_CONCURRENCY_MAX'] == '2'
    assert production_baseline() == baseline, 'production containers drifted'
    compat = shell(f'curl --silent --show-error --fail --max-time 10 --cacert {shlex.quote(str(CERTS / "selfsigned.crt"))} {DIRECT_URL}/v7/compatibility', check=True).stdout
    compat = json.loads(compat)
    tree = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=CANDIDATE, capture_output=True, text=True).stdout.strip()
    assert tree.startswith(FIXED_SOURCE), tree
    record(state, 'rollout', {'health': health, 'volumes': volumes, 'server': current,
                               'productionBaseline': baseline, 'compatibility': {
                                   'protocolVersion': compat['protocolVersion'],
                                   'suiteFingerprint': compat['suiteFingerprint'],
                                   'minimumClientVersion': compat['minimumClientVersion']},
                               'candidateSource': tree})
    print(json.dumps({'phase': 'rollout', 'image': current['image'], 'compat': compat['protocolVersion']}, indent=1))


def phase_drain(state):
    deadline = time.time() + 3600
    while True:
        open_states = db("SELECT count(*) FROM \"Artifact\" WHERE \"storageState\" IN ('PENDING','UPLOADED')")[0]
        if int(open_states) == 0:
            break
        if time.time() > deadline:
            raise RuntimeError(f'drain stalled with {open_states} open artifacts: '
                               + json.dumps(db("SELECT \"storageState\", count(*) FROM \"Artifact\" GROUP BY 1")))
        time.sleep(10)
    states = db("SELECT \"storageState\", count(*) FROM \"Artifact\" GROUP BY 1 ORDER BY 1")
    analyses = db('SELECT status, count(*) FROM "QualityAnalysis" GROUP BY 1 ORDER BY 1')
    record(state, 'drain', {'artifactStates': states, 'analyses': analyses})
    print(json.dumps({'phase': 'drain', 'states': states, 'analyses': analyses}, indent=1))


def phase_verify(state):
    WORK.mkdir(parents=True, exist_ok=True)
    binary = WORK / 'encodingdb-client-linux'
    import shutil
    shutil.copy2(PLAN_LINUX_BINARY, binary)
    assert digest(binary) == PLAN['packageSha256'], 'packaged binary digest drifted'
    results = {'packageSha256': PLAN['packageSha256'], 'seeds': {}, 'runs': [],
               'seedRule': 'first 13 hex digits of SHA256(' + PLAN['sourceCommit'] + SEED_NAMESPACE + '<name>:1)'}
    for clip in VERIFY_CLIPS:
        name = 'verify-' + clip.split('-1080p24-final')[0]
        seed = seed_for(name)
        results['seeds'][name] = seed
        queue = WORK / (name + '-queue')
        command = [str(binary), '--cli', '--campaign', 'full', '--v7-suite-clip', clip,
                   '--codec', 'libx264', '--presets', 'fast', '--crf', '24', '--submit',
                   '--max-attempts', '36', '--max-duration-minutes', '45',
                   '--max-storage-mb', '2048', '--queue-dir', str(queue), '--base-url', DIRECT_URL]
        env = client_env()
        env['ENCODINGDB_PROTOCOL_SEED'] = str(seed)
        receipt_path = WORK / (name + '-embedded-runtime.json')
        env['ENCODINGDB_RUNTIME_EVIDENCE_PATH'] = str(receipt_path)
        observed = RELEASE._run_smoke_command(command, env=env, queue_dir=queue,
                stdout_path=WORK / (name + '.stdout.log'), stderr_path=WORK / (name + '.stderr.log'),
                acquisition_seconds=2400, measurement_seconds=900)
        entry = {'clip': clip, 'argv': [str(part) for part in command],
                 'returnCode': observed['returnCode'],
                 'survivingOwnedPids': observed.get('survivingOwnedPids'),
                 'pending': sorted(p.name for p in queue.glob('*.json')) if queue.is_dir() else []}
        receipt = json.loads(receipt_path.read_text())
        source_lock = json.loads((CANDIDATE / 'client/resources/runtime/ffmpeg-lock.json').read_text())['platforms']['linux']
        assert receipt['frozen'] is True and receipt['platform'] == 'linux'
        for key in ['ffmpeg', 'ffprobe']:
            assert receipt['identity'][key]['sha256'] == source_lock[key]['sha256']
        entry['embeddedRuntimeVerified'] = True
        entry['ledger'] = LEDGER.capture(queue)
        assert not entry['pending'], f'{name}: uploads still pending: {entry["pending"]}'
        results['runs'].append(entry)
        record(state, 'verify:progress', results)
    phase_verify_db(state)


def phase_verify_db(state):
    # Server-side observation of the fresh contributions: runs, verified
    # artifacts, and the keyframe probe the fixed validator accepted.
    results = dict(next((p for p in state['phases'] if p['name'] == 'verify:progress'),
                        {'seeds': {}, 'runs': []}))
    if isinstance(results.get('runs'), dict):  # earlier mis-nested record
        results = dict(results['runs'])
    fresh = {}
    for row in db("""SELECT c.\"clipKey\", a.sha256, a.\"storageState\", r.\"repetitionIndex\",
                            coalesce(q.status::text,'-'), coalesce(a.\"stateDetails\" #>> '{observed,keyframeIndexes}','-')
                     FROM \"BenchmarkRun\" r
                     JOIN \"Artifact\" a ON a.\"benchmarkRunId\"=r.id
                     JOIN \"TestClip\" c ON c.id=r.\"testClipId\"
                     LEFT JOIN \"QualityAnalysis\" q ON q.\"benchmarkRunId\"=r.id
                     WHERE r.\"createdAt\" > '2026-09-20 09:55:00'
                     ORDER BY c.\"clipKey\", r.\"repetitionIndex\""""):
        clip, sha, storage, index, analysis, keyframes = row.split('|')
        fresh.setdefault(clip, []).append({'sha256': sha[:12], 'storageState': storage,
                                           'repetitionIndex': int(index), 'analysis': analysis,
                                           'keyframeIndexes': keyframes})
    results['fresh'] = fresh
    for clip, rows in fresh.items():
        for row in rows:
            assert row['storageState'] in ('VERIFIED', 'RETAINED'), row
            assert row['analysis'] in ('COMPLETE', 'SUSPECT'), row
    record(state, 'verify', results)
    print(json.dumps({'phase': 'verify-db', 'runs': [r['returnCode'] for r in results.get('runs', [])],
                      'fresh': fresh}, indent=1))


def load_submissions(queue):
    out = {}
    root = queue / 'campaigns'
    for campaign in sorted(root.glob('campaign-*')):
        for path in sorted((campaign).glob('submission-*.json')):
            payload = json.loads(path.read_text())
            run_create = payload.get('runCreate') or {}
            ph = run_create.get('payloadHash')
            if not ph:
                continue
            entry = out.setdefault(ph, {'sha256': payload.get('artifactSha256'),
                                        'key': (run_create.get('campaignId'), run_create.get('repetitionGroupId'),
                                                run_create.get('repetitionIndex')),
                                        'sources': []})
            assert entry['sha256'] == payload.get('artifactSha256')
            entry['sources'].append(str(path))
    return out


WINDOWS_R3 = {'campaigns': ('campaign-48cfe70dd43b036c', 'campaign-ade93ae84fc38765',
                             'campaign-fb607b76eec675bf'),
               'window': ('2026-09-20 08:49:00', '2026-09-20 08:52:59'),
               'expectedRows': {'campaign-48cfe70dd43b036c': 9, 'campaign-ade93ae84fc38765': 14,
                                'campaign-fb607b76eec675bf': 14}}


def phase_membership(state):
    prepared = {}
    def merge(mapping, origin):
        for ph, entry in mapping.items():
            if ph in prepared:
                assert prepared[ph]['sha256'] == entry['sha256'], f'payload {ph} byte conflict'
                prepared[ph]['sources'].append(origin)
            else:
                prepared[ph] = {**entry, 'sources': [origin]}
    for name, queue in QUEUES.items():
        merge(load_submissions(queue), f'linux:{name}')
    if MAC_PAYLOADS.is_dir():
        for path in sorted(MAC_PAYLOADS.rglob('submission-*.json')):
            payload = json.loads(path.read_text())
            run_create = payload.get('runCreate') or {}
            ph = run_create.get('payloadHash')
            if ph:
                entry = {'sha256': payload.get('artifactSha256'),
                         'key': (run_create.get('campaignId'), run_create.get('repetitionGroupId'),
                                 run_create.get('repetitionIndex')), 'sources': ['mac']}
                if ph in prepared:
                    assert prepared[ph]['sha256'] == entry['sha256']
                    prepared[ph]['sources'].append('mac')
                else:
                    prepared[ph] = entry
    terminal = {}
    for name, queue in QUEUES.items():
        for path in sorted((queue / 'terminal').glob('*.json')):
            entry = json.loads(path.read_text())
            run_create = (entry.get('payload') or {}).get('runCreate') or {}
            if run_create.get('payloadHash'):
                terminal[run_create['payloadHash']] = {'origin': f'linux:{name}', 'lastError': entry.get('lastError')}
    if WINDOWS_TERMINAL.is_dir():
        for path in sorted(WINDOWS_TERMINAL.glob('*.json')):
            entry = json.loads(path.read_text())
            run_create = (entry.get('payload') or {}).get('runCreate') or {}
            if run_create.get('payloadHash'):
                terminal[run_create['payloadHash']] = {'origin': 'windows', 'lastError': entry.get('lastError')}
    if MAC_TERMINAL.is_dir():
        for path in sorted(MAC_TERMINAL.glob('*.json')):
            entry = json.loads(path.read_text())
            run_create = (entry.get('payload') or {}).get('runCreate') or {}
            if run_create.get('payloadHash'):
                terminal[run_create['payloadHash']] = {'origin': 'mac', 'lastError': entry.get('lastError')}
    runs = db("""SELECT r.id, r.\"campaignId\", r.\"payloadHash\",
                        c.id || ':' || a.sha256 || ':' || a.\"byteSize\" || ':' || a.\"storageState\",
                        r.\"sourceFrameCount\", r.\"encodedFrameCount\", r.\"repetitionIndex\"
                 FROM \"BenchmarkRun\" r
                 JOIN \"Artifact\" a ON a.\"benchmarkRunId\"=r.id
                 JOIN \"TestClip\" c ON c.id = r.\"testClipId\"
                 ORDER BY r.\"campaignId\", r.id""")
    ghost_runs, sha_mismatches, frame_mismatches = [], [], []
    # Rows from the three Windows r3 campaigns are attested at receipt level
    # (r3 receipt: exit 0, dueUploadsAfter 0, campaignFilesUnchanged) but not
    # at payload level until the windows lane exports the submission files.
    windows_attested = []
    db_payloads = set()
    for row in runs:
        parts = row.split('|')
        ph, artifact = parts[2], parts[3]
        db_payloads.add(ph)
        if ph not in prepared and ph not in terminal:
            if parts[1] in WINDOWS_R3['campaigns']:
                windows_attested.append(ph)
            else:
                ghost_runs.append(f'run {parts[0]} payload {ph[:12]} not from any prepared submission or terminal receipt')
        if ph in prepared and prepared[ph]['sha256'] != artifact.split(':')[1]:
            sha_mismatches.append(parts[0])
        if parts[4] != parts[5]:
            frame_mismatches.append(parts[0])
    unaccounted = sorted(ph for ph in prepared if ph not in db_payloads and ph not in terminal)
    terminal_also_recorded = sorted(ph for ph in terminal if ph in db_payloads)
    states = db("SELECT \"storageState\", count(*) FROM \"Artifact\" GROUP BY 1 ORDER BY 1")
    open_objects = db("SELECT count(*) FROM \"Artifact\" WHERE \"storageState\" IN ('PENDING','UPLOADED')")[0]
    derived = db('SELECT count(*) FROM "DerivedResult"')[0]
    missing_objects = []
    for row in db("SELECT \"storageKey\", \"byteSize\", sha256 FROM \"Artifact\" WHERE \"storageState\" IN ('VERIFIED','RETAINED') ORDER BY sha256"):
        key, size, sha = row.split('|')
        verified = shell(['docker', 'exec', SERVER, 'sh', '-c',
                          f'wc -c < /app/artifacts/{key}; sha256sum /app/artifacts/{key}'], check=False)
        lines = verified.stdout.split()
        if verified.returncode != 0 or len(lines) < 2 or int(lines[0]) != int(size) or lines[1] != sha:
            missing_objects.append(key)
    windows_rows = db("""SELECT "campaignId", count(*), min("createdAt")::text, max("createdAt")::text
                         FROM "BenchmarkRun"
                         WHERE "campaignId" IN ('campaign-48cfe70dd43b036c','campaign-ade93ae84fc38765','campaign-fb607b76eec675bf')
                         GROUP BY 1 ORDER BY 1""")
    windows_receipt_match = []
    for row in windows_rows:
        cid, count, first, last = row.split('|')
        ok = (int(count) == WINDOWS_R3['expectedRows'][cid]
              and first >= WINDOWS_R3['window'][0] and last <= WINDOWS_R3['window'][1])
        windows_receipt_match.append({'campaign': cid, 'rows': int(count),
                                      'first': first, 'last': last, 'matchesReceipt': ok})
    assert all(m['matchesReceipt'] for m in windows_receipt_match), json.dumps(windows_receipt_match)
    # Every windows r3 row either became payload-proven (once the submission
    # export lands) or remains receipt-attested; receipt-attested rows are
    # counted, never silently dropped.
    attested_count = sum(m['rows'] for m in windows_receipt_match)
    proven_windows = attested_count - len(windows_attested)
    membership = {
        'windowsRowsReceiptAttested': len(windows_attested),
        'windowsRowsPayloadProven': proven_windows,
        'windowsReceiptMatch': windows_receipt_match,
        'distinctPayloadIdentities': len(prepared),
        'dbRuns': len(runs),
        'terminalReceipts': len(terminal),
        'terminalAlsoRecorded': terminal_also_recorded,
        'unaccountedAttempts': unaccounted,
        'ghostRuns': ghost_runs,
        'shaMismatches': sha_mismatches,
        'frameCoverageMismatches': frame_mismatches,
        'artifactStates': states,
        'openArtifacts': int(open_objects),
        'missingFromDisk': missing_objects,
        'derivedResultRows': int(derived),
        'windowsCampaignRows': windows_rows,
        'analyses': db('SELECT status, count(*) FROM "QualityAnalysis" GROUP BY 1 ORDER BY 1'),
    }
    membership['exactMemberSet'] = (not ghost_runs and not unaccounted and not sha_mismatches
                                    and not frame_mismatches and not missing_objects
                                    and int(open_objects) == 0)
    assert membership['exactMemberSet'], json.dumps(membership, indent=1)[:3000]
    assert int(derived) == 0, 'PL is inactive; derived membership must be empty'
    record(state, 'membership', membership)
    print(json.dumps({k: membership[k] for k in ('dbRuns', 'terminalReceipts', 'artifactStates', 'analyses',
                                                 'terminalAlsoRecorded', 'exactMemberSet')}, indent=1))


def phase_restore(state):
    snapshot = PUB / 'candidate.compose.pre-gopfix.private.json'
    config = json.loads(snapshot.read_bytes())
    config['services']['server']['image'] = FIXED_IMAGE
    config['services']['server'].setdefault('environment', {})['ARTIFACT_ANALYSIS_CONCURRENCY_MAX'] = '0'
    COMPOSE.write_text(json.dumps(config, indent=2) + '\n')
    shell(f'cd {shlex.quote(str(CANDIDATE))} && docker compose -p {RELEASE_ID} -f candidate.compose.json up -d --no-build --pull never server')
    deadline = time.time() + 180
    while time.time() < deadline:
        ready = shell(f'curl --silent --show-error --fail --max-time 5 --cacert {shlex.quote(str(CERTS / "selfsigned.crt"))} {DIRECT_URL}/health/ready', check=False)
        if ready.returncode == 0:
            break
        time.sleep(3)
    else:
        raise RuntimeError('restored candidate server did not become ready')
    current = server_state()
    assert current['env']['ARTIFACT_ANALYSIS_CONCURRENCY_MAX'] == '0'
    assert current['env']['ARTIFACT_PENDING_ANALYSIS_MAX'] == '500'
    production = production_baseline()
    record(state, 'restore', {'env': current['env'], 'image': current['image'], 'productionBaseline': production})
    print(json.dumps({'phase': 'restore', 'image': current['image'],
                      'concurrency': current['env']['ARTIFACT_ANALYSIS_CONCURRENCY_MAX']}, indent=1))


def main():
    phase = sys.argv[1]
    handle = (STATE / 'measurement.lock').open('a')
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        if not RESULTS.is_file():
            save_results({'startedAt': now(), 'fixedSource': FIXED_SOURCE,
                          'note': 'post-fix verification; original defect evidence untouched; seeds pre-declared via ' + SEED_NAMESPACE,
                          'phases': []})
        state = load_results()
        existing = [p for p in state['phases'] if p['name'] == phase]
        if existing and phase not in ('verify', 'verify-db'):
            print(json.dumps({'phase': phase, 'skipped': 'already recorded'}, indent=1))
            return
        globals()['phase_' + phase.replace('-', '_')](state)
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)

PLAN_LINUX_BINARY = Path(PLAN['candidateRoot']) / 'encodingdb-client-linux'

if __name__ == '__main__':
    main()
