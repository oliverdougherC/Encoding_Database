"""Windows console-window policy for children spawned by the packaged client.

The Windows GUI is a windowed (no-console) PyInstaller executable. When a
no-console parent spawns a console-subsystem child (ffmpeg, ffprobe,
powershell, nvidia-smi, taskkill) with default CreateProcess flags, Windows
allocates a fresh console for that child and the default terminal app shows
it, hiding the GUI behind a blank terminal window for the child's whole
lifetime. Microsoft's documented CreateProcess flag CREATE_NO_WINDOW
(0x08000000, "Process Creation Flags") creates the process without a console
and additionally suppresses the console-window flash at launch.

Piped stdio, return codes, process ownership, cancellation and every
timing boundary are untouched: only the console-allocation behavior of the
spawn changes, and only on Windows. On POSIX the mapping is empty, so the
spawn call stays exactly as it was.
"""

import os
import subprocess

# subprocess.CREATE_NO_WINDOW only exists on Windows; the literal is the
# documented CREATE_NO_WINDOW value and is used solely when a test forces the
# Windows branch on another platform. Never monkeypatch os.name globally.
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

_WINDOWS = os.name == "nt"


def hidden_console_kwargs() -> dict:
    """Return subprocess kwargs that keep a console-subsystem child windowless.

    Empty mapping on POSIX. Tests select the Windows branch by patching the
    module-level ``_WINDOWS`` flag, which is local to this module and cannot
    disturb ``pathlib`` or any other consumer of ``os.name``.
    """
    if _WINDOWS:
        return {"creationflags": _CREATE_NO_WINDOW}
    return {}
