"""Observed runtime/device provenance; unknown is never replaced with host guesses."""
import functools
import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path

from . import config


def _command(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=10, check=False)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


@functools.lru_cache(maxsize=8)
def runtime_identity():
    def binary(path):
        digest = hashlib.sha256()
        try:
            with open(path, "rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            description = _command(["file", "-b", path])
            architectures = [arch for arch in ("arm64", "x86_64", "aarch64") if arch in description]
            return {"sha256": digest.hexdigest(), "architectures": architectures or ["unknown"]}
        except OSError:
            return {"sha256": None, "architectures": ["unknown"]}
    from .runtime_lock import runtime_dependency_records
    return {"runtimeDependencies": runtime_dependency_records(config.ffmpeg_exe()),
            "ffmpeg": binary(config.ffmpeg_exe()), "ffprobe": binary(config.ffprobe_exe()),
            "clientExecutionArchitecture": platform.machine().lower()}


def execution_provenance():
    runtime = runtime_identity()
    host = platform.machine().lower()
    if platform.system() == "Darwin" and _command(["sysctl", "-n", "hw.optional.arm64"]) == "1":
        host = "arm64"
    architectures = runtime["ffmpeg"]["architectures"]
    execution = host if host in architectures else architectures[0]
    return {"executionArchitecture": execution,
            "translationMode": "unknown" if execution == "unknown" else ("native" if execution == host else "translated"),
            "runtimeIdentity": runtime}


@functools.lru_cache(maxsize=32)
def selected_device(encoder):
    result = {"selection": "unknown", "deviceId": "unknown", "model": "unknown", "driverVersion": "unknown"}
    if encoder.endswith("_nvenc"):
        # The actual encode command explicitly selects -gpu 0. Telemetry uses the same index.
        raw = _command(["nvidia-smi", "--id=0", "--query-gpu=name,driver_version,pci.bus_id", "--format=csv,noheader,nounits"])
        fields = [value.strip() for value in raw.split(",")]
        result.update(selection="ffmpeg:-gpu=0", deviceId="nvenc:0")
        if len(fields) == 3:
            result.update(model=fields[0], driverVersion=fields[1], pciBusId=fields[2])
    elif encoder.endswith("_videotoolbox"):
        # VideoToolbox owns device selection; Apple Silicon has one integrated media engine.
        result.update(selection="videotoolbox-system-selected", deviceId="videotoolbox:system")
        raw = _command(["system_profiler", "SPDisplaysDataType", "-json"])
        try:
            adapters = json.loads(raw).get("SPDisplaysDataType", [])
            if len(adapters) == 1:
                result["model"] = adapters[0].get("sppci_model") or "unknown"
            else:
                result["deviceId"] = "unknown"
        except (ValueError, TypeError):
            pass
    elif not any(encoder.endswith(suffix) for suffix in ("_qsv", "_amf", "_vaapi")):
        result.update(selection="software", deviceId="cpu", model=platform.processor() or "cpu", driverVersion="not-applicable")
    return result
