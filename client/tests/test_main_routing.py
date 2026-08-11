import tempfile
import unittest
from unittest import mock

from client import main as client_main


class MainRoutingTests(unittest.TestCase):
    def test_direct_cli_intent_routes_to_run_with_args(self) -> None:
        with tempfile.TemporaryDirectory() as queue_dir:
            argv = [
                "prog",
                "--codec",
                "libx264",
                "--presets",
                "fast",
                "--no-submit",
                "--queue-dir",
                queue_dir,
            ]
            with mock.patch.object(client_main, "run_with_args", return_value=17) as run_mock, \
                    mock.patch.object(client_main, "interactive_menu_flow", return_value=99) as menu_mock, \
                    mock.patch.object(client_main, "run_windows_gui_flow", return_value=88) as gui_mock:
                rc = client_main.main(argv)

        self.assertEqual(rc, 17)
        run_mock.assert_called_once()
        menu_mock.assert_not_called()
        gui_mock.assert_not_called()

    def test_menu_flag_overrides_direct_cli_intent(self) -> None:
        with tempfile.TemporaryDirectory() as queue_dir:
            argv = [
                "prog",
                "--menu",
                "--codec",
                "libx264",
                "--queue-dir",
                queue_dir,
            ]
            with mock.patch.object(client_main, "run_with_args", return_value=17) as run_mock, \
                    mock.patch.object(client_main, "interactive_menu_flow", return_value=23) as menu_mock:
                rc = client_main.main(argv)

        self.assertEqual(rc, 23)
        menu_mock.assert_called_once()
        run_mock.assert_not_called()

    def test_run_with_args_rejects_unusable_hardware_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as queue_dir:
            args = client_main.argparse.Namespace(
                base_url="https://example.invalid",
                api_key="",
                codec="h264_nvenc",
                presets="fast",
                no_submit=True,
                crf=24,
                retries=1,
                queue_dir=queue_dir,
                menu=False,
                batch_size=0,
                use_token=False,
                pause_on_exit=False,
            )
            with mock.patch.object(client_main, "ensure_ffmpeg_and_ffprobe", return_value=(True, "ffmpeg version n7")), \
                    mock.patch.object(client_main, "has_libvmaf", return_value=True), \
                    mock.patch.object(client_main, "get_default_sample_path", return_value="sample.mp4"), \
                    mock.patch.object(client_main, "verify_sample_video", return_value=(True, "ok")), \
                    mock.patch.object(client_main, "has_encoder", return_value=True), \
                    mock.patch.object(client_main, "is_hardware_encoder_usable", return_value=False), \
                    mock.patch.object(client_main, "run_single_benchmark") as bench_mock:
                rc = client_main.run_with_args(args)

        self.assertEqual(rc, 4)
        bench_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
