"""Dependency-free media evidence shared by packaged-client verification tests."""

from __future__ import annotations

import subprocess
from typing import Callable, Dict, Optional


def probe_video_packet_evidence(
    path: str,
    ffprobe_exe: str = "ffprobe",
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Dict[str, Optional[int]]:
    """Return the exact v:0 packet-size sum used for canonical bitrate evidence."""
    proc = runner(
        [
            ffprobe_exe,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "packet=size",
            "-of", "csv=p=0",
            path,
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    total = 0
    count = 0
    for raw_line in (proc.stdout or "").splitlines():
        value = raw_line.strip().split(",", 1)[0]
        try:
            size = int(value)
        except (TypeError, ValueError):
            continue
        if size < 0:
            continue
        total += size
        count += 1
    return {
        "videoPayloadBytes": total if count > 0 and total > 0 else None,
        "videoPacketCount": count if count > 0 else None,
    }
