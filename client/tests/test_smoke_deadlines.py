"""Bounded actual OS children; no media, builds, or external network."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest import mock

import psutil
import pytest
from scripts import release_manifest_lib as release


def run_child(tmp_path, code, preparation=0.5, measurement=0.5):
    queue = tmp_path / 'queue'
    queue.mkdir(exist_ok=True)
    return release._run_smoke_command([sys.executable, '-c', code], env=dict(os.environ),
        queue_dir=queue, stdout_path=tmp_path/'stdout', stderr_path=tmp_path/'stderr',
        acquisition_seconds=preparation, measurement_seconds=measurement)


def test_preparation_timeout_kills_actual_owned_descendant_and_preserves_output(tmp_path):
    code = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); print(p.pid,flush=True); time.sleep(30)"
    result = run_child(tmp_path, code)
    child_pid = int((tmp_path/'stdout').read_text().strip())
    assert result['timedOut'] and result['stageAtExit'] == 'preparation'
    assert result['cleanupForced'] and result['observedOwnedProcessCount'] >= 1
    assert result['survivingOwnedPids'] == []
    assert result['returnCode'] != 0
    try:
        assert not psutil.Process(child_pid).is_running() or psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        pass


def test_measurement_has_separate_bound_after_manifest(tmp_path):
    manifest = tmp_path/'queue'/'campaigns'/'campaign-test'/'manifest.json'
    code = f"from pathlib import Path; import time; p=Path({str(manifest)!r}); p.parent.mkdir(parents=True); p.write_text('{{}}'); time.sleep(30)"
    result = run_child(tmp_path, code, preparation=2, measurement=0.3)
    assert result['timedOut'] and result['stageAtExit'] == 'measurement'
    assert result['preparationSeconds'] is not None
    assert result['elapsedSeconds'] < 3
    assert result['survivingOwnedPids'] == []


def test_successful_process_keeps_zero_exit_and_no_forced_cleanup(tmp_path):
    result = run_child(tmp_path, "print('diagnostic')", preparation=2)
    assert result['returnCode'] == 0
    assert not result['timedOut'] and not result['cleanupForced']
    assert (tmp_path/'stdout').read_text().strip() == 'diagnostic'


def test_timeout_receipt_and_prior_journal_survive_smoke_failure(tmp_path):
    queue = tmp_path/'queue'
    (queue/'campaigns').mkdir(parents=True)
    (queue/'campaigns'/'retained.json').write_text('durable')
    def run(command, **kwargs):
        kwargs['stdout_path'].write_text('partial stdout')
        kwargs['stderr_path'].write_text('partial stderr')
        return dict(returnCode=0 if '--help' in command else -9, timedOut='--help' not in command,
                    cleanupForced='--help' not in command, survivingOwnedPids=[], stageAtExit='preparation')
    with mock.patch.object(release, 'ROOT_DIR', tmp_path), mock.patch.object(release, '_run_smoke_command', side_effect=run):
        with pytest.raises(RuntimeError, match='preparation'):
            release.run_smoke_check(artifact_path=tmp_path/'client', smoke_encoder='libx264', queue_dir=queue,
                                    suite_cache_dir=tmp_path/'cache', suite_pack_path=None)
    evidence = tmp_path/'.test-reports'/'native-smoke'/'client'
    commands = json.loads((evidence/'commands.json').read_text())
    assert commands[-1]['timedOut']
    assert '--max-duration-minutes' in commands[-1]['argv']
    assert (evidence/'no-submit-suite.stdout.log').read_text() == 'partial stdout'
    assert (evidence/'queue'/'campaigns'/'retained.json').read_text() == 'durable'


def test_windows_timeout_targets_owned_tree_before_wait_and_falls_back_on_taskkill_error():
    process = mock.Mock(pid=12345)
    process.poll.return_value = None
    with mock.patch.object(release.os, 'name', 'nt'), \
         mock.patch.object(release, '_smoke_children'), \
         mock.patch.object(release, '_smoke_survivors', return_value=[]), \
         mock.patch.object(release.psutil, 'wait_procs'), \
         mock.patch.object(release.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['taskkill'], 10)) as kill:
        assert release._stop_smoke_tree(process, {}) == []
    assert kill.call_args.args[0] == ['taskkill', '/PID', '12345', '/T', '/F']
    process.kill.assert_called_once()
    process.wait.assert_called_once_with(timeout=10)
