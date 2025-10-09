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
ENV_BACKEND_BASE_URL = os.environ.get("BACKEND_BASE_URL", BACKEND_BASE_URL)
ENV_API_KEY = os.environ.get("ENCDB_API_KEY", "")
ENV_PRESETS = os.environ.get("PRESETS", "fast,medium,slow")
ENV_CRF = os.environ.get("CRF", "24")
ENV_CODEC = os.environ.get("CODEC", "")  # If empty, prompt interactively
ENV_INGEST_HMAC_SECRET = os.environ.get("INGEST_HMAC_SECRET", "")
ENV_QUEUE_DIR = os.environ.get("QUEUE_DIR", os.path.join(tempfile.gettempdir(), "encodingdb-queue"))
PRESETS_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "presets.json")

# --- Cross-platform binary resolution helpers (PyInstaller-friendly) ---

def _app_base_dir() -> str:
    try:
        base = getattr(sys, "_MEIPASS", None)  # type: ignore[attr-defined]
        if base and isinstance(base, str):
            return base
    except Exception:
        pass
    return os.path.dirname(os.path.abspath(__file__))

def _resource_path(*names: str) -> str:
    return os.path.join(_app_base_dir(), *names)

def _platform_key() -> str:
    sysname = platform.system().lower()
    if sysname.startswith("darwin") or sysname.startswith("mac"):
        return "mac"
    if sysname.startswith("windows"):
        return "win"
    return "linux"

def _which(exe_name: str) -> Optional[str]:
    try:
        import shutil
        p = shutil.which(exe_name)
        return p
    except Exception:
        return None

def _candidate_ffmpeg_paths() -> List[str]:
    plat = _platform_key()
    names = ["ffmpeg"] if plat != "win" else ["ffmpeg.exe", "ffmpeg"]
    candidates: List[str] = []
    env_ffmpeg = os.environ.get("FFMPEG_EXE")
    if env_ffmpeg:
        candidates.append(env_ffmpeg)
    for n in names:
        w = _which(n)
        if w:
            candidates.append(w)
    if plat == "mac":
        candidates += ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"]
    elif plat == "linux":
        candidates += ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"]
    else:
        candidates += [r"C:\\ffmpeg\\bin\\ffmpeg.exe"]
    for n in names:
        candidates.append(_resource_path("bin", plat, n))
    return candidates

def _candidate_ffprobe_paths() -> List[str]:
    plat = _platform_key()
    names = ["ffprobe"] if plat != "win" else ["ffprobe.exe", "ffprobe"]
    candidates: List[str] = []
    env_ffprobe = os.environ.get("FFPROBE_EXE")
    if env_ffprobe:
        candidates.append(env_ffprobe)
    for n in names:
        w = _which(n)
        if w:
            candidates.append(w)
    if plat == "mac":
        candidates += ["/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe"]
    elif plat == "linux":
        candidates += ["/usr/bin/ffprobe", "/usr/local/bin/ffprobe"]
    else:
        candidates += [r"C:\\ffmpeg\\bin\\ffprobe.exe"]
    for n in names:
        candidates.append(_resource_path("bin", plat, n))
    return candidates

_FFMPEG_EXE: Optional[str] = None
_FFPROBE_EXE: Optional[str] = None

def ffmpeg_exe() -> str:
    global _FFMPEG_EXE
    if _FFMPEG_EXE and os.path.exists(_FFMPEG_EXE):
        return _FFMPEG_EXE
    for p in _candidate_ffmpeg_paths():
        try:
            if p and os.path.exists(p):
                _FFMPEG_EXE = p
                return _FFMPEG_EXE
        except Exception:
            continue
    return "ffmpeg"

