import argparse
import hashlib
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

import warnings
# Suppress urllib3 OpenSSL compatibility warning proactively (before any urllib3 import)
try:
    warnings.filterwarnings(
        "ignore",
        message=r".*urllib3 v2 only supports OpenSSL.*",
    )
except Exception:
    pass

try:
    import certifi  # type: ignore
    REQUESTS_VERIFY: Any = certifi.where()
except Exception:
    REQUESTS_VERIFY = True

import psutil
import cpuinfo  # type: ignore

try:
    import GPUtil  # type: ignore
except Exception:
    GPUtil = None  # type: ignore

# Fixed backend endpoint for submissions
BACKEND_BASE_URL = "https://encodingdb.platinumlabs.dev"
ENV_API_KEY = os.environ.get("API_KEY", "")
ENV_PRESETS = os.environ.get("PRESETS", "fast,medium,slow")
ENV_CODEC = os.environ.get("CODEC", "")  # If empty, prompt interactively
ENV_DISABLE_VMAF = os.environ.get("DISABLE_VMAF", "0") in ("1", "true", "TRUE")
ENV_INGEST_HMAC_SECRET = os.environ.get("INGEST_HMAC_SECRET", "")
ENV_QUEUE_DIR = os.environ.get("QUEUE_DIR", os.path.join(tempfile.gettempdir(), "encodingdb-queue"))

@dataclass
class HardwareInfo:
    cpuModel: str
    gpuModel: Optional[str]
    ramGB: int
    os: str


def detect_hardware() -> HardwareInfo:
    cpu = cpuinfo.get_cpu_info()
    cpu_model = cpu.get("brand_raw") or cpu.get("brand") or platform.processor() or "Unknown CPU"

    def normalize_apple_silicon_label(label: str) -> Optional[str]:
        try:
            if "Apple" not in label:
                return None
            # Common patterns include: "Apple M3 Pro", "Apple M2 Max", "Apple M1", possibly followed by core counts
            m = re.search(r"Apple\s+M\s*([0-9])\s*(Pro|Max|Ultra)?", label, re.IGNORECASE)
            if not m:
                return None
            gen = m.group(1)
            tier = m.group(2) or ""
            tier = tier.title()
            parts = ["Apple", f"M{gen}"]
            if tier:
                parts.append(tier)
            return " ".join(parts)
        except Exception:
            return None

    gpu_model: Optional[str] = None
    # On Apple Silicon, use CPU model as GPU model for consistency (VideoToolbox)
    try:
        if platform.system() == "Darwin" and ("Apple" in cpu_model):
            normalized = normalize_apple_silicon_label(cpu_model)
            if normalized:
                cpu_model = normalized
            gpu_model = cpu_model
        elif GPUtil is not None:
            try:
                gpus = GPUtil.getGPUs()
                if gpus:
                    gpu_model = gpus[0].name
            except Exception:
                gpu_model = None
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


# --- Codec selection helpers ---

CODEC_ALIASES: Dict[str, str] = {
    # h264
    "h264": "h264", "h.264": "h264", "avc": "h264", "x264": "h264", "libx264": "h264",
    # hevc / h265
    "h265": "hevc", "h.265": "hevc", "hevc": "hevc", "x265": "hevc", "libx265": "hevc",
    # av1
    "av1": "av1", "libaom": "av1", "libaom-av1": "av1", "svt": "av1", "svt-av1": "av1", "libsvtav1": "av1",
    # vp9
    "vp9": "vp9", "libvpx": "vp9", "libvpx-vp9": "vp9",
}

HARDWARE_ENCODERS: Dict[str, List[Tuple[str, str]]] = {
    # family -> list of (ffmpeg encoder name, friendly engine label)
    "h264": [
        ("h264_nvenc", "NVENC"),
        ("h264_qsv", "Intel QSV"),
        ("h264_amf", "AMD AMF"),
        ("h264_videotoolbox", "VideoToolbox"),
        ("h264_vaapi", "VAAPI"),
    ],
    "hevc": [
        ("hevc_nvenc", "NVENC"),
        ("hevc_qsv", "Intel QSV"),
        ("hevc_amf", "AMD AMF"),
        ("hevc_videotoolbox", "VideoToolbox"),
        ("hevc_vaapi", "VAAPI"),
    ],
    "av1": [
        ("av1_nvenc", "NVENC"),
        ("av1_qsv", "Intel QSV"),
        ("av1_amf", "AMD AMF"),
        ("av1_videotoolbox", "VideoToolbox"),
        ("av1_vaapi", "VAAPI"),
    ],
    "vp9": [
        ("vp9_qsv", "Intel QSV"),
        ("vp9_vaapi", "VAAPI"),
    ],
}

