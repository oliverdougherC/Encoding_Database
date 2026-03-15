import argparse
import os
import queue
import threading
import traceback
from typing import Any, Dict, Optional

from . import main as client_main
from .encoders import (
    enumerate_supported_presets_for_encoder,
    get_encoder_friendly_label,
    list_all_available_encoders,
)


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

    class WindowsClientApp:
        def __init__(self) -> None:
            self.root = tk.Tk()
            self.root.title("EncodingDB Windows Client")
            self.root.geometry("1100x760")
            self.root.minsize(980, 700)

            self.base_args = argparse.Namespace(**vars(base_args))
            self.event_queue: queue.Queue = queue.Queue()
            self.worker_thread: Optional[threading.Thread] = None
            self.cancel_event = threading.Event()
            self.running = False

            self.mode_var = tk.StringVar(value="Medium")
            self.no_submit_var = tk.BooleanVar(value=bool(getattr(base_args, "no_submit", False)))
            self.base_url_var = tk.StringVar(value=str(getattr(base_args, "base_url", "")))
            self.retries_var = tk.IntVar(value=max(1, int(getattr(base_args, "retries", 3))))
            self.batch_size_var = tk.IntVar(value=max(0, int(getattr(base_args, "batch_size", 0))))
            self.crf_var = tk.IntVar(value=int(getattr(base_args, "crf", 24) or 24))

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
            self._poll_events()
            self.root.protocol("WM_DELETE_WINDOW", self._on_close)

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
                values=["Single", "Small", "Medium", "Full"],
                state="readonly",
                width=14,
            )
            self.mode_combo.pack(side="left", padx=(8, 16))
            self.mode_combo.bind("<<ComboboxSelected>>", lambda _evt: self._update_single_fields_state())

            ttk.Checkbutton(row1, text="No submit (dry run)", variable=self.no_submit_var).pack(side="left", padx=(0, 12))
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

            ttk.Label(row3, text="CRF").pack(side="left")
            self.crf_spin = ttk.Spinbox(row3, from_=10, to=40, textvariable=self.crf_var, width=6)
            self.crf_spin.pack(side="left", padx=(8, 0))

            buttons = ttk.Frame(config_frame)
            buttons.pack(fill="x", pady=(10, 0))
            self.start_btn = ttk.Button(buttons, text="Start Run", command=self._start_run)
            self.start_btn.pack(side="left")
            self.stop_btn = ttk.Button(buttons, text="Stop", command=self._stop_run, state="disabled")
            self.stop_btn.pack(side="left", padx=(8, 0))

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

        def _set_running(self, running: bool) -> None:
            self.running = running
            start_state = "disabled" if running else "normal"
            stop_state = "normal" if running else "disabled"
            self.start_btn.configure(state=start_state)
            self.stop_btn.configure(state=stop_state)
            readonly = "disabled" if running else "readonly"
            enabled = "disabled" if running else "normal"
            self.mode_combo.configure(state=readonly)
            self.encoder_combo.configure(state=readonly if not running else "disabled")
            self.preset_combo.configure(state=readonly if not running else "disabled")
            self.retries_spin.configure(state=enabled)
            self.batch_spin.configure(state=enabled)
            self.base_url_entry.configure(state=enabled)
            self.crf_spin.configure(state=enabled)

        def _update_single_fields_state(self) -> None:
            single = self.mode_var.get() == "Single"
            state = "readonly" if single and not self.running else "disabled"
            spin_state = "normal" if single and not self.running else "disabled"
            self.encoder_combo.configure(state=state)
            self.preset_combo.configure(state=state)
            self.crf_spin.configure(state=spin_state)

        def _refresh_encoders(self) -> None:
            encoders = list_all_available_encoders()
            labels = []
            self.encoder_values = []
            for enc in encoders:
                label = get_encoder_friendly_label(enc)
                labels.append(f"{label} ({enc})")
                self.encoder_values.append(enc)
            self.encoder_combo["values"] = labels
            if labels and not self.selected_encoder_var.get():
                self.encoder_combo.current(0)
                self.selected_encoder_var.set(labels[0])
            self._refresh_presets()

        def _selected_encoder(self) -> str:
            idx = self.encoder_combo.current()
            if idx is None or idx < 0 or idx >= len(self.encoder_values):
                return self.encoder_values[0] if self.encoder_values else ""
            return self.encoder_values[idx]

        def _refresh_presets(self) -> None:
            encoder = self._selected_encoder()
            presets = enumerate_supported_presets_for_encoder(encoder) if encoder else []
            if not presets:
                presets = ["medium"]
            self.preset_values = list(presets)
            self.preset_combo["values"] = presets
            if presets:
                self.preset_combo.current(min(max(0, len(presets) // 2), len(presets) - 1))
                self.selected_preset_var.set(self.preset_combo.get())

        def _selected_preset(self) -> str:
            value = self.preset_combo.get().strip()
            if value:
                return value
            return self.preset_values[0] if self.preset_values else "medium"

        def _start_run(self) -> None:
            if self.running:
                return
            mode = self.mode_var.get().strip()
            if mode == "Single" and not self._selected_encoder():
                messagebox.showerror("No encoder", "No available encoder was detected in your FFmpeg build.")
                return
            self.cancel_event.clear()
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

            self.worker_thread = threading.Thread(target=self._run_worker, args=(run_args, mode), daemon=True)
            self.worker_thread.start()

        def _run_worker(self, run_args: argparse.Namespace, mode: str) -> None:
            def sink(event: Dict[str, Any]) -> None:
                self.event_queue.put(("event", event))

            rc = 1
            try:
                if mode == "Single":
                    encoder = self._selected_encoder()
                    preset = self._selected_preset()
                    crf = int(self.crf_var.get())
                    effective_args = client_main.build_single_effective_args(
                        base_args=run_args,
                        encoder=encoder,
                        preset=preset,
                        crf=crf,
                    )
                    rc = client_main.run_with_args(
                        effective_args,
                        event_sink=sink,
                        cancel_event=self.cancel_event,
                        show_end_screen=False,
                    )
                else:
                    mode_key = mode.lower()
                    rc = client_main.run_batch_mode(
                        mode=mode_key,
                        base_args=run_args,
                        event_sink=sink,
                        cancel_event=self.cancel_event,
                        show_end_screen=False,
                    )
            except Exception as e:
                self.event_queue.put(("error", f"{e}\n{traceback.format_exc()}"))
                rc = 1
            finally:
                self.event_queue.put(("done", rc))

        def _stop_run(self) -> None:
            if not self.running:
                return
            self.cancel_event.set()
            self.summary_var.set("Stopping after current step...")
            self._append_log("Cancellation requested")

        def _handle_event(self, event: Dict[str, Any]) -> None:
            event_type = str(event.get("type") or "")
            if not event_type:
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
                self._append_log(f"Submit result: {event.get('status')} ({event.get('preset') or event.get('codec')})")
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

            if event_type == "run_interrupted":
                self.stage_var.set("Interrupted")
                self.summary_var.set("Run interrupted")
                self._append_log("Run interrupted")
                return

            if event_type == "run_error":
                self.stage_var.set("Error")
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
                        self.summary_var.set("Run failed. See event log.")
                        self._append_log(payload)
                    elif kind == "done":
                        self._set_running(False)
                        rc = int(payload)
                        if rc == 0:
                            self.summary_var.set("Run finished successfully")
                        elif rc == 130:
                            self.summary_var.set("Run cancelled")
                        else:
                            self.summary_var.set(f"Run failed (exit code {rc})")
                        self._update_single_fields_state()
            except queue.Empty:
                pass
            self.root.after(120, self._poll_events)

        def _on_close(self) -> None:
            if self.running:
                if not messagebox.askyesno("Exit", "A benchmark run is still active. Stop and exit?"):
                    return
                self.cancel_event.set()
            self.root.destroy()

        def run(self) -> int:
            self.root.mainloop()
            return 0

    app = WindowsClientApp()
    return app.run()
