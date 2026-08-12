import hashlib
import json
import os
import platform
import re
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import config


RATE_CONTROL_MODE_ALIASES: Dict[str, str] = {
    "abr": "abr",
    "average-bitrate": "abr",
    "average_bitrate": "abr",
    "cbr": "cbr",
    "constant-bitrate": "cbr",
    "constant_bitrate": "cbr",
    "constant-quality": "cq",
    "constant_quality": "cq",
    "cq": "cq",
    "cqp": "cqp",
    "crf": "crf",
    "global-quality": "icq",
    "global_quality": "icq",
    "icq": "icq",
    "other": "other",
    "qp": "qp",
    "quality": "cq",
    "target-bitrate": "vbr",
    "target_bitrate": "vbr",
    "vbr": "vbr",
}

CONTAINER_FORMAT_ALIASES: Dict[str, str] = {
    "mov": "mp4",
    "mp4": "mp4",
    "m4v": "mp4",
    "3gp": "mp4",
    "3g2": "mp4",
    "matroska": "mkv",
    "webm": "webm",
}

PIXEL_FORMAT_ALIASES: Dict[str, str] = {
    "nv12": "nv12",
    "p010": "p010le",
    "p010le": "p010le",
    "yuv420p": "yuv420p",
    "yuv420p10": "yuv420p10le",
    "yuv420p10le": "yuv420p10le",
    "yuv422p": "yuv422p",
    "yuv422p10": "yuv422p10le",
    "yuv422p10le": "yuv422p10le",
    "yuv444p": "yuv444p",
    "yuv444p10": "yuv444p10le",
    "yuv444p10le": "yuv444p10le",
}

CHROMA_BY_PIXEL_FORMAT: Dict[str, str] = {
    "nv12": "4:2:0",
    "p010le": "4:2:0",
    "yuv420p": "4:2:0",
    "yuv420p10le": "4:2:0",
    "yuv422p": "4:2:2",
    "yuv422p10le": "4:2:2",
    "yuv444p": "4:4:4",
    "yuv444p10le": "4:4:4",
}

BIT_DEPTH_BY_PIXEL_FORMAT: Dict[str, int] = {
    "nv12": 8,
    "p010le": 10,
    "yuv420p": 8,
    "yuv420p10le": 10,
    "yuv422p": 8,
    "yuv422p10le": 10,
    "yuv444p": 8,
    "yuv444p10le": 10,
}

SOFTWARE_ENCODER_MODES: Dict[str, str] = {
    "libaom-av1": "crf",
    "libopenh264": "crf",
    "libsvtav1": "crf",
    "libvpx-vp9": "crf",
    "libx264": "crf",
    "libx265": "crf",
}


