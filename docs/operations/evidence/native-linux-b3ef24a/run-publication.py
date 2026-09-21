"""Serial isolated candidate publication phases over the task fault proxy.

Every phase acquires the shared host measurement lock, records a durable receipt in
publication/results.json, and preserves the first real error. Transport faults are
injected only through the reviewed proxy and recorded token-free; real server
backpressure is observed with the proxy in pass mode BEFORE any injected
authorization pressure can pre-admit retained rows. Nothing here writes production.
"""
import json
import os
import shlex
import shutil
import signal
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
BINARY = ROOT / '日本語 client trial/encodingdb-client-linux'
NODE = '/mnt/NVME/docker/encodingdb-operations/20260920-projection-b3ef24a/bin/node'
PROXY = str(CANDIDATE / 'scripts/candidate-upload-fault-proxy.mjs')
CERTS = CANDIDATE / 'nginx/dev-certs'
PROXY_URL = 'https://127.0.0.1:3096'
DIRECT_URL = 'https://127.0.0.1:3094'
RELEASE_ID = 'encodingdb-candidate-730de3c'
SERVER = 'encodingdb-candidate-730de3c-server-1'
DB = 'encodingdb-candidate-730de3c-db-1'
VOLUME_DIR = '/var/lib/docker/volumes/encodingdb-candidate-730de3c_artifact_data/_data'
DRIVER_PY = ('/mnt/NVME/docker/encodingdb-operations/20260914-native-linux-candidate/'
             'build-venv/lib/python3.12/site-packages')
QUEUES = {
    'software': ROOT / '日本語 client trial/software-queue',
    'nvenc': ROOT / '日本語 client trial/nvenc-queue',
}

sys.path.insert(0, DRIVER_PY)
sys.path.insert(0, str(CANDIDATE))
import fcntl  # noqa: E402
import hashlib  # noqa: E402
import importlib.util  # noqa: E402


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RELEASE = load('native_release', CANDIDATE / 'scripts/release_manifest_lib.py')
LEDGER = load('native_ledger', CANDIDATE / 'scripts/native-e2e-ledger.py')

RESULTS = PUB / 'results.json'


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


def shell(command, *, check=True, env=None):
    completed = subprocess.run(command, shell=isinstance(command, str), env=env,
                               capture_output=True, text=True)
    if check and completed.returncode != 0:
        raise RuntimeError(f'command failed ({completed.returncode}): {command if isinstance(command,str) else " ".join(command)}\n'
                           f'stdout={completed.stdout[:2000]}\nstderr={completed.stderr[:2000]}')
    return completed


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
                'ENCODINGDB_SUITE_CACHE_DIR': str(ROOT / '日本語 client trial/clean-suite-cache')})
    return env


def campaign_id(queue):
    ids = [path.name for path in (queue / 'campaigns').glob('campaign-*')
           if (path / 'campaign-complete.json').is_file()]
    assert len(ids) == 1, f'{queue} has {ids}'
    return ids[0]


def run_client(queue, args, tag, *, measurement=600):
    command = [str(BINARY), '--cli', *args, '--queue-dir', str(queue),
               '--max-storage-mb', '2048']
    observed = RELEASE._run_smoke_command(command, env=client_env(), queue_dir=queue,
            stdout_path=PUB / f'{tag}.stdout.log', stderr_path=PUB / f'{tag}.stderr.log',
            acquisition_seconds=120, measurement_seconds=measurement)
    return {'command': [str(part) for part in command], **observed}


def pending(queue):
    entries = []
    for path in sorted(queue.glob('*.json')):
        try:
            raw = json.loads(path.read_text())
        except ValueError:
            entries.append({'file': path.name, 'corrupt': True})
            continue
        entries.append({'file': path.name,
                        'attempts': raw.get('attempts'), 'nextAttemptAt': raw.get('nextAttemptAt'),
                        'retryDeadlineAt': raw.get('retryDeadlineAt'), 'lastError': (raw.get('lastError') or '')[:200]})
    return entries



def dead_letter(queue):
    root = queue / 'dead-letter'
    return sorted(path.name for path in root.glob('*.json')) if root.is_dir() else []


