import os
import unittest
from unittest import mock

from client import config


class ConfigPathTests(unittest.TestCase):
    def test_default_queue_dir_uses_linux_state_home(self) -> None:
        with mock.patch.object(config.platform, "system", return_value="Linux"), \
                mock.patch.dict(os.environ, {"XDG_STATE_HOME": "/tmp/xdg-state"}, clear=False), \
                mock.patch("os.path.expanduser", return_value="/tmp/home"):
            self.assertEqual(
                config.default_queue_dir(),
                "/tmp/xdg-state/EncodingDB/queue",
            )

    def test_default_queue_dir_uses_macos_application_support(self) -> None:
        with mock.patch.object(config.platform, "system", return_value="Darwin"), \
                mock.patch("os.path.expanduser", return_value="/Users/tester"):
            self.assertEqual(
                config.default_queue_dir(),
                "/Users/tester/Library/Application Support/EncodingDB/queue",
            )


if __name__ == "__main__":
    unittest.main()
