import argparse
import dataclasses
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from typing import Optional, Dict, Any, List, Tuple, Callable

import psutil

# Allow running as `python3 client/main.py` (adds parent dir to sys.path so
# relative imports resolve via the 'client' package).
# PyInstaller builds use _pyinstaller_entry.py instead (absolute imports).
if __name__ == "__main__" and __package__ is None:
    _parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _parent not in sys.path:
        sys.path.insert(0, _parent)
    __package__ = "client"

# Module imports (no circular dependencies - each only imports from above)
from . import config
from . import recipe as recipe_model
from .config import (
    ENV_BACKEND_BASE_URL, ENV_API_KEY, ENV_PRESETS, ENV_CRF, ENV_CODEC,
    ENV_QUEUE_DIR, PRESETS_CONFIG_PATH,
    HardwareInfo, sanitize_payload_for_server, validate_queue_dir, QueueDirError,
)
from .hardware import (
    detect_hardware, resolve_batch_size, measure_background_cpu_load,
)
from .encoders import (
    ensure_ffmpeg_and_ffprobe, has_encoder, has_libvmaf,
    normalize_codec_family, pick_software_encoder_for_family,
    discover_hardware_encoders_for_family, list_all_available_encoders,
    enumerate_supported_presets_for_encoder, sort_presets_by_speed_desc,
    get_encoder_friendly_label, is_hardware_encoder_name, is_hardware_encoder_usable,
    SOFTWARE_ENCODERS_ORDER, HARDWARE_ENCODERS,
)
from .ffmpeg import (
    run_ffmpeg_test, encode_to_artifact, compute_vmaf_parallel,
    compute_metrics_parallel,
    EXTENDED_TELEMETRY_KEYS,
    RAW_TELEMETRY_KEYS,
    run_single_benchmark, sha256_of_file,
    load_presets_config, probe_video_stream_metrics,
    build_execution_identity_payload,
    requested_output_identity_for_encoder,
    resolve_vmaf_model_context,
    validate_artifact_decodability,
)
from .artifacts import (
    AUTHORITATIVE_ANALYZER_VERSION,
    build_artifact_submission_payload,
    build_environment_bootstrap,
    build_payload_hash,
    build_recipe_bootstrap,
)
from .network import fetch_baseline_rows
from .protocol import (
    ArtifactProbe,
    EncodeOutcome,
    EncodeTiming,
    EnvironmentSnapshot,
    ProtocolConfig,
    RecipeSpec,
    StructuralExpectation,
    execute_protocol_campaign,
)
from .spool import count_pending_entries, replay_spool, spool_payload, submit_spooled_path
from .stats import should_skip_submission
from .suite import (
    PreparedSuiteClip,
    ensure_suite,
    ensure_suite_clip,
    get_clip,
    get_default_quick_clip,
    has_general_pl_coverage,
    load_default_suite_manifest,
)
from .ui import (
    prompt_yes_no, prompt_choice, prompt_text,
    _clear_screen, confirm_benchmark_readiness,
    print_end_screen, print_benchmark_result,
    BenchmarkProgress, BatchRunDashboard,
    print_info, print_success, print_warning, print_batch_summary,
)

CLIENT_VERSION = "client/0.2.0"


def _resolve_input_for_task(
    default_input: str,
    default_input_hash: str,
    task: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str, Optional[PreparedSuiteClip]]:
    """Return (effective_input_path, input_hash) for a task."""
    suite_clip = task.get("suiteClip") if isinstance(task, dict) else None
    if isinstance(suite_clip, PreparedSuiteClip):
        return suite_clip.path, suite_clip.input_hash, suite_clip
    return default_input, default_input_hash, None


def _infer_encoder_family(encoder: str) -> Optional[str]:
    e = (encoder or "").strip().lower()
    if "h264" in e:
        return "h264"
    if "hevc" in e or "h265" in e:
        return "hevc"
    if "av1" in e:
        return "av1"
    if "vp9" in e:
        return "vp9"
    return None


def _emit_event(event_sink: Optional[Callable[[Dict[str, Any]], None]], event_type: str, **payload: Any) -> None:
    if event_sink is None:
        return
    event = {"type": event_type, "ts": time.time(), "monotonicNs": time.perf_counter_ns()}
    event.update(payload)
    try:
        event_sink(event)
    except Exception:
        pass


def _prepare_quick_suite_clip() -> PreparedSuiteClip:
    manifest = load_default_suite_manifest()
    return ensure_suite_clip(get_default_quick_clip(manifest))


def _prepare_full_suite() -> List[PreparedSuiteClip]:
    manifest = load_default_suite_manifest()
    prepared = ensure_suite(manifest)
    if not has_general_pl_coverage(prepared):
        raise RuntimeError("suite coverage is incomplete; General PL requires all declared content classes")
    return prepared


def _prepare_named_suite_clip(clip_id: str) -> PreparedSuiteClip:
    manifest = load_default_suite_manifest()
    return ensure_suite_clip(get_clip(manifest, clip_id))


def _suite_identity_note(clip: PreparedSuiteClip) -> str:
    payload = {
        "suiteVersion": clip.suite_version,
        "clipId": clip.clip_id,
        "canonicalContentClass": clip.canonical_content_class,
        "payloadContentClass": clip.payload_content_class,
        "inputHash": clip.input_hash,
    }
    return "suite_meta=" + json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _load_suite_manifest_clip(prepared_clip: PreparedSuiteClip) -> Dict[str, Any]:
    manifest = load_default_suite_manifest()
    for clip in manifest.clips:
        if clip.clip_id == prepared_clip.clip_id:
            return {
                "suiteId": "encodingdb-test-suite",
                "suiteVersion": manifest.suite_version,
                "manifestVersion": manifest.manifest_version,
                "clipKey": clip.clip_id,
                "workloadId": clip.clip_id,
                "sha256": clip.sha256,
                "byteSize": clip.byte_size,
            }
    raise RuntimeError(f"Suite clip {prepared_clip.clip_id} not found in manifest")


def _build_authoritative_run_create_request(
    *,
    prepared_clip: PreparedSuiteClip,
    recipe_id: str,
    record: Any,
    info: Dict[str, Any],
    metrics: Dict[str, Any],
    hardware: HardwareInfo,
    source_probe: Dict[str, Any],
    artifact_probe: Dict[str, Any],
    ffmpeg_version: str,
    client_version: str,
    execution_identity_payload: Dict[str, Any],
    protocol_config: ProtocolConfig,
) -> Dict[str, Any]:
    suite_clip = _load_suite_manifest_clip(prepared_clip)
    telemetry = {
        key: info[key]
        for key in list(EXTENDED_TELEMETRY_KEYS) + list(RAW_TELEMETRY_KEYS) + [
            "gpuUtilAvg",
            "gpuPowerAvgW",
            "gpuMemPeakMB",
            "cpuUtilAvg",
            "cpuUtilMax",
            "peakMemoryMB",
            "thermalThrottle",
        ]
        if info.get(key) is not None
    }
    telemetry_notes = info.get("telemetryNotes")
    if not isinstance(telemetry_notes, list):
        telemetry_notes = [str(info.get("telemetryNote")).strip()] if info.get("telemetryNote") else []
    telemetry_sources = {
        "hardwareMonitor": sorted(list(telemetry.keys())),
        "artifactProbe": "ffprobe-video-stream-metrics-v1",
        "localQualityDebug": "client-local-debug-only",
    }
    client_quality_debug = {
        "source": "client-local-debug",
        "metricModelId": metrics.get("metricModelId"),
        "vmaf": metrics.get("vmaf"),
        "vmafMean": metrics.get("vmafMean"),
        "vmafP5": metrics.get("vmafP5"),
        "ssim": metrics.get("ssim"),
        "psnr": metrics.get("psnr"),
        "videoBitrateBps": artifact_probe.get("videoBitrateBps"),
    }
    raw_energy_domains = info.get("energyDomains")
    canonical_energy_domains = []
    if isinstance(raw_energy_domains, list):
        domain_types = {"gpu-board", "cpu-package", "cpu-core", "dram", "soc-package", "system"}
        unit_map = {
            "joule": "joules",
            "millijoule": "millijoules",
            "microjoule": "microjoules",
            "nanojoule": "nanojoules",
        }
        state_map = {
            "ok": "valid",
            "wrapped": "wrap",
            "reset": "reset",
            "unsupported": "unsupported",
            "missing": "error",
            "error": "error",
        }
        for measurement in raw_energy_domains:
            if not isinstance(measurement, dict):
                continue
            domain_type = str(measurement.get("domainType") or "other").strip().lower()
            canonical_energy_domains.append({
                "domain": domain_type if domain_type in domain_types else "other",
                "domainLabel": str(measurement.get("domain") or domain_type or "unknown"),
                "collector": str(measurement.get("source") or "unknown"),
                "collectorVersion": measurement.get("collectorVersion"),
                "source": measurement.get("source"),
                "counterUnit": unit_map.get(str(measurement.get("counterUnit") or "").lower()),
                "counterState": state_map.get(str(measurement.get("counterState") or "").lower(), "error"),
                "startCounter": measurement.get("startCounter"),
                "endCounter": measurement.get("endCounter"),
                "counterRolloverValue": measurement.get("counterMax"),
                "error": measurement.get("reason"),
            })

    raw_decode = info.get("decodeBenchmark")
    canonical_decode = None
    if isinstance(raw_decode, dict):
        supported = raw_decode.get("supported") is True
        canonical_decode = {
            "status": "complete" if supported else "unsupported",
            "decoderImplementation": str(raw_decode.get("decoder") or "ffmpeg-software-default") if supported else None,
            "decoderVersion": ffmpeg_version if supported else None,
            "toolchainFingerprint": execution_identity_payload.get("environmentFingerprint") if supported else None,
            "executionMode": "software" if supported else None,
            "cacheDiscipline": "documented" if supported else None,
            "wallTimeMs": raw_decode.get("elapsedMs"),
            "decodeFps": raw_decode.get("decodeFps"),
            "sourceFps": raw_decode.get("sourceFps"),
            "cpuTimeMs": (
                float(raw_decode["cpuTimeSeconds"]) * 1000.0
                if isinstance(raw_decode.get("cpuTimeSeconds"), (int, float))
                else None
            ),
            "peakRssBytes": raw_decode.get("peakRssBytes"),
            "notes": "; ".join(filter(None, [
                str(raw_decode.get("methodology") or "").strip(),
                str(raw_decode.get("cachePolicy") or "").strip(),
            ])) or None,
            "deferredReason": None if supported else str(raw_decode.get("reason") or "decode_unsupported"),
        }

    run_create = {
        "benchmarkProtocol": {
            "protocolVersion": config.BENCHMARK_PROTOCOL_VERSION,
            "sourceSuiteVersion": prepared_clip.suite_version,
            "minimumClientVersion": CLIENT_VERSION,
            "canonicalRecipeRules": {
                "artifactUploadRequired": True,
                "warmupRuns": protocol_config.warmup_runs,
                "minimumMeasuredRuns": protocol_config.minimum_measured_runs,
                "stabilityThresholdRatio": protocol_config.stability_threshold_ratio,
                "maxAdaptiveRepeats": protocol_config.max_adaptive_repeats,
            },
            "canonicalOutputRules": {
                "singleVideoStream": True,
                "noAudio": True,
            },
            "metricWorkerVersion": AUTHORITATIVE_ANALYZER_VERSION,
        },
        "testClip": suite_clip,
        "recipe": build_recipe_bootstrap(
            recipe_fingerprint=str(info.get("recipeFingerprint") or ""),
            requested_recipe_json=str(info.get("requestedRecipeJson") or "{}"),
            effective_recipe_json=str(info.get("effectiveRecipeJson") or "{}"),
        ),
        "environment": build_environment_bootstrap(
            environment_fingerprint=str(execution_identity_payload.get("environmentFingerprint") or ""),
            environment_json=str(execution_identity_payload.get("environmentJson") or "{}"),
            cpu_model=hardware.cpuModel,
        ),
        "workloadId": prepared_clip.workload_id,
        "expectedMetricModelId": metrics.get("metricModelId"),
        "inputHash": prepared_clip.input_hash,
        "campaignId": record.schedule.campaign_id,
        "repetitionGroupId": f"{record.schedule.campaign_id}:{recipe_id}",
        "repetitionIndex": record.schedule.repetition_index,
        "encodeWallTimeMs": int(round(record.timing.elapsed_s * 1000.0)),
        "encodeFps": float(record.timing.encode_fps),
        "sourceFps": float(record.timing.source_fps),
        "realTimeRatio": float(record.timing.realtime_multiple),
        "sourceFrameCount": int(record.timing.source_frame_count),
        "encodedFrameCount": int(record.timing.encoded_frame_count),
        "telemetry": telemetry,
        "telemetrySources": telemetry_sources,
        "telemetryMissing": telemetry_notes,
        "energyDomains": canonical_energy_domains or None,
        "decodeBenchmark": canonical_decode,
        "preRunEnvironmentCheck": {
            "snapshot": record.environment_snapshot.to_dict() if record.environment_snapshot is not None else None,
            "overallValidity": record.overall_validity.to_dict(),
            "environmentValidity": record.environment_validity.to_dict(),
            "structuralValidity": record.structural_validity.to_dict(),
        },
        "ffmpegProgressTelemetry": {
            "elapsedMs": info.get("elapsedMs"),
            "frameCount": info.get("frameCount"),
            "ffmpegCpuTimeS": info.get("ffmpegCpuTimeS"),
        },
        "clientQualityDebug": client_quality_debug,
        "artifact": {
            "role": "ENCODED",
            "sha256": str(info.get("artifactSha256") or ""),
            "byteSize": int(info.get("fileSizeBytes") or 0),
            "mediaContainer": artifact_probe.get("containerFormat"),
        },
    }
    run_create["payloadHash"] = build_payload_hash(run_create)
    return run_create