def db(sql):
    inspect = json.loads(shell(['docker', 'inspect', DB]).stdout)[0]
    values = dict(item.split('=', 1) for item in inspect['Config']['Env'] if '=' in item)
    user, database = values['POSTGRES_USER'], values['POSTGRES_DB']
    completed = shell(['docker', 'exec', DB, 'psql', '-U', user, '-d', database, '-tAc', sql], check=True)
    return [line for line in completed.stdout.splitlines() if line != '']


def server_env():
    inspect = json.loads(shell(['docker', 'inspect', SERVER]).stdout)[0]
    return dict(item.split('=', 1) for item in inspect['Config']['Env'] if '=' in item)


def inspect_summary(name):
    inspect = json.loads(shell(['docker', 'inspect', name]).stdout)[0]
    return {'id': inspect['Id'], 'startedAt': inspect['State']['StartedAt'],
            'image': inspect['Config']['Image'],
            'volumes': sorted(f"{m.get('Name') or m.get('Source')}->{m['Destination']}" for m in inspect['Mounts'])}


def evidence_file():
    marker = PUB / 'evidence-path'
    return Path(marker.read_text().strip()) if marker.is_file() else PUB / 'fault-proxy-events.jsonl'


def proxy_events(kind=None, injected=None, since=None, limit=100000):
    events = []
    path = evidence_file()
    if not path.is_file():
        return events
    for line in path.read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if kind is not None and event.get('kind') != kind:
            continue
        if injected is not None and bool(event.get('injected')) != injected:
            continue
        if since is not None and event.get('at', '') < since:
            continue
        events.append(event)
    return events[-limit:]


def stamp():
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()) + 'Z'


def set_mode(word):
    mode_path = PUB / 'mode'
    temporary = PUB / 'mode.tmp'
    temporary.write_text(word + '\n')
    os.replace(temporary, mode_path)


def mode():
    return (PUB / 'mode').read_text().strip()


def ledger_pair(queue):
    return LEDGER.capture(queue)


def proxy_alive():
    pid_file = PUB / 'proxy.pid'
    if not pid_file.is_file():
        return None
    pid = int(pid_file.read_text().strip())
    try:
        os.kill(pid, 0)
        return pid
    except OSError:
        return None


def restart_server():
    completed = shell(f'cd {shlex.quote(str(CANDIDATE))} && {shlex.quote(NODE)} scripts/verify-deployment-volumes.mjs candidate.compose.json', check=False)
    volumes_receipt = completed.stdout.strip()
    shell(f'cd {shlex.quote(str(CANDIDATE))} && docker compose -p {RELEASE_ID} -f candidate.compose.json up -d --no-build --pull never server', check=True)
    deadline = time.time() + 180
    while time.time() < deadline:
        ready = shell(f'curl --silent --show-error --fail --max-time 5 --cacert {shlex.quote(str(CANDIDATE / "nginx/dev-certs/selfsigned.crt"))} {DIRECT_URL}/health/ready', check=False)
        if ready.returncode == 0:
            return json.loads(ready.stdout), volumes_receipt
        time.sleep(3)
    raise RuntimeError('candidate server did not become ready after restart')


def compose_patch(env_updates, private_copy):
    original = COMPOSE.read_bytes()
    if private_copy.is_file():
        assert original == private_copy.read_bytes(), 'compose drifted from the recorded pre-test snapshot'
    config = json.loads(original)
    config['services']['server'].setdefault('environment', {}).update(env_updates)
    COMPOSE.write_text(json.dumps(config, indent=2) + '\n')


def production_baseline():
    return {name: inspect_summary(name) for name in
            ('encodingdb-server-1', 'encodingdb-frontend-1', 'encodingdb-db-1', 'encodingdb-nginx')}


def acquire():
    PUB.mkdir(exist_ok=True)
    handle = (STATE / 'measurement.lock').open('a')
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return handle


def expect(state, name):
    phase = next((phase for phase in state['phases'] if phase['name'] == name), None)
    return phase


def main():
    phase = sys.argv[1]
    assert PUB.parent == ROOT
    handle = acquire()
    if not RESULTS.is_file():
        save_results({'startedAt': now(), 'sourceCommit': PLAN['sourceCommit'],
                      'packageSha256': PLAN['packageSha256'],
                      'note': 'isolated candidate publication; injected transport faults are proxy-tagged; '
                              'real admission is measured in pass mode before injected pressure',
                      'phases': []})
    state = load_results()
    try:
        if phase != 'pre' and expect(state, phase):
            print(json.dumps({'phase': phase, 'skipped': 'already recorded in results.json'}, indent=1))
            return
        globals()['phase_' + phase.replace('-', '_')](state)
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)


