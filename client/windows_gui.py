import argparse
import os
import queue
import threading
import time
import traceback
from typing import Any, Dict, Optional

from . import main as client_main
from . import sweep_plan
from .encoders import (
    enumerate_supported_presets_for_encoder,
    get_encoder_friendly_label,
    list_all_available_encoders,
    is_codec_family_selector,
    normalize_codec_family,
    pick_software_encoder_for_family,
)

# Shared sweep modes plus the advanced manual recipe; both surfaces (TUI and
# this GUI) drive the same client.sweep_plan planner.
GUI_MODE_CHOICES: tuple[str, ...] = ("Small", "Medium", "Large", "Full", "Single (advanced)")
GUI_MODE_BY_LABEL: Dict[str, Optional[str]] = {
    "Small": "small",
    "Medium": "medium",
    "Large": "large",
    "Full": "full",
    "Single (advanced)": None,
}
# Replay checks its time budget between entries; an in-flight request can take
# longer. Keep the window visible until both owned workers have actually exited.
GUI_CLOSE_GRACE_SECONDS = 70.0


def plan_summary_text(mode: str, encoders: list[str], presets_cfg: dict[str, Any]) -> str:
    """One-line honest preview of a sweep plan: finite work counts, no wall-clock claims."""
    plan = sweep_plan.plan_sweep(mode, encoders, presets_cfg=presets_cfg)
    if plan.is_empty():
        return "No supported encoder is available for this sweep."
    clips = {
        sweep_plan.CLIP_POLICY_QUICK: "the quick clip",
        sweep_plan.CLIP_POLICY_CLASSES: "one clip per content class (all 7)",
        sweep_plan.CLIP_POLICY_SUITE: "all seven frozen clips",
    }.get(plan.clip_policy, plan.clip_policy)
    protocol_config = client_main._build_protocol_config()
    per_recipe_min = protocol_config.warmup_runs + protocol_config.minimum_measured_runs
    per_recipe_max = per_recipe_min + protocol_config.max_adaptive_repeats
    groups = plan.recipe_count * client_main._sweep_clip_count(plan)
    return (
        f"{mode.capitalize()} sweep plan: {plan.recipe_count} native recipes across "
        f"{len(plan.encoders)} encoders on {clips} = {groups} groups; "
        f"{groups * per_recipe_min}-{groups * per_recipe_max} encodes at full "
        "repetitions; checkpoint segments auto-continue until the plan completes."
    )


