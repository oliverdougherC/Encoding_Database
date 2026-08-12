import os
import platform
import re
import subprocess
from typing import Optional, Dict, List, Tuple

import psutil
try:
    import cpuinfo  # type: ignore
except Exception:
    cpuinfo = None  # type: ignore

try:
    import GPUtil  # type: ignore
except Exception:
    GPUtil = None  # type: ignore

from . import config


def _detect_gpu_vendors_from_name(name: str) -> List[str]:
    """Extract GPU vendor hints from a model name string."""
    vendors: List[str] = []
    ln = name.lower()
    if any(x in ln for x in ['nvidia', 'geforce', 'tesla', 'quadro', 'rtx', 'gtx']):
        vendors.append('nvidia')
    if any(x in ln for x in ['intel', 'iris', 'uhd', 'xe']):
        vendors.append('intel')
    if any(x in ln for x in ['amd', 'radeon', 'rx ', 'vega', 'navi']):
        vendors.append('amd')
    return vendors


def detect_hardware() -> config.HardwareInfo:
    cpu = cpuinfo.get_cpu_info() if cpuinfo is not None else {}
    cpu_model = cpu.get("brand_raw") or cpu.get("brand") or platform.processor() or "Unknown CPU"

    def normalize_apple_silicon_label(label: str) -> Optional[str]:
        try:
            if "Apple" not in label:
                return None
            m = re.search(r"Apple\s+M\s*([0-9])\s*(Pro|Max|Ultra)?", label, re.IGNORECASE)
            if not m:
                return None
            gen = m.group(1)
            tier = m.group(2) or ""
            tier = tier.title()
            parts = ["Apple", f"M{gen}"]
            if tier:
                parts.append(tier)
            return " ".join(parts)
        except Exception:
            return None

    gpu_model: Optional[str] = None
    vendors: List[str] = []
    try:
        if platform.system() == "Darwin" and ("Apple" in cpu_model):
            normalized = normalize_apple_silicon_label(cpu_model)
            if normalized:
                cpu_model = normalized
            gpu_model = cpu_model
            vendors.append('apple')
        elif GPUtil is not None:
            try:
                gpus = GPUtil.getGPUs()
                if gpus:
                    names = []
                    for g in gpus:
                        try:
                            n = str(getattr(g, 'name', '') or '')
                            if n:
                                names.append(n)
                        except Exception:
                            pass
                    if names:
                        gpu_model = gpu_model or names[0]
                        for n in names:
                            ln = n.lower()
                            if any(x in ln for x in ['nvidia', 'geforce', 'tesla', 'quadro']):
                                vendors.append('nvidia')
                            if any(x in ln for x in ['intel', 'iris', 'uhd', 'xe']):
                                vendors.append('intel')
                            if any(x in ln for x in ['amd', 'radeon', 'rx ', 'vega']):
                                vendors.append('amd')
            except Exception:
                gpu_model = None
        # Windows fallback: query WMI for GPU model when NVML is not available
        if not gpu_model and platform.system() == "Windows":
            try:
                probe = subprocess.run([
                    "powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name | ConvertTo-Json -Compress"
                ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5)
                names_raw = (probe.stdout or "").strip()
                if names_raw:
                    try:
                        import json as _json
                        names = _json.loads(names_raw)
                        if isinstance(names, list) and names:
                            gpu_model = str(names[0])
                            for n in names:
                                ln = str(n).lower()
                                if any(x in ln for x in ['nvidia', 'geforce', 'tesla', 'quadro']):
                                    vendors.append('nvidia')
                                if any(x in ln for x in ['intel', 'iris', 'uhd', 'xe']):
                                    vendors.append('intel')
                                if any(x in ln for x in ['amd', 'radeon', 'rx ', 'vega']):
                                    vendors.append('amd')
                        elif isinstance(names, str) and names:
                            gpu_model = names
                            vendors.extend(_detect_gpu_vendors_from_name(names))
                    except Exception:
                        for line in names_raw.splitlines():
                            t = line.strip()
                            if t:
                                gpu_model = t
                                vendors.extend(_detect_gpu_vendors_from_name(t))
                                break
            except Exception:
                gpu_model = gpu_model or None
        # Linux vendor hints via lspci (best-effort)
        if platform.system() == 'Linux':
            try:
                proc = subprocess.run(
                    ['lspci', '-nn'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=3
                )
                txt = (proc.stdout or '').lower()
                for line in txt.splitlines():
                    if 'vga' in line or '3d' in line:
                        vendors.extend(_detect_gpu_vendors_from_name(line))
            except Exception:
                pass
    except Exception:
        gpu_model = None

    ram_gb = int(round(psutil.virtual_memory().total / (1024 ** 3)))
    os_name = f"{platform.system()} {platform.release()}"
    # Deduplicate vendors
    vset: Dict[str, bool] = {}
    vlist: List[str] = []
    for v in vendors:
        if v and not vset.get(v):
            vset[v] = True
            vlist.append(v)
    return config.HardwareInfo(cpu_model, gpu_model, ram_gb, os_name, vlist)


def get_physical_core_count() -> int:
    """Return the number of physical CPU cores (not threads) if available."""
    try:
        n = psutil.cpu_count(logical=False)
        if isinstance(n, int) and n and n > 0:
            return n
    except Exception:
        pass
    try:
        n_logical = os.cpu_count() or 0
        return max(1, int(n_logical // 2) if n_logical and n_logical > 1 else int(n_logical or 1))
    except Exception:
        return 4


def resolve_batch_size(requested: Optional[int]) -> int:
    try:
        if isinstance(requested, int) and requested > 0:
            return max(1, requested)
    except Exception:
        pass
    return max(1, int(get_physical_core_count()))


def measure_background_cpu_load(seconds: float = 3.0, interval: float = 0.5) -> float:
    samples: List[float] = []
    elapsed: float = 0.0
    try:
        while elapsed < seconds:
            samples.append(psutil.cpu_percent(interval=interval))
            elapsed += interval
        return float(sum(samples) / max(1, len(samples)))
    except Exception:
        return 0.0


def detect_virtualization(hardware: config.HardwareInfo) -> Tuple[bool, str]:
    hints: List[str] = []
    try:
        info = cpuinfo.get_cpu_info() if cpuinfo is not None else {}
        info = info or {}
        flags = set(info.get('flags') or [])
        if 'hypervisor' in flags:
            hints.append('cpu_hypervisor_flag')
    except Exception:
        pass
    try:
        dmi_paths = ['/sys/class/dmi/id/product_name', '/sys/class/dmi/id/sys_vendor']
        for p in dmi_paths:
            if os.path.exists(p):
                try:
                    with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                        txt = f.read().lower()
                    if any(x in txt for x in ['kvm', 'qemu', 'vmware', 'virtualbox', 'hyper-v', 'parallels']):
                        hints.append(f'dmi:{os.path.basename(p)}')
                except Exception:
                    continue
    except Exception:
        pass
    try:
        if hardware.gpuModel and any(x in str(hardware.gpuModel).lower() for x in ['microsoft basic render', 'svga', 'vbox', 'virtio', 'llvmpipe']):
            hints.append('gpu_virtual_like')
    except Exception:
        pass
    reason = ','.join(hints)[:200] if hints else ''
    return (len(hints) > 0, reason)