def ffprobe_exe() -> str:
    global _FFPROBE_EXE
    if _FFPROBE_EXE and os.path.exists(_FFPROBE_EXE):
        return _FFPROBE_EXE
    for p in _candidate_ffprobe_paths():
        try:
            if p and os.path.exists(p):
                _FFPROBE_EXE = p
                return _FFPROBE_EXE
        except Exception:
            continue
    return "ffprobe"

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
    if not exec_ok([ffmpeg_exe(), "-version"]) or not exec_ok([ffprobe_exe(), "-version"]):
        return False, None
    try:
        out = subprocess.run([ffmpeg_exe(), "-version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        version_line = (out.stdout or "").splitlines()[0] if out.stdout else ""
    except Exception:
        version_line = ""
    return True, version_line


def has_encoder(encoder: str) -> bool:
    try:
        out = subprocess.run([ffmpeg_exe(), "-hide_banner", "-encoders"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        return encoder in (out.stdout or "")
    except Exception:
        return False


def has_libvmaf() -> bool:
    try:
        out = subprocess.run([ffmpeg_exe(), "-hide_banner", "-filters"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
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
        ("h264_v4l2m2m", "V4L2 M2M"),
        ("h264_omx", "OMX"),
    ],
    "hevc": [
        ("hevc_nvenc", "NVENC"),
        ("hevc_qsv", "Intel QSV"),
        ("hevc_amf", "AMD AMF"),
        ("hevc_videotoolbox", "VideoToolbox"),
        ("hevc_vaapi", "VAAPI"),
        ("hevc_v4l2m2m", "V4L2 M2M"),
    ],
    "av1": [
        ("av1_nvenc", "NVENC"),
        ("av1_qsv", "Intel QSV"),
        ("av1_amf", "AMD AMF"),
        ("av1_videotoolbox", "VideoToolbox"),
        ("av1_vaapi", "VAAPI"),
        ("av1_v4l2m2m", "V4L2 M2M"),
    ],
    "vp9": [
        ("vp9_qsv", "Intel QSV"),
        ("vp9_vaapi", "VAAPI"),
        ("vp9_v4l2m2m", "V4L2 M2M"),
    ],
}

SOFTWARE_ENCODERS_ORDER: Dict[str, List[str]] = {
    "h264": ["libx264", "libopenh264"],
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


def list_all_available_encoders() -> List[str]:
    """Return all available encoders (software + hardware) across supported families."""
    encoders: List[str] = []
    # Software encoders
    for fam, sw_list in SOFTWARE_ENCODERS_ORDER.items():
        for enc in sw_list:
            if has_encoder(enc):
                encoders.append(enc)
    # Hardware encoders
    for fam, hw_list in HARDWARE_ENCODERS.items():
        for enc, _label in hw_list:
            if has_encoder(enc):
                encoders.append(enc)
    # De-duplicate while preserving order
    seen: Dict[str, bool] = {}
    uniq: List[str] = []
    for enc in encoders:
        if enc not in seen:
            seen[enc] = True
            uniq.append(enc)
    return uniq


def enumerate_supported_presets_for_encoder(encoder: str) -> List[str]:
    e = encoder.strip().lower()
    # x264/x265 full set
    if e in ("libx264", "libx265"):
        return [
            "ultrafast", "superfast", "veryfast", "faster", "fast",
            "medium", "slow", "slower", "veryslow", "placebo",
        ]
    # libsvtav1 numeric 0..13 (as strings to feed mapping)
    if e == "libsvtav1":
        return [str(n) for n in range(0, 14)]
    # libaom-av1 cpu-used 0..8
    if e == "libaom-av1":
        return [str(n) for n in range(0, 9)]
    # libvpx-vp9 cpu-used 0..8 (broader range supported)
    if e == "libvpx-vp9":
        return [str(n) for n in range(0, 9)]
    # NVENC p1..p7; map via friendly labels for display but pass through mapping
    if e.endswith("_nvenc"):
        return ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]
    # QSV: include 'faster' where supported
    if e.endswith("_qsv"):
        return ["faster", "fast", "medium", "slow"]
    # AMF: speed/balanced/quality
    if e.endswith("_amf"):
        return ["fast", "medium", "slow"]
    # VideoToolbox: no presets exposed generally
    if e.endswith("_videotoolbox"):
        return ["default"]
    # VAAPI: typically no preset
    if e.endswith("_vaapi"):
        return ["default"]
    # Default
    return ["medium"]


def _family_display_name(family: str) -> str:
    fam = family.lower()
    if fam == "h264":
        return "H.264"
    if fam == "hevc":
        return "HEVC (H.265)"
    if fam == "av1":
        return "AV1"
    if fam == "vp9":
        return "VP9"
    return family.upper()


def _infer_family_for_encoder(encoder: str) -> Optional[str]:
    e = encoder.lower()
    # Check software lists
    for family, sw_list in SOFTWARE_ENCODERS_ORDER.items():
        if encoder in sw_list:
            return family
    # Check hardware lists
    for family, hw_list in HARDWARE_ENCODERS.items():
        for enc, _label in hw_list:
            if enc == encoder:
                return family
    # Fallback by substring
    for family in ["h264", "hevc", "av1", "vp9"]:
        if family in e:
            return family
    return None


def _hardware_engine_label(encoder: str) -> Optional[str]:
    for _family, hw_list in HARDWARE_ENCODERS.items():
        for enc, label in hw_list:
            if enc == encoder:
                return label
    return None


def get_encoder_friendly_label(encoder: str) -> str:
    e = encoder.strip()
    family = _infer_family_for_encoder(e) or ""
    fam_label = _family_display_name(family) if family else e
    # Software specific names
    sw_map = {
        "libx264": f"{_family_display_name('h264')} (x264)",
        "libopenh264": f"{_family_display_name('h264')} (OpenH264)",
        "libx265": f"{_family_display_name('hevc')} (x265)",
        "libsvtav1": f"{_family_display_name('av1')} (SVT-AV1)",
        "libaom-av1": f"{_family_display_name('av1')} (AOM)",
        "libvpx-vp9": f"{_family_display_name('vp9')} (libvpx)",
    }
    if e in sw_map:
        return sw_map[e]
    # Hardware engines
    engine = _hardware_engine_label(e)
    if engine:
        return f"{fam_label} ({engine})"
    # Fallback to raw encoder
    return e


def sort_presets_by_speed_desc(encoder: str, presets: List[str]) -> List[str]:
    """Return presets ordered from fastest to slowest for given encoder."""
    e = encoder.strip().lower()
    # x264/x265 explicit order fastest->slowest
    if e in ("libx264", "libx265"):
        ordering = [
            "ultrafast", "superfast", "veryfast", "faster", "fast",
            "medium", "slow", "slower", "veryslow", "placebo",
        ]
        order_index = {name: i for i, name in enumerate(ordering)}
        return sorted(presets, key=lambda n: order_index.get(n, len(ordering)))
    # SVT-AV1 numeric 0..13, higher is faster
    if e == "libsvtav1":
        def speed_key(n: str) -> int:
            try:
                return -int(n)  # higher faster -> more negative sorts first
            except Exception:
                return 0
        return sorted(presets, key=speed_key)
    # libaom-av1 cpu-used 0..8, higher faster
    if e == "libaom-av1":
        def speed_key(n: str) -> int:
            try:
                return -int(n)
            except Exception:
                return 0
        return sorted(presets, key=speed_key)
    # libvpx-vp9 cpu-used 0..8, higher faster
    if e == "libvpx-vp9":
        def speed_key(n: str) -> int:
            try:
                return -int(n)
            except Exception:
                return 0
        return sorted(presets, key=speed_key)
    # NVENC p1..p7, p7 fastest
    if e.endswith("_nvenc"):
        ordering = ["p7", "p6", "p5", "p4", "p3", "p2", "p1"]
        order_index = {name: i for i, name in enumerate(ordering)}
        return sorted(presets, key=lambda n: order_index.get(n, len(ordering)))
    # QSV: faster, fast, medium, slow
    if e.endswith("_qsv"):
        ordering = ["faster", "fast", "medium", "slow"]
        order_index = {name: i for i, name in enumerate(ordering)}
        return sorted(presets, key=lambda n: order_index.get(n, len(ordering)))
    # AMF: fast, medium, slow
    if e.endswith("_amf"):
        ordering = ["fast", "medium", "slow"]
        order_index = {name: i for i, name in enumerate(ordering)}
        return sorted(presets, key=lambda n: order_index.get(n, len(ordering)))
    # VideoToolbox/VAAPI/V4L2/OMX: no preset or default only
    return presets

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


def prompt_text(prompt: str, default_value: str = "") -> str:
    raw = input(f"{prompt} [{default_value}]: ").strip()
    return raw or default_value


def load_presets_config(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("Invalid presets.json format")
            return data
    except Exception:
        # Defaults if presets.json is missing or invalid
        return {
            "smallBenchmark": {
                "crfValues": [28, 24],
                "approxMinutes": 5
            },
            "fullBenchmark": {
                "crfValues": [24],
                "approxMinutes": 20
            }
        }


def get_default_sample_path() -> Optional[str]:
    # Prefer packaged resource (PyInstaller); fallback to repo layout
    try:
        rp = _resource_path("sample.mp4")
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


# --- FFmpeg command builder with encoder-aware presets ---

def map_preset_for_encoder(encoder: str, preset_name: str) -> List[str]:
    name = preset_name.strip().lower() if preset_name else "medium"
    e = encoder.strip().lower()
    # x264/x265: full preset set
    if e in ("libx264", "libx265"):
        # valid: ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow, placebo
        valid = {
            "ultrafast": "ultrafast",
            "superfast": "superfast",
            "veryfast": "veryfast",
            "faster": "faster",
            "fast": "fast",
            "medium": "medium",
            "slow": "slow",
            "slower": "slower",
            "veryslow": "veryslow",
            "placebo": "placebo",
        }
        return ["-preset", valid.get(name, "medium")]
    # SVT-AV1 expects numeric preset 0..13 (higher=faster). Support exact numeric
    if e == "libsvtav1":
        if name.isdigit():
            return ["-preset", name]
        # fallback mapping for friendly names
        svt = {"ultrafast": "13", "veryfast": "11", "fast": "10", "medium": "8", "slow": "6", "veryslow": "4"}
        return ["-preset", svt.get(name, "8")]
    # libaom-av1 uses -cpu-used 0..8 (higher=faster). Support exact numeric
    if e == "libaom-av1":
        if name.isdigit():
            return ["-cpu-used", name, "-row-mt", "1"]
        aom = {"ultrafast": 8, "veryfast": 7, "fast": 6, "medium": 4, "slow": 3, "veryslow": 2}
        return ["-cpu-used", str(aom.get(name, 6)), "-row-mt", "1"]
    # libvpx-vp9: use deadline=good + cpu-used (0..5 practical)
    if e == "libvpx-vp9":
        if name.isdigit():
            return ["-deadline", "good", "-cpu-used", name]
        vp9 = {"ultrafast": 5, "veryfast": 4, "fast": 3, "medium": 2, "slow": 1, "veryslow": 0}
        return ["-deadline", "good", "-cpu-used", str(vp9.get(name, 2))]
    # NVENC: support p1..p7 (p7 fastest). Accept pN directly or map friendly
    if e.endswith("_nvenc"):
        if re.fullmatch(r"p[1-7]", name):
            return ["-preset", name]
        nv = {"ultrafast": "p7", "veryfast": "p6", "fast": "p5", "medium": "p4", "slow": "p3", "veryslow": "p2"}
        return ["-preset", nv.get(name, "p4")]
    # QSV: use ffmpeg presets mapping
    if e.endswith("_qsv"):
        qsv = {"faster": "faster", "fast": "fast", "medium": "medium", "slow": "slow"}
        return ["-preset", qsv.get(name, "medium")]
    # AMF: use quality modes
    if e.endswith("_amf"):
        amf = {"fast": "speed", "medium": "balanced", "slow": "quality"}
        return ["-quality", amf.get(name, "balanced")]
    # VideoToolbox or others: no preset options; accept 'default' as no-op
    return []


def build_ffmpeg_encode_cmd(*, input_path: str, output_path: str, encoder: str, preset_name: str, crf: Optional[int] = None) -> List[str]:
    cmd: List[str] = [
        ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", input_path,
        "-c:v", encoder,
    ]
    cmd += map_preset_for_encoder(encoder, preset_name)
    # Apply CRF when supported by encoder
    if crf is not None:
        e = encoder.strip().lower()
        # Software encoders
        if e in ("libx264", "libx265", "libsvtav1", "libaom-av1", "libvpx-vp9"):
            cmd += ["-crf", str(crf)]
        # NVENC supports -cq for const quality; map crf approximately if provided
        elif e.endswith("_nvenc"):
            # NVENC ranges 0..51; use CRF directly if in range
            cmd += ["-cq", str(max(0, min(51, crf)))]
        # QSV/AMF/VideoToolbox have different quality controls; skip unless mapped explicitly
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


def run_ffmpeg_test(input_path: str, preset: str, codec: str = "libx264", crf: Optional[int] = None) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, "out.mp4")
        cmd = build_ffmpeg_encode_cmd(input_path=input_path, output_path=out_path, encoder=codec, preset_name=preset, crf=crf)
        start = time.time()
        proc = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        end = time.time()
        elapsed = max(0.0001, end - start)
        # Count frames with ffprobe for accurate FPS
        try:
            probe = subprocess.run([
                ffprobe_exe(), "-v", "error", "-count_frames", "-select_streams", "v:0",
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
    # Requires ffmpeg with libvmaf; try several model specifications for portability
    filter_candidates: List[str] = []
    # Preferred: select bundled model by version (works on newer ffmpeg/libvmaf)
    filter_candidates.append("libvmaf=model=version=vmaf_v0.6.1:log_fmt=json:log_path=-")
    # Variant without version selection (some builds resolve default model by name)
    filter_candidates.append("libvmaf=log_fmt=json:log_path=-")
    # Common model file locations (Homebrew, system)
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
            ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "info",
            "-i", input_path,
            "-i", encoded_path,
            "-lavfi", filt,
            "-f", "null", "-",
        ]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            out = proc.stdout
            # Try multiple JSON/text formats used by libvmaf
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
            # Try next filter spec
            continue
    return None


def run_single_benchmark(hardware: HardwareInfo, input_path: str, preset: str, codec: str = "libx264", crf: Optional[int] = None) -> Dict[str, Any]:
    result = run_ffmpeg_test(input_path, preset=preset, codec=codec, crf=crf)
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
                result = run_ffmpeg_test(input_path, preset=preset, codec=sw, crf=crf)
                codec = sw
    # For VMAF, we need the encoded output; re-run to keep artifact
    with tempfile.TemporaryDirectory() as td:
        encoded_path = os.path.join(td, "out.mp4")
        cmd = build_ffmpeg_encode_cmd(input_path=input_path, output_path=encoded_path, encoder=codec, preset_name=preset, crf=crf)
        # Only attempt VMAF pipeline if initial run looked successful
        vmaf: Optional[float] = None
        if result.get("_encode_rc", 1) == 0 and float(result.get("fps", 0.0)) > 0 and int(result.get("fileSizeBytes", 0)) > 0:
            print("Calculating VMAF...")
            subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            vmaf = compute_vmaf(input_path, encoded_path)
    payload = {
        "cpuModel": hardware.cpuModel,
        "gpuModel": hardware.gpuModel,
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


def validate_api_key(base_url: str, api_key: str, timeout: float = 10.0) -> Tuple[bool, str]:
    import requests
    url = f"{base_url.rstrip('/')}/health"
    try:
        r = requests.get(url, headers={"X-API-Key": api_key}, timeout=timeout, verify=REQUESTS_VERIFY)
        # Auth is enforced on /submit only; probe an auth-gated POST with empty payload
        r2 = requests.post(f"{base_url.rstrip('/')}/submit", data="{}", headers={"Content-Type": "application/json", "X-API-Key": api_key}, timeout=timeout, verify=REQUESTS_VERIFY)
        if r2.status_code in (200, 201, 400):
            return True, "ok"
        if r2.status_code == 401:
            return False, "missing_api_key"
        if r2.status_code == 403:
            return False, "invalid_or_revoked"
        if r2.status_code == 429:
            return False, "rate_limited"
        if r2.status_code == 503 and 'low_disk' in (r2.text or ''):
            return False, "server_low_disk"
        return False, f"unexpected_{r2.status_code}"
    except Exception as e:
        return False, f"network_error: {e}"


def submit(base_url: str, payload: Dict[str, Any], api_key: str = "", retries: int = 3, backoff_seconds: float = 1.0) -> None:
    import requests  # lazy import
    url = f"{base_url.rstrip('/')}/submit"
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key.strip()
    # Fetch submit token (and optional PoW) if server runs in public/hybrid mode
    try:
        base = base_url.rstrip('/')
        # Prefer health-based token which we know routes to the API
        endpoints = [
            f"{base}/health/token",
            f"{base}/submit-token",
            f"{base}/submit/token",
        ]
        tokenResp = None
        for ep in endpoints:
            try:
                r = requests.get(ep, timeout=10, verify=REQUESTS_VERIFY)
                if r.status_code == 200:
                    tokenResp = r
                    break
            except Exception:
                continue
        if tokenResp is None:
            # Nothing worked; leave unsigned (middleware may allow)
            tokenResp = requests.Response()
            tokenResp.status_code = 0
        if tokenResp.status_code == 200:
            tokenData = tokenResp.json() or {}
            token = str(tokenData.get('token') or '')
            powInfo = tokenData.get('pow') or {}
            if token:
                headers['x-ingest-token'] = token
                # Optional PoW: find a small nonce
                try:
                    difficulty = int(powInfo.get('difficulty') or 0)
                except Exception:
                    difficulty = 0
                if difficulty > 0:
                    prefix = '0' * max(0, difficulty)
                    # Simple bounded search; server uses sha256(token.nonce)
                    nonce = 0
                    max_iters = 500000
                    while nonce < max_iters:
                        test = hashlib.sha256(f"{token}.{nonce}".encode('utf-8')).hexdigest()
                        if test.startswith(prefix):
                            headers['x-ingest-nonce'] = str(nonce)
                            break
                        nonce += 1
                # else: no PoW required
        else:
            # Debug aid: show why token wasn't returned
            try:
                print(f"token fetch failed: {tokenResp.status_code} {tokenResp.text}", file=sys.stderr)
            except Exception:
                pass
        # If 404/other, continue; server may be in signed mode
    except Exception as te:
        try:
            print(f"token fetch error: {te}", file=sys.stderr)
        except Exception:
            pass
    # HMAC signing if secret available (legacy)
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
            # Friendly hints for common auth/disk errors
            try:
                import requests as _req  # type: ignore
                if isinstance(e, _req.HTTPError) and getattr(e, 'response', None) is not None:
                    resp = e.response
                    if resp.status_code in (401, 403):
                        print("Submission rejected: invalid or missing API key. Set --api-key or ENCDB_API_KEY.", file=sys.stderr)
                    elif resp.status_code == 429:
                        print("Rate limited. Waiting before retry...", file=sys.stderr)
                    elif resp.status_code == 503 and 'low_disk' in (resp.text or ''):
                        print("Server temporarily read-only due to low disk space. Try again later.", file=sys.stderr)
            except Exception:
                pass
            # On final attempt, surface server response body and token diagnostics
            if attempt == retries:
                try:
                    import requests as _req  # type: ignore
                    if isinstance(e, _req.HTTPError) and getattr(e, 'response', None) is not None:
                        resp = e.response
                        try:
                            err_text = resp.text
                        except Exception:
                            err_text = ""
                        sent_token = 'x-ingest-token' in headers
                        sent_nonce = 'x-ingest-nonce' in headers
                        print(f"submit error body ({resp.status_code}): {err_text}\n(sent_token={sent_token}, sent_nonce={sent_nonce})", file=sys.stderr)
                except Exception:
                    pass
                raise
            time.sleep(backoff_seconds * attempt)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Encoding Benchmark Client")
    p.add_argument("--base-url", default=ENV_BACKEND_BASE_URL, help="Backend base URL (default: env BACKEND_BASE_URL or production)")
    p.add_argument("--api-key", default=ENV_API_KEY, help="API key for submission (default: env ENCDB_API_KEY)")
    p.add_argument("--codec", default=ENV_CODEC, help="FFmpeg video encoder or codec family (e.g., libx264, h264, av1). If omitted, will prompt.")
    p.add_argument("--presets", default=ENV_PRESETS, help="Comma-separated list of presets (default: fast,medium,slow)")
    p.add_argument("--no-submit", action="store_true", help="Run tests but do not submit results")
    p.add_argument("--crf", type=int, default=int(ENV_CRF) if ENV_CRF.isdigit() else 24, help="Constant Rate Factor (encoder-dependent). Defaults to 24.")
    p.add_argument("--retries", type=int, default=3, help="Submission retry attempts (default: 3)")
    p.add_argument("--queue-dir", default=ENV_QUEUE_DIR, help="Directory for offline retry queue")
    p.add_argument("--menu", action="store_true", help="Force interactive menu even if arguments are provided")
    return p


def run_with_args(args: argparse.Namespace) -> int:
    # Ensure API key present and valid before any work
    api_key = (args.api_key or os.environ.get("ENCDB_API_KEY", "")).strip()
    if not api_key:
        # Prompt for API key interactively
        try:
            api_key = prompt_text("Enter your API key", "").strip()
        except Exception:
            api_key = ""
    if not api_key:
        print("An API key is required to submit results. Set --api-key or ENCDB_API_KEY.", file=sys.stderr)
        return 6
    ok, reason = validate_api_key(args.base_url, api_key)
    if not ok:
        msg = {
            "missing_api_key": "Missing API key (401).",
            "invalid_or_revoked": "Invalid or revoked API key (403).",
            "rate_limited": "API key rate limited (429). Try again later.",
            "server_low_disk": "Server temporarily read-only due to low disk. Try later.",
        }.get(reason, f"API key validation failed: {reason}")
        print(msg, file=sys.stderr)
        return 6
    # Persist validated key to environment for subsequent calls
    os.environ["ENCDB_API_KEY"] = api_key
    ok, ffmpeg_version = ensure_ffmpeg_and_ffprobe()
    if not ok:
        print("ffmpeg/ffprobe not found in PATH. Please install ffmpeg.", file=sys.stderr)
        return 2
    print(f"ffmpeg detected: {ffmpeg_version or 'unknown'}")
    # Require libvmaf presence always
    if not has_libvmaf():
        print(
            "Your ffmpeg build does not include libvmaf. Install ffmpeg with libvmaf.",
            file=sys.stderr,
        )
        return 5

    input_path = get_default_sample_path()
    if not input_path:
        print("Required test video not found (expected sample.mp4 in project root).", file=sys.stderr)
        return 3

    # Resolve codec/encoder: if a specific encoder is provided and available, use it directly without prompting.
    resolved_encoder: Optional[str] = None
    user_codec = (args.codec or "").strip()
    if user_codec and has_encoder(user_codec):
        resolved_encoder = user_codec
    else:
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
    # Build (preset, crf) combos. CLI --presets still supported as a fallback (using single CRF).
    combos: List[Tuple[str, Optional[int]]] = []
    try:
        preset_list = [s.strip() for s in args.presets.split(",") if s.strip()]
    except Exception:
        preset_list = ["fast", "medium", "slow"]

    all_payloads: List[Dict[str, Any]] = []
    os.makedirs(args.queue_dir, exist_ok=True)
    base_url = args.base_url
    user_crf: Optional[int] = args.crf
    if preset_list:
        combos = [(p, user_crf) for p in preset_list]
    for preset, crf_val in combos:
        print(f"Running preset: {preset} (crf={crf_val})...")
        payload = run_single_benchmark(hardware, input_path, preset=preset, codec=resolved_encoder, crf=crf_val)
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
            submit(base_url, payload, api_key=api_key, retries=max(1, args.retries))
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
                submit(base_url, payload, api_key=api_key, retries=max(1, args.retries))
                os.remove(fpath)
                print(f"Retried and submitted: {fn}")
            except Exception:
                # keep for next run
                pass
    except Exception:
        pass
    print(json.dumps(all_payloads, indent=2))
    return 0


def interactive_menu_flow(parser: argparse.ArgumentParser, base_args: argparse.Namespace) -> int:
    # Print menu
    print("Select an option:")
    menu = [
        "Run Single Benchmark",
        "Run Small Benchmark [~5 minutes]",
        "Run Full Benchmark [~20 minutes]",
        "Exit",
    ]
    choice = prompt_choice("Menu", menu, default_index=0)
    if choice == 3:
        return 0

    presets_cfg = load_presets_config(PRESETS_CONFIG_PATH)

    # Determine presets to run based on choice
    if choice == 0:
        # Single benchmark: list all encoders (software/hardware separated) -> CRF -> preset
        all_encs = list_all_available_encoders()
        if not all_encs:
            print("No available encoders found in this ffmpeg build.", file=sys.stderr)
            return 4

        sw_set = set([enc for _family, lst in SOFTWARE_ENCODERS_ORDER.items() for enc in lst])
        hw_set = set([enc for _family, lst in HARDWARE_ENCODERS.items() for enc, _ in lst])
        sw_encs = [e for e in all_encs if e in sw_set]
        hw_encs = [e for e in all_encs if e in hw_set]

        print("Select an encoder:")
        idx_map: List[str] = []
        counter = 1
        if sw_encs:
            print("------Software------")
            for e in sw_encs:
                print(f"  {counter}) {get_encoder_friendly_label(e)}")
                idx_map.append(e)
                counter += 1
        if hw_encs:
            print("------Hardware------")
            for e in hw_encs:
                print(f"  {counter}) {get_encoder_friendly_label(e)}")
                idx_map.append(e)
                counter += 1

        default_idx = 0
        try:
            if "libx264" in idx_map:
                default_idx = idx_map.index("libx264")
        except Exception:
            default_idx = 0
        raw = input(f"Choose encoder (1-{len(idx_map)}) [default {default_idx+1}]: ").strip()
        try:
            enc_idx = (int(raw) - 1) if raw else default_idx
        except Exception:
            enc_idx = default_idx
        enc_idx = min(max(0, enc_idx), len(idx_map)-1)
        chosen_encoder = idx_map[enc_idx]

        # CRF prompt
        try:
            default_crf = base_args.crf if isinstance(base_args.crf, int) else 24
        except Exception:
            default_crf = 24
        crf_input = prompt_text("Enter CRF", str(default_crf))
        try:
            chosen_crf = int(crf_input)
        except Exception:
            chosen_crf = default_crf

        # Preset prompt based on encoder
        encoder_presets = enumerate_supported_presets_for_encoder(chosen_encoder)
        if not encoder_presets:
            encoder_presets = ["medium"]
        mid_index = max(0, (len(encoder_presets) - 1) // 2)
        preset_idx = prompt_choice("Select a preset", encoder_presets, default_index=mid_index)
        chosen_preset = encoder_presets[preset_idx]

        # Execute single run
        effective_args = argparse.Namespace(
            base_url=base_args.base_url,
            api_key=base_args.api_key,
            codec=chosen_encoder,
            presets=chosen_preset,
            no_submit=base_args.no_submit,
            crf=chosen_crf,
            retries=base_args.retries,
            queue_dir=base_args.queue_dir,
            menu=False,
        )
        return run_with_args(effective_args)
    # Build an args Namespace reusing defaults from base_args
    # Now enumerate all encoders and run each CRF across all encoders and all their supported presets
    encoders = list_all_available_encoders()
    if not encoders:
        print("No available encoders found in this ffmpeg build.", file=sys.stderr)
        return 4
    # Ensure test video exists
    if not get_default_sample_path():
        print("Required test video not found (expected sample.mp4 in project root).", file=sys.stderr)
        return 3
    crf_values: List[int] = []
    if choice == 0:
        # Single: ask for CRF
        try:
            default_crf = base_args.crf if isinstance(base_args.crf, int) else 24
        except Exception:
            default_crf = 24
        crf_input = prompt_text("Enter CRF", str(default_crf))
        try:
            crf_values = [int(crf_input)]
        except Exception:
            crf_values = [default_crf]
    else:
        # Small/Full from config
        crf_values = [int(v) for v in (presets_cfg.get("smallBenchmark", {}).get("crfValues", []) if choice == 1 else presets_cfg.get("fullBenchmark", {}).get("crfValues", [])) if isinstance(v, int)]
        if not crf_values:
            crf_values = [24]

    for crf_val in crf_values:
        for enc in encoders:
            presets_for_encoder = enumerate_supported_presets_for_encoder(enc)
            # For Small (standard) benchmark, drop bottom 20% (rounded) slowest presets
            if choice == 1 and len(presets_for_encoder) > 0:
                ordered = sort_presets_by_speed_desc(enc, presets_for_encoder)
                drop_count = int(round(len(ordered) * 0.2))
                if drop_count >= len(ordered):
                    drop_count = len(ordered) - 1  # always keep at least one
                if drop_count > 0:
                    presets_for_encoder = ordered[:-drop_count]
                else:
                    presets_for_encoder = ordered
            for preset_label in presets_for_encoder:
                effective_args = argparse.Namespace(
                    base_url=base_args.base_url,
                    api_key=base_args.api_key,
                    codec=enc,
                    presets=preset_label,
                    no_submit=base_args.no_submit,
                    crf=crf_val,
                    retries=base_args.retries,
                    queue_dir=base_args.queue_dir,
                    menu=False,
                )
                rc = run_with_args(effective_args)
                if rc not in (0,):
                    pass
    return 0


def main(argv: List[str]) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv[1:])
    # Always show interactive menu for benchmarks
    return interactive_menu_flow(parser, args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
