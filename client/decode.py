from __future__ import annotations

import os
import re
import subprocess
import time
from typing import Any, Dict, List, Optional

from . import config


def build_ffmpeg_decode_cmd(*, input_path: str) -> List[str]:
    return [
        config.ffmpeg_exe(),
        "-v", "error",
        "-nostdin",
        "-nostats",
        "-benchmark",
        "-hwaccel", "none",
        "-threads:v", "1",
        "-threads", "1",
        "-progress", "pipe:1",
        "-i", input_path,
        "-map", "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-fps_mode", "passthrough",
        "-f", "null",
        "-",
    ]


def parse_decode_cpu_time(stderr: str) -> Optional[float]:
    text = str(stderr or "")
    match = re.search(
        r"bench:\s+utime=([0-9]+(?:\.[0-9]+)?)s\s+stime=([0-9]+(?:\.[0-9]+)?)s",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    try:
        return float(match.group(1)) + float(match.group(2))
    except Exception:
        return None


def _parse_progress_frame_count(progress_text: str) -> int:
    matches = re.findall(r"frame=\s*(\d+)", str(progress_text or ""))
    if not matches:
        return 0
    try:
        return int(matches[-1])
    except Exception:
        return 0


def explicit_decode_unsupported(*, reason: str, source_fps: Optional[float] = None) -> Dict[str, Any]:
    return {
        "supported": False,
        "reason": reason,
        "tool": "ffmpeg",
        "decoder": "software-default",
        "methodology": "ffmpeg-software-decode-v1",
        "cachePolicy": "single-pass-local-file-no-explicit-cache-flush",
        "sourceFps": source_fps,
        "decodeFps": None,
        "realtimeMultiple": None,
        "framesDecoded": None,
        "cpuTimeSeconds": None,
    }


def run_decode_benchmark(
    *,
    input_path: str,
    source_fps: Optional[float],
) -> Dict[str, Any]:
    if not input_path or not os.path.exists(input_path):
        return explicit_decode_unsupported(reason="artifact_missing", source_fps=source_fps)
    if not isinstance(source_fps, (int, float)) or float(source_fps) <= 0:
        return explicit_decode_unsupported(reason="source_fps_unavailable", source_fps=source_fps)

    cmd = build_ffmpeg_decode_cmd(input_path=input_path)
    start = time.perf_counter()
    proc = subprocess.run(
        cmd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    elapsed = max(0.0001, time.perf_counter() - start)
    frames_decoded = _parse_progress_frame_count(proc.stdout)
    if proc.returncode != 0 or frames_decoded <= 0:
        stderr_lines = [line.strip() for line in str(proc.stderr or "").splitlines() if line.strip()]
        reason = stderr_lines[-1] if stderr_lines else "decode_failed"
        return {
            **explicit_decode_unsupported(reason=reason[:200], source_fps=float(source_fps)),
            "returnCode": int(proc.returncode),
            "command": cmd,
        }

    decode_fps = float(frames_decoded) / elapsed
    return {
        "supported": True,
        "reason": None,
        "tool": "ffmpeg",
        "decoder": "software-default",
        "methodology": "ffmpeg-software-decode-v1",
        "cachePolicy": "single-pass-local-file-no-explicit-cache-flush",
        "command": cmd,
        "returnCode": int(proc.returncode),
        "sourceFps": float(source_fps),
        "framesDecoded": int(frames_decoded),
        "elapsedMs": int(round(elapsed * 1000.0)),
        "decodeFps": round(decode_fps, 6),
        "realtimeMultiple": round(decode_fps / float(source_fps), 6),
        "cpuTimeSeconds": parse_decode_cpu_time(proc.stderr),
    }
