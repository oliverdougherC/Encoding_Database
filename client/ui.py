import os
import re
import shutil
import signal
import subprocess
import sys
from typing import Any, Dict, List, Optional

# Palette:
# Evergreen       #173B34
# Cornflower Blue #6C8FD5
# Lavender Grey   #9693CC
# Ash Grey        #CDDBCD
# Vanilla Custard #EBE4B3

_RICH_AVAILABLE = False
_console = None
_Panel = None
_Table = None
_Prompt = None
_Confirm = None
_Progress = None
_SpinnerColumn = None
_TextColumn = None
_BarColumn = None
_TimeElapsedColumn = None
_TimeRemainingColumn = None
_Live = None
_Group = None
_Columns = None
_Column = None


def _env_true(name: str) -> bool:
    try:
        return str(os.environ.get(name, "")).strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        return False


_FORCE_TUI = _env_true("ENCODINGDB_FORCE_TUI") or _env_true("CLIENT_FORCE_TUI")
_FORCE_TERMINAL: Optional[bool] = True if _FORCE_TUI else None

try:
    from rich.console import Console
    from rich.console import Group
    try:
        from rich.columns import Columns  # type: ignore
    except Exception:
        Columns = None  # type: ignore
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
        TimeRemainingColumn,
    )
    from rich.prompt import Confirm, Prompt
    from rich.table import Column, Table
    from rich.theme import Theme

    _theme = Theme({
        "evergreen": "#173B34",
        "cornflower": "#6C8FD5",
        "lavender": "#9693CC",
        "ash": "#CDDBCD",
        "vanilla": "#EBE4B3",
        "title": "bold #EBE4B3 on #173B34",
        "accent": "bold #6C8FD5",
        "accent2": "#9693CC",
        "muted": "#CDDBCD",
        "ok": "bold #173B34 on #CDDBCD",
        "warn": "bold #173B34 on #EBE4B3",
        "bad": "bold #EBE4B3 on #173B34",
    })
    try:
        _console = Console(
            theme=_theme,
            highlight=False,
            soft_wrap=True,
            force_terminal=_FORCE_TERMINAL,
            force_interactive=True,
        )
    except TypeError:
        _console = Console(theme=_theme, highlight=False, soft_wrap=True, force_terminal=_FORCE_TERMINAL)
    _Panel = Panel
    _Table = Table
    _Prompt = Prompt
    _Confirm = Confirm
    _Progress = Progress
    _SpinnerColumn = SpinnerColumn
    _TextColumn = TextColumn
    _BarColumn = BarColumn
    _TimeElapsedColumn = TimeElapsedColumn
    _TimeRemainingColumn = TimeRemainingColumn
    _Live = Live
    _Group = Group
    _Columns = Columns
    _Column = Column
    _RICH_AVAILABLE = True
except Exception:
    _RICH_AVAILABLE = False


def _rich_tty() -> bool:
    if not (_RICH_AVAILABLE and _console is not None):
        return False
    if _FORCE_TUI:
        return True
    stdout_tty = bool(sys.stdout and sys.stdout.isatty())
    stdin_tty = bool(sys.stdin and sys.stdin.isatty())
    return stdout_tty or stdin_tty


def _stty_sane() -> None:
    try:
        if sys.stdin and sys.stdin.isatty():
            subprocess.run(["stty", "sane"], check=False)
    except Exception:
        pass


def print_info(message: str) -> None:
    if _rich_tty():
        _console.print(f"[accent]•[/accent] [muted]{message}[/muted]")
    else:
        print(message)


def print_success(message: str) -> None:
    if _rich_tty():
        _console.print(f"[ok] {message} [/ok]")
    else:
        print(message)


def print_warning(message: str) -> None:
    if _rich_tty():
        _console.print(f"[warn] {message} [/warn]")
    else:
        print(message)


def print_error(message: str) -> None:
    if _rich_tty():
        _console.print(f"[bad] {message} [/bad]")
    else:
        print(message)


