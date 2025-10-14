import argparse
import shutil
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

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
ENV_API_KEY = os.environ.get("API_KEY", "")
ENV_PRESETS = os.environ.get("PRESETS", "fast,medium,slow")
ENV_CRF = os.environ.get("CRF", "24")
ENV_CODEC = os.environ.get("CODEC", "")  # If empty, prompt interactively
ENV_INGEST_HMAC_SECRET = os.environ.get("INGEST_HMAC_SECRET", "")
ENV_QUEUE_DIR = os.environ.get("QUEUE_DIR", os.path.join(tempfile.gettempdir(), "encodingdb-queue"))
PRESETS_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "presets.json")

# Integrity reference for bundled sample.mp4 (do not change without updating both values)
SAMPLE_VIDEO_SHA256 = "53a87df054e65d284bc808b8f73e62e938b815cb6aeec8379f904ad6d792aab8"
SAMPLE_VIDEO_SIZE_BYTES = 66045059

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
# Print concise FFmpeg detected banner only once per session
_FFMPEG_DETECTED_PRINTED: bool = False
# Cache for probing hardware encoder usability so we do not repeatedly run ffmpeg
_ENCODER_USABLE_CACHE: Dict[str, bool] = {}
_ALLOWED_PAYLOAD_KEYS: Tuple[str, ...] = (
    'cpuModel', 'gpuModel', 'ramGB', 'os',
    'codec', 'preset', 'crf', 'fps', 'vmaf', 'fileSizeBytes', 'notes',
    'ffmpegVersion', 'encoderName', 'clientVersion', 'inputHash', 'runMs'
)
# Batch aggregation for Small/Full multi-run flows
_BATCH_ACTIVE: bool = False
_BATCH_START_TS: float = 0.0
_BATCH_COMPLETED_COUNT: int = 0

# Baseline cache for client-side outlier checks (populated lazily per session)
_BASELINE_ROWS_CACHE: Optional[List[Dict[str, Any]]] = None


