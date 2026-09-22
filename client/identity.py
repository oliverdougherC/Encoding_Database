"""Observed runtime/device provenance; unknown is never replaced with host guesses."""
import functools
import hashlib
import json
import os
import platform
import subprocess
import struct
import shutil
from pathlib import Path

from . import config
from .console_policy import hidden_console_kwargs


def _command(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=10, check=False,
                                **hidden_console_kwargs())
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def normalize_architecture(value):
    normalized = str(value or "").strip().lower()
    return {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64", "i386": "x86", "i686": "x86"}.get(normalized, normalized or "unknown")


def executable_architectures(path):
    """Read bounded native headers directly; Windows does not provide Unix file(1)."""
    cpu_names = {0x0100000C: "arm64", 0x01000007: "x86_64", 7: "x86", 12: "arm"}
    try:
        with open(path, "rb") as handle:
            header = handle.read(4096)
            if header[:4] == b"\x7fELF" and len(header) >= 20 and header[4] in (1, 2) and header[5] in (1, 2):
                machine = struct.unpack_from(("<" if header[5] == 1 else ">") + "H", header, 18)[0]
                return [{62: "x86_64", 183: "arm64", 3: "x86", 40: "arm"}.get(machine, "unknown")]
            if header[:2] == b"MZ" and len(header) >= 64:
                offset = struct.unpack_from("<I", header, 60)[0]
                # A malicious or corrupt offset must not trigger an unbounded read.
                if offset < 64 or offset > 16 * 1024 * 1024:
                    return ["unknown"]
                handle.seek(offset)
                pe = handle.read(6)
                if len(pe) == 6 and pe[:4] == b"PE\0\0":
                    return [{0x8664: "x86_64", 0xAA64: "arm64", 0x14C: "x86"}.get(struct.unpack_from("<H", pe, 4)[0], "unknown")]
            thin_magic = {b"\xcf\xfa\xed\xfe": "<", b"\xce\xfa\xed\xfe": "<", b"\xfe\xed\xfa\xcf": ">", b"\xfe\xed\xfa\xce": ">"}
            if header[:4] in thin_magic and len(header) >= 28:
                return [cpu_names.get(struct.unpack_from(thin_magic[header[:4]] + "I", header, 4)[0], "unknown")]
            fat_magic = {b"\xca\xfe\xba\xbe": (">", 20), b"\xbe\xba\xfe\xca": ("<", 20), b"\xca\xfe\xba\xbf": (">", 32), b"\xbf\xba\xfe\xca": ("<", 32)}
            if header[:4] in fat_magic and len(header) >= 8:
                endian, stride = fat_magic[header[:4]]
                count = struct.unpack_from(endian + "I", header, 4)[0]
                if 0 < count <= 64 and 8 + count * stride <= len(header):
                    return sorted({cpu_names.get(struct.unpack_from(endian + "I", header, 8 + index * stride)[0], "unknown") for index in range(count)})
    except (OSError, ValueError, struct.error):
        pass
    return ["unknown"]


def process_runtime_identity(executable):
    """Bind a process checkpoint to actual bytes, independent of extraction path.

    Read afresh at launch/resume: cached path metadata is insufficient to detect
    changed bytes with restored timestamps, especially on Windows.
    """
    from .runtime_lock import _sha256_path, runtime_dependency_records
    resolved = shutil.which(executable)
    if resolved is None:
        if not os.path.isfile(executable):
            raise FileNotFoundError(f"Cannot identify process executable: {executable}")
        resolved = os.path.abspath(executable)
    return {"schemaVersion": 1, "executableSha256": _sha256_path(resolved),
            "runtimeDependencies": runtime_dependency_records(resolved)}


@functools.lru_cache(maxsize=8)
def runtime_identity():
    def binary(path):
        digest = hashlib.sha256()
        try:
            with open(path, "rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            architectures = executable_architectures(path)
            return {"sha256": digest.hexdigest(), "architectures": architectures or ["unknown"]}
        except OSError:
            return {"sha256": None, "architectures": ["unknown"]}
    from .runtime_lock import runtime_dependency_records
    return {"runtimeDependencies": runtime_dependency_records(config.ffmpeg_exe()),
            "ffmpeg": binary(config.ffmpeg_exe()), "ffprobe": binary(config.ffprobe_exe()),
            "clientExecutionArchitecture": normalize_architecture(platform.machine())}


def execution_provenance():
    runtime = runtime_identity()
    host = normalize_architecture(platform.machine())
    if host not in {"arm64", "x86_64", "x86", "arm"}:
        host = "unknown"
    if platform.system() == "Darwin" and _command(["sysctl", "-n", "hw.optional.arm64"]) == "1":
        host = "arm64"
    architectures = [normalize_architecture(value) for value in runtime["ffmpeg"]["architectures"]]
    # A universal header identifies supported slices, not the executed slice.
    execution = architectures[0] if len(architectures) == 1 else "unknown"
    return {"executionArchitecture": execution,
            "translationMode": "unknown" if execution == "unknown" or host == "unknown" else ("native" if execution == host else "translated"),
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
