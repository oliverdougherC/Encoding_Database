import dataclasses
import datetime
import hashlib
import json
import platform
from pathlib import Path
import subprocess
import time

from client.hardware_monitor import HardwareMonitor, FFMPEG_PROCESS_WINDOW_SOURCE

root = Path.cwd()
helper = Path('/Users/ofhd/Developer/Encoding_Database/.build/runtime-macos-arm64-vmaf3.2/ffmpeg')
out = root / 'docs/collection-readiness/process-cpu-diagnostic'
command = [str(helper), '-hide_banner', '-nostdin', '-re', '-f', 'lavfi', '-i', 'testsrc2=size=1920x1080:rate=24', '-t', '5', '-an', '-c:v', 'libx264', '-preset', 'medium', '-crf', '23', '-threads', '2', '-f', 'null', '-']
receipt = {
    'schemaVersion': 1,
    'purpose': 'Bounded real-process CPU diagnostic only; paced synthetic input, no calibration or encode-speed claim.',
    'sourceCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
    'startedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'host': {'system': platform.system(), 'release': platform.release(), 'machine': platform.machine()},
    'command': command,
    'helperSha256': hashlib.sha256(helper.read_bytes()).hexdigest(),
    'helperVersion': subprocess.check_output([str(helper), '-version'], text=True).splitlines()[0],
    'deadlineSeconds': 30,
}
monitor = None
process = None
try:
    with (out / 'ffmpeg-stderr.txt').open('wb') as log:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log)
        monitor = HardwareMonitor(ffmpeg_pid=process.pid, encoder_name='libx264')
        monitor.start()
        receipt['exitCode'] = process.wait(timeout=30)
finally:
    if process is not None and process.poll() is None:
        receipt['forcedCleanup'] = True
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    if monitor is not None:
        metrics = monitor.stop()
        receipt['metrics'] = dataclasses.asdict(metrics)
        receipt['processCpuSamples'] = [sample.cpu_pct for sample in monitor._proc_samples]
    receipt['finishedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    receipt['passed'] = (
        receipt.get('exitCode') == 0 and not receipt.get('forcedCleanup')
        and receipt.get('metrics', {}).get('ffmpeg_sample_count', 0) >= 2
        and (receipt.get('metrics', {}).get('ffmpeg_cpu_util_avg') or 0) > 0
        and FFMPEG_PROCESS_WINDOW_SOURCE in (receipt.get('metrics', {}).get('telemetry_sources') or '')
    )
    (out / 'actual-ffmpeg.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({key: receipt[key] for key in ['sourceCommit', 'helperSha256', 'exitCode', 'passed', 'processCpuSamples', 'metrics']}, indent=2))
if not receipt['passed']:
    raise SystemExit(1)
