import argparse
import os
import queue
import re
import threading
import time
import traceback
from typing import Any, Dict, Optional

from . import main as client_main
from . import sweep_plan
from . import suite
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


def _validated_integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    """Read a Tk variable without leaving the window running on TclError."""
    try:
        raw = str(value.get()).strip()
        if not re.fullmatch(r"[0-9]+", raw):
            raise ValueError
        number = int(raw)
    except Exception as exc:
        raise ValueError(f"{label} must be a whole number from {minimum} to {maximum}.") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"{label} must be a whole number from {minimum} to {maximum}.")
    return number


def _submission_line(event: Dict[str, Any]) -> str:
    def display(value: Any, limit: int) -> str:
        text = " ".join(str(value or "").split())
        text = re.sub(r"(?i)\b(bearer)\s+\S+", r"\1 [redacted]", text)
        text = re.sub(r"(?i)\b(token|api[_-]?key|secret|authorization)\s*[:=]\s*\S+",
                      r"\1=[redacted]", text)
        return text[:limit]

    status = display(event.get("status") or "unknown", 24)
    category = display(event.get("errorCategory"), 40)
    reason = display(event.get("safeReason"), 240)
    action = display(event.get("recoveryAction"), 160)
    codes = event.get("reasonCodes")
    if isinstance(codes, (list, tuple)):
        valid_codes = [str(code) for code in codes if re.fullmatch(r"[A-Za-z0-9_-]{1,48}", str(code))]
    else:
        valid_codes = []
    run_id = str(event.get("benchmarkRunId") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        run_id = ""
    details = [item for item in (category, reason, ", ".join(valid_codes[:4]), action) if item]
    label = display(event.get("preset") or event.get("codec") or event.get("campaignId"), 80)
    line = f"Submission {status}" + (f" ({label})" if label else "")
    if details:
        line += ": " + "; ".join(details)
    if run_id:
        line += f" [run {run_id}]"
    return line


def _acquisition_preview(mode_key: Optional[str]) -> Dict[str, Any]:
    manifest = suite.load_default_suite_manifest()
    if mode_key in (None, "small"):
        clip_ids = [suite.get_default_quick_clip(manifest).clip_id]
    else:
        clip_ids = [clip.clip_id for clip in manifest.clips]
    return suite.acquisition_estimate(clip_ids, manifest=manifest)


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
            self.upload_cancel_event = threading.Event()
            self.cancel_event = threading.Event()
            self.running = False
            self._active_no_submit: Optional[bool] = None
            self._last_submission_failure = ""
            self._run_counts = {"submitted": 0, "locally_complete": 0, "queued": 0, "failed": 0}
            self._browse_shown = False
            self._close_deadline = 0.0
            self._estimate_acquisition = _acquisition_preview
            self._load_recovery_state = lambda: client_main.recovery_state(str(self.base_args.queue_dir))
            self.saved_campaign_ids: list[str] = []
            self.saved_state: Dict[str, Any] = {}
            # Causal message from the most recent run_error/unhandled failure in this
            # run; the done handler must not replace it with a bare exit code.
            self.last_failure: Optional[str] = None

            self.mode_var = tk.StringVar(value="Small")
            self.advanced_var = tk.BooleanVar(value=False)
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
            self.counter_var = tk.StringVar(value="local=0 uploaded=0 queued=0 failed=0")
            self.saved_summary_var = tk.StringVar(value="Checking saved work...")
            self.selected_saved_var = tk.StringVar(value="")

            self.overall_total = 1
            self.overall_done = 0
            self.batch_total = 1
            self.batch_done = 0

            self.encoder_values = []
            self.preset_values = []

            self._build_ui(ttk, tk, scrolledtext)
            self._toggle_advanced()
            self._refresh_encoders()
            self._update_single_fields_state()
            self._refresh_saved_work()
            self._refresh_controls()
            self._poll_events()
            self.root.after(30_000, self._idle_retry)
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

            self.no_submit_check = ttk.Checkbutton(row1, text="Save locally; publish later",
                                                    variable=self.no_submit_var, command=self._refresh_controls)
            self.no_submit_check.pack(side="left", padx=(0, 12))

            self.advanced_toggle = ttk.Checkbutton(config_frame, text="Advanced settings", variable=self.advanced_var,
                                                    command=self._toggle_advanced)
            self.advanced_toggle.pack(anchor="w")
            self.advanced_frame = ttk.LabelFrame(config_frame, text="Advanced settings", padding=10)
            advanced_row = ttk.Frame(self.advanced_frame)
            advanced_row.pack(fill="x", pady=(0, 8))
            ttk.Label(advanced_row, text="Retries").pack(side="left")
            self.retries_spin = ttk.Spinbox(advanced_row, from_=1, to=10, textvariable=self.retries_var, width=6)
            self.retries_spin.pack(side="left", padx=(6, 12))
            ttk.Label(advanced_row, text="Batch size").pack(side="left")
            self.batch_spin = ttk.Spinbox(advanced_row, from_=0, to=64, textvariable=self.batch_size_var, width=6)
            self.batch_spin.pack(side="left", padx=(6, 0))

            row2 = ttk.Frame(self.advanced_frame)
            row2.pack(fill="x", pady=(0, 8))
            ttk.Label(row2, text="Base URL").pack(side="left")
            self.base_url_entry = ttk.Entry(row2, textvariable=self.base_url_var)
            self.base_url_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))

            row3 = ttk.Frame(self.advanced_frame)
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
            self.buttons_frame = buttons
            buttons.pack(fill="x", pady=(10, 0))
            self.start_btn = ttk.Button(buttons, text="Start benchmark (Alt+B)", underline=6, command=self._start_run)
            self.start_btn.pack(side="left")
            self.stop_btn = ttk.Button(buttons, text="Stop (Alt+S)", underline=0, command=self._stop_run, state="disabled")
            self.stop_btn.pack(side="left", padx=(8, 0))
            self.upload_btn = ttk.Button(buttons, text="Retry due uploads", command=self._retry_uploads)
            self.upload_btn.pack(side="left", padx=(16, 0))

            saved_frame = ttk.LabelFrame(outer, text="Saved work", padding=10)
            saved_frame.pack(fill="x", pady=(12, 0))
            ttk.Label(saved_frame, textvariable=self.saved_summary_var).pack(anchor="w")
            saved_row = ttk.Frame(saved_frame)
            saved_row.pack(fill="x", pady=(6, 0))
            self.saved_combo = ttk.Combobox(saved_row, textvariable=self.selected_saved_var,
                                            values=[], state="readonly", width=64)
            self.saved_combo.pack(side="left", fill="x", expand=True)
            self.saved_combo.bind("<<ComboboxSelected>>", lambda _evt: self._refresh_controls())
            self.resume_btn = ttk.Button(saved_row, text="Resume", command=self._resume_saved)
            self.resume_btn.pack(side="left", padx=(8, 0))
            self.publish_btn = ttk.Button(saved_row, text="Publish saved results", command=self._publish_saved)
            self.publish_btn.pack(side="left", padx=(8, 0))
            ttk.Label(saved_frame, text="To publish, turn off Save locally and approve uploads.").pack(anchor="w", pady=(6, 0))

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
            self.stop_btn.configure(state="normal" if self.running or self._upload_active() else "disabled")
            self.upload_btn.configure(state="normal" if idle and not self.no_submit_var.get() else "disabled")
            self.no_submit_check.configure(state="normal" if idle else "disabled")
            selected = self._selected_saved_state()
            actions = {str(action.get("action") or "") for action in (selected or {}).get("actions", [])}
            self.resume_btn.configure(state="normal" if idle and "resume" in actions else "disabled")
            self.publish_btn.configure(state="normal" if idle and not self.no_submit_var.get()
                                       and "publish_saved" in actions else "disabled")

        def _selected_saved_campaign(self) -> str:
            index = self.saved_combo.current()
            if index is None or index < 0 or index >= len(self.saved_campaign_ids):
                return ""
            return self.saved_campaign_ids[index]

        def _selected_saved_state(self) -> Optional[Dict[str, Any]]:
            campaign_id = self._selected_saved_campaign()
            return next((item for item in self.saved_state.get("campaigns", [])
                         if item.get("campaignId") == campaign_id), None)

        def _confirm_publication_consent(self) -> bool:
            return client_main._ensure_interactive_publication_consent(
                queue_dir=str(self.base_args.queue_dir),
                prompt_callback=lambda disclosure: bool(messagebox.askyesno(
                    "Allow Benchmark Publication", disclosure, icon="warning",
                )),
            )

        def _refresh_saved_work(self) -> None:
            previous = self._selected_saved_campaign() if self.saved_campaign_ids else ""
            try:
                state = self._load_recovery_state()
            except Exception as exc:
                self.saved_state = {}
                self.saved_summary_var.set(f"Saved work unavailable: {exc}")
                return
            self.saved_state = state
            publication = state.get("publication") or {}
            pending = int(publication.get("pendingEntries") or 0)
            due = int(publication.get("dueEntries") or 0)
            terminal = int(publication.get("terminalEntries") or 0)
            accepted = int(publication.get("acceptedReceipts") or 0)
            campaigns = list(state.get("campaigns") or [])
            self.saved_summary_var.set(
                f"{len(campaigns)} campaign(s) · {due} due / {max(0, pending - due)} delayed uploads · "
                f"{accepted} uploaded (analysis pending) · {terminal} terminal"
            )
            self.saved_campaign_ids = [str(item.get("campaignId") or "") for item in campaigns]
            labels = [
                f"{item.get('campaignId')} — {'measured' if item.get('complete') else 'unfinished'}, "
                f"{int(item.get('pendingUploads') or 0)} unpublished, "
                f"{int(item.get('queueDue') or 0)} due, "
                f"{int(item.get('queueTerminal') or 0)} terminal, "
                f"{int(item.get('unavailableSources') or 0)} unavailable"
                for item in campaigns
            ]
            self.saved_combo["values"] = labels
            if labels:
                self.saved_combo.current(self.saved_campaign_ids.index(previous) if previous in self.saved_campaign_ids else 0)
            else:
                self.selected_saved_var.set("")
            self._refresh_controls()

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
            self._update_single_fields_state(preview=False)

        def _selected_mode_key(self) -> Optional[str]:
            return GUI_MODE_BY_LABEL.get(self.mode_var.get().strip())

        def _toggle_advanced(self) -> None:
            if self.advanced_var.get():
                self.advanced_frame.pack(fill="x", pady=(8, 0), before=self.buttons_frame)
            else:
                self.advanced_frame.pack_forget()

        def _update_single_fields_state(self, preview: bool = True) -> None:
            single = self._selected_mode_key() is None
            if single and not self.advanced_var.get():
                self.advanced_var.set(True)
                self._toggle_advanced()
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

        def _resume_saved(self) -> None:
            campaign_id = self._selected_saved_campaign()
            if campaign_id:
                self._start_run(resume_id=campaign_id)

        def _start_run(self, *, resume_id: str = "") -> None:
            if self.running or self._upload_active():
                return
            try:  # Advisory only; run_benchmark_batch refuses authoritatively before any preparation.
                active = client_main.active_collection(str(self.base_args.queue_dir))
            except Exception:
                active = None
            if active is not None:
                who = f" (campaign {active['campaignId']}, PID {active['pid']})" if active.get("campaignId") else ""
                self.summary_var.set(f"Another collection is actively running in this queue{who}. "
                                     f"Its checkpoints continue automatically - let it finish, or "
                                     f"stop/cancel that run first. Due uploads resume after measurement.")
                self._append_log("Start refused: active collection detected")
                return
            try:
                mode = self.mode_var.get().strip()
                if mode not in GUI_MODE_BY_LABEL:
                    raise ValueError("Choose a listed contribution mode.")
                mode_key = GUI_MODE_BY_LABEL[mode]
                run_args = argparse.Namespace(**vars(self.base_args))
                run_args.base_url = self.base_url_var.get().strip() or str(self.base_args.base_url)
                run_args.no_submit = bool(self.no_submit_var.get())
                if resume_id:
                    run_args.resume_campaign = resume_id
                    run_args.submit = not run_args.no_submit
                if not run_args.no_submit and not re.match(r"^https?://[^/\s]+", run_args.base_url):
                    raise ValueError("Base URL must be an HTTP or HTTPS address.")
                run_args.retries = _validated_integer(self.retries_var, "Retries", 1, 10)
                run_args.batch_size = _validated_integer(self.batch_size_var, "Batch size", 0, 64)
                run_args.pause_on_exit = False
                run_args.menu = False
                bitrate = str(self.bitrate_var.get()).strip()
                if mode_key is None and not resume_id:
                    encoder, preset = self._selected_encoder(), self._selected_preset()
                    if not encoder or preset not in self.preset_values:
                        raise ValueError("Select an available encoder and supported preset before starting.")
                    quality = _validated_integer(self.crf_var, "Native quality value", 0, 40)
                    if bitrate and not re.fullmatch(r"[0-9]+", bitrate):
                        raise ValueError("Bitrate must be a positive whole number in kbps.")
                    run_args.target_bitrate_kbps = int(bitrate) if bitrate else None
                    if run_args.target_bitrate_kbps is not None and run_args.target_bitrate_kbps <= 0:
                        raise ValueError("Bitrate must be a positive whole number in kbps.")
                    run_args = client_main.build_single_effective_args(
                        base_args=run_args, encoder=encoder, preset=preset, crf=quality,
                    )
                if not resume_id:
                    estimate = self._estimate_acquisition(mode_key)
                    if not estimate.get("storageOk", True):
                        raise ValueError(
                            "Not enough writable disk space for this contribution. "
                            f"Estimated peak: {client_main._format_byte_count(int(estimate['peakStorageBytes']))}."
                        )
                    if estimate.get("strategy") == "unavailable":
                        raise ValueError("The selected frozen clips are unavailable. " + "; ".join(estimate.get("warnings") or []))
                    transfer = int(estimate.get("bytesToTransfer") or 0)
                    if transfer:
                        approved = messagebox.askyesno(
                            "Download and storage estimate",
                            f"This run may download {client_main._format_byte_count(transfer)} of frozen reference media. "
                            f"Estimated peak extra storage: {client_main._format_byte_count(int(estimate.get('peakStorageBytes') or 0))}. "
                            "Continue?",
                        )
                        if not approved:
                            self.summary_var.set("Run not started; download estimate declined")
                            return
                if not run_args.no_submit:
                    consent_ok = self._confirm_publication_consent()
                    if not consent_ok:
                        run_args.no_submit = True
                        self.no_submit_var.set(True)
                        self._append_log("Publication consent not granted; saving locally.")
            except Exception as exc:
                messagebox.showerror("Check settings", str(exc))
                self.summary_var.set(f"Check settings: {exc}")
                return

            try:
                self._active_no_submit = run_args.no_submit
                self._last_submission_failure = ""
                self._run_counts = {"submitted": 0, "locally_complete": 0, "queued": 0, "failed": 0}
                self.cancel_event.clear()
                self.last_failure = None
                self._set_running(True)
                self.summary_var.set("Run started...")
                self.stage_var.set("Starting")
                self.current_var.set("-")
                self.telemetry_var.set("-")
                self.counter_var.set("local=0 uploaded=0 queued=0 failed=0")
                self.overall_total = self.batch_total = 1
                self.overall_done = self.batch_done = 0
                self.overall_pb.configure(maximum=1, value=0)
                self.batch_pb.configure(maximum=1, value=0)
                self._append_log(f"Resuming {resume_id}" if resume_id else f"Starting {mode} run")
                self._browse_shown = False
                if getattr(run_args, "max_duration_minutes_explicit", False):
                    self._append_log(
                        f"Explicit measurement allowance: {float(run_args.max_duration_minutes):g} minutes; "
                        "the run stops there with the campaign saved for a later continuation."
                    )
                else:
                    self._append_log(
                        f"Checkpoint segments: {getattr(run_args, 'max_duration_minutes', 60):g} minutes each; "
                        "the run continues automatically until the plan completes. Acquisition and uploads are separate."
                    )
                self.worker_thread = threading.Thread(target=self._run_worker, args=(run_args, mode, mode_key), daemon=False)
                self.worker_thread.start()
            except Exception as exc:
                self.worker_thread = None
                self._active_no_submit = None
                self._set_running(False)
                self._update_single_fields_state(preview=False)
                self.stage_var.set("Idle")
                self.summary_var.set(f"Could not start run: {exc}")
                messagebox.showerror("Could not start", str(exc))

        def _run_worker(self, run_args: argparse.Namespace, mode: str, mode_key: Optional[str]) -> None:
            def sink(event: Dict[str, Any]) -> None:
                self.event_queue.put(("event", event))

            rc = 1
            try:
                if getattr(run_args, "resume_campaign", ""):
                    rc = client_main._resume_campaign(run_args, event_sink=sink,
                                                      cancel_event=self.cancel_event, interactive=False)
                elif mode_key is not None:
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
                    rc = client_main.run_with_args(run_args, event_sink=sink,
                                                  cancel_event=self.cancel_event, show_end_screen=False)
            except Exception as e:
                self.event_queue.put(("error", f"{e}\n{traceback.format_exc()}"))
                rc = 1
            finally:
                self.event_queue.put(("done", rc))

        def _publish_saved(self) -> None:
            if self.running or self._upload_active():
                return
            if self.no_submit_var.get():
                self.summary_var.set("Turn off Save locally before publishing saved results")
                return
            campaign_id = self._selected_saved_campaign()
            if not campaign_id:
                return
            try:
                retries = _validated_integer(self.retries_var, "Retries", 1, 10)
                if not self._confirm_publication_consent():
                    self.summary_var.set("Saved work remains local; publication consent was not granted")
                    return
                self.upload_cancel_event.clear()
                self.upload_thread = threading.Thread(
                    target=self._publish_saved_worker,
                    args=(campaign_id, self.base_url_var.get().strip() or str(self.base_args.base_url),
                          str(getattr(self.base_args, "api_key", "") or ""), retries),
                    daemon=False,
                )
                self.upload_thread.start()
                self.summary_var.set(f"Publishing saved results from {campaign_id}; no encoding")
                self._refresh_controls()
            except Exception as exc:
                self.upload_thread = None
                self.summary_var.set(f"Could not publish saved work: {exc}")
                messagebox.showerror("Publish saved results", str(exc))
                self._refresh_controls()

        def _publish_saved_worker(self, campaign_id: str, base_url: str, api_key: str, retries: int) -> None:
            try:
                rc, info = client_main.publish_saved_campaign(
                    queue_dir=str(self.base_args.queue_dir), campaign_id=campaign_id,
                    base_url=base_url, api_key=api_key, retries=retries,
                    interactive=False, cancel_event=self.upload_cancel_event,
                    event_sink=lambda event: self.event_queue.put(("event", event)),
                )
                self.event_queue.put(("upload_status", self._publication_result_text(rc, info)))
            except Exception as exc:
                self.event_queue.put(("upload_status", f"Saved publication failed: {exc}"))

        @staticmethod
        def _publication_result_text(rc: int, info: Dict[str, Any]) -> str:
            submitted = int(info.get("submitted") or 0)
            pending = int(info.get("pending") or 0)
            unadmitted = int(info.get("unadmitted") or 0)
            terminal = int(info.get("terminal") or 0) + int(info.get("deadLettered") or 0)
            if rc == 0:
                return f"Uploaded {submitted} saved result(s); analysis pending"
            if rc == 10:
                reason = str(info.get("deferredReason") or "uploads_pending")
                return (f"Saved work retained: {pending} queued, {unadmitted} not yet staged "
                        f"({reason}); no encoding")
            return f"Saved publication has {terminal} terminal failure(s); review saved work"

        def _retry_uploads(self, *, automatic: bool = False) -> None:
            if self.running or self._upload_active():
                return
            if self.no_submit_var.get():
                self.summary_var.set("Turn off Save locally before retrying uploads")
                return
            try:
                retries = _validated_integer(self.retries_var, "Retries", 1, 10)
                if not automatic and not self._confirm_publication_consent():
                    self.summary_var.set("Queued uploads remain local; publication consent was not granted")
                    return
            except Exception as exc:
                messagebox.showerror("Check settings", str(exc))
                self.summary_var.set(f"Check settings: {exc}")
                return
            base_url = self.base_url_var.get().strip() or str(self.base_args.base_url)
            api_key = str(getattr(self.base_args, "api_key", "") or "")
            queue_dir = str(self.base_args.queue_dir)
            self._append_log("Retrying queued uploads (never encodes)...")
            self.summary_var.set("Retrying queued uploads...")
            self.upload_cancel_event.clear()
            try:
                self.upload_thread = threading.Thread(
                    target=self._retry_uploads_worker,
                    args=(queue_dir, base_url, api_key, retries),
                    daemon=False,
                )
                self.upload_thread.start()
                self._refresh_controls()
            except Exception as exc:
                self.upload_thread = None
                self.summary_var.set(f"Could not start upload retry: {exc}")
                messagebox.showerror("Retry uploads", str(exc))
                self._refresh_controls()

        def _retry_uploads_worker(self, queue_dir: str, base_url: str, api_key: str, retries: int) -> None:
            try:
                pending_before = client_main.count_pending_entries(queue_dir)
                if not pending_before:
                    self.event_queue.put(("upload_status", "Upload queue is empty; nothing to retry."))
                    return
                rc, info = client_main.retry_due_uploads(
                    queue_dir=queue_dir, base_url=base_url, api_key=api_key,
                    retries=retries, use_token=False, cancel_event=self.upload_cancel_event,
                )
                remaining = int(info.get("pending") or client_main.count_pending_entries(queue_dir))
                self.event_queue.put((
                    "upload_status",
                    f"Upload retry: {pending_before} pending before, {remaining} still pending, "
                    f"dead-lettered={int(info.get('deadLettered') or 0)}, "
                    f"corrupt={int(info.get('corrupt') or 0)}, status={info.get('status') or rc}.",
                ))
            except Exception as e:
                self.event_queue.put(("upload_status", f"Upload retry failed: {e}"))

        def _idle_retry(self) -> None:
            try:
                if not self.running and not self._upload_active():
                    self._refresh_saved_work()
                    publication = self.saved_state.get("publication") or {}
                    if (self.saved_state.get("publicationConsent") and not self.no_submit_var.get()
                            and not self.saved_state.get("activeCollection")
                            and not self.saved_state.get("publicationLockBusy")
                            and int(publication.get("dueEntries") or 0)):
                        self._retry_uploads(automatic=True)
            finally:
                self.root.after(30_000, self._idle_retry)

        def _stop_run(self) -> None:
            if not self.running and not self._upload_active():
                return
            if self.running:
                self.cancel_event.set()
            if self._upload_active():
                self.upload_cancel_event.set()
            self.summary_var.set("Stopping owned work; retaining saved results...")
            self._append_log("Cancellation requested")

        def _handle_event(self, event: Dict[str, Any]) -> None:
            event_type = str(event.get("type") or "")
            if not event_type:
                return

            if event_type == "preparation_progress":
                stage = str(event.get("stage") or "source")
                self.stage_var.set(f"Preparing: {stage}")
                if stage == "recovery" and event.get("message"):
                    self.summary_var.set("Suite cache recovery active; using a verified writable copy")
                    self._append_log(f"Cache recovery: {event['message']}")
                    return
                label = event.get("clipId") or os.path.basename(str(event.get("path") or ""))
                done, total = event.get("completedBytes"), event.get("totalBytes")
                if done is not None and total:
                    amount = f" ({done}/{total} bytes)"
                elif event.get("completed") is not None and event.get("total"):
                    amount = f" ({event['completed']}/{event['total']})"
                else:
                    amount = ""
                self.summary_var.set(f"Preparing {label}{amount}; Stop is available")
                return

            if event_type == "run_start":
                # Batch totalTasks is an upper bound on encode attempts, while
                # task_complete counts finished measurement groups.
                total = max(1, int(event.get("totalGroups") or 1)) if event.get("scope") == "batch" else max(1, int(event.get("totalTasks") or 1))
                self.overall_total = total
                self.overall_done = 0
                self.overall_pb.configure(maximum=total, value=0)
                self.batch_pb.configure(maximum=total, value=0)
                self.summary_var.set(f"Running {event.get('scope', 'benchmark')} measurement groups")
                self._append_log(f"Run start: groups={total}")
                return

            if event_type == "batch_start":
                batch_size = max(1, int(event.get("batchSize") or 1))
                self.batch_total = batch_size
                self.batch_done = 0
                self.batch_pb.configure(maximum=batch_size, value=0)
                if int(event.get("totalBatches") or 1) == 1:
                    self.overall_total = batch_size
                    self.overall_done = min(batch_size, max(0, int(event.get("processedTotal") or 0)))
                    self.overall_pb.configure(maximum=batch_size, value=self.overall_done)
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
                line = _submission_line(event)
                status = str(event.get("status") or "")
                if status in self._run_counts:
                    self._run_counts[status] += 1
                if status == "locally_complete":
                    self.counter_var.set(
                        f"local={self._run_counts['locally_complete']} "
                        f"uploaded={self._run_counts['submitted']} "
                        f"queued={self._run_counts['queued']} failed={self._run_counts['failed']}"
                    )
                if status in {"failed", "rejected", "queued"}:
                    self._last_submission_failure = line
                    self.summary_var.set(line)
                # The ingest response carries only the BenchmarkRun id, which the site does
                # not resolve; never fabricate a per-run URL. Point at the corpus browse page.
                if event.get("status") == "submitted" and not self._browse_shown:
                    self._browse_shown = True
                    line += f" — browse all results: {self._site_root()}"
                self._append_log(line)
                return

            if event_type == "counters":
                self.counter_var.set(
                    f"local={self._run_counts['locally_complete']} "
                    f"uploaded={int(event.get('submitted') or 0)} (analysis pending) "
                    f"skipped={int(event.get('skipped') or 0)} "
                    f"queued={int(event.get('queued') or 0)} "
                    f"failed={int(event.get('failed') or 0)}"
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
                        active_no_submit = self._active_no_submit
                        self._active_no_submit = None
                        pending_note = ""
                        if rc in (0, 10, 11) and not active_no_submit:
                            try:
                                pending = client_main.count_pending_entries(str(self.base_args.queue_dir))
                            except Exception:
                                pending = 0
                            if pending:
                                pending_note = f" — {pending} upload(s) queued; due work retries while this window is open"
                        if rc == 0:
                            if active_no_submit:
                                saved = self._run_counts["locally_complete"]
                                count = f"{saved} measurement group(s) " if saved else ""
                                self.summary_var.set(f"Saved {count}locally; use Publish saved results when ready")
                            elif self._run_counts["failed"]:
                                self.summary_var.set(self._last_submission_failure + pending_note)
                            elif self._run_counts["queued"] or pending_note:
                                self.summary_var.set("Measurements saved; some uploads are queued" + pending_note)
                            elif self._run_counts["submitted"]:
                                self.summary_var.set("Uploaded; analysis pending")
                            else:
                                self.summary_var.set("Run finished; review saved work")
                        elif rc == 11:
                            self.summary_var.set("Measurement allowance reached; campaign saved — starting this mode again continues it" + pending_note)
                        elif rc == 10:
                            self.summary_var.set(f"Saved locally; upload queued{pending_note}")
                        elif rc == 130:
                            self.summary_var.set("Run cancelled")
                        else:
                            failure = self._last_submission_failure or self.last_failure
                            failure = f"Run failed (exit code {rc}): {failure}" if failure else f"Run failed (exit code {rc}); see event log for details"
                            self.summary_var.set(failure)
                            self._append_log(failure)
                        self._update_single_fields_state(preview=False)
                        self._refresh_saved_work()
                    elif kind == "upload_status":
                        self._append_log(payload)
                        if not self.running:
                            self.summary_var.set(str(payload))
            except queue.Empty:
                pass
            if self.upload_thread is not None and not self.upload_thread.is_alive():
                self.upload_thread = None
                self._refresh_saved_work()
            self._refresh_controls()
            self.root.after(120, self._poll_events)

        def _on_close(self) -> None:
            if self.running or self._upload_active():
                if not messagebox.askyesno("Exit", "EncodingDB still has active work (benchmark run and/or upload replay). Stop and exit?"):
                    return
                if self.running:
                    self.cancel_event.set()
                if self._upload_active():
                    self.upload_cancel_event.set()
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