def phase_pre(state):
    private_compose = PUB / 'candidate.compose.pre.private.json'
    if not private_compose.is_file():
        shutil.copyfile(COMPOSE, private_compose)
        os.chmod(private_compose, 0o600)
    record(state, 'pre:snapshot', {
        'composeSha256': digest(private_compose),
        'serverEnv': {key: server_env()[key] for key in sorted(server_env()) if key.startswith(('ARTIFACT_', 'V7_'))},
        'candidateServer': inspect_summary(SERVER),
        'productionBaseline': production_baseline(),
        'binarySha256': digest(BINARY),
        'packageMatches': digest(BINARY) == PLAN['packageSha256'],
        'campaigns': {name: campaign_id(queue) for name, queue in QUEUES.items()},
    })
    baseline = {
        'runs': db('SELECT count(*) FROM "BenchmarkRun"')[0],
        'artifactsByState': db("SELECT \"storageState\", count(*) FROM \"Artifact\" GROUP BY 1 ORDER BY 1"),
        'analysesByStatus': db("SELECT status, count(*) FROM \"QualityAnalysis\" GROUP BY 1 ORDER BY 1"),
        'objects': shell(['docker', 'exec', SERVER, 'sh', '-c',
                          'find /app/artifacts -type f -printf "%P %s\\n" | sort'], check=True).stdout.splitlines(),
    }
    record(state, 'pre:db-baseline', baseline)
    if proxy_alive() is None:
        set_mode('offline')
        os.chmod(PUB / 'mode', 0o600)
        log = (PUB / 'proxy.stdout.log').open('a'), (PUB / 'proxy.stderr.log').open('a')
        evidence = PUB / 'fault-proxy-events.jsonl'
        counter = 0
        while evidence.exists():
            counter += 1
            evidence = PUB / f'fault-proxy-events-{counter}.jsonl'
        (PUB / 'evidence-path').write_text(str(evidence) + '\n')
        before_start = (PUB / 'proxy.stdout.log').stat().st_size
        proxy_env = dict(os.environ,
            CANDIDATE_UPSTREAM_URL=DIRECT_URL, CANDIDATE_FAULT_PORT='3096',
            CANDIDATE_FAULT_MODE_FILE=str(PUB / 'mode'),
            CANDIDATE_FAULT_EVIDENCE=str(evidence),
            CANDIDATE_CA_FILE=str(CERTS / 'selfsigned.crt'),
            CANDIDATE_CERT_FILE=str(CERTS / 'selfsigned.crt'),
            CANDIDATE_KEY_FILE=str(CERTS / 'selfsigned.key'))
        proxy_env.pop('CURL_CA_BUNDLE', None)
        process = subprocess.Popen([NODE, PROXY], env=proxy_env, stdout=log[0], stderr=log[1], start_new_session=True)
        (PUB / 'proxy.pid').write_text(f'{process.pid}\n')
        deadline = time.time() + 15
        while 'listening' not in (PUB / 'proxy.stdout.log').read_text()[before_start:]:
            if time.time() > deadline:
                raise RuntimeError('fault proxy did not start: ' + (PUB / 'proxy.stderr.log').read_text()[:800])
            time.sleep(0.5)
    elif not (PUB / 'evidence-path').is_file():
        (PUB / 'evidence-path').write_text(str(PUB / 'fault-proxy-events.jsonl') + '\n')
    record(state, 'pre:proxy', {'pid': proxy_alive(), 'mode': mode(), 'evidence': str(evidence_file())})
    print(json.dumps({'phase': 'pre', 'phases': [p['name'] for p in load_results()['phases']]}, indent=1))


