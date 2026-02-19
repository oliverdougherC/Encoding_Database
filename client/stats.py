from typing import Dict, Any, List, Tuple

from . import config
from .hardware import detect_virtualization


def _median(values: List[float]) -> float:
    v = sorted([float(x) for x in values])
    n = len(v)
    if n == 0:
        return 0.0
    m = n // 2
    if n % 2 == 1:
        return v[m]
    return (v[m - 1] + v[m]) / 2.0


def _mad(values: List[float], med: float) -> float:
    dev = [abs(float(x) - med) for x in values]
    return _median(dev)


def _robust_z(x: float, med: float, mad_val: float) -> float:
    denom = (1.4826 * mad_val) if mad_val > 0 else 1.0
    return (float(x) - med) / denom


def baseline_is_suspect(current: Dict[str, Any], rows: List[Dict[str, Any]]) -> Tuple[bool, str]:
    try:
        key = (
            current.get('cpuModel'),
            current.get('gpuModel'),
            int(current.get('ramGB') or 0),
            current.get('os'),
            current.get('codec'),
            current.get('preset'),
            int(current.get('crf') if current.get('crf') is not None else 24),
        )
        same = [r for r in rows if (
            r.get('cpuModel') == key[0] and
            (r.get('gpuModel') or None) == key[1] and
            int(r.get('ramGB') or 0) == key[2] and
            r.get('os') == key[3] and
            r.get('codec') == key[4] and
            r.get('preset') == key[5] and
            int(r.get('crf') or 24) == key[6]
        )]
        if not same:
            return (False, '')
        fps_arr = [float(r.get('fps') or 0) for r in same if float(r.get('fps') or 0) > 0]
        size_arr = [float(r.get('fileSizeBytes') or 0) for r in same if float(r.get('fileSizeBytes') or 0) > 0]
        vmaf_arr = [float(r.get('vmaf') or 0) for r in same if r.get('vmaf') is not None]
        ssim_arr = [float(r.get('ssim') or 0) for r in same if r.get('ssim') is not None]
        psnr_arr = [float(r.get('psnr') or 0) for r in same if r.get('psnr') is not None]
        fps_med = _median(fps_arr) if fps_arr else float(current.get('fps') or 0)
        size_med = _median(size_arr) if size_arr else float(current.get('fileSizeBytes') or 0)
        vmaf_med = _median(vmaf_arr) if vmaf_arr else float(current.get('vmaf') or 0)
        ssim_med = _median(ssim_arr) if ssim_arr else float(current.get('ssim') or 0)
        psnr_med = _median(psnr_arr) if psnr_arr else float(current.get('psnr') or 0)
        fps_mad = _mad(fps_arr, fps_med) if fps_arr else 0.0
        size_mad = _mad(size_arr, size_med) if size_arr else 0.0
        vmaf_mad = _mad(vmaf_arr, vmaf_med) if vmaf_arr else 0.0
        ssim_mad = _mad(ssim_arr, ssim_med) if ssim_arr else 0.0
        psnr_mad = _mad(psnr_arr, psnr_med) if psnr_arr else 0.0
        fps_z = _robust_z(float(current.get('fps') or 0), fps_med, fps_mad)
        size_z = _robust_z(float(current.get('fileSizeBytes') or 0), size_med, size_mad)
        vmaf_val = current.get('vmaf')
        vmaf_z = _robust_z(float(vmaf_val), vmaf_med, vmaf_mad) if vmaf_val is not None else 0.0
        ssim_val = current.get('ssim')
        ssim_z = _robust_z(float(ssim_val), ssim_med, ssim_mad) if ssim_val is not None else 0.0
        psnr_val = current.get('psnr')
        psnr_z = _robust_z(float(psnr_val), psnr_med, psnr_mad) if psnr_val is not None else 0.0
        max_abs = max(abs(fps_z), abs(size_z), abs(vmaf_z), abs(ssim_z), abs(psnr_z))
        if max_abs > 3.0:
            return (True, f'baseline_outlier|z={max_abs:.2f}')
        return (False, '')
    except Exception:
        return (False, '')


def should_skip_submission(*, hardware: config.HardwareInfo, payload: Dict[str, Any], background_cpu_pct: float, baseline_rows: List[Dict[str, Any]], background_threshold: float = 20.0) -> Tuple[bool, str]:
    is_vm, vm_reason = detect_virtualization(hardware)
    if is_vm:
        return True, f'vm_detected:{vm_reason}'
    try:
        if background_cpu_pct > background_threshold:
            return True, f'high_background_load:{background_cpu_pct:.1f}%'
    except Exception:
        pass
    suspect, reason = baseline_is_suspect(payload, baseline_rows)
    if suspect:
        return True, reason
    return False, ''
