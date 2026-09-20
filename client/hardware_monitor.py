"""Background hardware telemetry sampling during FFmpeg encodes.

Telemetry collection is intentionally best-effort and collector based:
- fast in-process collectors run every 500ms
- slower platform collectors run every 2s with timeout/backoff
- start/end snapshot collectors capture battery state

Collectors fail independently and emit stable diagnostic codes instead of raw
error text so submissions stay deterministic across retries.
"""

from __future__ import annotations

import json
import math
import os
import platform
import plistlib
import selectors
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple
from xml.parsers.expat import ExpatError

import psutil

from .config import normalize_cpu_freq_mhz
from .energy import EnergyCollector

try:
    import pynvml  # type: ignore

    _PYNVML_AVAILABLE = True
except Exception:
    pynvml = None  # type: ignore
    _PYNVML_AVAILABLE = False

try:
    import GPUtil  # type: ignore

    _GPUTIL_AVAILABLE = True
except Exception:
    GPUtil = None  # type: ignore
    _GPUTIL_AVAILABLE = False

_NVML_INITIALIZED = False
_NVML_INIT_LOCK = threading.Lock()
CPU_THREAD_WINDOW_SOURCE = "cpu_psutil_thread_window_v1"
FFMPEG_PROCESS_WINDOW_SOURCE = "ffmpeg_psutil_process_window_v1"

_DARWIN = platform.system() == "Darwin"
_WINDOWS = platform.system() == "Windows"


def _ensure_nvml() -> bool:
    global _NVML_INITIALIZED
    if not _PYNVML_AVAILABLE:
        return False
    if _NVML_INITIALIZED:
        return True
    with _NVML_INIT_LOCK:
        if _NVML_INITIALIZED:
            return True
        try:
            pynvml.nvmlInit()
            _NVML_INITIALIZED = True
            return True
        except Exception:
            return False


def infer_gpu_vendor_for_encoder(encoder_name: Optional[str]) -> Optional[str]:
    enc = (encoder_name or "").strip().lower()
    if not enc:
        return None
    if enc.endswith("_nvenc"):
        return "nvidia"
    if enc.endswith("_qsv"):
        return "intel"
    if enc.endswith("_amf"):
        return "amd"
    if enc.endswith("_videotoolbox"):
        return "apple"
    return None


def parse_pmset_battery_output(text: str) -> Tuple[Optional[float], Optional[str]]:
    percent: Optional[float] = None
    power_source: Optional[str] = None
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if "drawing from 'ac power'" in lower or "drawing from ac" in lower:
            power_source = "ac"
        elif "drawing from 'battery power'" in lower or "drawing from battery" in lower:
            power_source = "battery"
        if "%" in line:
            token = line.split("%", 1)[0].rsplit(None, 1)[-1]
            try:
                percent = float(token)
            except Exception:
                pass
    return percent, power_source