def phase_offline(state):
    assert proxy_alive()
    assert mode() == 'offline'
    outcomes = {}
    for name, queue in QUEUES.items():
        before = ledger_pair(queue)
        outcome = run_client(queue, ['--resume-campaign', campaign_id(queue), '--submit',
                                     '--base-url', PROXY_URL], f'offline:{name}')
        after = LEDGER.capture(queue)
        outcomes[name] = {
            'returnCode': outcome['returnCode'], 'survivors': outcome['survivingOwnedPids'],
            'pending': pending(queue), 'deadLetter': dead_letter(queue),
            'ledgerImmutable': before == after,
            'immutableFiles': len(before['files']),
        }
    injected = [event for event in proxy_events() if event.get('injected')]
    forwarded = [event for event in proxy_events(injected=False) if event.get('method') in ('POST', 'PUT')]
    assert all(outcome['returnCode'] == 10 for outcome in outcomes.values()), outcomes
    assert all(outcome['ledgerImmutable'] and not outcome['deadLetter'] for outcome in outcomes.values())
    assert all(outcome['pending'] for outcome in outcomes.values())
    assert injected and not forwarded
    record(state, 'offline', outcomes)
    print(json.dumps({'phase': 'offline', 'outcomes': {k: v['returnCode'] for k, v in outcomes.items()},
                      'pending': {k: len(v['pending']) for k, v in outcomes.items()},
                      'injected503': len(injected), 'forwardedWrites': len(forwarded)}, indent=1))


def phase_real_admission(state):
    assert proxy_alive() and mode() in ('offline', 'pass')
    compose_patch({'ARTIFACT_PENDING_ANALYSIS_MAX': '2'}, PUB / 'candidate.compose.pre.private.json')
    health, volumes_receipt = restart_server()
    env = server_env()
    assert env['ARTIFACT_PENDING_ANALYSIS_MAX'] == '2' and env['ARTIFACT_ANALYSIS_CONCURRENCY_MAX'] == '0'
    assert inspect_summary(SERVER)['image'] == expect(state, 'pre:snapshot')['candidateServer']['image']
    assert inspect_summary(SERVER)['volumes'] == expect(state, 'pre:snapshot')['candidateServer']['volumes']
    assert inspect_summary(SERVER)['id'] != expect(state, 'pre:snapshot')['candidateServer']['id']
    assert production_baseline() == expect(state, 'pre:snapshot')['productionBaseline']
    started = stamp()
    set_mode('pass')
    sw = QUEUES['software']
    nv = QUEUES['nvenc']
    first = run_client(sw, ['--upload-only', '--base-url', PROXY_URL], 'real-admission:software', measurement=900)
    second = run_client(nv, ['--upload-only', '--base-url', PROXY_URL], 'real-admission:nvenc', measurement=900)
    admitted_runs = db("SELECT id, \"campaignId\", \"physicalSourceId\", \"payloadHash\" FROM \"BenchmarkRun\" ORDER BY \"createdAt\"")
    pending_analyses = db("SELECT count(*) FROM \"QualityAnalysis\" WHERE status='PENDING'")[0]
    uploaded = db("SELECT a.sha256, a.\"byteSize\", a.\"storageState\" FROM \"Artifact\" a WHERE a.\"storageState\" <> 'PENDING' ORDER BY a.sha256")
    genuine_503 = [event for event in proxy_events(injected=False, since=started) if event.get('status') == 503]
    injected = proxy_events(injected=True, since=started)
    sw_pending, nv_pending = pending(sw), pending(nv)
    assert int(pending_analyses) == 2, pending_analyses
    assert len(admitted_runs) == 2, admitted_runs
    assert len(uploaded) == 2, uploaded
    assert any(event['path'].endswith('/benchmark-runs') and event['status'] == 503 for event in genuine_503), genuine_503[:5]
    assert not injected, injected[:3]
    future = [entry for entry in sw_pending + nv_pending if (entry.get('nextAttemptAt') or 0) > time.time() + 5]
    assert future, 'client did not preserve a bounded retry schedule for the real 503'
    record(state, 'real-admission', {
        'health': health, 'volumes': volumes_receipt,
        'software': {key: first[key] for key in ('returnCode', 'elapsedSeconds', 'survivingOwnedPids')},
        'nvenc': {key: second[key] for key in ('returnCode', 'elapsedSeconds', 'survivingOwnedPids')},
        'admittedRuns': admitted_runs, 'pendingAnalyses': int(pending_analyses),
        'uploadedArtifacts': uploaded,
        'genuineBackpressure503': len(genuine_503),
        'proxyInjectedEvents': len(injected),
        'softwarePending': len(sw_pending), 'nvencPending': len(nv_pending),
        'samplePreservedRetry': future[:3],
    })
    print(json.dumps({'phase': 'real-admission', 'admitted': len(admitted_runs),
                      'pendingAnalyses': int(pending_analyses), 'genuine503': len(genuine_503),
                      'softwareReturn': first['returnCode'], 'nvencReturn': second['returnCode']}, indent=1))


