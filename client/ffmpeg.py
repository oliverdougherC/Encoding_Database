import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, Any, List, Mapping

from . import config
from . import recipe as recipe_model
from .decode import run_decode_benchmark
from .encoders import (
    effective_preset_for_encoder, map_preset_for_encoder,
)
from .energy import derive_energy_intensities, serialize_energy_domains
from .hardware_monitor import HardwareMonitor

EXTENDED_TELEMETRY_KEYS: tuple = (
    'gpuTempMaxC', 'cpuFreqAvgMHz', 'cpuTempMaxC',
    'ffmpegCpuUtilAvg', 'ffmpegCpuUtilMax',
    'ffmpegReadMB', 'ffmpegWriteMB', 'ffmpegCpuTimeS',
    'batteryPercentStart', 'batteryPercentEnd', 'batteryPercentDrop',
    'powerSource', 'sampleCount', 'monitorDurationMs',
    'cpuSampleCount', 'gpuSampleCount', 'ffmpegSampleCount', 'batterySampleCount',
)
RAW_TELEMETRY_KEYS: tuple = ('telemetrySources', 'telemetryMissing')
_FALLBACK_TELEMETRY_KEYS: tuple = (
    'gpuUtilAvg', 'gpuPowerAvgW', 'gpuMemPeakMB',
    'cpuUtilAvg', 'cpuUtilMax', 'peakMemoryMB', 'thermalThrottle',
) + EXTENDED_TELEMETRY_KEYS
_VIDEO_PROBE_CACHE: Dict[str, Dict[str, Any]] = {}
_VMAF_MODEL_CONTEXT_CACHE: Optional[Dict[str, Any]] = None
_FFMPEG_BANNER_CACHE: Optional[str] = None


def _driver_identity() -> Optional[str]:
    value = (os.environ.get("ENCODINGDB_DRIVER_VERSION") or "").strip()
    if value:
        return value
    try:
        return str(platform.version()).strip() or str(platform.release()).strip() or None
    except Exception:
        return None


