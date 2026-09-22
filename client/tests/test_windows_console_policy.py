"""Windows helper-console policy regressions (own-window/own-process evidence).

The native acceptance evidence (gui-evidence-20260921-175802 events.jsonl)
showed conhost.exe children of ffmpeg.exe/powershell.exe/nvidia-smi.exe
directly under the packaged GUI pid, i.e. the windowed client allocated a
console per console-subsystem child. These tests pin the CREATE_NO_WINDOW
spawn policy on the Windows branch and prove the POSIX branch of every
touched spawn boundary is byte-for-byte the old call (no creationflags,
start_new_session ownership and pipes unchanged). The Windows branch is
selected through the module-local console_policy._WINDOWS flag or a
module-local ``os`` rebinding; os.name itself is never patched globally.
"""

import os
import subprocess
import sys
from types import SimpleNamespace
from unittest import mock

import pytest

from client import console_policy, decode, encoders, ffmpeg, hardware_monitor, identity, suite
from client import campaign
from client.campaign import MeasurementBudget

CREATE_NO_WINDOW = 0x08000000


def test_helper_emits_documented_flag_only_on_the_windows_branch():
    with mock.patch.object(console_policy, "_WINDOWS", True):
        kwargs = console_policy.hidden_console_kwargs()
    assert kwargs == {"creationflags": CREATE_NO_WINDOW}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):  # on Windows this is the subprocess constant
        assert kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW
    with mock.patch.object(console_policy, "_WINDOWS", False):
        assert console_policy.hidden_console_kwargs() == {}


def test_monitored_encode_on_windows_allocates_no_console_and_keeps_ownership_semantics():
    captured = {}

    class Process:
        pid = 42460
        returncode = 0

        def __init__(self, cmd, **kwargs):
            captured.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def communicate(self, timeout=None):
            return "frame=1", ""

    monitor = SimpleNamespace(start=lambda: None, stop=lambda: SimpleNamespace())
    # Module-local os rebinding: the nt branch only needs os.name here.
    with mock.patch.object(ffmpeg, "HardwareMonitor", lambda **kw: monitor), \
            mock.patch.object(ffmpeg, "os", SimpleNamespace(name="nt", path=os.path)), \
            mock.patch.object(console_policy, "_WINDOWS", True), \
            mock.patch.object(ffmpeg.subprocess, "Popen", Process):
        stdout, stderr, returncode, elapsed, metrics = ffmpeg._run_monitored(
            ["ffmpeg", "out.mp4"], encoder_name="libx264")
    assert returncode == 0 and stdout == "frame=1"
    assert captured["creationflags"] == CREATE_NO_WINDOW          # no helper console window
    assert captured["start_new_session"] is False                 # POSIX group ownership did not leak in
    assert captured["stdout"] is subprocess.PIPE and captured["stderr"] is subprocess.PIPE
    assert captured["text"] is True                               # progress parsing unchanged
    assert metrics.encode_end_monotonic_ns >= metrics.encode_start_monotonic_ns


def test_posix_monitored_launch_carries_no_creationflags_and_keeps_group_and_pipes():
    captured = {}
    real = subprocess.Popen

    def spy(cmd, **kwargs):
        captured.update(kwargs)
        return real(cmd, **kwargs)

    command = [sys.executable, "-c", 'print("frame=24")']
    monitor = SimpleNamespace(start=lambda: None, stop=lambda: SimpleNamespace())
    with mock.patch.object(ffmpeg, "HardwareMonitor", return_value=monitor), \
            mock.patch.object(ffmpeg.subprocess, "Popen", spy):
        stdout, stderr, returncode, elapsed, metrics = ffmpeg._run_monitored(command, encoder_name="libx264")
    assert returncode == 0 and stdout.strip() == "frame=24"
    assert "creationflags" not in captured                        # POSIX spawn is exactly the old call
    assert captured.get("start_new_session") is True              # kill-group ownership retained


