import hashlib
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from client import runtime_lock
from scripts import pyinstaller_locked_runtime as packaging
from scripts import release_manifest_lib as release


@pytest.fixture
def locked_runtime(tmp_path):
    data = {'bin/mac/ffmpeg': b'reviewed-ffmpeg', 'bin/mac/ffprobe': b'reviewed-ffprobe',
            'bin/mac/lib/codec.dylib': b'reviewed-codec'}
    records = {}
    for name, content in data.items():
        source = tmp_path/name
        source.parent.mkdir(parents=True,exist_ok=True)
        source.write_bytes(content)
        source.chmod(0o755)
        records[name] = {'relativePath':name,'sha256':hashlib.sha256(content).hexdigest(),'byteSize':len(content)}
    payload = {'schemaVersion':1,'runtimeId':'reviewed','source':'known-build','platforms':{'mac':{
        'ffmpeg':records['bin/mac/ffmpeg'],'ffprobe':records['bin/mac/ffprobe'],
        'runtimeDependencies':[{**records['bin/mac/lib/codec.dylib'],'relativePath':'lib/codec.dylib'}]}}}
    lock=tmp_path/'lock.json';lock.write_text(json.dumps(payload))
    return data,payload,lock


def test_only_locked_runtime_binaries_bypass_pyinstaller_rewriting(tmp_path,locked_runtime):
    data,_,lock=locked_runtime
    ordinary=('Python.framework/Python','python-lib','BINARY')
    analysis=SimpleNamespace(binaries=[ordinary]+[(name,str(tmp_path/name),'BINARY') for name in data],datas=[('notes','notes','DATA')])
    packaging.preserve_locked_runtime(analysis,str(lock),'mac')
    assert analysis.binaries == [ordinary]
    assert {(name,kind) for name,_,kind in analysis.datas if name in data} == {(name,'DATA') for name in data}
    assert all((tmp_path/name).read_bytes() == content for name,content in data.items())


def test_reclassification_refuses_unreviewed_source_bytes(tmp_path,locked_runtime):
    data,_,lock=locked_runtime
    (tmp_path/'bin/mac/lib/codec.dylib').write_bytes(b'changed-codec!')
    analysis=SimpleNamespace(binaries=[(name,str(tmp_path/name),'BINARY') for name in data],datas=[])
    with pytest.raises(ValueError,match='reviewed lock'):
        packaging.preserve_locked_runtime(analysis,str(lock),'mac')
    assert all(entry[2] == 'BINARY' for entry in analysis.binaries)


@pytest.mark.parametrize('change',['none','bytes','extra','missing','nonexecutable','lock'])
def test_archive_audit_checks_original_bytes_membership_and_executable_flag(tmp_path,locked_runtime,change):
    data,payload,lock=locked_runtime
    artifact=tmp_path/'candidate';artifact.write_bytes(b'archive')
    contents={**data,'resources/runtime/ffmpeg-lock.json':json.dumps(payload).encode()}
    toc={name:(0,0,len(value),1,'b') for name,value in contents.items()}
    if change == 'bytes': contents['bin/mac/lib/codec.dylib']=b'changed-codec!'
    if change == 'extra':
        contents['bin/mac/lib/extra.dylib']=b'unknown';toc['bin/mac/lib/extra.dylib']=(0,0,7,1,'b')
    if change == 'missing': del toc['bin/mac/ffprobe']
    if change == 'nonexecutable': toc['bin/mac/ffmpeg']=(0,0,15,1,'x')
    if change == 'lock':
        altered={**payload,'source':'unreviewed'}
        contents['resources/runtime/ffmpeg-lock.json']=json.dumps(altered).encode()
    reader=SimpleNamespace(toc=toc,extract=lambda name:contents[name])
    result=packaging.audit_archive(artifact,lock,'mac',reader)
    assert result['ok'] is (change == 'none')


def test_spec_patch_happens_after_analysis_before_package_processing(tmp_path):
    spec=tmp_path/'client.spec';spec.write_text('a = Analysis([])\npyz = PYZ(a.pure)\nexe = EXE(pyz, a.binaries, a.datas)')
    packaging.patch_spec(spec,tmp_path/'lock.json','mac')
    text=spec.read_text()
    assert text.index('a = Analysis') < text.index('preserve_locked_runtime(a,') < text.index('pyz = PYZ')
    with pytest.raises(ValueError,match='Unexpected'):
        packaging.patch_spec(spec,tmp_path/'lock.json','mac')


