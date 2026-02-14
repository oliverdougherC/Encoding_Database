import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, Any, List

from . import config
from .encoders import (
    map_preset_for_encoder, pick_software_encoder_for_family,
    has_encoder,
)


def build_ffmpeg_encode_cmd(*, input_path: str, output_path: str, encoder: str, preset_name: str, crf: Optional[int] = None) -> List[str]:
    cmd: List[str] = [
        config.ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", input_path,
        "-c:v", encoder,
    ]
    cmd += map_preset_for_encoder(encoder, preset_name)
    if crf is not None:
        e = encoder.strip().lower()
        if e in ("libx264", "libx265", "libsvtav1", "libaom-av1", "libvpx-vp9"):
            cmd += ["-crf", str(crf)]
        elif e.endswith("_nvenc"):
            cmd += ["-cq", str(max(0, min(51, crf)))]
    if encoder.endswith(("_nvenc", "_qsv", "_amf", "_videotoolbox", "_vaapi")):
        cmd += ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p"]
    e = encoder.strip().lower()
    if e.endswith("_videotoolbox"):
        cmd += ["-allow_sw", "1"]
    if e == "h264_videotoolbox":
        cmd += ["-b:v", "5000k", "-profile:v", "high", "-g", "120"]
    elif e == "hevc_videotoolbox":
        cmd += ["-b:v", "5000k", "-tag:v", "hvc1"]
    elif e == "av1_videotoolbox":
        cmd += ["-b:v", "5000k"]
    cmd += ["-an", output_path]
    return cmd


