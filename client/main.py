import argparse
from functools import wraps
import dataclasses
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import secrets
from contextlib import nullcontext
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
from . import sweep_plan
from .config import (
    ENV_BACKEND_BASE_URL, ENV_API_KEY, ENV_PRESETS, ENV_CRF, ENV_CODEC,
    ENV_QUEUE_DIR, PRESETS_CONFIG_PATH,
    HardwareInfo, sanitize_payload_for_server, validate_queue_dir, QueueDirError,
)
from .hardware import (
    detect_hardware, resolve_batch_size, measure_background_cpu_load, CPU_BLOCKING_WINDOW_SOURCE,
)
from .hardware_monitor import HardwareMonitor, CPU_THREAD_WINDOW_SOURCE
from .encoders import (
    ensure_ffmpeg_and_ffprobe, has_encoder, has_libvmaf,
    is_codec_family_selector, normalize_codec_family, pick_software_encoder_for_family,
    discover_hardware_encoders_for_family, list_all_available_encoders,
    enumerate_supported_presets_for_encoder,
    get_encoder_friendly_label, is_hardware_encoder_name, is_hardware_encoder_usable,
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
from .network import fetch_baseline_rows, check_compatibility
from .campaign import (CampaignJournal, atomic_json, physical_source_id, journal_path,
    PreparationScope, preparation_progress, check_preparation_cancelled,
    MeasurementBudget, MeasurementBudgetExceeded, check_measurement_budget, measurement_timeout, run_measurement_process)
from .identity import selected_device
from .protocol import (
    ArtifactProbe,
    EncodeOutcome,
    EncodeTiming,
    EnvironmentSnapshot,
    ProtocolConfig,
    RecipeSpec,
    StructuralExpectation,
    execute_protocol_campaign,
    generate_campaign_id,
)
from .spool import (
    cleanup_spool,
    count_pending_entries,
    inspect_spool,
    replay_spool,
    spool_payload,
    SpoolCapacityError,
    submit_spooled_path,
)
from .stats import should_skip_submission
from .suite import (
    PreparedSuiteClip,
    REQUIRED_CONTENT_CLASSES,
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
    print_info, print_success, print_warning, print_error, print_batch_summary,
)

CLIENT_VERSION = "client/0.3.1"
# UI/package patches do not change the server's frozen protocol 7.1 contract.
PROTOCOL_MINIMUM_CLIENT_VERSION = "client/0.3.0"
PUBLICATION_CONSENT_VERSION = 1
PUBLICATION_CONSENT_FILENAME = "publication-consent.json"


def _debug_exception_traceback() -> None:
    if config._env_flag("ENCODINGDB_DEBUG_TRACEBACK", False):
        import traceback
        traceback.print_exc(file=sys.stderr)


def _format_byte_count(num_bytes: int) -> str:
    value = float(max(0, num_bytes))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0
    return f"{int(value)} B"


def _publication_consent_path() -> str:
    return os.path.join(config.default_client_state_dir(), PUBLICATION_CONSENT_FILENAME)


def _publication_consent_payload() -> Dict[str, Any]:
    return {
        "version": PUBLICATION_CONSENT_VERSION,
        "acceptedAt": int(time.time()),
        "scope": "benchmark-publication",
    }


def _has_publication_consent() -> bool:
    path = _publication_consent_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    return int(payload.get("version") or 0) == PUBLICATION_CONSENT_VERSION


def _store_publication_consent() -> None:
    path = _publication_consent_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = f"{path}.tmp-{os.getpid()}-{int(time.time() * 1000)}"
    payload = _publication_consent_payload()
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass


def _publication_disclosure_lines(queue_dir: str) -> List[str]:
    return [
        "Publishing benchmark results sends benchmark evidence to the EncodingDB server.",
        "Collected fields include hardware profile (CPU model, GPU model, RAM, OS), workload settings (codec, preset, CRF or bitrate, suite clip, input hash), benchmark results (FPS, output size, VMAF, SSIM, PSNR, runtime), and hardware telemetry samples when available.",
        "Authoritative V7 runs also upload the encoded benchmark artifact so the server can run its own analysis.",
        "Failed uploads stay in the local offline queue until replayed or explicitly cleaned up.",
        f"Local queue directory: {queue_dir}",
        "Not collected: names, email addresses, account identifiers, serial numbers, MAC addresses, general filesystem snapshots, or unrelated personal files.",
    ]


def _ensure_interactive_publication_consent(
    *,
    queue_dir: str,
    prompt_callback: Optional[Callable[[str], bool]] = None,
) -> bool:
    if _has_publication_consent():
        return True
    disclosure = "\n".join(_publication_disclosure_lines(queue_dir))
    if prompt_callback is None:
        print_warning("Publication consent is required before the first interactive submission.")
        for line in _publication_disclosure_lines(queue_dir):
            print_info(line)
        accepted = prompt_yes_no("Allow EncodingDB to publish future benchmark results from this machine?", default_no=True)
    else:
        accepted = bool(prompt_callback(disclosure))
    if not accepted:
        return False
    _store_publication_consent()
    return True


def _apply_submission_policy(args: argparse.Namespace, *, interactive: bool) -> argparse.Namespace:
    effective = argparse.Namespace(**vars(args))
    if bool(getattr(effective, "no_submit", False)):
        return effective
    if interactive:
        if _ensure_interactive_publication_consent(queue_dir=str(getattr(effective, "queue_dir", ENV_QUEUE_DIR) or ENV_QUEUE_DIR)):
            return effective
        effective.no_submit = True
        print_warning("Publication consent was not granted. Continuing in local dry-run mode.")
        return effective
    if bool(getattr(effective, "submit", False)):
        return effective
    effective.no_submit = True
    print_info("Noninteractive CLI defaults to local-only mode. Pass --submit to publish or --no-submit to make dry-run intent explicit.")
    return effective


def _print_queue_status(queue_dir: str) -> None:
    status = inspect_spool(queue_dir)
    print_info(f"Queue directory: {queue_dir}")
    print_info(f"Pending payloads: {status.pending_entries} ({_format_byte_count(status.pending_bytes)})")
    print_info(f"Dead-letter files: {status.dead_letter_files} ({_format_byte_count(status.dead_letter_bytes)})")
    print_info(
        "Managed spool artifacts: "
        + f"{status.managed_artifact_files} ({_format_byte_count(status.managed_artifact_bytes)})"
    )


def _cleanup_queue(queue_dir: str) -> None:
    stats = cleanup_spool(queue_dir)
    print_info(f"Queue directory: {queue_dir}")
    print_info(
        "Removed dead-letter files: "
        + f"{stats.removed_dead_letter_files} ({_format_byte_count(stats.removed_dead_letter_bytes)})"
    )
    print_info(
        "Removed orphaned managed artifacts: "
        + f"{stats.removed_orphaned_managed_artifacts} ({_format_byte_count(stats.removed_orphaned_managed_artifact_bytes)})"
    )
    print_info(f"Pending payloads retained: {stats.pending_entries_retained}")


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


def _preparation_operation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        sink = kwargs.get("event_sink")

        def progress(stage, **details):
            _emit_event(sink, "preparation_progress", scope="preparation", stage=stage, **details)
            if sink is None:
                label = details.get("clipId") or os.path.basename(str(details.get("path") or ""))
                done, total = details.get("completedBytes"), details.get("totalBytes")
                amount = f" ({done}/{total} bytes)" if done is not None and total else ""
                print_info(f"Preparing: {stage} {label}{amount}")

        try:
            with PreparationScope(kwargs.get("cancel_event"), progress).activate():
                return function(*args, **kwargs)
        except KeyboardInterrupt:
            print_info("Preparation or collection interrupted; retained downloads and campaign records can be resumed.")
            _emit_event(sink, "run_interrupted", scope="preparation")
            return 130
    return wrapped


def _preparation_preflight(args, *, base_url=None):
    check_preparation_cancelled()
    if not getattr(args, "no_submit", False):
        preparation_progress("compatibility")
        try:
            check_compatibility(base_url or args.base_url, CLIENT_VERSION)
        except Exception as exc:
            print(f"Compatibility check failed before preparation: {exc}. Use --no-submit for local collection.", file=sys.stderr)
            return 5
    return _preparation_runtime_integrity()


def _preparation_runtime_integrity():
    check_preparation_cancelled()
    if bool(getattr(sys, "frozen", False)) or os.environ.get("ENCODINGDB_RUNTIME_LOCK_PATH"):
        from .runtime_lock import verify_runtime_lock
        preparation_progress("runtime")
        try:
            verify_runtime_lock(ffmpeg_path=config.ffmpeg_exe(), ffprobe_path=config.ffprobe_exe())
        except Exception as exc:
            print(f"Runtime integrity check failed before preparation: {exc}", file=sys.stderr)
            return 2
    return 0


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
                "clipKey": clip.clip_id,
                "workloadId": clip.clip_id,
                "sha256": clip.sha256,
            }
    raise RuntimeError(f"Suite clip {prepared_clip.clip_id} not found in manifest")


