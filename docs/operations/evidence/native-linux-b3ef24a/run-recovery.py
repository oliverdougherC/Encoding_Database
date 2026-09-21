"""Candidate recovery gates: real API+frontend smoke, restart persistence, paired
backup/isolated-restore of DB and retained objects, then exact config teardown.

Runs on P910 beside run-publication.py. Records every receipt to
publication/recovery-results.json. Nothing touches production; the isolated
restore lands in a scratch database inside the candidate DB container that is
dropped immediately, and object bytes are restored to a scratch directory that
is sha256-verified against the live volume before deletion.
"""
import datetime
import fcntl
import hashlib
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
PUB = ROOT / 'publication'
COMPOSE = CANDIDATE / 'candidate.compose.json'
PROJECT = 'encodingdb-candidate-730de3c'
SERVER = 'encodingdb-candidate-730de3c-server-1'
DB = 'encodingdb-candidate-730de3c-db-1'
CA = PUB / 'p910-candidate-ca.crt'
API_URL = 'https://127.0.0.1:3094'
APP_URL = 'https://127.0.0.1:3094'
HTTP_FRONTEND = 'http://127.0.0.1:3095'
RESULTS = PUB / 'recovery-results.json'
TABLES = ('BenchmarkRun', 'Artifact', 'QualityAnalysis', 'DerivedResult', 'DerivedResultMember',
          'TestClip', 'Benchmark', 'Recipe', 'Environment', 'BenchmarkProtocol', 'Submission',
          'ScoreContext', 'PublicCorpusGroup', '_prisma_migrations')


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def shell(command, check=True, env=None):
    completed = subprocess.run(command, capture_output=True, text=True, env=env)
    if check and completed.returncode != 0:
        raise RuntimeError(f'command failed ({completed.returncode}): '
                           f'{command if isinstance(command, str) else " ".join(command)}\n'
                           f'stdout={completed.stdout[:600]}\nstderr={completed.stderr[:600]}')
    return completed


def db(statement):
    return shell(['docker', 'exec', DB, 'psql', '-U', 'encodingdb_candidate', '-d', 'candidate',
                  '-tAc', statement]).stdout.splitlines()


def record(name, detail):
    existing = json.loads(RESULTS.read_text()) if RESULTS.is_file() else {'phases': []}
    existing['phases'] = [row for row in existing['phases'] if row['name'] != name]
    existing['phases'].append({'name': name, 'at': now(), 'detail': detail})
    RESULTS.write_text(json.dumps(existing, indent=2) + '\n')


def member_snapshot(database='candidate'):
    return shell(['docker', 'exec', DB, 'psql', '-U', 'encodingdb_candidate', '-d', database, '-tAc',
                  'SELECT md5(string_agg("payloadHash", \',\' ORDER BY "payloadHash")) FROM "BenchmarkRun"']).stdout.strip()


def phase_smoke(state):
    script = PUB / 'production_smoke.sh'
    assert script.is_file(), 'copy scripts/production_smoke.sh and the candidate CA to the native root first'
    env = dict(os.environ, CURL_CA_BUNDLE=str(CA))
    completed = shell(['bash', str(script), '--api-base-url', API_URL, '--app-url', APP_URL],
                      check=False, env=env)
    redirect = shell(['curl', '-sS', '-o', '/dev/null', '-w', '%{http_code} -> %{redirect_url}',
                      f'{HTTP_FRONTEND}/'], check=False)
    record('smoke', {'api': API_URL, 'app': APP_URL, 'exitCode': completed.returncode,
                     'httpFrontendRedirect': redirect.stdout.strip(),
                     'output': (completed.stdout + completed.stderr)[-2000:]})
    assert completed.returncode == 0, completed.stdout[-1200:] + completed.stderr[-1200:]
    assert redirect.stdout.startswith('301'), redirect.stdout


def phase_restart(state):
    before = {'runs': db('SELECT count(*) FROM "BenchmarkRun"')[0],
              'artifacts': db("SELECT \"storageState\", count(*) FROM \"Artifact\" GROUP BY 1 ORDER BY 1"),
              'members': member_snapshot('candidate')}
    shell(['docker', 'compose', '-p', PROJECT, '-f', str(COMPOSE), 'restart', 'server'])
    deadline = time.time() + 180
    ready = None
    while time.time() < deadline:
        probe = shell(['curl', '-sS', '--cacert', str(CA), '-o', '/dev/null', '-w', '%{http_code}',
                       f'{API_URL}/health/ready'], check=False)
        if probe.stdout.strip() == '200':
            ready = True
            break
        time.sleep(3)
    assert ready, 'candidate server did not become ready after restart'
    after = {'runs': db('SELECT count(*) FROM "BenchmarkRun"')[0],
             'artifacts': db("SELECT \"storageState\", count(*) FROM \"Artifact\" GROUP BY 1 ORDER BY 1"),
             'members': member_snapshot('candidate')}
    detail = {'before': before, 'after': after, 'identical': before == after}
    record('restart', detail)
    assert detail['identical']


