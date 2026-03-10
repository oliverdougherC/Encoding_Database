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


if __name__ == "__main__":
    unittest.main()
