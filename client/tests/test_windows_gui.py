"""GUI initialization/keyboard regressions; real Windows screenshots remain CI evidence."""
import argparse
import sys
import unittest
from unittest import mock

from client import windows_gui as gui


class FakeThread:
    """Records started targets; start() marks alive without racing the test body."""

    def __init__(self, *, target=None, args=(), daemon=None):
        self.target = target
        self.args = args
        self.daemon = daemon
        self._alive = False

    def start(self):
        self._alive = True

    def is_alive(self):
        return self._alive

    def finish(self):
        self._alive = False


class Variable:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def cached_estimate(_mode):
    return {"strategy": "cache", "storageOk": True, "bytesToTransfer": 0,
            "peakStorageBytes": 0, "warnings": []}


def cached_recovery_state(_queue=None):
    return {"publicationConsent": False, "campaigns": [],
            "publication": {"pendingEntries": 0, "dueEntries": 0,
                            "acceptedReceipts": 0, "terminalEntries": 0}}


class Widget:
    def __init__(self, *args, **kwargs):
        self.variable = kwargs.get("textvariable")
        self.values = kwargs.get("values", [])
        self.index = -1
        self.options = kwargs
        self.visible = False

    def __setitem__(self, key, value):
        if key == "values":
            self.values = value

    def current(self, index=None):
        if index is not None:
            self.index = index
            self.variable.set(self.values[index])
        return self.index

    def get(self):
        return self.variable.get()

    def configure(self, **kwargs):
        self.options.update(kwargs)

    def pack(self, **kwargs):
        self.visible = True

    def pack_forget(self):
        self.visible = False

    def grid(self, **kwargs):
        pass

    def bind(self, *args):
        pass

    def insert(self, *args):
        pass

    def see(self, *args):
        pass