@dataclass(frozen=True)
class RateControlConfig:
    mode: str
    qualityValue: Optional[float] = None
    targetBitrateKbps: Optional[int] = None
    maxBitrateKbps: Optional[int] = None
    bufferSizeKbits: Optional[int] = None
    qmin: Optional[int] = None
    qmax: Optional[int] = None
    nativeOptions: Dict[str, Any] = field(default_factory=dict)
    nativeArguments: Tuple[Tuple[str, Any], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class OutputIdentity:
    containerFormat: Optional[str] = None
    pixelFormat: Optional[str] = None
    bitDepth: Optional[int] = None
    chromaSubsampling: Optional[str] = None
    profile: Optional[str] = None
    level: Optional[str] = None
    tier: Optional[str] = None
    gopFrames: Optional[int] = None
    keyintMin: Optional[int] = None
    maxBFrames: Optional[int] = None
    bFrameReordering: Optional[bool] = None
    filmGrainSynthesis: Optional[int] = None
    lookaheadFrames: Optional[int] = None
    videoTag: Optional[str] = None
    timeBase: Optional[str] = None


@dataclass(frozen=True)
class RecipeIdentity:
    codecFamily: str
    encoderImplementation: str
    encoderNameRequested: str
    encoderNameEffective: str
    encoderVersion: Optional[str]
    presetRequested: Optional[str]
    presetEffective: Optional[str]
    tune: Optional[str]
    profile: Optional[str]
    level: Optional[str]
    tier: Optional[str]
    rateControlRequested: RateControlConfig
    rateControlEffective: RateControlConfig
    outputRequested: OutputIdentity
    outputEffective: OutputIdentity
    nativeOptionsRequested: Dict[str, Any] = field(default_factory=dict)
    nativeOptionsEffective: Dict[str, Any] = field(default_factory=dict)
    nativeArgumentsRequested: Tuple[Tuple[str, Any], ...] = field(default_factory=tuple)
    nativeArgumentsEffective: Tuple[Tuple[str, Any], ...] = field(default_factory=tuple)
    friendlyDescription: Optional[str] = None


@dataclass(frozen=True)
class EnvironmentIdentity:
    cpuArchitecture: str
    cpuPhysicalCores: int
    cpuLogicalCores: int
    physicalMemoryBytes: Optional[int]
    accelerator: Optional[str]
    driverVersion: Optional[str]
    gpuModel: Optional[str]
    osName: str
    osVersion: str
    ffmpegVersion: Optional[str]
    ffmpegBuildFingerprint: Optional[str]
    encoderVersion: Optional[str]
    clientVersion: Optional[str]
    benchmarkProtocolVersion: Optional[str]


def canonical_encoder_name(value: str) -> str:
    return str(value or "").strip().lower()


def normalize_rate_control_mode(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    key = str(value).strip().lower().replace(" ", "-").replace("_", "-")
    return RATE_CONTROL_MODE_ALIASES.get(key, key or None)


def normalize_native_option_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    while text.startswith("-"):
        text = text[1:]
    return text.replace("_", "-")


def normalize_native_options(options: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    if not options:
        return normalized
    for key, value in options.items():
        normalized[normalize_native_option_name(key)] = _normalize_json_value(value)
    return dict(sorted(normalized.items(), key=lambda item: item[0]))


def normalize_container_format(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    raw = str(value).strip().lower()
    if not raw:
        return None
    for token in re.split(r"[\s,]+", raw):
        normalized = CONTAINER_FORMAT_ALIASES.get(token)
        if normalized:
            return normalized
    return CONTAINER_FORMAT_ALIASES.get(raw, raw)


def normalize_native_arguments(arguments: Optional[Sequence[Any]]) -> Tuple[Tuple[str, Any], ...]:
    if not arguments:
        return tuple()
    items = list(arguments)
    pairs: List[Tuple[str, Any]] = []
    index = 0
    while index < len(items):
        current = items[index]
        current_text = str(current)
        if current_text.startswith("-"):
            key = normalize_native_option_name(current_text)
            if index + 1 < len(items):
                nxt = items[index + 1]
                nxt_text = str(nxt)
                if not nxt_text.startswith("-"):
                    pairs.append((key, _normalize_json_value(nxt)))
                    index += 2
                    continue
            pairs.append((key, True))
        else:
            pairs.append(("_arg", _normalize_json_value(current)))
        index += 1
    pairs.sort(key=lambda item: (item[0], json.dumps(item[1], sort_keys=True, separators=(",", ":"))))
    return tuple(pairs)


def codec_family_for_encoder(encoder: str) -> str:
    enc = canonical_encoder_name(encoder)
    if enc.startswith(("h264_", "libx264", "libopenh264")):
        return "h264"
    if enc.startswith(("hevc_", "libx265")):
        return "hevc"
    if enc.startswith(("av1_", "libsvtav1", "libaom-av1")):
        return "av1"
    if enc.startswith(("vp9_", "libvpx-vp9")):
        return "vp9"
    prefix = enc.split("_", 1)[0]
    if prefix:
        return prefix
    raise ValueError("Encoder name is required")


def encoder_implementation_for_encoder(encoder: str) -> str:
    enc = canonical_encoder_name(encoder)
    if enc in SOFTWARE_ENCODER_MODES:
        return enc
    if "_" in enc:
        return enc.rsplit("_", 1)[1]
    return enc


def infer_default_rate_control_mode(encoder: str) -> str:
    enc = canonical_encoder_name(encoder)
    if enc in SOFTWARE_ENCODER_MODES:
        return SOFTWARE_ENCODER_MODES[enc]
    if enc.endswith("_nvenc"):
        return "cq"
    if enc.endswith("_qsv"):
        return "icq"
    if enc.endswith(("_amf", "_vaapi", "_v4l2m2m", "_omx")):
        return "qp"
    if enc.endswith("_videotoolbox"):
        return "vbr"
    return "other"


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except Exception:
        return None


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def build_rate_control_config(
    *,
    encoder: str,
    mode: Optional[str] = None,
    quality_value: Optional[float] = None,
    target_bitrate_kbps: Optional[int] = None,
    max_bitrate_kbps: Optional[int] = None,
    buffer_size_kbits: Optional[int] = None,
    qmin: Optional[int] = None,
    qmax: Optional[int] = None,
    native_options: Optional[Mapping[str, Any]] = None,
    native_arguments: Optional[Sequence[Any]] = None,
) -> RateControlConfig:
    encoder_name = canonical_encoder_name(encoder)
    normalized_mode = normalize_rate_control_mode(mode) or infer_default_rate_control_mode(encoder_name)
    normalized_target = _coerce_int(target_bitrate_kbps)
    normalized_quality = _coerce_float(quality_value)
    normalized_native_options = normalize_native_options(native_options)
    normalized_native_arguments = normalize_native_arguments(native_arguments)

    if encoder_name.endswith("_videotoolbox") and normalized_mode in ("vbr", "abr", "cbr"):
        if normalized_target is None:
            raise ValueError(
                f"{encoder_name} {normalized_mode.upper()} requires explicit targetBitrateKbps; "
                "quality/CRF values are not portable VideoToolbox rate control"
            )
        normalized_native_options.setdefault("b:v", f"{normalized_target}k")

    if normalized_mode == "crf" and normalized_quality is not None:
        normalized_native_options.setdefault("crf", _coerce_int(normalized_quality))
    elif normalized_mode == "cq" and normalized_quality is not None:
        normalized_native_options.setdefault("cq", _coerce_int(normalized_quality))
    elif normalized_mode == "icq" and normalized_quality is not None:
        normalized_native_options.setdefault("global-quality", _coerce_int(normalized_quality))
    elif normalized_mode in ("qp", "cqp") and normalized_quality is not None:
        normalized_native_options.setdefault("qp", _coerce_int(normalized_quality))

    return RateControlConfig(
        mode=normalized_mode,
        qualityValue=normalized_quality,
        targetBitrateKbps=normalized_target,
        maxBitrateKbps=_coerce_int(max_bitrate_kbps),
        bufferSizeKbits=_coerce_int(buffer_size_kbits),
        qmin=_coerce_int(qmin),
        qmax=_coerce_int(qmax),
        nativeOptions=normalized_native_options,
        nativeArguments=normalized_native_arguments,
    )


def normalize_pixel_format(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    key = str(value).strip().lower()
    return PIXEL_FORMAT_ALIASES.get(key, key or None)


def bit_depth_for_pixel_format(pixel_format: Optional[str]) -> Optional[int]:
    normalized = normalize_pixel_format(pixel_format)
    if normalized is None:
        return None
    return BIT_DEPTH_BY_PIXEL_FORMAT.get(normalized)


def chroma_for_pixel_format(pixel_format: Optional[str]) -> Optional[str]:
    normalized = normalize_pixel_format(pixel_format)
    if normalized is None:
        return None
    return CHROMA_BY_PIXEL_FORMAT.get(normalized)


def build_output_identity(
    *,
    container_format: Optional[str] = None,
    pixel_format: Optional[str] = None,
    bit_depth: Optional[int] = None,
    chroma_subsampling: Optional[str] = None,
    profile: Optional[str] = None,
    level: Optional[str] = None,
    tier: Optional[str] = None,
    gop_frames: Optional[int] = None,
    keyint_min: Optional[int] = None,
    max_b_frames: Optional[int] = None,
    b_frame_reordering: Optional[bool] = None,
    film_grain_synthesis: Optional[int] = None,
    lookahead_frames: Optional[int] = None,
    video_tag: Optional[str] = None,
    time_base: Optional[str] = None,
) -> OutputIdentity:
    normalized_pixel_format = normalize_pixel_format(pixel_format)
    return OutputIdentity(
        containerFormat=normalize_container_format(container_format),
        pixelFormat=normalized_pixel_format,
        bitDepth=_coerce_int(bit_depth) if bit_depth is not None else bit_depth_for_pixel_format(normalized_pixel_format),
        chromaSubsampling=(
            str(chroma_subsampling).strip()
            if chroma_subsampling
            else chroma_for_pixel_format(normalized_pixel_format)
        ),
        profile=str(profile).strip().lower() if profile else None,
        level=str(level).strip().lower() if level else None,
        tier=str(tier).strip().lower() if tier else None,
        gopFrames=_coerce_int(gop_frames),
        keyintMin=_coerce_int(keyint_min),
        maxBFrames=_coerce_int(max_b_frames),
        bFrameReordering=b_frame_reordering if isinstance(b_frame_reordering, bool) else None,
        filmGrainSynthesis=_coerce_int(film_grain_synthesis),
        lookaheadFrames=_coerce_int(lookahead_frames),
        videoTag=str(video_tag).strip().lower() if video_tag else None,
        timeBase=str(time_base).strip() if time_base else None,
    )


def build_output_identity_from_probe(probe: Optional[Mapping[str, Any]]) -> OutputIdentity:
    data = probe or {}
    return build_output_identity(
        container_format=data.get("containerFormat"),
        pixel_format=data.get("pixelFormat"),
        bit_depth=data.get("bitDepth"),
        chroma_subsampling=data.get("chromaSubsampling"),
        profile=data.get("profile"),
        level=data.get("level"),
        tier=data.get("tier"),
        gop_frames=data.get("gopFrames", data.get("keyframeIntervalMax")),
        keyint_min=data.get("keyintMin", data.get("keyframeIntervalMin")),
        max_b_frames=data.get("maxBFrames"),
        b_frame_reordering=data.get("bFrameReordering"),
        video_tag=data.get("videoTag"),
        time_base=data.get("timeBase"),
    )


def compare_output_identities(requested: OutputIdentity, effective: OutputIdentity) -> List[str]:
    mismatches: List[str] = []
    for field_name, label in (
        ("containerFormat", "container format"),
        ("pixelFormat", "pixel format"),
        ("bitDepth", "bit depth"),
        ("chromaSubsampling", "chroma subsampling"),
        ("profile", "profile"),
        ("level", "level"),
        ("tier", "tier"),
        ("maxBFrames", "max B-frames"),
        ("bFrameReordering", "B-frame reordering"),
        ("videoTag", "video tag"),
        ("timeBase", "time base"),
        ("gopFrames", "GOP size"),
        ("keyintMin", "minimum keyframe interval"),
    ):
        expected = getattr(requested, field_name)
        if expected is None:
            continue
        actual = getattr(effective, field_name)
        if actual != expected:
            mismatches.append(f"{label}: expected {expected!r}, got {actual!r}")
    return mismatches


def build_recipe_identity(
    *,
    encoder_requested: str,
    encoder_effective: Optional[str] = None,
    encoder_version: Optional[str] = None,
    preset_requested: Optional[str] = None,
    preset_effective: Optional[str] = None,
    tune: Optional[str] = None,
    profile: Optional[str] = None,
    level: Optional[str] = None,
    tier: Optional[str] = None,
    rate_control_requested: RateControlConfig,
    rate_control_effective: Optional[RateControlConfig] = None,
    output_requested: Optional[OutputIdentity] = None,
    output_effective: Optional[OutputIdentity] = None,
    native_options_requested: Optional[Mapping[str, Any]] = None,
    native_options_effective: Optional[Mapping[str, Any]] = None,
    native_arguments_requested: Optional[Sequence[Any]] = None,
    native_arguments_effective: Optional[Sequence[Any]] = None,
) -> RecipeIdentity:
    effective_encoder = canonical_encoder_name(encoder_effective or encoder_requested)
    requested_encoder = canonical_encoder_name(encoder_requested)
    effective_rate_control = rate_control_effective or rate_control_requested
    return RecipeIdentity(
        codecFamily=codec_family_for_encoder(effective_encoder),
        encoderImplementation=encoder_implementation_for_encoder(effective_encoder),
        encoderNameRequested=requested_encoder,
        encoderNameEffective=effective_encoder,
        encoderVersion=str(encoder_version).strip() if encoder_version else None,
        presetRequested=str(preset_requested).strip().lower() if preset_requested else None,
        presetEffective=str(preset_effective).strip().lower() if preset_effective else None,
        tune=str(tune).strip().lower() if tune else None,
        profile=str(profile).strip().lower() if profile else None,
        level=str(level).strip().lower() if level else None,
        tier=str(tier).strip().lower() if tier else None,
        rateControlRequested=rate_control_requested,
        rateControlEffective=effective_rate_control,
        outputRequested=output_requested or build_output_identity(),
        outputEffective=output_effective or output_requested or build_output_identity(),
        nativeOptionsRequested=normalize_native_options(native_options_requested),
        nativeOptionsEffective=normalize_native_options(native_options_effective),
        nativeArgumentsRequested=normalize_native_arguments(native_arguments_requested),
        nativeArgumentsEffective=normalize_native_arguments(native_arguments_effective),
        friendlyDescription=describe_rate_control(effective_rate_control),
    )


def ffmpeg_build_fingerprint(ffmpeg_banner: Optional[str]) -> Optional[str]:
    if not ffmpeg_banner:
        return None
    lines = []
    for raw_line in str(ffmpeg_banner).splitlines():
        line = re.sub(r"\s+", " ", raw_line.strip())
        if line:
            lines.append(line)
    if not lines:
        return None
    canonical = "\n".join(lines)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_environment_identity(
    *,
    hardware_info: Optional[Any] = None,
    accelerator: Optional[str] = None,
    driver_version: Optional[str] = None,
    ffmpeg_version: Optional[str] = None,
    ffmpeg_banner: Optional[str] = None,
    encoder_version: Optional[str] = None,
    client_version: Optional[str] = None,
    benchmark_protocol_version: Optional[str] = None,
    cpu_architecture: Optional[str] = None,
    cpu_physical_cores: Optional[int] = None,
    cpu_logical_cores: Optional[int] = None,
    physical_memory_bytes: Optional[int] = None,
    os_name: Optional[str] = None,
    os_version: Optional[str] = None,
    gpu_model: Optional[str] = None,
) -> EnvironmentIdentity:
    hw_gpu_model = str(getattr(hardware_info, "gpuModel", "") or "").strip() or None
    selected_gpu = str(gpu_model or hw_gpu_model or "").strip() or None
    selected_accelerator = str(accelerator or selected_gpu or "").strip() or None
    system_name = str(os_name or platform.system() or "").strip()
    system_version = str(os_version or platform.release() or "").strip()
    return EnvironmentIdentity(
        cpuArchitecture=str(cpu_architecture or platform.machine() or "").strip().lower(),
        cpuPhysicalCores=_coerce_int(cpu_physical_cores) or _physical_core_count(),
        cpuLogicalCores=_coerce_int(cpu_logical_cores) or int(os.cpu_count() or 1),
        physicalMemoryBytes=(
            _coerce_int(physical_memory_bytes)
            or _coerce_int(getattr(hardware_info, "physicalMemoryBytes", None))
            or _physical_memory_bytes()
        ),
        accelerator=selected_accelerator,
        driverVersion=str(driver_version).strip() if driver_version else None,
        gpuModel=selected_gpu,
        osName=system_name,
        osVersion=system_version,
        ffmpegVersion=str(ffmpeg_version).strip() if ffmpeg_version else None,
        ffmpegBuildFingerprint=ffmpeg_build_fingerprint(ffmpeg_banner),
        encoderVersion=str(encoder_version).strip() if encoder_version else None,
        clientVersion=str(client_version or getattr(config, "CLIENT_VERSION", "") or "").strip() or None,
        benchmarkProtocolVersion=str(benchmark_protocol_version or config.BENCHMARK_PROTOCOL_VERSION or "").strip() or None,
    )


def describe_rate_control(config_value: RateControlConfig) -> str:
    mode = config_value.mode.upper()
    parts = [mode]
    if config_value.qualityValue is not None and config_value.mode in ("crf", "cq", "icq", "qp", "cqp"):
        quality_text = str(int(config_value.qualityValue)) if float(config_value.qualityValue).is_integer() else f"{config_value.qualityValue:g}"
        parts.append(quality_text)
    if config_value.targetBitrateKbps is not None and config_value.mode in ("vbr", "cbr", "abr"):
        parts.append(f"{config_value.targetBitrateKbps} kbps")
    extras: List[str] = []
    if config_value.maxBitrateKbps is not None:
        extras.append(f"max {config_value.maxBitrateKbps} kbps")
    if config_value.bufferSizeKbits is not None:
        extras.append(f"buf {config_value.bufferSizeKbits} kbits")
    if config_value.qualityValue is not None and config_value.mode in ("vbr", "cbr", "abr"):
        quality_text = str(int(config_value.qualityValue)) if float(config_value.qualityValue).is_integer() else f"{config_value.qualityValue:g}"
        extras.append(f"quality hint {quality_text}")
    if extras:
        parts.append(f"({', '.join(extras)})")
    return " ".join(parts)


def canonical_json(value: Any) -> str:
    return json.dumps(_normalize_json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def recipe_fingerprint(recipe: RecipeIdentity) -> str:
    return sha256_fingerprint(recipe)


def environment_fingerprint(environment: EnvironmentIdentity) -> str:
    return sha256_fingerprint(environment)


def _normalize_json_value(value: Any) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Mapping):
        normalized: Dict[str, Any] = {}
        for key in sorted(value.keys(), key=lambda item: str(item)):
            normalized_key = str(key)
            normalized_value = _normalize_json_value(value[key])
            if normalized_value is None:
                continue
            if normalized_value == {} or normalized_value == [] or normalized_value == ():
                continue
            normalized[normalized_key] = normalized_value
        return normalized
    if isinstance(value, tuple):
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, list):
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, float):
        rounded = round(value, 6)
        if rounded.is_integer():
            return int(rounded)
        return rounded
    if isinstance(value, (int, bool)) or value is None:
        return value
    return value


def _physical_core_count() -> int:
    try:
        count = config.psutil.cpu_count(logical=False)
        if isinstance(count, int) and count > 0:
            return count
    except Exception:
        pass
    logical = int(os.cpu_count() or 1)
    return max(1, logical // 2 if logical > 1 else logical)


def _physical_memory_bytes() -> Optional[int]:
    try:
        total = config.psutil.virtual_memory().total
        if isinstance(total, int) and total > 0:
            return total
    except Exception:
        pass
    return None
