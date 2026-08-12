import hashlib
import json
import os
import shutil
import subprocess
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from . import config
from . import recipe

RUNTIME_LOCK_SCHEMA_VERSION = 1
RUNTIME_LOCK_RELATIVE_PATH = os.path.join("resources", "runtime", "ffmpeg-lock.json")
RUNTIME_RESOURCE_DIR_RELATIVE_PATH = os.path.join("resources", "runtime")
RUNTIME_LOCK_SIDECAR_CANDIDATES: Sequence[str] = (
    "ffmpeg-lock.json",
    "runtime-lock.json",
)
REQUIRED_FILTERS: Sequence[str] = ("libvmaf", "xpsnr")
PLATFORM_REQUIRED_ENCODERS: Mapping[str, Sequence[str]] = {
    "linux": ("libaom-av1", "libvpx-vp9", "libx264", "libx265"),
    "mac": ("libaom-av1", "libvpx-vp9", "libx264", "libx265"),
    "win": ("libaom-av1", "libvpx-vp9", "libx264", "libx265"),
}
PLATFORM_OPTIONAL_ENCODERS: Mapping[str, Sequence[str]] = {
    "linux": (
        "libopenh264",
        "h264_nvenc",
        "hevc_nvenc",
        "av1_nvenc",
        "h264_qsv",
        "hevc_qsv",
        "av1_qsv",
        "vp9_qsv",
        "h264_vaapi",
        "hevc_vaapi",
        "av1_vaapi",
        "vp9_vaapi",
        "h264_v4l2m2m",
        "hevc_v4l2m2m",
        "av1_v4l2m2m",
        "vp9_v4l2m2m",
        "h264_omx",
    ),
    "mac": (
        "libopenh264",
        "h264_videotoolbox",
        "hevc_videotoolbox",
        "av1_videotoolbox",
    ),
    "win": (
        "libopenh264",
        "h264_nvenc",
        "hevc_nvenc",
        "av1_nvenc",
        "h264_qsv",
        "hevc_qsv",
        "av1_qsv",
        "vp9_qsv",
        "h264_amf",
        "hevc_amf",
        "av1_amf",
    ),
}
DEFAULT_REQUIRED_ENCODERS: Sequence[str] = PLATFORM_REQUIRED_ENCODERS["linux"]