class WindowsGuiTests(unittest.TestCase):
    def args(self, **kwargs):
        return argparse.Namespace(**{"codec": "libx264", "presets": "fast,slow", "crf": 0, "no_submit": True, "queue_dir": "test-only", "base_url": "http://127.0.0.1:9", **kwargs})

    def test_exact_native_choices_and_zero_are_preserved(self):
        self.assertEqual(gui.initial_gui_settings(self.args(), ["libx265", "libx264"]), ("libx264", "fast", 0))
        self.assertEqual(gui.initial_gui_settings(self.args(presets=" slow,fast ", crf=None), ["libx264"]), ("libx264", "slow", 24))
        with mock.patch.object(gui, "pick_software_encoder_for_family", return_value="libx264"):
            self.assertEqual(gui.initial_gui_settings(self.args(codec="h264"), ["libx264"])[0], "libx264")

    def test_unavailable_exact_encoder_and_preset_never_substitute(self):
        for overrides in ({"codec": "h264_nvenc"}, {"presets": "not-a-preset,fast"}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                gui.initial_gui_settings(self.args(**overrides), ["libx264"])
        with self.assertRaises(ValueError):
            gui.initial_gui_settings(self.args(), [])

    def test_geometry_reserves_work_area_chrome_and_taskbar(self):
        width, height, left, top = gui.initial_window_geometry((0, 0, 1024, 720))
        self.assertEqual((width, height, left, top), (992, 656, 8, 8))
        self.assertLessEqual(width + left + 16, 1024)
        self.assertLessEqual(height + top + 40, 720)
        self.assertEqual(gui.initial_window_geometry((0, 0, 1920, 1040))[:2], (1100, 760))

    def test_initialized_controls_and_keyboard_handlers_use_real_running_guards(self):
        root = mock.MagicMock()
        bindings = {}
        root.bind.side_effect = lambda key, callback: bindings.__setitem__(key, callback)
        tk = mock.MagicMock()
        tk.Tk.return_value = root
        tk.StringVar = tk.IntVar = tk.BooleanVar = Variable
        for name in ("Frame", "LabelFrame", "Label", "Combobox", "Checkbutton", "Spinbox", "Entry", "Button", "Progressbar"):
            setattr(tk.ttk, name, Widget)
        tk.scrolledtext.ScrolledText = Widget
        with mock.patch.dict(sys.modules, {"tkinter": tk}), mock.patch.object(gui.os, "name", "nt"), \
             mock.patch.object(gui, "list_all_available_encoders", return_value=["libx265", "libx264"]), \
             mock.patch.object(gui, "desktop_work_area", return_value=(0, 0, 1024, 720)), \
             mock.patch.object(gui.client_main, "recovery_state", side_effect=cached_recovery_state), \
             mock.patch.object(gui.threading, "Thread") as thread:
            self.assertEqual(gui.launch_windows_gui(self.args()), 0)
            app = bindings["<Alt-b>"].__self__
            app._estimate_acquisition = cached_estimate
            app._load_recovery_state = cached_recovery_state
            self.assertEqual((app._selected_encoder(), app._selected_preset(), app.crf_var.get()), ("libx264", "fast", 0))
            app._handle_event({"type": "preparation_progress", "stage": "probe", "path": "test.mkv"})
            self.assertEqual(app.stage_var.get(), "Preparing: probe")
            app._handle_event({"type": "preparation_progress", "stage": "source-contract",
                               "clipId": "talking-head-1080p24-final", "completed": 3, "total": 7})
            self.assertEqual(app.stage_var.get(), "Preparing: source-contract")
            self.assertIn("(3/7)", app.summary_var.get())
            self.assertIn("talking-head-1080p24-final", app.summary_var.get())
            self.assertIn("Stop is available", app.summary_var.get())
            app._handle_event({"type": "preparation_progress", "stage": "recovery",
                               "path": "recovered", "message": "installed a fully verified copy"})
            self.assertIn("Suite cache recovery active", app.summary_var.get())
            self.assertNotEqual(app.stage_var.get(), "Preparing: probe")
            self.assertIn("Alt+B", app.start_btn.options["text"])
            self.assertNotIn("<Alt-r>", bindings)
            self.assertIn("Alt+S", app.stop_btn.options["text"])
            root.geometry.assert_called_once_with("992x656+8+8")
            self.assertEqual(bindings["<Alt-s>"](None), "break")
            self.assertFalse(app.cancel_event.is_set())
            self.assertEqual(bindings["<Alt-b>"](None), "break")
            bindings["<Alt-b>"](None)
            self.assertEqual(thread.call_count, 1)
            self.assertTrue(app.running)
            self.assertEqual(app.start_btn.options["state"], "disabled")
            bindings["<Alt-s>"](None)
            self.assertTrue(app.cancel_event.is_set())
            self.assertEqual(app.summary_var.get(), "Stopping owned work; retaining saved results...")

    def _build_app(self, mode: str = "Small"):
        """Instantiate the Tk app against the mocked widget harness."""
        root = mock.MagicMock()
        bindings = {}
        root.bind.side_effect = lambda key, callback: bindings.__setitem__(key, callback)
        tk = mock.MagicMock()
        tk.Tk.return_value = root
        tk.StringVar = tk.IntVar = tk.BooleanVar = Variable
        for name in ("Frame", "LabelFrame", "Label", "Combobox", "Checkbutton", "Spinbox",
                     "Entry", "Button", "Progressbar"):
            setattr(tk.ttk, name, Widget)
        tk.scrolledtext.ScrolledText = Widget
        with mock.patch.dict(sys.modules, {"tkinter": tk}), mock.patch.object(gui.os, "name", "nt"), \
             mock.patch.object(gui, "list_all_available_encoders",
                               return_value=["libx264", "h264_videotoolbox"]), \
             mock.patch.object(gui, "desktop_work_area", return_value=(0, 0, 1024, 720)), \
             mock.patch.object(gui.client_main, "recovery_state", side_effect=cached_recovery_state), \
             mock.patch.object(gui.threading, "Thread"):
            gui.launch_windows_gui(self.args())
        app = bindings["<Alt-b>"].__self__
        app._estimate_acquisition = cached_estimate
        app._load_recovery_state = cached_recovery_state
        app.mode_var.set(mode)
        return app

    def test_mode_choices_expose_shared_sweeps_with_single_as_advanced(self):
        app = self._build_app()
        self.assertEqual(list(app.mode_combo.values), list(gui.GUI_MODE_CHOICES))
        self.assertEqual(app.mode_var.get(), "Small")
        self.assertIn("native recipes", app.summary_var.get())
        self.assertIn("quick clip", app.summary_var.get())
        self.assertFalse(app.advanced_frame.visible)
        app.mode_var.set("Full")
        app._update_single_fields_state()
        self.assertIn("all seven frozen clips", app.summary_var.get())
        app.mode_var.set("Single (advanced)")
        app._update_single_fields_state()
        self.assertTrue(app.advanced_frame.visible)
        self.assertEqual(app.encoder_combo.options["state"], "readonly")

    def test_sweep_worker_dispatches_to_shared_planner_run(self):
        app = self._build_app()
        from client import main as client_main
        with mock.patch.object(client_main, "run_sweep_mode", return_value=0) as sweep_mock, \
                mock.patch.object(client_main, "run_with_args") as single_mock:
            app._run_worker(self.run_args(), "Medium", "medium")
        sweep_mock.assert_called_once()
        self.assertEqual(sweep_mock.call_args.kwargs["mode"], "medium")
        self.assertTrue(sweep_mock.call_args.kwargs["interactive"])
        single_mock.assert_not_called()
        kind, rc = app.event_queue.get_nowait()
        self.assertEqual((kind, rc), ("done", 0))

    def test_single_worker_keeps_manual_recipe_path(self):
        app = self._build_app(mode="Single (advanced)")
        app.encoder_values = ["libx264"]
        app.preset_values = ["fast"]
        from client import main as client_main
        with mock.patch.object(client_main, "run_with_args", return_value=0) as single_mock, \
                mock.patch.object(client_main, "run_sweep_mode") as sweep_mock:
            app._run_worker(self.run_args(), "Single (advanced)", None)
        single_mock.assert_called_once()
        sweep_mock.assert_not_called()

    def test_upload_retry_never_encodes(self):
        app = self._build_app()
        from client import main as client_main

        with mock.patch.object(client_main, "count_pending_entries", side_effect=[2, 0]), \
                mock.patch.object(client_main, "retry_due_uploads",
                                  return_value=(0, {"status": "published", "pending": 0,
                                                    "deadLettered": 0, "corrupt": 0})) as replay_mock, \
                mock.patch.object(client_main, "run_sweep_mode") as sweep_mock, \
                mock.patch.object(client_main, "run_with_args") as single_mock:
            app._retry_uploads_worker("queue-dir", "https://example.invalid", "", 2)
        replay_mock.assert_called_once()
        sweep_mock.assert_not_called()
        single_mock.assert_not_called()
        kind, message = app.event_queue.get_nowait()
        self.assertEqual(kind, "upload_status")
        self.assertIn("2 pending before", message)

    def test_defaults_start_on_software_encoder_without_usable_gpu(self):
        # A hardware encoder name existing in the ffmpeg build does not mean the machine
        # has a usable GPU; the manual-recipe default must still be usable immediately.
        encoders = ["h264_videotoolbox", "hevc_videotoolbox", "libx264", "libx265"]
        encoder, preset, quality = gui.initial_gui_settings(
            argparse.Namespace(codec="", presets="", crf=None), encoders)
        self.assertEqual(encoder, "libx264")
        self.assertTrue(preset)
        self.assertEqual(quality, 24)
        # An explicitly requested codec family still resolves to its software path.
        encoder = gui.initial_gui_settings(
            argparse.Namespace(codec="h264", presets="fast", crf=20), encoders)[0]
        self.assertEqual(encoder, "libx264")
        # An explicitly requested concrete hardware encoder stays selectable.
        encoder = gui.initial_gui_settings(
            argparse.Namespace(codec="h264_videotoolbox", presets="", crf=None), encoders)[0]
        self.assertEqual(encoder, "h264_videotoolbox")

    def run_args(self):
        return argparse.Namespace(base_url="http://127.0.0.1:9", api_key="", no_submit=True,
                                  submit=False, crf=24, retries=3, queue_dir="test-only",
                                  batch_size=0, use_token=False, max_duration_minutes=60,
                                  max_attempts=100, max_storage_mb=2048, pause_on_exit=False)


class GuiLifecycleTests(unittest.TestCase):
    def args(self, **kwargs):
        return argparse.Namespace(**{
            "codec": "libx264", "presets": "fast,slow", "crf": 0, "no_submit": True,
            "queue_dir": "test-only", "base_url": "http://127.0.0.1:9",
            "api_key": "", "retries": 3, "batch_size": 0, **kwargs})

    def build(self, mode: str = "Small"):
        root = mock.MagicMock()
        bindings = {}
        afters = []
        root.bind.side_effect = lambda key, callback: bindings.__setitem__(key, callback)
        root.after.side_effect = lambda ms, cb=None: afters.append((ms, cb))
        tk = mock.MagicMock()
        tk.Tk.return_value = root
        tk.StringVar = tk.IntVar = tk.BooleanVar = Variable
        for name in ("Frame", "LabelFrame", "Label", "Combobox", "Checkbutton", "Spinbox",
                     "Entry", "Button", "Progressbar"):
            setattr(tk.ttk, name, Widget)
        tk.scrolledtext.ScrolledText = Widget
        with mock.patch.dict(sys.modules, {"tkinter": tk}), mock.patch.object(gui.os, "name", "nt"), \
             mock.patch.object(gui, "list_all_available_encoders",
                                  return_value=["libx264", "h264_videotoolbox"]), \
             mock.patch.object(gui, "desktop_work_area", return_value=(0, 0, 1024, 720)), \
             mock.patch.object(gui.client_main, "recovery_state", side_effect=cached_recovery_state):
            gui.launch_windows_gui(self.args())
        app = bindings["<Alt-b>"].__self__
        app._estimate_acquisition = cached_estimate
        app._load_recovery_state = cached_recovery_state
        app.mode_var.set(mode)
        return app, root, bindings, tk

    def states(self, app):
        return (app.start_btn.options["state"], app.stop_btn.options["state"],
                app.upload_btn.options["state"])

    def test_idle_states_then_active_benchmark_locks_retry_and_start(self):
        app, _root, bindings, _tk = self.build()
        self.assertEqual(self.states(app), ("normal", "disabled", "disabled"))
        with mock.patch.object(gui.threading, "Thread", FakeThread):
            bindings["<Alt-b>"](None)
            self.assertEqual(app.worker_thread.target.__name__, "_run_worker")
            self.assertEqual(self.states(app), ("disabled", "normal", "disabled"),
                             "Retry must be locked while a benchmark run is active")
            # A benchmark run also blocks starting a replay against the same spool.
            app._retry_uploads()
            self.assertIsNone(app.upload_thread)
        with mock.patch.object(gui.client_main, "count_pending_entries", return_value=0):
            app.event_queue.put(("done", 0))
            app._poll_events()
        self.assertFalse(app.running)
        self.assertEqual(self.states(app), ("normal", "disabled", "disabled"),
                         "Local-only policy keeps upload actions disabled after the run")

    def test_finished_run_surfaces_pending_uploads(self):
        app, _root, _bindings, _tk = self.build()
        app.no_submit_var.set(False)
        app._active_no_submit = False
        app.event_queue.put(("event", {"type": "submit_result", "status": "submitted"}))
        with mock.patch.object(gui.client_main, "count_pending_entries", return_value=2):
            app.event_queue.put(("done", 0))
            app._poll_events()
        self.assertIn("2 upload(s) queued", app.summary_var.get())
        self.assertIn("some uploads are queued", app.summary_var.get())
        self.assertEqual(app.upload_btn.options["state"], "normal")

    def test_batch_progress_counts_groups_not_maximum_encode_attempts(self):
        app, _root, _bindings, _tk = self.build()
        app._handle_event({"type": "run_start", "scope": "batch", "totalTasks": 30,
                           "totalBatches": 1})
        app._handle_event({"type": "batch_start", "batchSize": 3,
                           "totalBatches": 1, "processedTotal": 0})
        app._handle_event({"type": "task_complete", "scope": "batch", "processed": 1,
                           "total": 30})
        self.assertEqual(app.overall_total, 3)
        self.assertEqual(app.overall_pb.options["maximum"], 3)
        self.assertEqual(app.overall_pb.options["value"], 1)
        self.assertIn("1/3", app.summary_var.get())

    def test_invalid_typed_settings_leave_idle_without_worker(self):
        for field, value, mode in (
            ("retries_var", "abc", "Small"), ("retries_var", "", "Small"),
            ("retries_var", "11", "Small"), ("batch_size_var", " ", "Small"),
            ("batch_size_var", "65", "Small"), ("crf_var", "oops", "Single (advanced)"),
            ("bitrate_var", "-3", "Single (advanced)"),
        ):
            with self.subTest(field=field, value=value):
                app, _root, _bindings, tk = self.build(mode=mode)
                getattr(app, field).set(value)
                with mock.patch.object(gui.threading, "Thread", FakeThread):
                    app._start_run()
                self.assertFalse(app.running)
                self.assertIsNone(app.worker_thread)
                self.assertEqual(app.start_btn.options["state"], "normal")
                tk.messagebox.showerror.assert_called_once()

    def test_real_tcl_invalid_intvar_becomes_field_error(self):
        try:
            import tkinter as tkinter_real
            interpreter = tkinter_real.Tcl()
        except Exception as exc:
            self.skipTest(f"Tcl unavailable: {exc}")
        value = tkinter_real.IntVar(master=interpreter, value=3)
        interpreter.setvar(value._name, "abc")
        with self.assertRaises(tkinter_real.TclError):
            value.get()
        with self.assertRaisesRegex(ValueError, "Retries must be a whole number"):
            gui._validated_integer(value, "Retries", 1, 10)

    def test_local_only_run_does_not_require_a_live_server_url(self):
        app, _root, _bindings, tk = self.build()
        app.base_url_var.set("unconfigured")
        with mock.patch.object(gui.threading, "Thread", FakeThread):
            app._start_run()
        self.assertTrue(app.running)
        self.assertTrue(app.worker_thread.args[0].no_submit)
        tk.messagebox.showerror.assert_not_called()

    def test_download_cost_is_confirmed_before_worker_starts(self):
        app, _root, _bindings, tk = self.build()
        app._estimate_acquisition = lambda _mode: {
            "strategy": "pack", "storageOk": True,
            "bytesToTransfer": 1506890018, "peakStorageBytes": 3100000000,
        }
        tk.messagebox.askyesno.return_value = False
        with mock.patch.object(gui.threading, "Thread", FakeThread):
            app._start_run()
        self.assertFalse(app.running)
        self.assertIsNone(app.worker_thread)
        self.assertIn("1.4 GB", tk.messagebox.askyesno.call_args.args[1])
        self.assertIn("declined", app.summary_var.get())

    def test_storage_estimate_refuses_before_worker(self):
        app, _root, _bindings, tk = self.build()
        app._estimate_acquisition = lambda _mode: {
            "strategy": "clip", "storageOk": False,
            "bytesToTransfer": 100, "peakStorageBytes": 5000000000,
        }
        with mock.patch.object(gui.threading, "Thread", FakeThread):
            app._start_run()
        self.assertFalse(app.running)
        self.assertIsNone(app.worker_thread)
        self.assertIn("disk space", app.summary_var.get())
        tk.messagebox.showerror.assert_called_once()

    def test_acquisition_preview_uses_quick_or_complete_frozen_clip_set(self):
        manifest = gui.suite.load_default_suite_manifest()
        with mock.patch.object(gui.suite, "acquisition_estimate", return_value={}) as estimate:
            gui._acquisition_preview("small")
            quick_ids = estimate.call_args.args[0]
            gui._acquisition_preview("full")
            full_ids = estimate.call_args.args[0]
        self.assertEqual(quick_ids, [gui.suite.get_default_quick_clip(manifest).clip_id])
        self.assertEqual(set(full_ids), {clip.clip_id for clip in manifest.clips})

    def test_consent_save_and_thread_start_failures_restore_idle(self):
        app, _root, _bindings, tk = self.build()
        app.no_submit_var.set(False)
        with mock.patch.object(gui.client_main, "_ensure_interactive_publication_consent",
                               side_effect=OSError("consent storage unavailable")):
            app._start_run()
        self.assertFalse(app.running)
        self.assertIsNone(app.worker_thread)
        self.assertEqual(app.no_submit_var.get(), False)
        tk.messagebox.showerror.assert_called_once()

        app.no_submit_var.set(True)
        class FailingThread(FakeThread):
            def start(self):
                raise RuntimeError("thread unavailable")
        with mock.patch.object(gui.threading, "Thread", FailingThread):
            app._start_run()
        self.assertFalse(app.running)
        self.assertIsNone(app.worker_thread)
        self.assertEqual(app.stage_var.get(), "Idle")
        self.assertEqual(app.start_btn.options["state"], "normal")

        app.base_args.max_duration_minutes_explicit = True
        app.base_args.max_duration_minutes = "invalid"
        with mock.patch.object(gui.threading, "Thread", FakeThread):
            app._start_run()
        self.assertFalse(app.running)
        self.assertIsNone(app.worker_thread)
        self.assertEqual(app.start_btn.options["state"], "normal")

    def test_single_worker_uses_snapshot_even_if_widgets_change(self):
        app, _root, _bindings, _tk = self.build(mode="Single (advanced)")
        app._update_single_fields_state()
        app.crf_var.set(19)
        with mock.patch.object(gui.threading, "Thread", FakeThread):
            app._start_run()
        self.assertEqual(app.no_submit_check.options["state"], "disabled")
        app.crf_var.set("broken later")
        app.no_submit_var.set(False)
        with mock.patch.object(gui.client_main, "run_with_args", return_value=0) as run:
            app.worker_thread.target(*app.worker_thread.args)
        args = run.call_args.args[0]
        self.assertEqual(args.crf, 19)
        self.assertTrue(args.no_submit)
        app._poll_events()
        self.assertIn("Saved locally", app.summary_var.get())

    def test_local_completion_reports_saved_groups_without_upload_claim(self):
        app, _root, _bindings, _tk = self.build()
        app._active_no_submit = True
        app.event_queue.put(("event", {"type": "submit_result", "status": "locally_complete"}))
        app.event_queue.put(("event", {"type": "submit_result", "status": "locally_complete"}))
        app.event_queue.put(("done", 0))
        app._poll_events()
        self.assertIn("2 measurement group(s) locally", app.summary_var.get())
        self.assertNotIn("Uploaded", app.summary_var.get())

    def test_saved_work_is_visible_and_publish_uses_zero_encode_api(self):
        app, _root, _bindings, _tk = self.build()
        state = cached_recovery_state()
        state["publicationConsent"] = True
        state["publication"] = {"pendingEntries": 2, "dueEntries": 1,
                                "acceptedReceipts": 3, "terminalEntries": 1}
        state["campaigns"] = [{"campaignId": "campaign-test", "complete": True,
                               "pendingUploads": 2, "unavailableSources": 0,
                               "actions": [{"action": "publish_saved"}]}]
        app._load_recovery_state = lambda: state
        app._refresh_saved_work()
        app.no_submit_var.set(False)
        app._refresh_controls()
        self.assertIn("1 due / 1 delayed", app.saved_summary_var.get())
        self.assertIn("terminal", app.saved_summary_var.get())
        self.assertEqual(app._selected_saved_campaign(), "campaign-test")
        self.assertEqual(app.publish_btn.options["state"], "normal")
        with mock.patch.object(app, "_confirm_publication_consent", return_value=True), \
                mock.patch.object(gui.threading, "Thread", FakeThread):
            app._publish_saved()
        self.assertEqual(app.publish_btn.options["state"], "disabled")
        with mock.patch.object(gui.client_main, "publish_saved_campaign",
                               return_value=(0, {"submitted": 2, "pending": 0})) as publish, \
                mock.patch.object(gui.client_main, "run_with_args") as encode:
            app.upload_thread.target(*app.upload_thread.args)
        publish.assert_called_once()
        self.assertEqual(publish.call_args.kwargs["campaign_id"], "campaign-test")
        encode.assert_not_called()
        self.assertIn("analysis pending", app.event_queue.get_nowait()[1])
        self.assertIn("1 not yet staged", app._publication_result_text(
            10, {"pending": 0, "unadmitted": 1, "deferredReason": "storage_or_exclusion"}))

    def test_resume_selected_campaign_keeps_its_identity(self):
        app, _root, _bindings, _tk = self.build()
        state = cached_recovery_state()
        state["campaigns"] = [{"campaignId": "campaign-saved", "complete": False,
                               "pendingUploads": 0, "unavailableSources": 0,
                               "actions": [{"action": "resume"}]}]
        app._load_recovery_state = lambda: state
        app._refresh_saved_work()
        with mock.patch.object(app, "_start_run") as start:
            app._resume_saved()
        start.assert_called_once_with(resume_id="campaign-saved")
        args = self.args(resume_campaign="campaign-saved")
        with mock.patch.object(gui.client_main, "_resume_campaign", return_value=0) as resume, \
                mock.patch.object(gui.client_main, "run_with_args") as new_run:
            app._run_worker(args, "Small", "small")
        resume.assert_called_once()
        self.assertEqual(resume.call_args.args[0].resume_campaign, "campaign-saved")
        new_run.assert_not_called()

    def test_idle_retry_requires_due_work_and_saved_consent(self):
        app, _root, _bindings, _tk = self.build()
        state = cached_recovery_state()
        state["publicationConsent"] = True
        state["publication"]["pendingEntries"] = 2
        state["publication"]["dueEntries"] = 1
        app._load_recovery_state = lambda: state
        app.no_submit_var.set(False)
        with mock.patch.object(app, "_retry_uploads") as retry:
            app._idle_retry()
        retry.assert_called_once_with(automatic=True)
        state["publicationConsent"] = False
        with mock.patch.object(app, "_retry_uploads") as retry:
            app._idle_retry()
        retry.assert_not_called()
        state["publicationConsent"] = True
        app.no_submit_var.set(True)
        with mock.patch.object(app, "_retry_uploads") as retry:
            app._idle_retry()
        retry.assert_not_called()

    def test_stop_cancels_active_upload_replay(self):
        app, _root, _bindings, _tk = self.build()
        app.upload_thread = FakeThread()
        app.upload_thread.start()
        app._refresh_controls()
        self.assertEqual(app.stop_btn.options["state"], "normal")
        app._stop_run()
        self.assertTrue(app.upload_cancel_event.is_set())

    def test_active_replay_blocks_benchmark_start_and_restores_on_status(self):
        app, _root, _bindings, _tk = self.build()
        app.no_submit_var.set(False)
        with mock.patch.object(gui.threading, "Thread", FakeThread), \
                mock.patch.object(app, "_confirm_publication_consent", return_value=True), \
                mock.patch.object(gui.client_main, "count_pending_entries", return_value=3), \
                mock.patch.object(gui.client_main, "replay_spool"):
            app._retry_uploads()
            self.assertIsNotNone(app.upload_thread)
            self.assertEqual(self.states(app), ("disabled", "normal", "disabled"))
            app._start_run()
            self.assertIsNone(app.worker_thread, "benchmark must not race a live replay")
            # A second click while replaying must not spawn another uploader.
            first = app.upload_thread
            app._retry_uploads()
            self.assertIs(app.upload_thread, first)
        # Simulate the worker's queued result and poll it on the main thread.
        app.upload_thread.finish()
        app.event_queue.put(("upload_status", "Upload retry: 3 pending before, 0 still pending, "
                                              "dead-lettered=0, corrupt=0."))
        app._poll_events()
        self.assertIsNone(app.upload_thread)
        self.assertEqual(self.states(app), ("normal", "disabled", "normal"))
        self.assertIn("3 pending before", app.summary_var.get())

    def test_close_during_replay_waits_then_closes_bounded(self):
        app, root, _bindings, tk = self.build()
        app.no_submit_var.set(False)
        tk.messagebox.askyesno.return_value = True
        with mock.patch.object(gui.threading, "Thread", FakeThread), \
                mock.patch.object(app, "_confirm_publication_consent", return_value=True), \
                mock.patch.object(gui.client_main, "count_pending_entries", return_value=1), \
                mock.patch.object(gui.client_main, "replay_spool"):
            app._retry_uploads()
        uploader = app.upload_thread
        app._on_close()
        self.assertTrue(app.upload_cancel_event.is_set())
        root.destroy.assert_not_called()
        app._close_when_stopped()
        root.destroy.assert_not_called()
        # A slow request must not outlive an apparently closed application.
        app._close_deadline = gui.time.monotonic() - 1
        log_lines = []
        with mock.patch.object(app, "_append_log", log_lines.append):
            app._close_when_stopped()
        root.destroy.assert_not_called()
        self.assertIn("Waiting for the current operation", app.summary_var.get())
        self.assertTrue(uploader.is_alive(), "uploader object unaffected by close bookkeeping")
        # Declining the confirmation leaves the window open.
        root.reset_mock()
        tk.messagebox.askyesno.return_value = False
        app._on_close()
        root.destroy.assert_not_called()
        uploader.finish()
        app._close_when_stopped()
        root.destroy.assert_called_once()

    def test_retry_exception_surfaces_and_restores_controls(self):
        app, _root, _bindings, _tk = self.build()
        app.no_submit_var.set(False)
        with mock.patch.object(gui.client_main, "count_pending_entries", side_effect=OSError("disk gone")):
            app._retry_uploads_worker("queue-dir", "http://127.0.0.1:9", "", 2)
        app.upload_thread = FakeThread()
        app._poll_events()
        self.assertIn("Upload retry failed: disk gone", app.summary_var.get())
        self.assertIsNone(app.upload_thread)
        self.assertEqual(app.upload_btn.options["state"], "normal")

    def test_upload_status_does_not_release_a_still_running_worker(self):
        app, _root, _bindings, _tk = self.build()
        app.no_submit_var.set(False)
        with mock.patch.object(gui.threading, "Thread", FakeThread), \
                mock.patch.object(app, "_confirm_publication_consent", return_value=True):
            app._retry_uploads()
        uploader = app.upload_thread
        app.event_queue.put(("upload_status", "Upload complete"))
        app._poll_events()
        self.assertIs(app.upload_thread, uploader)
        self.assertEqual(app.start_btn.options["state"], "disabled")
        self.assertEqual(app.upload_btn.options["state"], "disabled")
        uploader.finish()
        app._poll_events()
        self.assertIsNone(app.upload_thread)
        self.assertEqual(app.start_btn.options["state"], "normal")

    def test_submit_result_events_get_browse_link_not_fake_run_url(self):
        app, _root, _bindings, _tk = self.build()
        lines = []
        with mock.patch.object(app, "_append_log", lines.append):
            app._handle_event({"type": "submit_result", "index": 1, "total": 2,
                               "status": "submitted", "preset": "fast"})
            app._handle_event({"type": "submit_result", "index": 2, "total": 2,
                               "status": "submitted", "preset": "slow"})
            app._handle_event({"type": "submit_result", "index": 1, "total": 1,
                               "status": "queued", "preset": "fast", "error": "offline"})
        self.assertIn("browse all results: http://127.0.0.1:9/", lines[0])
        self.assertNotIn("/results/", " ".join(lines))
        self.assertNotIn("browse", lines[1], "browse hint appears once per run")
        self.assertNotIn("browse", lines[2], "queued is not a browsable success claim")

    def test_submission_failure_shows_safe_cause_and_run_id(self):
        app, _root, _bindings, _tk = self.build()
        app._active_no_submit = False
        app._handle_event({"type": "submit_result", "status": "failed",
                           "errorCategory": "protocol_rejected", "safeReason": "Suite identity differs",
                           "recoveryAction": "Update the client", "reasonCodes": ["SUITE_MISMATCH"],
                           "benchmarkRunId": "run-123", "error": "token=SECRET"})
        self.assertIn("Suite identity differs", app.summary_var.get())
        self.assertIn("Update the client", app.summary_var.get())
        self.assertIn("run-123", app.summary_var.get())
        self.assertNotIn("SECRET", app.summary_var.get())
        app.event_queue.put(("done", 1))
        app._poll_events()
        self.assertIn("Suite identity differs", app.summary_var.get())

    def test_explicit_allowance_reported_when_set(self):
        app, _root, bindings, _tk = self.build()
        log_lines = []
        app.base_args.max_duration_minutes = 15.0
        app.base_args.max_duration_minutes_explicit = True
        with mock.patch.object(gui.threading, "Thread", FakeThread), \
                mock.patch.object(app, "_append_log", log_lines.append):
            bindings["<Alt-b>"](None)
        self.assertIn("Explicit measurement allowance: 15 minutes", " ".join(log_lines))

    def test_run_error_cause_survives_done_and_persists_in_log(self):
        app, _root, _bindings, _tk = self.build()
        lines = []
        with mock.patch.object(app, "_append_log", lines.append):
            app._handle_event({"type": "run_error", "scope": "preparation", "code": 3,
                               "message": "EncodingDB Test Suite v1 is unavailable: download blocked"})
            app.event_queue.put(("done", 3))
            app._poll_events()
        self.assertIn("Run failed (exit code 3)", app.summary_var.get())
        self.assertIn("download blocked", app.summary_var.get())
        self.assertIn("Run failed (exit code 3): EncodingDB Test Suite v1 is unavailable: download blocked",
                      " ".join(lines))

    def test_generic_failure_done_appends_actionable_log_line(self):
        app, _root, _bindings, _tk = self.build()
        lines = []
        with mock.patch.object(app, "_append_log", lines.append):
            app.event_queue.put(("done", 6))
            app._poll_events()
        self.assertIn("exit code 6", app.summary_var.get())
        self.assertIn("event log", app.summary_var.get())
        self.assertTrue(any("exit code 6" in line for line in lines))

    def test_start_clears_previous_failure_cause(self):
        app, _root, bindings, _tk = self.build()
        app.last_failure = "stale cause from a previous run"
        with mock.patch.object(gui.threading, "Thread", FakeThread):
            bindings["<Alt-b>"](None)
        self.assertIsNone(app.last_failure)


if __name__ == "__main__":
    unittest.main()
