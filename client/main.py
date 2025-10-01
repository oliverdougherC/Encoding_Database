import json
import os
import platform
import re
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List

import psutil
import cpuinfo  # type: ignore

try:
    import GPUtil  # type: ignore
except Exception:
    GPUtil = None  # type: ignore

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:3001")
SUBMIT_URL = f"{BACKEND_URL}/submit"

@dataclass
class HardwareInfo:
    cpuModel: str
    gpuModel: Optional[str]
    ramGB: int
    os: str


def detect_hardware() -> HardwareInfo:
    cpu = cpuinfo.get_cpu_info()
    cpu_model = cpu.get("brand_raw") or cpu.get("brand") or platform.processor() or "Unknown CPU"

    gpu_model: Optional[str] = None
    if GPUtil is not None:
        try:
            gpus = GPUtil.getGPUs()
            if gpus:
                gpu_model = gpus[0].name
        except Exception:
            gpu_model = None

    ram_gb = int(round(psutil.virtual_memory().total / (1024 ** 3)))
    os_name = f"{platform.system()} {platform.release()}"
    return HardwareInfo(cpu_model, gpu_model, ram_gb, os_name)


def ensure_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def parse_ffmpeg_fps(output: str) -> Optional[float]:
    # ffmpeg often prints fps=XX or frame= with speed. We try common patterns
    m = re.search(r"fps=\s*([0-9]+(?:\.[0-9]+)?)", output)
    if m:
        return float(m.group(1))
    # Fallback: look for "frame= ... time=... speed=...x" then infer using duration
    return None


def run_ffmpeg_test(input_path: str, preset: str, codec: str = "libx264") -> Dict[str, Any]:
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, "out.mp4")
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", input_path,
            "-c:v", codec,
            "-preset", preset,
            "-an",
            out_path,
        ]
        start = time.time()
        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        end = time.time()
        elapsed = max(0.0001, end - start)
        # Count frames with ffprobe for accurate FPS
        try:
            probe = subprocess.run([
                "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                "-show_entries", "stream=nb_read_frames",
                "-of", "default=nokey=1:noprint_wrappers=1", out_path
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            nb_frames_str = (probe.stdout or "").strip()
            total_frames = int(nb_frames_str) if nb_frames_str.isdigit() else 0
        except Exception:
            total_frames = 0
        fps = (total_frames / elapsed) if total_frames > 0 else 0.0
        size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
        return {"fps": fps, "fileSizeBytes": size}


def compute_vmaf(input_path: str, encoded_path: str) -> Optional[float]:
    # Requires ffmpeg with libvmaf; try to run and parse VMAF score
    with tempfile.TemporaryDirectory() as td:
        # Use built-in model path resolution (ffmpeg ships default list)
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "info",
            "-i", input_path,
            "-i", encoded_path,
            "-lavfi", "libvmaf=log_fmt=json:log_path=-",
            "-f", "null", "-",
        ]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            out = proc.stdout
            m = re.search(r'"VMAF_score"\s*:\s*([0-9]+(?:\.[0-9]+)?)', out)
            if m:
                return float(m.group(1))
        except Exception:
            return None
    return None


def run_single_benchmark(hardware: HardwareInfo, input_path: str, preset: str, codec: str = "libx264") -> Dict[str, Any]:
    result = run_ffmpeg_test(input_path, preset=preset, codec=codec)
    # For VMAF, we need the encoded output; re-run to keep artifact
    with tempfile.TemporaryDirectory() as td:
        encoded_path = os.path.join(td, "out.mp4")
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", input_path,
            "-c:v", codec,
            "-preset", preset,
            "-an",
            encoded_path,
        ]
        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        vmaf = compute_vmaf(input_path, encoded_path)
    payload = {
        "cpuModel": hardware.cpuModel,
        "gpuModel": hardware.gpuModel,
        "ramGB": hardware.ramGB,
        "os": hardware.os,
        "codec": codec,
        "preset": preset,
        "fps": float(result["fps"]),
        "fileSizeBytes": int(result["fileSizeBytes"]),
    }
    if vmaf is not None:
        payload["vmaf"] = float(vmaf)
    return payload


def submit(payload: Dict[str, Any]) -> None:
    import requests  # lazy import to speed cold start
    r = requests.post(SUBMIT_URL, json=payload, timeout=30)
    r.raise_for_status()


def main(argv: List[str]) -> int:
    if not ensure_ffmpeg():
        print("ffmpeg not found in PATH. Please install ffmpeg.", file=sys.stderr)
        return 2
    if len(argv) < 2:
        print("Usage: python main.py <path_to_test_video>")
        return 1
    input_path = argv[1]
    if not os.path.exists(input_path):
        print(f"Input not found: {input_path}", file=sys.stderr)
        return 3

    hardware = detect_hardware()
    presets = ["fast", "medium", "slow"]
    codec = "libx264"

    all_payloads: List[Dict[str, Any]] = []
    for preset in presets:
        print(f"Running preset: {preset}...")
        payload = run_single_benchmark(hardware, input_path, preset=preset, codec=codec)
        all_payloads.append(payload)
        try:
            submit(payload)
            print(f"Submitted: {preset}")
        except Exception as e:
            print(f"Failed to submit {preset}: {e}", file=sys.stderr)
    print(json.dumps(all_payloads, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