def phase_restore(state):
    assert proxy_alive()
    original = (PUB / 'candidate.compose.pre.private.json').read_bytes()
    COMPOSE.write_bytes(original)
    config = json.loads(original)
    config['services']['server']['environment']['ARTIFACT_ANALYSIS_CONCURRENCY_MAX'] = '2'
    COMPOSE.write_text(json.dumps(config, indent=2) + '\n')
    health, volumes_receipt = restart_server()
    env = server_env()
    assert env['ARTIFACT_PENDING_ANALYSIS_MAX'] == '500' and env['ARTIFACT_ANALYSIS_CONCURRENCY_MAX'] == '2'
    assert production_baseline() == expect(state, 'pre:snapshot')['productionBaseline']
    record(state, 'restore', {'health': health, 'volumes': volumes_receipt,
                              'env': {'ARTIFACT_PENDING_ANALYSIS_MAX': '500', 'ARTIFACT_ANALYSIS_CONCURRENCY_MAX': '2'}})
    print(json.dumps({'phase': 'restore', 'env': env['ARTIFACT_PENDING_ANALYSIS_MAX'],
                      'concurrency': env['ARTIFACT_ANALYSIS_CONCURRENCY_MAX']}, indent=1))


def phase_pressure(state):
    assert proxy_alive()
    set_mode('pressure')
    queue = QUEUES['nvenc']
    before = {entry['file']: entry for entry in pending(queue)}
    log_out = (PUB / 'pressure.client.stdout.log').open('w')
    log_err = (PUB / 'pressure.client.stderr.log').open('w')
    process = subprocess.Popen([str(BINARY), '--cli', '--upload-only', '--queue-dir', str(queue),
                                '--base-url', PROXY_URL, '--max-storage-mb', '2048'],
                               env=client_env(), stdout=log_out, stderr=log_err, start_new_session=True)
    observed_children = {}
    started = stamp()
    injected = []
    deadline = time.time() + 180
    while time.time() < deadline and not injected:
        RELEASE._smoke_children(process, observed_children)
        injected = [event for event in proxy_events(injected=True, since=started) if event.get('kind') == 'pressure']
        if process.poll() is not None:
            break
        time.sleep(0.25)
    stopped = process.poll() is None
    if stopped:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        return_code = process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        return_code = process.wait()
    survivors = RELEASE._smoke_survivors(observed_children)
    if survivors:
        RELEASE._stop_smoke_tree(process, observed_children)
    injected = [event for event in proxy_events(injected=True, since=started) if event.get('kind') == 'pressure']
    forwarded_creates = [event for event in proxy_events(injected=False, since=started)
                         if event.get('method') == 'POST' and not event['path'].endswith('/upload-authorizations')]
    after = {entry['file']: entry for entry in pending(queue)}
    retried = []
    for name, entry in after.items():
        old = before.get(name)
        if old is not None and (entry.get('nextAttemptAt') or 0) > (old.get('nextAttemptAt') or 0):
            assert entry.get('retryDeadlineAt') == old.get('retryDeadlineAt'), 'spool retry deadline was rewritten'
            retried.append({'file': name, 'nextAttemptAt': entry['nextAttemptAt'],
                            'lastError': entry['lastError']})
    assert injected, 'no injected authorization pressure was observed'
    assert not survivors
    wait_until = max(entry['nextAttemptAt'] for entry in retried)
    if wait_until > time.time():
        time.sleep(wait_until - time.time() + 1.0)
    record(state, 'pressure', {'clientReturnCode': return_code, 'terminatedAfterFirstInjection': stopped,
                                'injectedEvents': injected[:5], 'injectedCount': len(injected),
                                'forwardedRunCreates': len(forwarded_creates),
                                'preservedRetries': retried[:5], 'preservedCount': len(retried),
                                'waitedForRealSpoolDeadline': True})
    print(json.dumps({'phase': 'pressure', 'injected': len(injected), 'preserved': len(retried),
                      'clientReturn': return_code}, indent=1))


