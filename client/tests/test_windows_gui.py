"""GUI initialization/keyboard regressions; real Windows screenshots remain CI evidence."""
import argparse
import sys
import unittest
from unittest import mock

from client import windows_gui as gui


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
            app = bindings["<Alt-r>"].__self__
            self.assertEqual((app._selected_encoder(), app._selected_preset(), app.crf_var.get()), ("libx264", "fast", 0))
            app._handle_event({"type": "preparation_progress", "stage": "probe", "path": "test.mkv"})
            self.assertEqual(app.stage_var.get(), "Preparing: probe")
            self.assertIn("Stop is available", app.summary_var.get())
            self.assertIn("Alt+R", app.start_btn.options["text"])
            self.assertIn("Alt+S", app.stop_btn.options["text"])
            root.geometry.assert_called_once_with("992x656+8+8")
            self.assertEqual(bindings["<Alt-s>"](None), "break")
            self.assertFalse(app.cancel_event.is_set())
            self.assertEqual(bindings["<Alt-r>"](None), "break")
            bindings["<Alt-r>"](None)
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
        app = bindings["<Alt-r>"].__self__
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

    def run_args(self):
        return argparse.Namespace(base_url="http://127.0.0.1:9", api_key="", no_submit=True,
                                  submit=False, crf=24, retries=3, queue_dir="test-only",
                                  batch_size=0, use_token=False, max_duration_minutes=60,
                                  max_attempts=100, max_storage_mb=2048, pause_on_exit=False)


if __name__ == "__main__":
    unittest.main()
