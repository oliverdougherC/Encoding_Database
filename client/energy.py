from __future__ import annotations

import os
import platform
import threading
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import pynvml  # type: ignore

    _PYNVML_AVAILABLE = True
except Exception:
    pynvml = None  # type: ignore
    _PYNVML_AVAILABLE = False

_NVML_INITIALIZED = False
_NVML_INIT_LOCK = threading.Lock()
_LINUX = platform.system() == "Linux"


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


@dataclass(frozen=True)
class EnergySnapshot:
    domain: str
    domainType: str
    source: str
    collectorVersion: str
    counterUnit: str
    counterValue: Optional[float]
    counterMax: Optional[float] = None
    deviceIndex: Optional[int] = None
    deviceName: Optional[str] = None
    state: str = "ok"
    reason: Optional[str] = None


def unsupported_snapshot(
    *,
    domain: str,
    domain_type: str,
    source: str,
    collector_version: str,
    reason: str,
    counter_unit: str = "joule",
    device_index: Optional[int] = None,
    device_name: Optional[str] = None,
) -> EnergySnapshot:
    return EnergySnapshot(
        domain=domain,
        domainType=domain_type,
        source=source,
        collectorVersion=collector_version,
        counterUnit=counter_unit,
        counterValue=None,
        counterMax=None,
        deviceIndex=device_index,
        deviceName=device_name,
        state="unsupported",
        reason=reason,
    )


def _native_to_joules(value: Optional[float], unit: str) -> Optional[float]:
    if value is None:
        return None
    if unit == "millijoule":
        return value / 1000.0
    if unit == "microjoule":
        return value / 1_000_000.0
    if unit == "joule":
        return value
    return None