class RuntimeLockError(RuntimeError):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_path(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_platform_key(platform_key: Optional[str]) -> str:
    selected = str(platform_key or config._platform_key()).strip().lower()
    if selected in ("darwin", "macos", "osx"):
        return "mac"
    if selected in ("windows", "win32"):
        return "win"
    if selected not in PLATFORM_REQUIRED_ENCODERS:
        return "linux"
    return selected


def _dedupe_strings(values: Iterable[str]) -> List[str]:
    ordered: List[str] = []
    seen = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def runtime_capability_requirements(platform_key: Optional[str] = None) -> Dict[str, List[str]]:
    selected = _normalize_platform_key(platform_key)
    required = _dedupe_strings(PLATFORM_REQUIRED_ENCODERS.get(selected, DEFAULT_REQUIRED_ENCODERS))
    optional = [
        encoder for encoder in _dedupe_strings(PLATFORM_OPTIONAL_ENCODERS.get(selected, ()))
        if encoder not in required
    ]
    return {
        "platform": selected,
        "filters": sorted(_dedupe_strings(REQUIRED_FILTERS)),
        "requiredEncoders": sorted(required),
        "optionalEncoders": sorted(optional),
        "smokeTestEncoders": [encoder for encoder in required if encoder in ("libx264", "libx265", "libaom-av1", "libvpx-vp9")],
    }


def _run_text(command: Sequence[str]) -> str:
    proc = subprocess.run(
        list(command),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeLockError(f"{command[0]} failed with exit code {proc.returncode}: {detail}")
    return proc.stdout or ""


def _platform_entry(lock_payload: Mapping[str, Any], platform_key: str) -> Mapping[str, Any]:
    platforms = lock_payload.get("platforms")
    if not isinstance(platforms, Mapping):
        raise RuntimeLockError("runtime lock is missing platforms")
    entry = platforms.get(platform_key)
    if not isinstance(entry, Mapping):
        raise RuntimeLockError(f"runtime lock does not define platform {platform_key}")
    return entry


def _normalize_filters(raw_output: str) -> List[str]:
    names: List[str] = []
    for line in str(raw_output).splitlines():
        parts = line.split()
        if len(parts) >= 2:
            names.append(parts[1].strip())
    return sorted(set(name for name in names if name))


def _normalize_encoders(raw_output: str) -> List[str]:
    names: List[str] = []
    for line in str(raw_output).splitlines():
        parts = line.split()
        if len(parts) >= 2:
            names.append(parts[1].strip())
    return sorted(set(name for name in names if name))


def _binary_record(path: str, version_output: str) -> Dict[str, Any]:
    banner = str(version_output).strip()
    version_line = banner.splitlines()[0].strip() if banner else ""
    return {
        "relativePath": None,
        "sha256": _sha256_path(path),
        "byteSize": os.path.getsize(path),
        "versionLine": version_line,
        "buildFingerprint": recipe.ffmpeg_build_fingerprint(banner),
    }


def probe_runtime_identity(
    *,
    ffmpeg_path: str,
    ffprobe_path: str,
    platform_key: Optional[str] = None,
    required_filters: Optional[Iterable[str]] = None,
    required_encoders: Optional[Iterable[str]] = None,
    optional_encoders: Optional[Iterable[str]] = None,
    smoke_test_encoders: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    requirements = runtime_capability_requirements(platform_key)
    ffmpeg_version_output = _run_text([ffmpeg_path, "-version"])
    ffprobe_version_output = _run_text([ffprobe_path, "-version"])
    filter_output = _run_text([ffmpeg_path, "-hide_banner", "-filters"])
    encoder_output = _run_text([ffmpeg_path, "-hide_banner", "-encoders"])

    observed_filters = _normalize_filters(filter_output)
    observed_encoders = _normalize_encoders(encoder_output)
    requested_filters = sorted(_dedupe_strings(required_filters or requirements["filters"]))
    requested_encoders = sorted(_dedupe_strings(required_encoders or requirements["requiredEncoders"]))
    declared_optional_encoders = sorted(
        encoder for encoder in _dedupe_strings(optional_encoders or requirements["optionalEncoders"])
        if encoder not in requested_encoders
    )
    requested_smoke_encoders = [
        encoder for encoder in _dedupe_strings(smoke_test_encoders or requirements["smokeTestEncoders"])
        if encoder in observed_encoders
    ]

    missing_filters = [value for value in requested_filters if value not in observed_filters]
    missing_encoders = [value for value in requested_encoders if value not in observed_encoders]
    if missing_filters:
        raise RuntimeLockError(f"runtime is missing required ffmpeg filters: {', '.join(missing_filters)}")
    if missing_encoders:
        raise RuntimeLockError(f"runtime is missing required ffmpeg encoders: {', '.join(missing_encoders)}")
    if not requested_smoke_encoders:
        raise RuntimeLockError("runtime does not expose any smoke-testable FFmpeg encoders")

    ffmpeg_record = _binary_record(ffmpeg_path, ffmpeg_version_output)
    ffprobe_record = _binary_record(ffprobe_path, ffprobe_version_output)
    ffprobe_record["buildFingerprint"] = recipe.ffmpeg_build_fingerprint(ffprobe_version_output)
    return {
        "ffmpeg": ffmpeg_record,
        "ffprobe": ffprobe_record,
        "capabilities": {
            "ffprobe": True,
            "filters": requested_filters,
            "requiredEncoders": requested_encoders,
            "optionalEncoders": [encoder for encoder in declared_optional_encoders if encoder in observed_encoders],
            "smokeTestEncoders": requested_smoke_encoders,
            "encoders": requested_smoke_encoders,
        },
    }


def build_runtime_lock_payload(
    *,
    platform_key: Optional[str] = None,
    ffmpeg_path: Optional[str] = None,
    ffprobe_path: Optional[str] = None,
    required_filters: Optional[Iterable[str]] = None,
    required_encoders: Optional[Iterable[str]] = None,
    source: str = "deterministically-provisioned",
) -> Dict[str, Any]:
    selected_platform = _normalize_platform_key(platform_key)
    resolved_ffmpeg = os.path.abspath(ffmpeg_path or config.ffmpeg_exe())
    resolved_ffprobe = os.path.abspath(ffprobe_path or config.ffprobe_exe())
    identity = probe_runtime_identity(
        ffmpeg_path=resolved_ffmpeg,
        ffprobe_path=resolved_ffprobe,
        platform_key=selected_platform,
        required_filters=required_filters,
        required_encoders=required_encoders,
    )
    identity["ffmpeg"]["relativePath"] = os.path.join("bin", selected_platform, os.path.basename(resolved_ffmpeg))
    identity["ffprobe"]["relativePath"] = os.path.join("bin", selected_platform, os.path.basename(resolved_ffprobe))
    return {
        "schemaVersion": RUNTIME_LOCK_SCHEMA_VERSION,
        "runtimeId": "encodingdb-ffmpeg-runtime",
        "source": str(source).strip() or "deterministically-provisioned",
        "platforms": {
            selected_platform: identity,
        },
    }


def runtime_resource_dir() -> str:
    return config._resource_path(RUNTIME_RESOURCE_DIR_RELATIVE_PATH)


def default_runtime_lock_path() -> str:
    explicit = str(os.environ.get("ENCODINGDB_RUNTIME_LOCK_PATH") or "").strip()
    if explicit:
        return os.path.abspath(explicit)
    return config._resource_path(RUNTIME_LOCK_RELATIVE_PATH)


def load_runtime_lock(lock_path: Optional[str] = None) -> Dict[str, Any]:
    path = os.path.abspath(lock_path or default_runtime_lock_path())
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if int(payload.get("schemaVersion") or 0) != RUNTIME_LOCK_SCHEMA_VERSION:
        raise RuntimeLockError(f"unsupported runtime lock schema version at {path}")
    return payload


def write_runtime_lock(payload: Mapping[str, Any], lock_path: Optional[str] = None) -> str:
    path = os.path.abspath(lock_path or default_runtime_lock_path())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")
    os.replace(temp_path, path)
    return path


def filtered_runtime_lock_payload(lock_payload: Mapping[str, Any], platform_key: str) -> Dict[str, Any]:
    selected_platform = str(platform_key or "").strip().lower()
    entry = _platform_entry(lock_payload, selected_platform)
    return {
        "schemaVersion": int(lock_payload.get("schemaVersion") or RUNTIME_LOCK_SCHEMA_VERSION),
        "runtimeId": str(lock_payload.get("runtimeId") or "encodingdb-ffmpeg-runtime"),
        "source": str(lock_payload.get("source") or "deterministically-provisioned"),
        "platforms": {
            selected_platform: json.loads(json.dumps(entry)),
        },
    }


def upsert_runtime_lock_platform(
    lock_payload: Optional[Mapping[str, Any]],
    *,
    platform_key: str,
    platform_payload: Mapping[str, Any],
    source: Optional[str] = None,
) -> Dict[str, Any]:
    existing = json.loads(json.dumps(lock_payload or {}))
    platforms = existing.get("platforms")
    if not isinstance(platforms, dict):
        platforms = {}
    platforms[str(platform_key).strip().lower()] = json.loads(json.dumps(platform_payload))
    existing["schemaVersion"] = RUNTIME_LOCK_SCHEMA_VERSION
    existing["runtimeId"] = str(existing.get("runtimeId") or "encodingdb-ffmpeg-runtime")
    existing["source"] = str(source or existing.get("source") or "deterministically-provisioned")
    existing["platforms"] = platforms
    return existing


def stage_runtime_resource_dir(
    *,
    destination_dir: str,
    lock_payload: Mapping[str, Any],
    platform_key: str,
    source_dir: Optional[str] = None,
) -> str:
    source_root = os.path.abspath(source_dir or runtime_resource_dir())
    destination_root = os.path.abspath(destination_dir)
    os.makedirs(destination_root, exist_ok=True)
    for entry in os.listdir(source_root):
        source_path = os.path.join(source_root, entry)
        target_path = os.path.join(destination_root, entry)
        if entry == os.path.basename(RUNTIME_LOCK_RELATIVE_PATH):
            continue
        if os.path.isdir(source_path):
            if os.path.exists(target_path):
                shutil.rmtree(target_path)
            shutil.copytree(source_path, target_path)
        else:
            shutil.copy2(source_path, target_path)
    write_runtime_lock(filtered_runtime_lock_payload(lock_payload, platform_key), os.path.join(destination_root, os.path.basename(RUNTIME_LOCK_RELATIVE_PATH)))
    return destination_root


def _resolve_binary_path(
    *,
    lock_path: str,
    explicit_path: Optional[str],
    entry: Mapping[str, Any],
) -> str:
    if explicit_path:
        return os.path.abspath(explicit_path)
    relative_path = str(entry.get("relativePath") or "").strip()
    if not relative_path:
        raise RuntimeLockError(f"runtime lock at {lock_path} is missing relativePath")
    return os.path.abspath(os.path.join(os.path.dirname(lock_path), relative_path))


def _assert_binary_identity(label: str, path: str, expected: Mapping[str, Any], observed: Mapping[str, Any]) -> None:
    if not os.path.exists(path):
        raise RuntimeLockError(f"{label} binary does not exist at {path}")
    if observed.get("sha256") != expected.get("sha256"):
        raise RuntimeLockError(f"{label} SHA-256 mismatch for {path}")
    if int(observed.get("byteSize") or 0) != int(expected.get("byteSize") or 0):
        raise RuntimeLockError(f"{label} byte size mismatch for {path}")
    if str(observed.get("versionLine") or "").strip() != str(expected.get("versionLine") or "").strip():
        raise RuntimeLockError(f"{label} version line mismatch for {path}")
    expected_build = str(expected.get("buildFingerprint") or "").strip()
    if expected_build and str(observed.get("buildFingerprint") or "").strip() != expected_build:
        raise RuntimeLockError(f"{label} build fingerprint mismatch for {path}")


def _capability_list(
    capabilities: Mapping[str, Any],
    *,
    keys: Sequence[str],
    fallback: Sequence[str],
) -> List[str]:
    for key in keys:
        value = capabilities.get(key)
        if isinstance(value, list):
            return value
    return list(fallback)


def verify_runtime_lock(
    *,
    platform_key: Optional[str] = None,
    ffmpeg_path: Optional[str] = None,
    ffprobe_path: Optional[str] = None,
    lock_path: Optional[str] = None,
) -> Dict[str, Any]:
    selected_platform = _normalize_platform_key(platform_key)
    resolved_lock_path = os.path.abspath(lock_path or default_runtime_lock_path())
    payload = load_runtime_lock(resolved_lock_path)
    platform_entry = _platform_entry(payload, selected_platform)
    expected_ffmpeg = platform_entry.get("ffmpeg")
    expected_ffprobe = platform_entry.get("ffprobe")
    capabilities = platform_entry.get("capabilities")
    if not isinstance(expected_ffmpeg, Mapping) or not isinstance(expected_ffprobe, Mapping):
        raise RuntimeLockError(f"runtime lock at {resolved_lock_path} is missing ffmpeg/ffprobe records")
    if not isinstance(capabilities, Mapping):
        raise RuntimeLockError(f"runtime lock at {resolved_lock_path} is missing capabilities")

    resolved_ffmpeg = _resolve_binary_path(lock_path=resolved_lock_path, explicit_path=ffmpeg_path, entry=expected_ffmpeg)
    resolved_ffprobe = _resolve_binary_path(lock_path=resolved_lock_path, explicit_path=ffprobe_path, entry=expected_ffprobe)
    default_requirements = runtime_capability_requirements(selected_platform)
    observed = probe_runtime_identity(
        ffmpeg_path=resolved_ffmpeg,
        ffprobe_path=resolved_ffprobe,
        platform_key=selected_platform,
        required_filters=_capability_list(
            capabilities,
            keys=("filters",),
            fallback=default_requirements["filters"],
        ),
        required_encoders=_capability_list(
            capabilities,
            keys=("requiredEncoders", "encoders"),
            fallback=default_requirements["requiredEncoders"],
        ),
        optional_encoders=_capability_list(
            capabilities,
            keys=("optionalEncoders",),
            fallback=default_requirements["optionalEncoders"],
        ),
        smoke_test_encoders=_capability_list(
            capabilities,
            keys=("smokeTestEncoders", "encoders"),
            fallback=default_requirements["smokeTestEncoders"],
        ),
    )
    _assert_binary_identity("ffmpeg", resolved_ffmpeg, expected_ffmpeg, observed["ffmpeg"])
    _assert_binary_identity("ffprobe", resolved_ffprobe, expected_ffprobe, observed["ffprobe"])
    return {
        "platform": selected_platform,
        "lockPath": resolved_lock_path,
        "ffmpegPath": resolved_ffmpeg,
        "ffprobePath": resolved_ffprobe,
        "fingerprint": hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest(),
        "payload": payload,
        "identity": observed,
    }


def find_operator_runtime_lock(ffmpeg_path: str, ffprobe_path: str) -> Optional[str]:
    explicit = str(os.environ.get("ENCODINGDB_RUNTIME_LOCK_PATH") or "").strip()
    if explicit:
        return os.path.abspath(explicit)

    search_roots = {
        os.path.dirname(os.path.abspath(ffmpeg_path)),
        os.path.dirname(os.path.abspath(ffprobe_path)),
    }
    for root in sorted(search_roots):
        for candidate in RUNTIME_LOCK_SIDECAR_CANDIDATES:
            path = os.path.join(root, candidate)
            if os.path.exists(path):
                return path
    return None
