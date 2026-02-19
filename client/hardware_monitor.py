"""Background hardware metrics sampling during FFmpeg encodes.

Collects GPU utilization/power (NVIDIA via pynvml), CPU utilization (psutil),
process memory (psutil), and thermal throttling detection.
"""

import threading
import time
from dataclasses import dataclass
from typing import Optional, List, Tuple

import psutil

# Optional NVIDIA GPU monitoring
try:
    import pynvml  # type: ignore
    _PYNVML_AVAILABLE = True
except Exception:
    pynvml = None  # type: ignore
    _PYNVML_AVAILABLE = False

# Optional GPU telemetry fallback (best-effort)
try:
    import GPUtil  # type: ignore
    _GPUTIL_AVAILABLE = True
except Exception:
    GPUtil = None  # type: ignore
    _GPUTIL_AVAILABLE = False

_NVML_INITIALIZED = False
_NVML_INIT_LOCK = threading.Lock()


def _ensure_nvml() -> bool:
    """Lazily initialize NVML once per process. Returns True if usable."""
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


class HardwareMonitor:
    """Samples hardware metrics in a background thread while an encode runs."""

    def __init__(self, ffmpeg_pid: Optional[int] = None, interval: float = 0.5):
        self._ffmpeg_pid = ffmpeg_pid
        self._interval = max(0.1, interval)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._gpu_samples: List[_GpuSample] = []
        self._cpu_samples: List[_CpuSample] = []
        self._proc_samples: List[_ProcSample] = []
        self._memory_peak_bytes: float = 0.0
        self._lock = threading.Lock()
        self._gpu_handle = None
        self._start_ts: float = 0.0
        self._end_ts: float = 0.0
        self._battery_start_pct: Optional[float] = None
        self._battery_end_pct: Optional[float] = None
        self._power_source: Optional[str] = None
        self._ffmpeg_io_start: Optional[Tuple[float, float]] = None
        self._ffmpeg_io_end: Optional[Tuple[float, float]] = None
        self._ffmpeg_cpu_time_start: Optional[float] = None
        self._ffmpeg_cpu_time_end: Optional[float] = None

    def start(self) -> None:
        self._stop_event.clear()
        self._gpu_samples.clear()
        self._cpu_samples.clear()
        self._proc_samples.clear()
        self._memory_peak_bytes = 0.0
        self._start_ts = time.time()
        self._end_ts = 0.0
        self._battery_start_pct, source = self._read_battery_state()
        self._battery_end_pct = None
        self._power_source = source
        self._ffmpeg_io_start = self._read_ffmpeg_io_totals()
        self._ffmpeg_io_end = None
        self._ffmpeg_cpu_time_start = self._read_ffmpeg_cpu_time()
        self._ffmpeg_cpu_time_end = None

        if _ensure_nvml():
            try:
                self._gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            except Exception:
                self._gpu_handle = None
        else:
            self._gpu_handle = None

        # Prime psutil so the first real sample isn't always 0
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass
        for proc in self._collect_process_tree():
            try:
                proc.cpu_percent(interval=None)
            except Exception:
                continue

        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()

    def stop(self) -> HardwareMetrics:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        self._end_ts = time.time()
        self._ffmpeg_io_end = self._read_ffmpeg_io_totals()
        self._ffmpeg_cpu_time_end = self._read_ffmpeg_cpu_time()
        self._battery_end_pct, source = self._read_battery_state()
        if source:
            self._power_source = source
        return self._aggregate()

    # -- internal -----------------------------------------------------------

    def _sample_loop(self) -> None:
        while not self._stop_event.is_set():
            self._take_sample()
            self._stop_event.wait(self._interval)

    def _take_sample(self) -> None:
        self._sample_gpu()
        self._sample_cpu()
        self._sample_ffmpeg_process()
        self._sample_memory()

    def _sample_gpu(self) -> None:
        if self._gpu_handle is not None:
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(self._gpu_handle)
                power_w: Optional[float] = None
                try:
                    power_w = float(pynvml.nvmlDeviceGetPowerUsage(self._gpu_handle)) / 1000.0
                except Exception:
                    power_w = None
                mem_used_mb: Optional[float] = None
                try:
                    mem_info = pynvml.nvmlDeviceGetMemoryInfo(self._gpu_handle)
                    mem_used_mb = float(mem_info.used) / (1024 * 1024)
                except Exception:
                    mem_used_mb = None
                temp_c: Optional[float] = None
                try:
                    temp_c = float(
                        pynvml.nvmlDeviceGetTemperature(
                            self._gpu_handle, pynvml.NVML_TEMPERATURE_GPU
                        )
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
                return
            except Exception:
                pass

        # Fallback path for non-NVML systems (best-effort only)
        if not _GPUTIL_AVAILABLE:
            return
        try:
            gpus = GPUtil.getGPUs()  # type: ignore[attr-defined]
            if not gpus:
                return
            g = gpus[0]
            util_raw = getattr(g, 'load', None)
            util_pct = float(util_raw) * 100.0 if isinstance(util_raw, (int, float)) else None
            mem_raw = getattr(g, 'memoryUsed', None)
            mem_used_mb = float(mem_raw) if isinstance(mem_raw, (int, float)) else None
            power_raw = getattr(g, 'powerDraw', None)
            power_w = float(power_raw) if isinstance(power_raw, (int, float)) and power_raw >= 0 else None
            temp_raw = getattr(g, 'temperature', None)
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
        except Exception:
            pass

    def _sample_cpu(self) -> None:
        try:
            overall = psutil.cpu_percent(interval=None)
            freq: Optional[float] = None
            try:
                f = psutil.cpu_freq()
                if f and f.current and f.current > 0:
                    freq = float(f.current)
            except Exception:
                pass
            temp: Optional[float] = None
            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    for name in ('coretemp', 'k10temp', 'cpu_thermal',
                                 'cpu-thermal', 'acpitz'):
                        if name in temps and temps[name]:
                            readings = [e.current for e in temps[name]
                                        if e.current and e.current > 0]
                            if readings:
                                temp = max(readings)
                                break
            except Exception:
                pass
            sample = _CpuSample(overall_pct=float(overall), freq_mhz=freq,
                                temp_c=temp)
            with self._lock:
                self._cpu_samples.append(sample)
        except Exception:
            pass

    def _sample_ffmpeg_process(self) -> None:
        total_pct = 0.0
        any_sample = False
        for proc in self._collect_process_tree():
            try:
                pct = proc.cpu_percent(interval=None)
                if pct >= 0:
                    total_pct += float(pct)
                    any_sample = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception:
                continue
        if any_sample:
            with self._lock:
                self._proc_samples.append(_ProcSample(cpu_pct=total_pct))

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

    def _aggregate(self) -> HardwareMetrics:
        m = HardwareMetrics()

        with self._lock:
            gpu = list(self._gpu_samples)
            cpu = list(self._cpu_samples)
            proc = list(self._proc_samples)
            peak_mem = self._memory_peak_bytes

        # GPU metrics
        if gpu:
            util_vals = [float(s.util_pct) for s in gpu if s.util_pct is not None]
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

        # CPU metrics
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

        # FFmpeg process metrics
        if proc:
            vals = [s.cpu_pct for s in proc]
            m.ffmpeg_cpu_util_avg = sum(vals) / len(vals)
            m.ffmpeg_cpu_util_max = max(vals)

        # Memory
        if peak_mem > 0:
            m.peak_memory_mb = peak_mem / (1024 * 1024)

        # Process I/O deltas
        if self._ffmpeg_io_start and self._ffmpeg_io_end:
            read_delta = max(0.0, self._ffmpeg_io_end[0] - self._ffmpeg_io_start[0])
            write_delta = max(0.0, self._ffmpeg_io_end[1] - self._ffmpeg_io_start[1])
            m.ffmpeg_read_mb = read_delta / (1024 * 1024)
            m.ffmpeg_write_mb = write_delta / (1024 * 1024)

        # Process CPU-time delta
        if self._ffmpeg_cpu_time_start is not None and self._ffmpeg_cpu_time_end is not None:
            m.ffmpeg_cpu_time_s = max(0.0, self._ffmpeg_cpu_time_end - self._ffmpeg_cpu_time_start)

        # Power source / battery metrics
        m.battery_percent_start = self._battery_start_pct
        m.battery_percent_end = self._battery_end_pct
        if self._battery_start_pct is not None and self._battery_end_pct is not None:
            m.battery_percent_drop = max(0.0, self._battery_start_pct - self._battery_end_pct)
        m.power_source = self._power_source

        # Sampling stats
        m.sample_count = max(len(cpu), len(gpu), len(proc))
        if self._start_ts > 0 and self._end_ts >= self._start_ts:
            m.monitor_duration_ms = int(round((self._end_ts - self._start_ts) * 1000.0))

        # Thermal throttling detection
        m.thermal_throttle = self._detect_throttle(gpu, cpu)

        return m

    def _detect_throttle(self, gpu: List[_GpuSample],
                         cpu: List[_CpuSample]) -> Optional[bool]:
        """Heuristic throttle detection based on frequency drop and temperature."""
        throttled = False

        # CPU frequency-based detection: compare first 25% avg vs last 25%
        freq_samples = [s.freq_mhz for s in cpu if s.freq_mhz and s.freq_mhz > 0]
        if len(freq_samples) >= 8:
            q = max(1, len(freq_samples) // 4)
            early = sum(freq_samples[:q]) / q
            late = sum(freq_samples[-q:]) / q
            if early > 0 and (early - late) / early > 0.15:
                throttled = True

        # CPU temperature threshold
        cpu_temps = [s.temp_c for s in cpu if s.temp_c and s.temp_c > 0]
        if cpu_temps and max(cpu_temps) >= 95.0:
            throttled = True

        # GPU temperature threshold
        gpu_temps = [s.temp_c for s in gpu if s.temp_c and s.temp_c > 0]
        if gpu_temps and max(gpu_temps) >= 90.0:
            throttled = True

        if not freq_samples and not cpu_temps and not gpu_temps:
            return None

        return throttled

    def _collect_process_tree(self) -> List[psutil.Process]:
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
            pass
        return procs

    def _read_ffmpeg_io_totals(self) -> Optional[Tuple[float, float]]:
        read_total = 0.0
        write_total = 0.0
        any_sample = False
        for proc in self._collect_process_tree():
            try:
                io = proc.io_counters()
                read_total += float(getattr(io, 'read_bytes', 0.0) or 0.0)
                write_total += float(getattr(io, 'write_bytes', 0.0) or 0.0)
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
                cpu_time_s += float(getattr(t, 'user', 0.0) or 0.0)
                cpu_time_s += float(getattr(t, 'system', 0.0) or 0.0)
                any_sample = True
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                continue
            except Exception:
                continue
        if not any_sample:
            return None
        return cpu_time_s

    def _read_battery_state(self) -> Tuple[Optional[float], Optional[str]]:
        try:
            b = psutil.sensors_battery()
            if b is None:
                return (None, None)
            pct = float(b.percent) if b.percent is not None else None
            source = "ac" if bool(b.power_plugged) else "battery"
            return (pct, source)
        except Exception:
            return (None, None)