def finalize_energy_measurement(
    start: Optional[EnergySnapshot],
    end: Optional[EnergySnapshot],
    *,
    frame_count: Optional[int] = None,
    source_duration_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    template = end or start or unsupported_snapshot(
        domain="unknown",
        domain_type="unknown",
        source="unknown",
        collector_version="unknown",
        reason="energy_snapshot_missing",
    )
    record: Dict[str, Any] = {
        "domain": template.domain,
        "domainType": template.domainType,
        "source": template.source,
        "collectorVersion": template.collectorVersion,
        "counterUnit": template.counterUnit,
        "startCounter": round(float(start.counterValue), 6) if start and start.counterValue is not None else None,
        "endCounter": round(float(end.counterValue), 6) if end and end.counterValue is not None else None,
        "counterMax": round(float(end.counterMax), 6) if end and end.counterMax is not None else (
            round(float(start.counterMax), 6) if start and start.counterMax is not None else None
        ),
        "deltaJoules": None,
        "joulesPerFrame": None,
        "joulesPerSourceSecond": None,
        "counterState": "ok",
        "reason": None,
        "deviceIndex": template.deviceIndex,
        "deviceName": template.deviceName,
    }

    if start is None or end is None:
        record["counterState"] = "missing"
        record["reason"] = "energy_snapshot_missing"
        return record

    if start.state != "ok" or end.state != "ok":
        failed = end if end.state != "ok" else start
        record["counterState"] = failed.state
        record["reason"] = failed.reason
        return record

    if start.counterValue is None or end.counterValue is None:
        record["counterState"] = "missing"
        record["reason"] = "energy_counter_missing"
        return record

    delta_native = end.counterValue - start.counterValue
    if delta_native < 0:
        max_counter = end.counterMax if end.counterMax is not None else start.counterMax
        if max_counter is not None and max_counter > start.counterValue:
            delta_native = (max_counter - start.counterValue) + end.counterValue
            record["counterState"] = "wrapped"
        else:
            record["counterState"] = "reset"
            record["reason"] = "energy_counter_decreased_without_wrap_range"
            return record

    delta_joules = _native_to_joules(delta_native, template.counterUnit)
    if delta_joules is None:
        record["counterState"] = "unsupported"
        record["reason"] = f"unsupported_counter_unit:{template.counterUnit}"
        return record

    record["deltaJoules"] = round(delta_joules, 6)
    if isinstance(frame_count, int) and frame_count > 0:
        record["joulesPerFrame"] = round(delta_joules / float(frame_count), 9)
    if isinstance(source_duration_seconds, (int, float)) and source_duration_seconds > 0:
        record["joulesPerSourceSecond"] = round(delta_joules / float(source_duration_seconds), 9)
    return record


def derive_energy_intensities(
    records: Iterable[Dict[str, Any]],
    *,
    frame_count: Optional[int] = None,
    source_duration_seconds: Optional[float] = None,
) -> List[Dict[str, Any]]:
    derived: List[Dict[str, Any]] = []
    for raw in records:
        record = dict(raw)
        delta = record.get("deltaJoules")
        record["joulesPerFrame"] = None
        record["joulesPerSourceSecond"] = None
        if isinstance(delta, (int, float)) and delta >= 0:
            if isinstance(frame_count, int) and frame_count > 0:
                record["joulesPerFrame"] = round(float(delta) / float(frame_count), 9)
            if isinstance(source_duration_seconds, (int, float)) and source_duration_seconds > 0:
                record["joulesPerSourceSecond"] = round(float(delta) / float(source_duration_seconds), 9)
        derived.append(record)
    return derived


def _powercap_domain_type(name: str) -> str:
    lower = str(name or "").strip().lower()
    if lower.startswith("package-"):
        return "cpu-package"
    if "dram" in lower:
        return "dram"
    if "psys" in lower or "system" in lower:
        return "system"
    return "power-domain"


def collect_powercap_snapshot(*, root: str = "/sys/class/powercap") -> List[EnergySnapshot]:
    source = "linux-powercap-rapl"
    collector_version = "sysfs-v1"
    if not _LINUX:
        return [
            unsupported_snapshot(
                domain="rapl",
                domain_type="cpu-package",
                source=source,
                collector_version=collector_version,
                reason="powercap_not_linux",
                counter_unit="microjoule",
            )
        ]
    if not os.path.isdir(root):
        return [
            unsupported_snapshot(
                domain="rapl",
                domain_type="cpu-package",
                source=source,
                collector_version=collector_version,
                reason="powercap_root_missing",
                counter_unit="microjoule",
            )
        ]

    snapshots: List[EnergySnapshot] = []
    for entry in sorted(os.listdir(root)):
        path = os.path.join(root, entry)
        if not os.path.isdir(path):
            continue
        energy_path = os.path.join(path, "energy_uj")
        if not os.path.isfile(energy_path):
            continue
        try:
            with open(os.path.join(path, "name"), "r", encoding="utf-8", errors="ignore") as handle:
                label = handle.read().strip() or entry
        except Exception:
            label = entry
        try:
            with open(energy_path, "r", encoding="utf-8", errors="ignore") as handle:
                counter_value = float(handle.read().strip())
        except Exception:
            snapshots.append(
                unsupported_snapshot(
                    domain=f"rapl:{entry}:{label}",
                    domain_type=_powercap_domain_type(label),
                    source=source,
                    collector_version=collector_version,
                    reason="powercap_read_failed",
                    counter_unit="microjoule",
                )
            )
            continue
        counter_max: Optional[float] = None
        try:
            with open(
                os.path.join(path, "max_energy_range_uj"),
                "r",
                encoding="utf-8",
                errors="ignore",
            ) as handle:
                counter_max = float(handle.read().strip())
        except Exception:
            counter_max = None
        snapshots.append(
            EnergySnapshot(
                domain=f"rapl:{entry}:{label}",
                domainType=_powercap_domain_type(label),
                source=source,
                collectorVersion=collector_version,
                counterUnit="microjoule",
                counterValue=counter_value,
                counterMax=counter_max,
            )
        )
    if snapshots:
        return snapshots
    return [
        unsupported_snapshot(
            domain="rapl",
            domain_type="cpu-package",
            source=source,
            collector_version=collector_version,
            reason="powercap_no_energy_domains",
            counter_unit="microjoule",
        )
    ]


def collect_nvml_snapshot(*, device_indexes: Optional[Iterable[int]]) -> List[EnergySnapshot]:
    source = "nvml-total-energy"
    collector_version = str(getattr(pynvml, "__version__", "pynvml")) if pynvml is not None else "pynvml"
    indexes = [int(index) for index in (device_indexes or [])]
    if not indexes:
        return [
            unsupported_snapshot(
                domain="gpu-board",
                domain_type="gpu-board",
                source=source,
                collector_version=collector_version,
                reason="nvml_device_not_selected",
                counter_unit="millijoule",
            )
        ]
    if not _ensure_nvml():
        return [
            unsupported_snapshot(
                domain=f"gpu-board:{indexes[0]}",
                domain_type="gpu-board",
                source=source,
                collector_version=collector_version,
                reason="nvml_unavailable",
                counter_unit="millijoule",
                device_index=indexes[0],
            )
        ]

    snapshots: List[EnergySnapshot] = []
    for index in indexes:
        domain = f"gpu-board:{index}"
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(index)
            name_raw = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name_raw, bytes):
                device_name = name_raw.decode("utf-8", errors="ignore").strip() or None
            else:
                device_name = str(name_raw).strip() or None
            counter_value = float(pynvml.nvmlDeviceGetTotalEnergyConsumption(handle))
            snapshots.append(
                EnergySnapshot(
                    domain=domain,
                    domainType="gpu-board",
                    source=source,
                    collectorVersion=collector_version,
                    counterUnit="millijoule",
                    counterValue=counter_value,
                    deviceIndex=index,
                    deviceName=device_name,
                )
            )
        except Exception as exc:
            reason = getattr(exc, "__class__", type(exc)).__name__.lower()
            snapshots.append(
                unsupported_snapshot(
                    domain=domain,
                    domain_type="gpu-board",
                    source=source,
                    collector_version=collector_version,
                    reason=f"nvml_total_energy_unsupported:{reason}",
                    counter_unit="millijoule",
                    device_index=index,
                )
            )
    return snapshots