def prompt_yes_no(prompt: str, default_no: bool = True) -> bool:
    _stty_sane()
    if _rich_tty():
        return bool(_Confirm.ask(f"[accent]{prompt}[/accent]", default=not default_no))
    suffix = " [y/N]: " if default_no else " [Y/n]: "
    ans = input(prompt + suffix).strip().lower()
    if not ans:
        return not default_no
    return ans in ("y", "yes")


def prompt_choice(prompt: str, options: List[str], default_index: int = 0) -> int:
    _stty_sane()
    if not options:
        return 0
    if _rich_tty():
        table = _Table(show_header=False, box=None, pad_edge=False)
        table.add_column(style="accent", width=4)
        table.add_column(style="muted")
        for i, opt in enumerate(options, start=1):
            table.add_row(f"{i}.", opt)
        _console.print(_Panel(table, title=f"[title] {prompt} [/title]", border_style="accent2"))
        raw = _Prompt.ask(
            f"[cornflower]{prompt}[/cornflower] [muted](1-{len(options)}, default {default_index + 1})[/muted]",
            default=str(default_index + 1),
        ).strip()
    else:
        for i, opt in enumerate(options, start=1):
            print(f"  {i}) {opt}")
        raw = input(f"{prompt} (1-{len(options)}) [default {default_index+1}]: ").strip()
    try:
        idx = int(raw)
        if 1 <= idx <= len(options):
            return idx - 1
    except Exception:
        pass
    return max(0, min(default_index, len(options) - 1))


def prompt_text(prompt: str, default_value: str = "") -> str:
    _stty_sane()
    if _rich_tty():
        raw = _Prompt.ask(
            f"[cornflower]{prompt}[/cornflower]",
            default=default_value if default_value is not None else "",
        ).strip()
        return raw or default_value
    raw = input(f"{prompt} [{default_value}]: ").strip()
    return raw or default_value


def _clear_screen() -> None:
    try:
        if _rich_tty():
            _console.clear()
        else:
            os.system("cls" if os.name == "nt" else "clear")
    except Exception:
        pass


def ensure_min_terminal_size(min_cols: int = 100, min_rows: int = 30) -> None:
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
    if _rich_tty():
        text = (
            "[bad] Warning! [/bad]\n\n"
            "[muted]Please close all programs that may be stealing CPU resources or using your media engine\n"
            "(video games, NLEs, video playback, browser tabs, etc.).[/muted]\n\n"
            "[accent2]Accurate data is important.[/accent2]\n"
            "[accent]Type \"yes\" to proceed.[/accent]"
        )
        _console.print(_Panel(text, title="[title] Benchmark Readiness Check [/title]", border_style="accent2"))
    else:
        print("Please close all heavy background applications for accurate results.")
        print('Type "yes" to proceed')
    _stty_sane()
    ans = input('Type "yes" to proceed: ').strip().lower()
    return ans == "yes"


def _format_duration(seconds: float) -> str:
    total = int(round(max(0.0, seconds)))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    parts: List[str] = []
    if h > 0:
        parts.append(f"{h}h")
    if m > 0 or h > 0:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def print_end_screen(completed_count: int, elapsed_seconds: float) -> None:
    time_str = _format_duration(elapsed_seconds)
    if _rich_tty():
        body = (
            "[ok] Benchmark run complete [/ok]\n\n"
            f"[muted]Submitted data points:[/muted] [accent]{completed_count}[/accent]\n"
            f"[muted]Time donated:[/muted] [accent2]{time_str}[/accent2]"
        )
        _console.print(_Panel(body, title="[title] Thank You [/title]", border_style="accent2"))
    else:
        print(f"Benchmark complete. Submitted {completed_count} data points in {time_str}.")


