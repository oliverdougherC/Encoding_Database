import argparse
import json
import os
import re
import sys
import tempfile
import time
from typing import Optional, Dict, Any, List, Tuple, Callable

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
    run_single_benchmark, sha256_of_file, verify_sample_video,
    load_presets_config, get_default_sample_path,
)
from .network import fetch_baseline_rows
from .spool import count_pending_entries, replay_spool, spool_payload, submit_spooled_path
from .stats import should_skip_submission
from .ui import (
    prompt_yes_no, prompt_choice, prompt_text,
    _clear_screen, confirm_benchmark_readiness,
    print_end_screen, print_benchmark_result,
    BenchmarkProgress, BatchRunDashboard,
    print_info, print_success, print_warning, print_batch_summary,
)

CLIENT_VERSION = "client/0.1.1"


def _resolve_input_for_task(
    default_input: str,
    default_input_hash: str,
) -> Tuple[str, str]:
    """Return (effective_input_path, input_hash) for a task."""
    return default_input, default_input_hash


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
    event = {"type": event_type, "ts": time.time()}
    event.update(payload)
    try:
        event_sink(event)
    except Exception:
        pass


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


def build_batch_tasks_for_mode(*, mode: str, presets_cfg: Dict[str, Any], encoders: List[str], default_crf: int = 24) -> List[Dict[str, Any]]:
    mode_key = (mode or "").strip().lower()
    if mode_key not in ("small", "medium", "full"):
        raise ValueError(f"Unsupported batch mode: {mode}")
    crf_values = _resolve_crf_values_for_mode(mode_key, presets_cfg, default_crf)
    tasks: List[Dict[str, Any]] = []
    for crf_val in crf_values:
        for enc in encoders:
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
                    tasks.append({"encoder": enc, "preset": preset_label, "crf": crf_val})
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
                    tasks.append({"encoder": enc, "preset": preset_label, "crf": crf_val})
                continue
            for preset_label in ordered:
                tasks.append({"encoder": enc, "preset": preset_label, "crf": crf_val})
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
    default_input_hash = sha256_of_file(input_path)
    client_version = CLIENT_VERSION
    workers = resolve_batch_size(getattr(args, 'batch_size', 0))
    chunk_size = max(1, workers)
    total_tasks = len(tasks)
    total_batches = (total_tasks + chunk_size - 1) // chunk_size if total_tasks > 0 else 0
    run_started_at = time.time()
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
    pre_batch_bg_load = measure_background_cpu_load(3.0, 0.5)
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
        with BatchRunDashboard(total_tasks=total_tasks, total_batches=total_batches, hardware=hardware) as progress:
            for i in range(0, len(tasks), chunk_size):
                if _is_cancelled(cancel_event):
                    raise KeyboardInterrupt
                chunk = tasks[i:i + chunk_size]
                batch_no = (i // chunk_size) + 1
                with tempfile.TemporaryDirectory() as batch_dir:
                    artifacts_info: List[Dict[str, Any]] = []
                    print_info(f"Batch {batch_no}/{total_batches}: {len(chunk)} task(s)")
                    progress.start_batch(batch_no=batch_no, batch_size=len(chunk))
                    progress.set_description(_batch_status(f"Batch {batch_no}/{total_batches} preparing", processed_total + 1))
                    _emit_event(
                        event_sink,
                        "batch_start",
                        batchNo=batch_no,
                        totalBatches=total_batches,
                        batchSize=len(chunk),
                        processedTotal=processed_total,
                    )

                    for idx, t in enumerate(chunk, start=1):
                        if _is_cancelled(cancel_event):
                            raise KeyboardInterrupt
                        enc = t['encoder']
                        preset = t['preset']
                        crf = t.get('crf')
                        bg_load = pre_batch_bg_load
                        name = f"{enc.replace('/', '_')}-{preset}-{str(crf) if crf is not None else 'none'}-{idx}.mp4"
                        global_index = processed_total + idx
                        progress.set_description(_batch_status("Encoding", global_index, enc, preset) + f" [{enc}, {preset}, crf={crf}]")
                        progress.set_current_test(
                            stage="Encoding",
                            encoder=enc,
                            preset=preset,
                            crf=crf,
                            passes=1,
                            isHardware=is_hardware_encoder_name(enc),
                        )
                        _emit_event(
                            event_sink,
                            "encode_start",
                            index=global_index,
                            total=total_tasks,
                            encoder=enc,
                            preset=preset,
                            crf=crf,
                            batchNo=batch_no,
                        )
                        effective_input, input_hash = _resolve_input_for_task(input_path, default_input_hash)

                        info = encode_to_artifact(
                            input_path=effective_input,
                            encoder=enc,
                            preset=preset,
                            crf=crf,
                            out_dir=batch_dir,
                            artifact_name=name,
                            host_gpu_vendors=list(getattr(hardware, 'gpuVendors', []) or []),
                        )

                        info['backgroundCpuPct'] = float(bg_load)
                        info['task'] = t
                        info['_input_hash'] = input_hash
                        info['_effective_input'] = effective_input
                        final_encoder = str(info.get('encoderUsed') or enc)
                        final_preset = str(info.get('presetUsed') or preset)
                        progress.set_current_test(
                            stage="Encoded",
                            encoder=final_encoder,
                            preset=final_preset,
                            crf=crf,
                            passes=1,
                            isHardware=is_hardware_encoder_name(final_encoder),
                        )
                        progress.update_machine_metrics(info)
                        artifacts_info.append(info)
                        _emit_event(
                            event_sink,
                            "encode_done",
                            index=global_index,
                            total=total_tasks,
                            encoder=final_encoder,
                            preset=final_preset,
                            crf=crf,
                            fps=float(info.get("fps") or 0.0),
                            fileSizeBytes=int(info.get("fileSizeBytes") or 0),
                            runMs=int(info.get("elapsedMs") or 0),
                            error=info.get("error"),
                            telemetry={
                                key: info[key]
                                for key in list(EXTENDED_TELEMETRY_KEYS) + list(RAW_TELEMETRY_KEYS) + [
                                    'gpuUtilAvg', 'gpuPowerAvgW', 'gpuMemPeakMB',
                                    'cpuUtilAvg', 'cpuUtilMax', 'peakMemoryMB', 'thermalThrottle',
                                ]
                                if key in info
                            },
                            batchNo=batch_no,
                        )
                        progress.advance_phase(
                            description=_batch_status("Encoded", processed_total + idx, final_encoder, final_preset),
                        )

                    for metric_idx, info in enumerate(artifacts_info, start=1):
                        if _is_cancelled(cancel_event):
                            raise KeyboardInterrupt
                        effective_input = info.get('_effective_input', input_path)
                        ap = info['artifactPath']
                        metric_index = processed_total + metric_idx
                        progress.set_current_test(
                            stage="Metrics",
                            encoder=str(info.get('encoderUsed') or info['task']['encoder']),
                            preset=str(info.get('presetUsed') or info['task']['preset']),
                            crf=info['task'].get('crf'),
                            passes=1,
                            isHardware=is_hardware_encoder_name(str(info.get('encoderUsed') or info['task']['encoder'])),
                        )
                        if info.get('error') is None and float(info.get('fps', 0.0)) > 0:
                            progress.set_description(
                                _batch_status(
                                    "Metrics", metric_index,
                                    str(info.get('encoderUsed') or info['task']['encoder']),
                                    str(info.get('presetUsed') or info['task']['preset']),
                                )
                            )
                            _emit_event(
                                event_sink,
                                "metrics_start",
                                index=metric_index,
                                total=total_tasks,
                                encoder=str(info.get('encoderUsed') or info['task']['encoder']),
                                preset=str(info.get('presetUsed') or info['task']['preset']),
                                crf=info['task'].get('crf'),
                            )
                            metrics = compute_metrics_parallel(effective_input, [ap], workers, quiet=True)
                            info['_metrics'] = metrics.get(ap, {})
                        else:
                            info['_metrics'] = {}
                        _emit_event(
                            event_sink,
                            "metrics_done",
                            index=metric_index,
                            total=total_tasks,
                            encoder=str(info.get('encoderUsed') or info['task']['encoder']),
                            preset=str(info.get('presetUsed') or info['task']['preset']),
                            crf=info['task'].get('crf'),
                            metrics=info.get("_metrics", {}),
                        )
                        progress.advance_phase(
                            description=_batch_status(
                                "Metrics done",
                                metric_index,
                                str(info.get('encoderUsed') or info['task']['encoder']),
                                str(info.get('presetUsed') or info['task']['preset']),
                            ),
                        )

                    for info in artifacts_info:
                        if _is_cancelled(cancel_event):
                            raise KeyboardInterrupt
                        t = info['task']
                        input_hash = info.get('_input_hash', default_input_hash)
                        payload: Dict[str, Any] = {
                            'cpuModel': hardware.cpuModel,
                            'gpuModel': hardware.gpuModel or "",
                            'ramGB': hardware.ramGB,
                            'os': hardware.os,
                            'codec': info.get('encoderUsed') or t['encoder'],
                            'preset': info.get('presetUsed') or t['preset'],
                            'crf': t.get('crf'),
                            'passes': 1,
                            'fps': float(info.get('fps') or 0.0),
                            'fileSizeBytes': int(info.get('fileSizeBytes') or 0),
                            'runMs': int(info.get('elapsedMs') or 0),
                            'ffmpegVersion': ffmpeg_version,
                            'encoderName': info.get('encoderUsed') or t['encoder'],
                            'clientVersion': client_version,
                            'inputHash': input_hash,
                        }
                        artifact_metrics = info.get('_metrics', {})
                        vmaf_score = artifact_metrics.get('vmaf')
                        if vmaf_score is not None:
                            payload['vmaf'] = float(vmaf_score)
                        ssim_score = artifact_metrics.get('ssim')
                        if ssim_score is not None:
                            payload['ssim'] = float(ssim_score)
                        psnr_score = artifact_metrics.get('psnr')
                        if psnr_score is not None:
                            payload['psnr'] = float(psnr_score)

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
                            payload['notes'] = "; ".join(note_parts)[:3500]

                        skip, reason = should_skip_submission(
                            hardware=hardware,
                            payload=payload,
                            background_cpu_pct=float(info.get('backgroundCpuPct') or 0.0),
                            baseline_rows=baseline_rows,
                        )
                        next_index = processed_total + 1
                        progress.set_description(_batch_status("Submitting", next_index, str(payload['codec']), str(payload['preset'])))
                        progress.set_current_test(
                            stage="Submitting",
                            encoder=str(payload['codec']),
                            preset=str(payload['preset']),
                            crf=payload.get('crf'),
                            passes=payload.get('passes', 1),
                            isHardware=is_hardware_encoder_name(str(payload['codec'])),
                        )
                        _emit_event(
                            event_sink,
                            "submit_start",
                            index=next_index,
                            total=total_tasks,
                            codec=str(payload["codec"]),
                            preset=str(payload["preset"]),
                            crf=payload.get("crf"),
                            dryRun=bool(args.no_submit),
                        )
                        if skip:
                            print_warning(f"Skipped submission for {payload['codec']} {payload['preset']} (reason: {reason})")
                            skipped_count += 1
                            progress.update_counters(
                                submitted=submitted_count, skipped=skipped_count,
                                queued=queued_count, failed=failed_count,
                            )
                            _emit_event(event_sink, "submit_result", index=next_index, total=total_tasks, status="skipped", reason=reason)
                        elif args.no_submit:
                            progress.set_description(_batch_status("Dry-run", next_index, str(payload['codec']), str(payload['preset'])))
                            progress.update_counters(
                                submitted=submitted_count, skipped=skipped_count,
                                queued=queued_count, failed=failed_count,
                            )
                            _emit_event(event_sink, "submit_result", index=next_index, total=total_tasks, status="dry_run")
                        else:
                            status = "failed"
                            error_text = ""
                            try:
                                status, error_text, queued_count = _submit_payload_with_spool(
                                    queue_dir=args.queue_dir,
                                    base_url=base_url,
                                    payload=sanitize_payload_for_server(payload),
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
                                    _emit_event(event_sink, "submit_result", index=next_index, total=total_tasks, status="submitted")
                                elif status == "retained":
                                    print_warning(f"Queued payload for retry: {payload['preset']} ({error_text})")
                                    _emit_event(event_sink, "submit_result", index=next_index, total=total_tasks, status="queued", error=error_text)
                                else:
                                    failed_count += 1
                                    print(f"Failed to submit {payload['preset']}: {error_text}", file=sys.stderr)
                                    _emit_event(event_sink, "submit_result", index=next_index, total=total_tasks, status="failed", error=error_text)
                            except Exception as e:
                                failed_count += 1
                                error_text = str(e)
                                print(f"Failed to submit {payload['preset']}: {error_text}", file=sys.stderr)
                                queued_count = count_pending_entries(args.queue_dir)
                                _emit_event(event_sink, "submit_result", index=next_index, total=total_tasks, status="failed", error=error_text)
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

    elapsed_seconds = max(0.0, time.time() - run_started_at)
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
    return 0


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
    if not has_libvmaf():
        print(
            "Your ffmpeg build does not include libvmaf. Install ffmpeg with libvmaf.",
            file=sys.stderr,
        )
        _emit_event(event_sink, "run_error", scope="single", code=5, message="libvmaf not available")
        return 5

    input_path = get_default_sample_path()
    if not input_path:
        print("Required test video not found (expected sample.mp4 in project root).", file=sys.stderr)
        _emit_event(event_sink, "run_error", scope="single", code=3, message="sample.mp4 not found")
        return 3
    ok_sample, msg = verify_sample_video(input_path)
    if not ok_sample:
        print(
            f"Test video integrity check failed: {msg}.\n"
            "Please use the original, unmodified sample.mp4 included with the client.",
            file=sys.stderr,
        )
        _emit_event(event_sink, "run_error", scope="single", code=6, message=f"sample verification failed: {msg}")
        return 6

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
                f"Selected hardware encoder '{resolved_encoder}' may not be usable on this machine. "
                "Attempting it anyway; software fallback will be used if needed."
            )
        else:
            fam = _infer_encoder_family(resolved_encoder)
            sw = pick_software_encoder_for_family(fam) if fam else None
            if sw and has_encoder(sw):
                print(
                    f"Selected hardware encoder '{resolved_encoder}' is not usable on this machine. "
                    f"Using software encoder '{sw}' instead."
                )
                resolved_encoder = sw
            else:
                print(
                    f"Selected hardware encoder '{resolved_encoder}' is not usable on this machine, "
                    "and no software fallback was found.",
                    file=sys.stderr,
                )
                _emit_event(event_sink, "run_error", scope="single", code=4, message="hardware encoder unusable and no fallback")
                return 4

    hardware = detect_hardware()
    input_hash = sha256_of_file(input_path)
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
    benchmark_start_ts = time.time()
    try:
        original_size_bytes = os.path.getsize(input_path)
    except Exception:
        original_size_bytes = 0
    completed_count = 0
    with BenchmarkProgress(len(combos), title="Single Benchmark Progress") as progress:
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
            payload = run_single_benchmark(hardware, input_path, preset=preset, codec=resolved_encoder, crf=crf_val)
            payload["ffmpegVersion"] = ffmpeg_version
            payload["encoderName"] = payload.get("codec", resolved_encoder)
            payload["clientVersion"] = client_version
            payload["inputHash"] = input_hash
            payload["passes"] = 1
            effective_preset = str(payload.get("preset") or preset)

            size_val = payload.get("fileSizeBytes")
            try:
                rel_size = (float(size_val) / float(original_size_bytes) * 100.0) if original_size_bytes > 0 else None
            except Exception:
                rel_size = None
            print_benchmark_result(payload, rel_size)
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
        elapsedSeconds=max(0.0, time.time() - benchmark_start_ts),
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
    encoders = list_all_available_encoders()
    if not encoders:
        print("No available encoders found in this ffmpeg build.", file=sys.stderr)
        return 4
    if not get_default_sample_path():
        print("Required test video not found (expected sample.mp4 in project root).", file=sys.stderr)
        return 3
    tasks = build_batch_tasks_for_mode(
        mode=mode,
        presets_cfg=presets_cfg,
        encoders=encoders,
        default_crf=int(base_args.crf) if isinstance(base_args.crf, int) else 24,
    )
    config._BATCH_ACTIVE = True
    config._BATCH_START_TS = time.time()
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
        elapsed_sec = max(0.0, time.time() - config._BATCH_START_TS)
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
    print_success("Test Video Checksum Verified")
    presets_cfg = load_presets_config(PRESETS_CONFIG_PATH)
    estimates = build_mode_estimates(presets_cfg)
    s_minutes = estimates["smallMinutes"]
    m_hours = estimates["mediumHours"]
    f_hours = estimates["fullHours"]
    print_info("Select an option:")
    menu = [
        "Run Single Benchmark",
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
        hw_encs = [e for e in all_encs if e in hw_set]

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
    p.add_argument("--crf", type=int, default=int(ENV_CRF) if ENV_CRF.isdigit() else 24, help="Constant Rate Factor (encoder-dependent). Defaults to 24.")
    p.add_argument("--retries", type=int, default=3, help="Submission retry attempts (default: 3)")
    p.add_argument("--queue-dir", default=ENV_QUEUE_DIR, help="Directory for offline retry queue")
    p.add_argument("--menu", action="store_true", help="Force interactive menu even if arguments are provided")
    p.add_argument("--batch-size", type=int, default=0, help="Batch size for parallel VMAF (0=auto: cpu_count or 4)")
    p.add_argument("--use-token", action="store_true", help="Use short-lived submit token (opt-in; or set INGEST_USE_TOKENS=1)")
    p.add_argument("--pause-on-exit", action="store_true", help="On Windows, wait for Enter key after completion to keep the window open")
    p.add_argument("--gui", action="store_true", help="Force Windows GUI mode")
    p.add_argument("--cli", action="store_true", help="Force terminal mode")
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
