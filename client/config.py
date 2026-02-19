import os
import platform
import shutil
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple

# Thread lock for global state accessed during parallel operations
_GLOBAL_STATE_LOCK = threading.Lock()

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

_ALLOWED_PAYLOAD_KEYS: Tuple[str, ...] = (
    'cpuModel', 'gpuModel', 'ramGB', 'os',
    'codec', 'preset', 'crf', 'contentClass', 'resolution', 'passes',
    'fps', 'vmaf', 'ssim', 'psnr', 'fileSizeBytes', 'notes',
    'ffmpegVersion', 'encoderName', 'clientVersion', 'inputHash', 'runMs',
    'gpuUtilAvg', 'gpuPowerAvgW', 'gpuMemPeakMB',
    'cpuUtilAvg', 'cpuUtilMax', 'peakMemoryMB', 'thermalThrottle',
    # Extended telemetry (Sprint 7)
    'gpuTempMaxC', 'cpuFreqAvgMHz', 'cpuTempMaxC',
    'ffmpegCpuUtilAvg', 'ffmpegCpuUtilMax',
    'ffmpegReadMB', 'ffmpegWriteMB', 'ffmpegCpuTimeS',
    'batteryPercentStart', 'batteryPercentEnd', 'batteryPercentDrop',
    'powerSource', 'sampleCount', 'monitorDurationMs',
)

# Batch aggregation for Small/Full multi-run flows
_BATCH_ACTIVE: bool = False
_BATCH_START_TS: float = 0.0
_BATCH_COMPLETED_COUNT: int = 0

# Baseline cache for client-side outlier checks (populated lazily per session)
_BASELINE_ROWS_CACHE: Optional[List[Dict[str, Any]]] = None
_BASELINE_ROWS_CACHE_TS: float = 0.0
_BASELINE_ROWS_CACHE_TTL: float = 1800.0  # 30 minutes

# --- Cross-platform binary resolution helpers ---

_FFMPEG_EXE: Optional[str] = None
_FFPROBE_EXE: Optional[str] = None
# Print FFmpeg detected banner only once per session
_FFMPEG_DETECTED_PRINTED: bool = False
# Cache for probing hardware encoder usability so we do not repeatedly run ffmpeg
_ENCODER_USABLE_CACHE: Dict[str, bool] = {}


@dataclass
class HardwareInfo:
    cpuModel: str
    gpuModel: Optional[str]
    ramGB: int
    os: str
    gpuVendors: List[str] = field(default_factory=list)


def _env_flag(name: str, default: bool = False) -> bool:
    try:
        v = os.environ.get(name, "")
        return str(v).strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        return default


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
    # Bundled binary first — ensures PyInstaller builds use the included ffmpeg (with libvmaf)
    for n in names:
        candidates.append(_resource_path("bin", plat, n))
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
    return candidates


def _candidate_ffprobe_paths() -> List[str]:
    plat = _platform_key()
    names = ["ffprobe"] if plat != "win" else ["ffprobe.exe", "ffprobe"]
    candidates: List[str] = []
    env_ffprobe = os.environ.get("FFPROBE_EXE")
    if env_ffprobe:
        candidates.append(env_ffprobe)
    # Bundled binary first — ensures PyInstaller builds use the included ffprobe
    for n in names:
        candidates.append(_resource_path("bin", plat, n))
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
    return candidates


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


def sanitize_payload_for_server(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of payload containing only fields accepted by the server schema."""
    try:
        clean: Dict[str, Any] = {}
        for k in _ALLOWED_PAYLOAD_KEYS:
            if k in payload:
                clean[k] = payload[k]
        return clean
    except Exception:
        return dict(payload)


# --- Queue directory validation ---

class QueueDirError(Exception):
    """Raised when the queue directory path is invalid or unsafe."""
    pass


# System directories that should never be used as a queue directory
_SYSTEM_DIRS = frozenset([
    '/etc', '/usr', '/bin', '/sbin', '/lib', '/lib64',
    '/boot', '/dev', '/proc', '/sys', '/run',
    '/var/run', '/var/lock',
    'C:\\Windows', 'C:\\Windows\\System32',
])


def validate_queue_dir(path: str) -> str:
    """Validate and return a safe, resolved queue directory path.

    Resolves symlinks, rejects system directories, and ensures the directory
    exists and is writable (or creates it with mode 0o700).

    Raises QueueDirError on failure.
    """
    if not path or not path.strip():
        raise QueueDirError("Queue directory path is empty")

    resolved = os.path.realpath(path)

    # Check path is under a safe parent (temp dir, home dir, or cwd)
    safe_parents = []
    try:
        safe_parents.append(os.path.realpath(tempfile.gettempdir()))
    except Exception:
        pass
    try:
        home = os.path.expanduser("~")
        if home and home != "~":
            safe_parents.append(os.path.realpath(home))
    except Exception:
        pass
    try:
        safe_parents.append(os.path.realpath(os.getcwd()))
    except Exception:
        pass

    is_under_safe = any(
        resolved == sp or resolved.startswith(sp + os.sep)
        for sp in safe_parents if sp
    )
    if not is_under_safe:
        raise QueueDirError(
            f"Queue directory '{resolved}' is not under a recognized safe parent "
            f"(temp dir, home dir, or cwd)"
        )

    # Reject system directories
    for sys_dir in _SYSTEM_DIRS:
        sys_resolved = os.path.realpath(sys_dir) if os.path.exists(sys_dir) else sys_dir
        if resolved == sys_resolved or resolved.startswith(sys_resolved + os.sep):
            raise QueueDirError(f"Queue directory '{resolved}' is inside system directory '{sys_dir}'")

    # Ensure directory exists and is writable, or create it
    if os.path.exists(resolved):
        if not os.path.isdir(resolved):
            raise QueueDirError(f"Queue path '{resolved}' exists but is not a directory")
        if not os.access(resolved, os.W_OK):
            raise QueueDirError(f"Queue directory '{resolved}' is not writable")
    else:
        try:
            os.makedirs(resolved, mode=0o700, exist_ok=True)
        except OSError as e:
            raise QueueDirError(f"Cannot create queue directory '{resolved}': {e}") from e

    return resolved