def print_benchmark_result(payload: Dict[str, Any], relative_file_size_pct: Optional[float]) -> None:
    def _fmt_float(v: Any, digits: int = 2) -> str:
        try:
            return f"{float(v):.{digits}f}"
        except Exception:
            return "N/A"

    if _rich_tty():
        table = _Table(show_header=False, box=None, pad_edge=False)
        table.add_column(style="muted", width=30)
        table.add_column(style="accent", justify="right")
        table.add_row("FPS", _fmt_float(payload.get("fps"), 2))
        table.add_row("VMAF", _fmt_float(payload.get("vmaf"), 2) if payload.get("vmaf") is not None else "N/A")
        table.add_row("SSIM", _fmt_float(payload.get("ssim"), 4) if payload.get("ssim") is not None else "N/A")
        table.add_row("PSNR", (_fmt_float(payload.get("psnr"), 2) + " dB") if payload.get("psnr") is not None else "N/A")
        if relative_file_size_pct is not None:
            table.add_row("Relative File Size", f"{_fmt_float(relative_file_size_pct, 1)}%")
        else:
            table.add_row("Relative File Size", "N/A")
        if payload.get("gpuUtilAvg") is not None:
            table.add_row("GPU Util", f"{_fmt_float(payload.get('gpuUtilAvg'), 1)}%")
        if payload.get("gpuPowerAvgW") is not None:
            gpu_power = float(payload.get("gpuPowerAvgW") or 0.0)
            fps = float(payload.get("fps") or 0.0)
            fps_per_watt = (fps / gpu_power) if gpu_power > 0 else None
            if fps_per_watt is None:
                table.add_row("GPU Power", f"{_fmt_float(gpu_power, 1)} W")
            else:
                table.add_row("GPU Power", f"{_fmt_float(gpu_power, 1)} W ({_fmt_float(fps_per_watt, 2)} FPS/W)")
        if payload.get("cpuUtilAvg") is not None:
            table.add_row("CPU Util", f"{_fmt_float(payload.get('cpuUtilAvg'), 1)}%")
        if payload.get("peakMemoryMB") is not None:
            table.add_row("Peak Memory", f"{_fmt_float(payload.get('peakMemoryMB'), 0)} MB")
        if payload.get("thermalThrottle") is True:
            table.add_row("Thermal Status", "[warn]THROTTLING DETECTED[/warn]")
        _console.print(_Panel(table, title="[title] Benchmark Result [/title]", border_style="accent2"))
        return

    print("\n|---------------------------")
    print(f"| FPS: {_fmt_float(payload.get('fps'), 2)}")
    print("|---------------------------")
    print(f"| VMAF: {_fmt_float(payload.get('vmaf'), 2) if payload.get('vmaf') is not None else 'N/A'}")
    print("|---------------------------")
    print(f"| SSIM: {_fmt_float(payload.get('ssim'), 4) if payload.get('ssim') is not None else 'N/A'}")
    print("|---------------------------")
    print(f"| PSNR: {(_fmt_float(payload.get('psnr'), 2) + ' dB') if payload.get('psnr') is not None else 'N/A'}")
    print("|---------------------------")
    if relative_file_size_pct is not None:
        print(f"| Relative File Size: {_fmt_float(relative_file_size_pct, 1)}%")
    else:
        print("| Relative File Size: N/A")
    print("|---------------------------")


def print_batch_summary(summary: Dict[str, Any]) -> None:
    total = int(summary.get("totalTasks") or 0)
    total_batches = int(summary.get("totalBatches") or 0)
    completed = int(summary.get("completed") or 0)
    submitted = int(summary.get("submitted") or 0)
    skipped = int(summary.get("skipped") or 0)
    queued = int(summary.get("queued") or 0)
    failed = int(summary.get("failed") or 0)
    elapsed_seconds = float(summary.get("elapsedSeconds") or 0.0)
    throughput_per_hour = float(summary.get("throughputPerHour") or 0.0)
    if _rich_tty():
        table = _Table(show_header=False, box=None, pad_edge=False)
        table.add_column(style="muted", width=22)
        table.add_column(style="accent", justify="right")
        table.add_row("Planned Tasks", str(total))
        if total_batches > 0:
            table.add_row("Batches", str(total_batches))
        table.add_row("Completed Encodes", str(completed))
        table.add_row("Submitted", str(submitted))
        table.add_row("Skipped", str(skipped))
        table.add_row("Queued", str(queued))
        table.add_row("Failures", str(failed))
        if elapsed_seconds > 0:
            table.add_row("Elapsed", _format_duration(elapsed_seconds))
            table.add_row("Throughput", f"{throughput_per_hour:.1f} encodes/hour")
        _console.print(_Panel(table, title="[title] Batch Summary [/title]", border_style="accent2"))
        return
    print("Batch Summary")
    print(f"  Planned Tasks: {total}")
    if total_batches > 0:
        print(f"  Batches: {total_batches}")
    print(f"  Completed Encodes: {completed}")
    print(f"  Submitted: {submitted}")
    print(f"  Skipped: {skipped}")
    print(f"  Queued: {queued}")
    print(f"  Failures: {failed}")
    if elapsed_seconds > 0:
        print(f"  Elapsed: {_format_duration(elapsed_seconds)}")
        print(f"  Throughput: {throughput_per_hour:.1f} encodes/hour")


