import hashlib
import json
import math
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
    effective_preset_for_encoder, map_preset_for_encoder,
)
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
_VIDEO_PROBE_CACHE: Dict[str, Dict[str, Optional[float]]] = {}


def _videotoolbox_target_bitrate(encoder: str, crf: Optional[int]) -> str:
    """Translate CRF-like intent into a stable VideoToolbox bitrate target."""
    e = (encoder or "").strip().lower()
    if crf is None:
        if e == "hevc_videotoolbox":
            return "3500k"
        if e == "av1_videotoolbox":
            return "3000k"
        return "5000k"
    c = max(10, min(40, int(crf)))
    if e == "hevc_videotoolbox":
        base = 3500
    elif e == "av1_videotoolbox":
        base = 3000
    else:
        base = 5000
    # Every +2 CRF lowers bitrate by ~20%; every -2 raises by ~25%.
    delta = (24 - c) / 2.0
    if delta >= 0:
        kbps = int(round(base * (1.25 ** delta)))
    else:
        kbps = int(round(base * (0.8 ** (-delta))))
    kbps = max(1200, min(22000, kbps))
    return f"{kbps}k"


def build_ffmpeg_encode_cmd(*, input_path: str, output_path: str, encoder: str, preset_name: str, crf: Optional[int] = None) -> List[str]:
    cmd: List[str] = [
        config.ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-nostats",
        "-progress", "pipe:1",
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
        elif e.endswith("_qsv"):
            cmd += ["-global_quality", str(crf)]
        elif e.endswith("_amf"):
            cmd += ["-qp", str(crf)]
        elif e.endswith("_vaapi"):
            cmd += ["-qp", str(crf)]
        elif e.endswith("_videotoolbox"):
            # VideoToolbox reliability is significantly better with explicit bitrate.
            cmd += ["-b:v", _videotoolbox_target_bitrate(e, crf)]
    e = encoder.strip().lower()
    if e == "h264_videotoolbox":
        if crf is None:
            cmd += ["-b:v", _videotoolbox_target_bitrate(e, None)]
        cmd += ["-profile:v", "high", "-g", "120"]
    elif e == "hevc_videotoolbox":
        if crf is None:
            cmd += ["-b:v", _videotoolbox_target_bitrate(e, None)]
        cmd += ["-tag:v", "hvc1"]
    elif e == "av1_videotoolbox":
        if crf is None:
            cmd += ["-b:v", _videotoolbox_target_bitrate(e, None)]
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


def _vmaf_filter_candidates() -> List[Dict[str, str]]:
    candidates: List[Dict[str, str]] = []
    v1_paths = [
        "/opt/homebrew/opt/libvmaf/share/libvmaf/model/vmaf_v1.0.16/vmaf_v1.0.16_3d0h.json",
        "/opt/homebrew/Cellar/libvmaf/3.2.0/share/libvmaf/model/vmaf_v1.0.16/vmaf_v1.0.16_3d0h.json",
        "/usr/local/opt/libvmaf/share/libvmaf/model/vmaf_v1.0.16/vmaf_v1.0.16_3d0h.json",
        "/usr/local/share/libvmaf/model/vmaf_v1.0.16/vmaf_v1.0.16_3d0h.json",
        "/usr/share/libvmaf/model/vmaf_v1.0.16/vmaf_v1.0.16_3d0h.json",
    ]
    for model_path in v1_paths:
        if os.path.exists(model_path):
            candidates.append({
                "filter": f"libvmaf=model='path={model_path}':log_fmt=json:log_path=-",
                "metricModelId": "vmaf-v1-sdr-1080p",
            })
    return candidates


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
    out_dir: str,
    artifact_name: str,
    host_gpu_vendors: Optional[List[str]] = None,
) -> Dict[str, Any]:
    os.makedirs(out_dir, exist_ok=True)
    artifact_path = os.path.join(out_dir, artifact_name)
    cmd = build_ffmpeg_encode_cmd(input_path=input_path, output_path=artifact_path, encoder=encoder, preset_name=preset, crf=crf)
    stdout, stderr, returncode, elapsed, hw_metrics = _run_monitored(
        cmd,
        encoder_name=encoder,
        host_gpu_vendors=host_gpu_vendors,
    )
    original_encoder = encoder
    original_preset = preset
    effective_preset = effective_preset_for_encoder(encoder, preset)
    total_frames = _parse_frame_count(stdout) or _parse_frame_count(stderr)
    fps_val = (total_frames / elapsed) if total_frames > 0 else 0.0
    size_val = os.path.getsize(artifact_path) if os.path.exists(artifact_path) else 0
    err_msg: Optional[str] = None
    if returncode != 0 or size_val <= 0 or fps_val <= 0.0:
        err_lines = (stderr or '').splitlines()
        if not err_lines:
            err_lines = (stdout or '').splitlines()
        err_msg = '; '.join([ln.strip() for ln in err_lines[-5:]]) if err_lines else 'ffmpeg failed'
    result: Dict[str, Any] = {
        'artifactPath': artifact_path,
        'encoderUsed': encoder,
        'elapsedMs': int(round(elapsed * 1000)),
        'fps': float(fps_val),
        'fileSizeBytes': int(size_val),
        'error': err_msg,
        'encoderRequested': original_encoder,
        'presetRequested': original_preset,
        'presetUsed': effective_preset,
    }
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


def probe_video_stream_metrics(path: str) -> Dict[str, Optional[float]]:
    resolved = os.path.realpath(path)
    cached = _VIDEO_PROBE_CACHE.get(resolved)
    if cached is not None:
        return dict(cached)

    result: Dict[str, Optional[float]] = {
        "sourceFps": None,
        "sourceDurationSeconds": None,
        "videoBitrateBps": None,
    }
    cmd = [
        config.ffprobe_exe(),
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=avg_frame_rate,bit_rate,duration:format=duration",
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
                    duration = _safe_float(stream.get("duration"))
                    if duration is not None and duration > 0:
                        result["sourceDurationSeconds"] = duration
                    bitrate = _safe_float(stream.get("bit_rate"))
                    if bitrate is not None and bitrate > 0:
                        result["videoBitrateBps"] = bitrate
            if result["sourceDurationSeconds"] is None:
                fmt = payload.get("format")
                if isinstance(fmt, dict):
                    duration = _safe_float(fmt.get("duration"))
                    if duration is not None and duration > 0:
                        result["sourceDurationSeconds"] = duration
    except Exception:
        pass

    _VIDEO_PROBE_CACHE[resolved] = dict(result)
    return result


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


def run_single_benchmark(hardware: config.HardwareInfo, input_path: str, preset: str, codec: str = "libx264", crf: Optional[int] = None) -> Dict[str, Any]:
    source_probe = probe_video_stream_metrics(input_path)
    with tempfile.TemporaryDirectory() as td:
        info = encode_to_artifact(
            input_path=input_path,
            encoder=codec,
            preset=preset,
            crf=crf,
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
        "benchmarkProtocolVersion": config.BENCHMARK_PROTOCOL_VERSION,
        "sourceSuiteVersion": config.SOURCE_SUITE_VERSION,
        "workloadId": config.WORKLOAD_ID,
    }
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
    telemetry_notes = info.get('telemetryNotes')
    if isinstance(telemetry_notes, list):
        note_parts.extend([str(part).strip() for part in telemetry_notes if str(part).strip()])
    elif info.get('telemetryNote'):
        note_parts.append(str(info['telemetryNote']).strip())
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
