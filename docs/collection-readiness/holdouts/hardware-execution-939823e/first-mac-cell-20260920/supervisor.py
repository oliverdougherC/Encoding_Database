"""Exactly-one-cell supervisor using the reviewed operator's boundary pause."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import psutil

ROOT = Path('/Users/ofhd/Developer/Encoding_Database')
PACKET = ROOT / 'docs/collection-readiness/holdouts/hardware-execution-939823e'
CONTROL = Path(__file__).resolve().parent
PLAN = json.loads((PACKET / 'execution.json').read_text())
HOST = PLAN['hosts']['Mac']
CELL = next(cell for cell in PLAN['cells'] if cell['host'] == 'Mac')
ALLOCATION = Path(HOST['budgetRoot']) / 'mac-first-cell-allocation.json'
PAUSE = Path(HOST['pauseFile'])
LEDGER = Path(HOST['outputRoot']) / 'operator-ledger' / (CELL['cellId'] + '.json')
assert not PAUSE.exists() and not LEDGER.exists()
assert not (CONTROL / 'receipt.json').exists()
assert hashlib.sha256((PACKET / 'run.py').read_bytes()).hexdigest() == PLAN['operatorSha256']
allocation = json.loads(ALLOCATION.read_text())
assert allocation['executionHash'] == PLAN['executionHash'] and allocation['sourceCommit'] == PLAN['sourceCommit']
assert allocation['host'] == 'Mac' and allocation['exclusiveTimingGranted'] is True
assert datetime.datetime.fromisoformat(allocation['expiresAt']) > datetime.datetime.now(datetime.timezone.utc)
shutil.copyfile(ALLOCATION, CONTROL / 'allocation.json')
command = [HOST['python'], str(PACKET / 'run.py'), '--host', 'Mac', '--execution', str(PACKET / 'execution.json'),
           '--base-plan', str(PACKET.parent / 'timing-hardware-extension-v1.json'), '--execute', '--allocation', str(ALLOCATION)]
receipt = {'scope': 'Exactly first frozen Mac private hardware cell; no import, analysis, upload or calibration/PL acceptance claim.',
           'startedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'command': command, 'cell': CELL,
           'sourceCommit': PLAN['sourceCommit'], 'executionHash': PLAN['executionHash'], 'operatorSha256': PLAN['operatorSha256'],
           'allocation': allocation, 'pauseLatched': False, 'ownedProcesses': []}

def save():
    temporary = CONTROL / 'receipt.partial'
    temporary.write_text(json.dumps(receipt, indent=2) + '\n')
    temporary.replace(CONTROL / 'receipt.json')

with (CONTROL / 'operator.log').open('w') as log:
    process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                               env=dict(os.environ), start_new_session=True)
    root_process = psutil.Process(process.pid)
    receipt['operatorPid'] = process.pid
    receipt['operatorCreatedAt'] = root_process.create_time()
    save()
    while process.poll() is None and not receipt['pauseLatched']:
        if LEDGER.exists():
            started = json.loads(LEDGER.read_text())
            assert started['executionHash'] == PLAN['executionHash'] and started['cell'] == CELL
            assert started['status'] == 'RUNNING', 'Unexpected state before boundary pause could be latched'
            with PAUSE.open('x') as latch:
                latch.write('Parent allocation permits only the first Mac hardware cell. Stop at its next boundary; do not interrupt it.\n')
            receipt['pauseLatched'] = True
            receipt['pauseLatchedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            receipt['pausePath'] = str(PAUSE)
            receipt['observedRunningRecord'] = started
            receipt['ownedProcesses'] = [{'pid': p.pid, 'createdAt': p.create_time(), 'name': p.name()} for p in [root_process, *root_process.children(recursive=True)]]
            save()
            print(json.dumps({'status': 'FIRST_CELL_RUNNING_BOUNDARY_PAUSE_LATCHED', 'cellId': CELL['cellId']}), flush=True)
            break
        time.sleep(.05)
    receipt['exitCode'] = process.wait()
receipt['finishedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
receipt['operatorLogSha256'] = hashlib.sha256((CONTROL / 'operator.log').read_bytes()).hexdigest()
receipt['cellLedger'] = json.loads(LEDGER.read_text()) if LEDGER.exists() else None
reports = list((Path(HOST['outputRoot']) / 'operator-ledger').glob('*.json')) if Path(HOST['outputRoot']).exists() else []
receipt['otherCellLedgers'] = [str(path) for path in reports if not path.name.startswith('allocation-') and path != LEDGER]
receipt['survivingOwnedProcesses'] = []
for identity in receipt['ownedProcesses']:
    try:
        p = psutil.Process(identity['pid'])
        if p.create_time() == identity['createdAt'] and p.is_running() and p.status() != psutil.STATUS_ZOMBIE:
            receipt['survivingOwnedProcesses'].append(identity)
    except psutil.NoSuchProcess:
        pass
receipt['scopedMediaSurvivors'] = []
for p in psutil.process_iter(['pid', 'create_time', 'name', 'cmdline', 'status']):
    try:
        info = p.info
        if info['name'] in {'ffmpeg', 'ffprobe'} and info['status'] != psutil.STATUS_ZOMBIE:
            if any(str(HOST['outputRoot']) in arg or CELL['referencePath'] in arg for arg in (info['cmdline'] or [])):
                receipt['scopedMediaSurvivors'].append(info)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
receipt['outcome'] = 'GUARD_REFUSED_BEFORE_CELL' if receipt['cellLedger'] is None else receipt['cellLedger']['status']
save()
assert not receipt['otherCellLedgers'] and not receipt['survivingOwnedProcesses'] and not receipt['scopedMediaSurvivors']
print(json.dumps({'outcome': receipt['outcome'], 'exitCode': receipt['exitCode'], 'pauseLatched': receipt['pauseLatched'],
                  'otherCells': len(receipt['otherCellLedgers']), 'scopedMediaSurvivors': receipt['scopedMediaSurvivors']}), flush=True)