SOFTWARE_ENCODERS_ORDER: Dict[str, List[str]] = {
    "h264": ["libx264"],
    "hevc": ["libx265"],
    "av1": ["libsvtav1", "libaom-av1"],
    "vp9": ["libvpx-vp9"],
}

def normalize_codec_family(user_input: str) -> Optional[str]:
    key = re.sub(r"[^a-z0-9]", "", (user_input or "").strip().lower())
    return CODEC_ALIASES.get(key)

def pick_software_encoder_for_family(family: str) -> Optional[str]:
    for enc in SOFTWARE_ENCODERS_ORDER.get(family, []):
        if has_encoder(enc):
            return enc
    return None

def discover_hardware_encoders_for_family(family: str) -> List[Tuple[str, str]]:
    candidates = HARDWARE_ENCODERS.get(family, [])
    available: List[Tuple[str, str]] = []
    for enc, label in candidates:
        if has_encoder(enc):
            available.append((enc, label))
    return available

def prompt_yes_no(prompt: str, default_no: bool = True) -> bool:
    suffix = " [y/N]: " if default_no else " [Y/n]: "
    ans = input(prompt + suffix).strip().lower()
    if not ans:
        return not default_no
    return ans in ("y", "yes")

def prompt_choice(prompt: str, options: List[str], default_index: int = 0) -> int:
    for i, opt in enumerate(options, start=1):
        print(f"  {i}) {opt}")
    raw = input(f"{prompt} (1-{len(options)}) [default {default_index+1}]: ").strip()
    if not raw:
        return default_index
    try:
        idx = int(raw)
        if 1 <= idx <= len(options):
            return idx - 1
    except Exception:
        pass
    return default_index


# --- FFmpeg command builder with encoder-aware presets ---

def map_preset_for_encoder(encoder: str, preset_name: str) -> List[str]:
    name = preset_name.strip().lower() if preset_name else "medium"
    e = encoder.strip().lower()
    # x264/x265: direct presets
    if e in ("libx264", "libx265"):
        direct = {"fast": "fast", "medium": "medium", "slow": "slow"}
        return ["-preset", direct.get(name, "medium")]
    # SVT-AV1 expects numeric preset 0..13 (higher=faster). Choose 10/8/6
    if e == "libsvtav1":
        svt = {"fast": "10", "medium": "8", "slow": "6"}
        return ["-preset", svt.get(name, "8")]
    # libaom-av1 uses -cpu-used 0..8 (higher=faster). Choose 8/6/4
    if e == "libaom-av1":
        aom = {"fast": 8, "medium": 6, "slow": 4}
        return ["-cpu-used", str(aom.get(name, 6)), "-row-mt", "1"]
    # libvpx-vp9: use deadline good + cpu-used
    if e == "libvpx-vp9":
        vp9 = {"fast": 5, "medium": 2, "slow": 0}
        return ["-deadline", "good", "-cpu-used", str(vp9.get(name, 2))]
    # NVENC: support p1..p7 (p7 fastest)
    if e.endswith("_nvenc"):
        nv = {"fast": "p7", "medium": "p4", "slow": "p2"}
        return ["-preset", nv.get(name, "p4")]
    # QSV: use ffmpeg presets fast/medium/slow mapping
    if e.endswith("_qsv"):
        qsv = {"fast": "faster", "medium": "medium", "slow": "slow"}
        return ["-preset", qsv.get(name, "medium")]
    # AMF: use quality modes
    if e.endswith("_amf"):
        amf = {"fast": "speed", "medium": "balanced", "slow": "quality"}
        return ["-quality", amf.get(name, "balanced")]
    # VideoToolbox or others: no preset options
    return []