def phase_backup(state):
    dump = PUB / 'candidate-backup-20260920.dump'
    with dump.open('wb') as handle:
        subprocess.run(['docker', 'exec', DB, 'pg_dump', '-U', 'encodingdb_candidate',
                        '--format', 'custom', 'candidate'], stdout=handle, check=True)
    objects_backup = PUB / 'objects-backup-20260920.tar'
    with objects_backup.open('wb') as handle:
        subprocess.run(['docker', 'exec', SERVER, 'tar', 'cf', '-', '-C', '/app/artifacts', 'objects'],
                       stdout=handle, check=True)
    expected = {line.split()[1]: line.split()[0]
                for line in db("SELECT sha256 || ' ' || \"byteSize\" FROM \"Artifact\" "
                               "WHERE \"storageState\" IN ('UPLOADED','VERIFIED','RETAINED')") if line.strip()}
    listed = shell(['docker', 'exec', SERVER, 'sh', '-c',
                    'cd /app/artifacts/objects && find . -type f -printf "%p %s\\n" | sort']).stdout.splitlines()
    detail = {'dumpSha256': digest(dump), 'dumpBytes': dump.stat().st_size,
              'objectsTarSha256': digest(objects_backup), 'objectsTarBytes': objects_backup.stat().st_size,
              'objectFiles': len(listed), 'storedExpectations': len(expected)}
    record('backup', detail)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def phase_restore(state):
    scratch = 'candidate_restore_check'
    shell(['docker', 'exec', DB, 'dropdb', '--if-exists', '-U', 'encodingdb_candidate', scratch])
    shell(['docker', 'exec', DB, 'createdb', '-U', 'encodingdb_candidate', scratch])
    dump = PUB / 'candidate-backup-20260920.dump'
    with dump.open('rb') as handle:
        subprocess.run(['docker', 'exec', '-i', DB, 'pg_restore', '-U', 'encodingdb_candidate',
                        '-d', scratch, '--no-owner'], stdin=handle, check=True)
    counts = {}
    for table in TABLES:
        live = db(f'SELECT count(*) FROM "{table}"')[0]
        restored = shell(['docker', 'exec', DB, 'psql', '-U', 'encodingdb_candidate', '-d', scratch,
                          '-tAc', f'SELECT count(*) FROM "{table}"']).stdout.strip()
        counts[table] = {'live': live, 'restored': restored, 'match': live == restored}
    live_members = db('SELECT md5(string_agg("payloadHash", \',\' ORDER BY "payloadHash")) FROM "BenchmarkRun"')[0]
    restored_members = shell(['docker', 'exec', DB, 'psql', '-U', 'encodingdb_candidate', '-d', scratch,
                              '-tAc', 'SELECT md5(string_agg("payloadHash", \',\' ORDER BY "payloadHash")) FROM "BenchmarkRun"']).stdout.strip()
    shell(['docker', 'exec', DB, 'dropdb', '-U', 'encodingdb_candidate', scratch])
    objects_restore = PUB / 'objects-restore-check-20260920'
    shell(['rm', '-rf', str(objects_restore)])
    objects_restore.mkdir()
    with (PUB / 'objects-backup-20260920.tar').open('rb') as handle:
        subprocess.run(['tar', 'xf', '-', '-C', str(objects_restore)], stdin=handle, check=True)
    mismatched = []
    listed = shell(['docker', 'exec', SERVER, 'sh', '-c',
                    'cd /app/artifacts/objects && find . -type f -printf "%P\\n" | sort']).stdout.splitlines()
    for name in listed:
        live = shell(['docker', 'exec', SERVER, 'sha256sum', f'/app/artifacts/objects/{name}']).stdout.split()[0]
        copy = digest(objects_restore / 'objects' / name)
        if live != copy:
            mismatched.append(name)
    shell(['rm', '-rf', str(objects_restore)])
    detail = {'tables': counts, 'membersMatch': live_members == restored_members,
              'objectFiles': len(listed), 'objectShaMismatches': mismatched}
    record('restore', detail)
    assert all(row['match'] for row in counts.values()), counts
    assert detail['membersMatch'] and not mismatched


def phase_teardown(state):
    import importlib.util
    driver = Path(__file__).with_name('run-publication.py')
    spec = importlib.util.spec_from_file_location('run_publication', driver)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.phase_teardown(module.load_results())
    record('teardown', {'restored': True, 'via': 'run-publication.py phase_teardown (shared lock)'})


PHASES = {'smoke': phase_smoke, 'restart': phase_restart, 'backup': phase_backup,
          'restore': phase_restore, 'teardown': phase_teardown}


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else None
    assert phase in PHASES, f'usage: run-recovery.py {"|".join(PHASES)}'
    lock = (STATE / 'measurement.lock').open('a+b')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    PHASES[phase](None)


if __name__ == '__main__':
    main()