def test_measurement_wrapper_policy_applies_to_direct_run_and_budgeted_popen_paths():
    seen = {}

    class Process:
        returncode = 0

        def __init__(self, cmd, **kwargs):
            seen.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def communicate(self, timeout=None):
            return "ok", ""

    def fake_run(cmd, **kwargs):
        seen.clear()
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    for windows in (True, False):
        for budgeted in (False, True):
            seen.clear()
            with mock.patch.object(console_policy, "_WINDOWS", windows), \
                    mock.patch.object(campaign.subprocess, "run", fake_run), \
                    mock.patch.object(campaign.subprocess, "Popen", Process):
                if budgeted:
                    with MeasurementBudget(minutes=1).activate():
                        result = campaign.run_measurement_process(
                            ["ffprobe"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
                else:
                    result = campaign.run_measurement_process(
                        ["ffprobe"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            assert (result.stdout, result.returncode) == ("ok", 0)  # CompletedProcess contract intact
            assert ("creationflags" in seen) is windows
            if windows:
                assert seen["creationflags"] == CREATE_NO_WINDOW
            elif not budgeted:
                assert "start_new_session" not in seen              # direct run path: POSIX call unchanged


def test_measurement_wrapper_posix_path_still_sets_process_group_ownership():
    seen = {}

    class Process:
        returncode = 0

        def __init__(self, cmd, **kwargs):
            seen.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def communicate(self, timeout=None):
            return "", ""

    with mock.patch.object(campaign.subprocess, "Popen", Process):
        with MeasurementBudget(minutes=1).activate():
            campaign.run_measurement_process(["ffprobe"], stdout=subprocess.PIPE)
    assert seen.get("start_new_session") is True
    assert "creationflags" not in seen


def test_owned_process_termination_taskkill_is_windowless_and_still_reaps():
    dispatch = []
    reaped = []

    def fake_run(cmd, **kwargs):
        dispatch.append((cmd, kwargs))
        return SimpleNamespace(returncode=0)

    proc = SimpleNamespace(pid=4321, poll=lambda: None, kill=lambda: None,
                           communicate=lambda timeout=None: reaped.append(timeout) or ("", ""))
    with mock.patch.object(ffmpeg, "os", SimpleNamespace(name="nt", path=os.path)), \
            mock.patch.object(console_policy, "_WINDOWS", True), \
            mock.patch.object(ffmpeg.subprocess, "run", fake_run):
        ffmpeg._terminate_owned_process(proc)
    cmd, kwargs = dispatch[0]
    assert cmd == ["taskkill", "/PID", "4321", "/T", "/F"]        # tree reaping receipt unchanged
    assert kwargs["creationflags"] == CREATE_NO_WINDOW            # cancel path never pops a terminal
    assert reaped == [5]                                          # communicate-based reap still performed


@pytest.mark.parametrize("module,launch", [
    (identity, lambda tmp: identity._command(["nvidia-smi", "--id=0"])),
    (encoders, lambda tmp: encoders.exec_ok(["ffmpeg", "-version"])),
    (hardware_monitor, lambda tmp: hardware_monitor._run_command(["powershell", "-NoProfile"], timeout=1.0)),
    (ffmpeg, lambda tmp: ffmpeg.get_ffmpeg_banner(force_refresh=True)),
    (decode, lambda tmp: decode.run_decode_benchmark(input_path=str(tmp / "in.mp4"), source_fps=24.0)),
    (suite, lambda tmp: suite._generate_clip("testsrc", str(tmp / "clip" / "c.mp4"), 8)),
])
def test_helper_probe_spawns_inherit_console_policy(module, launch, tmp_path):
    (tmp_path / "in.mp4").write_bytes(b"placeholder")
    seen = {}

    def fake_run(cmd, *args, **kwargs):
        seen.clear()
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "ffmpeg version test", "")

    for windows in (True, False):
        with mock.patch.object(console_policy, "_WINDOWS", windows), \
                mock.patch.object(module.subprocess, "run", fake_run):
            launch(tmp_path)
        if windows:
            assert "creationflags" in seen, f"{module.__name__} probe never forwarded the console policy"
            assert seen["creationflags"] == CREATE_NO_WINDOW
        else:
            assert "creationflags" not in seen                      # POSIX call is byte-for-byte the old one