def phase_lost_response(state):
    assert proxy_alive()
    def earliest(candidate):
        return min([entry.get('nextAttemptAt') or 0 for entry in pending(candidate)] or [float('inf')])
    queue = QUEUES['software'] if earliest(QUEUES['software']) <= earliest(QUEUES['nvenc']) else QUEUES['nvenc']
    due_waited = 0.0
    while due_waited < 600:
        assert pending(queue), 'no pending submissions remain to exercise a lost response'
        next_due = earliest(queue)
        if next_due <= time.time():
            break
        time.sleep(min(5.0, next_due - time.time() + 0.5))
        due_waited += 1
    started = stamp()
    set_mode('lost-response-once')
    log_out = (PUB / 'lost-response.client.stdout.log').open('w')
    log_err = (PUB / 'lost-response.client.stderr.log').open('w')
    process = subprocess.Popen([str(BINARY), '--cli', '--upload-only', '--queue-dir', str(queue),
                                '--base-url', PROXY_URL, '--max-storage-mb', '2048'],
                               env=client_env(), stdout=log_out, stderr=log_err, start_new_session=True)
    observed_children = {}
    drops = []
    deadline = time.time() + 300
    while time.time() < deadline and not drops:
        RELEASE._smoke_children(process, observed_children)
        drops = [event for event in proxy_events(since=started) if event.get('kind') == 'lost-response-after-upstream-success']
        if process.poll() is not None:
            break
        time.sleep(0.25)
    stopped = process.poll() is None
    if stopped:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        return_code = process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        return_code = process.wait()
    survivors = RELEASE._smoke_survivors(observed_children)
    if survivors:
        RELEASE._stop_smoke_tree(process, observed_children)
    drops = [event for event in proxy_events(since=started) if event.get('kind') == 'lost-response-after-upstream-success']
    assert len(drops) == 1, drops[:3]
    assert not survivors
    mid_rows = db('SELECT r.id, a.id, a.sha256, a."byteSize", a."storageState" FROM "BenchmarkRun" r '
                  'JOIN "Artifact" a ON a."benchmarkRunId"=r.id '
                  'WHERE a."uploadedAt" >= ' + repr(started) + '::timestamptz ORDER BY r.id')
    dropped = [row.split('|') for row in mid_rows
               if int(row.split('|')[3]) == drops[0].get('requestBytes')]
    assert dropped, [drops[0], mid_rows[:4]]
    assert len(dropped) == 1, [drops[0], mid_rows[:4]]
    set_mode('pass')
    second = run_client(queue, ['--upload-only', '--base-url', PROXY_URL], 'lost-response:replay2', measurement=1500)
    identity = db('SELECT r.id, a.id, a.sha256, a."byteSize", a."storageState" FROM "BenchmarkRun" r '
                  'JOIN "Artifact" a ON a."benchmarkRunId"=r.id WHERE r.id=' + repr(dropped[0][0]))[0].split('|')
    payload_repeat = db('SELECT count(*) FROM "BenchmarkRun" WHERE "payloadHash"='
                        '(SELECT "payloadHash" FROM "BenchmarkRun" WHERE id=' + repr(dropped[0][0]) + ')')[0]
    sha_repeat = db('SELECT count(*) FROM "Artifact" WHERE sha256=' + repr(dropped[0][2]))[0]
    runs_after = set(db('SELECT id FROM "BenchmarkRun"'))
    assert identity[0] == dropped[0][0] and identity[1] == dropped[0][1] and identity[2] == dropped[0][2]
    assert identity[4] in ('UPLOADED', 'VERIFIED', 'RETAINED'), identity
    assert int(payload_repeat) == 1, 'replay created a duplicate run payload identity'
    assert dropped[0][0] in runs_after
    record(state, 'lost-response', {'dropEvent': drops[0], 'clientReturn': return_code,
                                    'terminatedAfterDrop': stopped, 'replay2': second['returnCode'],
                                    'runIdentity': {'runId': identity[0], 'artifactId': identity[1],
                                                     'sha256': identity[2], 'byteSize': int(identity[3])},
                                    'stateAfterDrop': dropped[0][4], 'stateAfterReplay': identity[4],
                                    'payloadHashRows': int(payload_repeat), 'artifactRowsForSha': int(sha_repeat)})
    print(json.dumps({'phase': 'lost-response', 'run': identity[0], 'stateAfterReplay': identity[4]}, indent=1))


