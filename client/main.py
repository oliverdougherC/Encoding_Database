import argparse
import json
import os
import re
import sys
import tempfile
import time
from typing import Optional, Dict, Any, List, Tuple

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
    compute_metrics_parallel, encode_to_artifact_twopass,
    scale_video, RESOLUTION_DIMENSIONS, TWOPASS_BITRATE_TARGETS,
    EXTENDED_TELEMETRY_KEYS,
    run_single_benchmark, sha256_of_file, verify_sample_video,
    load_presets_config, get_default_sample_path,
)
from .test_videos import (
    CONTENT_CLASSES, CONTENT_CLASS_LABELS, RESOLUTION_ORDER,
    ensure_test_videos, get_video_path, available_content_classes,
)
from .network import submit, fetch_baseline_rows
from .stats import should_skip_submission
from .ui import (
    prompt_yes_no, prompt_choice, prompt_text,
    _clear_screen, confirm_benchmark_readiness,
    print_end_screen, print_benchmark_result,
    BenchmarkProgress, BatchRunDashboard,
    print_info, print_success, print_warning, print_batch_summary,
)


def _resolve_input_for_task(
    t: Dict[str, Any], default_input: str, batch_dir: str,
) -> Tuple[str, str]:
    """Return (effective_input_path, input_hash) for a task, scaling resolution if needed."""
    content_class = t.get('contentClass', 'mixed')
    resolution = t.get('resolution', '1080p')

    video_path = get_video_path(str(content_class), str(resolution))
    if not video_path:
        video_path = get_video_path(str(content_class))
    if not video_path:
        video_path = default_input

    target_dims = RESOLUTION_DIMENSIONS.get(str(resolution))
    if target_dims and str(resolution) != '1080p' and video_path == default_input:
        scaled_name = f"scaled_{resolution}.mp4"
        scaled_path = os.path.join(batch_dir, scaled_name)
        if not os.path.exists(scaled_path):
            print(f"  Scaling source to {resolution}...")
            ok = scale_video(video_path, str(resolution), scaled_path)
            if ok:
                video_path = scaled_path
            else:
                print(f"  Warning: scaling to {resolution} failed, using original", file=sys.stderr)

    return video_path, sha256_of_file(video_path)


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