def _completed_measurement_groups(campaign_result: Any) -> Dict[str, Dict[str, Any]]:
    """Bind counted timing members only after execute_protocol_campaign returns.

    The server recomputes stability and verifies retained membership; this receipt
    deliberately makes no claim that the group is stable or eligible.
    """
    groups = {}
    for recipe_result in campaign_result.recipe_results:
        attempts = [
            {"repetitionIndex": record.schedule.repetition_index,
             "encodeWallTimeMs": record.timing.elapsed_s * 1000.0}
            for record in recipe_result.runs
            if record.schedule.phase == "measured"
            and record.counted_for_stability and record.timing is not None
        ]
        attempts.sort(key=lambda attempt: attempt["repetitionIndex"])
        # Incomplete/invalid groups remain visible as individual observations.
        # They cannot acquire a group receipt by filling in invented repetitions.
        if not 2 <= len(attempts) <= 4:
            continue
        groups[recipe_result.recipe_id] = {
            "schemaVersion": "encodingdb-measurement-group/v1",
            "campaignId": campaign_result.campaign_id,
            "repetitionGroupId": f"{campaign_result.campaign_id}:{recipe_result.recipe_id}",
            "completed": True,
            "countedAttempts": attempts,
        }
    return groups


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
    measurement_group: Optional[Dict[str, Any]] = None,
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
            "minimumClientVersion": PROTOCOL_MINIMUM_CLIENT_VERSION,
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
            requested_recipe_json=str(info.get("requestedRecipeJson") or "{}"),
            effective_recipe_json=str(info.get("effectiveRecipeJson") or "{}"),
        ),
        "environment": build_environment_bootstrap(
            environment_json=str(execution_identity_payload.get("environmentJson") or "{}"),
            cpu_model=hardware.cpuModel,
        ),
        "physicalSourceId": physical_source_id(),
        "encodeTimerBoundary": "ffmpeg-process-v1",
        "workloadId": prepared_clip.workload_id,
        "expectedMetricModelId": "vmaf-v1-sdr-1080p",
        "inputHash": prepared_clip.input_hash,
        "campaignId": record.schedule.campaign_id,
        "repetitionGroupId": f"{record.schedule.campaign_id}:{recipe_id}",
        "repetitionIndex": record.schedule.repetition_index,
        "encodeWallTimeMs": record.timing.elapsed_s * 1000.0,
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
    if measurement_group is not None:
        run_create["measurementGroup"] = measurement_group
    run_create["payloadHash"] = build_payload_hash(run_create)
    return run_create


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
    check_measurement_budget()
    cmd = [
        config.ffprobe_exe(),
        "-v", "error",
        "-count_frames",
        "-show_entries",
        (
            "stream=index,codec_type,codec_name,codec_tag_string,profile,level,pix_fmt,bits_per_raw_sample,"
            "color_range,color_space,color_transfer,color_primaries,width,height,avg_frame_rate,time_base,"
            "nb_read_frames,nb_frames:format=duration,size,format_name"
        ),
        "-of", "json",
        path,
    ]
    try:
        proc = run_measurement_process(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
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
        keyframe_proc = run_measurement_process(
            [
                config.ffprobe_exe(), "-v", "error", "-select_streams", "v:0",
                "-show_entries", "frame=key_frame", "-of", "csv=p=0", path,
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
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
        duration_s=duration_s if duration_s is not None else _safe_float(output_metrics.get("sourceDurationSeconds")),
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
        avg_frame_rate=avg_frame_rate if avg_frame_rate is not None else _safe_float(output_metrics.get("sourceFps")),
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
        source_duration = source_probe.duration_s
        source_fps = source_probe.avg_frame_rate
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
            time_base=_parse_ratio(requested_output.timeBase),
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
        time.sleep(measurement_timeout(max(0.1, background_cpu_seconds)))
        check_measurement_budget()
    finally:
        environment_metrics = monitor.stop()
    background_cpu_pct = _safe_float(environment_metrics.cpu_util_avg)
    sources = set(filter(None, (environment_metrics.telemetry_sources or "").split(",")))
    if background_cpu_pct is None:
        sources.discard(CPU_THREAD_WINDOW_SOURCE)
        sources.discard(CPU_BLOCKING_WINDOW_SOURCE)
        background_cpu_pct = _safe_float(measure_background_cpu_load(background_cpu_seconds, background_cpu_interval))
        if background_cpu_pct is not None:
            sources.add(CPU_BLOCKING_WINDOW_SOURCE)
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
        selected_accelerator=(selected_device(encoder)["deviceId"]
                              if is_hardware_encoder_name(encoder) else "software"),
        accelerator_is_hardware=is_hardware_encoder_name(encoder),
        gpu_load_trustworthy=(
            not is_hardware_encoder_name(encoder)
            or (selected_device(encoder)["deviceId"] != "unknown"
                and int(environment_metrics.gpu_util_sample_count or 0) > 0
                and _safe_float(environment_metrics.gpu_util_avg) is not None
                and 0 <= environment_metrics.gpu_util_avg <= 100)
        ),
        gpu_sample_count=int(environment_metrics.gpu_util_sample_count or 0),
        telemetry_sources=",".join(sorted(sources)) or None,
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
    max_storage_mb: int = 2048,
) -> Tuple[str, str, int]:
    path, _entry = spool_payload(queue_dir, payload, max_storage_mb=max_storage_mb)
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
        "--submit",
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


def _probe_encoder_usable_with_cancel(encoder: str) -> bool:
    check_preparation_cancelled()
    return is_hardware_encoder_usable(encoder)


def _prepare_sweep_clips(clip_policy: str) -> List[PreparedSuiteClip]:
    """Resolve the frozen suite clips a sweep mode covers, in stable order."""
    manifest = load_default_suite_manifest()
    if clip_policy == sweep_plan.CLIP_POLICY_QUICK:
        return [ensure_suite_clip(get_default_quick_clip(manifest))]
    if clip_policy == sweep_plan.CLIP_POLICY_CLASSES:
        prepared: List[PreparedSuiteClip] = []
        for content_class in REQUIRED_CONTENT_CLASSES:
            clip = next((c for c in manifest.clips if c.canonical_content_class == content_class), None)
            if clip is None:
                raise RuntimeError(f"EncodingDB Test Suite v1 is missing the {content_class} clip")
            prepared.append(ensure_suite_clip(clip))
        return prepared
    return _prepare_full_suite()


def build_sweep_plan(mode: str, presets_cfg: Optional[Dict[str, Any]] = None) -> sweep_plan.SweepPlan:
    """Plan the sweep against currently detected encoders without probing devices."""
    presets_cfg = presets_cfg if presets_cfg is not None else load_presets_config(PRESETS_CONFIG_PATH)
    return sweep_plan.plan_sweep(mode, list_all_available_encoders(), presets_cfg=presets_cfg)


def _matching_saved_sweep_campaign(queue_dir: str, mode: str,
                                   planned_tasks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Manifest of an incomplete campaign whose frozen plan equals the planned tasks.

    A budget-paused or interrupted sweep must continue from its saved plan, never a
    re-planned one, and the journal refuses manifest drift; only an exact task match
    may be resumed under the saved campaign identity.
    """
    for campaign_id, _modified in _incomplete_campaigns(queue_dir):
        try:
            with open(journal_path(queue_dir, campaign_id) / "manifest.json", encoding="utf-8") as handle:
                saved = json.load(handle)
        except Exception:
            continue
        if saved.get("sweepMode") != mode or saved.get("seed") is None:
            continue
        if saved.get("tasks") == planned_tasks:
            return saved
    return None


@_preparation_operation
def run_sweep_mode(
    *,
    mode: str,
    base_args: argparse.Namespace,
    event_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_event: Optional[Any] = None,
    show_end_screen: bool = True,
    interactive: bool = True,
    presets_cfg: Optional[Dict[str, Any]] = None,
) -> int:
    if mode not in sweep_plan.SWEEP_MODES:
        print(f"Unsupported sweep mode: {mode}", file=sys.stderr)
        return 4
    base_args = _apply_submission_policy(base_args, interactive=interactive)
    preflight_rc = _preparation_preflight(base_args)
    if preflight_rc:
        return preflight_rc
    presets_cfg = presets_cfg if presets_cfg is not None else load_presets_config(PRESETS_CONFIG_PATH)
    candidates = list_all_available_encoders()
    if not candidates:
        print("No available encoders found in this ffmpeg build.", file=sys.stderr)
        return 4
    plan = sweep_plan.plan_sweep(
        mode,
        candidates,
        presets_cfg=presets_cfg,
        is_usable=_probe_encoder_usable_with_cancel,
    )
    if plan.is_empty():
        print("No usable encoder on this machine supports a sweep.", file=sys.stderr)
        return 4
    for name, reason in plan.skipped:
        print_info(f"Skipped {sweep_plan_label(name)}: {reason}")
    try:
        suite_clips = _prepare_sweep_clips(plan.clip_policy)
    except Exception as exc:
        print(f"EncodingDB Test Suite v1 is unavailable: {exc}", file=sys.stderr)
        return 3
    tasks: List[Dict[str, Any]] = []
    for step in plan.steps:
        for suite_clip in suite_clips:
            expanded = dict(step)
            expanded["suiteClip"] = suite_clip
            tasks.append(expanded)
    planned_identity = [{"encoder": t["encoder"], "preset": t["preset"], "crf": t.get("crf"),
                         "rateControl": t.get("rateControl"), "clipId": t["suiteClip"].clip_id} for t in tasks]
    saved_manifest = _matching_saved_sweep_campaign(base_args.queue_dir, mode, planned_identity)
    campaign_seed = None
    plan_metadata = plan.manifest_metadata()
    if saved_manifest is not None:
        campaign_seed = saved_manifest["seed"]
        plan_metadata = {key: saved_manifest[key] for key in sweep_plan.MANIFEST_KEYS if key in saved_manifest}
        print_info(f"Continuing the retained {mode} sweep campaign from its saved plan.")
    protocol_config = _build_protocol_config()
    per_recipe_min = protocol_config.warmup_runs + protocol_config.minimum_measured_runs
    per_recipe_max = per_recipe_min + protocol_config.max_adaptive_repeats
    encodes_min = len(tasks) * per_recipe_min
    encodes_max = len(tasks) * per_recipe_max
    if campaign_seed is None:
        env_seed = _safe_int(os.environ.get("ENCODINGDB_PROTOCOL_SEED"))
        campaign_seed = env_seed if env_seed is not None else secrets.randbits(63)
    explicit_duration = bool(getattr(base_args, "explicit_max_duration_minutes", False))
    segment_minutes = float(getattr(base_args, "max_duration_minutes", 60))
    attempts_cap = (int(getattr(base_args, "max_attempts")) if bool(getattr(base_args, "explicit_max_attempts", False))
                    else encodes_max)
    storage_mb = int(getattr(base_args, "max_storage_mb", 2048))
    print_info(
        f"{mode} sweep: {len(plan.steps)} native recipes across {len(plan.encoders)} encoders "
        f"on {len(suite_clips)} frozen clip(s) = {len(tasks)} measured groups; "
        f"{encodes_min}-{encodes_max} encodes at full repetitions."
    )
    print_info(
        f"Authoritative protocol performs every warmup and at least {protocol_config.minimum_measured_runs} "
        "stable measured repetitions per group. Repetitions are never trimmed."
    )
    if explicit_duration:
        print_info(
            f"Explicit measurement allowance honored: {segment_minutes:g} minutes; the run stops at the cap "
            "with the campaign saved, and starting this mode again continues it."
        )
    else:
        print_info(
            f"Checkpoint policy: every {segment_minutes:g}-minute segment saves progress and the run continues "
            "automatically until the plan completes or you cancel; a checkpoint is never a partial completion."
        )
    print_info(f"Active limits: storage budget {storage_mb} MB, attempts cap {attempts_cap}.")
    config._BATCH_ACTIVE = True
    config._BATCH_START_TS = time.perf_counter()
    config._BATCH_COMPLETED_COUNT = 0
    total_submitted = 0
    try:
        segment = 0
        while True:
            segment += 1
            rc = run_benchmark_batch(
                hardware=detect_hardware(),
                base_url=base_args.base_url,
                args=argparse.Namespace(
                    base_url=base_args.base_url,
                    api_key=base_args.api_key,
                    no_submit=base_args.no_submit,
                    submit=getattr(base_args, "submit", False),
                    crf=None,
                    retries=base_args.retries,
                    queue_dir=base_args.queue_dir,
                    menu=False,
                    batch_size=getattr(base_args, "batch_size", 0),
                    use_token=getattr(base_args, "use_token", False),
                    campaign_seed=campaign_seed,
                    max_duration_minutes=segment_minutes,
                    max_attempts=attempts_cap,
                    max_storage_mb=storage_mb,
                ),
                tasks=tasks,
                event_sink=event_sink,
                cancel_event=cancel_event,
                plan_metadata=plan_metadata,
            )
            total_submitted += int(getattr(config, "_BATCH_COMPLETED_COUNT", 0))
            if rc != 11 or explicit_duration or _is_cancelled(cancel_event):
                if rc == 11 and _is_cancelled(cancel_event):
                    rc = 130
                break
            if int(getattr(config, "_BATCH_COMPLETED_COUNT", 0)) <= 0:
                print("Checkpoint reached without any new measurement; stopping to keep retained progress "
                      "safe. Start the same mode to continue.", file=sys.stderr)
                break
            if segment >= 10000:
                print("Safety segment limit reached; campaign remains saved and continues on the next start.",
                      file=sys.stderr)
                break
            config._BATCH_COMPLETED_COUNT = 0
            print_info(f"Time checkpoint reached; continuing the campaign from retained evidence (segment {segment + 1}).")
            _emit_event(event_sink, "campaign_checkpoint_continue", segment=segment + 1)
        elapsed_sec = max(0.0, time.perf_counter() - config._BATCH_START_TS)
        if show_end_screen:
            _clear_screen()
            print_end_screen(total_submitted, elapsed_sec)
            try:
                if os.name == "nt" and (bool(getattr(base_args, "pause_on_exit", False)) or bool(getattr(sys, "frozen", False))):
                    input("Press Enter to exit...")
            except Exception:
                pass
        return rc
    finally:
        config._BATCH_ACTIVE = False


def sweep_plan_label(encoder: str) -> str:
    try:
        return get_encoder_friendly_label(encoder)
    except Exception:
        return encoder


@_preparation_operation
def run_benchmark_batch(
    *,
    hardware: HardwareInfo,
    base_url: str,
    args: argparse.Namespace,
    tasks: List[Dict[str, Any]],
    event_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_event: Optional[Any] = None,
    plan_metadata: Optional[Dict[str, Any]] = None,
) -> int:
    duration_minutes = float(getattr(args, "max_duration_minutes", 60))
    if not math.isfinite(duration_minutes) or not math.isfinite(duration_minutes * 60) or duration_minutes <= 0:
        print("--max-duration-minutes must be positive and finite", file=sys.stderr)
        return 4
    preflight_rc = _preparation_preflight(args, base_url=base_url)
    if preflight_rc:
        return preflight_rc
    ok, ffmpeg_version = ensure_ffmpeg_and_ffprobe()
    if not ok:
        print("ffmpeg/ffprobe not found in PATH. Please install ffmpeg.", file=sys.stderr)
        return 2
    if getattr(args, "local_metrics", False):
        quality_ok, quality_rc = _ensure_local_quality_stack(event_sink=event_sink, scope="batch")
        if not quality_ok:
            return quality_rc
    suite_clip = tasks[0].get("suiteClip") if tasks else None
    if not isinstance(suite_clip, PreparedSuiteClip):
        print("Batch benchmark requires EncodingDB Test Suite v1 clip identities.", file=sys.stderr)
        return 3
    input_path = suite_clip.path
    default_input_hash = suite_clip.input_hash
    protocol_config = _build_protocol_config()
    planned_attempts = len(tasks) * (protocol_config.warmup_runs + protocol_config.minimum_measured_runs + protocol_config.max_adaptive_repeats)
    if planned_attempts > int(getattr(args, "max_attempts", 100)):
        print(f"Campaign can require {planned_attempts} encodes, exceeding --max-attempts. Select fewer recipes or set an explicit budget.", file=sys.stderr)
        return 4
    campaign_seed = getattr(args, "campaign_seed", None)
    if campaign_seed is None:
        campaign_seed = _safe_int(os.environ.get("ENCODINGDB_PROTOCOL_SEED"))
    if campaign_seed is None:
        campaign_seed = secrets.randbits(63)
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
    campaign_id = generate_campaign_id(protocol_config.version, list(recipe_by_id), campaign_seed)
    from .identity import runtime_identity
    manifest = {
        "protocolVersion": protocol_config.version, "seed": campaign_seed,
        "physicalSourceId": physical_source_id(), "hardware": dataclasses.asdict(hardware),
        "runtime": runtime_identity(), "protocolConfig": dataclasses.asdict(protocol_config),
        "selectedDevices": {str(t["encoder"]): selected_device(str(t["encoder"])) for t in tasks},
        "tasks": [{"encoder": t["encoder"], "preset": t["preset"], "crf": t.get("crf"),
                   "rateControl": t.get("rateControl"), "clipId": t["suiteClip"].clip_id} for t in tasks],
    }
    if isinstance(plan_metadata, dict):
        manifest.update(plan_metadata)
    try:
        journal = CampaignJournal(args.queue_dir, campaign_id, manifest, int(getattr(args, "max_storage_mb", 2048)))
        journal.check_budget()
    except Exception as exc:
        print(f"Cannot open campaign journal: {exc}", file=sys.stderr)
        _debug_exception_traceback()
        return 6
    print_info(f"Campaign {campaign_id}: at most {total_tasks} encodes; resume with --resume-campaign {campaign_id}")
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
        maxDurationMinutes=duration_minutes,
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
        with journal.measurement_lock(), nullcontext(str(journal.root)) as batch_dir, \
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
                environment_path = journal.root / f"environment-{schedule.execution_order:06d}.json"
                if environment_path.exists() and list(journal.root.glob(f"{schedule.execution_order:03d}-*.process.json")):
                    retained = json.loads(environment_path.read_text())
                    if retained["schedule"] != schedule.to_dict():
                        raise ValueError("Interrupted environment checkpoint schedule changed")
                    return EnvironmentSnapshot(**retained["snapshot"])
                task = _task_from_recipe(recipe)
                progress.set_description(
                    _batch_status(f"{schedule.phase.title()} env", schedule.execution_order, task["encoder"], task["preset"])
                )
                snapshot = _capture_protocol_environment_snapshot(
                    hardware=hardware,
                    encoder=task["encoder"],
                )
                atomic_json(environment_path, {"schedule": schedule.to_dict(), "snapshot": snapshot.to_dict()})
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
                journal.check_budget()
                atomic_json(journal.root / "in-flight.json", schedule.to_dict())
                info = encode_to_artifact(
                    input_path=effective_input,
                    encoder=encoder,
                    preset=preset,
                    crf=crf,
                    rate_control=rate_control,
                    out_dir=batch_dir,
                    artifact_name=artifact_name,
                    host_gpu_vendors=list(getattr(hardware, 'gpuVendors', []) or []),
                    cancel_event=cancel_event,
                    checkpoint_path=os.path.join(batch_dir, artifact_name + '.process.json'),
                    max_output_bytes=journal.check_budget(),
                )
                start_ns = info.get('encodeStartMonotonicNs')
                end_ns = info.get('encodeEndMonotonicNs')
                if start_ns is None or end_ns is None:
                    info["error"] = info.get("error") or "Encode returned no corrected process interval"
                    return EncodeOutcome(timing=None, probe=ArtifactProbe(decodable=False, decode_error=info["error"]),
                                         metadata={"info": info, "inputHash": input_hash, "suiteClip": prepared_clip})
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

            budget = MeasurementBudget(duration_minutes, cancel_event=cancel_event)
            with budget.activate():
                campaign_result = execute_protocol_campaign(
                    recipes=recipe_specs,
                    config=protocol_config,
                    encode_runner=_encode_protocol_run,
                    environment_sampler=_sample_environment,
                    seed=campaign_seed,
                    record_sink=journal.save,
                    resumed_records=journal.records,
                )
            attempt_evidence_path = _persist_protocol_attempt_evidence(args.queue_dir, campaign_result)
            _emit_event(
                event_sink,
                "protocol_attempt_evidence_retained",
                campaignId=campaign_result.campaign_id,
                seed=campaign_result.seed,
                path=attempt_evidence_path,
            )

            measurement_groups = _completed_measurement_groups(campaign_result)
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
                if not getattr(args, "local_metrics", False):
                    record.metadata["metrics"] = {}
                    continue
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

                prepared_clip = task.get("suiteClip")
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

                advisory_skip, reason = should_skip_submission(
                    hardware=hardware,
                    payload=payload,
                    background_cpu_pct=float(getattr(record.environment_snapshot, 'background_cpu_pct', 0.0) or 0.0),
                    baseline_rows=baseline_rows,
                )
                if advisory_skip:
                    # Legacy aggregate heuristics are advisory only in the v7
                    # evidence epoch. Canonical validity is decided by the
                    # protocol record and authoritative server analysis.
                    payload['legacySubmissionAdvisory'] = reason
                    print_info(f"Legacy submission advisory for {payload['codec']} {payload['preset']}: {reason}")
                skip = False
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
                else:
                    if payload.get('scoreEligibilityNote') and not payload.get('scoreFormulaVersion'):
                        print_warning(str(payload['scoreEligibilityNote']))
                    if record.overall_validity.state == "suspect":
                        print_warning(
                            f"Retaining suspect protocol evidence for {payload['codec']} {payload['preset']}: "
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
                            measurement_group=measurement_groups.get(recipe.recipe_id),
                        )
                        authoritative_submission = build_artifact_submission_payload(
                            artifact_path=str(info["artifactPath"]),
                            media_container=artifact_probe.get("containerFormat"),
                            run_create=authoritative_run_create,
                        )
                        local_path = journal.root / f"submission-{record.schedule.execution_order:06d}.json"
                        if local_path.exists():
                            authoritative_submission = json.loads(local_path.read_text())
                        else:
                            atomic_json(local_path, authoritative_submission)
                        if args.no_submit:
                            _emit_event(event_sink, "submit_result", status="locally_complete", campaignId=campaign_id)
                            completed_count_local += 1
                            continue
                        status, error_text, queued_count = _submit_payload_with_spool(
                            queue_dir=args.queue_dir,
                            base_url=base_url,
                            payload=authoritative_submission,
                            max_storage_mb=getattr(args, "max_storage_mb", 2048),
                            api_key=args.api_key,
                            retries=max(1, args.retries),
                            use_token=use_token,
                        )
                        if status == "submitted":
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
                    except SpoolCapacityError:
                        raise
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
    except MeasurementBudgetExceeded as exc:
        status = {"status": "budget_exhausted", "campaignId": campaign_id,
                  "maxDurationMinutes": exc.budget.minutes,
                  "elapsedSeconds": max(0.0, exc.budget.clock() - exc.budget.started),
                  "stoppedAt": time.time(), "phase": "measurement"}
        flight = journal.root / "in-flight.json"
        try:
            if flight.exists():
                status["lastStartedAttempt"] = json.loads(flight.read_text())
            atomic_json(journal.root / f"budget-exhausted-{time.time_ns()}.json", status)
        except OSError as error:
            print(f"Time budget exhausted; unable to persist pause status: {error}", file=sys.stderr)
            _debug_exception_traceback()
            return 6
        print_warning(f"{exc}. Saved attempts remain available; resume with --resume-campaign {campaign_id}.")
        _emit_event(event_sink, "run_budget_exhausted", scope="batch", **status)
        return 11
    except (OSError, ValueError, TimeoutError) as exc:
        print(f"Campaign retained for resume: {exc}", file=sys.stderr)
        _debug_exception_traceback()
        _emit_event(event_sink, "run_error", scope="batch", code=6, message=str(exc))
        return 6
    except KeyboardInterrupt:
        print_warning("Batch run interrupted by user.")
        _emit_event(event_sink, "run_interrupted", scope="batch", processed=processed_total, total=total_tasks)
        return 130

    atomic_json(journal.root / "campaign-complete.json", {"campaignId": campaign_id, "skipped": skipped_count, "failed": failed_count})
    elapsed_seconds = max(0.0, time.perf_counter() - run_started_at)
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
    if failed_count or skipped_count:
        return 1
    if not getattr(args, "no_submit", False) and queued_count:
        return 10
    if not getattr(args, "no_submit", False) and submitted_count <= 0:
        return 1
    return 0


@_preparation_operation
def run_v7_suite_clip_mode(
    *,
    base_args: argparse.Namespace,
    event_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_event: Optional[Any] = None,
    interactive: bool = False,
) -> int:
    base_args = _apply_submission_policy(base_args, interactive=interactive)
    preflight_rc = _preparation_preflight(base_args)
    if preflight_rc:
        return preflight_rc
    clip_id = str(getattr(base_args, "v7_suite_clip", "") or "").strip()
    try:
        suite_clips = (_prepare_full_suite() if getattr(base_args, "campaign", "quick") == "full"
                       else [_prepare_named_suite_clip(clip_id) if clip_id else _prepare_quick_suite_clip()])
    except Exception as exc:
        print(f"Unable to prepare suite clip {clip_id}: {exc}", file=sys.stderr)
        return 3

    requested_codec = str(getattr(base_args, "codec", "") or "").strip()
    if not requested_codec:
        print("--codec is required for noninteractive v7 suite clip mode.", file=sys.stderr)
        return 4
    if has_encoder(requested_codec):
        resolved_encoder = requested_codec
    elif is_codec_family_selector(requested_codec):
        family = normalize_codec_family(requested_codec)
        resolved_encoder = pick_software_encoder_for_family(family) if family else None
    else:
        resolved_encoder = None
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
    target_bitrate_kbps = getattr(base_args, "target_bitrate_kbps", None)
    if target_bitrate_kbps is not None or resolved_encoder.lower().endswith("_videotoolbox"):
        if target_bitrate_kbps is None or target_bitrate_kbps <= 0:
            print("VideoToolbox v7 runs require --target-bitrate-kbps.", file=sys.stderr)
            return 4
        task_rate_control = {"mode": "vbr", "targetBitrateKbps": int(target_bitrate_kbps)}
    else:
        task_rate_control = None
    tasks = [
        {
            "encoder": resolved_encoder,
            "preset": preset,
            "crf": crf_value,
            "rateControl": task_rate_control,
            "suiteClip": suite_clip,
        }
        for suite_clip in suite_clips for preset in preset_list
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
    for field in ("campaign_seed", "max_attempts", "max_storage_mb", "max_duration_minutes", "local_metrics"):
        if hasattr(base_args, field):
            setattr(strict_args, field, getattr(base_args, field))
    return run_benchmark_batch(
        hardware=detect_hardware(),
        base_url=base_args.base_url,
        args=strict_args,
        tasks=tasks,
        event_sink=event_sink,
        cancel_event=cancel_event,
    )


@_preparation_operation
def _resume_campaign(args, *, event_sink=None, cancel_event=None, interactive=False):
    args = _apply_submission_policy(args, interactive=interactive)
    preflight_rc = _preparation_preflight(args)
    if preflight_rc:
        return preflight_rc
    try:
        root = journal_path(args.queue_dir, args.resume_campaign)
        saved = json.loads((root / "manifest.json").read_text())
        args.campaign_seed = saved["seed"]
        # Reopening the journal requires the exact saved manifest; sweep campaigns persist
        # their planner metadata, so resume must pass every plan key through unchanged.
        plan_metadata = {key: saved[key] for key in sweep_plan.MANIFEST_KEYS if key in saved} or None
        tasks = [{"encoder": task["encoder"], "preset": task["preset"], "crf": task["crf"],
                  "rateControl": task["rateControl"], "suiteClip": _prepare_named_suite_clip(task["clipId"])}
                 for task in saved["tasks"]]
        check_preparation_cancelled()
        return run_benchmark_batch(hardware=detect_hardware(), base_url=args.base_url, args=args, tasks=tasks,
                                   event_sink=event_sink, cancel_event=cancel_event,
                                   plan_metadata=plan_metadata)
    except Exception as exc:
        print(f"Cannot resume campaign: {exc}", file=sys.stderr)
        _debug_exception_traceback()
        return 6


def run_with_args(args, *, event_sink=None, cancel_event=None, show_end_screen=True, interactive=True):
    if getattr(args, "legacy_diagnostic", False):
        args.no_submit = True
        return run_legacy_diagnostic(args, event_sink=event_sink, cancel_event=cancel_event,
                                     show_end_screen=show_end_screen, interactive=False)
    return run_v7_suite_clip_mode(base_args=args, event_sink=event_sink,
                                  cancel_event=cancel_event, interactive=interactive)


def run_legacy_diagnostic(
    args: argparse.Namespace,
    *,
    event_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_event: Optional[Any] = None,
    show_end_screen: bool = True,
    interactive: bool = True,
) -> int:
    args = _apply_submission_policy(args, interactive=interactive)
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
                    max_storage_mb=getattr(args, "max_storage_mb", 2048),
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
            except SpoolCapacityError as exc:
                print_warning(f"Upload deferred: {exc}")
                return 10
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
    elapsed_sec = max(0.0, time.perf_counter() - benchmark_start_ts)
    if show_end_screen and not config._BATCH_ACTIVE:
        _clear_screen()
        if args.no_submit:
            print_info(f"Benchmark complete. Completed {completed_count} encodes in {elapsed_sec:.1f}s. Dry-run: no data submitted.")
        else:
            print_end_screen(submitted_count, elapsed_sec)
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
        elapsedSeconds=elapsed_sec,
    )
    return 0


def build_single_effective_args(
    *,
    base_args: argparse.Namespace,
    encoder: str,
    preset: str,
    crf: Optional[int],
    target_bitrate_kbps: Optional[int] = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        base_url=base_args.base_url,
        api_key=base_args.api_key,
        codec=encoder,
        presets=preset,
        no_submit=base_args.no_submit,
        submit=getattr(base_args, "submit", False),
        crf=crf,
        retries=base_args.retries,
        queue_dir=base_args.queue_dir,
        menu=False,
        batch_size=getattr(base_args, "batch_size", 0),
        use_token=getattr(base_args, "use_token", False),
        target_bitrate_kbps=(
            target_bitrate_kbps if target_bitrate_kbps is not None
            else getattr(base_args, "target_bitrate_kbps", None)
        ),
        max_duration_minutes=getattr(base_args, "max_duration_minutes", 60),
        max_attempts=getattr(base_args, "max_attempts", 100),
        max_storage_mb=getattr(base_args, "max_storage_mb", 2048),
        pause_on_exit=getattr(base_args, "pause_on_exit", False),
    )


def _incomplete_campaigns(queue_dir: str) -> List[Tuple[str, float]]:
    """Retained campaign journals that never reached their completion marker."""
    try:
        root = os.path.join(queue_dir, "campaigns")
        if not os.path.isdir(root):
            return []
        found: List[Tuple[str, float]] = []
        for name in os.listdir(root):
            entry = os.path.join(root, name)
            if not os.path.isdir(entry):
                continue
            try:
                journal = journal_path(queue_dir, name)
            except ValueError:
                continue
            if (journal / "campaign-complete.json").exists():
                continue
            found.append((name, os.path.getmtime(entry)))
        found.sort(key=lambda item: item[1], reverse=True)
        return found[:5]
    except Exception:
        return []


def _sweep_clip_count(plan: sweep_plan.SweepPlan) -> int:
    return 1 if plan.clip_policy == sweep_plan.CLIP_POLICY_QUICK else len(REQUIRED_CONTENT_CLASSES)


def _guided_mode_label(mode: str, plan: sweep_plan.SweepPlan,
                       per_recipe_min: int, per_recipe_max: int) -> str:
    """Finite work counts only; absolute wall-clock claims need measurement evidence."""
    clips = {
        sweep_plan.CLIP_POLICY_QUICK: "the quick clip",
        sweep_plan.CLIP_POLICY_CLASSES: "one clip per content class (all 7)",
        sweep_plan.CLIP_POLICY_SUITE: "all seven frozen clips",
    }.get(plan.clip_policy, plan.clip_policy)
    if plan.is_empty():
        return f"no supported encoder available for this sweep on this machine ({clips})"
    clip_count = _sweep_clip_count(plan)
    groups = plan.recipe_count * clip_count
    return (
        f"{plan.recipe_count} native recipes x {clip_count} clip(s) = {groups} groups; "
        f"{groups * per_recipe_min}-{groups * per_recipe_max} encodes at full repetitions"
    )


def _advanced_single_flow(base_args: argparse.Namespace, encoders: List[str]) -> int:
    """Manual one-recipe configuration; the advanced path, not the default flow."""
    base_args = _apply_submission_policy(base_args, interactive=True)
    preflight_rc = _preparation_preflight(base_args)
    if preflight_rc:
        return preflight_rc
    sw_encs = [e for e in encoders if not is_hardware_encoder_name(e)]
    hw_encs = [e for e in encoders if is_hardware_encoder_name(e) and is_hardware_encoder_usable(e)]
    idx_map: List[str] = sw_encs + hw_encs
    if not idx_map:
        print("No usable encoders found in this ffmpeg build.", file=sys.stderr)
        return 4
    option_labels = (
        [f"Software | {get_encoder_friendly_label(e)}" for e in sw_encs]
        + [f"Hardware | {get_encoder_friendly_label(e)}" for e in hw_encs]
    )
    default_idx = idx_map.index("libx264") if "libx264" in idx_map else 0
    enc_idx = prompt_choice("Choose encoder", option_labels, default_index=default_idx)
    chosen_encoder = idx_map[enc_idx]

    encoder_presets = enumerate_supported_presets_for_encoder(chosen_encoder)
    if not encoder_presets:
        encoder_presets = ["medium"]
    mid_index = max(0, (len(encoder_presets) - 1) // 2)
    preset_idx = prompt_choice("Select a preset", encoder_presets, default_index=mid_index)
    chosen_preset = encoder_presets[preset_idx]

    target_bitrate_kbps: Optional[int] = None
    chosen_crf: Optional[int]
    if sweep_plan.is_bitrate_driven(chosen_encoder):
        try:
            default_bitrate = int(getattr(base_args, "target_bitrate_kbps", None) or 6000)
        except Exception:
            default_bitrate = 6000
        bitrate_input = prompt_text(
            "Target bitrate in kbps (bitrate-driven encoder; quality values do not apply)",
            str(default_bitrate),
        )
        try:
            target_bitrate_kbps = max(1, int(bitrate_input))
        except Exception:
            target_bitrate_kbps = default_bitrate
        chosen_crf = None
    else:
        try:
            default_crf = base_args.crf if isinstance(base_args.crf, int) else 24
        except Exception:
            default_crf = 24
        crf_input = prompt_text(f"Enter {sweep_plan.native_quality_label(chosen_encoder)}", str(default_crf))
        try:
            chosen_crf = int(crf_input)
        except Exception:
            chosen_crf = default_crf
    return run_with_args(build_single_effective_args(
        base_args=base_args,
        encoder=chosen_encoder,
        preset=chosen_preset,
        crf=chosen_crf,
        target_bitrate_kbps=target_bitrate_kbps,
    ))


@_preparation_operation
def interactive_menu_flow(parser: argparse.ArgumentParser, base_args: argparse.Namespace) -> int:
    try:
        import subprocess
        import shutil
        if os.name != 'nt' and sys.stdin and sys.stdin.isatty() and shutil.which("stty"):
            subprocess.run(["stty", "sane"], check=False)
    except Exception:
        pass
    ffmpeg_ok, _ffmpeg_version = ensure_ffmpeg_and_ffprobe()
    if not ffmpeg_ok:
        print_error("ffmpeg/ffprobe were not found in PATH. Install ffmpeg (https://ffmpeg.org/download.html), then start EncodingDB again.")
        return 2
    hardware = detect_hardware()
    encoders = list_all_available_encoders()
    if not encoders:
        print_error("No supported encoders were found in this ffmpeg build. Install a full ffmpeg build with libx264.")
        return 4
    software_encoders = [e for e in encoders if not is_hardware_encoder_name(e)]
    hardware_encoders = [e for e in encoders if is_hardware_encoder_name(e)]
    print_success("EncodingDB contributor setup looks good.")
    print_info(
        f"Machine: {hardware.cpuModel} | {hardware.gpuModel or 'no discrete GPU detected'} "
        f"| {hardware.ramGB} GB RAM | {hardware.os}"
    )
    print_info(f"Software encoders ready: {', '.join(software_encoders) if software_encoders else 'none'}")
    if hardware_encoders:
        print_info(f"Hardware encoders detected (real usability is probed before measuring): {', '.join(hardware_encoders)}")
    else:
        print_info("Hardware encoders detected: none; software encoders will be swept.")
    presets_cfg = load_presets_config(PRESETS_CONFIG_PATH)
    previews = {mode: sweep_plan.plan_sweep(mode, encoders, presets_cfg=presets_cfg) for mode in sweep_plan.SWEEP_MODES}
    option_labels: List[str] = []
    actions: List[Tuple[str, Optional[str]]] = []
    for campaign_id, mtime in _incomplete_campaigns(base_args.queue_dir):
        saved_on = time.strftime("%Y-%m-%d", time.localtime(mtime))
        option_labels.append(f"Continue the saved campaign {campaign_id} (saved {saved_on})")
        actions.append(("resume", campaign_id))
    protocol_config = _build_protocol_config()
    per_recipe_min = protocol_config.warmup_runs + protocol_config.minimum_measured_runs
    per_recipe_max = per_recipe_min + protocol_config.max_adaptive_repeats
    mode_notes = {
        "small": "Recommended",
        "medium": "preset band plus native quality points",
        "large": "every supported speed preset",
        "full": "complete supported grid; server-class",
    }
    for mode in sweep_plan.SWEEP_MODES:
        option_labels.append(
            f"Run the {mode.capitalize()} sweep [{mode_notes[mode]}: "
            f"{_guided_mode_label(mode, previews[mode], per_recipe_min, per_recipe_max)}]"
        )
        actions.append(("sweep", mode))
    option_labels.append("Advanced: configure one recipe yourself (encoder, preset, native quality or bitrate)")
    actions.append(("single", None))
    option_labels.append("Exit")
    actions.append(("exit", None))
    default_index = next((index for index, (action, _payload) in enumerate(actions) if action == "sweep"), 0)
    choice = prompt_choice("What would you like to do?", option_labels, default_index=default_index)
    action, payload = actions[choice]
    if action == "exit":
        return 0
    if action == "resume":
        base_args.resume_campaign = payload
        return _resume_campaign(base_args, interactive=True)
    if action == "sweep":
        if not confirm_benchmark_readiness():
            print("Aborted by user. Please close other programs and try again.")
            return 0
        _clear_screen()
        return run_sweep_mode(mode=str(payload), base_args=base_args)
    return _advanced_single_flow(base_args, encoders)


class _ExplicitBudgetAction(argparse.Action):
    """Parse a budget value and remember that the operator set it explicitly.

    Guided sweeps treat these budgets differently: the attempt cap sizes to the plan,
    and the duration allowance becomes a checkpoint segment that auto-continues - unless
    the operator named a value, which is then honored strictly.
    """

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)
        setattr(namespace, f"{self.dest}_explicit", True)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Encoding Benchmark Client")
    p.add_argument("--base-url", default=ENV_BACKEND_BASE_URL, help="Backend base URL (default: env BACKEND_BASE_URL or production)")
    p.add_argument("--api-key", default=ENV_API_KEY, help="API key for submission (default: env API_KEY)")
    p.add_argument("--codec", default=ENV_CODEC, help="FFmpeg video encoder or codec family (e.g., libx264, h264, av1). If omitted, will prompt.")
    p.add_argument("--presets", default=ENV_PRESETS, help="Comma-separated list of presets (default: fast,medium,slow)")
    p.add_argument("--no-submit", action="store_true", help="Run tests but do not submit results")
    p.add_argument("--submit", action="store_true", help="Publish benchmark results in noninteractive CLI mode")
    p.add_argument("--crf", type=int, default=int(ENV_CRF) if ENV_CRF.isdigit() else 24, help="Native quality value for CRF/CQ/ICQ/QP encoders. Defaults to 24; never converted across rate-control families.")
    p.add_argument("--target-bitrate-kbps", type=int, default=None, help="Explicit native bitrate target for bitrate-driven encoders such as VideoToolbox.")
    p.add_argument("--retries", type=int, default=3, help="Submission retry attempts (default: 3)")
    p.add_argument("--queue-dir", default=ENV_QUEUE_DIR, help="Directory for offline retry queue")
    p.add_argument("--queue-status", action="store_true", help="Print offline queue counts and sizes, then exit")
    p.add_argument("--queue-cleanup", action="store_true", help="Delete dead-letter files and orphaned managed artifacts, then exit")
    p.add_argument("--menu", action="store_true", help="Force interactive menu even if arguments are provided")
    p.add_argument("--batch-size", type=int, default=0, help="Batch size for parallel VMAF (0=auto: cpu_count or 4)")
    p.add_argument("--use-token", action="store_true", help="Use short-lived submit token (opt-in; or set INGEST_USE_TOKENS=1)")
    p.add_argument("--pause-on-exit", action="store_true", help="On Windows, wait for Enter key after completion to keep the window open")
    p.add_argument("--gui", action="store_true", help="Force Windows GUI mode")
    p.add_argument("--cli", action="store_true", help="Force terminal mode")
    p.add_argument("--v7-suite-clip", default="", help="Run authoritative PLA-77 flow against one canonical EncodingDB Test Suite v1 clip ID without prompts")
    p.add_argument("--campaign", choices=("quick", "full"), default="quick", help="One clip (quick) or all seven clips (full), with the selected recipe")
    p.add_argument("--resume-campaign", default="", help="Resume a retained campaign ID, preserving completed attempts")
    p.add_argument("--upload-only", action="store_true", help="Retry due queued uploads without encoding")
    p.add_argument("--local-metrics", action="store_true", help="Run optional local quality diagnostics after all measurements")
    p.add_argument("--max-attempts", type=int, default=100, action=_ExplicitBudgetAction,
                   help="Maximum planned warmup/measured encodes (default 100; guided sweeps size the cap "
                        "to the plan unless set)")
    p.add_argument("--max-duration-minutes", type=float, default=60, action=_ExplicitBudgetAction,
                   help="Measurement allowance per invocation in minutes; acquisition and uploads are "
                        "separate (default 60; guided sweeps continue across checkpoints unless set)")
    p.add_argument("--max-storage-mb", type=int, default=2048, help="Maximum retained queue and campaign storage in MiB")
    p.add_argument("--legacy-diagnostic", action="store_true", help="Noncanonical local-only legacy diagnostic; never publishes")
    p.set_defaults(explicit_max_attempts=False, explicit_max_duration_minutes=False)
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
    # Budget flags carry explicit_max_* markers (see _ExplicitBudgetAction); guided sweeps
    # size the attempt cap to the plan and chain checkpoint segments unless the operator set them.

    # Validate queue directory path early
    try:
        args.queue_dir = validate_queue_dir(args.queue_dir)
    except QueueDirError as e:
        print(f"Invalid queue directory: {e}", file=sys.stderr)
        return 1

    if args.gui and args.cli:
        print("--gui and --cli cannot be used together.", file=sys.stderr)
        return 1
    if args.submit and args.no_submit:
        print("--submit and --no-submit cannot be used together.", file=sys.stderr)
        return 1
    if args.queue_cleanup:
        try:
            _cleanup_queue(args.queue_dir)
        except SpoolCapacityError as exc:
            print_warning(f"Queue cleanup deferred: {exc}")
            return 10
        if not args.queue_status:
            return 0
    if args.queue_status:
        _print_queue_status(args.queue_dir)
        return 0
    if not math.isfinite(args.max_duration_minutes) or not math.isfinite(args.max_duration_minutes * 60) or args.max_duration_minutes <= 0:
        parser.error("--max-duration-minutes must be positive and finite")
    if args.max_attempts < 1 or args.max_storage_mb < 1:
        parser.error("Campaign budgets must be positive")
    if args.resume_campaign and args.submit and not args.no_submit and not args.upload_only:
        # An explicit --upload-only is a never-encode contract; the completion-marker
        # inference may only upgrade an implicit publish request, never downgrade the
        # flag the operator actually typed (a resume without the marker must fail
        # visibly, not silently re-encode throwaway attempts).
        try:
            args.upload_only = (journal_path(args.queue_dir, args.resume_campaign) / "campaign-complete.json").exists()
        except ValueError as exc:
            parser.error(str(exc))
    if args.upload_only:
        if args.no_submit:
            parser.error("--upload-only cannot be combined with --no-submit")
        try:
            check_compatibility(args.base_url, CLIENT_VERSION)
            campaign_failures = False
            publication_deferred = False
            if args.resume_campaign:
                root = journal_path(args.queue_dir, args.resume_campaign)
                marker = root / "campaign-complete.json"
                if marker.exists():
                    result = json.loads(marker.read_text())
                    campaign_failures = bool(result.get("skipped") or result.get("failed"))
                for path in sorted(root.glob("submission-*.json")):
                    try:
                        _spooled_path, entry = spool_payload(args.queue_dir, json.loads(path.read_text()),
                                                            max_storage_mb=args.max_storage_mb)
                    except SpoolCapacityError as exc:
                        print_warning(f"Upload deferred: {exc}")
                        publication_deferred = True
                        break
                    if entry.get("terminal") is True:
                        campaign_failures = True
                        print_warning(f"Retained upload is terminal ({entry.get('lastError') or 'terminal_upload'}); see {_spooled_path}.")
            stats = replay_spool(args.queue_dir, base_url=args.base_url, api_key=args.api_key,
                                 retries=1, use_token=False)
            return 1 if campaign_failures or stats.dead_lettered or stats.corrupt else (10 if publication_deferred or count_pending_entries(args.queue_dir) else 0)
        except Exception as exc:
            print(f"Upload deferred: {exc}", file=sys.stderr)
            return 10
    if args.resume_campaign:
        return _resume_campaign(args)
    if getattr(args, "v7_suite_clip", ""):
        return run_v7_suite_clip_mode(base_args=args, interactive=False)
    if args.menu:
        return interactive_menu_flow(parser, args)
    if args.cli and not direct_single_run_intent and "--campaign" not in raw_args:
        return interactive_menu_flow(parser, args)
    if args.gui:
        if os.name != "nt":
            print("--gui is only supported on Windows.", file=sys.stderr)
            return 1
        return run_windows_gui_flow(args)
    if direct_single_run_intent or "--campaign" in raw_args:
        return run_with_args(args, interactive=False)
    if os.name == "nt" and bool(getattr(sys, "frozen", False)):
        return run_windows_gui_flow(args)
    return interactive_menu_flow(parser, args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