def phase_drain(state):
    assert proxy_alive()
    set_mode('pass')
    started = time.time()
    rounds = []
    while time.time() - started < 3600:
        due = False
        for name, queue in QUEUES.items():
            entries = pending(queue)
            if entries:
                outcome = run_client(queue, ['--upload-only', '--base-url', PROXY_URL], f'drain:{name}', measurement=1200)
                rounds.append({'queue': name, 'returnCode': outcome['returnCode'],
                               'pendingAfter': len(pending(queue)), 'deadLetter': dead_letter(queue)})
                due = True
                assert not outcome['survivingOwnedPids']
        if not due:
            break
        nxt = min([entry.get('nextAttemptAt') or 0 for name, queue in QUEUES.items() for entry in pending(queue)] or [0])
        if nxt > time.time():
            time.sleep(min(60, nxt - time.time() + 1.0))
    leftovers = {name: pending(queue) for name, queue in QUEUES.items() if pending(queue)}
    assert not leftovers, [row['file'] for rows in leftovers.values() for row in rows][:5]
    deadline = time.time() + 3600
    while time.time() < deadline:
        backlog = db("SELECT count(*) FROM \"QualityAnalysis\" WHERE status='PENDING'")[0]
        if int(backlog) == 0:
            break
        time.sleep(15)
    else:
        raise RuntimeError('analysis backlog did not drain within the bounded budget')
    record(state, 'drain', {'rounds': rounds, 'wallSeconds': round(time.time() - started, 1),
                            'analysesBacklog': int(db("SELECT count(*) FROM \"QualityAnalysis\" WHERE status='PENDING'")[0]),
                            'deadLetters': {name: dead_letter(queue) for name, queue in QUEUES.items()},
                            'pendingAfter': {name: len(pending(queue)) for name, queue in QUEUES.items()}})
    print(json.dumps({'phase': 'drain', 'wallSeconds': rounds and round(time.time() - started, 1)}, indent=1))


