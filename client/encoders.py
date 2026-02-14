import platform
import re
import subprocess
import tempfile
import os
from typing import Optional, Dict, List, Tuple

from . import config
from .hardware import detect_hardware


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


def exec_ok(cmd: List[str]) -> bool:
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def ensure_ffmpeg_and_ffprobe() -> Tuple[bool, Optional[str]]:
    if not exec_ok([config.ffmpeg_exe(), "-version"]) or not exec_ok([config.ffprobe_exe(), "-version"]):
        return False, None
    try:
        out = subprocess.run([config.ffmpeg_exe(), "-version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        version_line = (out.stdout or "").splitlines()[0] if out.stdout else ""
    except Exception:
        version_line = ""
    return True, version_line


def has_encoder(encoder: str) -> bool:
    try:
        out = subprocess.run([config.ffmpeg_exe(), "-hide_banner", "-encoders"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        return encoder in (out.stdout or "")
    except Exception:
        return False


def is_hardware_encoder_usable(encoder: str) -> bool:
    """Return True if the given hardware encoder appears to be usable on this machine."""
    enc = encoder.strip().lower()

    with config._GLOBAL_STATE_LOCK:
        if enc in config._ENCODER_USABLE_CACHE:
            return config._ENCODER_USABLE_CACHE[enc]

    if not enc.endswith(("_nvenc", "_qsv", "_amf", "_videotoolbox", "_vaapi", "_v4l2m2m", "_omx")):
        ok = has_encoder(encoder)
        with config._GLOBAL_STATE_LOCK:
            config._ENCODER_USABLE_CACHE[enc] = ok
        return ok

    try:
        with tempfile.TemporaryDirectory() as td:
            out_path = os.path.join(td, "probe.mp4")
            cmd = [
                config.ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=size=16x16:rate=1",
                "-frames:v", "1", "-pix_fmt", "yuv420p",
                "-c:v", encoder,
                "-an", out_path,
            ]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=8)
            ok = (proc.returncode == 0) and os.path.exists(out_path) and os.path.getsize(out_path) > 0
            with config._GLOBAL_STATE_LOCK:
                config._ENCODER_USABLE_CACHE[enc] = bool(ok)
            return bool(ok)
    except Exception:
        with config._GLOBAL_STATE_LOCK:
            config._ENCODER_USABLE_CACHE[enc] = False
        return False


def has_libvmaf() -> bool:
    try:
        out = subprocess.run([config.ffmpeg_exe(), "-hide_banner", "-filters"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        return "libvmaf" in (out.stdout or "")
    except Exception:
        return False


def normalize_codec_family(user_input: str) -> Optional[str]:
    key = re.sub(r"[^a-z0-9]", "", (user_input or "").strip().lower())
    return CODEC_ALIASES.get(key)


def pick_software_encoder_for_family(family: str) -> Optional[str]:
    for enc in SOFTWARE_ENCODERS_ORDER.get(family, []):
        if has_encoder(enc):
            return enc
    return None


def _platform_supports_encoder(enc_name: str, hw: config.HardwareInfo) -> bool:
    """Check if the current platform likely supports the given hardware encoder."""
    try:
        e = enc_name.strip().lower()
        sysname = platform.system().lower()
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


def discover_hardware_encoders_for_family(family: str) -> List[Tuple[str, str]]:
    candidates = HARDWARE_ENCODERS.get(family, [])
    available: List[Tuple[str, str]] = []
    hw = detect_hardware()

    for enc, label in candidates:
        if has_encoder(enc) and _platform_supports_encoder(enc, hw):
            available.append((enc, label))
    return available


def list_all_available_encoders() -> List[str]:
    """Return all available encoders (software + hardware) across supported families."""
    encoders: List[str] = []
    hw = detect_hardware()

    for fam, sw_list in SOFTWARE_ENCODERS_ORDER.items():
        for enc in sw_list:
            if has_encoder(enc):
                encoders.append(enc)
    for fam, hw_list in HARDWARE_ENCODERS.items():
        for enc, _label in hw_list:
            if has_encoder(enc) and _platform_supports_encoder(enc, hw):
                encoders.append(enc)
    seen: Dict[str, bool] = {}
    uniq: List[str] = []
    for enc in encoders:
        if enc not in seen:
            seen[enc] = True
            uniq.append(enc)
    return uniq


def enumerate_supported_presets_for_encoder(encoder: str) -> List[str]:
    e = encoder.strip().lower()
    if e in ("libx264", "libx265"):
        return [
            "ultrafast", "superfast", "veryfast", "faster", "fast",
            "medium", "slow", "slower", "veryslow", "placebo",
        ]
    if e == "libsvtav1":
        return [str(n) for n in range(0, 14)]
    if e == "libaom-av1":
        return [str(n) for n in range(0, 9)]
    if e == "libvpx-vp9":
        return [str(n) for n in range(0, 9)]
    if e.endswith("_nvenc"):
        return ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]
    if e.endswith("_qsv"):
        return ["faster", "fast", "medium", "slow"]
    if e.endswith("_amf"):
        return ["fast", "medium", "slow"]
    if e.endswith("_videotoolbox"):
        return ["default"]
    if e.endswith("_vaapi"):
        return ["default"]
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
    for family, sw_list in SOFTWARE_ENCODERS_ORDER.items():
        if encoder in sw_list:
            return family
    for family, hw_list in HARDWARE_ENCODERS.items():
        for enc, _label in hw_list:
            if enc == encoder:
                return family
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
    engine = _hardware_engine_label(e)
    if engine:
        return f"{fam_label} ({engine})"
    return e


def sort_presets_by_speed_desc(encoder: str, presets: List[str]) -> List[str]:
    """Return presets ordered from fastest to slowest for given encoder."""
    e = encoder.strip().lower()
    if e in ("libx264", "libx265"):
        ordering = [
            "ultrafast", "superfast", "veryfast", "faster", "fast",
            "medium", "slow", "slower", "veryslow", "placebo",
        ]
        order_index = {name: i for i, name in enumerate(ordering)}
        return sorted(presets, key=lambda n: order_index.get(n, len(ordering)))
    if e == "libsvtav1":
        def speed_key(n: str) -> int:
            try:
                return -int(n)
            except Exception:
                return 0
        return sorted(presets, key=speed_key)
    if e == "libaom-av1":
        def speed_key(n: str) -> int:
            try:
                return -int(n)
            except Exception:
                return 0
        return sorted(presets, key=speed_key)
    if e == "libvpx-vp9":
        def speed_key(n: str) -> int:
            try:
                return -int(n)
            except Exception:
                return 0
        return sorted(presets, key=speed_key)
    if e.endswith("_nvenc"):
        ordering = ["p7", "p6", "p5", "p4", "p3", "p2", "p1"]
        order_index = {name: i for i, name in enumerate(ordering)}
        return sorted(presets, key=lambda n: order_index.get(n, len(ordering)))
    if e.endswith("_qsv"):
        ordering = ["faster", "fast", "medium", "slow"]
        order_index = {name: i for i, name in enumerate(ordering)}
        return sorted(presets, key=lambda n: order_index.get(n, len(ordering)))
    if e.endswith("_amf"):
        ordering = ["fast", "medium", "slow"]
        order_index = {name: i for i, name in enumerate(ordering)}
        return sorted(presets, key=lambda n: order_index.get(n, len(ordering)))
    return presets


def map_preset_for_encoder(encoder: str, preset_name: str) -> List[str]:
    name = preset_name.strip().lower() if preset_name else "medium"
    e = encoder.strip().lower()
    if e in ("libx264", "libx265"):
        valid = {
            "ultrafast": "ultrafast", "superfast": "superfast", "veryfast": "veryfast",
            "faster": "faster", "fast": "fast", "medium": "medium",
            "slow": "slow", "slower": "slower", "veryslow": "veryslow", "placebo": "placebo",
        }
        return ["-preset", valid.get(name, "medium")]
    if e == "libsvtav1":
        if name.isdigit():
            return ["-preset", name]
        svt = {"ultrafast": "13", "veryfast": "11", "fast": "10", "medium": "8", "slow": "6", "veryslow": "4"}
        return ["-preset", svt.get(name, "8")]
    if e == "libaom-av1":
        if name.isdigit():
            return ["-cpu-used", name, "-row-mt", "1"]
        aom = {"ultrafast": 8, "veryfast": 7, "fast": 6, "medium": 4, "slow": 3, "veryslow": 2}
        return ["-cpu-used", str(aom.get(name, 6)), "-row-mt", "1"]
    if e == "libvpx-vp9":
        if name.isdigit():
            return ["-deadline", "good", "-cpu-used", name]
        vp9 = {"ultrafast": 5, "veryfast": 4, "fast": 3, "medium": 2, "slow": 1, "veryslow": 0}
        return ["-deadline", "good", "-cpu-used", str(vp9.get(name, 2))]
    if e.endswith("_nvenc"):
        if re.fullmatch(r"p[1-7]", name):
            return ["-preset", name]
        nv = {"ultrafast": "p7", "veryfast": "p6", "fast": "p5", "medium": "p4", "slow": "p3", "veryslow": "p2"}
        return ["-preset", nv.get(name, "p4")]
    if e.endswith("_qsv"):
        qsv = {"faster": "faster", "fast": "fast", "medium": "medium", "slow": "slow"}
        return ["-preset", qsv.get(name, "medium")]
    if e.endswith("_amf"):
        amf = {"fast": "speed", "medium": "balanced", "slow": "quality"}
        return ["-quality", amf.get(name, "balanced")]
    return []
