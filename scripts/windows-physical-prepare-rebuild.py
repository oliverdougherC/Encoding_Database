#!/usr/bin/env python3
"""Stage a newly reviewed source in isolated paths using existing pinned inputs."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys


_spec = importlib.util.spec_from_file_location('physical_prepare_operator', Path(__file__).with_name('windows-physical-acceptance.py'))
operator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(operator)


def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--revision',required=True)
    p.add_argument('--tree',required=True)
    p.add_argument('--label',required=True)
    a=p.parse_args()
    if os.name!='nt' or not re.fullmatch('[0-9a-f]{40}',a.revision) or not re.fullmatch('[0-9a-f]{40}',a.tree) or not re.fullmatch('[a-z0-9-]{1,40}',a.label):
        p.error('Actual Windows, exact reviewed revision/tree and bounded ASCII label required')
    root=a.root.resolve(strict=True)
    source=root/('source-'+a.label)
    receipt_path=root/('physical-prepare-'+a.label+'-receipt.json')
    log_path=root/('physical-prepare-'+a.label+'.log')
    if source.exists() or receipt_path.exists() or log_path.exists():raise ValueError('Create-only preparation already exists')
    with operator.host_lock(root/'host-state'):
        identity=(root/'host-state/physical-source-id').read_text().strip()
        if identity!='installation-9e7cd0a8c6158d19d179f0acf79249c6c790b988b8a48f6563952c1c00acca29':raise ValueError('Physical installation identity changed')
        bins=root/'runtime-939823e/ffmpeg-n8.1.2-51-g7ba069f4f1-win64-gpl-8.1/bin'
        pack=root/'source-939823e/encodingdb-test-suite-v1.tar.gz'
        if sha(root/'runtime-939823e/ffmpeg-win.zip')!='4e40699fa864811312d6c1895ea4873beaf8475e1188563fee57fac860554601':raise ValueError('Runtime archive changed')
        if sha(pack)!='d20407f8d78f152f06c3b7271881d8b3f07d2b76cf3a2642b241162d666ac150':raise ValueError('Canonical pack changed')
        receipt={'schemaVersion':1,'status':'RUNNING','startedAt':datetime.now(timezone.utc).isoformat(),'requestedSource':a.revision,'reviewedTree':a.tree,'installationId':identity,'commands':[]}
        def save():receipt_path.write_text(json.dumps(receipt,indent=2)+'\n')
        env=os.environ.copy()
        for key in list(env):
            if key.startswith(('ENCODINGDB_','V7_OPERATOR_','DYLD_')) or key in ('FFMPEG_EXE','FFPROBE_EXE','PYTHONPATH','PYTHONHOME','LD_LIBRARY_PATH'):del env[key]
        env.update(ENCODINGDB_FFMPEG_PATH=str(bins/'ffmpeg.exe'),ENCODINGDB_FFPROBE_PATH=str(bins/'ffprobe.exe'),FFMPEG_EXE=str(bins/'ffmpeg.exe'),FFPROBE_EXE=str(bins/'ffprobe.exe'),ENCODINGDB_STATE_DIR=str(root/'host-state'),ENCODINGDB_SUITE_CACHE_DIR=str(root/'suite-cache'))
        save()
        try:
            with log_path.open('x',encoding='utf-8') as log:
                def run(argv,cwd=root):
                    argv=list(map(str,argv)); item={'argv':argv,'cwd':str(cwd),'startedAt':datetime.now(timezone.utc).isoformat()};receipt['commands'].append(item);save()
                    print('PHYSICAL_PREPARE: '+' '.join(argv),flush=True)
                    result=subprocess.run(argv,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT)
                    item.update(exitCode=result.returncode,finishedAt=datetime.now(timezone.utc).isoformat());save()
                    if result.returncode:raise RuntimeError('Preparation command failed with exit '+str(result.returncode))
                run(['git','init',source]);run(['git','-C',source,'config','core.autocrlf','false'])
                run(['git','-C',source,'remote','add','origin','https://github.com/oliverdougherC/Encoding_Database.git'])
                run(['git','-C',source,'fetch','--depth','1','origin',a.revision]);run(['git','-C',source,'checkout','--detach','FETCH_HEAD'])
                if subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()!=a.revision:raise ValueError('Source revision differs')
                if subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD^{tree}'],text=True).strip()!=a.tree:raise ValueError('Source tree differs')
                bootstrap=root/'bootstrap-venv-939823e/Scripts/python.exe'
                run([bootstrap,source/'scripts/materialize_final_suite.py','--pack-path',pack,'--cache-dir',root/'suite-cache'],source)
                run([bootstrap,source/'scripts/verify_runtime_model.py'],source)
                build=source/'.build/clients/windows'
                for name in ['dist','work','spec','runtime_resources','suite_resources']:(build/name).mkdir(parents=True,exist_ok=True)
                run([sys.executable,'-m','venv',build/'venv'],source)
                python=build/'venv/Scripts/python.exe'
                run([python,'-m','pip','install','--disable-pip-version-check','-r',source/'client/requirements-build.txt'],source)
                run([python,source/'scripts/register_ffmpeg_runtime.py','--platform','win','--ffmpeg-path',bins/'ffmpeg.exe','--ffprobe-path',bins/'ffprobe.exe','--lock-path',source/'client/resources/runtime/ffmpeg-lock.json','--stage-runtime-dir',build/'runtime_resources'],source)
                run([python,source/'scripts/prepare_client_suite_distribution.py','--staged-resource-dir',build/'suite_resources/test_suite_v1','--pack-out',source/'encodingdb-test-suite-v1.tar.gz'],source)
                run([python,source/'scripts/verify_suite_assets.py',source/'client/resources/test_suite_v1'],source)
            receipt['trackedStatus']=subprocess.check_output(['git','-C',str(source),'status','--porcelain','--untracked-files=no'],text=True).strip()
            if receipt['trackedStatus']:raise ValueError('Tracked source changed')
            if (root/'host-state/physical-source-id').read_text().strip()!=identity:raise ValueError('Installation identity changed')
            receipt['status']='PREPARED'
        except BaseException as error:
            receipt['status']='FAILED';receipt['error']=str(error);raise
        finally:
            receipt['finishedAt']=datetime.now(timezone.utc).isoformat();save();print(json.dumps({'status':receipt['status'],'receipt':str(receipt_path)}),flush=True)


if __name__=='__main__':main()