def build_ffmpeg_encode_cmd(*, input_path: str, output_path: str, encoder: str, preset_name: str) -> List[str]:
    cmd: List[str] = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", input_path,
        "-c:v", encoder,
    ]
    cmd += map_preset_for_encoder(encoder, preset_name)
    if encoder.endswith(("_nvenc", "_qsv", "_amf", "_videotoolbox", "_vaapi")):
        cmd += ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p"]
    e = encoder.strip().lower()
    if e == "h264_videotoolbox":
        cmd += ["-b:v", "5000k", "-profile:v", "high", "-g", "120"]
    elif e == "hevc_videotoolbox":
        cmd += ["-b:v", "5000k", "-tag:v", "hvc1"]
    elif e == "av1_videotoolbox":
        cmd += ["-b:v", "5000k"]
    # Common flags
    cmd += ["-an", output_path]
    return cmd


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
        cmd = build_ffmpeg_encode_cmd(input_path=input_path, output_path=out_path, encoder=codec, preset_name=preset)
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
        result: Dict[str, Any] = {"fps": fps, "fileSizeBytes": size, "_encode_rc": proc.returncode, "elapsedMs": int(round(elapsed * 1000))}
        # Basic error reporting: if encode failed or produced no output, print concise error
        if proc.returncode != 0 or size == 0 or fps == 0.0:
            stderr_lines = (proc.stderr or "").splitlines()
            brief = "; ".join([ln.strip() for ln in stderr_lines[-5:]]) if stderr_lines else "ffmpeg failed"
            print(f"ffmpeg error (preset={preset}, codec={codec}): {brief}", file=sys.stderr)
            # Attach a non-submitted local error for caller decisions
            result["_error"] = brief
        return result


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
    # Fallback: if failed with a hardware encoder, retry with software encoder for the same family
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
                result = run_ffmpeg_test(input_path, preset=preset, codec=sw)
                codec = sw
    # For VMAF, we need the encoded output; re-run to keep artifact
    with tempfile.TemporaryDirectory() as td:
        encoded_path = os.path.join(td, "out.mp4")
        cmd = build_ffmpeg_encode_cmd(input_path=input_path, output_path=encoded_path, encoder=codec, preset_name=preset)
        # Only attempt VMAF pipeline if initial run looked successful
        vmaf: Optional[float] = None
        if result.get("_encode_rc", 1) == 0 and float(result.get("fps", 0.0)) > 0 and int(result.get("fileSizeBytes", 0)) > 0:
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
        "runMs": int(result.get("elapsedMs") or 0),
    }
    if vmaf is not None:
        payload["vmaf"] = float(vmaf)
    # Surface basic error in notes for visibility (not too verbose)
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


