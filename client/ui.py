import os
import re
import shutil
import subprocess
import sys
from typing import List

from . import config


def prompt_yes_no(prompt: str, default_no: bool = True) -> bool:
    try:
        if sys.stdin and sys.stdin.isatty():
            subprocess.run(["stty", "sane"], check=False)
    except Exception:
        pass
    suffix = " [y/N]: " if default_no else " [Y/n]: "
    ans = input(prompt + suffix).strip().lower()
    if not ans:
        return not default_no
    return ans in ("y", "yes")


def prompt_choice(prompt: str, options: List[str], default_index: int = 0) -> int:
    try:
        if sys.stdin and sys.stdin.isatty():
            subprocess.run(["stty", "sane"], check=False)
    except Exception:
        pass
    for i, opt in enumerate(options, start=1):
        print(f"  {i}) {opt}")
    raw = input(f"{prompt} (1-{len(options)}) [default {default_index+1}]: ").strip()
    if not raw:
        return default_index
    try:
        idx = int(raw)
        if 1 <= idx <= len(options):
            return idx - 1
    except Exception:
        pass
    return default_index


def prompt_text(prompt: str, default_value: str = "") -> str:
    try:
        if sys.stdin and sys.stdin.isatty():
            subprocess.run(["stty", "sane"], check=False)
    except Exception:
        pass
    raw = input(f"{prompt} [{default_value}]: ").strip()
    return raw or default_value


def _clear_screen() -> None:
    try:
        os.system("cls" if os.name == "nt" else "clear")
    except Exception:
        pass


def ensure_min_terminal_size(min_cols: int = 100, min_rows: int = 30) -> None:
    """Best-effort to resize terminal to avoid misaligned boxes."""
    try:
        cols, rows = shutil.get_terminal_size((80, 24))
    except Exception:
        cols, rows = (80, 24)
    try:
        if os.name == "nt":
            os.system(f"mode con: cols={max(cols, min_cols)} lines={max(rows, min_rows)}")
        else:
            sys.stdout.write(f"\033[8;{max(rows, min_rows)};{max(cols, min_cols)}t")
            sys.stdout.flush()
    except Exception:
        pass


def confirm_benchmark_readiness() -> bool:
    _clear_screen()
    try:
        width = max(60, min(shutil.get_terminal_size((100, 20)).columns, 100))
    except Exception:
        width = 80
    border = "\u2550" * (width - 2)
    top = f"\u2554{border}\u2557"
    bottom = f"\u255a{border}\u255d"
    RED = "\033[31;1m"
    RED_BG = "\033[41;97;1m"
    RESET = "\033[0m"
    ansi_re = re.compile(r"\x1b\[[0-9;]*m")

    def _display_len(s: str) -> int:
        try:
            return len(ansi_re.sub("", s))
        except Exception:
            return len(s)

    def center_line(text: str) -> str:
        t = text.strip()
        pad = max(0, width - 2 - _display_len(t))
        left = pad // 2
        right = pad - left
        return f"\u2551{' ' * left}{t}{' ' * right}\u2551"

    print(top)
    print(center_line(f"{RED_BG} Warning! {RESET}"))
    print(center_line(""))
    lines = [
        f"{RED}Please close all programs that may be stealing CPU resources or using your media engine{RESET}",
        f"{RED}(ie. Video Games, Studio Software, Video Playback, Browser, etc.){RESET}",
        "",
        f"{RED}Accurate data is very important! Have you closed all other programs?{RESET}",
    ]
    for ln in lines:
        print(center_line(ln))
    print(center_line(""))
    print(center_line("Type \"yes\" to proceed"))
    print(bottom)

    try:
        if sys.stdin and sys.stdin.isatty():
            subprocess.run(["stty", "sane"], check=False)
    except Exception:
        pass
    ans = input("Type \"yes\" to proceed: ").strip().lower()
    return ans == "yes"


def _format_duration(seconds: float) -> str:
    total = int(round(max(0.0, seconds)))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    parts = []
    if h > 0:
        parts.append(f"{h}h")
    if m > 0 or h > 0:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def print_end_screen(completed_count: int, elapsed_seconds: float) -> None:
    try:
        width = max(60, min(shutil.get_terminal_size((100, 20)).columns, 100))
    except Exception:
        width = 80
    border = "\u2550" * (width - 2)
    top = f"\u2554{border}\u2557"
    bottom = f"\u255a{border}\u255d"
    GREEN = "\033[32;1m"
    MAGENTA = "\033[35;1m"
    GREEN_BG = "\033[42;97;1m"
    RESET = "\033[0m"
    ansi_re = re.compile(r"\x1b\[[0-9;]*m")

    def _display_len(s: str) -> int:
        try:
            return len(ansi_re.sub("", s))
        except Exception:
            return len(s)

    def center_line(text: str) -> str:
        t = text.strip()
        pad = max(0, width - 2 - _display_len(t))
        left = pad // 2
        right = pad - left
        return f"\u2551{' ' * left}{t}{' ' * right}\u2551"

    print(top)
    print(center_line(f"{GREEN_BG} Thank you for completing the benchmark! {RESET}"))
    print(center_line(""))
    time_str = _format_duration(elapsed_seconds)
    print(center_line(f"{GREEN}You supported an open-source database by submitting {completed_count} data points{RESET}"))
    print(center_line(f"{GREEN}and donating {time_str} of your computer's time! {MAGENTA}<3{RESET}"))
    print(bottom)