def _filter_canonical_encoders(encoders: List[str]) -> List[str]:
    filtered: List[str] = []
    for encoder in encoders:
        if not is_hardware_encoder_name(encoder) or is_hardware_encoder_usable(encoder):
            filtered.append(encoder)
    return filtered


def _apply_v7_score_contract(payload: Dict[str, Any]) -> None:
    required_fields = (
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
    if all(required_fields):
        payload["scoreFormulaVersion"] = config.SCORE_FORMULA_VERSION
        payload["scoreEligibilityNote"] = "Content-specific quick test; eligible for PL v7 benchmark scoring, not General PL."
        return
    payload.pop("scoreFormulaVersion", None)
    payload["scoreEligibilityNote"] = "Content-specific quick test only; not score-eligible for PL v7 canonical scoring and never General PL."


def _is_cancelled(cancel_event: Optional[Any]) -> bool:
    if cancel_event is None:
        return False
    try:
        return bool(cancel_event.is_set())
    except Exception:
        return False


def _should_use_submit_token(args: argparse.Namespace) -> bool:
    return config._env_flag('INGEST_USE_TOKENS', False) or bool(getattr(args, 'use_token', False))


def _emit_counters(
    event_sink: Optional[Callable[[Dict[str, Any]], None]],
    *,
    submitted: int,
    skipped: int,
    queued: int,
    failed: int,
) -> None:
    _emit_event(
        event_sink,
        "counters",
        submitted=submitted,
        skipped=skipped,
        queued=queued,
        failed=failed,
    )


def _format_vmaf_model_unavailable(context: Dict[str, Any]) -> str:
    reason = str(context.get("reason") or "unknown")
    model_id = str(context.get("metricModelId") or "unknown-model")
    model_version = str(context.get("metricModelVersion") or "unknown-version")
    model_path = str(context.get("modelPath") or "unresolved")
    if reason == "model-missing":
        detail = f"bundled model file missing at {model_path}"
    elif reason == "checksum-mismatch":
        detail = (
            f"bundled model checksum mismatch at {model_path} "
            f"(expected {context.get('expectedSha256')}, got {context.get('modelSha256')})"
        )
    elif reason == "manifest-incomplete":
        detail = f"manifest is incomplete at {context.get('manifestPath')}"
    elif reason == "manifest-invalid":
        detail = f"manifest is invalid at {context.get('manifestPath')}"
    else:
        detail = f"manifest could not be read at {context.get('manifestPath')}"
        if context.get("detail"):
            detail = f"{detail}: {context.get('detail')}"
    return (
        f"Local VMAF quality analysis unavailable for {model_id} ({model_version}): {detail}. "
        "Local quality diagnostics are disabled; uploaded artifacts can still receive canonical server-side PL v7 analysis."
    )


def _ensure_local_quality_stack(
    *,
    event_sink: Optional[Callable[[Dict[str, Any]], None]],
    scope: str,
) -> Tuple[bool, int]:
    if not has_libvmaf():
        print(
            "Your ffmpeg build does not include libvmaf. Install ffmpeg with libvmaf.",
            file=sys.stderr,
        )
        _emit_event(event_sink, "run_error", scope=scope, code=5, message="libvmaf not available")
        return False, 5

    model_context = resolve_vmaf_model_context()
    if not model_context.get("available"):
        message = _format_vmaf_model_unavailable(model_context)
        print(message, file=sys.stderr)
        _emit_event(
            event_sink,
            "run_error",
            scope=scope,
            code=7,
            message=message,
            metricModelId=model_context.get("metricModelId"),
            metricModelVersion=model_context.get("metricModelVersion"),
            metricModelPath=model_context.get("modelPath"),
            metricModelReason=model_context.get("reason"),
        )
        return False, 7

    if not config._VMAF_MODEL_DETECTED_PRINTED:
        print(
            "Pinned VMAF model ready: "
            f"{model_context.get('metricModelId')} ({model_context.get('metricModelVersion')}) "
            f"[{model_context.get('resolutionSource')}]"
        )
        print(f"VMAF model path: {model_context.get('modelPath')}")
        config._VMAF_MODEL_DETECTED_PRINTED = True
    return True, 0


def _safe_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except Exception:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _parse_ratio(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "/" in text:
        try:
            numerator_text, denominator_text = text.split("/", 1)
            numerator = float(numerator_text)
            denominator = float(denominator_text)
            if denominator == 0:
                return None
            return numerator / denominator
        except Exception:
            return None
    return _safe_float(text)


def _pix_fmt_to_chroma_subsampling(pix_fmt: Optional[str]) -> Optional[str]:
    value = str(pix_fmt or "").strip().lower()
    if not value:
        return None
    for token, chroma in (
        ("420", "4:2:0"),
        ("422", "4:2:2"),
        ("444", "4:4:4"),
        ("440", "4:4:0"),
    ):
        if token in value:
            return chroma
    return None


def _serialize_note_chunk(prefix: str, payload: Dict[str, Any], max_len: int) -> Optional[str]:
    if max_len <= 0:
        return None
    compact = {key: value for key, value in payload.items() if value is not None}
    if not compact:
        return None
    try:
        blob = json.dumps(compact, sort_keys=True, separators=(",", ":"))
    except Exception:
        return None
    chunk = f"{prefix}={blob}"
    if len(chunk) > max_len:
        return None
    return chunk


def _append_note_chunk(note_parts: List[str], prefix: str, payload: Dict[str, Any], *, max_total_len: int = 3500) -> None:
    used_len = sum(len(part) for part in note_parts)
    used_len += max(0, (len(note_parts) - 1) * 2)
    remaining = max_total_len - used_len
    if note_parts:
        remaining -= 2
    chunk = _serialize_note_chunk(prefix, payload, remaining)
    if chunk:
        note_parts.append(chunk)


def _infer_expected_codec_name(encoder: str) -> Optional[str]:
    family = _infer_encoder_family(encoder)
    if family == "hevc":
        return "hevc"
    return family


def _probe_artifact_contract(path: str) -> ArtifactProbe:
    cmd = [
        config.ffprobe_exe(),
        "-v", "error",
        "-count_frames",
        "-show_entries",
        (
            "stream=index,codec_type,codec_name,codec_tag_string,profile,level,pix_fmt,bits_per_raw_sample,"
            "color_range,color_space,color_transfer,color_primaries,width,height,avg_frame_rate,time_base,"
            "nb_read_frames,nb_frames:format=duration,size"
        ),
        "-of", "json",
        path,
    ]
    try:
        proc = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except Exception:
        return ArtifactProbe(decodable=False, truncated=True)
    if proc.returncode != 0:
        return ArtifactProbe(decodable=False, truncated=True)
    try:
        payload = json.loads(proc.stdout or "{}")
    except Exception:
        return ArtifactProbe(decodable=False, truncated=True)
    streams = payload.get("streams")
    if not isinstance(streams, list):
        return ArtifactProbe(decodable=False, truncated=True)
    video_stream = None
    video_stream_count = 0
    has_audio = False
    auxiliary_stream_count = 0
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        codec_type = str(stream.get("codec_type") or "").strip().lower()
        if codec_type == "video" and video_stream is None:
            video_stream = stream
            video_stream_count += 1
        elif codec_type == "video":
            video_stream_count += 1
        elif codec_type == "audio":
            has_audio = True
        else:
            auxiliary_stream_count += 1
    if not isinstance(video_stream, dict):
        return ArtifactProbe(decodable=False, truncated=True, has_audio=has_audio)

    duration_s = None
    frame_count = None
    avg_frame_rate = _parse_ratio(video_stream.get("avg_frame_rate"))
    time_base = _parse_ratio(video_stream.get("time_base"))
    format_payload = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    duration_s = _safe_float(video_stream.get("duration"))
    if duration_s is None:
        duration_s = _safe_float(format_payload.get("duration"))
    frame_count = _safe_int(video_stream.get("nb_read_frames"))
    if frame_count is None:
        frame_count = _safe_int(video_stream.get("nb_frames"))
    if frame_count is None and duration_s is not None and avg_frame_rate is not None:
        frame_count = int(round(duration_s * avg_frame_rate))

    bit_depth = _safe_int(video_stream.get("bits_per_raw_sample"))
    pix_fmt = str(video_stream.get("pix_fmt") or "").strip() or None
    if bit_depth is None and pix_fmt:
        for suffix in ("10le", "10be", "12le", "12be"):
            if pix_fmt.endswith(suffix):
                bit_depth = _safe_int(suffix[:2])
                break
        if bit_depth is None:
            bit_depth = 8

    size_bytes = _safe_int(format_payload.get("size"))
    truncated = bool(size_bytes is not None and size_bytes <= 0)
    keyframe_interval_min: Optional[int] = None
    keyframe_interval_max: Optional[int] = None
    try:
        keyframe_proc = subprocess.run(
            [
                config.ffprobe_exe(), "-v", "error", "-select_streams", "v:0",
                "-show_entries", "frame=key_frame", "-of", "csv=p=0", path,
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        keyframes = [
            index for index, line in enumerate((keyframe_proc.stdout or "").splitlines())
            if line.strip().split(",", 1)[0] == "1"
        ]
        intervals = [right - left for left, right in zip(keyframes, keyframes[1:])]
        if intervals:
            keyframe_interval_min = min(intervals)
            keyframe_interval_max = max(intervals)
    except Exception:
        pass

    decodable, decode_error = validate_artifact_decodability(path)
    output_metrics = probe_video_stream_metrics(path)
    return ArtifactProbe(
        decodable=decodable,
        duration_s=duration_s,
        frame_count=frame_count,
        width=_safe_int(video_stream.get("width")),
        height=_safe_int(video_stream.get("height")),
        codec=str(video_stream.get("codec_name") or "").strip() or None,
        codec_tag=str(video_stream.get("codec_tag_string") or "").strip().lower() or None,
        profile=str(video_stream.get("profile") or "").strip().lower() or None,
        level=str(output_metrics.get("level") or video_stream.get("level") or "").strip().lower() or None,
        pix_fmt=recipe_model.normalize_pixel_format(pix_fmt),
        bit_depth=bit_depth,
        chroma_subsampling=_pix_fmt_to_chroma_subsampling(pix_fmt),
        color_range=str(video_stream.get("color_range") or "").strip() or None,
        color_space=str(video_stream.get("color_space") or "").strip() or None,
        color_transfer=str(video_stream.get("color_transfer") or "").strip() or None,
        color_primaries=str(video_stream.get("color_primaries") or "").strip() or None,
        container_format=recipe_model.normalize_container_format(format_payload.get("format_name")),
        keyframe_interval_min=keyframe_interval_min,
        keyframe_interval_max=keyframe_interval_max,
        max_b_frames=_safe_int(output_metrics.get("maxBFrames")),
        b_frame_reordering=(
            bool(output_metrics.get("bFrameReordering"))
            if output_metrics.get("bFrameReordering") is not None
            else None
        ),
        avg_frame_rate=avg_frame_rate,
        time_base=time_base,
        video_stream_count=video_stream_count,
        auxiliary_stream_count=auxiliary_stream_count,
        has_audio=has_audio,
        size_bytes=size_bytes,
        truncated=truncated,
        decode_error=decode_error,
    )


def _build_protocol_config() -> ProtocolConfig:
    threshold = _safe_float(os.environ.get("ENCODINGDB_PROTOCOL_STABILITY_THRESHOLD"))
    adaptive_repeats = _safe_int(os.environ.get("ENCODINGDB_PROTOCOL_MAX_ADAPTIVE_REPEATS"))
    return ProtocolConfig.for_version(
        config.BENCHMARK_PROTOCOL_VERSION,
        stability_threshold_ratio=threshold if threshold is not None and threshold > 0 else 0.03,
        max_adaptive_repeats=adaptive_repeats if adaptive_repeats is not None and adaptive_repeats >= 0 else 2,
    )


def _build_protocol_recipe_specs(
    tasks: List[Dict[str, Any]],
    *,
    default_input_path: str,
    default_input_hash: str,
) -> List[RecipeSpec]:
    specs: List[RecipeSpec] = []
    for task in tasks:
        encoder = str(task.get("encoder") or "").strip()
        preset = str(task.get("preset") or "").strip()
        crf = task.get("crf")
        rate_control = task.get("rateControl")
        effective_input, input_hash, prepared_clip = _resolve_input_for_task(default_input_path, default_input_hash, task)
        source_probe = _probe_artifact_contract(effective_input)
        source_metrics = probe_video_stream_metrics(effective_input)
        source_duration = source_probe.duration_s if source_probe.duration_s is not None else _safe_float(source_metrics.get("sourceDurationSeconds"))
        source_fps = source_probe.avg_frame_rate if source_probe.avg_frame_rate is not None else _safe_float(source_metrics.get("sourceFps"))
        source_frame_count = source_probe.frame_count
        if source_frame_count is None and source_duration is not None and source_fps is not None:
            source_frame_count = int(round(source_duration * source_fps))
        clip_identity = (
            prepared_clip.clip_id
            if isinstance(prepared_clip, PreparedSuiteClip)
            else input_hash
        )
        rate_control_identity = recipe_model.canonical_json(rate_control) if rate_control else str(crf if crf is not None else "none")
        recipe_id = f"{clip_identity}|{encoder}|{preset}|{rate_control_identity}"
        requested_output = requested_output_identity_for_encoder(encoder)
        expectation = StructuralExpectation(
            duration_s=source_duration,
            frame_count=source_frame_count,
            width=source_probe.width,
            height=source_probe.height,
            codec=_infer_expected_codec_name(encoder),
            codec_tag=requested_output.videoTag,
            profile=requested_output.profile,
            level=requested_output.level,
            pix_fmt=requested_output.pixelFormat,
            bit_depth=requested_output.bitDepth,
            chroma_subsampling=requested_output.chromaSubsampling,
            color_range=source_probe.color_range,
            color_space=source_probe.color_space,
            color_transfer=source_probe.color_transfer,
            color_primaries=source_probe.color_primaries,
            container_format=requested_output.containerFormat,
            gop_frames=requested_output.gopFrames,
            keyint_min=requested_output.keyintMin,
            max_b_frames=requested_output.maxBFrames,
            b_frame_reordering=requested_output.bFrameReordering,
            avg_frame_rate=source_fps,
            time_base=source_probe.time_base,
            no_audio=True,
        )
        specs.append(
            RecipeSpec(
                recipe_id=recipe_id,
                expectation=expectation,
                metadata={
                    "encoder": encoder,
                    "preset": preset,
                    "crf": crf,
                    "rateControl": rate_control,
                    "inputPath": effective_input,
                    "inputHash": input_hash,
                    "suiteClip": prepared_clip,
                },
            )
        )
    return specs


def _capture_protocol_environment_snapshot(
    *,
    hardware: HardwareInfo,
    encoder: str,
    background_cpu_seconds: float = 1.0,
    background_cpu_interval: float = 0.25,
) -> EnvironmentSnapshot:
    monitor = HardwareMonitor(
        ffmpeg_pid=None,
        interval=max(0.1, background_cpu_interval),
        encoder_name=encoder,
        host_gpu_vendors=list(getattr(hardware, "gpuVendors", []) or []),
    )
    monitor.start()
    try:
        time.sleep(max(0.1, background_cpu_seconds))
    finally:
        environment_metrics = monitor.stop()
    background_cpu_pct = environment_metrics.cpu_util_avg
    if background_cpu_pct is None:
        background_cpu_pct = measure_background_cpu_load(background_cpu_seconds, background_cpu_interval)
    power_source: Optional[str] = None
    try:
        battery = psutil.sensors_battery()
        if battery is None:
            power_source = "ac"
        else:
            power_source = "ac" if bool(getattr(battery, "power_plugged", False)) else "battery"
    except Exception:
        power_source = None

    free_memory_mb: Optional[float] = None
    memory_pressure_pct: Optional[float] = None
    try:
        memory = psutil.virtual_memory()
        free_memory_mb = float(memory.available) / (1024.0 * 1024.0)
        total_memory = float(memory.total)
        if total_memory > 0:
            memory_pressure_pct = max(0.0, min(100.0, 100.0 - (float(memory.available) / total_memory * 100.0)))
    except Exception:
        free_memory_mb = None
        memory_pressure_pct = None

    cpu_temp_c: Optional[float] = None
    try:
        sensors = psutil.sensors_temperatures()
        if isinstance(sensors, dict):
            for entries in sensors.values():
                if not entries:
                    continue
                values = []
                for entry in entries:
                    current = _safe_float(getattr(entry, "current", None))
                    if current is not None:
                        values.append(current)
                if values:
                    cpu_temp_c = max(values)
                    break
    except Exception:
        cpu_temp_c = None

    return EnvironmentSnapshot(
        background_cpu_pct=background_cpu_pct,
        background_gpu_pct=environment_metrics.gpu_util_avg,
        power_source=environment_metrics.power_source or power_source,
        cpu_temp_c=environment_metrics.cpu_temp_max_c or cpu_temp_c,
        gpu_temp_c=environment_metrics.gpu_temp_max_c,
        thermal_throttle=environment_metrics.thermal_throttle,
        free_memory_mb=free_memory_mb,
        memory_pressure_pct=memory_pressure_pct,
        gpu_power_w=environment_metrics.gpu_power_avg_w,
        gpu_memory_mb=environment_metrics.gpu_mem_peak_mb,
        cpu_frequency_mhz=environment_metrics.cpu_freq_avg_mhz,
        selected_accelerator=encoder if is_hardware_encoder_name(encoder) else "software",
        accelerator_is_hardware=is_hardware_encoder_name(encoder),
        gpu_load_trustworthy=(
            not is_hardware_encoder_name(encoder)
            or int(environment_metrics.gpu_sample_count or 0) > 0
        ),
        gpu_sample_count=int(environment_metrics.gpu_sample_count or 0),
        telemetry_sources=environment_metrics.telemetry_sources,
        telemetry_missing=environment_metrics.telemetry_missing,
    )


def _replay_pending_uploads(
    *,
    queue_dir: str,
    base_url: str,
    api_key: str,
    retries: int,
    use_token: bool,
) -> int:
    stats = replay_spool(
        queue_dir,
        base_url=base_url,
        api_key=api_key,
        retries=max(1, retries),
        use_token=use_token,
    )
    if stats.submitted:
        print_info(f"Submitted {stats.submitted} queued payload(s).")
    if stats.dead_lettered:
        print_warning(f"Moved {stats.dead_lettered} payload(s) to dead-letter.")
    if stats.corrupt:
        print_warning(f"Moved {stats.corrupt} corrupt queue file(s) to dead-letter.")
    return count_pending_entries(queue_dir)


def _persist_protocol_attempt_evidence(queue_dir: str, campaign_result: Any) -> str:
    """Retain every attempt, including warmups and pre-encode invalidations."""
    evidence_dir = os.path.join(queue_dir, "protocol-attempts")
    os.makedirs(evidence_dir, exist_ok=True)
    campaign_id = str(campaign_result.campaign_id)
    final_path = os.path.join(evidence_dir, f"{campaign_id}.json")
    temp_path = final_path + ".tmp"
    payload = campaign_result.to_dict()
    def _json_default(value: Any) -> Any:
        if dataclasses.is_dataclass(value):
            return dataclasses.asdict(value)
        if isinstance(value, set):
            return sorted(value)
        return str(value)

    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(
            payload,
            handle,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=_json_default,
        )
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, final_path)
    return final_path


def _submit_payload_with_spool(
    *,
    queue_dir: str,
    base_url: str,
    payload: Dict[str, Any],
    api_key: str,
    retries: int,
    use_token: bool,
) -> Tuple[str, str, int]:
    path, _entry = spool_payload(queue_dir, payload)
    status, message = submit_spooled_path(
        path,
        queue_dir=queue_dir,
        base_url=base_url,
        api_key=api_key,
        retries=max(1, retries),
        use_token=use_token,
    )
    return status, message, count_pending_entries(queue_dir)


def _has_direct_single_run_intent(raw_args: List[str]) -> bool:
    """Return True when CLI args explicitly request direct single-run execution."""
    direct_flags = (
        "--codec",
        "--presets",
        "--crf",
        "--no-submit",
        "--use-token",
        "--retries",
        "--queue-dir",
        "--batch-size",
    )
    for token in raw_args:
        for flag in direct_flags:
            if token == flag or token.startswith(flag + "="):
                return True
    return False


def build_mode_estimates(presets_cfg: Dict[str, Any]) -> Dict[str, Any]:
    small_minutes = int(presets_cfg.get("smallBenchmark", {}).get("approxMinutes", 5))
    medium_hours = int(presets_cfg.get("mediumBenchmark", presets_cfg.get("smallBenchmark", {})).get("approxHours", 3))
    full_hours = presets_cfg.get("fullBenchmark", {}).get("approxHours")
    try:
        full_hours = int(full_hours) if isinstance(full_hours, int) else float(full_hours)
    except Exception:
        full_hours = 3
    return {
        "smallMinutes": small_minutes,
        "mediumHours": medium_hours,
        "fullHours": full_hours,
    }


def _resolve_crf_values_for_mode(mode: str, presets_cfg: Dict[str, Any], default_crf: int) -> List[int]:
    m = (mode or "").strip().lower()
    if m == "small":
        small_defaults = presets_cfg.get("smallBenchmark", {}).get("crfValues", [])
        return [int(small_defaults[0])] if small_defaults else [default_crf]
    if m == "medium":
        values = [int(v) for v in presets_cfg.get("mediumBenchmark", presets_cfg.get("smallBenchmark", {})).get("crfValues", []) if isinstance(v, int)]
        return values or [default_crf]
    if m == "full":
        values = [int(v) for v in presets_cfg.get("fullBenchmark", {}).get("crfValues", []) if isinstance(v, int)]
        return values or [default_crf]
    return [default_crf]


def build_batch_tasks_for_mode(
    *,
    mode: str,
    presets_cfg: Dict[str, Any],
    encoders: List[str],
    default_crf: int = 24,
    videotoolbox_target_bitrate_kbps: Optional[int] = None,
) -> List[Dict[str, Any]]:
    mode_key = (mode or "").strip().lower()
    if mode_key not in ("small", "medium", "full"):
        raise ValueError(f"Unsupported batch mode: {mode}")
    crf_values = _resolve_crf_values_for_mode(mode_key, presets_cfg, default_crf)
    tasks: List[Dict[str, Any]] = []
    for crf_val in crf_values:
        for enc in encoders:
            if enc.strip().lower().endswith("_videotoolbox"):
                if videotoolbox_target_bitrate_kbps is None or videotoolbox_target_bitrate_kbps <= 0:
                    continue
                task_rate_control: Optional[Dict[str, Any]] = {
                    "mode": "vbr",
                    "targetBitrateKbps": int(videotoolbox_target_bitrate_kbps),
                }
            else:
                task_rate_control = None
            presets_for_encoder = enumerate_supported_presets_for_encoder(enc)
            ordered = sort_presets_by_speed_desc(enc, presets_for_encoder)
            if mode_key == "small":
                if not ordered:
                    continue
                mid_index = max(0, (len(ordered) - 1) // 2)
                picks: List[str] = []
                faster1 = mid_index - 1
                faster2 = mid_index - 2
                if faster2 >= 0:
                    picks.append(ordered[faster2])
                if faster1 >= 0:
                    picks.append(ordered[faster1])
                picks.append(ordered[mid_index])
                seen: Dict[str, bool] = {}
                final = [p for p in picks if not seen.setdefault(p, False)]
                for preset_label in final:
                    tasks.append({"encoder": enc, "preset": preset_label, "crf": None if task_rate_control else crf_val, "rateControl": task_rate_control})
                continue
            if mode_key == "medium":
                if len(ordered) > 0:
                    drop_count = int(round(len(ordered) * 0.2))
                    if drop_count >= len(ordered):
                        drop_count = len(ordered) - 1
                    keep = ordered[:-drop_count] if drop_count > 0 else ordered
                else:
                    keep = ordered
                for preset_label in keep:
                    tasks.append({"encoder": enc, "preset": preset_label, "crf": None if task_rate_control else crf_val, "rateControl": task_rate_control})
                continue
            for preset_label in ordered:
                tasks.append({"encoder": enc, "preset": preset_label, "crf": None if task_rate_control else crf_val, "rateControl": task_rate_control})
    return tasks


def run_benchmark_batch(
    *,
    hardware: HardwareInfo,
    base_url: str,
    args: argparse.Namespace,
    tasks: List[Dict[str, Any]],
    event_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_event: Optional[Any] = None,
) -> int:
    ok, ffmpeg_version = ensure_ffmpeg_and_ffprobe()
    if not ok:
        print("ffmpeg/ffprobe not found in PATH. Please install ffmpeg.", file=sys.stderr)
        return 2
    quality_ok, quality_rc = _ensure_local_quality_stack(event_sink=event_sink, scope="batch")
    if not quality_ok:
        if bool(getattr(args, "no_submit", False)):
            return quality_rc
        print_warning("Continuing without client-local quality diagnostics; server artifact analysis is authoritative.")
    suite_clip = tasks[0].get("suiteClip") if tasks else None
    if not isinstance(suite_clip, PreparedSuiteClip):
        print("Batch benchmark requires EncodingDB Test Suite v1 clip identities.", file=sys.stderr)
        return 3
    input_path = suite_clip.path
    default_input_hash = suite_clip.input_hash
    protocol_config = _build_protocol_config()
    campaign_seed = _safe_int(os.environ.get("ENCODINGDB_PROTOCOL_SEED"))
    recipe_specs = _build_protocol_recipe_specs(
        tasks,
        default_input_path=input_path,
        default_input_hash=default_input_hash,
    )
    recipe_by_id = {recipe.recipe_id: recipe for recipe in recipe_specs}
    client_version = CLIENT_VERSION
    workers = resolve_batch_size(getattr(args, 'batch_size', 0))
    total_tasks = max(
        1,
        len(recipe_specs) * (
            protocol_config.warmup_runs
            + protocol_config.minimum_measured_runs
            + protocol_config.max_adaptive_repeats
        ),
    )
    total_batches = 1
    run_started_at = time.perf_counter()
    use_token = _should_use_submit_token(args)
    baseline_rows: List[Dict[str, Any]] = []
    queued_count = count_pending_entries(args.queue_dir)
    if not getattr(args, 'no_submit', False):
        queued_count = _replay_pending_uploads(
            queue_dir=args.queue_dir,
            base_url=base_url,
            api_key=args.api_key,
            retries=max(1, args.retries),
            use_token=use_token,
        )
    if not getattr(args, 'no_submit', False):
        baseline_rows = fetch_baseline_rows(base_url)

    completed_count_local = 0
    processed_total = 0
    submitted_count = 0
    skipped_count = 0
    failed_count = 0
    _emit_event(
        event_sink,
        "run_start",
        scope="batch",
        totalTasks=total_tasks,
        totalBatches=total_batches,
        workers=workers,
        noSubmit=bool(getattr(args, "no_submit", False)),
        protocol={
            "version": protocol_config.version,
            "warmupRuns": protocol_config.warmup_runs,
            "minimumMeasuredRuns": protocol_config.minimum_measured_runs,
            "stabilityThresholdRatio": protocol_config.stability_threshold_ratio,
            "maxAdaptiveRepeats": protocol_config.max_adaptive_repeats,
            "seed": campaign_seed,
        },
        hardware={
            "cpuModel": hardware.cpuModel,
            "gpuModel": hardware.gpuModel,
            "ramGB": hardware.ramGB,
            "os": hardware.os,
        },
    )
    _emit_counters(event_sink, submitted=submitted_count, skipped=skipped_count, queued=queued_count, failed=failed_count)

    def _batch_status(stage: str, index: int, codec: str = "", preset: str = "") -> str:
        label = f"{codec} {preset}".strip()
        stats = f"ok={submitted_count} skip={skipped_count} queue={queued_count} fail={failed_count}"
        total = max(1, total_tasks)
        if label:
            return f"{stage} {index}/{total}: {label} | {stats}"
        return f"{stage} {index}/{total} | {stats}"

    try:
        with tempfile.TemporaryDirectory() as batch_dir, \
                BatchRunDashboard(total_tasks=total_tasks, total_batches=total_batches, hardware=hardware) as progress:
            print_info(f"Batch 1/{total_batches}: {len(recipe_specs)} protocol recipe(s)")
            progress.start_batch(batch_no=1, batch_size=total_tasks)
            progress.set_description(_batch_status("Batch 1/1 preparing", 1))
            _emit_event(
                event_sink,
                "batch_start",
                batchNo=1,
                totalBatches=total_batches,
                batchSize=len(recipe_specs),
                processedTotal=processed_total,
            )

            def _task_from_recipe(recipe: RecipeSpec) -> Dict[str, Any]:
                return {
                    "encoder": str(recipe.metadata.get("encoder") or ""),
                    "preset": str(recipe.metadata.get("preset") or ""),
                    "crf": recipe.metadata.get("crf"),
                    "rateControl": recipe.metadata.get("rateControl"),
                    "suiteClip": recipe.metadata.get("suiteClip"),
                    "inputPath": str(recipe.metadata.get("inputPath") or input_path),
                    "inputHash": str(recipe.metadata.get("inputHash") or default_input_hash),
                }

            def _sample_environment(schedule: Any, recipe: RecipeSpec) -> EnvironmentSnapshot:
                if _is_cancelled(cancel_event):
                    raise KeyboardInterrupt
                task = _task_from_recipe(recipe)
                progress.set_description(
                    _batch_status(f"{schedule.phase.title()} env", schedule.execution_order, task["encoder"], task["preset"])
                )
                snapshot = _capture_protocol_environment_snapshot(
                    hardware=hardware,
                    encoder=task["encoder"],
                )
                _emit_event(
                    event_sink,
                    "protocol_environment",
                    index=schedule.execution_order,
                    total=total_tasks,
                    recipeId=recipe.recipe_id,
                    campaignId=schedule.campaign_id,
                    phase=schedule.phase,
                    repetitionIndex=schedule.repetition_index,
                    executionOrder=schedule.execution_order,
                    snapshot=snapshot.to_dict(),
                )
                return snapshot

            def _encode_protocol_run(schedule: Any, recipe: RecipeSpec) -> EncodeOutcome:
                if _is_cancelled(cancel_event):
                    raise KeyboardInterrupt
                task = _task_from_recipe(recipe)
                encoder = task["encoder"]
                preset = task["preset"]
                crf = task.get("crf")
                rate_control = task.get("rateControl")
                effective_input = task["inputPath"]
                input_hash = task["inputHash"]
                prepared_clip = task.get("suiteClip")
                source_probe = probe_video_stream_metrics(effective_input)
                source_frame_count = recipe.expectation.frame_count
                if source_frame_count is None:
                    source_duration = _safe_float(source_probe.get("sourceDurationSeconds"))
                    source_fps = _safe_float(source_probe.get("sourceFps"))
                    if source_duration is not None and source_fps is not None:
                        source_frame_count = int(round(source_duration * source_fps))
                source_fps_value = _safe_float(source_probe.get("sourceFps")) or recipe.expectation.avg_frame_rate or 0.0
                artifact_name = (
                    f"{schedule.execution_order:03d}-"
                    f"{encoder.replace('/', '_')}-{preset}-{str(crf) if crf is not None else 'none'}-"
                    f"{schedule.phase}-r{schedule.repetition_index}.mp4"
                )
                progress.set_description(
                    _batch_status(f"{schedule.phase.title()} encode", schedule.execution_order, encoder, preset)
                    + f" [{encoder}, {preset}, crf={crf}]"
                )
                progress.set_current_test(
                    stage=f"{schedule.phase.title()} Encode",
                    encoder=encoder,
                    preset=preset,
                    crf=crf,
                    rate_control=rate_control,
                    passes=1,
                    isHardware=is_hardware_encoder_name(encoder),
                )
                _emit_event(
                    event_sink,
                    "encode_start",
                    index=schedule.execution_order,
                    total=total_tasks,
                    encoder=encoder,
                    preset=preset,
                    crf=crf,
                    campaignId=schedule.campaign_id,
                    recipeId=recipe.recipe_id,
                    phase=schedule.phase,
                    repetitionIndex=schedule.repetition_index,
                    executionOrder=schedule.execution_order,
                )
                start_ns = time.perf_counter_ns()
                info = encode_to_artifact(
                    input_path=effective_input,
                    encoder=encoder,
                    preset=preset,
                    crf=crf,
                    out_dir=batch_dir,
                    artifact_name=artifact_name,
                    host_gpu_vendors=list(getattr(hardware, 'gpuVendors', []) or []),
                )
                end_ns = time.perf_counter_ns()
                info["task"] = task
                info["_input_hash"] = input_hash
                info["_effective_input"] = effective_input
                info["_suite_clip"] = prepared_clip
                info["_source_probe"] = source_probe
                artifact_contract = _probe_artifact_contract(str(info["artifactPath"]))
                encoded_frame_count = artifact_contract.frame_count or source_frame_count
                if source_frame_count is None:
                    source_frame_count = encoded_frame_count
                timing = EncodeTiming.from_measurement(
                    start_monotonic_ns=start_ns,
                    end_monotonic_ns=end_ns,
                    source_frame_count=source_frame_count or 1,
                    encoded_frame_count=encoded_frame_count or source_frame_count or 1,
                    source_fps=source_fps_value or 1.0,
                    ffmpeg_cpu_time_s=_safe_float(info.get("ffmpegCpuTimeS")),
                )
                final_encoder = str(info.get('encoderUsed') or encoder)
                final_preset = str(info.get('presetUsed') or preset)
                progress.set_current_test(
                    stage=f"{schedule.phase.title()} Encoded",
                    encoder=final_encoder,
                    preset=final_preset,
                    crf=crf,
                    passes=1,
                    isHardware=is_hardware_encoder_name(final_encoder),
                )
                progress.update_machine_metrics(info)
                _emit_event(
                    event_sink,
                    "encode_done",
                    index=schedule.execution_order,
                    total=total_tasks,
                    encoder=final_encoder,
                    preset=final_preset,
                    crf=crf,
                    fps=float(timing.encode_fps),
                    fileSizeBytes=int(info.get("fileSizeBytes") or 0),
                    runMs=int(round(timing.elapsed_s * 1000.0)),
                    error=info.get("error"),
                    telemetry={
                        key: info[key]
                        for key in list(EXTENDED_TELEMETRY_KEYS) + list(RAW_TELEMETRY_KEYS) + [
                            'gpuUtilAvg', 'gpuPowerAvgW', 'gpuMemPeakMB',
                            'cpuUtilAvg', 'cpuUtilMax', 'peakMemoryMB', 'thermalThrottle',
                        ]
                        if key in info
                    },
                    campaignId=schedule.campaign_id,
                    recipeId=recipe.recipe_id,
                    phase=schedule.phase,
                    repetitionIndex=schedule.repetition_index,
                    executionOrder=schedule.execution_order,
                )
                progress.advance_phase(
                    description=_batch_status(f"{schedule.phase.title()} encoded", schedule.execution_order, final_encoder, final_preset),
                )
                return EncodeOutcome(
                    timing=timing,
                    probe=artifact_contract,
                    artifact_path=str(info["artifactPath"]),
                    metadata={
                        "info": info,
                        "inputHash": input_hash,
                        "effectiveInput": effective_input,
                        "suiteClip": prepared_clip,
                        "sourceProbe": source_probe,
                    },
                )

            campaign_result = execute_protocol_campaign(
                recipes=recipe_specs,
                config=protocol_config,
                encode_runner=_encode_protocol_run,
                environment_sampler=_sample_environment,
                seed=campaign_seed,
            )
            attempt_evidence_path = _persist_protocol_attempt_evidence(args.queue_dir, campaign_result)
            _emit_event(
                event_sink,
                "protocol_attempt_evidence_retained",
                campaignId=campaign_result.campaign_id,
                seed=campaign_result.seed,
                path=attempt_evidence_path,
            )

            measured_records: List[Tuple[RecipeSpec, Any]] = []
            for recipe_result in campaign_result.recipe_results:
                recipe = recipe_by_id[recipe_result.recipe_id]
                _emit_event(
                    event_sink,
                    "protocol_recipe_complete",
                    recipeId=recipe_result.recipe_id,
                    campaignId=campaign_result.campaign_id,
                    stability=recipe_result.stability.to_dict(),
                    measuredRunsCompleted=recipe_result.measured_runs_completed,
                    measuredRunsCounted=recipe_result.measured_runs_counted,
                )
                for record in recipe_result.runs:
                    if record.schedule.phase == "measured":
                        measured_records.append((recipe, record))

            for recipe, record in measured_records:
                if _is_cancelled(cancel_event):
                    raise KeyboardInterrupt
                info = dict(record.metadata.get("info") or {})
                task = _task_from_recipe(recipe)
                if record.skipped_before_encode or record.timing is None or not info or info.get("error") is not None:
                    record.metadata["metrics"] = {}
                    continue
                progress.set_description(
                    _batch_status("Metrics", record.schedule.execution_order, str(info.get('encoderUsed') or task['encoder']), str(info.get('presetUsed') or task['preset']))
                )
                progress.set_current_test(
                    stage="Metrics",
                    encoder=str(info.get('encoderUsed') or task['encoder']),
                    preset=str(info.get('presetUsed') or task['preset']),
                    crf=task.get('crf'),
                    passes=1,
                    isHardware=is_hardware_encoder_name(str(info.get('encoderUsed') or task['encoder'])),
                )
                _emit_event(
                    event_sink,
                    "metrics_start",
                    index=record.schedule.execution_order,
                    total=total_tasks,
                    encoder=str(info.get('encoderUsed') or task['encoder']),
                    preset=str(info.get('presetUsed') or task['preset']),
                    crf=task.get('crf'),
                    campaignId=record.schedule.campaign_id,
                    recipeId=recipe.recipe_id,
                    repetitionIndex=record.schedule.repetition_index,
                    executionOrder=record.schedule.execution_order,
                )
                metrics = compute_metrics_parallel(
                    str(record.metadata.get("effectiveInput") or input_path),
                    [str(info["artifactPath"])],
                    workers,
                    quiet=True,
                )
                record.metadata["metrics"] = metrics.get(str(info["artifactPath"]), {})
                _emit_event(
                    event_sink,
                    "metrics_done",
                    index=record.schedule.execution_order,
                    total=total_tasks,
                    encoder=str(info.get('encoderUsed') or task['encoder']),
                    preset=str(info.get('presetUsed') or task['preset']),
                    crf=task.get('crf'),
                    metrics=record.metadata.get("metrics", {}),
                    campaignId=record.schedule.campaign_id,
                    recipeId=recipe.recipe_id,
                    repetitionIndex=record.schedule.repetition_index,
                    executionOrder=record.schedule.execution_order,
                )
                progress.advance_phase(
                    description=_batch_status("Metrics done", record.schedule.execution_order, str(info.get('encoderUsed') or task['encoder']), str(info.get('presetUsed') or task['preset'])),
                )

            for recipe, record in measured_records:
                if _is_cancelled(cancel_event):
                    raise KeyboardInterrupt
                task = _task_from_recipe(recipe)
                info = dict(record.metadata.get("info") or {})
                codec_label = str(info.get('encoderUsed') or task['encoder'])
                preset_label = str(info.get('presetUsed') or task['preset'])
                next_index = processed_total + 1
                progress.set_description(_batch_status("Submitting", next_index, codec_label, preset_label))
                progress.set_current_test(
                    stage="Submitting",
                    encoder=codec_label,
                    preset=preset_label,
                    crf=task.get('crf'),
                    passes=1,
                    isHardware=is_hardware_encoder_name(codec_label),
                )
                _emit_event(
                    event_sink,
                    "submit_start",
                    index=next_index,
                    total=total_tasks,
                    codec=codec_label,
                    preset=preset_label,
                    crf=task.get("crf"),
                    dryRun=bool(args.no_submit),
                    campaignId=record.schedule.campaign_id,
                    recipeId=recipe.recipe_id,
                    repetitionIndex=record.schedule.repetition_index,
                    executionOrder=record.schedule.execution_order,
                )

                if record.skipped_before_encode or record.overall_validity.state == "invalid" or not info or record.timing is None:
                    reason_codes = [reason.code for reason in record.overall_validity.reasons]
                    print_warning(
                        f"Skipped submission for {codec_label} {preset_label} due to protocol invalidation"
                        + (f" ({','.join(reason_codes)})" if reason_codes else "")
                    )
                    skipped_count += 1
                    progress.update_counters(
                        submitted=submitted_count, skipped=skipped_count,
                        queued=queued_count, failed=failed_count,
                    )
                    _emit_event(
                        event_sink,
                        "submit_result",
                        index=next_index,
                        total=total_tasks,
                        status="protocol_invalid",
                        reasonCodes=reason_codes,
                        campaignId=record.schedule.campaign_id,
                        recipeId=recipe.recipe_id,
                        repetitionIndex=record.schedule.repetition_index,
                        executionOrder=record.schedule.execution_order,
                    )
                    _emit_counters(
                        event_sink,
                        submitted=submitted_count,
                        skipped=skipped_count,
                        queued=queued_count,
                        failed=failed_count,
                    )
                    processed_total += 1
                    progress.advance(description=_batch_status("Completed", processed_total, codec_label, preset_label))
                    _emit_event(event_sink, "task_complete", scope="batch", processed=processed_total, total=total_tasks)
                    continue

                prepared_clip = record.metadata.get("suiteClip")
                payload: Dict[str, Any] = {
                    'cpuModel': hardware.cpuModel,
                    'gpuModel': hardware.gpuModel or "",
                    'ramGB': hardware.ramGB,
                    'os': hardware.os,
                    'codec': codec_label,
                    'preset': preset_label,
                    'crf': task.get('crf'),
                    'passes': 1,
                    'fps': float(record.timing.encode_fps),
                    'fileSizeBytes': int(info.get('fileSizeBytes') or 0),
                    'runMs': int(round(record.timing.elapsed_s * 1000.0)),
                    'ffmpegVersion': ffmpeg_version,
                    'encoderName': codec_label,
                    'clientVersion': client_version,
                    'inputHash': str(record.metadata.get('inputHash') or default_input_hash),
                    'benchmarkProtocolVersion': config.BENCHMARK_PROTOCOL_VERSION,
                }
                if isinstance(prepared_clip, PreparedSuiteClip):
                    payload['sourceSuiteVersion'] = prepared_clip.suite_version
                    payload['workloadId'] = prepared_clip.workload_id
                    payload['contentClass'] = prepared_clip.payload_content_class
                source_probe = record.metadata.get('sourceProbe') if isinstance(record.metadata.get('sourceProbe'), dict) else {}
                if source_probe.get('sourceFps') is not None:
                    payload['sourceFps'] = float(source_probe['sourceFps'])
                if source_probe.get('sourceDurationSeconds') is not None:
                    payload['sourceDurationSeconds'] = float(source_probe['sourceDurationSeconds'])
                artifact_probe = probe_video_stream_metrics(str(info['artifactPath']))
                if artifact_probe.get('videoBitrateBps') is not None:
                    payload['videoBitrateBps'] = float(artifact_probe['videoBitrateBps'])
                artifact_metrics = record.metadata.get('metrics', {})
                vmaf_score = artifact_metrics.get('vmaf')
                if vmaf_score is not None:
                    payload['vmaf'] = float(vmaf_score)
                vmaf_mean = artifact_metrics.get('vmafMean')
                if vmaf_mean is not None:
                    payload['vmafMean'] = float(vmaf_mean)
                vmaf_p5 = artifact_metrics.get('vmafP5')
                if vmaf_p5 is not None:
                    payload['vmafP5'] = float(vmaf_p5)
                metric_model_id = artifact_metrics.get('metricModelId')
                if metric_model_id:
                    payload['metricModelId'] = str(metric_model_id)
                _apply_v7_score_contract(payload)
                ssim_score = artifact_metrics.get('ssim')
                if ssim_score is not None:
                    payload['ssim'] = float(ssim_score)
                psnr_score = artifact_metrics.get('psnr')
                if psnr_score is not None:
                    payload['psnr'] = float(psnr_score)
                execution_identity_payload = build_execution_identity_payload(
                    hardware=hardware,
                    artifact_info=info,
                    ffmpeg_version=ffmpeg_version,
                    client_version=client_version,
                    benchmark_protocol_version=config.BENCHMARK_PROTOCOL_VERSION,
                )
                payload.update(execution_identity_payload)

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
                if isinstance(prepared_clip, PreparedSuiteClip):
                    note_parts.append(_suite_identity_note(prepared_clip))
                if info.get('failureCode'):
                    note_parts.append(f"failure_code={info['failureCode']}")
                telemetry_notes = info.get('telemetryNotes')
                if isinstance(telemetry_notes, list):
                    note_parts.extend([str(part).strip() for part in telemetry_notes if str(part).strip()])
                elif info.get('telemetryNote'):
                    note_parts.append(str(info['telemetryNote']).strip())
                if record.environment_snapshot is not None:
                    _append_note_chunk(note_parts, "protocol_env", record.environment_snapshot.to_dict())
                _append_note_chunk(
                    note_parts,
                    "protocol_run",
                    {
                        "campaignId": record.schedule.campaign_id,
                        "recipeId": recipe.recipe_id,
                        "phase": record.schedule.phase,
                        "repetitionIndex": record.schedule.repetition_index,
                        "executionOrder": record.schedule.execution_order,
                        "overallValidity": record.overall_validity.state,
                        "environmentValidity": record.environment_validity.state,
                        "structuralValidity": record.structural_validity.state,
                    },
                )
                _append_note_chunk(
                    note_parts,
                    "protocol_timing",
                    {
                        "elapsedSeconds": round(record.timing.elapsed_s, 6),
                        "sourceFrameCount": record.timing.source_frame_count,
                        "encodedFrameCount": record.timing.encoded_frame_count,
                        "sourceFps": round(record.timing.source_fps, 6),
                        "encodeFps": round(record.timing.encode_fps, 6),
                        "realtimeMultiple": round(record.timing.realtime_multiple, 6),
                        "ffmpegCpuTimeS": record.timing.ffmpeg_cpu_time_s,
                    },
                )
                _append_note_chunk(
                    note_parts,
                    "protocol_validity",
                    {
                        "overall": [reason.code for reason in record.overall_validity.reasons],
                        "environment": [reason.code for reason in record.environment_validity.reasons],
                        "structural": [reason.code for reason in record.structural_validity.reasons],
                    },
                )
                if note_parts:
                    payload['notes'] = "; ".join(note_parts)[:3500]

                skip, reason = should_skip_submission(
                    hardware=hardware,
                    payload=payload,
                    background_cpu_pct=float(getattr(record.environment_snapshot, 'background_cpu_pct', 0.0) or 0.0),
                    baseline_rows=baseline_rows,
                )
                if skip:
                    print_warning(f"Skipped submission for {payload['codec']} {payload['preset']} (reason: {reason})")
                    skipped_count += 1
                    progress.update_counters(
                        submitted=submitted_count, skipped=skipped_count,
                        queued=queued_count, failed=failed_count,
                    )
                    _emit_event(
                        event_sink,
                        "submit_result",
                        index=next_index,
                        total=total_tasks,
                        status="skipped",
                        reason=reason,
                        campaignId=record.schedule.campaign_id,
                        recipeId=recipe.recipe_id,
                        repetitionIndex=record.schedule.repetition_index,
                        executionOrder=record.schedule.execution_order,
                    )
                elif args.no_submit:
                    if payload.get('scoreEligibilityNote'):
                        print_info(str(payload['scoreEligibilityNote']))
                    if record.overall_validity.state == "suspect":
                        print_warning(
                            f"Protocol suspect for {payload['codec']} {payload['preset']}: "
                            + ",".join([reason.code for reason in record.overall_validity.reasons])
                        )
                    progress.set_description(_batch_status("Dry-run", next_index, str(payload['codec']), str(payload['preset'])))
                    progress.update_counters(
                        submitted=submitted_count, skipped=skipped_count,
                        queued=queued_count, failed=failed_count,
                    )
                    _emit_event(
                        event_sink,
                        "submit_result",
                        index=next_index,
                        total=total_tasks,
                        status="dry_run",
                        protocolValidity=record.overall_validity.to_dict(),
                        campaignId=record.schedule.campaign_id,
                        recipeId=recipe.recipe_id,
                        repetitionIndex=record.schedule.repetition_index,
                        executionOrder=record.schedule.execution_order,
                    )
                else:
                    if payload.get('scoreEligibilityNote') and not payload.get('scoreFormulaVersion'):
                        print_warning(str(payload['scoreEligibilityNote']))
                    if record.overall_validity.state == "suspect":
                        print_warning(
                            f"Submitting suspect protocol evidence for {payload['codec']} {payload['preset']}: "
                            + ",".join([reason.code for reason in record.overall_validity.reasons])
                        )
                    status = "failed"
                    error_text = ""
                    try:
                        artifact_sha256 = sha256_of_file(str(info["artifactPath"]))
                        info["artifactSha256"] = artifact_sha256
                        authoritative_run_create = _build_authoritative_run_create_request(
                            prepared_clip=prepared_clip,
                            recipe_id=recipe.recipe_id,
                            record=record,
                            info=info,
                            metrics=artifact_metrics,
                            hardware=hardware,
                            source_probe=source_probe,
                            artifact_probe=artifact_probe,
                            ffmpeg_version=ffmpeg_version,
                            client_version=client_version,
                            execution_identity_payload=execution_identity_payload,
                            protocol_config=protocol_config,
                        )
                        authoritative_submission = build_artifact_submission_payload(
                            artifact_path=str(info["artifactPath"]),
                            media_container=artifact_probe.get("containerFormat"),
                            run_create=authoritative_run_create,
                        )
                        status, error_text, queued_count = _submit_payload_with_spool(
                            queue_dir=args.queue_dir,
                            base_url=base_url,
                            payload=authoritative_submission,
                            api_key=args.api_key,
                            retries=max(1, args.retries),
                            use_token=use_token,
                        )
                        if status == "submitted":
                            queued_count = _replay_pending_uploads(
                                queue_dir=args.queue_dir,
                                base_url=base_url,
                                api_key=args.api_key,
                                retries=max(1, args.retries),
                                use_token=use_token,
                            )
                            submitted_count += 1
                            if error_text:
                                print_info(f"Authoritative benchmark run recorded as {error_text}.")
                            _emit_event(
                                event_sink,
                                "submit_result",
                                index=next_index,
                                total=total_tasks,
                                status="submitted",
                                benchmarkRunId=error_text or None,
                                protocolValidity=record.overall_validity.to_dict(),
                                campaignId=record.schedule.campaign_id,
                                recipeId=recipe.recipe_id,
                                repetitionIndex=record.schedule.repetition_index,
                                executionOrder=record.schedule.execution_order,
                            )
                        elif status == "retained":
                            print_warning(f"Queued payload for retry: {payload['preset']} ({error_text})")
                            _emit_event(
                                event_sink,
                                "submit_result",
                                index=next_index,
                                total=total_tasks,
                                status="queued",
                                error=error_text,
                                campaignId=record.schedule.campaign_id,
                                recipeId=recipe.recipe_id,
                                repetitionIndex=record.schedule.repetition_index,
                                executionOrder=record.schedule.execution_order,
                            )
                        else:
                            failed_count += 1
                            print(f"Failed to submit {payload['preset']}: {error_text}", file=sys.stderr)
                            _emit_event(
                                event_sink,
                                "submit_result",
                                index=next_index,
                                total=total_tasks,
                                status="failed",
                                error=error_text,
                                campaignId=record.schedule.campaign_id,
                                recipeId=recipe.recipe_id,
                                repetitionIndex=record.schedule.repetition_index,
                                executionOrder=record.schedule.execution_order,
                            )
                    except Exception as e:
                        failed_count += 1
                        error_text = str(e)
                        print(f"Failed to submit {payload['preset']}: {error_text}", file=sys.stderr)
                        queued_count = count_pending_entries(args.queue_dir)
                        _emit_event(
                            event_sink,
                            "submit_result",
                            index=next_index,
                            total=total_tasks,
                            status="failed",
                            error=error_text,
                            campaignId=record.schedule.campaign_id,
                            recipeId=recipe.recipe_id,
                            repetitionIndex=record.schedule.repetition_index,
                            executionOrder=record.schedule.execution_order,
                        )
                    progress.update_counters(
                        submitted=submitted_count, skipped=skipped_count,
                        queued=queued_count, failed=failed_count,
                    )
                _emit_counters(
                    event_sink,
                    submitted=submitted_count,
                    skipped=skipped_count,
                    queued=queued_count,
                    failed=failed_count,
                )

                if float(payload.get('fps', 0.0)) > 0.0 and int(payload.get('fileSizeBytes', 0)) > 0:
                    completed_count_local += 1
                    if config._BATCH_ACTIVE:
                        with config._GLOBAL_STATE_LOCK:
                            config._BATCH_COMPLETED_COUNT += 1

                processed_total += 1
                progress.advance(description=_batch_status("Completed", processed_total, str(payload['codec']), str(payload['preset'])))
                _emit_event(event_sink, "task_complete", scope="batch", processed=processed_total, total=total_tasks)
    except KeyboardInterrupt:
        print_warning("Batch run interrupted by user.")
        _emit_event(event_sink, "run_interrupted", scope="batch", processed=processed_total, total=total_tasks)
        return 130

    elapsed_seconds = max(0.0, time.perf_counter() - run_started_at)
    if not getattr(args, 'no_submit', False):
        queued_count = _replay_pending_uploads(
            queue_dir=args.queue_dir,
            base_url=base_url,
            api_key=args.api_key,
            retries=max(1, args.retries),
            use_token=use_token,
        )
    throughput_per_hour = (completed_count_local / elapsed_seconds * 3600.0) if elapsed_seconds > 0 else 0.0
    print_batch_summary({
        "totalTasks": total_tasks,
        "totalBatches": total_batches,
        "completed": completed_count_local,
        "submitted": submitted_count,
        "skipped": skipped_count,
        "queued": queued_count,
        "failed": failed_count,
        "elapsedSeconds": elapsed_seconds,
        "throughputPerHour": throughput_per_hour,
    })
    _emit_event(
        event_sink,
        "run_complete",
        scope="batch",
        totalTasks=total_tasks,
        totalBatches=total_batches,
        completed=completed_count_local,
        submitted=submitted_count,
        skipped=skipped_count,
        queued=queued_count,
        failed=failed_count,
        elapsedSeconds=elapsed_seconds,
        throughputPerHour=throughput_per_hour,
    )
    if bool(getattr(args, "strict_authoritative", False)) and not getattr(args, "no_submit", False):
        if queued_count or failed_count or skipped_count:
            return 1
        if submitted_count <= 0:
            return 1
    return 0


def run_v7_suite_clip_mode(
    *,
    base_args: argparse.Namespace,
    event_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_event: Optional[Any] = None,
) -> int:
    clip_id = str(getattr(base_args, "v7_suite_clip", "") or "").strip()
    if not clip_id:
        print("--v7-suite-clip is required for v7 suite clip mode.", file=sys.stderr)
        return 1
    try:
        suite_clip = _prepare_named_suite_clip(clip_id)
    except Exception as exc:
        print(f"Unable to prepare suite clip {clip_id}: {exc}", file=sys.stderr)
        return 3

    requested_codec = str(getattr(base_args, "codec", "") or "").strip()
    if not requested_codec:
        print("--codec is required for noninteractive v7 suite clip mode.", file=sys.stderr)
        return 4
    if has_encoder(requested_codec):
        resolved_encoder = requested_codec
    else:
        family = normalize_codec_family(requested_codec)
        resolved_encoder = pick_software_encoder_for_family(family) if family else None
    if not resolved_encoder or not has_encoder(resolved_encoder):
        print(f"Requested encoder '{requested_codec}' is not available.", file=sys.stderr)
        return 4
    if is_hardware_encoder_name(resolved_encoder) and not is_hardware_encoder_usable(resolved_encoder):
        print(f"Selected hardware encoder '{resolved_encoder}' is not usable on this machine.", file=sys.stderr)
        return 4

    preset_list = [value.strip() for value in str(getattr(base_args, "presets", "") or "").split(",") if value.strip()]
    if not preset_list:
        preset_list = ["medium"]
    crf_value = getattr(base_args, "crf", None)
    tasks = [
        {
            "encoder": resolved_encoder,
            "preset": preset,
            "crf": crf_value,
            "suiteClip": suite_clip,
        }
        for preset in preset_list
    ]
    strict_args = argparse.Namespace(
        base_url=base_args.base_url,
        api_key=base_args.api_key,
        no_submit=base_args.no_submit,
        crf=crf_value,
        retries=base_args.retries,
        queue_dir=base_args.queue_dir,
        menu=False,
        batch_size=getattr(base_args, "batch_size", 0),
        use_token=getattr(base_args, "use_token", False),
        strict_authoritative=True,
    )
    return run_benchmark_batch(
        hardware=detect_hardware(),
        base_url=base_args.base_url,
        args=strict_args,
        tasks=tasks,
        event_sink=event_sink,
        cancel_event=cancel_event,
    )


def run_with_args(
    args: argparse.Namespace,
    *,
    event_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_event: Optional[Any] = None,
    show_end_screen: bool = True,
) -> int:
    ok, ffmpeg_version = ensure_ffmpeg_and_ffprobe()
    if not ok:
        print("ffmpeg/ffprobe not found in PATH. Please install ffmpeg.", file=sys.stderr)
        _emit_event(event_sink, "run_error", scope="single", code=2, message="ffmpeg/ffprobe not found")
        return 2
    if not config._FFMPEG_DETECTED_PRINTED:
        ver = "unknown"
        try:
            m = re.search(r"version\s*([\w\.-]+)", ffmpeg_version or "", flags=re.IGNORECASE)
            if m:
                ver = m.group(1)
        except Exception:
            ver = "unknown"
        print(f"FFmpeg (Version {ver}) Detected")
        config._FFMPEG_DETECTED_PRINTED = True
    quality_ok, quality_rc = _ensure_local_quality_stack(event_sink=event_sink, scope="single")
    if not quality_ok:
        return quality_rc

    try:
        quick_clip = _prepare_quick_suite_clip()
    except Exception as exc:
        print(f"EncodingDB Test Suite v1 quick clip is unavailable: {exc}", file=sys.stderr)
        _emit_event(event_sink, "run_error", scope="single", code=3, message=f"suite quick clip unavailable: {exc}")
        return 3
    input_path = quick_clip.path

    resolved_encoder: Optional[str] = None
    explicit_encoder_selection = False
    user_codec = (args.codec or "").strip()
    if user_codec and has_encoder(user_codec):
        resolved_encoder = user_codec
        explicit_encoder_selection = True
    else:
        family = normalize_codec_family(user_codec) if user_codec else None
        if not family:
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
            idx = prompt_choice("Use Hardware Acceleration? Choose engine", labels + ["No (software)"], default_index=len(labels))
            if idx < len(labels):
                resolved_encoder = hw_options[idx][0]

        if not resolved_encoder:
            sw = pick_software_encoder_for_family(family)
            if not sw:
                print("No media engine detected for the selected codec, using Software Encoding")
            resolved_encoder = sw

    if not resolved_encoder or not has_encoder(resolved_encoder):
        print("Requested codec/encoder not available in this ffmpeg build.", file=sys.stderr)
        _emit_event(event_sink, "run_error", scope="single", code=4, message="requested encoder unavailable")
        return 4
    if is_hardware_encoder_name(resolved_encoder) and not is_hardware_encoder_usable(resolved_encoder):
        if explicit_encoder_selection:
            print(
                f"Selected hardware encoder '{resolved_encoder}' is not usable on this machine.",
                file=sys.stderr,
            )
        else:
            print(
                f"Selected hardware encoder '{resolved_encoder}' is not usable on this machine.",
                file=sys.stderr,
            )
        _emit_event(event_sink, "run_error", scope="single", code=4, message="hardware encoder unusable")
        return 4

    hardware = detect_hardware()
    input_hash = quick_clip.input_hash
    client_version = CLIENT_VERSION
    combos: List[Tuple[str, Optional[int]]] = []
    try:
        preset_list = [s.strip() for s in args.presets.split(",") if s.strip()]
    except Exception:
        preset_list = ["fast", "medium", "slow"]

    base_url = args.base_url
    use_token = _should_use_submit_token(args)
    user_crf: Optional[int] = args.crf
    if preset_list:
        combos = [(p, user_crf) for p in preset_list]
    queued_count = count_pending_entries(args.queue_dir)
    if not args.no_submit:
        queued_count = _replay_pending_uploads(
            queue_dir=args.queue_dir,
            base_url=base_url,
            api_key=args.api_key,
            retries=max(1, args.retries),
            use_token=use_token,
        )
    submitted_count = 0
    skipped_count = 0
    failed_count = 0
    _emit_event(
        event_sink,
        "run_start",
        scope="single",
        totalTasks=len(combos),
        encoder=resolved_encoder,
        presets=[p for p, _ in combos],
        noSubmit=bool(args.no_submit),
        hardware={
            "cpuModel": hardware.cpuModel,
            "gpuModel": hardware.gpuModel,
            "ramGB": hardware.ramGB,
            "os": hardware.os,
        },
    )
    _emit_counters(event_sink, submitted=submitted_count, skipped=skipped_count, queued=queued_count, failed=failed_count)
    benchmark_start_ts = time.perf_counter()
    try:
        original_size_bytes = os.path.getsize(input_path)
    except Exception:
        original_size_bytes = 0
    completed_count = 0
    with BenchmarkProgress(len(combos), title="Single Benchmark Progress (content-specific quick test)") as progress:
        for task_index, (preset, crf_val) in enumerate(combos, start=1):
            if _is_cancelled(cancel_event):
                _emit_event(event_sink, "run_interrupted", scope="single", completed=completed_count, total=len(combos))
                return 130
            progress.set_description(f"Running {resolved_encoder} {preset} crf={crf_val}")
            print_info(f"Running Test: {resolved_encoder}, crf={crf_val}, {preset}...")
            _emit_event(
                event_sink,
                "encode_start",
                scope="single",
                index=task_index,
                total=len(combos),
                encoder=resolved_encoder,
                preset=preset,
                crf=crf_val,
            )
            payload = run_single_benchmark(
                hardware,
                input_path,
                preset=preset,
                codec=resolved_encoder,
                crf=crf_val,
                source_suite_version=quick_clip.suite_version,
                workload_id=quick_clip.workload_id,
                content_class=quick_clip.payload_content_class,
                ffmpeg_version=ffmpeg_version,
                client_version=client_version,
                benchmark_protocol_version=config.BENCHMARK_PROTOCOL_VERSION,
            )
            payload["ffmpegVersion"] = ffmpeg_version
            payload["encoderName"] = payload.get("codec", resolved_encoder)
            payload["clientVersion"] = client_version
            payload["inputHash"] = input_hash
            payload["passes"] = 1
            payload["benchmarkProtocolVersion"] = config.BENCHMARK_PROTOCOL_VERSION
            payload["sourceSuiteVersion"] = quick_clip.suite_version
            payload["workloadId"] = quick_clip.workload_id
            payload["contentClass"] = quick_clip.payload_content_class
            suite_note = _suite_identity_note(quick_clip)
            if payload.get("notes"):
                payload["notes"] = f"{suite_note}; {payload['notes']}"[:3500]
            else:
                payload["notes"] = suite_note
            _apply_v7_score_contract(payload)
            effective_preset = str(payload.get("preset") or preset)

            size_val = payload.get("fileSizeBytes")
            try:
                rel_size = (float(size_val) / float(original_size_bytes) * 100.0) if original_size_bytes > 0 else None
            except Exception:
                rel_size = None
            print_benchmark_result(payload, rel_size)
            if payload.get("scoreEligibilityNote"):
                print_info(str(payload["scoreEligibilityNote"]))
            _emit_event(
                event_sink,
                "encode_done",
                scope="single",
                index=task_index,
                total=len(combos),
                encoder=payload.get("codec", resolved_encoder),
                preset=effective_preset,
                crf=crf_val,
                fps=float(payload.get("fps") or 0.0),
                fileSizeBytes=int(payload.get("fileSizeBytes") or 0),
                runMs=int(payload.get("runMs") or 0),
                telemetry={
                    key: payload[key]
                    for key in list(EXTENDED_TELEMETRY_KEYS) + list(RAW_TELEMETRY_KEYS) + [
                        'gpuUtilAvg', 'gpuPowerAvgW', 'gpuMemPeakMB',
                        'cpuUtilAvg', 'cpuUtilMax', 'peakMemoryMB', 'thermalThrottle',
                    ]
                    if key in payload
                },
                metrics={
                    "vmaf": payload.get("vmaf"),
                    "ssim": payload.get("ssim"),
                    "psnr": payload.get("psnr"),
                },
            )

            if float(payload.get("fps", 0.0)) > 0.0 and int(payload.get("fileSizeBytes", 0)) > 0:
                completed_count += 1
                if config._BATCH_ACTIVE:
                    with config._GLOBAL_STATE_LOCK:
                        config._BATCH_COMPLETED_COUNT += 1

            if args.no_submit:
                print_info(f"Dry-run: not submitting preset={effective_preset}")
                progress.advance(description=f"{effective_preset} (dry-run)")
                _emit_event(event_sink, "submit_result", scope="single", index=task_index, total=len(combos), status="dry_run", preset=effective_preset)
                _emit_event(event_sink, "task_complete", scope="single", processed=task_index, total=len(combos), preset=effective_preset)
                continue
            try:
                if payload.get("fps", 0.0) <= 0 or payload.get("fileSizeBytes", 0) <= 0:
                    print_warning(
                        f"Skipped submission for preset={effective_preset} due to encode failure "
                        f"(fps={payload.get('fps')}, size={payload.get('fileSizeBytes')})"
                    )
                    failed_count += 1
                    progress.advance(description=f"{effective_preset} (failed)")
                    _emit_event(event_sink, "submit_result", scope="single", index=task_index, total=len(combos), status="failed", preset=effective_preset)
                    _emit_counters(event_sink, submitted=submitted_count, skipped=skipped_count, queued=queued_count, failed=failed_count)
                    _emit_event(event_sink, "task_complete", scope="single", processed=task_index, total=len(combos), preset=effective_preset)
                    continue
                clean_payload = sanitize_payload_for_server(payload)
                status, message, queued_count = _submit_payload_with_spool(
                    queue_dir=args.queue_dir,
                    base_url=base_url,
                    payload=clean_payload,
                    api_key=args.api_key,
                    retries=max(1, args.retries),
                    use_token=use_token,
                )
                if status == "submitted":
                    queued_count = _replay_pending_uploads(
                        queue_dir=args.queue_dir,
                        base_url=base_url,
                        api_key=args.api_key,
                        retries=max(1, args.retries),
                        use_token=use_token,
                    )
                    submitted_count += 1
                    print_success("Submitted Results")
                    progress.advance(description=f"{effective_preset} (submitted)")
                    _emit_event(event_sink, "submit_result", scope="single", index=task_index, total=len(combos), status="submitted", preset=effective_preset)
                elif status == "retained":
                    print_warning(f"Queued for retry: {effective_preset} ({message})")
                    progress.advance(description=f"{effective_preset} (queued)")
                    _emit_event(event_sink, "submit_result", scope="single", index=task_index, total=len(combos), status="queued", preset=effective_preset, error=message)
                else:
                    failed_count += 1
                    print(f"Failed to submit {effective_preset}: {message}", file=sys.stderr)
                    progress.advance(description=f"{effective_preset} (failed)")
                    _emit_event(event_sink, "submit_result", scope="single", index=task_index, total=len(combos), status="failed", preset=effective_preset, error=message)
            except Exception as e:
                failed_count += 1
                print(f"Failed to submit {effective_preset}: {e}", file=sys.stderr)
                queued_count = count_pending_entries(args.queue_dir)
                progress.advance(description=f"{effective_preset} (failed)")
                _emit_event(event_sink, "submit_result", scope="single", index=task_index, total=len(combos), status="failed", preset=effective_preset, error=str(e))
            _emit_counters(event_sink, submitted=submitted_count, skipped=skipped_count, queued=queued_count, failed=failed_count)
            _emit_event(event_sink, "task_complete", scope="single", processed=task_index, total=len(combos), preset=effective_preset)

    if not args.no_submit:
        queued_count = _replay_pending_uploads(
            queue_dir=args.queue_dir,
            base_url=base_url,
            api_key=args.api_key,
            retries=max(1, args.retries),
            use_token=use_token,
        )
        _emit_counters(event_sink, submitted=submitted_count, skipped=skipped_count, queued=queued_count, failed=failed_count)
    if show_end_screen and not config._BATCH_ACTIVE:
        _clear_screen()
        elapsed_sec = max(0.0, time.time() - benchmark_start_ts)
        print_end_screen(completed_count, elapsed_sec)
        try:
            if os.name == 'nt' and (bool(getattr(args, 'pause_on_exit', False)) or bool(getattr(sys, 'frozen', False))):
                input("Press Enter to exit...")
        except Exception:
            pass
    _emit_event(
        event_sink,
        "run_complete",
        scope="single",
        completed=completed_count,
        total=len(combos),
        elapsedSeconds=max(0.0, time.perf_counter() - benchmark_start_ts),
    )
    return 0


def build_single_effective_args(
    *,
    base_args: argparse.Namespace,
    encoder: str,
    preset: str,
    crf: int,
) -> argparse.Namespace:
    return argparse.Namespace(
        base_url=base_args.base_url,
        api_key=base_args.api_key,
        codec=encoder,
        presets=preset,
        no_submit=base_args.no_submit,
        crf=crf,
        retries=base_args.retries,
        queue_dir=base_args.queue_dir,
        menu=False,
        batch_size=getattr(base_args, "batch_size", 0),
        use_token=getattr(base_args, "use_token", False),
        pause_on_exit=getattr(base_args, "pause_on_exit", False),
    )


def run_batch_mode(
    *,
    mode: str,
    base_args: argparse.Namespace,
    event_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_event: Optional[Any] = None,
    show_end_screen: bool = True,
) -> int:
    presets_cfg = load_presets_config(PRESETS_CONFIG_PATH)
    encoders = _filter_canonical_encoders(list_all_available_encoders())
    if not encoders:
        print("No available encoders found in this ffmpeg build.", file=sys.stderr)
        return 4
    try:
        suite_clips = _prepare_full_suite()
    except Exception as exc:
        print(f"EncodingDB Test Suite v1 is unavailable: {exc}", file=sys.stderr)
        return 3
    base_tasks = build_batch_tasks_for_mode(
        mode=mode,
        presets_cfg=presets_cfg,
        encoders=encoders,
        default_crf=int(base_args.crf) if isinstance(base_args.crf, int) else 24,
        videotoolbox_target_bitrate_kbps=getattr(base_args, "target_bitrate_kbps", None),
    )
    tasks: List[Dict[str, Any]] = []
    for task in base_tasks:
        for suite_clip in suite_clips:
            expanded = dict(task)
            expanded["suiteClip"] = suite_clip
            tasks.append(expanded)
    config._BATCH_ACTIVE = True
    config._BATCH_START_TS = time.perf_counter()
    config._BATCH_COMPLETED_COUNT = 0
    try:
        rc = run_benchmark_batch(
            hardware=detect_hardware(),
            base_url=base_args.base_url,
            args=argparse.Namespace(
                base_url=base_args.base_url,
                api_key=base_args.api_key,
                no_submit=base_args.no_submit,
                crf=None,
                retries=base_args.retries,
                queue_dir=base_args.queue_dir,
                menu=False,
                batch_size=getattr(base_args, "batch_size", 0),
                use_token=getattr(base_args, "use_token", False),
            ),
            tasks=tasks,
            event_sink=event_sink,
            cancel_event=cancel_event,
        )
        elapsed_sec = max(0.0, time.perf_counter() - config._BATCH_START_TS)
        if show_end_screen:
            _clear_screen()
            print_end_screen(config._BATCH_COMPLETED_COUNT, elapsed_sec)
            try:
                if os.name == "nt" and (bool(getattr(base_args, "pause_on_exit", False)) or bool(getattr(sys, "frozen", False))):
                    input("Press Enter to exit...")
            except Exception:
                pass
        return rc
    finally:
        config._BATCH_ACTIVE = False


def interactive_menu_flow(parser: argparse.ArgumentParser, base_args: argparse.Namespace) -> int:
    try:
        import subprocess
        import shutil
        if os.name != 'nt' and sys.stdin and sys.stdin.isatty() and shutil.which("stty"):
            subprocess.run(["stty", "sane"], check=False)
    except Exception:
        pass
    try:
        _prepare_quick_suite_clip()
    except Exception as exc:
        print(f"EncodingDB Test Suite v1 is unavailable: {exc}", file=sys.stderr)
        return 6
    print_success("EncodingDB Test Suite v1 Verified")
    presets_cfg = load_presets_config(PRESETS_CONFIG_PATH)
    estimates = build_mode_estimates(presets_cfg)
    s_minutes = estimates["smallMinutes"]
    m_hours = estimates["mediumHours"]
    f_hours = estimates["fullHours"]
    print_info("Select an option:")
    menu = [
        "Run Single Benchmark [content-specific quick test, not General PL]",
        f"Run Small Benchmark [~{s_minutes} minutes]",
        f"Run Medium Benchmark [~{m_hours} hours] (Recommended)",
        f"Run Full Benchmark [~{f_hours} hours] (Not recommended for most machines, intended for servers)",
        "Exit",
    ]
    choice = prompt_choice("Menu", menu, default_index=0)
    if choice == 4:
        return 0

    if choice == 0:
        all_encs = list_all_available_encoders()
        if not all_encs:
            print("No available encoders found in this ffmpeg build.", file=sys.stderr)
            return 4

        sw_set = set([enc for _family, lst in SOFTWARE_ENCODERS_ORDER.items() for enc in lst])
        hw_set = set([enc for _family, lst in HARDWARE_ENCODERS.items() for enc, _ in lst])
        sw_encs = [e for e in all_encs if e in sw_set]
        hw_encs = [e for e in all_encs if e in hw_set and is_hardware_encoder_usable(e)]

        print_info("Select an encoder:")
        idx_map: List[str] = []
        option_labels: List[str] = []
        if sw_encs:
            for e in sw_encs:
                idx_map.append(e)
                option_labels.append(f"Software | {get_encoder_friendly_label(e)}")
        if hw_encs:
            for e in hw_encs:
                idx_map.append(e)
                option_labels.append(f"Hardware | {get_encoder_friendly_label(e)}")

        default_idx = 0
        try:
            if "libx264" in idx_map:
                default_idx = idx_map.index("libx264")
        except Exception:
            default_idx = 0
        enc_idx = prompt_choice("Choose encoder", option_labels, default_index=default_idx)
        chosen_encoder = idx_map[enc_idx]

        try:
            default_crf = base_args.crf if isinstance(base_args.crf, int) else 24
        except Exception:
            default_crf = 24
        crf_input = prompt_text("Enter CRF", str(default_crf))
        try:
            chosen_crf = int(crf_input)
        except Exception:
            chosen_crf = default_crf

        encoder_presets = enumerate_supported_presets_for_encoder(chosen_encoder)
        if not encoder_presets:
            encoder_presets = ["medium"]
        mid_index = max(0, (len(encoder_presets) - 1) // 2)
        preset_idx = prompt_choice("Select a preset", encoder_presets, default_index=mid_index)
        chosen_preset = encoder_presets[preset_idx]

        effective_args = argparse.Namespace(
            **vars(build_single_effective_args(
                base_args=base_args,
                encoder=chosen_encoder,
                preset=chosen_preset,
                crf=chosen_crf,
            ))
        )
        return run_with_args(effective_args)

    if choice in (1, 2, 3):
        ok = confirm_benchmark_readiness()
        if not ok:
            print("Aborted by user. Please close other programs and try again.")
            return 0
        _clear_screen()

    mode_map = {1: "small", 2: "medium", 3: "full"}
    mode = mode_map.get(choice)
    if not mode:
        return 1
    return run_batch_mode(mode=mode, base_args=base_args)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Encoding Benchmark Client")
    p.add_argument("--base-url", default=ENV_BACKEND_BASE_URL, help="Backend base URL (default: env BACKEND_BASE_URL or production)")
    p.add_argument("--api-key", default=ENV_API_KEY, help="API key for submission (default: env API_KEY)")
    p.add_argument("--codec", default=ENV_CODEC, help="FFmpeg video encoder or codec family (e.g., libx264, h264, av1). If omitted, will prompt.")
    p.add_argument("--presets", default=ENV_PRESETS, help="Comma-separated list of presets (default: fast,medium,slow)")
    p.add_argument("--no-submit", action="store_true", help="Run tests but do not submit results")
    p.add_argument("--crf", type=int, default=int(ENV_CRF) if ENV_CRF.isdigit() else 24, help="Native quality value for CRF/CQ/ICQ/QP encoders. Defaults to 24; never converted across rate-control families.")
    p.add_argument("--target-bitrate-kbps", type=int, default=None, help="Explicit native bitrate target for bitrate-driven encoders such as VideoToolbox.")
    p.add_argument("--retries", type=int, default=3, help="Submission retry attempts (default: 3)")
    p.add_argument("--queue-dir", default=ENV_QUEUE_DIR, help="Directory for offline retry queue")
    p.add_argument("--menu", action="store_true", help="Force interactive menu even if arguments are provided")
    p.add_argument("--batch-size", type=int, default=0, help="Batch size for parallel VMAF (0=auto: cpu_count or 4)")
    p.add_argument("--use-token", action="store_true", help="Use short-lived submit token (opt-in; or set INGEST_USE_TOKENS=1)")
    p.add_argument("--pause-on-exit", action="store_true", help="On Windows, wait for Enter key after completion to keep the window open")
    p.add_argument("--gui", action="store_true", help="Force Windows GUI mode")
    p.add_argument("--cli", action="store_true", help="Force terminal mode")
    p.add_argument("--v7-suite-clip", default="", help="Run authoritative PLA-77 flow against one canonical EncodingDB Test Suite v1 clip ID without prompts")
    return p


def run_windows_gui_flow(args: argparse.Namespace) -> int:
    try:
        from .windows_gui import launch_windows_gui
    except Exception as e:
        print(f"Unable to start Windows GUI: {e}", file=sys.stderr)
        return 1
    return launch_windows_gui(args)


def main(argv: List[str]) -> int:
    if len(argv) > 1 and argv[1].startswith('--multiprocessing-fork'):
        return 0

    raw_args = list(argv[1:])
    direct_single_run_intent = _has_direct_single_run_intent(raw_args)
    parser = build_arg_parser()
    args = parser.parse_args(raw_args)

    # Validate queue directory path early
    try:
        args.queue_dir = validate_queue_dir(args.queue_dir)
    except QueueDirError as e:
        print(f"Invalid queue directory: {e}", file=sys.stderr)
        return 1

    if args.gui and args.cli:
        print("--gui and --cli cannot be used together.", file=sys.stderr)
        return 1
    if getattr(args, "v7_suite_clip", ""):
        return run_v7_suite_clip_mode(base_args=args)
    if args.menu:
        return interactive_menu_flow(parser, args)
    if args.cli:
        return interactive_menu_flow(parser, args)
    if args.gui:
        if os.name != "nt":
            print("--gui is only supported on Windows.", file=sys.stderr)
            return 1
        return run_windows_gui_flow(args)
    if direct_single_run_intent:
        return run_with_args(args)
    if os.name == "nt" and bool(getattr(sys, "frozen", False)):
        return run_windows_gui_flow(args)
    return interactive_menu_flow(parser, args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