@pytest.mark.parametrize('external',[False,True])
def test_runtime_evidence_requires_actual_embedded_paths(tmp_path,external):
    root=tmp_path/'_MEIactual';root.mkdir()
    evidence=tmp_path/'runtime.json'
    result={'platform':'mac','ffmpegPath':str(root/'bin/mac/ffmpeg'),
            'ffprobePath':str((tmp_path/'external') if external else root/'bin/mac/ffprobe'),
            'lockPath':str(root/'resources/runtime/ffmpeg-lock.json'),'fingerprint':'verified','identity':{}}
    with mock.patch.dict(os.environ,{'ENCODINGDB_RUNTIME_EVIDENCE_PATH':str(evidence)}), mock.patch.object(runtime_lock.sys,'frozen',True,create=True), mock.patch.object(runtime_lock.sys,'_MEIPASS',str(root),create=True):
        if external:
            with pytest.raises(runtime_lock.RuntimeLockError,match='outside'):
                runtime_lock._write_embedded_runtime_evidence(result)
            assert not evidence.exists()
        else:
            runtime_lock._write_embedded_runtime_evidence(result)
            assert json.loads(evidence.read_text())['extractionRoot'] == str(root.resolve())


@pytest.mark.parametrize('receipt_kind',['embedded','external','absent'])
def test_smoke_strips_overrides_preserves_state_and_requires_embedded_proof(tmp_path,receipt_kind):
    artifact=tmp_path/'client';artifact.write_bytes(b'candidate')
    seen=[]
    def run(command,**kwargs):
        env=kwargs['env'];seen.append(env)
        if '--no-submit' in command and receipt_kind != 'absent':
            root=tmp_path/'_MEIsmoke'
            payload={'schemaVersion':1,'frozen':True,'extractionRoot':str(root),
                'ffmpegPath':str(root/'bin/mac/ffmpeg'),
                'ffprobePath':str((tmp_path/'external') if receipt_kind == 'external' else root/'bin/mac/ffprobe'),
                'lockPath':str(root/'resources/runtime/ffmpeg-lock.json')}
            Path(env['ENCODINGDB_RUNTIME_EVIDENCE_PATH']).write_text(json.dumps(payload))
        return subprocess.CompletedProcess(command,0,'ok','')
    overridden={'FFMPEG_EXE':'/unreviewed/ffmpeg','FFPROBE_EXE':'/unreviewed/ffprobe',
        'ENCODINGDB_RUNTIME_LOCK_PATH':'/unreviewed/lock','ENCODINGDB_FFMPEG_PATH':'/unreviewed/ffmpeg',
        'ENCODINGDB_FFPROBE_PATH':'/unreviewed/ffprobe','ENCODINGDB_RUNTIME_BUNDLE_DIR':'/unreviewed',
        'LD_LIBRARY_PATH':'/unreviewed','DYLD_LIBRARY_PATH':'/unreviewed','ENCODINGDB_STATE_DIR':'/shared-state'}
    with mock.patch.dict(os.environ,overridden), mock.patch.object(release,'ROOT_DIR',tmp_path), mock.patch.object(release.subprocess,'run',side_effect=run):
        args=dict(artifact_path=artifact,smoke_encoder='libx264',queue_dir=tmp_path/'queue',suite_cache_dir=tmp_path/'cache',suite_pack_path=tmp_path/'actual-pack.tar.gz')
        if receipt_kind == 'embedded': assert release.run_smoke_check(**args)['embeddedRuntime']['frozen']
        else:
            with pytest.raises(RuntimeError,match='embedded runtime identity'):
                release.run_smoke_check(**args)
        assert os.environ['FFMPEG_EXE'] == '/unreviewed/ffmpeg'
    for env in seen:
        assert env['ENCODINGDB_STATE_DIR'] == '/shared-state'
        assert env['ENCODINGDB_SUITE_PACK_PATH'] == str(tmp_path/'actual-pack.tar.gz')
        assert env['ENCODINGDB_SUITE_CACHE_DIR'] == str(tmp_path/'cache')
        assert not any(key in env for key in overridden if key != 'ENCODINGDB_STATE_DIR')