class BenchmarkProgress:
    def __init__(self, total: int, title: str = "Benchmark Progress"):
        self.total = max(1, int(total))
        self.title = title
        self._progress = None
        self._task_id = None
        self._count = 0

    def __enter__(self) -> "BenchmarkProgress":
        if _rich_tty():
            self._progress = _Progress(
                _SpinnerColumn(style="cornflower"),
                _TextColumn("[cornflower]{task.description}[/cornflower]"),
                _BarColumn(bar_width=40, complete_style="lavender", finished_style="lavender", style="evergreen"),
                _TextColumn("[muted]{task.completed}/{task.total}[/muted]"),
                _TimeElapsedColumn(),
                _TimeRemainingColumn(),
                console=_console,
                transient=False,
            )
            self._progress.start()
            self._task_id = self._progress.add_task(self.title, total=self.total)
        return self

    def advance(self, description: Optional[str] = None, step: int = 1) -> None:
        self._count += step
        if self._progress is not None and self._task_id is not None:
            kwargs: Dict[str, Any] = {"advance": step}
            if description:
                kwargs["description"] = description
            self._progress.update(self._task_id, **kwargs)
            return
        if description:
            print(f"Progress: {self._count}/{self.total} - {description}")
        else:
            print(f"Progress: {self._count}/{self.total}")

    def set_description(self, description: str) -> None:
        if self._progress is not None and self._task_id is not None:
            self._progress.update(self._task_id, description=description)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._progress is not None:
            self._progress.stop()
            self._progress = None
            self._task_id = None