def initial_gui_settings(base_args: argparse.Namespace, encoders: list[str]) -> tuple[str, str, int]:
    """Honor configured native choices; an omitted encoder defaults to a software encoder.

    A hardware encoder name being present in the ffmpeg build does not mean the machine
    has a usable GPU, so the advanced-single default starts on the always-usable software
    path; hardware names stay selectable and sweeps probe them at run time.
    """
    requested = str(getattr(base_args, "codec", "") or "").strip()
    if requested:
        encoder = requested
        if encoder not in encoders and is_codec_family_selector(requested):
            family = normalize_codec_family(requested)
            encoder = pick_software_encoder_for_family(family) if family else ""
    else:
        encoder = pick_software_encoder_for_family("h264")
        if encoder not in encoders:
            encoder = encoders[0] if encoders else ""
    if not encoder or encoder not in encoders:
        raise ValueError(f"Requested encoder '{requested or '(none available)'}' is not available.")
    presets = enumerate_supported_presets_for_encoder(encoder)
    requested_presets = [value.strip() for value in str(getattr(base_args, "presets", "") or "").split(",") if value.strip()]
    preset = requested_presets[0] if requested_presets else (presets[len(presets) // 2] if presets else "")
    if not preset or preset not in presets:
        raise ValueError(f"Requested preset '{preset}' is not supported by {encoder}.")
    quality = getattr(base_args, "crf", None)
    return encoder, preset, int(24 if quality is None else quality)


def initial_window_geometry(work_area: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Leave room for native window chrome inside the actual work area."""
    left, top, right, bottom = work_area
    return min(1100, max(1, right - left - 32)), min(760, max(1, bottom - top - 64)), left + 8, top + 8


def desktop_work_area(root: Any) -> tuple[int, int, int, int]:
    import ctypes
    from ctypes import wintypes
    rect = wintypes.RECT()
    if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
        return rect.left, rect.top, rect.right, rect.bottom
    return 0, 0, root.winfo_screenwidth(), max(1, root.winfo_screenheight() - 60)


def launch_windows_gui(base_args: argparse.Namespace) -> int:
    if os.name != "nt":
        print("Windows GUI mode is only supported on Windows.")
        return 1

    try:
        import tkinter as tk
        from tkinter import messagebox
        from tkinter import scrolledtext
        from tkinter import ttk
    except Exception as e:
        print(f"Tkinter is unavailable ({e}); falling back to CLI mode.")
        parser = client_main.build_arg_parser()
        return client_main.interactive_menu_flow(parser, base_args)

    runtime_rc = client_main._preparation_runtime_integrity()
    if runtime_rc:
        messagebox.showerror("Runtime integrity", "Bundled runtime verification failed. See the diagnostic output.")
        return runtime_rc
    encoders = list_all_available_encoders()
    presets_cfg = client_main.load_presets_config(client_main.PRESETS_CONFIG_PATH)
    try:
        initial_encoder, initial_preset, initial_quality = initial_gui_settings(base_args, encoders)
    except ValueError as exc:
        messagebox.showerror("Unsupported configuration", str(exc))
        return 4

    class WindowsClientApp:
        def __init__(self) -> None:
            self.root = tk.Tk()
            self.root.title("EncodingDB Windows Client")
            width, height, left, top = initial_window_geometry(desktop_work_area(self.root))
            self.root.geometry(f"{width}x{height}{left:+d}{top:+d}")
            self.root.minsize(min(980, width), min(640, height))

            self.base_args = argparse.Namespace(**vars(base_args))
            self.event_queue: queue.Queue = queue.Queue()
            self.worker_thread: Optional[threading.Thread] = None
            self.upload_thread: Optional[threading.Thread] = None
            self.cancel_event = threading.Event()
            self.running = False
            self._browse_shown = False
            self._close_deadline = 0.0
            # Causal message from the most recent run_error/unhandled failure in this
            # run; the done handler must not replace it with a bare exit code.
            self.last_failure: Optional[str] = None

            self.mode_var = tk.StringVar(value="Small")
            self.no_submit_var = tk.BooleanVar(value=bool(getattr(base_args, "no_submit", False)))
            self.base_url_var = tk.StringVar(value=str(getattr(base_args, "base_url", "")))
            self.retries_var = tk.IntVar(value=max(1, int(getattr(base_args, "retries", 3))))
            self.batch_size_var = tk.IntVar(value=max(0, int(getattr(base_args, "batch_size", 0))))
            self.bitrate_var = tk.StringVar(value=str(getattr(base_args, "target_bitrate_kbps", "") or ""))
            self.crf_var = tk.IntVar(value=initial_quality)

            self.selected_encoder_var = tk.StringVar(value="")
            self.selected_preset_var = tk.StringVar(value="")

            self.stage_var = tk.StringVar(value="Idle")
            self.current_var = tk.StringVar(value="-")
            self.summary_var = tk.StringVar(value="Ready")
            self.telemetry_var = tk.StringVar(value="-")
            self.counter_var = tk.StringVar(value="ok=0 skip=0 queue=0 fail=0")

            self.overall_total = 1
            self.overall_done = 0
            self.batch_total = 1
            self.batch_done = 0

            self.encoder_values = []
            self.preset_values = []

            self._build_ui(ttk, tk, scrolledtext)
            self._refresh_encoders()
            self._update_single_fields_state()
            self._refresh_controls()
            self._poll_events()
            self.root.protocol("WM_DELETE_WINDOW", self._on_close)
            self.root.bind("<Alt-b>", self._start_shortcut)
            self.root.bind("<Alt-s>", self._stop_shortcut)

        def _build_ui(self, ttk: Any, tk: Any, scrolledtext: Any) -> None:
            outer = ttk.Frame(self.root, padding=12)
            outer.pack(fill="both", expand=True)

            config_frame = ttk.LabelFrame(outer, text="Run Configuration", padding=10)
            config_frame.pack(fill="x", expand=False)

            row1 = ttk.Frame(config_frame)
            row1.pack(fill="x", pady=(0, 8))
            ttk.Label(row1, text="Mode").pack(side="left")
            self.mode_combo = ttk.Combobox(
                row1,
                textvariable=self.mode_var,
                values=list(GUI_MODE_CHOICES),
                state="readonly",
                width=18,
            )
            self.mode_combo.pack(side="left", padx=(8, 16))
            self.mode_combo.bind("<<ComboboxSelected>>", lambda _evt: self._update_single_fields_state())

            ttk.Checkbutton(row1, text="No submit (local dry run only)", variable=self.no_submit_var).pack(side="left", padx=(0, 12))
            ttk.Label(row1, text="Retries").pack(side="left")
            self.retries_spin = ttk.Spinbox(row1, from_=1, to=10, textvariable=self.retries_var, width=6)
            self.retries_spin.pack(side="left", padx=(6, 12))
            ttk.Label(row1, text="Batch size").pack(side="left")
            self.batch_spin = ttk.Spinbox(row1, from_=0, to=64, textvariable=self.batch_size_var, width=6)
            self.batch_spin.pack(side="left", padx=(6, 0))

            row2 = ttk.Frame(config_frame)
            row2.pack(fill="x", pady=(0, 8))
            ttk.Label(row2, text="Base URL").pack(side="left")
            self.base_url_entry = ttk.Entry(row2, textvariable=self.base_url_var)
            self.base_url_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))

            row3 = ttk.Frame(config_frame)
            row3.pack(fill="x")
            ttk.Label(row3, text="Encoder").pack(side="left")
            self.encoder_combo = ttk.Combobox(row3, textvariable=self.selected_encoder_var, state="readonly", width=34)
            self.encoder_combo.pack(side="left", padx=(8, 16))
            self.encoder_combo.bind("<<ComboboxSelected>>", lambda _evt: self._refresh_presets())

            ttk.Label(row3, text="Preset").pack(side="left")
            self.preset_combo = ttk.Combobox(row3, textvariable=self.selected_preset_var, state="readonly", width=18)
            self.preset_combo.pack(side="left", padx=(8, 16))

            ttk.Label(row3, text="Native quality value").pack(side="left")
            self.crf_spin = ttk.Spinbox(row3, from_=0, to=40, textvariable=self.crf_var, width=6)
            self.crf_spin.pack(side="left", padx=(8, 0))

            ttk.Label(row3, text="Bitrate kbps (hardware)").pack(side="left", padx=(12, 0))
            self.bitrate_entry = ttk.Entry(row3, textvariable=self.bitrate_var, width=8)
            self.bitrate_entry.pack(side="left", padx=(6, 0))

            buttons = ttk.Frame(config_frame)
            buttons.pack(fill="x", pady=(10, 0))
            self.start_btn = ttk.Button(buttons, text="Start benchmark (Alt+B)", underline=6, command=self._start_run)
            self.start_btn.pack(side="left")
            self.stop_btn = ttk.Button(buttons, text="Stop (Alt+S)", underline=0, command=self._stop_run, state="disabled")
            self.stop_btn.pack(side="left", padx=(8, 0))
            self.upload_btn = ttk.Button(buttons, text="Retry Queued Uploads", command=self._retry_uploads)
            self.upload_btn.pack(side="left", padx=(16, 0))

            progress_frame = ttk.LabelFrame(outer, text="Live Progress", padding=10)
            progress_frame.pack(fill="x", pady=(12, 12))

            ttk.Label(progress_frame, text="Overall").pack(anchor="w")
            self.overall_pb = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate", maximum=1)
            self.overall_pb.pack(fill="x", pady=(2, 8))
            ttk.Label(progress_frame, text="Batch").pack(anchor="w")
            self.batch_pb = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate", maximum=1)
            self.batch_pb.pack(fill="x", pady=(2, 8))

            detail = ttk.Frame(progress_frame)
            detail.pack(fill="x")
            ttk.Label(detail, text="Stage:").grid(row=0, column=0, sticky="w")
            ttk.Label(detail, textvariable=self.stage_var).grid(row=0, column=1, sticky="w", padx=(8, 16))
            ttk.Label(detail, text="Current:").grid(row=0, column=2, sticky="w")
            ttk.Label(detail, textvariable=self.current_var).grid(row=0, column=3, sticky="w", padx=(8, 0))
            ttk.Label(detail, text="Counters:").grid(row=1, column=0, sticky="w", pady=(6, 0))
            ttk.Label(detail, textvariable=self.counter_var).grid(row=1, column=1, columnspan=3, sticky="w", padx=(8, 0), pady=(6, 0))
            ttk.Label(detail, text="Telemetry:").grid(row=2, column=0, sticky="w", pady=(6, 0))
            ttk.Label(detail, textvariable=self.telemetry_var).grid(row=2, column=1, columnspan=3, sticky="w", padx=(8, 0), pady=(6, 0))

            ttk.Label(outer, textvariable=self.summary_var).pack(anchor="w", pady=(0, 8))

            log_frame = ttk.LabelFrame(outer, text="Event Log", padding=8)
            log_frame.pack(fill="both", expand=True)
            self.log_text = scrolledtext.ScrolledText(log_frame, wrap="word", height=18)
            self.log_text.pack(fill="both", expand=True)
            self.log_text.configure(state="disabled")

        def _append_log(self, line: str) -> None:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", f"{line}\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

        def _upload_active(self) -> bool:
            return self.upload_thread is not None and self.upload_thread.is_alive()

        def _site_root(self) -> str:
            base = (self.base_url_var.get().strip() or str(self.base_args.base_url)).rstrip("/")
            if base.endswith("/api"):
                base = base[: -len("/api")]
            return f"{base}/"

        def _refresh_controls(self) -> None:
            idle = not self.running and not self._upload_active()
            self.start_btn.configure(state="normal" if idle else "disabled")
            self.stop_btn.configure(state="normal" if self.running else "disabled")
            self.upload_btn.configure(state="normal" if idle else "disabled")

        def _set_running(self, running: bool) -> None:
            self.running = running
            self._refresh_controls()
            readonly = "disabled" if running else "readonly"
            enabled = "disabled" if running else "normal"
            self.mode_combo.configure(state=readonly)
            self.encoder_combo.configure(state=readonly if not running else "disabled")
            self.preset_combo.configure(state=readonly if not running else "disabled")
            self.retries_spin.configure(state="normal" if not self.running and not self._upload_active() else "disabled")
            self.batch_spin.configure(state="normal" if not self.running and not self._upload_active() else "disabled")
            self.base_url_entry.configure(state="normal" if not self.running and not self._upload_active() else "disabled")
            self.crf_spin.configure(state=enabled)

        def _selected_mode_key(self) -> Optional[str]:
            return GUI_MODE_BY_LABEL.get(self.mode_var.get().strip())

        def _update_single_fields_state(self, preview: bool = True) -> None:
            single = self._selected_mode_key() is None
            state = "readonly" if single and not self.running else "disabled"
            spin_state = "normal" if single and not self.running else "disabled"
            self.encoder_combo.configure(state=state)
            self.preset_combo.configure(state=state)
            self.crf_spin.configure(state=spin_state)
            self.bitrate_entry.configure(state="normal" if single and not self.running else "disabled")
            if not self.running and not single and preview:
                mode_key = self._selected_mode_key()
                try:
                    self.summary_var.set(plan_summary_text(str(mode_key), encoders, presets_cfg))
                except Exception as exc:
                    self.summary_var.set(f"Plan preview unavailable: {exc}")

        def _refresh_encoders(self) -> None:
            labels = []
            self.encoder_values = []
            for enc in encoders:
                label = get_encoder_friendly_label(enc)
                labels.append(f"{label} ({enc})")
                self.encoder_values.append(enc)
            self.encoder_combo["values"] = labels
            if labels and not self.selected_encoder_var.get():
                index = self.encoder_values.index(initial_encoder)
                self.encoder_combo.current(index)
                self.selected_encoder_var.set(labels[index])
            self._refresh_presets(initial_preset)

        def _selected_encoder(self) -> str:
            idx = self.encoder_combo.current()
            if idx is None or idx < 0 or idx >= len(self.encoder_values):
                return ""
            return self.encoder_values[idx]

        def _refresh_presets(self, requested: Optional[str] = None) -> None:
            encoder = self._selected_encoder()
            presets = enumerate_supported_presets_for_encoder(encoder) if encoder else []
            if not presets:
                presets = ["medium"]
            self.preset_values = list(presets)
            self.preset_combo["values"] = presets
            if presets:
                self.preset_combo.current(presets.index(requested) if requested is not None else len(presets) // 2)
                self.selected_preset_var.set(self.preset_combo.get())

        def _selected_preset(self) -> str:
            value = self.preset_combo.get().strip()
            if value:
                return value
            return ""

        def _start_shortcut(self, _event: Any = None) -> str:
            self._start_run()
            return "break"

        def _stop_shortcut(self, _event: Any = None) -> str:
            self._stop_run()
            return "break"

        def _start_run(self) -> None:
            if self.running or self._upload_active():
                return
            mode = self.mode_var.get().strip()
            mode_key = GUI_MODE_BY_LABEL.get(mode)
            if mode_key is None and (
                not self._selected_encoder() or self._selected_preset() not in self.preset_values
            ):
                messagebox.showerror("Unsupported configuration", "Select an available encoder and supported preset before starting.")
                return
            self.cancel_event.clear()
            self.last_failure = None
            self._set_running(True)
            self.summary_var.set("Run started...")
            self.stage_var.set("Starting")
            self.current_var.set("-")
            self.telemetry_var.set("-")
            self.counter_var.set("ok=0 skip=0 queue=0 fail=0")
            self.overall_total = 1
            self.overall_done = 0
            self.batch_total = 1
            self.batch_done = 0
            self.overall_pb.configure(maximum=1, value=0)
            self.batch_pb.configure(maximum=1, value=0)
            self._append_log(f"Starting {mode} run")

            run_args = argparse.Namespace(**vars(self.base_args))
            run_args.base_url = self.base_url_var.get().strip() or self.base_args.base_url
            run_args.no_submit = bool(self.no_submit_var.get())
            run_args.retries = max(1, int(self.retries_var.get() or 1))
            run_args.batch_size = max(0, int(self.batch_size_var.get() or 0))
            run_args.pause_on_exit = False
            run_args.menu = False
            self._browse_shown = False
            if getattr(run_args, "explicit_max_duration_minutes", False):
                self._append_log(
                    f"Explicit measurement allowance: {float(run_args.max_duration_minutes):g} minutes; "
                    "the run stops there with the campaign saved for a later continuation."
                )
            else:
                self._append_log(
                    f"Checkpoint segments: {getattr(run_args, 'max_duration_minutes', 60):g} minutes each; "
                    "the run continues automatically until the plan completes. Acquisition and uploads are separate."
                )
            bitrate = self.bitrate_var.get().strip()
            try:
                run_args.target_bitrate_kbps = int(bitrate) if bitrate else None
            except ValueError:
                messagebox.showerror("Bitrate", "Enter a positive integer bitrate in kbps")
                self._set_running(False)
                return
            if not run_args.no_submit:
                consent_ok = client_main._ensure_interactive_publication_consent(
                    queue_dir=str(run_args.queue_dir),
                    prompt_callback=lambda disclosure: bool(messagebox.askyesno(
                        "Allow Benchmark Publication",
                        disclosure,
                        icon="warning",
                    )),
                )
                if not consent_ok:
                    run_args.no_submit = True
                    self.no_submit_var.set(True)
                    self._append_log("Publication consent not granted; switching to local dry-run mode.")

            self.worker_thread = threading.Thread(target=self._run_worker, args=(run_args, mode, mode_key), daemon=False)
            self.worker_thread.start()

        def _run_worker(self, run_args: argparse.Namespace, mode: str, mode_key: Optional[str]) -> None:
            def sink(event: Dict[str, Any]) -> None:
                self.event_queue.put(("event", event))

            rc = 1
            try:
                if mode_key is not None:
                    rc = client_main.run_sweep_mode(
                        mode=mode_key,
                        base_args=run_args,
                        event_sink=sink,
                        cancel_event=self.cancel_event,
                        show_end_screen=False,
                        interactive=True,
                        presets_cfg=dict(presets_cfg),
                    )
                else:
                    effective_args = client_main.build_single_effective_args(
                        base_args=run_args, encoder=self._selected_encoder(),
                        preset=self._selected_preset(), crf=int(self.crf_var.get()),
                    )
                    rc = client_main.run_with_args(effective_args, event_sink=sink,
                                                  cancel_event=self.cancel_event, show_end_screen=False)
            except Exception as e:
                self.event_queue.put(("error", f"{e}\n{traceback.format_exc()}"))
                rc = 1
            finally:
                self.event_queue.put(("done", rc))

        def _retry_uploads(self) -> None:
            if self.running or self._upload_active():
                return
            base_url = self.base_url_var.get().strip() or str(self.base_args.base_url)
            api_key = str(getattr(self.base_args, "api_key", "") or "")
            queue_dir = str(self.base_args.queue_dir)
            retries = max(1, int(self.retries_var.get() or 1))
            self._append_log("Retrying queued uploads (never encodes)...")
            self.summary_var.set("Retrying queued uploads...")
            self.upload_thread = threading.Thread(
                target=self._retry_uploads_worker,
                args=(queue_dir, base_url, api_key, retries),
                daemon=False,
            )
            self.upload_thread.start()
            self._refresh_controls()

        def _retry_uploads_worker(self, queue_dir: str, base_url: str, api_key: str, retries: int) -> None:
            try:
                pending_before = client_main.count_pending_entries(queue_dir)
                if not pending_before:
                    self.event_queue.put(("upload_status", "Upload queue is empty; nothing to retry."))
                    return
                stats = client_main.replay_spool(queue_dir, base_url=base_url, api_key=api_key,
                                                 retries=retries, use_token=False)
                remaining = client_main.count_pending_entries(queue_dir)
                self.event_queue.put((
                    "upload_status",
                    f"Upload retry: {pending_before} pending before, {remaining} still pending, "
                    f"dead-lettered={stats.dead_lettered}, corrupt={stats.corrupt}.",
                ))
            except Exception as e:
                self.event_queue.put(("upload_status", f"Upload retry failed: {e}"))

        def _stop_run(self) -> None:
            if not self.running:
                return
            self.cancel_event.set()
            self.summary_var.set("Stopping owned work; retaining downloads and campaign...")
            self._append_log("Cancellation requested")

        def _handle_event(self, event: Dict[str, Any]) -> None:
            event_type = str(event.get("type") or "")
            if not event_type:
                return

            if event_type == "preparation_progress":
                stage = str(event.get("stage") or "source")
                self.stage_var.set(f"Preparing: {stage}")
                label = event.get("clipId") or os.path.basename(str(event.get("path") or ""))
                done, total = event.get("completedBytes"), event.get("totalBytes")
                amount = f" ({done}/{total} bytes)" if done is not None and total else ""
                self.summary_var.set(f"Preparing {label}{amount}; Stop is available")
                return

            if event_type == "run_start":
                total = max(1, int(event.get("totalTasks") or 1))
                self.overall_total = total
                self.overall_done = 0
                self.overall_pb.configure(maximum=total, value=0)
                self.batch_pb.configure(maximum=total, value=0)
                self.summary_var.set(f"Running {event.get('scope', 'benchmark')} tasks")
                self._append_log(f"Run start: total={total}")
                return

            if event_type == "batch_start":
                batch_size = max(1, int(event.get("batchSize") or 1))
                self.batch_total = batch_size
                self.batch_done = 0
                self.batch_pb.configure(maximum=batch_size, value=0)
                self._append_log(
                    f"Batch {event.get('batchNo')}/{event.get('totalBatches')} start ({batch_size} tasks)"
                )
                return

            if event_type in ("encode_start", "metrics_start", "submit_start"):
                self.stage_var.set(event_type.replace("_", " ").title())
                enc = event.get("encoder") or event.get("codec") or "-"
                preset = event.get("preset") or "-"
                crf = event.get("crf")
                index = event.get("index")
                total = event.get("total")
                self.current_var.set(f"{index}/{total} {enc} {preset} crf={crf}")
                self._append_log(self.current_var.get())
                return

            if event_type == "encode_done":
                telemetry = event.get("telemetry") or {}
                if telemetry:
                    cpu = telemetry.get("cpuUtilAvg")
                    gpu = telemetry.get("gpuUtilAvg")
                    pwr = telemetry.get("gpuPowerAvgW")
                    cpu_samples = int(telemetry.get("cpuSampleCount") or 0)
                    gpu_samples = int(telemetry.get("gpuSampleCount") or 0)
                    missing = str(telemetry.get("telemetryMissing") or "none")
                    self.telemetry_var.set(
                        f"cpu={cpu}% gpu={gpu}% power={pwr}W samples(cpu={cpu_samples},gpu={gpu_samples}) missing={missing}"
                    )
                else:
                    fps = event.get("fps")
                    size = event.get("fileSizeBytes")
                    self.telemetry_var.set(f"fps={fps} size={size}")
                self._append_log(
                    f"Encode done: fps={event.get('fps')} size={event.get('fileSizeBytes')} error={event.get('error') or '-'}"
                )
                return

            if event_type == "metrics_done":
                metrics = event.get("metrics") or {}
                self._append_log(
                    f"Metrics: vmaf={metrics.get('vmaf')} ssim={metrics.get('ssim')} psnr={metrics.get('psnr')}"
                )
                return

            if event_type == "submit_result":
                line = f"Submit result: {event.get('status')} ({event.get('preset') or event.get('codec')})"
                # The ingest response carries only the BenchmarkRun id, which the site does
                # not resolve; never fabricate a per-run URL. Point at the corpus browse page.
                if event.get("status") == "submitted" and not self._browse_shown:
                    self._browse_shown = True
                    line += f" — browse all results: {self._site_root()}"
                self._append_log(line)
                return

            if event_type == "counters":
                self.counter_var.set(
                    f"ok={int(event.get('submitted') or 0)} "
                    f"skip={int(event.get('skipped') or 0)} "
                    f"queue={int(event.get('queued') or 0)} "
                    f"fail={int(event.get('failed') or 0)}"
                )
                return

            if event_type == "task_complete":
                processed = max(0, int(event.get("processed") or 0))
                self.overall_done = processed
                self.overall_pb.configure(value=min(self.overall_total, processed))
                if event.get("scope") == "batch" and self.batch_total > 0:
                    self.batch_done = min(self.batch_total, self.batch_done + 1)
                    self.batch_pb.configure(value=self.batch_done)
                elif event.get("scope") == "single":
                    self.batch_pb.configure(maximum=max(1, int(event.get("total") or 1)), value=processed)
                self.summary_var.set(f"Completed {processed}/{self.overall_total}")
                return

            if event_type == "run_complete":
                completed = event.get("completed")
                elapsed = event.get("elapsedSeconds")
                self.stage_var.set("Complete")
                self.summary_var.set(f"Completed {completed} task(s) in {elapsed:.1f}s" if isinstance(elapsed, (int, float)) else "Run complete")
                self._append_log(self.summary_var.get())
                return

            if event_type == "campaign_checkpoint_continue":
                self._append_log(
                    f"Time checkpoint reached; continuing the campaign from retained evidence "
                    f"(segment {event.get('segment')})."
                )
                return

            if event_type == "run_interrupted":
                self.stage_var.set("Interrupted")
                self.summary_var.set("Run interrupted")
                self._append_log("Run interrupted")
                return

            if event_type == "run_error":
                self.stage_var.set("Error")
                self.last_failure = str(event.get("message") or "").strip() or None
                self.summary_var.set(str(event.get("message") or "Run failed"))
                self._append_log(self.summary_var.get())

        def _poll_events(self) -> None:
            try:
                while True:
                    kind, payload = self.event_queue.get_nowait()
                    if kind == "event":
                        self._handle_event(payload)
                    elif kind == "error":
                        self.stage_var.set("Error")
                        first_line = str(payload).strip().splitlines()[0] if str(payload).strip() else ""
                        self.last_failure = first_line or None
                        self.summary_var.set("Run failed. See event log.")
                        self._append_log(payload)
                    elif kind == "done":
                        self._set_running(False)
                        rc = int(payload)
                        pending_note = ""
                        if rc in (0, 10, 11) and not self.no_submit_var.get():
                            try:
                                pending = client_main.count_pending_entries(str(self.base_args.queue_dir))
                            except Exception:
                                pending = 0
                            if pending:
                                pending_note = f" — {pending} upload(s) queued; use Retry Queued Uploads"
                        if rc == 0:
                            self.summary_var.set(("Locally complete" if self.no_submit_var.get() else "Uploaded; analysis pending") + pending_note)
                        elif rc == 11:
                            self.summary_var.set("Measurement allowance reached; campaign saved — starting this mode again continues it" + pending_note)
                        elif rc == 10:
                            self.summary_var.set(f"Saved locally; upload queued{pending_note}")
                        elif rc == 130:
                            self.summary_var.set("Run cancelled")
                        else:
                            if self.last_failure:
                                failure = f"Run failed (exit code {rc}): {self.last_failure}"
                            else:
                                failure = f"Run failed (exit code {rc}); see event log for details"
                            self.summary_var.set(failure)
                            self._append_log(failure)
                        self._update_single_fields_state(preview=False)
                    elif kind == "upload_status":
                        self._append_log(payload)
                        if not self.running:
                            self.summary_var.set(str(payload))
            except queue.Empty:
                pass
            if self.upload_thread is not None and not self.upload_thread.is_alive():
                self.upload_thread = None
            self._refresh_controls()
            self.root.after(120, self._poll_events)

        def _on_close(self) -> None:
            if self.running or self._upload_active():
                if not messagebox.askyesno("Exit", "EncodingDB still has active work (benchmark run and/or upload replay). Stop and exit?"):
                    return
                if self.running:
                    self.cancel_event.set()
                self.summary_var.set("Stopping owned work before close...")
                self._close_deadline = time.monotonic() + GUI_CLOSE_GRACE_SECONDS
                self.root.after(100, self._close_when_stopped)
                return
            self.root.destroy()

        def _close_when_stopped(self):
            benchmark = self.worker_thread is not None and self.worker_thread.is_alive()
            uploader = self._upload_active()
            if benchmark or uploader:
                if time.monotonic() >= self._close_deadline:
                    self.summary_var.set("Waiting for the current operation to finish safely before closing...")
                    self._close_deadline = time.monotonic() + GUI_CLOSE_GRACE_SECONDS
                self.root.after(100, self._close_when_stopped)
                return
            self.root.destroy()

        def run(self) -> int:
            self.root.mainloop()
            return 0

    app = WindowsClientApp()
    return app.run()