def phase_reconcile(state):
    prepared = {}
    submissions = 0
    for name, queue in QUEUES.items():
        campaign = campaign_id(queue)
        for path in sorted((queue / 'campaigns' / campaign).glob('submission-*.json')):
            payload = json.loads(path.read_text())
            run_create = payload.get('runCreate') or {}
            ph = run_create.get('payloadHash')
            assert ph, f'submission {path.name} lacks payloadHash'
            row = prepared.setdefault(ph, {'queue': name, 'sha256': payload.get('artifactSha256'),
                                           'key': (run_create.get('campaignId'), run_create.get('repetitionGroupId'),
                                                   run_create.get('repetitionIndex'))})
            assert row['sha256'] == payload.get('artifactSha256'), 'same payloadHash with different artifact bytes'
            submissions += 1
    terminal = {}
    for name, queue in QUEUES.items():
        for path in sorted((queue / 'terminal').glob('*.json')):
            entry = json.loads(path.read_text())
            run_create = (entry.get('payload') or {}).get('runCreate') or {}
            ph = run_create.get('payloadHash')
            if ph:
                terminal[ph] = {'queue': name, 'lastError': entry.get('lastError'), 'attempts': entry.get('attempts')}
    runs = db("""SELECT r.id, r.\"campaignId\", r.\"physicalSourceId\", r.\"payloadHash\",
                        c.id || ':' || a.sha256 || ':' || a.\"byteSize\" || ':' || a.\"storageState\",
                        r.\"sourceFrameCount\", r.\"encodedFrameCount\",
                        r.\"repetitionIndex\", r.\"repetitionGroupId\"
                 FROM \"BenchmarkRun\" r
                 JOIN \"Artifact\" a ON a.\"benchmarkRunId\"=r.id
                 JOIN \"TestClip\" c ON c.id = r.\"testClipId\"
                 ORDER BY r.\"campaignId\", r.id""")
    derived = db('SELECT count(*) FROM "DerivedResult"')[0]
    frame_mismatches = []
    sha_mismatches = []
    ghost_runs = []
    db_payloads = {}
    for row in runs:
        parts = row.split('|')
        ph = parts[3]
        key = (parts[1], '|'.join(parts[8:]), parts[7])
        if key in db_payloads:
            ghost_runs.append(f'duplicate measurement group repetition: {key}')
        db_payloads[key] = ph
        if ph not in prepared:
            ghost_runs.append(f'run {parts[0]} payload not from any prepared submission')
        elif prepared[ph]['sha256'] != parts[4].split(':')[1]:
            sha_mismatches.append(parts[0])
        if parts[5] != parts[6]:
            frame_mismatches.append(parts[0])
    unaccounted = sorted(ph for ph, row in prepared.items()
                         if ph not in set(db_payloads.values()) and ph not in terminal)
    terminal_also_recorded = sorted(ph for ph in terminal if ph in set(db_payloads.values()))
    states = db("SELECT \"storageState\", count(*) FROM \"Artifact\" GROUP BY 1 ORDER BY 1")
    analyses = db("""SELECT q.status, q.\"metricModelId\", q.\"analysisWorkerVersion\", count(*)
                     FROM \"QualityAnalysis\" q GROUP BY 1,2,3 ORDER BY 1""")
    missing_objects = []
    for row in db("SELECT \"storageKey\", \"byteSize\", sha256 FROM \"Artifact\" WHERE \"storageState\" IN ('UPLOADED','VERIFIED','RETAINED') ORDER BY sha256"):
        key, size, sha = row.split('|')
        verified = shell(['docker', 'exec', SERVER, 'sh', '-c',
                          f'wc -c < /app/artifacts/{key}; sha256sum /app/artifacts/{key}'], check=False)
        lines = verified.stdout.split()
        if verified.returncode != 0 or len(lines) < 2 or int(lines[0]) != int(size) or lines[1] != sha:
            missing_objects.append(row)
    duplicates = db('SELECT sha256, count(*) FROM "Artifact" WHERE sha256 IS NOT NULL GROUP BY 1 HAVING count(*) > 1')
    objects_total = int(shell(['docker', 'exec', SERVER, 'sh', '-c',
                               'find /app/artifacts/objects -type f | wc -l']).stdout.strip())
    members = {
        'submissionsPrepared': submissions,
        'distinctPayloadIdentities': len(prepared),
        'dbRuns': len(runs),
        'terminalReceipts': len(terminal),
        'unaccountedAttempts': unaccounted,
        'terminalAlsoRecorded': terminal_also_recorded,
        'ghostRuns': ghost_runs,
        'shaMismatches': sha_mismatches,
        'frameCoverageMismatches': frame_mismatches,
        'derivedResultRows': int(derived),
        'missingFromDisk': missing_objects,
        'repeatedArtifactShas': duplicates,
        'artifactStates': states, 'analyses': analyses,
        'objectsOnVolume': objects_total,
        'physicalSourceId': (STATE / 'physical-source-id').read_bytes().hex(),
        'physicalSourceIds': sorted({row.split('|')[2] for row in runs}),
    }
    members['exactMemberSet'] = (not ghost_runs and not unaccounted and not sha_mismatches
                                 and not frame_mismatches and not missing_objects)
    assert members['exactMemberSet'], json.dumps(members, indent=1)[:2000]
    assert int(derived) == 0, 'PL is inactive; derived membership must be empty'
    record(state, 'reconcile', members)
    print(json.dumps({'phase': 'reconcile', 'runs': members['dbRuns'],
                      'exact': members['exactMemberSet'], 'terminal': members['terminalReceipts'],
                      'states': states, 'analyses': analyses}, indent=1))


def phase_teardown(state):
    pid = proxy_alive()
    if pid:
        os.killpg(pid, signal.SIGTERM)
        time.sleep(1)
        try:
            os.killpg(pid, 0)
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            pass
    COMPOSE.write_bytes((PUB / 'candidate.compose.pre.private.json').read_bytes())
    health, volumes = restart_server()
    env = server_env()
    assert env['ARTIFACT_PENDING_ANALYSIS_MAX'] == '500'
    assert env['ARTIFACT_ANALYSIS_CONCURRENCY_MAX'] == '0'
    assert digest(COMPOSE) == digest(PUB / 'candidate.compose.pre.private.json')
    record(state, 'teardown', {'health': health, 'volumes': volumes, 'proxyStopped': True,
                               'restoredEnv': {key: env[key] for key in ('ARTIFACT_PENDING_ANALYSIS_MAX', 'ARTIFACT_ANALYSIS_CONCURRENCY_MAX')}})
    print(json.dumps({'phase': 'teardown', 'restored': True}, indent=1))


if __name__ == '__main__':
    main()
