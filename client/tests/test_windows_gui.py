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


class Widget:
    def __init__(self, *args, **kwargs):
        self.variable = kwargs.get("textvariable")
        self.values = kwargs.get("values", [])
        self.index = -1
        self.options = kwargs

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
        pass

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
             mock.patch.object(gui.threading, "Thread") as thread:
            self.assertEqual(gui.launch_windows_gui(self.args()), 0)
            app = bindings["<Alt-b>"].__self__
            self.assertEqual((app._selected_encoder(), app._selected_preset(), app.crf_var.get()), ("libx264", "fast", 0))
            app._handle_event({"type": "preparation_progress", "stage": "probe", "path": "test.mkv"})
            self.assertEqual(app.stage_var.get(), "Preparing: probe")
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
            self.assertEqual(app.summary_var.get(), "Stopping owned work; retaining downloads and campaign...")

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
             mock.patch.object(gui.threading, "Thread"):
            gui.launch_windows_gui(self.args())
        app = bindings["<Alt-b>"].__self__
        app.mode_var.set(mode)
        return app

    def test_mode_choices_expose_shared_sweeps_with_single_as_advanced(self):
        app = self._build_app()
        self.assertEqual(list(app.mode_combo.values), list(gui.GUI_MODE_CHOICES))
        self.assertEqual(app.mode_var.get(), "Small")
        self.assertIn("native recipes", app.summary_var.get())
        self.assertIn("quick clip", app.summary_var.get())
        app.mode_var.set("Full")
        app._update_single_fields_state()
        self.assertIn("all seven frozen clips", app.summary_var.get())
        app.mode_var.set("Single (advanced)")
        app._update_single_fields_state()
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
                mock.patch.object(client_main, "replay_spool",
                                  return_value=mock.Mock(dead_lettered=0, corrupt=0)) as replay_mock, \
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
                mock.patch.object(gui, "desktop_work_area", return_value=(0, 0, 1024, 720)):
            gui.launch_windows_gui(self.args())
        app = bindings["<Alt-b>"].__self__
        app.mode_var.set(mode)
        return app, root, bindings, tk

    def states(self, app):
        return (app.start_btn.options["state"], app.stop_btn.options["state"],
                app.upload_btn.options["state"])

    def test_idle_states_then_active_benchmark_locks_retry_and_start(self):
        app, _root, bindings, _tk = self.build()
        self.assertEqual(self.states(app), ("normal", "disabled", "normal"))
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
        self.assertEqual(self.states(app), ("normal", "disabled", "normal"),
                         "Retry must be available again after the run finishes")

    def test_finished_run_surfaces_pending_uploads(self):
        app, _root, _bindings, _tk = self.build()
        app.no_submit_var.set(False)
        with mock.patch.object(gui.client_main, "count_pending_entries", return_value=2):
            app.event_queue.put(("done", 0))
            app._poll_events()
        self.assertIn("2 upload(s) queued", app.summary_var.get())
        self.assertIn("Uploaded; analysis pending", app.summary_var.get())
        self.assertEqual(app.upload_btn.options["state"], "normal")

    def test_active_replay_blocks_benchmark_start_and_restores_on_status(self):
        app, _root, _bindings, _tk = self.build()
        with mock.patch.object(gui.threading, "Thread", FakeThread), \
                mock.patch.object(gui.client_main, "count_pending_entries", return_value=3), \
                mock.patch.object(gui.client_main, "replay_spool"):
            app._retry_uploads()
            self.assertIsNotNone(app.upload_thread)
            self.assertEqual(self.states(app), ("disabled", "disabled", "disabled"))
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
        tk.messagebox.askyesno.return_value = True
        with mock.patch.object(gui.threading, "Thread", FakeThread), \
                mock.patch.object(gui.client_main, "count_pending_entries", return_value=1), \
                mock.patch.object(gui.client_main, "replay_spool"):
            app._retry_uploads()
        uploader = app.upload_thread
        app._on_close()
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
        with mock.patch.object(gui.client_main, "count_pending_entries", side_effect=OSError("disk gone")):
            app._retry_uploads_worker("queue-dir", "http://127.0.0.1:9", "", 2)
        app.upload_thread = FakeThread()
        app._poll_events()
        self.assertIn("Upload retry failed: disk gone", app.summary_var.get())
        self.assertIsNone(app.upload_thread)
        self.assertEqual(app.upload_btn.options["state"], "normal")

    def test_upload_status_does_not_release_a_still_running_worker(self):
        app, _root, _bindings, _tk = self.build()
        with mock.patch.object(gui.threading, "Thread", FakeThread):
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

    def test_explicit_allowance_reported_when_set(self):
        app, _root, bindings, _tk = self.build()
        log_lines = []
        app.base_args.max_duration_minutes = 15.0
        app.base_args.explicit_max_duration_minutes = True
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
