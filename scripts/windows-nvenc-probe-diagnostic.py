#!/usr/bin/env python3
"""Retain stderr for native usability diagnostics; never campaign/fitting data."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--root',type=Path,required=True)
a=p.parse_args()
root=a.root.resolve(strict=True)
output=root/'nvenc-probe-diagnostic'
output.mkdir(exist_ok=False)
ffmpeg=root/'runtime-939823e/ffmpeg-n8.1.2-51-g7ba069f4f1-win64-gpl-8.1/bin/ffmpeg.exe'
h=hashlib.sha256(ffmpeg.read_bytes()).hexdigest()
if h!='b74bd2209fe38026ae9f73ad676e626599bdc1efd950fe32d40b23184fb1a060':raise ValueError('Pinned helper mismatch')
receipt={'scope':'Synthetic hardware usability diagnosis only; not timing, acceptance or fitting evidence','ffmpegSha256':h,'probes':[]}
for name,size,extra in [('original-128','128x128',[]),('size-only-1080','1920x1080',[]),('device0-1080','1920x1080',['-gpu','0','-preset','p4','-rc','vbr','-cq','24','-b:v','0'])]:
 argv=[str(ffmpeg),'-y','-hide_banner','-loglevel','error','-f','lavfi','-i',f'testsrc=size={size}:rate=30','-frames:v','8','-pix_fmt','yuv420p','-c:v','h264_nvenc',*extra,'-an',str(output/(name+'.mp4'))]
 start=time.monotonic()
 try:
  result=subprocess.run(argv,capture_output=True,timeout=8)
  item={'name':name,'argv':argv,'exitCode':result.returncode,'elapsedSeconds':time.monotonic()-start,'timeout':False,'stdout':result.stdout.decode('utf-8','replace'),'stderr':result.stderr.decode('utf-8','replace')}
 except subprocess.TimeoutExpired as e:
  item={'name':name,'argv':argv,'elapsedSeconds':time.monotonic()-start,'timeout':True,'stdout':(e.stdout or b'').decode('utf-8','replace'),'stderr':(e.stderr or b'').decode('utf-8','replace')}
 receipt['probes'].append(item)
 (output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
 print(json.dumps(item))
