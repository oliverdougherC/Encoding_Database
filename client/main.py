import argparse
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple

import psutil
import cpuinfo  # type: ignore

try:
    import GPUtil  # type: ignore
except Exception:
    GPUtil = None  # type: ignore

# Configuration via environment with sensible defaults
ENV_BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:3001")
ENV_API_KEY = os.environ.get("API_KEY", "")
ENV_PRESETS = os.environ.get("PRESETS", "fast,medium,slow")
ENV_CODEC = os.environ.get("CODEC", "libx264")
ENV_DISABLE_VMAF = os.environ.get("DISABLE_VMAF", "0") in ("1", "true", "TRUE")

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


def exec_ok(cmd: List[str]) -> bool:
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def ensure_ffmpeg_and_ffprobe() -> Tuple[bool, Optional[str]]:
    if not exec_ok(["ffmpeg", "-version"]) or not exec_ok(["ffprobe", "-version"]):
        return False, None
    try:
        out = subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        version_line = (out.stdout or "").splitlines()[0] if out.stdout else ""
    except Exception:
        version_line = ""
    return True, version_line


def has_encoder(encoder: str) -> bool:
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        return encoder in (out.stdout or "")
    except Exception:
        return False


def has_libvmaf() -> bool:
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        return "libvmaf" in (out.stdout or "")
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
        proc = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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
        return {"fps": fps, "fileSizeBytes": size, "_encode_rc": proc.returncode}


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


def run_single_benchmark(hardware: HardwareInfo, input_path: str, preset: str, codec: str = "libx264", enable_vmaf: bool = True) -> Dict[str, Any]:
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
        vmaf = compute_vmaf(input_path, encoded_path) if enable_vmaf and has_libvmaf() else None
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


def submit(base_url: str, payload: Dict[str, Any], api_key: str = "", retries: int = 3, backoff_seconds: float = 1.0) -> None:
    import requests  # lazy import
    url = f"{base_url.rstrip('/')}/submit"
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=30, headers=headers)
            if r.status_code >= 500:
                raise RuntimeError(f"server_error {r.status_code}")
            r.raise_for_status()
            return
        except Exception as e:
            if attempt == retries:
                raise
            time.sleep(backoff_seconds * attempt)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Encoding Benchmark Client")
    p.add_argument("input", help="Path to input test video (e.g., sample.mp4)")
    p.add_argument("--base-url", default=ENV_BACKEND_URL, help="Backend base URL (default: env BACKEND_URL or http://localhost:3001)")
    p.add_argument("--api-key", default=ENV_API_KEY, help="API key for submission (default: env API_KEY)")
    p.add_argument("--codec", default=ENV_CODEC, help="FFmpeg video encoder (e.g., libx264, libx265)")
    p.add_argument("--presets", default=ENV_PRESETS, help="Comma-separated list of presets (default: fast,medium,slow)")
    p.add_argument("--no-submit", action="store_true", help="Run tests but do not submit results")
    p.add_argument("--disable-vmaf", action="store_true", default=ENV_DISABLE_VMAF, help="Skip VMAF computation")
    p.add_argument("--retries", type=int, default=3, help="Submission retry attempts (default: 3)")
    return p


def main(argv: List[str]) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv[1:])

    ok, ffmpeg_version = ensure_ffmpeg_and_ffprobe()
    if not ok:
        print("ffmpeg/ffprobe not found in PATH. Please install ffmpeg.", file=sys.stderr)
        return 2
    print(f"ffmpeg detected: {ffmpeg_version or 'unknown'}")

    input_path = args.input
    if not os.path.exists(input_path):
        print(f"Input not found: {input_path}", file=sys.stderr)
        return 3

    if not has_encoder(args.codec):
        print(f"Requested encoder '{args.codec}' not available in this ffmpeg build.", file=sys.stderr)
        return 4

    hardware = detect_hardware()
    try:
        presets = [s.strip() for s in args.presets.split(",") if s.strip()]
    except Exception:
        presets = ["fast", "medium", "slow"]

    all_payloads: List[Dict[str, Any]] = []
    for preset in presets:
        print(f"Running preset: {preset}...")
        payload = run_single_benchmark(hardware, input_path, preset=preset, codec=args.codec, enable_vmaf=(not args.disable_vmaf))
        all_payloads.append(payload)
        if args.no_submit:
            print(f"Dry-run: not submitting preset={preset}")
            continue
        try:
            submit(args.base_url, payload, api_key=args.api_key, retries=max(1, args.retries))
            print(f"Submitted: {preset}")
        except Exception as e:
            print(f"Failed to submit {preset}: {e}", file=sys.stderr)
    print(json.dumps(all_payloads, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