def _env_flag(name: str, default: bool = False) -> bool:
    try:
        v = os.environ.get(name, "")
        return str(v).strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        return default

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
    gpuVendors: List[str] = field(default_factory=list)


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
    vendors: List[str] = []
    # On Apple Silicon, use CPU model as GPU model for consistency (VideoToolbox)
    try:
        if platform.system() == "Darwin" and ("Apple" in cpu_model):
            normalized = normalize_apple_silicon_label(cpu_model)
            if normalized:
                cpu_model = normalized
            gpu_model = cpu_model
            vendors.append('apple')
        elif GPUtil is not None:
            try:
                gpus = GPUtil.getGPUs()
                if gpus:
                    # Collect all GPU names and infer vendors
                    names = []
                    for g in gpus:
                        try:
                            n = str(getattr(g, 'name', '') or '')
                            if n:
                                names.append(n)
                        except Exception:
                            pass
                    if names:
                        gpu_model = gpu_model or names[0]
                        for n in names:
                            ln = n.lower()
                            if any(x in ln for x in ['nvidia', 'geforce', 'tesla', 'quadro']):
                                vendors.append('nvidia')
                            if any(x in ln for x in ['intel', 'iris', 'uhd', 'xe']):
                                vendors.append('intel')
                            if any(x in ln for x in ['amd', 'radeon', 'rx ', 'vega']):
                                vendors.append('amd')
            except Exception:
                gpu_model = None
        # Windows fallback: query WMI for GPU model when NVML is not available
        if not gpu_model and platform.system() == "Windows":
            try:
                # Prefer PowerShell CIM which is available on modern Windows
                probe = subprocess.run([
                    "powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name | ConvertTo-Json -Compress"
                ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5)
                names_raw = (probe.stdout or "").strip()
                if names_raw:
                    try:
                        import json as _json
                        names = _json.loads(names_raw)
                        if isinstance(names, list) and names:
                            gpu_model = str(names[0])
                            for n in names:
                                ln = str(n).lower()
                                if any(x in ln for x in ['nvidia', 'geforce', 'tesla', 'quadro']):
                                    vendors.append('nvidia')
                                if any(x in ln for x in ['intel', 'iris', 'uhd', 'xe']):
                                    vendors.append('intel')
                                if any(x in ln for x in ['amd', 'radeon', 'rx ', 'vega']):
                                    vendors.append('amd')
                        elif isinstance(names, str) and names:
                            gpu_model = names
                            ln = names.lower()
                            if any(x in ln for x in ['nvidia', 'geforce', 'tesla', 'quadro']):
                                vendors.append('nvidia')
                            if any(x in ln for x in ['intel', 'iris', 'uhd', 'xe']):
                                vendors.append('intel')
                            if any(x in ln for x in ['amd', 'radeon', 'rx ', 'vega']):
                                vendors.append('amd')
                    except Exception:
                        # Fallback: take the first non-empty line
                        for line in names_raw.splitlines():
                            t = line.strip()
                            if t:
                                gpu_model = t
                                lt = t.lower()
                                if any(x in lt for x in ['nvidia', 'geforce', 'tesla', 'quadro']):
                                    vendors.append('nvidia')
                                if any(x in lt for x in ['intel', 'iris', 'uhd', 'xe']):
                                    vendors.append('intel')
                                if any(x in lt for x in ['amd', 'radeon', 'rx ', 'vega']):
                                    vendors.append('amd')
                                break
            except Exception:
                gpu_model = gpu_model or None
        # Linux vendor hints via lspci (best-effort)
        if platform.system() == 'Linux':
            try:
                proc = subprocess.run(['sh', '-lc', "lspci -nn | grep -i 'vga\|3d'"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=3)
                txt = (proc.stdout or '').lower()
                if 'nvidia' in txt or 'geforce' in txt:
                    vendors.append('nvidia')
                if 'intel' in txt:
                    vendors.append('intel')
                if 'amd' in txt or 'radeon' in txt:
                    vendors.append('amd')
            except Exception:
                pass
    except Exception:
        gpu_model = None

    ram_gb = int(round(psutil.virtual_memory().total / (1024 ** 3)))
    os_name = f"{platform.system()} {platform.release()}"
    # Deduplicate vendors
    vset: Dict[str, bool] = {}
    vlist: List[str] = []
    for v in vendors:
        if v and not vset.get(v):
            vset[v] = True
            vlist.append(v)
    return HardwareInfo(cpu_model, gpu_model, ram_gb, os_name, vlist)


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


def sanitize_payload_for_server(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of payload containing only fields accepted by the server schema.

    Drops any diagnostic fields like 'localError' that would cause 400s
    under the server's strict zod schema.
    """
    try:
        clean: Dict[str, Any] = {}
        for k in _ALLOWED_PAYLOAD_KEYS:
            if k in payload:
                clean[k] = payload[k]
        return clean
    except Exception:
        # Best-effort: if something goes wrong, return original
        return dict(payload)


def is_hardware_encoder_usable(encoder: str) -> bool:
    """Return True if the given hardware encoder appears to be usable on this machine.

    This is stronger than `has_encoder`, which only checks if ffmpeg was compiled
    with the encoder. Here we try a 1-frame encode using a synthetic source.
    Results are cached per-process.
    """
    enc = encoder.strip().lower()
    if enc in _ENCODER_USABLE_CACHE:
        return _ENCODER_USABLE_CACHE[enc]
    # If it's not a known hardware encoder suffix, defer to has_encoder()
    if not enc.endswith(("_nvenc", "_qsv", "_amf", "_videotoolbox", "_vaapi", "_v4l2m2m", "_omx")):
        ok = has_encoder(encoder)
        _ENCODER_USABLE_CACHE[enc] = ok
        return ok
    # Quick 1-frame test encode into a temp file
    try:
        with tempfile.TemporaryDirectory() as td:
            out_path = os.path.join(td, "probe.mp4")
            cmd = [
                ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=size=16x16:rate=1",
                "-frames:v", "1", "-pix_fmt", "yuv420p",
                "-c:v", encoder,
                "-an", out_path,
            ]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=8)
            ok = (proc.returncode == 0) and os.path.exists(out_path) and os.path.getsize(out_path) > 0
            _ENCODER_USABLE_CACHE[enc] = bool(ok)
            return bool(ok)
    except Exception:
        _ENCODER_USABLE_CACHE[enc] = False
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
    hw = detect_hardware()
    def _platform_supports(enc_name: str) -> bool:
        try:
            e = enc_name.strip().lower()
            sysname = platform.system().lower()
            gpu = (hw.gpuModel or "").lower()
            cpu = (hw.cpuModel or "").lower()
            if sysname.startswith('darwin') or sysname.startswith('mac'):
                return e.endswith('_videotoolbox')
            if sysname.startswith('windows'):
                if e.endswith('_nvenc'):
                    return ('nvidia' in hw.gpuVendors)
                if e.endswith('_qsv'):
                    return ('intel' in hw.gpuVendors) or ('intel' in cpu)
                if e.endswith('_amf'):
                    return ('amd' in hw.gpuVendors)
                if e.endswith(('_vaapi', '_v4l2m2m', '_omx')):
                    return False
                return True
            # linux and others
            if e.endswith('_videotoolbox'):
                return False
            if e.endswith('_amf'):
                return False
            if e.endswith('_nvenc'):
                return ('nvidia' in hw.gpuVendors)
            if e.endswith('_qsv'):
                return ('intel' in hw.gpuVendors) or ('intel' in cpu)
            # VAAPI/V4L2/OMX are plausible on linux depending on hardware; allow listing if compiled
            return True
        except Exception:
            return True
    
    for enc, label in candidates:
        # Use ffmpeg-compiled presence to list, actual usability is handled by runtime fallback
        if has_encoder(enc) and _platform_supports(enc):
            available.append((enc, label))
    return available


def list_all_available_encoders() -> List[str]:
    """Return all available encoders (software + hardware) across supported families."""
    encoders: List[str] = []
    hw = detect_hardware()
    def _platform_supports(enc_name: str) -> bool:
        try:
            e = enc_name.strip().lower()
            sysname = platform.system().lower()
            gpu = (hw.gpuModel or "").lower()
            cpu = (hw.cpuModel or "").lower()
            if sysname.startswith('darwin') or sysname.startswith('mac'):
                return e.endswith('_videotoolbox')
            if sysname.startswith('windows'):
                if e.endswith('_nvenc'):
                    return ('nvidia' in hw.gpuVendors)
                if e.endswith('_qsv'):
                    return ('intel' in hw.gpuVendors) or ('intel' in cpu)
                if e.endswith('_amf'):
                    return ('amd' in hw.gpuVendors)
                if e.endswith(('_vaapi', '_v4l2m2m', '_omx')):
                    return False
                return True
            if e.endswith('_videotoolbox'):
                return False
            if e.endswith('_amf'):
                return False
            if e.endswith('_nvenc'):
                return ('nvidia' in hw.gpuVendors)
            if e.endswith('_qsv'):
                return ('intel' in hw.gpuVendors) or ('intel' in cpu)
            return True
        except Exception:
            return True
    # Software encoders
    for fam, sw_list in SOFTWARE_ENCODERS_ORDER.items():
        for enc in sw_list:
            if has_encoder(enc):
                encoders.append(enc)
    # Hardware encoders (only those that appear usable on this machine)
    for fam, hw_list in HARDWARE_ENCODERS.items():
        for enc, _label in hw_list:
            if has_encoder(enc) and _platform_supports(enc):
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
    # Best-effort: ensure TTY is in a sane state (fixes ^M echo on macOS terminals)
    try:
        if sys.stdin and sys.stdin.isatty():
            subprocess.run(["stty", "sane"], check=False)
    except Exception:
        pass
    suffix = " [y/N]: " if default_no else " [Y/n]: "
    ans = input(prompt + suffix).strip().lower()
    if not ans:
        return not default_no
    return ans in ("y", "yes")

def prompt_choice(prompt: str, options: List[str], default_index: int = 0) -> int:
    # Best-effort: ensure TTY is in a sane state (fixes ^M echo on macOS terminals)
    try:
        if sys.stdin and sys.stdin.isatty():
            subprocess.run(["stty", "sane"], check=False)
    except Exception:
        pass
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
    # Best-effort: ensure TTY is in a sane state (fixes ^M echo on macOS terminals)
    try:
        if sys.stdin and sys.stdin.isatty():
            subprocess.run(["stty", "sane"], check=False)
    except Exception:
        pass
    raw = input(f"{prompt} [{default_value}]: ").strip()
    return raw or default_value


def _clear_screen() -> None:
    try:
        os.system("cls" if os.name == "nt" else "clear")
    except Exception:
        pass


def ensure_min_terminal_size(min_cols: int = 100, min_rows: int = 30) -> None:
    """Best-effort to resize terminal to avoid misaligned boxes."""
    try:
        cols, rows = shutil.get_terminal_size((80, 24))
    except Exception:
        cols, rows = (80, 24)
    try:
        if os.name == "nt":
            os.system(f"mode con: cols={max(cols, min_cols)} lines={max(rows, min_rows)}")
        else:
            sys.stdout.write(f"\033[8;{max(rows, min_rows)};{max(cols, min_cols)}t")
            sys.stdout.flush()
    except Exception:
        pass


def confirm_benchmark_readiness() -> bool:
    _clear_screen()
    try:
        width = max(60, min(shutil.get_terminal_size((100, 20)).columns, 100))
    except Exception:
        width = 80
    border = "═" * (width - 2)
    top = f"╔{border}╗"
    bottom = f"╚{border}╝"
    RED = "\033[31;1m"
    RED_BG = "\033[41;97;1m"
    RESET = "\033[0m"
    ansi_re = re.compile(r"\x1b\[[0-9;]*m")
    def _display_len(s: str) -> int:
        try:
            return len(ansi_re.sub("", s))
        except Exception:
            return len(s)
    def center_line(text: str) -> str:
        t = text.strip()
        pad = max(0, width - 2 - _display_len(t))
        left = pad // 2
        right = pad - left
        return f"║{' ' * left}{t}{' ' * right}║"

    print(top)
    print(center_line(f"{RED_BG} Warning! {RESET}"))
    print(center_line(""))
    lines = [
        f"{RED}Please close all programs that may be stealing CPU resources or using your media engine{RESET}",
        f"{RED}(ie. Video Games, Studio Software, Video Playback, Browser, etc.){RESET}",
        "",
        f"{RED}Accurate data is very important! Have you closed all other programs?{RESET}",
    ]
    for ln in lines:
        print(center_line(ln))
    print(center_line(""))
    print(center_line("Type \"yes\" to proceed"))
    print(bottom)

    # Best-effort: ensure TTY is sane for input
    try:
        if sys.stdin and sys.stdin.isatty():
            subprocess.run(["stty", "sane"], check=False)
    except Exception:
        pass
    ans = input("Type \"yes\" to proceed: ").strip().lower()
    return ans == "yes"


def _format_duration(seconds: float) -> str:
    total = int(round(max(0.0, seconds)))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    parts = []
    if h > 0:
        parts.append(f"{h}h")
    if m > 0 or h > 0:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def print_end_screen(completed_count: int, elapsed_seconds: float) -> None:
    try:
        width = max(60, min(shutil.get_terminal_size((100, 20)).columns, 100))
    except Exception:
        width = 80
    border = "═" * (width - 2)
    top = f"╔{border}╗"
    bottom = f"╚{border}╝"
    GREEN = "\033[32;1m"
    MAGENTA = "\033[35;1m"
    GREEN_BG = "\033[42;97;1m"
    RESET = "\033[0m"
    ansi_re = re.compile(r"\x1b\[[0-9;]*m")
    def _display_len(s: str) -> int:
        try:
            return len(ansi_re.sub("", s))
        except Exception:
            return len(s)
    def center_line(text: str) -> str:
        t = text.strip()
        pad = max(0, width - 2 - _display_len(t))
        left = pad // 2
        right = pad - left
        return f"║{' ' * left}{t}{' ' * right}║"
    print(top)
    print(center_line(f"{GREEN_BG} Thank you for completing the benchmark! {RESET}"))
    print(center_line(""))
    time_str = _format_duration(elapsed_seconds)
    print(center_line(f"{GREEN}You supported an open-source database by submitting {completed_count} data points{RESET}"))
    print(center_line(f"{GREEN}and donating {time_str} of your computer's time! {MAGENTA}<3{RESET}"))
    print(bottom)


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


# --- Client-only heuristics and helpers for batched pipeline ---

def get_physical_core_count() -> int:
    """Return the number of physical CPU cores (not threads) if available."""
    try:
        n = psutil.cpu_count(logical=False)
        if isinstance(n, int) and n and n > 0:
            return n
    except Exception:
        pass
    try:
        n_logical = os.cpu_count() or 0
        # Best-effort fallback: assume SMT factor 2 for common desktop CPUs
        return max(1, int(n_logical // 2) if n_logical and n_logical > 1 else int(n_logical or 1))
    except Exception:
        return 4


def resolve_batch_size(requested: Optional[int]) -> int:
    try:
        if isinstance(requested, int) and requested > 0:
            return max(1, requested)
    except Exception:
        pass
    return max(1, int(get_physical_core_count()))


def measure_background_cpu_load(seconds: float = 3.0, interval: float = 0.5) -> float:
    samples: List[float] = []
    elapsed: float = 0.0
    try:
        while elapsed < seconds:
            samples.append(psutil.cpu_percent(interval=interval))
            elapsed += interval
        return float(sum(samples) / max(1, len(samples)))
    except Exception:
        return 0.0


def detect_virtualization(hardware: HardwareInfo) -> Tuple[bool, str]:
    hints: List[str] = []
    # CPU hypervisor flag
    try:
        info = cpuinfo.get_cpu_info() or {}
        flags = set(info.get('flags') or [])
        if 'hypervisor' in flags:
            hints.append('cpu_hypervisor_flag')
    except Exception:
        pass
    # Linux DMI strings (best-effort)
    try:
        dmi_paths = ['/sys/class/dmi/id/product_name', '/sys/class/dmi/id/sys_vendor']
        for p in dmi_paths:
            if os.path.exists(p):
                try:
                    txt = open(p, 'r', encoding='utf-8', errors='ignore').read().lower()
                    if any(x in txt for x in ['kvm', 'qemu', 'vmware', 'virtualbox', 'hyper-v', 'parallels']):
                        hints.append(f'dmi:{os.path.basename(p)}')
                except Exception:
                    continue
    except Exception:
        pass
    # GPU model indicators
    try:
        if hardware.gpuModel and any(x in str(hardware.gpuModel).lower() for x in ['microsoft basic render', 'svga', 'vbox', 'virtio', 'llvmpipe']):
            hints.append('gpu_virtual_like')
    except Exception:
        pass
    reason = ','.join(hints)[:200] if hints else ''
    return (len(hints) > 0, reason)


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
    # If failed with HW encoder, retry with software for same family
    if (proc.returncode != 0 or not os.path.exists(artifact_path) or os.path.getsize(artifact_path) <= 0):
        family = _encoder_family_for(encoder)
        if family:
            sw = pick_software_encoder_for_family(family)
            if sw and sw != encoder and has_encoder(sw):
                try:
                    cmd_sw = build_ffmpeg_encode_cmd(input_path=input_path, output_path=artifact_path, encoder=sw, preset_name=preset, crf=crf)
                    start = time.time()
                    proc = subprocess.run(cmd_sw, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    end = time.time()
                    elapsed = max(0.0001, end - start)
                    encoder = sw
                except Exception:
                    pass
    # Probe frames
    try:
        probe = subprocess.run([
            ffprobe_exe(), '-v', 'error', '-count_frames', '-select_streams', 'v:0',
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


def _median(values: List[float]) -> float:
    v = sorted([float(x) for x in values])
    n = len(v)
    if n == 0:
        return 0.0
    m = n // 2
    if n % 2 == 1:
        return v[m]
    return (v[m - 1] + v[m]) / 2.0


def _mad(values: List[float], med: float) -> float:
    dev = [abs(float(x) - med) for x in values]
    return _median(dev)


def _robust_z(x: float, med: float, mad_val: float) -> float:
    denom = (1.4826 * mad_val) if mad_val > 0 else 1.0
    return (float(x) - med) / denom


def fetch_baseline_rows(base_url: str) -> List[Dict[str, Any]]:
    global _BASELINE_ROWS_CACHE
    if _BASELINE_ROWS_CACHE is not None:
        return _BASELINE_ROWS_CACHE
    try:
        import requests  # lazy import
        url = f"{base_url.rstrip('/')}/query?limit=500"
        r = requests.get(url, timeout=15, verify=REQUESTS_VERIFY)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                _BASELINE_ROWS_CACHE = data
                return data
    except Exception:
        pass
    _BASELINE_ROWS_CACHE = []
    return _BASELINE_ROWS_CACHE


def baseline_is_suspect(current: Dict[str, Any], rows: List[Dict[str, Any]]) -> Tuple[bool, str]:
    try:
        key = (
            current.get('cpuModel'),
            current.get('gpuModel'),
            int(current.get('ramGB') or 0),
            current.get('os'),
            current.get('codec'),
            current.get('preset'),
            int(current.get('crf') if current.get('crf') is not None else 24),
        )
        same = [r for r in rows if (
            r.get('cpuModel') == key[0] and
            (r.get('gpuModel') or None) == key[1] and
            int(r.get('ramGB') or 0) == key[2] and
            r.get('os') == key[3] and
            r.get('codec') == key[4] and
            r.get('preset') == key[5] and
            int(r.get('crf') or 24) == key[6]
        )]
        if not same:
            return (False, '')
        fps_arr = [float(r.get('fps') or 0) for r in same if float(r.get('fps') or 0) > 0]
        size_arr = [float(r.get('fileSizeBytes') or 0) for r in same if float(r.get('fileSizeBytes') or 0) > 0]
        vmaf_arr = [float(r.get('vmaf') or 0) for r in same if r.get('vmaf') is not None]
        fps_med = _median(fps_arr) if fps_arr else float(current.get('fps') or 0)
        size_med = _median(size_arr) if size_arr else float(current.get('fileSizeBytes') or 0)
        vmaf_med = _median(vmaf_arr) if vmaf_arr else float(current.get('vmaf') or 0)
        fps_mad = _mad(fps_arr, fps_med) if fps_arr else 0.0
        size_mad = _mad(size_arr, size_med) if size_arr else 0.0
        vmaf_mad = _mad(vmaf_arr, vmaf_med) if vmaf_arr else 0.0
        fps_z = _robust_z(float(current.get('fps') or 0), fps_med, fps_mad)
        size_z = _robust_z(float(current.get('fileSizeBytes') or 0), size_med, size_mad)
        vmaf_val = current.get('vmaf')
        vmaf_z = _robust_z(float(vmaf_val), vmaf_med, vmaf_mad) if vmaf_val is not None else 0.0
        max_abs = max(abs(fps_z), abs(size_z), abs(vmaf_z))
        if max_abs > 3.0:
            return (True, f'baseline_outlier|z={max_abs:.2f}')
        return (False, '')
    except Exception:
        return (False, '')


def should_skip_submission(*, hardware: HardwareInfo, payload: Dict[str, Any], background_cpu_pct: float, baseline_rows: List[Dict[str, Any]], background_threshold: float = 20.0) -> Tuple[bool, str]:
    # VM detection
    is_vm, vm_reason = detect_virtualization(hardware)
    if is_vm:
        return True, f'vm_detected:{vm_reason}'
    # Background load
    try:
        if background_cpu_pct > background_threshold:
            return True, f'high_background_load:{background_cpu_pct:.1f}%'
    except Exception:
        pass
    # Baseline outlier check
    suspect, reason = baseline_is_suspect(payload, baseline_rows)
    if suspect:
        return True, reason
    return False, ''


def run_benchmark_batch(*, hardware: HardwareInfo, base_url: str, args: argparse.Namespace, tasks: List[Dict[str, Any]]) -> int:
    # Ensure ffmpeg tools and sample file
    ok, ffmpeg_version = ensure_ffmpeg_and_ffprobe()
    if not ok:
        print("ffmpeg/ffprobe not found in PATH. Please install ffmpeg.", file=sys.stderr)
        return 2
    if not has_libvmaf():
        print("Your ffmpeg build does not include libvmaf. Install ffmpeg with libvmaf.", file=sys.stderr)
        return 5
    input_path = get_default_sample_path()
    if not input_path:
        print("Required test video not found (expected sample.mp4 in project root).", file=sys.stderr)
        return 3
    ok_sample, msg = verify_sample_video(input_path)
    if not ok_sample:
        print(
            f"Test video integrity check failed: {msg}.\n"
            "Please use the original, unmodified sample.mp4 included with the client.",
            file=sys.stderr,
        )
        return 6
    input_hash = sha256_of_file(input_path)
    client_version = "client/0.1.0"
    # Resolve workers
    workers = resolve_batch_size(getattr(args, 'batch_size', 0))
    if not getattr(args, 'no_submit', False):
        # Warm baseline cache once
        _ = fetch_baseline_rows(base_url)

    # Process tasks in chunks of `workers`
    completed_count_local = 0
    total_tasks = len(tasks)
    processed_total = 0
    for i in range(0, len(tasks), max(1, workers)):
        chunk = tasks[i:i + max(1, workers)]
        with tempfile.TemporaryDirectory() as batch_dir:
            artifacts_info: List[Dict[str, Any]] = []
            print(f"Encoding batch {i//max(1,workers)+1}: {len(chunk)} task(s) → {batch_dir}")
            for idx, t in enumerate(chunk, start=1):
                enc = t['encoder']
                preset = t['preset']
                crf = t.get('crf')
                bg_load = measure_background_cpu_load(3.0, 0.5)
                name = f"{enc.replace('/', '_')}-{preset}-{str(crf) if crf is not None else 'none'}-{idx}.mp4"
                global_index = processed_total + idx
                try:
                    overall_pct = ((global_index - 1) / max(1, total_tasks)) * 100.0
                except Exception:
                    overall_pct = 0.0
                print(f"  - Encoding {idx}/{len(chunk)} in batch | Overall {global_index-1}/{total_tasks} ({overall_pct:.0f}%) → {enc} {preset} crf={crf}")
                info = encode_to_artifact(input_path=input_path, encoder=enc, preset=preset, crf=crf, out_dir=batch_dir, artifact_name=name)
                info['backgroundCpuPct'] = float(bg_load)
                info['task'] = t
                artifacts_info.append(info)
            # VMAF in parallel
            apaths = [x['artifactPath'] for x in artifacts_info]
            vmaf_map = compute_vmaf_parallel(input_path, apaths, workers)
            # Build and submit payloads
            baseline_rows = fetch_baseline_rows(base_url)
            for info in artifacts_info:
                t = info['task']
                payload: Dict[str, Any] = {
                    'cpuModel': hardware.cpuModel,
                    'gpuModel': hardware.gpuModel or "",
                    'ramGB': hardware.ramGB,
                    'os': hardware.os,
                    'codec': info.get('encoderUsed') or t['encoder'],
                    'preset': t['preset'],
                    'crf': t.get('crf'),
                    'fps': float(info.get('fps') or 0.0),
                    'fileSizeBytes': int(info.get('fileSizeBytes') or 0),
                    'runMs': int(info.get('elapsedMs') or 0),
                    'ffmpegVersion': ffmpeg_version,
                    'encoderName': info.get('encoderUsed') or t['encoder'],
                    'clientVersion': client_version,
                    'inputHash': input_hash,
                }
                vmaf_score = vmaf_map.get(info['artifactPath'])
                if vmaf_score is not None:
                    payload['vmaf'] = float(vmaf_score)
                # Attach any local error snippet
                if info.get('error'):
                    payload['notes'] = str(info['error'])[:500]
                # Gating heuristics
                skip, reason = should_skip_submission(hardware=hardware, payload=payload, background_cpu_pct=float(info.get('backgroundCpuPct') or 0.0), baseline_rows=baseline_rows)
                if skip:
                    print(f"Skipped submission for {payload['codec']} {payload['preset']} (reason: {reason})")
                    # Persist skip to queue for visibility if not no-submit
                    if not args.no_submit:
                        try:
                            os.makedirs(args.queue_dir, exist_ok=True)
                            fname = os.path.join(args.queue_dir, f"{int(time.time()*1000)}-skipped-{payload['preset']}.json")
                            # Never include non-schema keys like 'localError' in the saved payload
                            payload_to_save = dict(payload)
                            if reason:
                                try:
                                    payload_to_save['notes'] = ((payload_to_save.get('notes') or '') + f"; {reason}")[:500]
                                except Exception:
                                    pass
                            with open(fname, 'w', encoding='utf-8') as fh:
                                json.dump(sanitize_payload_for_server(payload_to_save), fh, separators=(',', ':'))
                            print(f"Queued skipped payload for review: {fname}")
                        except Exception as qe:
                            print(f"Failed to queue skipped payload: {qe}", file=sys.stderr)
                    continue
                # Submit
                if args.no_submit:
                    print(f"Dry-run: not submitting {payload['codec']} {payload['preset']}")
                else:
                    try:
                        submit(base_url, sanitize_payload_for_server(payload), api_key=args.api_key, retries=max(1, args.retries), use_token=_env_flag('INGEST_USE_TOKENS', False) or bool(getattr(args, 'use_token', False)))
                        print("Submitted Results")
                    except Exception as e:
                        print(f"Failed to submit {payload['preset']}: {e}", file=sys.stderr)
                        try:
                            os.makedirs(args.queue_dir, exist_ok=True)
                            fname = os.path.join(args.queue_dir, f"{int(time.time()*1000)}-{payload['preset']}.json")
                            with open(fname, 'w', encoding='utf-8') as fh:
                                json.dump(sanitize_payload_for_server(payload), fh, separators=(',', ':'))
                            print(f"Queued for retry: {fname}")
                        except Exception as qe:
                            print(f"Failed to queue payload: {qe}", file=sys.stderr)
                if float(payload.get('fps', 0.0)) > 0.0 and int(payload.get('fileSizeBytes', 0)) > 0:
                    completed_count_local += 1
                    if _BATCH_ACTIVE:
                        global _BATCH_COMPLETED_COUNT
                        _BATCH_COMPLETED_COUNT += 1
                processed_total += 1
                try:
                    overall_pct = (processed_total / max(1, total_tasks)) * 100.0
                except Exception:
                    overall_pct = 100.0
                print(f"Progress: {processed_total}/{total_tasks} ({overall_pct:.0f}%) complete\n")
    return 0


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


def verify_sample_video(path: str) -> Tuple[bool, str]:
    """Return (ok, message). Verifies that sample.mp4 matches expected size and hash.
    """
    try:
        if not os.path.exists(path):
            return False, "sample.mp4 not found"
        size = os.path.getsize(path)
        if int(size) != int(SAMPLE_VIDEO_SIZE_BYTES):
            return False, f"sample.mp4 size mismatch (expected {SAMPLE_VIDEO_SIZE_BYTES}, got {size})"
        digest = sha256_of_file(path)
        if digest.lower() != SAMPLE_VIDEO_SHA256.lower():
            return False, "sample.mp4 checksum mismatch"
        return True, "ok"
    except Exception as e:
        return False, f"verification error: {e}"


def submit(base_url: str, payload: Dict[str, Any], api_key: str = "", retries: int = 3, backoff_seconds: float = 1.0, use_token: Optional[bool] = None) -> None:
    import requests  # lazy import
    url = f"{base_url.rstrip('/')}/submit"
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    # Fetch submit token (and optional PoW) if server runs in public/hybrid mode
    if use_token is None:
        use_token = _env_flag('INGEST_USE_TOKENS', False)
    if use_token:
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
            if tokenResp and tokenResp.status_code == 200:
                tokenData = tokenResp.json() or {}
                token = str(tokenData.get('token') or '')
                powInfo = tokenData.get('pow') or {}
                # Accept only real issued tokens (32 hex chars); ignore placeholders like 'direct'
                if token and re.fullmatch(r"[0-9a-f]{32}", token):
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
            # If token fetch fails or invalid, continue unsigned
        except Exception as te:
            try:
                print(f"token fetch error: {te}", file=sys.stderr)
            except Exception:
                pass
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
            # Avoid infinite redirect loops; follow at most once manually
            r = requests.post(url, data=body, timeout=30, headers=headers, verify=REQUESTS_VERIFY, allow_redirects=False)
            if 300 <= r.status_code < 400:
                loc = r.headers.get('Location') or r.headers.get('location')
                if loc:
                    # Re-issue once to the redirect target
                    r = requests.post(loc, data=body, timeout=30, headers=headers, verify=REQUESTS_VERIFY, allow_redirects=False)
            # Handle rate limiting gracefully
            if r.status_code == 429:
                try:
                    ra = r.headers.get('Retry-After')
                    delay = float(ra) if ra and str(ra).replace('.', '', 1).isdigit() else (backoff_seconds * attempt * 2)
                except Exception:
                    delay = backoff_seconds * attempt * 2
                time.sleep(max(0.5, delay))
                continue
            if r.status_code >= 500:
                raise RuntimeError(f"server_error {r.status_code}")
            r.raise_for_status()
            return
        except Exception as e:
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
    p.add_argument("--api-key", default=ENV_API_KEY, help="API key for submission (default: env API_KEY)")
    p.add_argument("--codec", default=ENV_CODEC, help="FFmpeg video encoder or codec family (e.g., libx264, h264, av1). If omitted, will prompt.")
    p.add_argument("--presets", default=ENV_PRESETS, help="Comma-separated list of presets (default: fast,medium,slow)")
    p.add_argument("--no-submit", action="store_true", help="Run tests but do not submit results")
    p.add_argument("--crf", type=int, default=int(ENV_CRF) if ENV_CRF.isdigit() else 24, help="Constant Rate Factor (encoder-dependent). Defaults to 24.")
    p.add_argument("--retries", type=int, default=3, help="Submission retry attempts (default: 3)")
    p.add_argument("--queue-dir", default=ENV_QUEUE_DIR, help="Directory for offline retry queue")
    p.add_argument("--menu", action="store_true", help="Force interactive menu even if arguments are provided")
    p.add_argument("--batch-size", type=int, default=0, help="Batch size for parallel VMAF (0=auto: cpu_count or 4)")
    p.add_argument("--use-token", action="store_true", help="Use short-lived submit token (opt-in; or set INGEST_USE_TOKENS=1)")
    p.add_argument("--pause-on-exit", action="store_true", help="On Windows, wait for Enter key after completion to keep the window open")
    return p


def run_with_args(args: argparse.Namespace) -> int:
    global _FFMPEG_DETECTED_PRINTED, _BATCH_ACTIVE, _BATCH_START_TS, _BATCH_COMPLETED_COUNT
    ok, ffmpeg_version = ensure_ffmpeg_and_ffprobe()
    if not ok:
        print("ffmpeg/ffprobe not found in PATH. Please install ffmpeg.", file=sys.stderr)
        return 2
    if not _FFMPEG_DETECTED_PRINTED:
        # Parse concise version number, fallback to 'unknown'
        ver = "unknown"
        try:
            m = re.search(r"version\s*([\w\.-]+)", ffmpeg_version or "", flags=re.IGNORECASE)
            if m:
                ver = m.group(1)
        except Exception:
            ver = "unknown"
        print(f"FFmpeg (Version {ver}) Detected")
        _FFMPEG_DETECTED_PRINTED = True
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
    ok_sample, msg = verify_sample_video(input_path)
    if not ok_sample:
        print(
            f"Test video integrity check failed: {msg}.\n"
            "Please use the original, unmodified sample.mp4 included with the client.",
            file=sys.stderr,
        )
        return 6

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
    benchmark_start_ts = time.time()
    # Pre-compute original sample size for relative size reporting
    try:
        original_size_bytes = os.path.getsize(input_path)
    except Exception:
        original_size_bytes = 0
    completed_count = 0
    for preset, crf_val in combos:
        print(f"Running Test: {resolved_encoder}, crf={crf_val}, {preset}...")
        payload = run_single_benchmark(hardware, input_path, preset=preset, codec=resolved_encoder, crf=crf_val)
        # Attach submission metadata
        payload["ffmpegVersion"] = ffmpeg_version
        payload["encoderName"] = payload.get("codec", resolved_encoder)
        payload["clientVersion"] = client_version
        payload["inputHash"] = input_hash
        # runMs is already populated by run_single_benchmark based on encode timing
        all_payloads.append(payload)
        # Compact metrics block
        fps_val = payload.get("fps")
        vmaf_val = payload.get("vmaf")
        size_val = payload.get("fileSizeBytes")
        try:
            rel_size = (float(size_val) / float(original_size_bytes) * 100.0) if original_size_bytes > 0 else None
        except Exception:
            rel_size = None
        print("\n|---------------------------")
        try:
            print(f"| FPS: {float(fps_val):.2f}")
        except Exception:
            print("| FPS: N/A")
        print("|---------------------------")
        if vmaf_val is not None:
            try:
                print(f"| VMAF: {float(vmaf_val):.2f}")
            except Exception:
                print("| VMAF: N/A")
        else:
            print("| VMAF: N/A")
        print("|---------------------------")
        if rel_size is not None:
            try:
                print(f"| Relative File Size: {rel_size:.1f}%")
            except Exception:
                print("| Relative File Size: N/A")
        else:
            print("| Relative File Size: N/A")
        print("|---------------------------\n")
        if float(payload.get("fps", 0.0)) > 0.0 and int(payload.get("fileSizeBytes", 0)) > 0:
            completed_count += 1
            if _BATCH_ACTIVE:
                _BATCH_COMPLETED_COUNT += 1
        if args.no_submit:
            print(f"Dry-run: not submitting preset={preset}")
            continue
        try:
            # Skip submission if encode failed obviously
            if payload.get("fps", 0.0) <= 0 or payload.get("fileSizeBytes", 0) <= 0:
                print(f"Skipped submission for preset={preset} due to encode failure (fps={payload.get('fps')}, size={payload.get('fileSizeBytes')})")
                all_payloads.append({**payload, "localError": True})
                continue
            submit(base_url, payload, api_key=args.api_key, retries=max(1, args.retries))
            print("Submitted Results")
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
                clean_payload = sanitize_payload_for_server(payload if isinstance(payload, dict) else {})
                submit(base_url, clean_payload, api_key=args.api_key, retries=max(1, args.retries))
                os.remove(fpath)
                print(f"Retried and submitted: {fn}")
            except Exception:
                # keep for next run
                pass
    except Exception:
        pass
    # End-of-benchmark screen: only show for single runs or when batch is not active
    if not _BATCH_ACTIVE:
        _clear_screen()
        elapsed_sec = max(0.0, time.time() - benchmark_start_ts)
        print_end_screen(completed_count, elapsed_sec)
        # Optional pause on Windows: keep the console open for end screen visibility
        try:
            if os.name == 'nt' and (bool(getattr(args, 'pause_on_exit', False)) or bool(getattr(sys, 'frozen', False))):
                input("Press Enter to exit...")
        except Exception:
            pass
    # Suppress verbose JSON output for cleaner UI
    return 0


def interactive_menu_flow(parser: argparse.ArgumentParser, base_args: argparse.Namespace) -> int:
    # Verify test video integrity FIRST (before any other output)
    # Best-effort: reset TTY to sane mode at start of interactive session
    try:
        if sys.stdin and sys.stdin.isatty():
            subprocess.run(["stty", "sane"], check=False)
    except Exception:
        pass
    GREEN = "\033[32;1m"
    RESET = "\033[0m"
    sample_path = get_default_sample_path()
    if not sample_path:
        print("Required test video not found (expected sample.mp4 in project root).", file=sys.stderr)
        return 3
    ok_sample, msg = verify_sample_video(sample_path)
    if not ok_sample:
        print(
            f"Test video integrity check failed: {msg}.\n"
            "Please use the original, unmodified sample.mp4 included with the client.",
            file=sys.stderr,
        )
        return 6
    print(f"Test Video Checksum {GREEN}Verified{RESET}")
    print("")
    # Load presets for dynamic approx durations
    presets_cfg = load_presets_config(PRESETS_CONFIG_PATH)
    s_minutes = int(presets_cfg.get("smallBenchmark", {}).get("approxMinutes", 5))
    m_minutes = int(presets_cfg.get("mediumBenchmark", presets_cfg.get("smallBenchmark", {})).get("approxMinutes", 20))
    f_hours = presets_cfg.get("fullBenchmark", {}).get("approxHours")
    try:
        f_hours = int(f_hours) if isinstance(f_hours, int) else float(f_hours)
    except Exception:
        f_hours = 3
    # Print menu
    print("Select an option:")
    menu = [
        "Run Single Benchmark",
        f"Run Small Benchmark [~{s_minutes} minutes]",
        f"Run Medium Benchmark [~{m_minutes} minutes]",
        f"Run Full Benchmark [~{f_hours} hours]",
        "Exit",
    ]
    choice = prompt_choice("Menu", menu, default_index=0)
    if choice == 4:
        return 0

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
    # For Small or Full benchmark, require explicit readiness confirmation
    if choice in (1, 2, 3):
        ok = confirm_benchmark_readiness()
        if not ok:
            print("Aborted by user. Please close other programs and try again.")
            return 0
        _clear_screen()
    # Now enumerate all encoders and run each CRF across all encoders and all their supported presets
    # Activate batch mode for Small/Full to aggregate results and show a single end screen
    global _BATCH_ACTIVE, _BATCH_START_TS, _BATCH_COMPLETED_COUNT
    _BATCH_ACTIVE = True
    _BATCH_START_TS = time.time()
    _BATCH_COMPLETED_COUNT = 0
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
        # Map: choice 1=Small(new), 2=Medium(previous smallBenchmark), 3=Full(fullBenchmark)
        if choice == 1:
            # Small: use a single CRF (prefer 24) and restrict presets in construction later
            small_defaults = presets_cfg.get("smallBenchmark", {}).get("crfValues", [])
            crf_values = [int(small_defaults[0])] if small_defaults else [24]
        elif choice == 2:
            crf_values = [int(v) for v in presets_cfg.get("mediumBenchmark", presets_cfg.get("smallBenchmark", {})).get("crfValues", []) if isinstance(v, int)]
            if not crf_values:
                crf_values = [24]
        else:
            crf_values = [int(v) for v in presets_cfg.get("fullBenchmark", {}).get("crfValues", []) if isinstance(v, int)]
            if not crf_values:
                crf_values = [24]

    # Build batched tasks list
    tasks: List[Dict[str, Any]] = []
    for crf_val in crf_values:
        for enc in encoders:
            presets_for_encoder = enumerate_supported_presets_for_encoder(enc)
            ordered = sort_presets_by_speed_desc(enc, presets_for_encoder)
            if choice == 1:
                # Small: pick middle preset + two faster ones (if available)
                if not ordered:
                    continue
                mid_index = max(0, (len(ordered) - 1) // 2)
                picks: List[str] = []
                # two faster -> indices just before mid in speed-desc ordering
                faster1 = mid_index - 1
                faster2 = mid_index - 2
                if faster2 >= 0:
                    picks.append(ordered[faster2])
                if faster1 >= 0:
                    picks.append(ordered[faster1])
                picks.append(ordered[mid_index])
                # Deduplicate preserve order
                seen: Dict[str, bool] = {}
                final = [p for p in picks if not seen.setdefault(p, False)]
                for preset_label in final:
                    tasks.append({'encoder': enc, 'preset': preset_label, 'crf': crf_val})
            elif choice == 2:
                # Medium: previous "Small" behavior – drop slowest 20%
                if len(ordered) > 0:
                    drop_count = int(round(len(ordered) * 0.2))
                    if drop_count >= len(ordered):
                        drop_count = len(ordered) - 1
                    keep = ordered[:-drop_count] if drop_count > 0 else ordered
                else:
                    keep = ordered
                for preset_label in keep:
                    tasks.append({'encoder': enc, 'preset': preset_label, 'crf': crf_val})
            else:
                # Full: all presets
                for preset_label in ordered:
                    tasks.append({'encoder': enc, 'preset': preset_label, 'crf': crf_val})

    # Run batched pipeline
    rc = run_benchmark_batch(
        hardware=detect_hardware(),
        base_url=base_args.base_url,
        args=argparse.Namespace(
            base_url=base_args.base_url,
            api_key=base_args.api_key,
            no_submit=base_args.no_submit,
            crf=None,  # not used by batch function
            retries=base_args.retries,
            queue_dir=base_args.queue_dir,
            menu=False,
            batch_size=getattr(base_args, 'batch_size', 0),
        ),
        tasks=tasks,
    )
    # Deactivate batch mode and print a single end screen
    elapsed_sec = max(0.0, time.time() - _BATCH_START_TS)
    _clear_screen()
    print_end_screen(_BATCH_COMPLETED_COUNT, elapsed_sec)
    _BATCH_ACTIVE = False
    return rc


def main(argv: List[str]) -> int:
    # Handle PyInstaller multiprocessing arguments on Windows
    if len(argv) > 1 and argv[1].startswith('--multiprocessing-fork'):
        # This is a multiprocessing child process, exit immediately
        return 0
    
    parser = build_arg_parser()
    args = parser.parse_args(argv[1:])
    # Always show interactive menu for benchmarks
    return interactive_menu_flow(parser, args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
