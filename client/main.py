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
    get_encoder_friendly_label,
    SOFTWARE_ENCODERS_ORDER, HARDWARE_ENCODERS,
)
from .ffmpeg import (
    run_ffmpeg_test, encode_to_artifact, compute_vmaf_parallel,
    run_single_benchmark, sha256_of_file, verify_sample_video,
    load_presets_config, get_default_sample_path,
)
from .network import submit, fetch_baseline_rows
from .stats import should_skip_submission
from .ui import (
    prompt_yes_no, prompt_choice, prompt_text,
    _clear_screen, confirm_benchmark_readiness,
    print_end_screen,
)


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
    input_hash = sha256_of_file(input_path)
    client_version = "client/0.1.0"
    workers = resolve_batch_size(getattr(args, 'batch_size', 0))
    if not getattr(args, 'no_submit', False):
        _ = fetch_baseline_rows(base_url)

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
            apaths = [x['artifactPath'] for x in artifacts_info]
            vmaf_map = compute_vmaf_parallel(input_path, apaths, workers)
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
                if info.get('error'):
                    payload['notes'] = str(info['error'])[:500]
                skip, reason = should_skip_submission(hardware=hardware, payload=payload, background_cpu_pct=float(info.get('backgroundCpuPct') or 0.0), baseline_rows=baseline_rows)
                if skip:
                    print(f"Skipped submission for {payload['codec']} {payload['preset']} (reason: {reason})")
                    if not args.no_submit:
                        try:
                            fname = os.path.join(args.queue_dir, f"{int(time.time()*1000)}-skipped-{payload['preset']}.json")
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
                if args.no_submit:
                    print(f"Dry-run: not submitting {payload['codec']} {payload['preset']}")
                else:
                    try:
                        submit(base_url, sanitize_payload_for_server(payload), api_key=args.api_key, retries=max(1, args.retries), use_token=config._env_flag('INGEST_USE_TOKENS', False) or bool(getattr(args, 'use_token', False)))
                        print("Submitted Results")
                    except Exception as e:
                        print(f"Failed to submit {payload['preset']}: {e}", file=sys.stderr)
                        try:
                            fname = os.path.join(args.queue_dir, f"{int(time.time()*1000)}-{payload['preset']}.json")
                            with open(fname, 'w', encoding='utf-8') as fh:
                                json.dump(sanitize_payload_for_server(payload), fh, separators=(',', ':'))
                            print(f"Queued for retry: {fname}")
                        except Exception as qe:
                            print(f"Failed to queue payload: {qe}", file=sys.stderr)
                if float(payload.get('fps', 0.0)) > 0.0 and int(payload.get('fileSizeBytes', 0)) > 0:
                    completed_count_local += 1
                    if config._BATCH_ACTIVE:
                        with config._GLOBAL_STATE_LOCK:
                            config._BATCH_COMPLETED_COUNT += 1
                processed_total += 1
                try:
                    overall_pct = (processed_total / max(1, total_tasks)) * 100.0
                except Exception:
                    overall_pct = 100.0
                print(f"Progress: {processed_total}/{total_tasks} ({overall_pct:.0f}%) complete\n")
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
    user_codec = (args.codec or "").strip()
    if user_codec and has_encoder(user_codec):
        resolved_encoder = user_codec
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

    hardware = detect_hardware()
    input_hash = sha256_of_file(input_path)
    client_version = "client/0.1.0"
    combos: List[Tuple[str, Optional[int]]] = []
    try:
        preset_list = [s.strip() for s in args.presets.split(",") if s.strip()]
    except Exception:
        preset_list = ["fast", "medium", "slow"]

    all_payloads: List[Dict[str, Any]] = []
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
    for preset, crf_val in combos:
        print(f"Running Test: {resolved_encoder}, crf={crf_val}, {preset}...")
        payload = run_single_benchmark(hardware, input_path, preset=preset, codec=resolved_encoder, crf=crf_val)
        payload["ffmpegVersion"] = ffmpeg_version
        payload["encoderName"] = payload.get("codec", resolved_encoder)
        payload["clientVersion"] = client_version
        payload["inputHash"] = input_hash
        all_payloads.append(payload)
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
            if config._BATCH_ACTIVE:
                with config._GLOBAL_STATE_LOCK:
                    config._BATCH_COMPLETED_COUNT += 1
        if args.no_submit:
            print(f"Dry-run: not submitting preset={preset}")
            continue
        try:
            if payload.get("fps", 0.0) <= 0 or payload.get("fileSizeBytes", 0) <= 0:
                print(f"Skipped submission for preset={preset} due to encode failure (fps={payload.get('fps')}, size={payload.get('fileSizeBytes')})")
                all_payloads.append({**payload, "localError": True})
                continue
            submit(base_url, payload, api_key=args.api_key, retries=max(1, args.retries))
            print("Submitted Results")
        except Exception as e:
            print(f"Failed to submit {preset}: {e}", file=sys.stderr)
            try:
                fname = os.path.join(args.queue_dir, f"{int(time.time()*1000)}-{preset}.json")
                with open(fname, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, separators=(",", ":"))
                print(f"Queued for retry: {fname}")
            except Exception as qe:
                print(f"Failed to queue payload: {qe}", file=sys.stderr)

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
    presets_cfg = load_presets_config(PRESETS_CONFIG_PATH)
    s_minutes = int(presets_cfg.get("smallBenchmark", {}).get("approxMinutes", 5))
    m_hours = int(presets_cfg.get("mediumBenchmark", presets_cfg.get("smallBenchmark", {})).get("approxHours", 3))
    f_hours = presets_cfg.get("fullBenchmark", {}).get("approxHours")
    try:
        f_hours = int(f_hours) if isinstance(f_hours, int) else float(f_hours)
    except Exception:
        f_hours = 3
    print("Select an option:")
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

    tasks: List[Dict[str, Any]] = []
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
                    tasks.append({'encoder': enc, 'preset': preset_label, 'crf': crf_val})
            elif choice == 2:
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
                for preset_label in ordered:
                    tasks.append({'encoder': enc, 'preset': preset_label, 'crf': crf_val})

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