class BatchRunDashboard:
    def __init__(self, total_tasks: int, total_batches: int, hardware: Optional[Any] = None):
        self.total_tasks = max(1, int(total_tasks))
        self.total_batches = max(1, int(total_batches))
        self.hardware = hardware
        self._phase_steps_per_task = 3  # encode + metrics + submit

        self._live = None
        self._overall_progress = None
        self._batch_progress = None
        self._overall_task_id = None
        self._batch_task_id = None

        self._overall_phase_steps = 0
        self._batch_phase_steps = 0
        self._overall_count = 0
        self._batch_count = 0
        self._batch_no = 1
        self._batch_size = 1
        self._description = "Preparing batch..."
        self._task_info: Dict[str, Any] = {}
        self._metrics: Dict[str, Any] = {}
        self._counters: Dict[str, int] = {"submitted": 0, "skipped": 0, "queued": 0, "failed": 0}
        self._prev_sigwinch: Any = None
        self._sigwinch_installed = False

    def __enter__(self) -> "BatchRunDashboard":
        if _rich_tty():
            left_col = _Column(width=8, no_wrap=True) if _Column is not None else None
            self._overall_progress = _Progress(
                _TextColumn("[accent]{task.fields[label]}[/accent]", table_column=left_col),
                _BarColumn(bar_width=None, complete_style="lavender", finished_style="lavender", style="evergreen"),
                _TextColumn("[muted]{task.fields[display_done]}/{task.fields[display_total]}[/muted]"),
                _TimeElapsedColumn(),
                _TimeRemainingColumn(),
                console=_console,
                expand=True,
                transient=False,
            )
            self._batch_progress = _Progress(
                _TextColumn("[accent2]{task.fields[label]}[/accent2]", table_column=left_col),
                _BarColumn(bar_width=None, complete_style="cornflower", finished_style="cornflower", style="evergreen"),
                _TextColumn("[muted]{task.fields[display_done]}/{task.fields[display_total]}[/muted]"),
                _TimeElapsedColumn(),
                _TimeRemainingColumn(),
                console=_console,
                expand=True,
                transient=False,
            )
            # Important: do not call Progress.start() here.
            # Each Progress would create its own Live display and conflict with
            # this dashboard's parent Live, which can delay rendering until
            # teardown/interrupt on some terminals.
            self._overall_task_id = self._overall_progress.add_task(
                "Overall progress",
                total=self.total_tasks * self._phase_steps_per_task,
                display_done=0,
                display_total=self.total_tasks,
                label="Overall",
            )
            self._batch_task_id = self._batch_progress.add_task(
                "Batch progress",
                total=max(1, self._batch_size * self._phase_steps_per_task),
                display_done=0,
                display_total=self._batch_size,
                label="Batch",
            )
            self._live = _Live(
                self._render(),
                console=_console,
                refresh_per_second=8,
                auto_refresh=True,
            )
            try:
                self._live.start(refresh=True)
            except TypeError:
                self._live.start()
                try:
                    self._live.refresh()
                except Exception:
                    pass
            self._install_resize_handler()
            self._refresh()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._restore_resize_handler()
        if self._live is not None:
            self._live.stop()
            self._live = None
        if self._overall_progress is not None:
            self._overall_progress.stop()
            self._overall_progress = None
        if self._batch_progress is not None:
            self._batch_progress.stop()
            self._batch_progress = None
        self._overall_task_id = None
        self._batch_task_id = None

    def start_batch(self, batch_no: int, batch_size: int) -> None:
        self._batch_no = max(1, int(batch_no))
        self._batch_size = max(1, int(batch_size))
        self._batch_count = 0
        self._batch_phase_steps = 0
        if self._batch_progress is not None and self._batch_task_id is not None:
            self._batch_progress.reset(
                self._batch_task_id,
                total=max(1, self._batch_size * self._phase_steps_per_task),
                completed=0,
                description=f"Batch {self._batch_no}/{self.total_batches}",
                display_done=0,
                display_total=self._batch_size,
                label="Batch",
            )
        self._refresh()

    def set_description(self, description: str) -> None:
        self._description = description
        if self._overall_progress is not None and self._overall_task_id is not None:
            self._overall_progress.update(self._overall_task_id, description=description)
        if self._batch_progress is not None and self._batch_task_id is not None:
            self._batch_progress.update(
                self._batch_task_id,
                description=f"Batch {self._batch_no}/{self.total_batches}",
            )
        self._refresh()

    def set_current_test(self, **kwargs: Any) -> None:
        self._task_info = dict(kwargs)
        self._refresh()

    def update_machine_metrics(self, metrics: Dict[str, Any]) -> None:
        self._metrics = dict(metrics or {})
        self._refresh()

    def update_counters(self, *, submitted: int, skipped: int, queued: int, failed: int) -> None:
        self._counters = {
            "submitted": max(0, int(submitted)),
            "skipped": max(0, int(skipped)),
            "queued": max(0, int(queued)),
            "failed": max(0, int(failed)),
        }
        self._refresh()

    def advance_phase(self, description: Optional[str] = None, step: int = 1) -> None:
        step_n = max(1, int(step))
        self._overall_phase_steps += step_n
        self._batch_phase_steps += step_n
        if description:
            self._description = description
        display_overall = min(self.total_tasks, max(self._overall_count, self._overall_phase_steps))
        display_batch = min(self._batch_size, max(self._batch_count, self._batch_phase_steps))

        if self._overall_progress is not None and self._overall_task_id is not None:
            kwargs: Dict[str, Any] = {
                "advance": step_n,
                "display_done": display_overall,
                "display_total": self.total_tasks,
            }
            if description:
                kwargs["description"] = description
            self._overall_progress.update(self._overall_task_id, **kwargs)

        if self._batch_progress is not None and self._batch_task_id is not None:
            self._batch_progress.update(
                self._batch_task_id,
                advance=step_n,
                display_done=display_batch,
                display_total=self._batch_size,
            )
        self._refresh()

    def advance(self, description: Optional[str] = None, step: int = 1) -> None:
        step_n = max(1, int(step))
        self._overall_count += step_n
        self._batch_count += step_n
        self._overall_phase_steps += step_n
        self._batch_phase_steps += step_n
        if description:
            self._description = description
        display_overall = min(self.total_tasks, max(self._overall_count, self._overall_phase_steps))
        display_batch = min(self._batch_size, max(self._batch_count, self._batch_phase_steps))

        if self._overall_progress is not None and self._overall_task_id is not None:
            kwargs: Dict[str, Any] = {
                "advance": step_n,
                "display_done": display_overall,
                "display_total": self.total_tasks,
            }
            if description:
                kwargs["description"] = description
            self._overall_progress.update(self._overall_task_id, **kwargs)
        if self._batch_progress is not None and self._batch_task_id is not None:
            self._batch_progress.update(
                self._batch_task_id,
                advance=step_n,
                display_done=display_batch,
                display_total=self._batch_size,
            )

        if not _rich_tty():
            if description:
                print(f"Progress: {self._overall_count}/{self.total_tasks} - {description}")
            else:
                print(f"Progress: {self._overall_count}/{self.total_tasks}")
        self._refresh()

    def _install_resize_handler(self) -> None:
        try:
            sig = signal.SIGWINCH
        except Exception:
            return

        try:
            self._prev_sigwinch = signal.getsignal(sig)
        except Exception:
            self._prev_sigwinch = None

        def _on_resize(signum: int, frame: Any) -> None:
            self._refresh()
            prev = self._prev_sigwinch
            if callable(prev) and prev is not _on_resize:
                try:
                    prev(signum, frame)
                except Exception:
                    pass

        try:
            signal.signal(sig, _on_resize)
            self._sigwinch_installed = True
        except Exception:
            self._sigwinch_installed = False

    def _restore_resize_handler(self) -> None:
        if not self._sigwinch_installed:
            return
        try:
            signal.signal(signal.SIGWINCH, self._prev_sigwinch)
        except Exception:
            pass
        self._sigwinch_installed = False

    def _fmt(self, key: str, suffix: str = "", digits: int = 1) -> str:
        try:
            v = self._metrics.get(key)
            if v is None:
                return "N/A"
            return f"{float(v):.{digits}f}{suffix}"
        except Exception:
            return "N/A"

    def _machine_info_lines(self, compact: bool = False) -> List[str]:
        hw = self.hardware
        cpu_model = getattr(hw, "cpuModel", None) if hw is not None else None
        gpu_model = getattr(hw, "gpuModel", None) if hw is not None else None
        ram_gb = getattr(hw, "ramGB", None) if hw is not None else None
        os_name = getattr(hw, "os", None) if hw is not None else None

        is_hardware = bool(self._task_info.get("isHardware", False))
        mode_label = "Hardware Encoder" if is_hardware else "Software Encoder"
        power_source = str(self._metrics.get("powerSource") or "unknown").upper()

        lines = [
            f"[muted]Mode:[/muted] [accent]{mode_label}[/accent]",
            f"[muted]OS:[/muted] {os_name or 'Unknown'}",
            f"[muted]RAM:[/muted] {ram_gb if ram_gb is not None else 'N/A'} GB",
            f"[muted]Power Source:[/muted] {power_source}",
            f"[muted]Power Draw:[/muted] {self._fmt('gpuPowerAvgW', ' W', 1)}",
            f"[muted]Battery Drop:[/muted] {self._fmt('batteryPercentDrop', '%', 2)}"
        ]

        if compact:
            if is_hardware:
                lines.extend([
                    f"[muted]GPU:[/muted] {gpu_model or 'Unknown'}",
                    f"[muted]GPU Util:[/muted] {self._fmt('gpuUtilAvg', '%', 1)}",
                ])
            else:
                lines.extend([
                    f"[muted]CPU:[/muted] {cpu_model or 'Unknown'}",
                    f"[muted]CPU Util:[/muted] {self._fmt('cpuUtilAvg', '%', 1)}",
                ])
            return lines

        if is_hardware:
            lines.extend([
                f"[muted]GPU:[/muted] {gpu_model or 'Unknown'}",
                f"[muted]GPU Util:[/muted] {self._fmt('gpuUtilAvg', '%', 1)}",
                f"[muted]GPU Temp:[/muted] {self._fmt('gpuTempMaxC', ' C', 1)}",
                f"[muted]Video Engine CPU:[/muted] {self._fmt('ffmpegCpuUtilAvg', '%', 1)}",
            ])
        else:
            lines.extend([
                f"[muted]CPU:[/muted] {cpu_model or 'Unknown'}",
                f"[muted]CPU Util:[/muted] {self._fmt('cpuUtilAvg', '%', 1)}",
                f"[muted]CPU Temp:[/muted] {self._fmt('cpuTempMaxC', ' C', 1)}",
                f"[muted]CPU Freq:[/muted] {self._fmt('cpuFreqAvgMHz', ' MHz', 0)}",
            ])
        return lines

    def _test_info_lines(self, compact: bool = False) -> List[str]:
        stage = str(self._task_info.get("stage") or "Preparing")
        enc = str(self._task_info.get("encoder") or "-")
        preset = str(self._task_info.get("preset") or "-")
        crf = self._task_info.get("crf")

        lines = [
            f"[muted]Stage:[/muted] [accent2]{stage}[/accent2]",
            f"[muted]Encoder:[/muted] [vanilla]{enc}[/vanilla]",
            f"[muted]Preset:[/muted] {preset}    [muted]CRF:[/muted] {crf if crf is not None else '-'}",
            f"[muted]Mode:[/muted] CRF (1-pass)",
            f"[muted]Queue:[/muted] ok={self._counters['submitted']} skip={self._counters['skipped']} queue={self._counters['queued']} fail={self._counters['failed']}",
            f"[muted]Now:[/muted] {self._description}",
        ]
        if compact:
            return lines[:5]
        return lines

    def _render(self) -> Any:
        if not (_rich_tty() and self._overall_progress is not None and self._batch_progress is not None):
            return ""

        width = 0
        try:
            width = int(getattr(getattr(_console, "size", None), "width", 0) or 0)
        except Exception:
            width = 0
        compact = width > 0 and width < 120
        side_by_side = width >= 130

        test_lines = self._test_info_lines(compact=compact)
        machine_lines = self._machine_info_lines(compact=compact)
        if side_by_side:
            max_lines = max(len(test_lines), len(machine_lines))
            if len(test_lines) < max_lines:
                test_lines.extend([""] * (max_lines - len(test_lines)))
            if len(machine_lines) < max_lines:
                machine_lines.extend([""] * (max_lines - len(machine_lines)))

        current_panel = _Panel(
            "\n".join(test_lines),
            title="[title] Current Benchmark [/title]",
            border_style="accent2",
            expand=True,
        )
        telemetry_panel = _Panel(
            "\n".join(machine_lines),
            title="[title] Client Telemetry [/title]",
            border_style="accent2",
            expand=True,
        )
        if side_by_side:
            top_grid = _Table.grid(expand=True)
            top_grid.add_column(ratio=3)
            top_grid.add_column(ratio=2)
            top_grid.add_row(current_panel, telemetry_panel)
            top = top_grid
        else:
            top_stack = _Table.grid(expand=True)
            top_stack.add_row(current_panel)
            top_stack.add_row(telemetry_panel)
            top = top_stack

        batch_panel = _Panel(
            self._batch_progress,
            title=f"[title] Batch {self._batch_no}/{self.total_batches} [/title]",
            border_style="accent2",
            expand=True,
        )
        overall_panel = _Panel(
            self._overall_progress,
            title="[title] Total Run Progress [/title]",
            border_style="accent2",
            expand=True,
        )
        return _Group(top, batch_panel, overall_panel)

    def _refresh(self) -> None:
        if self._live is not None:
            self._live.update(self._render(), refresh=False)
            try:
                self._live.refresh()
            except Exception:
                try:
                    self._live.update(self._render(), refresh=True)
                except Exception:
                    pass
            try:
                if _console is not None and getattr(_console, "file", None) is not None:
                    _console.file.flush()
            except Exception:
                pass