class EnergyCollector:
    def __init__(
        self,
        *,
        collect_nvml: bool = False,
        nvml_device_indexes: Optional[Iterable[int]] = None,
        collect_powercap: bool = True,
        powercap_root: str = "/sys/class/powercap",
    ) -> None:
        self._collect_nvml = bool(collect_nvml)
        self._nvml_device_indexes = list(nvml_device_indexes or [])
        self._collect_powercap = bool(collect_powercap)
        self._powercap_root = powercap_root
        self._start_snapshots: List[EnergySnapshot] = []

    def start(self) -> None:
        self._start_snapshots = self._collect_snapshots()

    def stop(self) -> List[Dict[str, Any]]:
        end_snapshots = self._collect_snapshots()
        start_map = {(item.source, item.domain): item for item in self._start_snapshots}
        end_map = {(item.source, item.domain): item for item in end_snapshots}
        ordered_keys = sorted(set(start_map.keys()) | set(end_map.keys()))
        return [
            finalize_energy_measurement(start_map.get(key), end_map.get(key))
            for key in ordered_keys
        ]

    def _collect_snapshots(self) -> List[EnergySnapshot]:
        snapshots: List[EnergySnapshot] = []
        if self._collect_nvml:
            snapshots.extend(collect_nvml_snapshot(device_indexes=self._nvml_device_indexes))
        if self._collect_powercap:
            snapshots.extend(collect_powercap_snapshot(root=self._powercap_root))
        return snapshots


def serialize_energy_domains(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    serialized: List[Dict[str, Any]] = []
    for record in records:
        clean: Dict[str, Any] = {}
        for key, value in record.items():
            if value is None:
                clean[key] = None
            elif isinstance(value, float):
                clean[key] = round(value, 9)
            else:
                clean[key] = value
        serialized.append(clean)
    return serialized