def run_benchmark_batch(*, hardware: HardwareInfo, base_url: str, args: argparse.Namespace, tasks: List[Dict[str, Any]]) -> int:
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
    client_version = "client/0.1.0"
    workers = resolve_batch_size(getattr(args, 'batch_size', 0))
    chunk_size = max(1, workers)
    total_tasks = len(tasks)
    total_batches = (total_tasks + chunk_size - 1) // chunk_size if total_tasks > 0 else 0
    run_started_at = time.time()
    baseline_rows: List[Dict[str, Any]] = []
    if not getattr(args, 'no_submit', False):
        baseline_rows = fetch_baseline_rows(base_url)

    needed_cc = set()
    needed_res = set()
    for t in tasks:
        cc = t.get('contentClass', 'mixed')
        res = t.get('resolution', '1080p')
        if cc != 'mixed':
            needed_cc.add(cc)
        if res != '1080p':
            needed_res.add(res)
    if needed_cc or needed_res:
        ensure_test_videos(list(needed_cc) if needed_cc else None, list(needed_res) if needed_res else None)

    completed_count_local = 0
    processed_total = 0
    pre_batch_bg_load = measure_background_cpu_load(3.0, 0.5)
    submitted_count = 0
    skipped_count = 0
    queued_count = 0
    failed_count = 0

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
                chunk = tasks[i:i + chunk_size]
                batch_no = (i // chunk_size) + 1
                with tempfile.TemporaryDirectory() as batch_dir:
                    artifacts_info: List[Dict[str, Any]] = []
                    print_info(f"Batch {batch_no}/{total_batches}: {len(chunk)} task(s)")
                    progress.start_batch(batch_no=batch_no, batch_size=len(chunk))
                    progress.set_description(_batch_status(f"Batch {batch_no}/{total_batches} preparing", processed_total + 1))

                    for idx, t in enumerate(chunk, start=1):
                        enc = t['encoder']
                        preset = t['preset']
                        crf = t.get('crf')
                        passes = t.get('passes', 1)
                        content_class = t.get('contentClass', 'mixed')
                        resolution = t.get('resolution', '1080p')
                        bg_load = pre_batch_bg_load
                        name = f"{enc.replace('/', '_')}-{preset}-{str(crf) if crf is not None else 'none'}-{idx}.mp4"
                        global_index = processed_total + idx
                        label_parts = [enc, preset, f"crf={crf}"]
                        if content_class != 'mixed':
                            label_parts.append(f"content={content_class}")
                        if resolution != '1080p':
                            label_parts.append(f"res={resolution}")
                        if passes == 2:
                            label_parts.append("2-pass")
                        progress.set_description(_batch_status("Encoding", global_index, enc, preset) + f" [{', '.join(label_parts)}]")
                        progress.set_current_test(
                            stage="Encoding",
                            encoder=enc,
                            preset=preset,
                            crf=crf,
                            passes=passes,
                            contentClass=content_class,
                            resolution=resolution,
                            isHardware=is_hardware_encoder_name(enc),
                        )
                        effective_input, input_hash = _resolve_input_for_task(t, input_path, batch_dir)

                        if passes == 2:
                            bitrate = TWOPASS_BITRATE_TARGETS.get(str(resolution), '6000k')
                            info = encode_to_artifact_twopass(
                                input_path=effective_input, encoder=enc, preset=preset,
                                bitrate=bitrate, out_dir=batch_dir, artifact_name=name,
                            )
                        else:
                            info = encode_to_artifact(
                                input_path=effective_input,
                                encoder=enc,
                                preset=preset,
                                crf=crf,
                                out_dir=batch_dir,
                                artifact_name=name,
                            )

                        info['backgroundCpuPct'] = float(bg_load)
                        info['task'] = t
                        info['_input_hash'] = input_hash
                        info['_effective_input'] = effective_input
                        final_encoder = str(info.get('encoderUsed') or enc)
                        progress.set_current_test(
                            stage="Encoded",
                            encoder=final_encoder,
                            preset=preset,
                            crf=crf,
                            passes=passes,
                            contentClass=content_class,
                            resolution=resolution,
                            isHardware=is_hardware_encoder_name(final_encoder),
                        )
                        progress.update_machine_metrics(info)
                        artifacts_info.append(info)
                        progress.advance_phase(
                            description=_batch_status("Encoded", processed_total + idx, final_encoder, preset),
                        )

                    for metric_idx, info in enumerate(artifacts_info, start=1):
                        effective_input = info.get('_effective_input', input_path)
                        ap = info['artifactPath']
                        metric_index = processed_total + metric_idx
                        progress.set_current_test(
                            stage="Metrics",
                            encoder=str(info.get('encoderUsed') or info['task']['encoder']),
                            preset=str(info['task']['preset']),
                            crf=info['task'].get('crf'),
                            passes=info['task'].get('passes', 1),
                            contentClass=info['task'].get('contentClass', 'mixed'),
                            resolution=info['task'].get('resolution', '1080p'),
                            isHardware=is_hardware_encoder_name(str(info.get('encoderUsed') or info['task']['encoder'])),
                        )
                        if info.get('error') is None and float(info.get('fps', 0.0)) > 0:
                            progress.set_description(
                                _batch_status(
                                    "Metrics", metric_index,
                                    str(info.get('encoderUsed') or info['task']['encoder']),
                                    str(info['task']['preset']),
                                )
                            )
                            metrics = compute_metrics_parallel(effective_input, [ap], workers, quiet=True)
                            info['_metrics'] = metrics.get(ap, {})
                        else:
                            info['_metrics'] = {}
                        progress.advance_phase(
                            description=_batch_status(
                                "Metrics done",
                                metric_index,
                                str(info.get('encoderUsed') or info['task']['encoder']),
                                str(info['task']['preset']),
                            ),
                        )

                    for info in artifacts_info:
                        t = info['task']
                        input_hash = info.get('_input_hash', default_input_hash)
                        payload: Dict[str, Any] = {
                            'cpuModel': hardware.cpuModel,
                            'gpuModel': hardware.gpuModel or "",
                            'ramGB': hardware.ramGB,
                            'os': hardware.os,
                            'codec': info.get('encoderUsed') or t['encoder'],
                            'preset': t['preset'],
                            'crf': t.get('crf'),
                            'contentClass': t.get('contentClass', 'mixed'),
                            'resolution': t.get('resolution', '1080p'),
                            'passes': t.get('passes', 1),
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

                        note_parts: List[str] = []
                        if info.get('error'):
                            note_parts.append(str(info['error']).strip())
                        if info.get('telemetryNote'):
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
                            contentClass=payload.get('contentClass', 'mixed'),
                            resolution=payload.get('resolution', '1080p'),
                            isHardware=is_hardware_encoder_name(str(payload['codec'])),
                        )
                        if skip:
                            print_warning(f"Skipped submission for {payload['codec']} {payload['preset']} (reason: {reason})")
                            skipped_count += 1
                            if not args.no_submit:
                                try:
                                    fname = os.path.join(args.queue_dir, f"{int(time.time()*1000)}-skipped-{payload['preset']}.json")
                                    payload_to_save = dict(payload)
                                    if reason:
                                        try:
                                            payload_to_save['notes'] = ((payload_to_save.get('notes') or '') + f"; {reason}")[:3500]
                                        except Exception:
                                            pass
                                    with open(fname, 'w', encoding='utf-8') as fh:
                                        json.dump(sanitize_payload_for_server(payload_to_save), fh, separators=(',', ':'))
                                    queued_count += 1
                                except Exception as qe:
                                    print(f"Failed to queue skipped payload: {qe}", file=sys.stderr)
                                    failed_count += 1
                            progress.update_counters(
                                submitted=submitted_count, skipped=skipped_count,
                                queued=queued_count, failed=failed_count,
                            )
                        elif args.no_submit:
                            progress.set_description(_batch_status("Dry-run", next_index, str(payload['codec']), str(payload['preset'])))
                            progress.update_counters(
                                submitted=submitted_count, skipped=skipped_count,
                                queued=queued_count, failed=failed_count,
                            )
                        else:
                            try:
                                submit(
                                    base_url,
                                    sanitize_payload_for_server(payload),
                                    api_key=args.api_key,
                                    retries=max(1, args.retries),
                                    use_token=config._env_flag('INGEST_USE_TOKENS', False) or bool(getattr(args, 'use_token', False)),
                                )
                                submitted_count += 1
                            except Exception as e:
                                print(f"Failed to submit {payload['preset']}: {e}", file=sys.stderr)
                                try:
                                    fname = os.path.join(args.queue_dir, f"{int(time.time()*1000)}-{payload['preset']}.json")
                                    with open(fname, 'w', encoding='utf-8') as fh:
                                        json.dump(sanitize_payload_for_server(payload), fh, separators=(',', ':'))
                                    queued_count += 1
                                except Exception as qe:
                                    print(f"Failed to queue payload: {qe}", file=sys.stderr)
                                    failed_count += 1
                            progress.update_counters(
                                submitted=submitted_count, skipped=skipped_count,
                                queued=queued_count, failed=failed_count,
                            )

                        if float(payload.get('fps', 0.0)) > 0.0 and int(payload.get('fileSizeBytes', 0)) > 0:
                            completed_count_local += 1
                            if config._BATCH_ACTIVE:
                                with config._GLOBAL_STATE_LOCK:
                                    config._BATCH_COMPLETED_COUNT += 1

                        processed_total += 1
                        progress.advance(description=_batch_status("Completed", processed_total, str(payload['codec']), str(payload['preset'])))
    except KeyboardInterrupt:
        print_warning("Batch run interrupted by user.")
        return 130

    elapsed_seconds = max(0.0, time.time() - run_started_at)
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
    return 0


def run_with_args(args: argparse.Namespace) -> int:
    ok, ffmpeg_version = ensure_ffmpeg_and_ffprobe()
    if not ok:
        print("ffmpeg/ffprobe not found in PATH. Please install ffmpeg.", file=sys.stderr)
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
                return 4

    hardware = detect_hardware()
    input_hash = sha256_of_file(input_path)
    client_version = "client/0.1.0"
    combos: List[Tuple[str, Optional[int]]] = []
    try:
        preset_list = [s.strip() for s in args.presets.split(",") if s.strip()]
    except Exception:
        preset_list = ["fast", "medium", "slow"]

    base_url = args.base_url
    user_crf: Optional[int] = args.crf
    if preset_list:
        combos = [(p, user_crf) for p in preset_list]
    benchmark_start_ts = time.time()
    try:
        original_size_bytes = os.path.getsize(input_path)
    except Exception:
        original_size_bytes = 0
    completed_count = 0
    with BenchmarkProgress(len(combos), title="Single Benchmark Progress") as progress:
        for preset, crf_val in combos:
            progress.set_description(f"Running {resolved_encoder} {preset} crf={crf_val}")
            print_info(f"Running Test: {resolved_encoder}, crf={crf_val}, {preset}...")
            payload = run_single_benchmark(hardware, input_path, preset=preset, codec=resolved_encoder, crf=crf_val)
            payload["ffmpegVersion"] = ffmpeg_version
            payload["encoderName"] = payload.get("codec", resolved_encoder)
            payload["clientVersion"] = client_version
            payload["inputHash"] = input_hash
            payload["contentClass"] = getattr(args, 'content_class', 'mixed') or 'mixed'
            payload["resolution"] = getattr(args, 'resolution', '1080p') or '1080p'
            payload["passes"] = getattr(args, 'passes', 1) or 1

            size_val = payload.get("fileSizeBytes")
            try:
                rel_size = (float(size_val) / float(original_size_bytes) * 100.0) if original_size_bytes > 0 else None
            except Exception:
                rel_size = None
            print_benchmark_result(payload, rel_size)

            if float(payload.get("fps", 0.0)) > 0.0 and int(payload.get("fileSizeBytes", 0)) > 0:
                completed_count += 1
                if config._BATCH_ACTIVE:
                    with config._GLOBAL_STATE_LOCK:
                        config._BATCH_COMPLETED_COUNT += 1

            if args.no_submit:
                print_info(f"Dry-run: not submitting preset={preset}")
                progress.advance(description=f"{preset} (dry-run)")
                continue
            try:
                if payload.get("fps", 0.0) <= 0 or payload.get("fileSizeBytes", 0) <= 0:
                    print_warning(
                        f"Skipped submission for preset={preset} due to encode failure "
                        f"(fps={payload.get('fps')}, size={payload.get('fileSizeBytes')})"
                    )
                    progress.advance(description=f"{preset} (failed)")
                    continue
                clean_payload = sanitize_payload_for_server(payload)
                submit(base_url, clean_payload, api_key=args.api_key, retries=max(1, args.retries))
                print_success("Submitted Results")
                progress.advance(description=f"{preset} (submitted)")
            except Exception as e:
                print(f"Failed to submit {preset}: {e}", file=sys.stderr)
                try:
                    fname = os.path.join(args.queue_dir, f"{int(time.time()*1000)}-{preset}.json")
                    with open(fname, "w", encoding="utf-8") as fh:
                        json.dump(sanitize_payload_for_server(payload), fh, separators=(",", ":"))
                    print_info(f"Queued for retry: {fname}")
                except Exception as qe:
                    print(f"Failed to queue payload: {qe}", file=sys.stderr)
                progress.advance(description=f"{preset} (queued)")

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
                pass
    except Exception:
        pass
    if not config._BATCH_ACTIVE:
        _clear_screen()
        elapsed_sec = max(0.0, time.time() - benchmark_start_ts)
        print_end_screen(completed_count, elapsed_sec)
        try:
            if os.name == 'nt' and (bool(getattr(args, 'pause_on_exit', False)) or bool(getattr(sys, 'frozen', False))):
                input("Press Enter to exit...")
        except Exception:
            pass
    return 0


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
    s_minutes = int(presets_cfg.get("smallBenchmark", {}).get("approxMinutes", 5))
    m_hours = int(presets_cfg.get("mediumBenchmark", presets_cfg.get("smallBenchmark", {})).get("approxHours", 3))
    f_hours = presets_cfg.get("fullBenchmark", {}).get("approxHours")
    try:
        f_hours = int(f_hours) if isinstance(f_hours, int) else float(f_hours)
    except Exception:
        f_hours = 3
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

    if choice in (1, 2, 3):
        ok = confirm_benchmark_readiness()
        if not ok:
            print("Aborted by user. Please close other programs and try again.")
            return 0
        _clear_screen()

    config._BATCH_ACTIVE = True
    config._BATCH_START_TS = time.time()
    config._BATCH_COMPLETED_COUNT = 0
    encoders = list_all_available_encoders()
    if not encoders:
        print("No available encoders found in this ffmpeg build.", file=sys.stderr)
        return 4
    if not get_default_sample_path():
        print("Required test video not found (expected sample.mp4 in project root).", file=sys.stderr)
        return 3
    crf_values: List[int] = []
    if choice == 0:
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
        if choice == 1:
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

    bench_key = {1: "smallBenchmark", 2: "mediumBenchmark", 3: "fullBenchmark"}.get(choice, "smallBenchmark")
    bench_cfg = presets_cfg.get(bench_key, {})
    content_classes_list: List[str] = bench_cfg.get("contentClasses", ["mixed"])
    resolutions_list: List[str] = bench_cfg.get("resolutions", ["1080p"])
    passes_list: List[int] = [int(p) for p in bench_cfg.get("passes", [1])]
    if not content_classes_list:
        content_classes_list = ["mixed"]
    if not resolutions_list:
        resolutions_list = ["1080p"]
    if not passes_list:
        passes_list = [1]

    tasks: List[Dict[str, Any]] = []
    for content_class in content_classes_list:
        for resolution in resolutions_list:
            for num_passes in passes_list:
                for crf_val in crf_values:
                    for enc in encoders:
                        presets_for_encoder = enumerate_supported_presets_for_encoder(enc)
                        ordered = sort_presets_by_speed_desc(enc, presets_for_encoder)
                        if choice == 1:
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
                                tasks.append({'encoder': enc, 'preset': preset_label, 'crf': crf_val,
                                              'contentClass': content_class, 'resolution': resolution, 'passes': num_passes})
                        elif choice == 2:
                            if len(ordered) > 0:
                                drop_count = int(round(len(ordered) * 0.2))
                                if drop_count >= len(ordered):
                                    drop_count = len(ordered) - 1
                                keep = ordered[:-drop_count] if drop_count > 0 else ordered
                            else:
                                keep = ordered
                            for preset_label in keep:
                                tasks.append({'encoder': enc, 'preset': preset_label, 'crf': crf_val,
                                              'contentClass': content_class, 'resolution': resolution, 'passes': num_passes})
                        else:
                            for preset_label in ordered:
                                tasks.append({'encoder': enc, 'preset': preset_label, 'crf': crf_val,
                                              'contentClass': content_class, 'resolution': resolution, 'passes': num_passes})

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
            batch_size=getattr(base_args, 'batch_size', 0),
        ),
        tasks=tasks,
    )
    elapsed_sec = max(0.0, time.time() - config._BATCH_START_TS)
    _clear_screen()
    print_end_screen(config._BATCH_COMPLETED_COUNT, elapsed_sec)
    try:
        if os.name == 'nt' and (bool(getattr(base_args, 'pause_on_exit', False)) or bool(getattr(sys, 'frozen', False))):
            input("Press Enter to exit...")
    except Exception:
        pass
    config._BATCH_ACTIVE = False
    return rc


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
    p.add_argument("--content-class", default="mixed", choices=CONTENT_CLASSES, help="Content class for the test video (default: mixed)")
    p.add_argument("--resolution", default="1080p", choices=RESOLUTION_ORDER, help="Target resolution (default: 1080p)")
    p.add_argument("--passes", type=int, default=1, choices=[1, 2], help="Number of encoding passes (default: 1)")
    return p


def main(argv: List[str]) -> int:
    if len(argv) > 1 and argv[1].startswith('--multiprocessing-fork'):
        return 0

    parser = build_arg_parser()
    args = parser.parse_args(argv[1:])

    # Validate queue directory path early
    try:
        args.queue_dir = validate_queue_dir(args.queue_dir)
    except QueueDirError as e:
        print(f"Invalid queue directory: {e}", file=sys.stderr)
        return 1

    return interactive_menu_flow(parser, args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