def run_ffmpeg_test(input_path: str, preset: str, codec: str = "libx264", crf: Optional[int] = None) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, "out.mp4")
        cmd = build_ffmpeg_encode_cmd(input_path=input_path, output_path=out_path, encoder=codec, preset_name=preset, crf=crf)
        start = time.time()
        proc = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        end = time.time()
        elapsed = max(0.0001, end - start)
        try:
            probe = subprocess.run([
                config.ffprobe_exe(), "-v", "error", "-count_frames", "-select_streams", "v:0",
                "-show_entries", "stream=nb_read_frames",
                "-of", "default=nokey=1:noprint_wrappers=1", out_path
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            nb_frames_str = (probe.stdout or "").strip()
            total_frames = int(nb_frames_str) if nb_frames_str.isdigit() else 0
        except Exception:
            total_frames = 0
        fps = (total_frames / elapsed) if total_frames > 0 else 0.0
        size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
        result: Dict[str, Any] = {"fps": fps, "fileSizeBytes": size, "_encode_rc": proc.returncode, "elapsedMs": int(round(elapsed * 1000))}
        if proc.returncode != 0 or size == 0 or fps == 0.0:
            stderr_lines = (proc.stderr or "").splitlines()
            brief = "; ".join([ln.strip() for ln in stderr_lines[-5:]]) if stderr_lines else "ffmpeg failed"
            print(f"ffmpeg error (preset={preset}, codec={codec}): {brief}", file=sys.stderr)
            result["_error"] = brief
        return result


def compute_vmaf(input_path: str, encoded_path: str) -> Optional[float]:
    filter_candidates: List[str] = []
    filter_candidates.append("libvmaf=model=version=vmaf_v0.6.1:log_fmt=json:log_path=-")
    filter_candidates.append("libvmaf=log_fmt=json:log_path=-")
    common_paths = [
        "/opt/homebrew/opt/libvmaf/share/model/vmaf_v0.6.1.json",
        "/usr/local/opt/libvmaf/share/model/vmaf_v0.6.1.json",
        "/usr/local/share/model/vmaf_v0.6.1.json",
        "/usr/share/model/vmaf_v0.6.1.json",
    ]
    for p in common_paths:
        if os.path.exists(p):
            filter_candidates.append(f"libvmaf=model_path={p}:log_fmt=json:log_path=-")

    for filt in filter_candidates:
        cmd = [
            config.ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "info",
            "-i", input_path,
            "-i", encoded_path,
            "-lavfi", filt,
            "-f", "null", "-",
        ]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            out = proc.stdout
            m = re.search(r'"VMAF_score"\s*:\s*([0-9]+(?:\.[0-9]+)?)', out)
            if not m:
                m = re.search(r'"aggregate"[\s\S]*?"mean"\s*:\s*([0-9]+(?:\.[0-9]+)?)', out)
            if not m:
                m = re.search(r'"vmaf"\s*:\s*([0-9]+(?:\.[0-9]+)?)', out)
            if not m:
                m = re.search(r'VMAF\s+score\s*:\s*([0-9]+(?:\.[0-9]+)?)', out, re.IGNORECASE)
            if m:
                return float(m.group(1))
        except Exception:
            continue
    return None


def _encoder_family_for(encoder: str) -> Optional[str]:
    e = (encoder or '').lower()
    if 'h264' in e:
        return 'h264'
    if 'hevc' in e or 'h265' in e:
        return 'hevc'
    if 'av1' in e:
        return 'av1'
    if 'vp9' in e:
        return 'vp9'
    return None


def encode_to_artifact(*, input_path: str, encoder: str, preset: str, crf: Optional[int], out_dir: str, artifact_name: str) -> Dict[str, Any]:
    os.makedirs(out_dir, exist_ok=True)
    artifact_path = os.path.join(out_dir, artifact_name)
    cmd = build_ffmpeg_encode_cmd(input_path=input_path, output_path=artifact_path, encoder=encoder, preset_name=preset, crf=crf)
    start = time.time()
    proc = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    end = time.time()
    elapsed = max(0.0001, end - start)
    original_encoder = encoder
    if (proc.returncode != 0 or not os.path.exists(artifact_path) or os.path.getsize(artifact_path) <= 0):
        family = _encoder_family_for(encoder)
        if family:
            sw = pick_software_encoder_for_family(family)
            if sw and sw != encoder and has_encoder(sw):
                try:
                    print(f"  Hardware encoder '{encoder}' failed, falling back to software encoder '{sw}'...")
                    cmd_sw = build_ffmpeg_encode_cmd(input_path=input_path, output_path=artifact_path, encoder=sw, preset_name=preset, crf=crf)
                    start = time.time()
                    proc = subprocess.run(cmd_sw, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    end = time.time()
                    elapsed = max(0.0001, end - start)
                    encoder = sw
                    if proc.returncode == 0 and os.path.exists(artifact_path) and os.path.getsize(artifact_path) > 0:
                        print(f"  Software encoder '{sw}' succeeded.")
                    else:
                        print(f"  Software encoder '{sw}' also failed.", file=sys.stderr)
                except Exception as e:
                    print(f"  Fallback to software encoder failed: {e}", file=sys.stderr)
    try:
        probe = subprocess.run([
            config.ffprobe_exe(), '-v', 'error', '-count_frames', '-select_streams', 'v:0',
            '-show_entries', 'stream=nb_read_frames',
            '-of', 'default=nokey=1:noprint_wrappers=1', artifact_path
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        nb_frames_str = (probe.stdout or '').strip()
        total_frames = int(nb_frames_str) if nb_frames_str.isdigit() else 0
    except Exception:
        total_frames = 0
    fps_val = (total_frames / elapsed) if total_frames > 0 else 0.0
    size_val = os.path.getsize(artifact_path) if os.path.exists(artifact_path) else 0
    err_msg: Optional[str] = None
    if proc.returncode != 0 or size_val <= 0 or fps_val <= 0.0:
        stderr_lines = (proc.stderr or '').splitlines()
        err_msg = '; '.join([ln.strip() for ln in stderr_lines[-5:]]) if stderr_lines else 'ffmpeg failed'
    return {
        'artifactPath': artifact_path,
        'encoderUsed': encoder,
        'elapsedMs': int(round(elapsed * 1000)),
        'fps': float(fps_val),
        'fileSizeBytes': int(size_val),
        'error': err_msg,
    }


def compute_vmaf_parallel(input_path: str, artifacts: List[str], workers: int) -> Dict[str, Optional[float]]:
    results: Dict[str, Optional[float]] = {}
    if not artifacts:
        return results
    total = len(artifacts)
    done = 0
    print(f"Starting parallel VMAF for {total} item(s) with {max(1, workers)} worker(s)...")
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(compute_vmaf, input_path, ap): ap for ap in artifacts}
        for fut in as_completed(futs):
            ap = futs[fut]
            try:
                results[ap] = fut.result()
            except Exception:
                results[ap] = None
            done += 1
            try:
                pct = (done / total) * 100.0
            except Exception:
                pct = 100.0
            print(f"VMAF progress: {done}/{total} ({pct:.0f}%)")
    print("VMAF batch complete.")
    return results


def run_single_benchmark(hardware: config.HardwareInfo, input_path: str, preset: str, codec: str = "libx264", crf: Optional[int] = None) -> Dict[str, Any]:
    result = run_ffmpeg_test(input_path, preset=preset, codec=codec, crf=crf)
    if (result.get("_encode_rc", 1) != 0 or float(result.get("fps", 0.0)) <= 0 or int(result.get("fileSizeBytes", 0)) <= 0):
        family = None
        if codec.endswith("_videotoolbox"):
            family = "h264" if "h264" in codec else ("hevc" if "hevc" in codec else ("av1" if "av1" in codec else None))
        elif codec.endswith(('_nvenc', '_qsv', '_amf', '_vaapi')):
            if 'h264' in codec:
                family = 'h264'
            elif 'hevc' in codec:
                family = 'hevc'
            elif 'av1' in codec:
                family = 'av1'
            elif 'vp9' in codec:
                family = 'vp9'
        if family:
            sw = pick_software_encoder_for_family(family)
            if sw and sw != codec:
                print(f"Retrying with software encoder {sw} for preset={preset}...")
                result = run_ffmpeg_test(input_path, preset=preset, codec=sw, crf=crf)
                codec = sw
    with tempfile.TemporaryDirectory() as td:
        encoded_path = os.path.join(td, "out.mp4")
        cmd = build_ffmpeg_encode_cmd(input_path=input_path, output_path=encoded_path, encoder=codec, preset_name=preset, crf=crf)
        vmaf: Optional[float] = None
        if result.get("_encode_rc", 1) == 0 and float(result.get("fps", 0.0)) > 0 and int(result.get("fileSizeBytes", 0)) > 0:
            print("Calculating VMAF...")
            subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            vmaf = compute_vmaf(input_path, encoded_path)
    payload = {
        "cpuModel": hardware.cpuModel,
        "gpuModel": hardware.gpuModel or "",
        "ramGB": hardware.ramGB,
        "os": hardware.os,
        "codec": codec,
        "preset": preset,
        "crf": crf,
        "fps": float(result["fps"]),
        "fileSizeBytes": int(result["fileSizeBytes"]),
        "runMs": int(result.get("elapsedMs") or 0),
    }
    if vmaf is not None:
        payload["vmaf"] = float(vmaf)
    if result.get("_error"):
        payload["notes"] = str(result["_error"])[:500]
    return payload


def sha256_of_file(path: str) -> str:
    hasher = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def verify_sample_video(path: str) -> tuple:
    """Return (ok, message). Verifies that sample.mp4 matches expected size and hash."""
    try:
        if not os.path.exists(path):
            return False, "sample.mp4 not found"
        size = os.path.getsize(path)
        if int(size) != int(config.SAMPLE_VIDEO_SIZE_BYTES):
            return False, f"sample.mp4 size mismatch (expected {config.SAMPLE_VIDEO_SIZE_BYTES}, got {size})"
        digest = sha256_of_file(path)
        if digest.lower() != config.SAMPLE_VIDEO_SHA256.lower():
            return False, "sample.mp4 checksum mismatch"
        return True, "ok"
    except Exception as e:
        return False, f"verification error: {e}"


def load_presets_config(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("Invalid presets.json format")
            return data
    except Exception:
        return {
            "smallBenchmark": {
                "crfValues": [28, 24],
                "approxMinutes": 60
            },
            "fullBenchmark": {
                "crfValues": [24],
                "approxMinutes": 120
            }
        }


def get_default_sample_path() -> Optional[str]:
    try:
        rp = config._resource_path("sample.mp4")
        if rp and os.path.exists(rp):
            return rp
    except Exception:
        pass
    try:
        client_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.abspath(os.path.join(client_dir, ".."))
        candidate = os.path.join(root_dir, "sample.mp4")
        return candidate if os.path.exists(candidate) else None
    except Exception:
        return None