def parse_powermetrics_output(text: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if "cpu die temperature" in lower or "cpu temperature" in lower:
            try:
                out["cpuTempMaxC"] = float(line.split(":")[-1].strip().split()[0])
            except Exception:
                pass
        elif "gpu die temperature" in lower or "gpu temperature" in lower:
            try:
                out["gpuTempMaxC"] = float(line.split(":")[-1].strip().split()[0])
            except Exception:
                pass
    return out


AGX_SYSTEM_GPU_SOURCE = "gpu_ioreg_agx_system_utilization_v1"
_AGX_OUTPUT_LIMIT = 256 * 1024
_AGX_COMMAND = ["/usr/sbin/ioreg", "-a", "-r", "-c", "AGXAccelerator", "-d", "1"]


def _read_agx_ioreg() -> bytes:
    """Bound both time and buffered bytes from this nonprivileged, leaf command."""
    deadline = time.monotonic() + 1.0
    chunks = bytearray()
    with subprocess.Popen(_AGX_COMMAND, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise subprocess.TimeoutExpired(_AGX_COMMAND, 1.0)
                    chunk = os.read(proc.stdout.fileno(), 8192)
                    if not chunk:
                        break
                    chunks.extend(chunk)
                    if len(chunks) > _AGX_OUTPUT_LIMIT:
                        raise ValueError("AGX observation exceeds output budget")
            if proc.wait(timeout=max(0.001, deadline - time.monotonic())) != 0:
                raise ValueError("AGX observation command failed")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
    return bytes(chunks)


def parse_agx_system_utilization(raw: bytes, expected_model: Optional[str]) -> Optional[float]:
    """Driver-reported system GPU load, not VideoToolbox media-engine occupancy."""
    if not expected_model or expected_model == "unknown" or len(raw) > _AGX_OUTPUT_LIMIT:
        return None
    try:
        rows = plistlib.loads(raw)
    except (ValueError, TypeError, plistlib.InvalidFileException, ExpatError):
        return None
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        return None
    adapter = rows[0]
    if not str(adapter.get("IOObjectClass", "")).startswith("AGXAccelerator"):
        return None
    if adapter.get("model") != expected_model:
        return None
    stats = adapter.get("PerformanceStatistics")
    value = stats.get("Device Utilization %") if isinstance(stats, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if 0 <= value <= 100 and math.isfinite(value) else None


def parse_windows_gpu_counter_output(text: str) -> Dict[str, Optional[float]]:
    util_values: List[float] = []
    mem_values_mb: List[float] = []
    rows: List[Dict[str, object]] = []
    try:
        parsed = json.loads(text or "[]")
        if isinstance(parsed, dict):
            rows = [parsed]
        elif isinstance(parsed, list):
            rows = [row for row in parsed if isinstance(row, dict)]
    except Exception:
        rows = []

    for row in rows:
        path = str(row.get("Path") or row.get("path") or "")
        cooked = row.get("CookedValue")
        try:
            value = float(cooked)  # type: ignore[arg-type]
        except Exception:
            continue
        lower = path.lower()
        if "utilization percentage" in lower:
            util_values.append(max(0.0, value))
        elif "dedicated usage" in lower or "shared usage" in lower:
            if value >= 0:
                mem_values_mb.append(value / (1024.0 * 1024.0))

    util_pct = min(100.0, sum(util_values)) if util_values else None
    mem_used_mb = max(mem_values_mb) if mem_values_mb else None
    return {"util_pct": util_pct, "mem_used_mb": mem_used_mb}


def _run_command(cmd: List[str], timeout: float) -> str:
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=timeout,
    )
    return proc.stdout or ""


def _is_elevated() -> bool:
    if _WINDOWS:
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
        except Exception:
            return False
    try:
        return os.geteuid() == 0  # type: ignore[attr-defined]
    except Exception:
        return False


@dataclass
class HardwareMetrics:
    gpu_util_avg: Optional[float] = None
    gpu_power_avg_w: Optional[float] = None
    gpu_mem_peak_mb: Optional[float] = None
    gpu_temp_max_c: Optional[float] = None
    cpu_util_avg: Optional[float] = None
    cpu_util_max: Optional[float] = None
    cpu_freq_avg_mhz: Optional[float] = None
    cpu_temp_max_c: Optional[float] = None
    peak_memory_mb: Optional[float] = None
    ffmpeg_cpu_util_avg: Optional[float] = None
    ffmpeg_cpu_util_max: Optional[float] = None
    ffmpeg_read_mb: Optional[float] = None
    ffmpeg_write_mb: Optional[float] = None
    ffmpeg_cpu_time_s: Optional[float] = None
    battery_percent_start: Optional[float] = None
    battery_percent_end: Optional[float] = None
    battery_percent_drop: Optional[float] = None
    power_source: Optional[str] = None
    sample_count: Optional[int] = None
    monitor_duration_ms: Optional[int] = None
    thermal_throttle: Optional[bool] = None
    cpu_sample_count: Optional[int] = None
    gpu_sample_count: Optional[int] = None
    gpu_util_sample_count: Optional[int] = None
    ffmpeg_sample_count: Optional[int] = None
    battery_sample_count: Optional[int] = None
    telemetry_sources: Optional[str] = None
    telemetry_missing: Optional[str] = None
    energy_domains: Optional[List[Dict[str, Any]]] = None


@dataclass
class _GpuSample:
    util_pct: Optional[float] = None
    power_w: Optional[float] = None
    mem_used_mb: Optional[float] = None
    temp_c: Optional[float] = None


@dataclass
class _CpuSample:
    overall_pct: float
    freq_mhz: Optional[float] = None
    temp_c: Optional[float] = None


@dataclass
class _ProcSample:
    cpu_pct: float


@dataclass
class _BatterySample:
    percent: Optional[float]
    power_source: Optional[str]


@dataclass
class _Collector:
    name: str
    interval_s: float
    fn: Callable[[], None]
    next_due_s: float = 0.0
    backoff_until_s: float = 0.0
    failures: int = 0


class HardwareMonitor:
    """Samples hardware metrics in a background thread while an encode runs."""

    def __init__(
        self,
        ffmpeg_pid: Optional[int] = None,
        interval: float = 0.5,
        *,
        encoder_name: Optional[str] = None,
        host_gpu_vendors: Optional[Iterable[str]] = None,
    ) -> None:
        self._ffmpeg_pid = ffmpeg_pid
        self._interval = max(0.1, interval)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._gpu_samples: List[_GpuSample] = []
        self._cpu_samples: List[_CpuSample] = []
        self._cpu_baseline_ready = False
        self._cpu_sampler_ident: Optional[int] = None
        self._cpu_baseline_mono: Optional[float] = None
        self._cpu_sample_is_fresh = False
        self._proc_samples: List[_ProcSample] = []
        self._proc_cpu_windows: Dict[Tuple[int, float], Tuple[psutil.Process, float]] = {}
        self._battery_samples: List[_BatterySample] = []
        self._memory_peak_bytes: float = 0.0
        self._lock = threading.Lock()
        self._sources: Set[str] = set()
        self._missing: Set[str] = set()
        self._start_ts: float = 0.0
        self._end_ts: float = 0.0
        self._start_mono: float = 0.0
        self._end_mono: float = 0.0
        self._battery_start_pct: Optional[float] = None
        self._battery_end_pct: Optional[float] = None
        self._power_source: Optional[str] = None
        self._ffmpeg_io_start: Optional[Tuple[float, float]] = None
        self._ffmpeg_io_end: Optional[Tuple[float, float]] = None
        self._ffmpeg_cpu_time_start: Optional[float] = None
        self._ffmpeg_cpu_time_end: Optional[float] = None
        self._cpu_freq_reference_mhz: Optional[float] = self._detect_cpu_freq_reference_mhz()
        self._collectors: List[_Collector] = []
        self._gpu_vendor = infer_gpu_vendor_for_encoder(encoder_name)
        self._agx_expected_model: Optional[str] = None
        if _DARWIN and self._gpu_vendor == "apple":
            from .identity import selected_device
            device = selected_device(encoder_name)
            if device.get("deviceId") == "videotoolbox:system":
                self._agx_expected_model = device.get("model")
        self._host_gpu_vendors = sorted({
            str(v).strip().lower()
            for v in (host_gpu_vendors or [])
            if str(v).strip()
        })
        self._allow_gpu_collection = self._should_collect_gpu()
        self._nvml_device_indexes: Optional[List[int]] = None
        self._elevated = _is_elevated()
        self._energy_collector: Optional[EnergyCollector] = None
        self._energy_domains: List[Dict[str, Any]] = []

    def start(self) -> None:
        self._stop_event.clear()
        self._gpu_samples.clear()
        self._cpu_samples.clear()
        self._proc_samples.clear()
        self._proc_cpu_windows.clear()
        self._battery_samples.clear()
        self._sources.clear()
        self._missing.clear()
        self._memory_peak_bytes = 0.0
        self._start_ts = time.time()
        self._end_ts = 0.0
        self._start_mono = time.monotonic()
        self._end_mono = 0.0
        self._battery_start_pct = None
        self._battery_end_pct = None
        self._power_source = None
        self._ffmpeg_io_start = self._read_ffmpeg_io_totals()
        self._ffmpeg_io_end = None
        self._ffmpeg_cpu_time_start = self._read_ffmpeg_cpu_time()
        self._ffmpeg_cpu_time_end = None
        self._nvml_device_indexes = self._select_nvml_device_indexes()
        self._energy_collector = EnergyCollector(
            collect_nvml=self._gpu_vendor == "nvidia" or bool(self._nvml_device_indexes),
            nvml_device_indexes=self._nvml_device_indexes,
            collect_powercap=platform.system() == "Linux",
        )
        self._energy_collector.start()

        self._sample_ffmpeg_process()  # Prime the retained per-process objects; retain no first-read zeros.

        self._capture_battery_snapshot(is_end=False)
        self._build_collectors()
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()

    def stop(self) -> HardwareMetrics:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        self._end_ts = time.time()
        self._end_mono = time.monotonic()
        self._ffmpeg_io_end = self._read_ffmpeg_io_totals()
        self._ffmpeg_cpu_time_end = self._read_ffmpeg_cpu_time()
        self._capture_battery_snapshot(is_end=True)
        self._energy_domains = self._energy_collector.stop() if self._energy_collector is not None else []
        return self._aggregate()

    def _build_collectors(self) -> None:
        self._collectors = [
            _Collector("cpu_psutil", 0.5, self._sample_cpu),
            _Collector("ffmpeg_psutil", 0.5, self._sample_ffmpeg_process),
            _Collector("memory_psutil", 0.5, self._sample_memory),
            _Collector("gpu_fast", 0.5, self._sample_gpu_fast),
        ]
        if _WINDOWS:
            self._collectors.append(_Collector("gpu_windows_counter", 2.0, self._sample_windows_gpu_counter))
        if _DARWIN:
            self._collectors.append(_Collector("powermetrics", 2.0, self._sample_powermetrics))
            if self._gpu_vendor == "apple":
                self._collectors.append(_Collector("agx_system_gpu", 0.5, self._sample_agx_system_gpu))

    def _sample_loop(self) -> None:
        # psutil keeps system CPU baselines by thread ID. A caller-thread prime
        # cannot reset a recycled sampler ID's history from a previous encode.
        self._cpu_baseline_ready = False
        self._cpu_sampler_ident = threading.get_ident()
        self._cpu_baseline_mono = None
        self._read_cpu_percent()
        # The discarded baseline is not a zero-utilization sample. Give the
        # first retained delta the >=100ms interval recommended by psutil.
        if self._stop_event.wait(0.1):
            return
        while not self._stop_event.is_set():
            now = time.monotonic()
            for collector in self._collectors:
                if now < collector.next_due_s or now < collector.backoff_until_s:
                    continue
                self._run_collector(collector, now)
            self._stop_event.wait(self._interval)

    def _run_collector(self, collector: _Collector, now: float) -> None:
        try:
            collector.fn()
            collector.failures = 0
            collector.backoff_until_s = 0.0
        except subprocess.TimeoutExpired:
            collector.failures += 1
            self._record_missing(f"collector_timeout_{collector.name}")
            collector.backoff_until_s = now + min(30.0, collector.interval_s * (2 ** min(collector.failures, 5)))
        except Exception:
            collector.failures += 1
            self._record_missing(f"collector_error_{collector.name}")
            collector.backoff_until_s = now + min(30.0, collector.interval_s * (2 ** min(collector.failures, 5)))
        finally:
            collector.next_due_s = now + collector.interval_s

    def _record_source(self, code: str) -> None:
        if code:
            self._sources.add(code)

    def _record_missing(self, code: str) -> None:
        if code:
            self._missing.add(code)

    def _should_collect_gpu(self) -> bool:
        if self._gpu_vendor:
            return True
        if len(self._host_gpu_vendors) > 1:
            self._record_missing("gpu_ambiguous")
            return False
        return True

    def _select_nvml_device_indexes(self) -> Optional[List[int]]:
        if not self._allow_gpu_collection or not _ensure_nvml():
            return None
        try:
            count = int(pynvml.nvmlDeviceGetCount())
        except Exception:
            return None
        indexes = list(range(max(0, count)))
        if not indexes:
            return None
        if self._gpu_vendor and self._gpu_vendor != "nvidia":
            return None
        if len(indexes) == 1:
            return indexes
        if self._gpu_vendor == "nvidia":
            return [0]  # canonical NVENC commands explicitly use -gpu 0
        self._record_missing("gpu_ambiguous")
        return None

    def _sample_gpu_fast(self) -> None:
        # Apple system GPU observations belong to the attributed AGX collector.
        if _DARWIN and self._gpu_vendor == "apple":
            return
        if not self._allow_gpu_collection:
            return
        if self._sample_gpu_nvml():
            return
        if self._sample_gpu_gputil():
            return
        self._record_missing("gpu_unavailable")

    def _sample_gpu_nvml(self) -> bool:
        indexes = self._nvml_device_indexes or []
        if not indexes:
            return False
        for idx in indexes:
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(idx)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                power_w: Optional[float] = None
                try:
                    power_w = float(pynvml.nvmlDeviceGetPowerUsage(handle)) / 1000.0
                except Exception:
                    power_w = None
                mem_used_mb: Optional[float] = None
                try:
                    mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    mem_used_mb = float(mem_info.used) / (1024.0 * 1024.0)
                except Exception:
                    mem_used_mb = None
                temp_c: Optional[float] = None
                try:
                    temp_c = float(
                        pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                    )
                except Exception:
                    temp_c = None
                with self._lock:
                    self._gpu_samples.append(
                        _GpuSample(
                            util_pct=float(util.gpu),
                            power_w=power_w,
                            mem_used_mb=mem_used_mb,
                            temp_c=temp_c,
                        )
                    )
                self._record_source("gpu_nvml")
                if power_w is not None:
                    self._record_source("gpu_power_nvml")
                if temp_c is not None:
                    self._record_source("gpu_temp_nvml")
                return True
            except Exception:
                continue
        return False

    def _sample_gpu_gputil(self) -> bool:
        if not _GPUTIL_AVAILABLE:
            return False
        try:
            gpus = GPUtil.getGPUs()  # type: ignore[attr-defined]
        except Exception:
            return False
        if not gpus:
            return False
        if self._gpu_vendor and self._gpu_vendor != "nvidia":
            return False
        if len(gpus) > 1:
            self._record_missing("gpu_ambiguous")
            return False
        g = gpus[0]
        util_raw = getattr(g, "load", None)
        util_pct = float(util_raw) * 100.0 if isinstance(util_raw, (int, float)) else None
        mem_raw = getattr(g, "memoryUsed", None)
        mem_used_mb = float(mem_raw) if isinstance(mem_raw, (int, float)) else None
        power_raw = getattr(g, "powerDraw", None)
        power_w = float(power_raw) if isinstance(power_raw, (int, float)) and power_raw >= 0 else None
        temp_raw = getattr(g, "temperature", None)
        temp_c = float(temp_raw) if isinstance(temp_raw, (int, float)) and temp_raw >= 0 else None
        with self._lock:
            self._gpu_samples.append(
                _GpuSample(
                    util_pct=util_pct,
                    power_w=power_w,
                    mem_used_mb=mem_used_mb,
                    temp_c=temp_c,
                )
            )
        self._record_source("gpu_gputil")
        return True

    def _sample_windows_gpu_counter(self) -> None:
        if not _WINDOWS or not self._allow_gpu_collection:
            return
        if self._gpu_vendor == "nvidia" and self._nvml_device_indexes:
            return
        if len(self._host_gpu_vendors) > 1 and not self._gpu_vendor:
            self._record_missing("gpu_ambiguous")
            return
        command = (
            "Get-Counter '\\GPU Engine(*)\\Utilization Percentage',"
            "'\\GPU Adapter Memory(*)\\Dedicated Usage' | "
            "Select-Object -ExpandProperty CounterSamples | "
            "Select-Object Path,InstanceName,CookedValue | ConvertTo-Json -Compress"
        )
        raw = _run_command(["powershell", "-NoProfile", "-Command", command], timeout=1.5)
        parsed = parse_windows_gpu_counter_output(raw)
        if parsed.get("util_pct") is None and parsed.get("mem_used_mb") is None:
            self._record_missing("gpu_windows_counter_unavailable")
            return
        with self._lock:
            self._gpu_samples.append(
                _GpuSample(
                    util_pct=parsed.get("util_pct"),
                    mem_used_mb=parsed.get("mem_used_mb"),
                )
            )
        self._record_source("gpu_windows_counter")

    def _sample_agx_system_gpu(self) -> None:
        if not self._allow_gpu_collection or not self._agx_expected_model:
            self._record_missing("gpu_ioreg_agx_unattributed")
            return
        utilization = parse_agx_system_utilization(_read_agx_ioreg(), self._agx_expected_model)
        if utilization is None:
            self._record_missing("gpu_ioreg_agx_unavailable")
            return
        with self._lock:
            self._gpu_samples.append(_GpuSample(util_pct=utilization))
        self._record_source(AGX_SYSTEM_GPU_SOURCE)

    def _sample_powermetrics(self) -> None:
        if not _DARWIN or not self._elevated:
            if _DARWIN:
                self._record_missing("powermetrics_unavailable")
            return
        raw = _run_command(
            ["powermetrics", "--samplers", "smc", "-n", "1", "--format", "text"],
            timeout=2.0,
        )
        parsed = parse_powermetrics_output(raw)
        if not parsed:
            self._record_missing("powermetrics_unavailable")
            return
        gpu_temp = parsed.get("gpuTempMaxC")
        if gpu_temp is not None and self._allow_gpu_collection:
            with self._lock:
                self._gpu_samples.append(_GpuSample(temp_c=gpu_temp))
            self._record_source("gpu_temp_powermetrics")
        cpu_temp = parsed.get("cpuTempMaxC")
        if cpu_temp is not None:
            overall = self._read_cpu_percent()
            if overall is None:
                return
            with self._lock:
                self._cpu_samples.append(_CpuSample(overall_pct=overall, temp_c=cpu_temp))
            self._record_source("cpu_temp_powermetrics")
            if self._cpu_sample_is_fresh:
                self._record_source(CPU_THREAD_WINDOW_SOURCE)

    def _read_cpu_percent(self) -> Optional[float]:
        self._cpu_sample_is_fresh = False
        try:
            overall = float(psutil.cpu_percent(interval=None))
            if not math.isfinite(overall) or not 0 <= overall <= 100:
                raise ValueError("invalid CPU counter")
        except Exception:
            self._cpu_baseline_ready = False
            self._cpu_baseline_mono = None
            self._record_missing("cpu_unavailable")
            return None
        now = time.monotonic()
        previous = self._cpu_baseline_mono
        self._cpu_baseline_mono = now
        if not self._cpu_baseline_ready:
            self._cpu_baseline_ready = True
            return None
        self._cpu_sample_is_fresh = (self._cpu_sampler_ident == threading.get_ident()
            and previous is not None and now >= previous + 0.1)
        if self._cpu_sampler_ident is not None and not self._cpu_sample_is_fresh:
            return None
        return overall

    def _sample_cpu(self) -> None:
        overall = self._read_cpu_percent()
        if overall is None:
            return
        freq: Optional[float] = None
        try:
            f = psutil.cpu_freq()
            if f and f.current and f.current > 0:
                freq = normalize_cpu_freq_mhz(
                    f.current,
                    reference_mhz=self._cpu_freq_reference_mhz,
                )
                if freq is not None and self._cpu_freq_reference_mhz is None:
                    self._cpu_freq_reference_mhz = freq
                if freq is not None:
                    self._record_source("cpu_freq_psutil")
        except Exception:
            pass
        temp: Optional[float] = None
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for name in ("coretemp", "k10temp", "cpu_thermal", "cpu-thermal", "acpitz"):
                    if name in temps and temps[name]:
                        readings = [e.current for e in temps[name] if e.current and e.current > 0]
                        if readings:
                            temp = max(readings)
                            self._record_source("cpu_temp_psutil")
                            break
        except Exception:
            pass
        with self._lock:
            self._cpu_samples.append(_CpuSample(overall_pct=overall, freq_mhz=freq, temp_c=temp))
        self._record_source("cpu_psutil")
        if self._cpu_sample_is_fresh:
            self._record_source(CPU_THREAD_WINDOW_SOURCE)

    def _sample_ffmpeg_process(self) -> None:
        # psutil's nonblocking process CPU baseline belongs to the Process
        # object. Discovery creates fresh objects; reuse only an exact PID and
        # creation-time match so a recycled PID cannot inherit an old baseline.
        processes = self._collect_process_tree(require_complete=True)
        next_windows: Dict[Tuple[int, float], Tuple[psutil.Process, float]] = {}
        total_pct = 0.0
        complete = bool(processes)
        for discovered in processes:
            try:
                created = float(discovered.create_time())
                if not math.isfinite(created) or created <= 0:
                    raise ValueError("invalid process identity")
                identity = (discovered.pid, created)
                previous = self._proc_cpu_windows.get(identity)
                proc = previous[0] if previous is not None else discovered
                pct = float(proc.cpu_percent(interval=None))
                if not math.isfinite(pct) or pct < 0:
                    raise ValueError("invalid process CPU counter")
                now = time.monotonic()
                next_windows[identity] = (proc, now)
                if previous is None or now < previous[1] + 0.1:
                    complete = False
                else:
                    # Keep psutil's existing units: one busy CPU is 100%, so
                    # a multithreaded encode may legitimately exceed 100%.
                    total_pct += pct
            except Exception:
                complete = False
                self._record_missing("ffmpeg_cpu_unavailable")
        self._proc_cpu_windows = next_windows
        # A partial tree is not a zero or a complete process-utilization sample.
        if complete:
            with self._lock:
                self._proc_samples.append(_ProcSample(cpu_pct=total_pct))
            self._record_source("ffmpeg_psutil")
            self._record_source(FFMPEG_PROCESS_WINDOW_SOURCE)

    def _sample_memory(self) -> None:
        rss = 0.0
        any_sample = False
        for proc in self._collect_process_tree():
            try:
                rss += float(proc.memory_info().rss)
                any_sample = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception:
                continue
        if any_sample:
            with self._lock:
                if rss > self._memory_peak_bytes:
                    self._memory_peak_bytes = rss
            self._record_source("memory_psutil")

    def _capture_battery_snapshot(self, *, is_end: bool) -> None:
        percent, power_source, source_code = self._read_battery_state()
        if source_code:
            self._record_source(source_code)
        if percent is None and power_source is None:
            self._record_missing("battery_unavailable")
            return
        with self._lock:
            self._battery_samples.append(_BatterySample(percent=percent, power_source=power_source))
        if is_end:
            self._battery_end_pct = percent
        else:
            self._battery_start_pct = percent
        if power_source:
            self._power_source = power_source
        else:
            self._record_missing("power_source_unavailable")

    def _aggregate(self) -> HardwareMetrics:
        m = HardwareMetrics()
        with self._lock:
            gpu = list(self._gpu_samples)
            cpu = list(self._cpu_samples)
            proc = list(self._proc_samples)
            battery = list(self._battery_samples)
            peak_mem = self._memory_peak_bytes

        util_vals = [float(s.util_pct) for s in gpu
                     if isinstance(s.util_pct, (int, float)) and not isinstance(s.util_pct, bool)
                     and 0 <= s.util_pct <= 100 and math.isfinite(s.util_pct)]
        m.gpu_util_sample_count = len(util_vals)
        if gpu:
            if util_vals:
                m.gpu_util_avg = sum(util_vals) / len(util_vals)
            power_vals = [float(s.power_w) for s in gpu if s.power_w is not None and s.power_w >= 0]
            if power_vals:
                m.gpu_power_avg_w = sum(power_vals) / len(power_vals)
            mem_vals = [float(s.mem_used_mb) for s in gpu if s.mem_used_mb is not None and s.mem_used_mb >= 0]
            if mem_vals:
                m.gpu_mem_peak_mb = max(mem_vals)
            gpu_temps = [float(s.temp_c) for s in gpu if s.temp_c is not None and s.temp_c > 0]
            if gpu_temps:
                m.gpu_temp_max_c = max(gpu_temps)

        if cpu:
            vals = [s.overall_pct for s in cpu]
            m.cpu_util_avg = sum(vals) / len(vals)
            m.cpu_util_max = max(vals)
            freq_vals = [float(s.freq_mhz) for s in cpu if s.freq_mhz and s.freq_mhz > 0]
            if freq_vals:
                m.cpu_freq_avg_mhz = sum(freq_vals) / len(freq_vals)
            cpu_temps = [float(s.temp_c) for s in cpu if s.temp_c and s.temp_c > 0]
            if cpu_temps:
                m.cpu_temp_max_c = max(cpu_temps)

        if proc:
            vals = [s.cpu_pct for s in proc]
            m.ffmpeg_cpu_util_avg = sum(vals) / len(vals)
            m.ffmpeg_cpu_util_max = max(vals)

        if peak_mem > 0:
            m.peak_memory_mb = peak_mem / (1024.0 * 1024.0)

        if self._ffmpeg_io_start and self._ffmpeg_io_end:
            read_delta = max(0.0, self._ffmpeg_io_end[0] - self._ffmpeg_io_start[0])
            write_delta = max(0.0, self._ffmpeg_io_end[1] - self._ffmpeg_io_start[1])
            m.ffmpeg_read_mb = read_delta / (1024.0 * 1024.0)
            m.ffmpeg_write_mb = write_delta / (1024.0 * 1024.0)

        if self._ffmpeg_cpu_time_start is not None and self._ffmpeg_cpu_time_end is not None:
            m.ffmpeg_cpu_time_s = max(0.0, self._ffmpeg_cpu_time_end - self._ffmpeg_cpu_time_start)

        m.battery_percent_start = self._battery_start_pct
        m.battery_percent_end = self._battery_end_pct
        if self._battery_start_pct is not None and self._battery_end_pct is not None:
            m.battery_percent_drop = max(0.0, self._battery_start_pct - self._battery_end_pct)
        m.power_source = self._power_source

        m.cpu_sample_count = len(cpu)
        m.gpu_sample_count = len(gpu)
        m.ffmpeg_sample_count = len(proc)
        m.battery_sample_count = len(battery)
        m.sample_count = max(len(cpu), len(gpu), len(proc), len(battery))
        if self._start_mono > 0 and self._end_mono >= self._start_mono:
            m.monitor_duration_ms = int(round((self._end_mono - self._start_mono) * 1000.0))

        m.thermal_throttle = self._detect_throttle(gpu, cpu)
        if self._energy_domains:
            m.energy_domains = [dict(item) for item in self._energy_domains]
            for item in self._energy_domains:
                source = str(item.get("source") or "").strip()
                state = str(item.get("counterState") or "").strip().lower()
                if source and state not in {"unsupported", "missing", "reset"}:
                    self._record_source(f"energy_{source}")
                elif source and state:
                    self._record_missing(f"energy_{source}_{state}")

        if m.cpu_sample_count == 0:
            self._record_missing("cpu_unavailable")
        if m.ffmpeg_sample_count == 0:
            self._record_missing("ffmpeg_unavailable")
        if self._allow_gpu_collection and m.gpu_sample_count == 0:
            self._record_missing("gpu_unavailable")
        if self._allow_gpu_collection and m.gpu_util_sample_count == 0:
            self._record_missing("gpu_utilization_unavailable")
        if m.battery_sample_count == 0:
            self._record_missing("battery_unavailable")
        if m.cpu_temp_max_c is None:
            self._record_missing("cpu_temp_unavailable")
        if self._allow_gpu_collection and m.gpu_temp_max_c is None:
            self._record_missing("gpu_temp_unavailable")

        if self._sources:
            m.telemetry_sources = ",".join(sorted(self._sources))
        if self._missing:
            m.telemetry_missing = ",".join(sorted(self._missing))
        return m

    def _detect_throttle(self, gpu: List[_GpuSample], cpu: List[_CpuSample]) -> Optional[bool]:
        throttled = False
        freq_samples = [s.freq_mhz for s in cpu if s.freq_mhz and s.freq_mhz > 0]
        if len(freq_samples) >= 8:
            q = max(1, len(freq_samples) // 4)
            early = sum(freq_samples[:q]) / q
            late = sum(freq_samples[-q:]) / q
            if early > 0 and (early - late) / early > 0.15:
                throttled = True
        cpu_temps = [s.temp_c for s in cpu if s.temp_c and s.temp_c > 0]
        if cpu_temps and max(cpu_temps) >= 95.0:
            throttled = True
        gpu_temps = [s.temp_c for s in gpu if s.temp_c and s.temp_c > 0]
        if gpu_temps and max(gpu_temps) >= 90.0:
            throttled = True
        if not freq_samples and not cpu_temps and not gpu_temps:
            return None
        return throttled

    def _collect_process_tree(self, *, require_complete: bool = False) -> List[psutil.Process]:
        pid = self._ffmpeg_pid
        if pid is None:
            return []
        try:
            root = psutil.Process(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return []
        except Exception:
            return []
        procs = [root]
        try:
            procs.extend(root.children(recursive=True))
        except Exception:
            if require_complete:
                self._record_missing("ffmpeg_cpu_unavailable")
                return []
        return procs

    def _read_ffmpeg_io_totals(self) -> Optional[Tuple[float, float]]:
        read_total = 0.0
        write_total = 0.0
        any_sample = False
        for proc in self._collect_process_tree():
            try:
                io = proc.io_counters()
                read_total += float(getattr(io, "read_bytes", 0.0) or 0.0)
                write_total += float(getattr(io, "write_bytes", 0.0) or 0.0)
                any_sample = True
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                continue
            except Exception:
                continue
        if not any_sample:
            return None
        return (read_total, write_total)

    def _read_ffmpeg_cpu_time(self) -> Optional[float]:
        cpu_time_s = 0.0
        any_sample = False
        for proc in self._collect_process_tree():
            try:
                t = proc.cpu_times()
                cpu_time_s += float(getattr(t, "user", 0.0) or 0.0)
                cpu_time_s += float(getattr(t, "system", 0.0) or 0.0)
                any_sample = True
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                continue
            except Exception:
                continue
        if not any_sample:
            return None
        return cpu_time_s

    def _read_battery_state(self) -> Tuple[Optional[float], Optional[str], Optional[str]]:
        try:
            battery = psutil.sensors_battery()
            if battery is not None:
                pct = float(battery.percent) if battery.percent is not None else None
                source = "ac" if bool(battery.power_plugged) else "battery"
                return pct, source, "battery_psutil"
        except Exception:
            pass
        if _DARWIN:
            try:
                raw = _run_command(["pmset", "-g", "batt"], timeout=1.0)
                pct, source = parse_pmset_battery_output(raw)
                if pct is not None or source is not None:
                    return pct, source, "battery_pmset"
            except Exception:
                pass
        return None, None, None

    def _detect_cpu_freq_reference_mhz(self) -> Optional[float]:
        refs: List[float] = []
        try:
            f = psutil.cpu_freq()
            if f and f.max and f.max > 0:
                n = normalize_cpu_freq_mhz(f.max)
                if n is not None:
                    refs.append(n)
        except Exception:
            pass
        try:
            f = psutil.cpu_freq()
            if f and f.current and f.current > 0:
                n = normalize_cpu_freq_mhz(f.current)
                if n is not None:
                    refs.append(n)
        except Exception:
            pass
        if _DARWIN:
            try:
                raw = _run_command(["sysctl", "-n", "hw.cpufrequency_max"], timeout=1.0).strip()
                hz = float(raw or "0")
                if hz > 0:
                    mhz = hz / 1_000_000.0
                    n = normalize_cpu_freq_mhz(mhz)
                    if n is not None:
                        refs.append(n)
                        self._record_source("cpu_freq_sysctl")
            except Exception:
                pass
        if not refs:
            return None
        return sum(refs) / len(refs)