def get_ffmpeg_banner(*, force_refresh: bool = False) -> Optional[str]:
    global _FFMPEG_BANNER_CACHE
    if _FFMPEG_BANNER_CACHE is not None and not force_refresh:
        return _FFMPEG_BANNER_CACHE
    try:
        proc = subprocess.run(
            [config.ffmpeg_exe(), "-version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        banner = (proc.stdout or "").strip() or None
    except Exception:
        banner = None
    _FFMPEG_BANNER_CACHE = banner
    return banner


def _build_rate_control_from_legacy_crf(
    *,
    encoder: str,
    crf: Optional[int],
) -> recipe_model.RateControlConfig:
    quality_value = int(crf) if crf is not None else None
    return recipe_model.build_rate_control_config(
        encoder=encoder,
        quality_value=quality_value,
    )


def _normalize_rate_control_input(
    *,
    encoder: str,
    crf: Optional[int],
    rate_control: Optional[Any],
) -> recipe_model.RateControlConfig:
    if isinstance(rate_control, recipe_model.RateControlConfig):
        return rate_control
    if isinstance(rate_control, Mapping):
        return recipe_model.build_rate_control_config(
            encoder=encoder,
            mode=rate_control.get("mode"),
            quality_value=rate_control.get("qualityValue", rate_control.get("quality_value")),
            target_bitrate_kbps=rate_control.get("targetBitrateKbps", rate_control.get("target_bitrate_kbps")),
            max_bitrate_kbps=rate_control.get("maxBitrateKbps", rate_control.get("max_bitrate_kbps")),
            buffer_size_kbits=rate_control.get("bufferSizeKbits", rate_control.get("buffer_size_kbits")),
            qmin=rate_control.get("qmin"),
            qmax=rate_control.get("qmax"),
            native_options=rate_control.get("nativeOptions", rate_control.get("native_options")),
            native_arguments=rate_control.get("nativeArguments", rate_control.get("native_arguments")),
        )
    return _build_rate_control_from_legacy_crf(encoder=encoder, crf=crf)


def _build_rate_control_args(
    *,
    encoder: str,
    rate_control: recipe_model.RateControlConfig,
) -> List[str]:
    enc = encoder.strip().lower()
    mode = recipe_model.normalize_rate_control_mode(rate_control.mode) or "other"
    quality = recipe_model._coerce_int(rate_control.qualityValue)
    target = recipe_model._coerce_int(rate_control.targetBitrateKbps)
    maxrate = recipe_model._coerce_int(rate_control.maxBitrateKbps)
    bufsize = recipe_model._coerce_int(rate_control.bufferSizeKbits)

    args: List[str] = []
    if enc in ("libx264", "libx265", "libsvtav1", "libaom-av1", "libvpx-vp9", "libopenh264"):
        if mode != "crf":
            raise ValueError(f"{enc} requires CRF rate control, got {mode}")
        if quality is not None:
            args += ["-crf", str(quality)]
    elif enc.endswith("_nvenc"):
        if mode == "cq":
            if quality is None:
                raise ValueError(f"{enc} CQ mode requires qualityValue")
            args += ["-cq", str(max(0, min(51, quality)))]
        elif mode in ("qp", "cqp"):
            if quality is None:
                raise ValueError(f"{enc} QP mode requires qualityValue")
            args += ["-qp", str(max(0, min(51, quality)))]
        else:
            raise ValueError(f"{enc} does not support canonical {mode} rate control")
    elif enc.endswith("_qsv"):
        if mode != "icq":
            raise ValueError(f"{enc} requires ICQ rate control, got {mode}")
        if quality is None:
            raise ValueError(f"{enc} ICQ mode requires qualityValue")
        args += ["-global_quality", str(quality)]
    elif enc.endswith(("_amf", "_vaapi", "_v4l2m2m", "_omx")):
        if mode not in ("qp", "cqp"):
            raise ValueError(f"{enc} requires QP/CQP rate control, got {mode}")
        if quality is None:
            raise ValueError(f"{enc} QP mode requires qualityValue")
        args += ["-qp", str(quality)]
    elif enc.endswith("_videotoolbox"):
        if mode not in ("vbr", "abr", "cbr"):
            raise ValueError(f"{enc} requires bitrate-driven VideoToolbox control, got {mode}")
        if target is None or target <= 0:
            raise ValueError(f"{enc} requires targetBitrateKbps for {mode}")
        args += ["-b:v", f"{target}k"]
        if maxrate is not None and maxrate > 0:
            args += ["-maxrate:v", f"{maxrate}k"]
        if bufsize is not None and bufsize > 0:
            args += ["-bufsize:v", f"{bufsize}k"]
    elif quality is not None:
        raise ValueError(f"Unsupported encoder/rate control combination: {enc} / {mode}")

    return args


def _special_output_args(encoder: str) -> List[str]:
    enc = encoder.strip().lower()
    args = ["-pix_fmt", "yuv420p", "-video_track_timescale", "24000"]
    if enc == "h264_videotoolbox":
        return args + ["-profile:v", "high", "-g", "120"]
    if enc == "hevc_videotoolbox":
        return args + ["-tag:v", "hvc1"]
    return args


def _requested_output_identity(
    *,
    encoder: str,
    requested_output: Optional[recipe_model.OutputIdentity] = None,
) -> recipe_model.OutputIdentity:
    if requested_output is not None:
        return requested_output
    enc = encoder.strip().lower()
    kwargs: Dict[str, Any] = {
        "container_format": "mp4",
        "pixel_format": "yuv420p",
        "time_base": "1/24000",
    }
    if enc == "h264_videotoolbox":
        kwargs["profile"] = "high"
        kwargs["gop_frames"] = 120
    elif enc == "hevc_videotoolbox":
        kwargs["video_tag"] = "hvc1"
    return recipe_model.build_output_identity(**kwargs)


def requested_output_identity_for_encoder(encoder: str) -> recipe_model.OutputIdentity:
    """Return the canonical output contract applied by the encode command."""
    return _requested_output_identity(encoder=encoder)


def _classify_failure(
    *,
    returncode: int,
    stdout: str,
    stderr: str,
    artifact_exists: bool,
) -> str:
    detail = " ".join([stdout or "", stderr or ""]).lower()
    if returncode == 0 and artifact_exists:
        return "encode"
    if any(token in detail for token in ("unknown encoder", "encoder not found", "unsupported", "option not found")):
        return "unsupported"
    if any(token in detail for token in ("driver", "nvcuda", "videotoolbox", "device", "vaapi", "amf")):
        return "driver"
    if any(token in detail for token in ("error while opening encoder", "failed to initialise", "failed to initialize", "cannot allocate", "invalid argument")):
        return "init"
    return "encode"


def build_execution_identity_payload(
    *,
    hardware: config.HardwareInfo,
    artifact_info: Dict[str, Any],
    ffmpeg_version: Optional[str],
    client_version: Optional[str],
    benchmark_protocol_version: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    recipe_fingerprint = artifact_info.get("recipeFingerprint")
    requested_recipe_json = artifact_info.get("requestedRecipeJson")
    effective_recipe_json = artifact_info.get("effectiveRecipeJson")
    if recipe_fingerprint and requested_recipe_json and effective_recipe_json:
        payload["recipeFingerprint"] = str(recipe_fingerprint)
        payload["requestedRecipeJson"] = str(requested_recipe_json)
        payload["effectiveRecipeJson"] = str(effective_recipe_json)
    else:
        payload["failureCode"] = str(artifact_info.get("failureCode") or "protocol_violation")

    environment_identity = recipe_model.build_environment_identity(
        hardware_info=hardware,
        accelerator=str(artifact_info.get("encoderUsed") or artifact_info.get("encoderRequested") or "").strip() or None,
        driver_version=_driver_identity(),
        ffmpeg_version=ffmpeg_version,
        ffmpeg_banner=get_ffmpeg_banner(),
        encoder_version=str(artifact_info.get("encoderUsed") or artifact_info.get("encoderRequested") or "").strip() or None,
        client_version=client_version,
        benchmark_protocol_version=benchmark_protocol_version or config.BENCHMARK_PROTOCOL_VERSION,
    )
    payload["environmentJson"] = recipe_model.canonical_json(environment_identity)
    payload["environmentFingerprint"] = recipe_model.environment_fingerprint(environment_identity)
    if environment_identity.driverVersion:
        payload["driverVersion"] = environment_identity.driverVersion
    if artifact_info.get("rateControlDisplay"):
        payload["rateControlDisplay"] = str(artifact_info["rateControlDisplay"])
    if artifact_info.get("failureCode") and "failureCode" not in payload:
        payload["failureCode"] = str(artifact_info["failureCode"])
    return payload


def build_ffmpeg_encode_cmd(
    *,
    input_path: str,
    output_path: str,
    encoder: str,
    preset_name: str,
    crf: Optional[int] = None,
    rate_control: Optional[Any] = None,
) -> List[str]:
    resolved_rate_control = _normalize_rate_control_input(
        encoder=encoder,
        crf=crf,
        rate_control=rate_control,
    )
    cmd: List[str] = [
        config.ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-nostats",
        "-progress", "pipe:1",
        "-i", input_path,
        "-c:v", encoder,
    ]
    cmd += map_preset_for_encoder(encoder, preset_name)
    cmd += _build_rate_control_args(
        encoder=encoder,
        rate_control=resolved_rate_control,
    )
    cmd += _special_output_args(encoder)
    cmd += ["-an", output_path]
    return cmd


def _parse_frame_count(progress_output: str) -> int:
    """Extract the last frame= value from FFmpeg progress output."""
    matches = re.findall(r'frame=\s*(\d+)', progress_output or '')
    if matches:
        try:
            return int(matches[-1])
        except (ValueError, IndexError):
            pass
    return 0


def run_ffmpeg_test(input_path: str, preset: str, codec: str = "libx264", crf: Optional[int] = None) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, "out.mp4")
        cmd = build_ffmpeg_encode_cmd(input_path=input_path, output_path=out_path, encoder=codec, preset_name=preset, crf=crf)
        start = time.perf_counter()
        proc = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        end = time.perf_counter()
        elapsed = max(0.0001, end - start)
        total_frames = _parse_frame_count(proc.stdout) or _parse_frame_count(proc.stderr)
        fps = (total_frames / elapsed) if total_frames > 0 else 0.0
        size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
        result: Dict[str, Any] = {"fps": fps, "fileSizeBytes": size, "_encode_rc": proc.returncode, "elapsedMs": int(round(elapsed * 1000))}
        if proc.returncode != 0 or size == 0 or fps == 0.0:
            stderr_lines = (proc.stderr or "").splitlines()
            brief = "; ".join([ln.strip() for ln in stderr_lines[-5:]]) if stderr_lines else "ffmpeg failed"
            print(f"ffmpeg error (preset={preset}, codec={codec}): {brief}", file=sys.stderr)
            result["_error"] = brief
        return result


def _extract_json_blob(text: str) -> Optional[str]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    return text[start:end + 1]


def _safe_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except Exception:
        return None
    if not math.isfinite(number):
        return None
    return number


def _safe_int(value: Any) -> Optional[int]:
    try:
        number = int(str(value).strip())
    except Exception:
        return None
    return number if number >= 0 else None


def _normalize_ffprobe_level(level: Any) -> Optional[str]:
    raw = _safe_int(level)
    if raw is None:
        return None
    if raw >= 10 and raw % 3 != 0:
        major = raw // 10
        minor = raw % 10
        return f"{major}.{minor}"
    return str(raw)


def _percentile(values: List[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(0.0, min(1.0, q)) * (len(ordered) - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _parse_vmaf_report(report_text: str, *, model_id: str) -> Optional[Dict[str, Any]]:
    json_blob = _extract_json_blob(report_text or "")
    if json_blob:
        try:
            payload = json.loads(json_blob)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            frame_scores: List[float] = []
            for frame in payload.get("frames", []):
                if not isinstance(frame, dict):
                    continue
                metrics = frame.get("metrics")
                candidates: List[Any] = []
                if isinstance(metrics, dict):
                    candidates.extend([
                        metrics.get("vmaf"),
                        metrics.get("vmaf_score"),
                        metrics.get("VMAF_score"),
                    ])
                candidates.extend([frame.get("vmaf"), frame.get("VMAF_score")])
                for candidate in candidates:
                    score = _safe_float(candidate)
                    if score is not None:
                        frame_scores.append(score)
                        break

            pooled = payload.get("pooled_metrics")
            mean_score: Optional[float] = None
            if isinstance(pooled, dict):
                for key in ("vmaf", "VMAF_score"):
                    metric_payload = pooled.get(key)
                    if isinstance(metric_payload, dict):
                        mean_score = _safe_float(metric_payload.get("mean"))
                        if mean_score is not None:
                            break
            if mean_score is None:
                aggregate = payload.get("aggregate")
                if isinstance(aggregate, dict):
                    mean_score = _safe_float(aggregate.get("mean"))
                    if mean_score is None:
                        vmaf_aggregate = aggregate.get("VMAF_score")
                        if isinstance(vmaf_aggregate, dict):
                            mean_score = _safe_float(vmaf_aggregate.get("mean"))
            if mean_score is None and frame_scores:
                mean_score = sum(frame_scores) / len(frame_scores)
            if mean_score is not None:
                p5_score = _percentile(frame_scores, 0.05) if frame_scores else None
                return {
                    "vmaf": float(mean_score),
                    "vmafMean": float(mean_score),
                    "vmafP5": float(p5_score) if p5_score is not None else None,
                    "metricModelId": model_id,
                    "vmafFrameCount": len(frame_scores),
                }

    mean_match = re.search(r'"VMAF_score"\s*:\s*([0-9]+(?:\.[0-9]+)?)', report_text or "")
    if not mean_match:
        mean_match = re.search(r'"aggregate"[\s\S]*?"mean"\s*:\s*([0-9]+(?:\.[0-9]+)?)', report_text or "")
    if not mean_match:
        mean_match = re.search(r'"vmaf"\s*:\s*([0-9]+(?:\.[0-9]+)?)', report_text or "")
    if not mean_match:
        mean_match = re.search(r'VMAF\s+score\s*:\s*([0-9]+(?:\.[0-9]+)?)', report_text or "", re.IGNORECASE)
    if mean_match:
        mean_score = float(mean_match.group(1))
        return {
            "vmaf": mean_score,
            "vmafMean": mean_score,
            "vmafP5": None,
            "metricModelId": model_id,
            "vmafFrameCount": 0,
        }
    return None


def _vmaf_manifest_path() -> str:
    return config._resource_path("resources", "vmaf", "manifest.json")


def _sha256_path(path: str) -> Optional[str]:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except Exception:
        return None


def _escape_ffmpeg_filter_path(path: str) -> str:
    normalized = os.path.abspath(path).replace("\\", "/")
    normalized = normalized.replace(":", "\\:")
    normalized = normalized.replace("'", "\\'")
    return normalized


def resolve_vmaf_model_context(*, force_refresh: bool = False) -> Dict[str, Any]:
    global _VMAF_MODEL_CONTEXT_CACHE
    if _VMAF_MODEL_CONTEXT_CACHE is not None and not force_refresh:
        return dict(_VMAF_MODEL_CONTEXT_CACHE)

    context: Dict[str, Any] = {
        "available": False,
        "reason": "manifest-unreadable",
        "manifestPath": _vmaf_manifest_path(),
        "metricModelId": None,
        "metricModelVersion": None,
        "modelPath": None,
        "modelSha256": None,
        "expectedSha256": None,
        "analysisContextId": None,
        "resolutionSource": None,
        "filter": None,
        "detail": None,
    }
    try:
        with open(context["manifestPath"], "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except Exception as exc:
        context["detail"] = str(exc)
        _VMAF_MODEL_CONTEXT_CACHE = dict(context)
        return dict(context)

    if not isinstance(manifest, dict):
        context["reason"] = "manifest-invalid"
        _VMAF_MODEL_CONTEXT_CACHE = dict(context)
        return dict(context)

    metric_model_id = str(manifest.get("metricModelId") or "").strip()
    metric_model_version = str(manifest.get("metricModelVersion") or "").strip()
    filename = str(manifest.get("filename") or "").strip()
    bundle_relative_path = str(manifest.get("bundleRelativePath") or "").strip()
    expected_sha = str(manifest.get("sha256") or "").strip().lower()
    filter_options = manifest.get("filterOptions") if isinstance(manifest.get("filterOptions"), dict) else {}
    log_fmt = str(filter_options.get("log_fmt") or "json").strip() or "json"
    log_path = str(filter_options.get("log_path") or "-").strip() or "-"

    context.update({
        "metricModelId": metric_model_id or None,
        "metricModelVersion": metric_model_version or None,
        "expectedSha256": expected_sha or None,
        "analysisContextId": manifest.get("analysisContextId"),
    })

    if not metric_model_id or not metric_model_version or not filename or not bundle_relative_path or not expected_sha:
        context["reason"] = "manifest-incomplete"
        _VMAF_MODEL_CONTEXT_CACHE = dict(context)
        return dict(context)

    override_model_path = str(os.environ.get("ENCODINGDB_VMAF_MODEL_PATH", "") or "").strip()
    if override_model_path:
        model_path = override_model_path
        resolution_source = "override"
    else:
        model_path = config._resource_path(*bundle_relative_path.split("/"))
        resolution_source = "bundled"
    context["modelPath"] = model_path
    context["resolutionSource"] = resolution_source

    if not os.path.isfile(model_path):
        context["reason"] = "model-missing"
        _VMAF_MODEL_CONTEXT_CACHE = dict(context)
        return dict(context)

    actual_sha = _sha256_path(model_path)
    context["modelSha256"] = actual_sha
    if actual_sha != expected_sha:
        context["reason"] = "checksum-mismatch"
        _VMAF_MODEL_CONTEXT_CACHE = dict(context)
        return dict(context)

    escaped_path = _escape_ffmpeg_filter_path(model_path)
    context["filter"] = f"libvmaf=model='path={escaped_path}':log_fmt={log_fmt}:log_path={log_path}"
    context["available"] = True
    context["reason"] = "ok"
    _VMAF_MODEL_CONTEXT_CACHE = dict(context)
    return dict(context)


def _vmaf_filter_candidates() -> List[Dict[str, str]]:
    context = resolve_vmaf_model_context()
    if not context.get("available"):
        return []
    return [{
        "filter": str(context["filter"]),
        "metricModelId": str(context["metricModelId"]),
    }]


def compute_vmaf_metrics(input_path: str, encoded_path: str) -> Dict[str, Any]:
    for candidate in _vmaf_filter_candidates():
        cmd = [
            config.ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "info",
            "-i", encoded_path,
            "-i", input_path,
            "-lavfi", candidate["filter"],
            "-f", "null", "-",
        ]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        except Exception:
            continue
        parsed = _parse_vmaf_report(proc.stdout or "", model_id=candidate["metricModelId"])
        if parsed:
            return parsed
    return {}


def compute_vmaf(input_path: str, encoded_path: str) -> Optional[float]:
    metrics = compute_vmaf_metrics(input_path, encoded_path)
    score = _safe_float(metrics.get("vmaf"))
    return float(score) if score is not None else None


def compute_ssim(input_path: str, encoded_path: str) -> Optional[float]:
    cmd = [
        config.ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "info",
        "-i", input_path,
        "-i", encoded_path,
        "-lavfi", "ssim",
        "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        out = proc.stdout
        m = re.search(r'All:\s*([0-9]+(?:\.[0-9]+)?)', out)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return None


def compute_psnr(input_path: str, encoded_path: str) -> Optional[float]:
    cmd = [
        config.ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "info",
        "-i", input_path,
        "-i", encoded_path,
        "-lavfi", "psnr",
        "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        out = proc.stdout
        m = re.search(r'average:\s*([0-9]+(?:\.[0-9]+)?|inf)', out)
        if m:
            val = m.group(1)
            if val == 'inf':
                return 100.0
            return min(float(val), 100.0)
    except Exception:
        pass
    return None


def _csv_stable(value: Any) -> Optional[str]:
    if value is None:
        return None
    parts = [str(part).strip() for part in str(value).split(",") if str(part).strip()]
    if not parts:
        return None
    return ",".join(sorted(dict.fromkeys(parts)))


def _serialize_note_chunk(prefix: str, payload: Dict[str, Any], max_len: int) -> Optional[str]:
    if not payload or max_len <= 0:
        return None
    try:
        blob = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    except Exception:
        return None
    chunk = f"{prefix}={blob}"
    if len(chunk) > max_len:
        return None
    return chunk


def _note_bytes_used(parts: List[str]) -> int:
    if not parts:
        return 0
    return sum(len(part) for part in parts) + ((len(parts) - 1) * 2)


def _append_note_chunk(
    parts: List[str],
    prefix: str,
    payload: Dict[str, Any],
    *,
    max_len: int = 3500,
) -> None:
    remaining = max_len - _note_bytes_used(parts)
    if remaining <= 0:
        return
    chunk = _serialize_note_chunk(prefix, payload, remaining)
    if chunk:
        parts.append(chunk)


def build_telemetry_notes(
    telemetry: Dict[str, Any],
    telemetry_meta: Dict[str, Any],
    *,
    max_len: int = 3200,
) -> List[str]:
    notes: List[str] = []
    remaining = max_len

    telemetry_chunk = _serialize_note_chunk("telemetry", telemetry, remaining)
    if telemetry_chunk:
        notes.append(telemetry_chunk)
        remaining -= len(telemetry_chunk)
        if remaining > 2:
            remaining -= 2  # account for "; "

    if remaining <= 0:
        return notes

    stable_meta = {
        key: _csv_stable(telemetry_meta.get(key))
        for key in RAW_TELEMETRY_KEYS
        if telemetry_meta.get(key)
    }
    if not stable_meta:
        return notes

    meta_candidates: List[Dict[str, Any]] = []
    if stable_meta.get('telemetryMissing'):
        meta_candidates.append({'telemetryMissing': stable_meta['telemetryMissing']})
    if stable_meta.get('telemetrySources'):
        base = dict(meta_candidates[0]) if meta_candidates else {}
        base['telemetrySources'] = stable_meta['telemetrySources']
        meta_candidates.insert(0, base)

    for meta_payload in meta_candidates:
        meta_chunk = _serialize_note_chunk("telemetry_meta", meta_payload, remaining)
        if meta_chunk:
            notes.append(meta_chunk)
            break
    return notes


def _run_monitored(cmd: List[str], *, encoder_name: str, host_gpu_vendors: Optional[List[str]] = None) -> tuple:
    """Run an FFmpeg command with hardware monitoring via Popen.

    Returns (stdout, stderr, returncode, elapsed, hw_metrics).
    """
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    monitor = HardwareMonitor(
        ffmpeg_pid=proc.pid,
        interval=0.5,
        encoder_name=encoder_name,
        host_gpu_vendors=host_gpu_vendors,
    )
    monitor.start()
    start = time.perf_counter()
    stdout, stderr = proc.communicate()
    end = time.perf_counter()
    hw_metrics = monitor.stop()
    elapsed = max(0.0001, end - start)
    return stdout, stderr, proc.returncode, elapsed, hw_metrics


def encode_to_artifact(
    *,
    input_path: str,
    encoder: str,
    preset: str,
    crf: Optional[int],
    rate_control: Optional[Any] = None,
    requested_output: Optional[recipe_model.OutputIdentity] = None,
    out_dir: str,
    artifact_name: str,
    host_gpu_vendors: Optional[List[str]] = None,
) -> Dict[str, Any]:
    os.makedirs(out_dir, exist_ok=True)
    artifact_path = os.path.join(out_dir, artifact_name)
    original_encoder = encoder
    original_preset = preset
    effective_preset = effective_preset_for_encoder(encoder, preset)
    resolved_rate_control = _normalize_rate_control_input(
        encoder=encoder,
        crf=crf,
        rate_control=rate_control,
    )
    requested_output_identity = _requested_output_identity(
        encoder=encoder,
        requested_output=requested_output,
    )
    encoder_args = map_preset_for_encoder(encoder, preset) + _build_rate_control_args(
        encoder=encoder,
        rate_control=resolved_rate_control,
    ) + _special_output_args(encoder)
    try:
        cmd = build_ffmpeg_encode_cmd(
            input_path=input_path,
            output_path=artifact_path,
            encoder=encoder,
            preset_name=preset,
            crf=crf,
            rate_control=resolved_rate_control,
        )
    except Exception as exc:
        error_message = str(exc) or "unsupported encode configuration"
        return {
            "artifactPath": artifact_path,
            "encoderUsed": encoder,
            "elapsedMs": 0,
            "fps": 0.0,
            "fileSizeBytes": 0,
            "error": error_message,
            "failureCode": "unsupported",
            "encoderRequested": original_encoder,
            "presetRequested": original_preset,
            "presetUsed": effective_preset,
            "rateControlDisplay": recipe_model.describe_rate_control(resolved_rate_control),
        }

    stdout, stderr, returncode, elapsed, hw_metrics = _run_monitored(
        cmd,
        encoder_name=encoder,
        host_gpu_vendors=host_gpu_vendors,
    )
    total_frames = _parse_frame_count(stdout) or _parse_frame_count(stderr)
    fps_val = (total_frames / elapsed) if total_frames > 0 else 0.0
    size_val = os.path.getsize(artifact_path) if os.path.exists(artifact_path) else 0
    err_msg: Optional[str] = None
    failure_code: Optional[str] = None
    artifact_probe: Dict[str, Any] = {}
    effective_output_identity = requested_output_identity
    if returncode != 0 or size_val <= 0 or fps_val <= 0.0:
        err_lines = (stderr or '').splitlines()
        if not err_lines:
            err_lines = (stdout or '').splitlines()
        err_msg = '; '.join([ln.strip() for ln in err_lines[-5:]]) if err_lines else 'ffmpeg failed'
        failure_code = _classify_failure(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            artifact_exists=bool(size_val > 0),
        )
    else:
        artifact_probe = probe_video_stream_metrics(artifact_path)
        decodable, decode_error = validate_artifact_decodability(artifact_path)
        artifact_probe["decodable"] = decodable
        artifact_probe["decodeError"] = decode_error
        effective_output_identity = recipe_model.build_output_identity_from_probe(artifact_probe)
        output_mismatches = recipe_model.compare_output_identities(
            requested_output_identity,
            effective_output_identity,
        )
        if output_mismatches:
            failure_code = "invalid_output"
            err_msg = "Output validation failed: " + "; ".join(output_mismatches)
        elif not decodable:
            failure_code = "invalid_output"
            err_msg = "Output validation failed: artifact-not-decodable"

    requested_recipe_identity = recipe_model.build_recipe_identity(
        encoder_requested=original_encoder,
        encoder_effective=encoder,
        preset_requested=original_preset,
        preset_effective=effective_preset,
        rate_control_requested=resolved_rate_control,
        rate_control_effective=resolved_rate_control,
        output_requested=requested_output_identity,
        output_effective=requested_output_identity,
        native_options_requested=resolved_rate_control.nativeOptions,
        native_options_effective=resolved_rate_control.nativeOptions,
        native_arguments_requested=encoder_args,
        native_arguments_effective=encoder_args,
    )
    effective_recipe_identity = recipe_model.build_recipe_identity(
        encoder_requested=original_encoder,
        encoder_effective=encoder,
        preset_requested=original_preset,
        preset_effective=effective_preset,
        rate_control_requested=resolved_rate_control,
        rate_control_effective=resolved_rate_control,
        output_requested=effective_output_identity,
        output_effective=effective_output_identity,
        native_options_requested=resolved_rate_control.nativeOptions,
        native_options_effective=resolved_rate_control.nativeOptions,
        native_arguments_requested=encoder_args,
        native_arguments_effective=encoder_args,
    )
    combined_recipe_identity = recipe_model.build_recipe_identity(
        encoder_requested=original_encoder,
        encoder_effective=encoder,
        preset_requested=original_preset,
        preset_effective=effective_preset,
        rate_control_requested=resolved_rate_control,
        rate_control_effective=resolved_rate_control,
        output_requested=requested_output_identity,
        output_effective=effective_output_identity,
        native_options_requested=resolved_rate_control.nativeOptions,
        native_options_effective=resolved_rate_control.nativeOptions,
        native_arguments_requested=encoder_args,
        native_arguments_effective=encoder_args,
    )
    result: Dict[str, Any] = {
        'artifactPath': artifact_path,
        'encoderUsed': encoder,
        'elapsedMs': int(round(elapsed * 1000)),
        'fps': float(fps_val),
        'fileSizeBytes': int(size_val),
        'error': err_msg,
        'failureCode': failure_code,
        'encoderRequested': original_encoder,
        'presetRequested': original_preset,
        'presetUsed': effective_preset,
        'artifactProbe': artifact_probe,
        'rateControlDisplay': recipe_model.describe_rate_control(resolved_rate_control),
        'requestedRecipeJson': recipe_model.canonical_json(requested_recipe_identity),
        'effectiveRecipeJson': recipe_model.canonical_json(effective_recipe_identity),
        'recipeFingerprint': recipe_model.recipe_fingerprint(combined_recipe_identity),
    }
    if total_frames > 0:
        result['frameCount'] = int(total_frames)
    if hw_metrics.gpu_util_avg is not None:
        result['gpuUtilAvg'] = round(hw_metrics.gpu_util_avg, 2)
    if hw_metrics.gpu_power_avg_w is not None:
        result['gpuPowerAvgW'] = round(hw_metrics.gpu_power_avg_w, 2)
    if hw_metrics.gpu_mem_peak_mb is not None:
        result['gpuMemPeakMB'] = round(hw_metrics.gpu_mem_peak_mb, 2)
    if hw_metrics.cpu_util_avg is not None:
        result['cpuUtilAvg'] = round(hw_metrics.cpu_util_avg, 2)
    if hw_metrics.cpu_util_max is not None:
        result['cpuUtilMax'] = round(hw_metrics.cpu_util_max, 2)
    if hw_metrics.peak_memory_mb is not None:
        result['peakMemoryMB'] = round(hw_metrics.peak_memory_mb, 2)
    if hw_metrics.thermal_throttle is not None:
        result['thermalThrottle'] = hw_metrics.thermal_throttle

    # Extended telemetry fields (queryable columns on newer servers)
    if hw_metrics.gpu_temp_max_c is not None:
        result['gpuTempMaxC'] = round(hw_metrics.gpu_temp_max_c, 2)
    if hw_metrics.cpu_freq_avg_mhz is not None:
        result['cpuFreqAvgMHz'] = round(hw_metrics.cpu_freq_avg_mhz, 2)
    if hw_metrics.cpu_temp_max_c is not None:
        result['cpuTempMaxC'] = round(hw_metrics.cpu_temp_max_c, 2)
    if hw_metrics.ffmpeg_cpu_util_avg is not None:
        result['ffmpegCpuUtilAvg'] = round(hw_metrics.ffmpeg_cpu_util_avg, 2)
    if hw_metrics.ffmpeg_cpu_util_max is not None:
        result['ffmpegCpuUtilMax'] = round(hw_metrics.ffmpeg_cpu_util_max, 2)
    if hw_metrics.ffmpeg_read_mb is not None:
        result['ffmpegReadMB'] = round(hw_metrics.ffmpeg_read_mb, 2)
    if hw_metrics.ffmpeg_write_mb is not None:
        result['ffmpegWriteMB'] = round(hw_metrics.ffmpeg_write_mb, 2)
    if hw_metrics.ffmpeg_cpu_time_s is not None:
        result['ffmpegCpuTimeS'] = round(hw_metrics.ffmpeg_cpu_time_s, 3)
    if hw_metrics.battery_percent_start is not None:
        result['batteryPercentStart'] = round(hw_metrics.battery_percent_start, 2)
    if hw_metrics.battery_percent_end is not None:
        result['batteryPercentEnd'] = round(hw_metrics.battery_percent_end, 2)
    if hw_metrics.battery_percent_drop is not None:
        result['batteryPercentDrop'] = round(hw_metrics.battery_percent_drop, 2)
    if hw_metrics.power_source is not None:
        result['powerSource'] = hw_metrics.power_source
    if hw_metrics.sample_count is not None:
        result['sampleCount'] = int(hw_metrics.sample_count)
    if hw_metrics.monitor_duration_ms is not None:
        result['monitorDurationMs'] = int(hw_metrics.monitor_duration_ms)
    if hw_metrics.cpu_sample_count is not None:
        result['cpuSampleCount'] = int(hw_metrics.cpu_sample_count)
    if hw_metrics.gpu_sample_count is not None:
        result['gpuSampleCount'] = int(hw_metrics.gpu_sample_count)
    if hw_metrics.ffmpeg_sample_count is not None:
        result['ffmpegSampleCount'] = int(hw_metrics.ffmpeg_sample_count)
    if hw_metrics.battery_sample_count is not None:
        result['batterySampleCount'] = int(hw_metrics.battery_sample_count)
    if hw_metrics.telemetry_sources:
        result['telemetrySources'] = hw_metrics.telemetry_sources
    if hw_metrics.telemetry_missing:
        result['telemetryMissing'] = hw_metrics.telemetry_missing
    if hw_metrics.energy_domains:
        result['energyDomains'] = serialize_energy_domains(
            derive_energy_intensities(
                hw_metrics.energy_domains,
                frame_count=total_frames if total_frames > 0 else None,
            )
        )

    telemetry: Dict[str, Any] = {key: result[key] for key in _FALLBACK_TELEMETRY_KEYS if key in result}
    telemetry_meta: Dict[str, Any] = {key: result[key] for key in RAW_TELEMETRY_KEYS if key in result}
    notes = build_telemetry_notes(telemetry, telemetry_meta)
    if telemetry:
        result['telemetry'] = telemetry
    if telemetry_meta:
        result['telemetryMeta'] = telemetry_meta
    if notes:
        result['telemetryNotes'] = notes
        result['telemetryNote'] = "; ".join(notes)
    return result


def _parse_ratio(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "/" in text:
        try:
            num_text, den_text = text.split("/", 1)
            numerator = float(num_text)
            denominator = float(den_text)
            if denominator == 0:
                return None
            return numerator / denominator
        except Exception:
            return None
    return _safe_float(text)


def probe_video_stream_metrics(path: str) -> Dict[str, Any]:
    resolved = os.path.realpath(path)
    cached = _VIDEO_PROBE_CACHE.get(resolved)
    if cached is not None:
        return dict(cached)

    result: Dict[str, Any] = {
        "sourceFps": None,
        "sourceDurationSeconds": None,
        "videoBitrateBps": None,
        "videoPayloadBytes": None,
        "containerBytes": None,
        "ffprobeStreamBitrateBps": None,
        "containerFormat": None,
        "codecName": None,
        "pixelFormat": None,
        "bitDepth": None,
        "chromaSubsampling": None,
        "profile": None,
        "level": None,
        "gopFrames": None,
        "keyintMin": None,
        "maxBFrames": None,
        "bFrameReordering": None,
        "videoTag": None,
        "timeBase": None,
    }
    cmd = [
        config.ffprobe_exe(),
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=avg_frame_rate,time_base,bit_rate,duration,codec_name,codec_tag_string,profile,level,pix_fmt,has_b_frames,bits_per_raw_sample:format=duration,size,format_name",
        "-of", "json",
        path,
    ]
    try:
        proc = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        payload = json.loads(proc.stdout or "{}")
        if isinstance(payload, dict):
            streams = payload.get("streams")
            if isinstance(streams, list) and streams:
                stream = streams[0] if isinstance(streams[0], dict) else {}
                if isinstance(stream, dict):
                    result["sourceFps"] = _parse_ratio(stream.get("avg_frame_rate"))
                    raw_time_base = str(stream.get("time_base") or "").strip()
                    if raw_time_base:
                        result["timeBase"] = raw_time_base
                    duration = _safe_float(stream.get("duration"))
                    if duration is not None and duration > 0:
                        result["sourceDurationSeconds"] = duration
                    bitrate = _safe_float(stream.get("bit_rate"))
                    if bitrate is not None and bitrate > 0:
                        result["ffprobeStreamBitrateBps"] = bitrate
                    codec_name = str(stream.get("codec_name") or "").strip().lower()
                    if codec_name:
                        result["codecName"] = codec_name
                    codec_tag = str(stream.get("codec_tag_string") or "").strip().lower()
                    if codec_tag:
                        result["videoTag"] = codec_tag
                    pixel_format = recipe_model.normalize_pixel_format(stream.get("pix_fmt"))
                    if pixel_format:
                        result["pixelFormat"] = pixel_format
                        result["bitDepth"] = recipe_model.bit_depth_for_pixel_format(pixel_format)
                        result["chromaSubsampling"] = recipe_model.chroma_for_pixel_format(pixel_format)
                    bits_per_raw_sample = _safe_int(stream.get("bits_per_raw_sample"))
                    if bits_per_raw_sample is not None and bits_per_raw_sample > 0:
                        result["bitDepth"] = bits_per_raw_sample
                    profile = str(stream.get("profile") or "").strip().lower()
                    if profile:
                        result["profile"] = profile
                    level = _normalize_ffprobe_level(stream.get("level"))
                    if level:
                        result["level"] = level
                    max_b_frames = _safe_int(stream.get("has_b_frames"))
                    if max_b_frames is not None:
                        result["maxBFrames"] = max_b_frames
                        result["bFrameReordering"] = bool(max_b_frames > 0)
            fmt = payload.get("format")
            if isinstance(fmt, dict):
                if result["sourceDurationSeconds"] is None:
                    duration = _safe_float(fmt.get("duration"))
                    if duration is not None and duration > 0:
                        result["sourceDurationSeconds"] = duration
                container_bytes = _safe_int(fmt.get("size"))
                if container_bytes is not None and container_bytes > 0:
                    result["containerBytes"] = container_bytes
                container_format = recipe_model.normalize_container_format(fmt.get("format_name"))
                if container_format:
                    result["containerFormat"] = container_format
    except Exception:
        pass

    packet_cmd = [
        config.ffprobe_exe(),
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "packet=size",
        "-of", "csv=p=0",
        path,
    ]
    try:
        proc = subprocess.run(packet_cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        packet_total = 0
        saw_packet = False
        for raw_line in (proc.stdout or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            packet_size = _safe_int(line.split(",", 1)[0])
            if packet_size is None:
                continue
            saw_packet = True
            packet_total += packet_size
        if saw_packet and packet_total > 0:
            result["videoPayloadBytes"] = packet_total
    except Exception:
        pass

    if result["containerBytes"] is None:
        try:
            container_bytes = os.path.getsize(path)
            if container_bytes > 0:
                result["containerBytes"] = container_bytes
        except Exception:
            pass

    duration_seconds = _safe_float(result.get("sourceDurationSeconds"))
    payload_bytes = result.get("videoPayloadBytes")
    if duration_seconds is not None and duration_seconds > 0 and isinstance(payload_bytes, int) and payload_bytes > 0:
        result["videoBitrateBps"] = (payload_bytes * 8.0) / duration_seconds

    _VIDEO_PROBE_CACHE[resolved] = dict(result)
    return result


def validate_artifact_decodability(path: str) -> tuple[bool, Optional[str]]:
    """Decode every video frame; metadata-only ffprobe success is insufficient."""
    cmd = [
        config.ffmpeg_exe(), "-v", "error", "-xerror", "-nostdin",
        "-i", path, "-map", "0:v:0", "-an", "-sn", "-dn", "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except Exception as exc:
        return False, f"decode-validation-unavailable:{type(exc).__name__}"
    if proc.returncode == 0:
        return True, None
    detail = "; ".join(line.strip() for line in (proc.stderr or "").splitlines()[-5:] if line.strip())
    return False, detail or f"decode-validation-exit-{proc.returncode}"


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


def compute_metrics_parallel(input_path: str, artifacts: List[str], workers: int, quiet: bool = False) -> Dict[str, Dict[str, Optional[float]]]:
    """Compute VMAF, SSIM, and PSNR for each artifact in parallel.

    Returns {artifact_path: {'vmaf': X, 'vmafMean': X, 'vmafP5': Y, 'metricModelId': Z, 'ssim': A, 'psnr': B}}.
    """
    results: Dict[str, Dict[str, Optional[float]]] = {
        ap: {'vmaf': None, 'vmafMean': None, 'vmafP5': None, 'metricModelId': None, 'ssim': None, 'psnr': None}
        for ap in artifacts
    }
    if not artifacts:
        return results
    metric_fns: List[tuple] = []
    for ap in artifacts:
        metric_fns.append((ap, 'vmaf_bundle', compute_vmaf_metrics))
        metric_fns.append((ap, 'ssim', compute_ssim))
        metric_fns.append((ap, 'psnr', compute_psnr))
    total = len(metric_fns)
    done = 0
    if not quiet:
        print(f"Calculating quality metrics (VMAF, SSIM, PSNR) for {len(artifacts)} artifact(s) with {max(1, workers)} worker(s)...")
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(fn, input_path, ap): (ap, metric_name) for ap, metric_name, fn in metric_fns}
        for fut in as_completed(futs):
            ap, metric_name = futs[fut]
            try:
                metric_value = fut.result()
                if metric_name == 'vmaf_bundle':
                    if isinstance(metric_value, dict):
                        results[ap].update(metric_value)
                    else:
                        results[ap]['vmaf'] = None
                else:
                    results[ap][metric_name] = metric_value
            except Exception:
                if metric_name == 'vmaf_bundle':
                    results[ap]['vmaf'] = None
                    results[ap]['vmafMean'] = None
                    results[ap]['vmafP5'] = None
                    results[ap]['metricModelId'] = None
                else:
                    results[ap][metric_name] = None
            done += 1
            try:
                pct = (done / total) * 100.0
            except Exception:
                pct = 100.0
            if not quiet:
                print(f"Metrics progress: {done}/{total} ({pct:.0f}%)")
    if not quiet:
        print("Quality metrics batch complete.")
    return results


def run_single_benchmark(
    hardware: config.HardwareInfo,
    input_path: str,
    preset: str,
    codec: str = "libx264",
    crf: Optional[int] = None,
    *,
    source_suite_version: Optional[str] = None,
    workload_id: Optional[str] = None,
    content_class: Optional[str] = None,
    rate_control: Optional[Any] = None,
    ffmpeg_version: Optional[str] = None,
    client_version: Optional[str] = None,
    benchmark_protocol_version: Optional[str] = None,
) -> Dict[str, Any]:
    source_probe = probe_video_stream_metrics(input_path)
    with tempfile.TemporaryDirectory() as td:
        info = encode_to_artifact(
            input_path=input_path,
            encoder=codec,
            preset=preset,
            crf=crf,
            rate_control=rate_control,
            out_dir=td,
            artifact_name="out.mp4",
            host_gpu_vendors=list(getattr(hardware, 'gpuVendors', []) or []),
        )
        actual_encoder = info.get('encoderUsed', codec)
        actual_preset = info.get('presetUsed', preset)
        vmaf_metrics: Dict[str, Any] = {}
        ssim: Optional[float] = None
        psnr: Optional[float] = None
        artifact_path = info.get('artifactPath', os.path.join(td, "out.mp4"))
        artifact_probe = probe_video_stream_metrics(artifact_path)
        if info.get('error') is None and float(info.get('fps', 0.0)) > 0 and int(info.get('fileSizeBytes', 0)) > 0:
            print("Calculating quality metrics (VMAF, SSIM, PSNR)...")
            vmaf_metrics = compute_vmaf_metrics(input_path, artifact_path)
            ssim = compute_ssim(input_path, artifact_path)
            psnr = compute_psnr(input_path, artifact_path)

    payload = {
        "cpuModel": hardware.cpuModel,
        "gpuModel": hardware.gpuModel or "",
        "ramGB": hardware.ramGB,
        "os": hardware.os,
        "codec": actual_encoder,
        "preset": actual_preset,
        "crf": crf,
        "fps": float(info.get('fps', 0.0)),
        "fileSizeBytes": int(info.get('fileSizeBytes', 0)),
        "runMs": int(info.get('elapsedMs') or 0),
        "sourceFps": source_probe.get("sourceFps"),
        "videoBitrateBps": artifact_probe.get("videoBitrateBps"),
        "benchmarkProtocolVersion": benchmark_protocol_version or config.BENCHMARK_PROTOCOL_VERSION,
    }
    if content_class:
        payload["contentClass"] = content_class
    if source_suite_version:
        payload["sourceSuiteVersion"] = source_suite_version
    if workload_id:
        payload["workloadId"] = workload_id
    if source_probe.get("sourceDurationSeconds") is not None:
        payload["sourceDurationSeconds"] = source_probe.get("sourceDurationSeconds")
    if vmaf_metrics.get("vmaf") is not None:
        payload["vmaf"] = float(vmaf_metrics["vmaf"])
    if vmaf_metrics.get("vmafMean") is not None:
        payload["vmafMean"] = float(vmaf_metrics["vmafMean"])
    if vmaf_metrics.get("vmafP5") is not None:
        payload["vmafP5"] = float(vmaf_metrics["vmafP5"])
    if vmaf_metrics.get("metricModelId"):
        payload["metricModelId"] = str(vmaf_metrics["metricModelId"])
    required_v7_fields = (
        payload.get("vmaf") is not None,
        payload.get("vmafP5") is not None,
        payload.get("videoBitrateBps") is not None,
        payload.get("sourceFps") is not None,
        payload.get("sourceDurationSeconds") is not None,
        bool(payload.get("benchmarkProtocolVersion")),
        bool(payload.get("sourceSuiteVersion")),
        bool(payload.get("workloadId")),
        bool(payload.get("metricModelId")),
    )
    if all(required_v7_fields):
        payload["scoreFormulaVersion"] = config.SCORE_FORMULA_VERSION
        payload["scoreEligibilityNote"] = "Content-specific quick test; eligible for PL v7 benchmark scoring, not General PL."
    else:
        payload["scoreEligibilityNote"] = "Content-specific quick test only; not score-eligible for PL v7 canonical scoring and never General PL."
    if ssim is not None:
        payload["ssim"] = float(ssim)
    if psnr is not None:
        payload["psnr"] = float(psnr)
    payload.update(
        build_execution_identity_payload(
            hardware=hardware,
            artifact_info=info,
            ffmpeg_version=ffmpeg_version,
            client_version=client_version,
            benchmark_protocol_version=benchmark_protocol_version,
        )
    )
    # Hardware metrics from the monitor
    for hw_key in ('gpuUtilAvg', 'gpuPowerAvgW', 'gpuMemPeakMB',
                   'cpuUtilAvg', 'cpuUtilMax', 'peakMemoryMB', 'thermalThrottle'):
        if info.get(hw_key) is not None:
            payload[hw_key] = info[hw_key]
    for hw_key in EXTENDED_TELEMETRY_KEYS:
        if info.get(hw_key) is not None:
            payload[hw_key] = info[hw_key]
    for hw_key in RAW_TELEMETRY_KEYS:
        if info.get(hw_key) is not None:
            payload[hw_key] = info[hw_key]
    note_parts: List[str] = []
    bitrate_meta: Dict[str, Any] = {}
    video_payload_bytes = artifact_probe.get("videoPayloadBytes")
    if isinstance(video_payload_bytes, int) and video_payload_bytes > 0:
        bitrate_meta["videoPayloadBytes"] = video_payload_bytes
    container_bytes = artifact_probe.get("containerBytes")
    if not isinstance(container_bytes, int) or container_bytes <= 0:
        fallback_container_bytes = _safe_int(info.get("fileSizeBytes"))
        if fallback_container_bytes is not None and fallback_container_bytes > 0:
            container_bytes = fallback_container_bytes
    if isinstance(container_bytes, int) and container_bytes > 0:
        bitrate_meta["containerBytes"] = container_bytes
    ffprobe_stream_bitrate = _safe_float(artifact_probe.get("ffprobeStreamBitrateBps"))
    if ffprobe_stream_bitrate is not None and ffprobe_stream_bitrate > 0:
        bitrate_meta["ffprobeStreamBitrateBps"] = ffprobe_stream_bitrate
    bitrate_duration = _safe_float(artifact_probe.get("sourceDurationSeconds"))
    if bitrate_duration is not None and bitrate_duration > 0:
        bitrate_meta["durationSeconds"] = bitrate_duration
    _append_note_chunk(note_parts, "bitrate_meta", bitrate_meta)
    if info.get("failureCode"):
        note_parts.append(f"failure_code={info['failureCode']}")
    telemetry_notes = info.get('telemetryNotes')
    if isinstance(telemetry_notes, list):
        note_parts.extend([str(part).strip() for part in telemetry_notes if str(part).strip()])
    elif info.get('telemetryNote'):
        note_parts.append(str(info['telemetryNote']).strip())
    energy_domains = info.get("energyDomains")
    if isinstance(energy_domains, list) and energy_domains:
        enriched_energy = serialize_energy_domains(
            derive_energy_intensities(
                energy_domains,
                frame_count=_safe_int(info.get("frameCount")),
                source_duration_seconds=bitrate_duration,
            )
        )
        info["energyDomains"] = enriched_energy
        _append_note_chunk(note_parts, "energy", {"domains": enriched_energy})
    decode_benchmark = run_decode_benchmark(
        input_path=info["artifactPath"],
        source_fps=_safe_float(artifact_probe.get("sourceFps")),
    )
    info["decodeBenchmark"] = decode_benchmark
    _append_note_chunk(note_parts, "decode_benchmark", decode_benchmark)
    if note_parts:
        payload["notes"] = "; ".join(note_parts)[:3500]
    return payload


_SHA256_CACHE: Dict[str, str] = {}


def sha256_of_file(path: str) -> str:
    resolved = os.path.realpath(path)
    if resolved in _SHA256_CACHE:
        return _SHA256_CACHE[resolved]
    hasher = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    digest = hasher.hexdigest()
    _SHA256_CACHE[resolved] = digest
    return digest


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