def submit(base_url: str, payload: Dict[str, Any], api_key: str = "", retries: int = 3, backoff_seconds: float = 1.0) -> None:
    import requests  # lazy import
    url = f"{base_url.rstrip('/')}/submit"
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    # HMAC signing if secret available
    ts = int(time.time())
    body = json.dumps(payload, separators=(",", ":"))
    secret = ENV_INGEST_HMAC_SECRET
    if secret:
        import hmac, hashlib
        sig = hmac.new(secret.encode("utf-8"), f"{ts}.".encode("utf-8") + body.encode("utf-8"), hashlib.sha256).hexdigest()
        headers["x-signature"] = sig
        headers["x-timestamp"] = str(ts)
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, data=body, timeout=30, headers=headers, verify=REQUESTS_VERIFY)
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
    p.add_argument("--api-key", default=ENV_API_KEY, help="API key for submission (default: env API_KEY)")
    p.add_argument("--codec", default=ENV_CODEC, help="FFmpeg video encoder or codec family (e.g., libx264, h264, av1). If omitted, will prompt.")
    p.add_argument("--presets", default=ENV_PRESETS, help="Comma-separated list of presets (default: fast,medium,slow)")
    p.add_argument("--no-submit", action="store_true", help="Run tests but do not submit results")
    p.add_argument("--disable-vmaf", action="store_true", default=ENV_DISABLE_VMAF, help="Skip VMAF computation")
    p.add_argument("--retries", type=int, default=3, help="Submission retry attempts (default: 3)")
    p.add_argument("--queue-dir", default=ENV_QUEUE_DIR, help="Directory for offline retry queue")
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

    # Resolve codec/encoder interactively if needed
    resolved_encoder: Optional[str] = None
    user_codec = (args.codec or "").strip()
    family = normalize_codec_family(user_codec) if user_codec else None
    if not family:
        # Prompt for family
        families = ["h264", "hevc (h265)", "av1", "vp9"]
        choice = prompt_choice("Select a codec", families, default_index=0)
        family = ["h264", "hevc", "av1", "vp9"][choice]

    hw_options = discover_hardware_encoders_for_family(family)
    if len(hw_options) == 1:
        enc, label = hw_options[0]
        if prompt_yes_no(f"Use Hardware Acceleration ({label})?"):
            resolved_encoder = enc
    elif len(hw_options) > 1:
        labels = [label for _, label in hw_options]
        idx = prompt_choice("Use Hardware Acceleration? Choose engine", labels + ["No (software)"] , default_index=len(labels))
        if idx < len(labels):
            resolved_encoder = hw_options[idx][0]

    if not resolved_encoder:
        # fallback to software
        sw = pick_software_encoder_for_family(family)
        if not sw:
            print("No media engine detected for the selected codec, using Software Encoding")
            # keep sw None to trigger error below
        resolved_encoder = sw

    if not resolved_encoder or not has_encoder(resolved_encoder):
        print("Requested codec/encoder not available in this ffmpeg build.", file=sys.stderr)
        return 4

    hardware = detect_hardware()
    input_hash = sha256_of_file(input_path)
    client_version = "client/0.1.0"
    try:
        presets = [s.strip() for s in args.presets.split(",") if s.strip()]
    except Exception:
        presets = ["fast", "medium", "slow"]

    all_payloads: List[Dict[str, Any]] = []
    os.makedirs(args.queue_dir, exist_ok=True)
    for preset in presets:
        print(f"Running preset: {preset}...")
        payload = run_single_benchmark(hardware, input_path, preset=preset, codec=resolved_encoder, enable_vmaf=(not args.disable_vmaf))
        # Attach submission metadata
        payload["ffmpegVersion"] = ffmpeg_version
        payload["encoderName"] = payload.get("codec", resolved_encoder)
        payload["clientVersion"] = client_version
        payload["inputHash"] = input_hash
        # runMs is already populated by run_single_benchmark based on encode timing
        all_payloads.append(payload)
        if args.no_submit:
            print(f"Dry-run: not submitting preset={preset}")
            continue
        try:
            # Skip submission if encode failed obviously
            if payload.get("fps", 0.0) <= 0 or payload.get("fileSizeBytes", 0) <= 0:
                print(f"Skipped submission for preset={preset} due to encode failure (fps={payload.get('fps')}, size={payload.get('fileSizeBytes')})")
                all_payloads.append({**payload, "localError": True})
                continue
            submit(BACKEND_BASE_URL, payload, api_key=args.api_key, retries=max(1, args.retries))
            print(f"Submitted: {preset}")
        except Exception as e:
            print(f"Failed to submit {preset}: {e}", file=sys.stderr)
            # Persist to local retry queue
            try:
                fname = os.path.join(args.queue_dir, f"{int(time.time()*1000)}-{preset}.json")
                with open(fname, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, separators=(",", ":"))
                print(f"Queued for retry: {fname}")
            except Exception as qe:
                print(f"Failed to queue payload: {qe}", file=sys.stderr)

    # Attempt to drain queue after loop
    try:
        files = sorted([f for f in os.listdir(args.queue_dir) if f.endswith('.json')])
        for fn in files:
            fpath = os.path.join(args.queue_dir, fn)
            try:
                with open(fpath, 'r', encoding='utf-8') as fh:
                    payload = json.load(fh)
                submit(BACKEND_BASE_URL, payload, api_key=args.api_key, retries=max(1, args.retries))
                os.remove(fpath)
                print(f"Retried and submitted: {fn}")
            except Exception:
                # keep for next run
                pass
    except Exception:
        pass
    print(json.dumps(all_payloads, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
