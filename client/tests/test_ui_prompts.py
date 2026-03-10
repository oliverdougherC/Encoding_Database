import unittest
from unittest import mock

from client import ui


class PromptEofHandlingTests(unittest.TestCase):
    def test_prompt_yes_no_uses_default_on_eof(self) -> None:
        with mock.patch.object(ui, "_rich_tty", return_value=False), \
                mock.patch("builtins.input", side_effect=EOFError):
            self.assertFalse(ui.prompt_yes_no("Proceed?", default_no=True))
            self.assertTrue(ui.prompt_yes_no("Proceed?", default_no=False))

    def test_prompt_choice_returns_default_on_eof(self) -> None:
        with mock.patch.object(ui, "_rich_tty", return_value=False), \
                mock.patch("builtins.input", side_effect=EOFError):
            idx = ui.prompt_choice("Pick one", ["a", "b", "c"], default_index=1)
        self.assertEqual(idx, 1)

    def test_prompt_text_returns_default_on_eof(self) -> None:
        with mock.patch.object(ui, "_rich_tty", return_value=False), \
                mock.patch("builtins.input", side_effect=EOFError):
            value = ui.prompt_text("Enter value", "default")
        self.assertEqual(value, "default")

    def test_confirm_readiness_returns_false_on_eof(self) -> None:
        with mock.patch.object(ui, "_rich_tty", return_value=False), \
                mock.patch("builtins.input", side_effect=EOFError):
            ready = ui.confirm_benchmark_readiness()
        self.assertFalse(ready)


if __name__ == "__main__":
    unittest.main()
