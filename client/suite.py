import errno
import hashlib
import json
import math
import re
import os
import shutil
import queue
import threading
from urllib.parse import urljoin
import subprocess
from .campaign import (check_preparation_cancelled, preparation_progress, run_measurement_process,
                       start_owned_acquisition, wait_for_owned_acquisition)
from .console_policy import hidden_console_kwargs
import sys
import tempfile
import tarfile
import warnings
import binascii
import struct
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import config

SUITE_VERSION = "encodingdb-test-suite-v1"
DEFAULT_QUICK_CLIP_ID = "sports-action-960x540-24p"
MANIFEST_RELATIVE_PATH = os.path.join("resources", "test_suite_v1", "manifest.json")
FINALIZATION_STATUS_RELATIVE_PATH = os.path.join("resources", "test_suite_v1", "finalization-status.json")
SUITE_LOCK_RELATIVE_PATH = os.path.join("resources", "test_suite_v1", "suite-lock.json")
SUITE_PACK_METADATA_RELATIVE_PATH = os.path.join("resources", "test_suite_v1", "suite-pack.json")
SUITE_PACK_SCHEMA_VERSION = 1
DEFAULT_SUITE_PACK_FILE_NAME = f"{SUITE_VERSION}.tar.gz"
CLIP_DISTRIBUTION_RELATIVE_PATH = os.path.join("resources", "test_suite_v1", "clip-distribution.json")
CLIP_DISTRIBUTION_SCHEMA_VERSION = 1
SUITE_CLIP_BASE_URL_ENV = "ENCODINGDB_SUITE_CLIP_BASE_URL"
SUITE_ALLOW_FULL_PACK_ENV = "ENCODINGDB_ALLOW_FULL_PACK"
SUITE_MIN_FREE_MB_ENV = "ENCODINGDB_SUITE_MIN_FREE_MB"

REQUIRED_CONTENT_CLASSES: Tuple[str, ...] = (
    "high-motion-sports",
    "fine-natural-detail",
    "film-grain-noise",
    "dark-gradients-shadows",
    "animation-flat-fields",
    "screen-text",
    "talking-head",
)


SUITE_BUILD_SPEC: Tuple[Dict[str, Any], ...] = (
    {
        "id": "sports-action-960x540-24p",
        "displayName": "High motion / sports synthetic master",
        "contentClass": "high-motion-sports",
        "payloadContentClass": "action",
        "lavfi": "testsrc2=size=960x540:rate=24,zoompan=z='1+0.06*sin(on/8)':x='iw/2-(iw/zoom/2)+sin(on/4)*38':y='ih/2-(ih/zoom/2)+cos(on/6)*20':d=1:s=960x540:fps=24",
        "description": "Fast motion, zoom, and repeated texture changes intended to stress motion handling.",
    },
    {
        "id": "natural-detail-960x540-24p",
        "displayName": "Fine natural detail / texture synthetic master",
        "contentClass": "fine-natural-detail",
        "payloadContentClass": "nature",
        "lavfi": "mandelbrot=size=960x540:rate=24:maxiter=80:end_scale=0.4:outer=1:inner=3",
        "description": "Fractal detail with dense high-frequency structure intended to stand in for foliage and texture retention.",
    },
    {
        "id": "grain-noise-960x540-24p",
        "displayName": "Film grain / noise synthetic master",
        "contentClass": "film-grain-noise",
        "payloadContentClass": "gaming",
        "lavfi": "nullsrc=size=960x540:rate=24,geq=lum='96+20*sin((X+N*7)/29)+18*sin((Y+N*5)/31)':cb='128+10*sin((X+N*2)/17)':cr='128+10*sin((Y+N*3)/19)',noise=alls=24:all_seed=71:allf=t+u",
        "description": "Low-contrast structured luma with deterministic temporal noise intended to stress grain retention without external media.",
    },
    {
        "id": "dark-gradients-960x540-24p",
        "displayName": "Dark gradients / shadows synthetic master",
        "contentClass": "dark-gradients-shadows",
        "payloadContentClass": "mixed",
        "lavfi": "nullsrc=size=960x540:rate=24,geq=lum='16+18*X/W+7*sin((X+N*3)/47)+5*sin((Y+N*2)/53)':cb='128+2*sin((X+N)/41)':cr='128+2*sin((Y+N)/37)'",
        "description": "Low-luma gradients with slight motion intended to expose banding and shadow instability.",
    },
    {
        "id": "animation-960x540-24p",
        "displayName": "Animation / flat fields / hard edges synthetic master",
        "contentClass": "animation-flat-fields",
        "payloadContentClass": "animation",
        "lavfi": "color=c=0x8ad4ff:size=960x540:rate=24,drawbox=x='140+110*sin(t*3)':y=70:w=140:h=140:color=0xff6b35@1:t=fill,drawbox=x='620+90*cos(t*2.4)':y=280:w=180:h=180:color=0x2a4bff@1:t=fill,drawbox=x=0:y=420:w=960:h=120:color=0x2ecc71@1:t=fill",
        "description": "Flat fills, saturated color regions, and hard edges intended to reflect animation-specific tradeoffs.",
    },
    {
        "id": "screen-text-960x540-24p",
        "displayName": "Screen / text synthetic master",
        "contentClass": "screen-text",
        "payloadContentClass": "screen",
        "lavfi": "testsrc=size=960x540:rate=24,drawgrid=w=80:h=54:t=2:c=white@0.35",
        "description": "Grid, labels, and sharp transitions intended to approximate UI and screen-recording behavior without external fonts or screenshots.",
    },
    {
        "id": "talking-head-960x540-24p",
        "displayName": "Low-motion face / talking head synthetic master",
        "contentClass": "talking-head",
        "payloadContentClass": "talkingHead",
        "lavfi": "color=c=0x31445a:size=960x540:rate=24,drawbox=x=280:y=100:w=400:h=360:color=0xd9b18c@1:t=fill,drawbox=x=350:y=220:w=48:h=24:color=black@0.95:t=fill,drawbox=x=562:y=220:w=48:h=24:color=black@0.95:t=fill,drawbox=x='430+6*sin(t*3)':y='330+4*sin(t*2.2)':w=100:h=16:color=0x7a342d@0.95:t=fill,drawbox=x=310:y=380:w=340:h=100:color=0x6a7d95@1:t=fill",
        "description": "Low-motion portrait-like composition intended to stand in for webcam and interview material.",
    },
)


@dataclass(frozen=True)
class ClipMediaContract:
    frame_count: int
    duration_num: int
    duration_den: int
    frame_rate_num: int
    frame_rate_den: int
    width: int
    height: int
    pixel_format: str
    bit_depth: int
    chroma_subsampling: str
    color_primaries: str
    color_transfer: str
    color_matrix: str
    color_range: str
    field_order: str
    hdr_metadata: Optional[Dict[str, Any]]


@dataclass(frozen=True)
class SuiteClip:
    clip_id: str
    display_name: str
    canonical_content_class: str
    payload_content_class: str
    file_name: str
    sha256: str
    byte_size: int
    acquisition: Dict[str, Any]
    description: str
    provenance: Dict[str, Any]
    media: ClipMediaContract


@dataclass(frozen=True)
class SuiteManifest:
    suite_version: str
    display_name: str
    manifest_version: int
    default_quick_clip_id: str
    required_content_classes: Tuple[str, ...]
    clips: Tuple[SuiteClip, ...]


@dataclass(frozen=True)
class PreparedSuiteClip:
    suite_version: str
    clip_id: str
    canonical_content_class: str
    payload_content_class: str
    workload_id: str
    path: str
    input_hash: str
    file_name: str


@dataclass(frozen=True)
class ClipVerificationResult:
    ok: bool
    message: str
    details: Dict[str, Any]


def _manifest_resource_candidates() -> List[str]:
    return [
        config._resource_path(MANIFEST_RELATIVE_PATH),
        os.path.join(os.path.dirname(__file__), MANIFEST_RELATIVE_PATH),
    ]


def get_manifest_path() -> str:
    for candidate in _manifest_resource_candidates():
        if candidate and os.path.exists(candidate):
            return candidate
    raise FileNotFoundError("EncodingDB Test Suite v1 manifest not found")


def get_finalization_status_path() -> str:
    for manifest_path in _manifest_resource_candidates():
        candidate = os.path.join(os.path.dirname(manifest_path), os.path.basename(FINALIZATION_STATUS_RELATIVE_PATH))
        if os.path.exists(candidate):
            return candidate
    raise FileNotFoundError("EncodingDB Test Suite v1 finalization status not found")


def get_suite_lock_path() -> str:
    for manifest_path in _manifest_resource_candidates():
        candidate = os.path.join(os.path.dirname(manifest_path), os.path.basename(SUITE_LOCK_RELATIVE_PATH))
        if os.path.exists(candidate):
            return candidate
    raise FileNotFoundError("EncodingDB Test Suite v1 lock not found")


def get_suite_pack_metadata_path() -> str:
    for manifest_path in _manifest_resource_candidates():
        candidate = os.path.join(os.path.dirname(manifest_path), os.path.basename(SUITE_PACK_METADATA_RELATIVE_PATH))
        if os.path.exists(candidate):
            return candidate
    raise FileNotFoundError("EncodingDB Test Suite v1 pack metadata not found")


def load_finalization_status(path: Optional[str] = None) -> Dict[str, Any]:
    with open(path or get_finalization_status_path(), "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError("suite finalization status is invalid")
    return payload


def load_suite_lock(path: Optional[str] = None) -> Dict[str, Any]:
    with open(path or get_suite_lock_path(), "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError("suite lock is invalid")
    return payload


def load_suite_pack_metadata(path: Optional[str] = None) -> Dict[str, Any]:
    with open(path or get_suite_pack_metadata_path(), "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError("suite pack metadata is invalid")
    return payload


def get_clip_distribution_path() -> Optional[str]:
    for manifest_path in _manifest_resource_candidates():
        candidate = os.path.join(os.path.dirname(manifest_path), os.path.basename(CLIP_DISTRIBUTION_RELATIVE_PATH))
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def _clip_notice_asset_names(manifest: SuiteManifest, suite_root: str) -> Dict[str, List[str]]:
    """Map each clip to its attribution notice plus the license texts it names.

    Bindings come from the frozen notice bodies themselves: every clip notice
    declares "License: <id>;" and a font notice beside that clip's license is
    included only when the clip notice mentions the font.
    """
    notices_root = os.path.join(suite_root, "notices")
    available = {name for name in os.listdir(notices_root) if name.endswith(".txt")} if os.path.isdir(notices_root) else set()
    bindings: Dict[str, List[str]] = {}
    for clip in manifest.clips:
        own = f"{clip.clip_id}.txt"
        if own not in available:
            raise RuntimeError(f"missing attribution notice for {clip.clip_id}")
        with open(os.path.join(notices_root, own), "r", encoding="utf-8") as handle:
            text = handle.read()
        names = [own]
        license_match = re.search(r"License:\s*([^;\n]+);", text)
        declared = license_match.group(1).strip() if license_match else ""
        if declared:
            license_file = f"{declared}.txt"
            if license_file not in available:
                raise RuntimeError(f"missing license text {license_file} for {clip.clip_id}")
            names.append(license_file)
        if re.search(r"plex|font", text, re.IGNORECASE):
            for name in sorted(available):
                if name in names or name == own:
                    continue
                with open(os.path.join(notices_root, name), "r", encoding="utf-8") as other_handle:
                    other = other_handle.read(400)
                if re.search(r"font software is licensed", other, re.IGNORECASE):
                    names.append(name)
        bindings[clip.clip_id] = names
    return bindings


def build_clip_distribution_metadata(
    suite_root: str,
    *,
    manifest: Optional[SuiteManifest] = None,
    base_url: str = "",
    release_tag: Optional[str] = None,
    published: bool = False,
) -> Dict[str, Any]:
    """Derive the per-clip distribution manifest from frozen suite resources.

    Every clip/notice hash and size comes from manifest.json and notices/; the
    canonical media bytes themselves are not required. ``path`` records the
    logical source layout; ``downloadName`` is unique and flat for releases.
    """
    suite_root_abs = os.path.abspath(suite_root)
    manifest_value = manifest
    if manifest_value is None:
        with open(os.path.join(suite_root_abs, "manifest.json"), "r", encoding="utf-8") as handle:
            manifest_value = manifest_from_payload(json.load(handle))
    manifest_path = os.path.join(suite_root_abs, "manifest.json")
    clips: Dict[str, Any] = {}
    for clip_id, names in _clip_notice_asset_names(manifest_value, suite_root_abs).items():
        clip = get_clip(manifest_value, clip_id)
        assets: List[Dict[str, Any]] = [
            {
                "role": "clip",
                "path": f"{clip_id}/{clip.file_name}",
                "downloadName": f"{clip_id}--{clip.file_name}",
                "sha256": clip.sha256,
                "byteSize": clip.byte_size,
            }
        ]
        for name in names:
            notice_path = os.path.join(suite_root_abs, "notices", name)
            assets.append(
                {
                    "role": "notice" if name == f"{clip_id}.txt" else "license",
                    "path": f"{clip_id}/notices/{name}",
                    "downloadName": f"{clip_id}--{name}",
                    "sha256": _sha256_of_file(notice_path),
                    "byteSize": os.path.getsize(notice_path),
                }
            )
        clips[clip_id] = {
            "fileName": clip.file_name,
            "license": str(clip.provenance.get("license") or ""),
            "assets": assets,
        }
    return {
        "schemaVersion": CLIP_DISTRIBUTION_SCHEMA_VERSION,
        "suiteId": "encodingdb-test-suite",
        "suiteVersion": manifest_value.suite_version,
        "manifestVersion": manifest_value.manifest_version,
        "source": "github-release" if published else "staged-unpublished",
        "releaseTag": release_tag,
        "distribution": {
            "baseUrl": base_url,
            "clipUrlOverrideEnv": SUITE_CLIP_BASE_URL_ENV,
            "published": bool(published),
        },
        "manifest": {
            "sha256": _sha256_of_file(manifest_path),
            "byteSize": os.path.getsize(manifest_path),
        },
        "clips": clips,
    }


def write_clip_distribution_metadata(suite_root: str, output_path: Optional[str] = None, **kwargs: Any) -> str:
    payload = build_clip_distribution_metadata(suite_root, **kwargs)
    destination = os.path.abspath(output_path or os.path.join(suite_root, "clip-distribution.json"))
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(destination, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")
    return destination


def load_clip_distribution_metadata(path: Optional[str] = None,
                                   manifest: Optional[SuiteManifest] = None) -> Optional[Dict[str, Any]]:
    """Load the clip distribution manifest; None when the file is absent.

    Absence only disables the per-clip route (development fixtures). A present
    file that contradicts the frozen suite identity fails closed — it would
    otherwise redirect acquisition to unreviewed bytes.
    """
    resolved = path if path is not None else get_clip_distribution_path()
    if resolved is None:
        return None
    with open(resolved, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError("clip distribution metadata is invalid")
    if int(payload.get("schemaVersion") or 0) != CLIP_DISTRIBUTION_SCHEMA_VERSION:
        raise RuntimeError("clip distribution metadata has an unsupported schemaVersion")
    suite_manifest = manifest if manifest is not None else load_default_suite_manifest()
    if str(payload.get("suiteVersion") or "") != suite_manifest.suite_version:
        raise RuntimeError("clip distribution metadata suite version mismatch")
    manifest_path = os.path.join(os.path.dirname(resolved), "manifest.json")
    record = dict(payload.get("manifest") or {})
    if int(record.get("byteSize") or 0) != os.path.getsize(manifest_path) \
            or str(record.get("sha256") or "").lower() != _sha256_of_file(manifest_path):
        raise RuntimeError("clip distribution metadata manifest identity mismatch")
    clips = dict(payload.get("clips") or {})
    manifest_ids = {clip.clip_id for clip in suite_manifest.clips}
    if set(clips) != manifest_ids:
        raise RuntimeError("clip distribution metadata clip inventory mismatch")
    bindings = _clip_notice_asset_names(suite_manifest, os.path.dirname(resolved))
    for clip in suite_manifest.clips:
        entry = dict(clips.get(clip.clip_id) or {})
        if str(entry.get("fileName") or "") != clip.file_name:
            raise RuntimeError(f"clip distribution metadata file name mismatch for {clip.clip_id}")
        assets = list(entry.get("assets") or [])
        roles = [str(asset.get("role") or "") for asset in assets]
        if roles.count("clip") != 1:
            raise RuntimeError(f"clip distribution metadata needs exactly one clip asset for {clip.clip_id}")
        expected_names = bindings[clip.clip_id]
        actual_names = [
            str(asset.get("path") or "").rsplit("notices/", 1)[-1]
            for asset in assets if str(asset.get("role") or "") in ("notice", "license")
        ]
        if sorted(actual_names) != sorted(expected_names):
            raise RuntimeError(f"clip distribution metadata notice binding mismatch for {clip.clip_id}")
        for asset in assets:
            relative = str(asset.get("path") or "")
            if not relative.startswith(f"{clip.clip_id}/") or ".." in relative.split("/"):
                raise RuntimeError(f"clip distribution metadata has an unsafe asset path: {relative}")
            expected_download_name = f"{clip.clip_id}--{relative.rsplit('/', 1)[-1]}"
            if str(asset.get("downloadName") or "") != expected_download_name:
                raise RuntimeError(f"clip distribution metadata download name mismatch: {relative}")
            expected_sha = str(asset.get("sha256") or "").lower()
            expected_bytes = int(asset.get("byteSize") or 0)
            if str(asset.get("role") or "") == "clip":
                if expected_bytes != clip.byte_size or expected_sha != clip.sha256.lower():
                    raise RuntimeError(f"clip distribution metadata identity mismatch for {clip.clip_id}")
            else:
                notice_file = relative.rsplit("notices/", 1)[-1]
                notice_path = os.path.join(os.path.dirname(resolved), "notices", notice_file)
                if not os.path.isfile(notice_path) or os.path.getsize(notice_path) != expected_bytes \
                        or _sha256_of_file(notice_path).lower() != expected_sha:
                    raise RuntimeError(f"clip distribution metadata notice mismatch: {relative}")
    return payload


def clip_distribution_available(metadata: Optional[Mapping[str, Any]]) -> bool:
    if not metadata:
        return False
    override = os.environ.get(SUITE_CLIP_BASE_URL_ENV, "").strip()
    base = str(dict(metadata.get("distribution") or {}).get("baseUrl") or "").strip()
    return bool(override or base)


def _clip_asset_url(metadata: Mapping[str, Any], asset_path: str) -> str:
    override = os.environ.get(SUITE_CLIP_BASE_URL_ENV, "").strip()
    base = override or str(dict(metadata.get("distribution") or {}).get("baseUrl") or "").strip()
    if not base:
        raise RuntimeError("clip distribution has no base URL")
    return urljoin(base.rstrip("/") + "/", asset_path.lstrip("/"))


def _suite_cache_root() -> str:
    custom = os.environ.get("ENCODINGDB_SUITE_CACHE_DIR", "").strip()
    if custom:
        return os.path.abspath(custom)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA", "").strip() or tempfile.gettempdir()
        return os.path.join(base, "EncodingDB", "suite", SUITE_VERSION)
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~/Library/Caches"), "EncodingDB", "suite", SUITE_VERSION)
    xdg = os.environ.get("XDG_CACHE_HOME", "").strip()
    if xdg:
        return os.path.join(xdg, "encodingdb", "suite", SUITE_VERSION)
    return os.path.join(os.path.expanduser("~"), ".cache", "encodingdb", "suite", SUITE_VERSION)


def _manifest_media_from_dict(data: Dict[str, Any]) -> ClipMediaContract:
    duration = data.get("duration", {})
    frame_rate = data.get("frameRate", {})
    return ClipMediaContract(
        frame_count=int(data["frameCount"]),
        duration_num=int(duration["numerator"]),
        duration_den=int(duration["denominator"]),
        frame_rate_num=int(frame_rate["numerator"]),
        frame_rate_den=int(frame_rate["denominator"]),
        width=int(data["width"]),
        height=int(data["height"]),
        pixel_format=str(data["pixelFormat"]),
        bit_depth=int(data["bitDepth"]),
        chroma_subsampling=str(data["chromaSubsampling"]),
        color_primaries=str(data["colorPrimaries"]),
        color_transfer=str(data["colorTransfer"]),
        color_matrix=str(data["colorMatrix"]),
        color_range=str(data["colorRange"]),
        field_order=str(data["fieldOrder"]),
        hdr_metadata=data.get("hdrMetadata"),
    )


def manifest_from_payload(payload: Mapping[str, Any]) -> SuiteManifest:
    clips = []
    for clip in payload.get("clips", []):
        clips.append(
            SuiteClip(
                clip_id=str(clip["id"]),
                display_name=str(clip["displayName"]),
                canonical_content_class=str(clip["contentClass"]),
                payload_content_class=str(clip.get("payloadContentClass") or clip["contentClass"]),
                file_name=str(clip["fileName"]),
                sha256=str(clip["sha256"]),
                byte_size=int(clip["byteSize"]),
                acquisition=dict(clip.get("acquisition") or {}),
                description=str(clip.get("description") or ""),
                provenance=dict(clip.get("source", {})),
                media=_manifest_media_from_dict(dict(clip["media"])),
            )
        )
    return SuiteManifest(
        suite_version=str(payload["suiteVersion"]),
        display_name=str(payload["displayName"]),
        manifest_version=int(payload["manifestVersion"]),
        default_quick_clip_id=str(payload["defaultQuickClipId"]),
        required_content_classes=tuple(str(value) for value in payload.get("requiredContentClasses", [])),
        clips=tuple(clips),
    )


def load_default_suite_manifest() -> SuiteManifest:
    with open(get_manifest_path(), "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return manifest_from_payload(payload)


def _clip_file_name(clip_id: str) -> str:
    return f"{clip_id}.mkv"


def _base_media_contract() -> Dict[str, Any]:
    return {
        "frameCount": 72,
        "duration": {"numerator": 3, "denominator": 1},
        "frameRate": {"numerator": 24, "denominator": 1},
        "width": 960,
        "height": 540,
        "pixelFormat": "yuv420p",
        "bitDepth": 8,
        "chromaSubsampling": "4:2:0",
        "colorPrimaries": "bt709",
        "colorTransfer": "bt709",
        "colorMatrix": "bt709",
        "colorRange": "tv",
        "fieldOrder": "progressive",
        "hdrMetadata": None,
    }


def _build_manifest_seed() -> Dict[str, Any]:
    clips: List[Dict[str, Any]] = []
    for clip in SUITE_BUILD_SPEC:
        clips.append(
            {
                "id": clip["id"],
                "displayName": clip["displayName"],
                "contentClass": clip["contentClass"],
                "payloadContentClass": clip["payloadContentClass"],
                "description": clip["description"],
                "fileName": _clip_file_name(str(clip["id"])),
                "source": {
                    "kind": "project-generated",
                    "provenance": "Generated from deterministic FFmpeg lavfi graphs owned by the project; no third-party media redistribution required.",
                    "license": "CC0-1.0",
                },
                "acquisition": {
                    "kind": "generated",
                    "ffmpegLavfi": clip["lavfi"],
                    "container": "mkv",
                    "videoCodec": "ffv1",
                    "deterministicFlags": [
                        "-threads 1",
                        "-fflags +bitexact",
                        "-flags:v +bitexact",
                        "-map_metadata -1",
                        "-map_chapters -1",
                    ],
                },
                "media": _base_media_contract(),
            }
        )
    return {
        "suiteId": "encodingdb-test-suite",
        "suiteVersion": SUITE_VERSION,
        "displayName": "EncodingDB Test Suite v1",
        "manifestVersion": 1,
        "defaultQuickClipId": DEFAULT_QUICK_CLIP_ID,
        "requiredContentClasses": list(REQUIRED_CONTENT_CLASSES),
        "generalPlPolicy": {
            "requiresCompleteCoverage": True,
            "weighting": "equal-class-geometric-mean",
            "legacySingleClipGeneralPlAllowed": False,
        },
        "redistribution": {
            "license": "CC0-1.0",
            "notes": "Every clip in suite v1 is project-generated and reproducible from the checked-in manifest plus bundled/system ffmpeg.",
        },
        "clips": clips,
    }


def _sha256_of_file(path: str) -> str:
    total = os.path.getsize(path)
    preparation_progress("hash", path=path, totalBytes=total)
    hasher = hashlib.sha256()
    completed = 0
    with open(path, "rb") as handle:
        while True:
            check_preparation_cancelled()
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
            completed += len(chunk)
            preparation_progress("hash", path=path, completedBytes=completed, totalBytes=total)
    return hasher.hexdigest()


def _probe_ratio(text: Optional[str]) -> Optional[Tuple[int, int]]:
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    if "/" in raw:
        left, right = raw.split("/", 1)
        try:
            num = int(left)
            den = int(right)
        except Exception:
            return None
        if den == 0:
            return None
        reduced = Fraction(num, den)
        return reduced.numerator, reduced.denominator
    try:
        reduced = Fraction(raw).limit_denominator()
    except Exception:
        return None
    return reduced.numerator, reduced.denominator


def _chroma_subsampling_for_pix_fmt(pix_fmt: str) -> Optional[str]:
    mapping = {
        "yuv420p": "4:2:0",
        "yuv422p": "4:2:2",
        "yuv444p": "4:4:4",
        "yuv420p10le": "4:2:0",
        "yuv422p10le": "4:2:2",
        "yuv444p10le": "4:4:4",
    }
    return mapping.get((pix_fmt or "").strip().lower())


def _bit_depth_from_pix_fmt(pix_fmt: str) -> Optional[int]:
    value = (pix_fmt or "").strip().lower()
    if "10" in value:
        return 10
    if value:
        return 8
    return None


def _normalize_container_alias(value: str) -> str:
    normalized = str(value or "").split(",", 1)[0].strip().lower()
    aliases = {
        "mkv": "matroska",
        "matroska": "matroska",
        "mov": "mov",
        "mp4": "mp4",
        "mpegts": "mpegts",
        "ts": "mpegts",
        "avi": "avi",
    }
    return aliases.get(normalized, normalized)


def _container_matches(expected: str, actual: str) -> bool:
    expected_value = _normalize_container_alias(expected)
    actual_values = {
        _normalize_container_alias(part)
        for part in str(actual or "").split(",")
        if str(part).strip()
    }
    return bool(expected_value and expected_value in actual_values)


def _probe_clip(path: str) -> Dict[str, Any]:
    cmd = [
        config.ffprobe_exe(),
        "-v", "error",
        "-count_frames",
        "-select_streams", "v:0",
        "-show_entries",
        "format=format_name:stream=codec_name,width,height,pix_fmt,bits_per_raw_sample,color_range,color_space,color_transfer,color_primaries,field_order,avg_frame_rate,r_frame_rate,nb_read_frames:stream_side_data",
        "-of", "json",
        path,
    ]
    preparation_progress("probe", path=path)
    proc = run_measurement_process(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    payload = json.loads(proc.stdout or "{}")
    streams = payload.get("streams") if isinstance(payload, dict) else None
    stream = streams[0] if isinstance(streams, list) and streams else {}
    container = payload.get("format") if isinstance(payload, dict) else None
    if not isinstance(stream, dict):
        stream = {}
    if not isinstance(container, dict):
        container = {}

    avg_rate = _probe_ratio(stream.get("avg_frame_rate")) or _probe_ratio(stream.get("r_frame_rate"))
    frame_count = 0
    try:
        frame_count = int(stream.get("nb_read_frames") or 0)
    except Exception:
        frame_count = 0
    bit_depth = None
    try:
        raw = stream.get("bits_per_raw_sample")
        bit_depth = int(raw) if raw not in (None, "") else None
    except Exception:
        bit_depth = None
    if bit_depth is None:
        bit_depth = _bit_depth_from_pix_fmt(str(stream.get("pix_fmt") or ""))

    duration_ratio: Optional[Tuple[int, int]] = None
    if avg_rate and frame_count > 0:
        duration_ratio = Fraction(frame_count * avg_rate[1], avg_rate[0]).as_integer_ratio()

    return {
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "containerFormat": str(container.get("format_name") or ""),
        "videoCodec": str(stream.get("codec_name") or ""),
        "pixFmt": str(stream.get("pix_fmt") or ""),
        "bitDepth": bit_depth,
        "chromaSubsampling": _chroma_subsampling_for_pix_fmt(str(stream.get("pix_fmt") or "")),
        "colorRange": str(stream.get("color_range") or ""),
        "colorSpace": str(stream.get("color_space") or ""),
        "colorTransfer": str(stream.get("color_transfer") or ""),
        "colorPrimaries": str(stream.get("color_primaries") or ""),
        "fieldOrder": str(stream.get("field_order") or ""),
        "frameRate": avg_rate,
        "frameCount": frame_count,
        "durationRatio": duration_ratio,
        "hdrMetadata": stream.get("side_data_list"),
    }


def _generation_command(lavfi: str, output_path: str, frame_count: int) -> List[str]:
    return [
        config.ffmpeg_exe(),
        "-y",
        "-v", "error",
        "-f", "lavfi",
        "-i", lavfi,
        "-frames:v", str(frame_count),
        "-an",
        "-sn",
        "-dn",
        "-map_metadata", "-1",
        "-map_chapters", "-1",
        "-threads", "1",
        "-fflags", "+bitexact",
        "-flags:v", "+bitexact",
        "-vf", "setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709:field_mode=prog",
        "-pix_fmt", "yuv420p",
        "-colorspace", "bt709",
        "-color_trc", "bt709",
        "-color_primaries", "bt709",
        "-color_range", "tv",
        "-c:v", "ffv1",
        "-level", "3",
        "-coder", "1",
        "-context", "1",
        "-g", "1",
        "-slices", "16",
        "-slicecrc", "1",
        output_path,
    ]


def _generate_clip(lavfi: str, output_path: str, frame_count: int) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    subprocess.run(_generation_command(lavfi, output_path, frame_count), check=True,
                   **hidden_console_kwargs())


def build_manifest_data() -> Dict[str, Any]:
    manifest = _build_manifest_seed()
    with tempfile.TemporaryDirectory() as temp_dir:
        for clip in manifest["clips"]:
            file_name = str(clip["fileName"])
            clip_path = os.path.join(temp_dir, file_name)
            frame_count = int(clip["media"]["frameCount"])
            _generate_clip(str(clip["acquisition"]["ffmpegLavfi"]), clip_path, frame_count)
            probe = _probe_clip(clip_path)
            clip["sha256"] = _sha256_of_file(clip_path)
            clip["byteSize"] = os.path.getsize(clip_path)
            clip["media"]["width"] = int(probe["width"])
            clip["media"]["height"] = int(probe["height"])
            clip["media"]["pixelFormat"] = str(probe["pixFmt"])
            clip["media"]["bitDepth"] = int(probe["bitDepth"] or 0)
            clip["media"]["chromaSubsampling"] = str(probe["chromaSubsampling"] or "")
            clip["media"]["colorRange"] = str(probe["colorRange"] or "")
            clip["media"]["colorMatrix"] = str(probe["colorSpace"] or "")
            clip["media"]["colorTransfer"] = str(probe["colorTransfer"] or "")
            clip["media"]["colorPrimaries"] = str(probe["colorPrimaries"] or "")
            clip["media"]["fieldOrder"] = str(probe["fieldOrder"] or "")
            clip["media"]["hdrMetadata"] = None
            frame_rate = probe["frameRate"] or (24, 1)
            clip["media"]["frameRate"] = {"numerator": int(frame_rate[0]), "denominator": int(frame_rate[1])}
            duration_ratio = probe["durationRatio"] or (3, 1)
            clip["media"]["duration"] = {"numerator": int(duration_ratio[0]), "denominator": int(duration_ratio[1])}
            clip["media"]["frameCount"] = int(probe["frameCount"] or frame_count)
    return manifest


def write_manifest(path: str) -> None:
    status_path = os.path.join(os.path.dirname(path), "finalization-status.json")
    if os.path.exists(status_path) and load_finalization_status(status_path).get("isFrozen"):
        raise RuntimeError("cannot regenerate synthetic media for a frozen suite")
    payload = build_manifest_data()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")


def get_clip(manifest: SuiteManifest, clip_id: str) -> SuiteClip:
    for clip in manifest.clips:
        if clip.clip_id == clip_id:
            return clip
    raise KeyError(f"Unknown suite clip: {clip_id}")


def get_default_quick_clip(manifest: Optional[SuiteManifest] = None) -> SuiteClip:
    suite = manifest or load_default_suite_manifest()
    override = os.environ.get("ENCODINGDB_QUICK_CLIP_ID", "").strip()
    clip_id = override or suite.default_quick_clip_id
    return get_clip(suite, clip_id)


def clip_cache_path(clip: SuiteClip, cache_root: Optional[str] = None) -> str:
    return os.path.join(cache_root or _suite_cache_root(), "canonical", clip.file_name)


def _cache_suite_pack_path(pack_metadata: Mapping[str, Any], cache_root: Optional[str] = None) -> str:
    distribution = dict(pack_metadata.get("distribution") or {})
    file_name = str(distribution.get("fileName") or DEFAULT_SUITE_PACK_FILE_NAME)
    return os.path.join(cache_root or _suite_cache_root(), "packs", file_name)


def _suite_pack_extract_root(pack_metadata: Mapping[str, Any], cache_root: Optional[str] = None) -> str:
    suite_fingerprint = str(pack_metadata.get("suiteFingerprint") or "").strip()
    if not suite_fingerprint:
        raise RuntimeError("suite pack metadata is missing suiteFingerprint")
    return os.path.join(cache_root or _suite_cache_root(), ".suite-pack", suite_fingerprint)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _suite_notice_entries(manifest: SuiteManifest, suite_root: str) -> List[Tuple[str, str]]:
    notices_root = os.path.join(suite_root, "notices")
    status = load_finalization_status(os.path.join(suite_root, "finalization-status.json"))
    if status.get("isFrozen"):
        for clip in manifest.clips:
            path = os.path.join(notices_root, f"{clip.clip_id}.txt")
            if not os.path.isfile(path) or os.path.getsize(path) == 0:
                raise RuntimeError(f"frozen suite is missing attribution/license notice for {clip.clip_id}")
    entries = []
    if os.path.isdir(notices_root):
        for name in sorted(os.listdir(notices_root)):
            path = os.path.join(notices_root, name)
            if os.path.islink(path) or not os.path.isfile(path):
                raise RuntimeError("suite notices must be regular files")
            entries.append((f"notices/{name}", path))
    return entries


def _suite_pack_source_entries(manifest: SuiteManifest, suite_root: str) -> List[Tuple[str, str]]:
    entries: List[Tuple[str, str]] = [
        ("manifest.json", os.path.join(suite_root, "manifest.json")),
        ("finalization-status.json", os.path.join(suite_root, "finalization-status.json")),
    ]
    lock_path = os.path.join(suite_root, "suite-lock.json")
    if os.path.exists(lock_path):
        entries.append(("suite-lock.json", lock_path))
    for clip in manifest.clips:
        entries.append((f"canonical/{clip.file_name}", os.path.join(suite_root, "canonical", clip.file_name)))
    entries.extend(_suite_notice_entries(manifest, suite_root))
    return entries


def _build_suite_pack_inventory(manifest: SuiteManifest, suite_root: str) -> Dict[str, Any]:
    manifest_path = os.path.join(suite_root, "manifest.json")
    status_path = os.path.join(suite_root, "finalization-status.json")
    lock_path = os.path.join(suite_root, "suite-lock.json")
    canonical_entries = []
    for clip in manifest.clips:
        clip_path = os.path.join(suite_root, "canonical", clip.file_name)
        canonical_entries.append(
            {
                "clipId": clip.clip_id,
                "fileName": clip.file_name,
                "sha256": clip.sha256,
                "byteSize": clip.byte_size,
            }
        )
    inventory: Dict[str, Any] = {
        "manifest": {
            "sha256": _sha256_of_file(manifest_path),
            "byteSize": os.path.getsize(manifest_path),
        },
        "finalizationStatus": {
            "sha256": _sha256_of_file(status_path),
            "byteSize": os.path.getsize(status_path),
        },
        "suiteLock": None,
        "canonical": canonical_entries,
    }
    if os.path.exists(lock_path):
        inventory["suiteLock"] = {
            "sha256": _sha256_of_file(lock_path),
            "byteSize": os.path.getsize(lock_path),
        }
    notices = _suite_notice_entries(manifest, suite_root)
    if notices:
        inventory["notices"] = [
            {"fileName": name, "sha256": _sha256_of_file(path), "byteSize": os.path.getsize(path)}
            for name, path in notices
        ]
    return inventory


def build_suite_pack_metadata(
    suite_root: str,
    *,
    manifest: Optional[SuiteManifest] = None,
    pack_file_name: str = DEFAULT_SUITE_PACK_FILE_NAME,
    download_urls: Optional[Sequence[str]] = None,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    suite_root_abs = os.path.abspath(suite_root)
    manifest_value = manifest
    if manifest_value is None:
        with open(os.path.join(suite_root_abs, "manifest.json"), "r", encoding="utf-8") as handle:
            manifest_value = manifest_from_payload(json.load(handle))
    inventory = _build_suite_pack_inventory(manifest_value, suite_root_abs)
    suite_fingerprint = _sha256_text(
        _canonical_json(
            {
                "suiteId": "encodingdb-test-suite",
                "suiteVersion": manifest_value.suite_version,
                "manifestVersion": manifest_value.manifest_version,
                "contents": inventory,
            }
        )
    )
    temp_output = output_path
    cleanup_output = False
    if temp_output is None:
        fd, temp_output = tempfile.mkstemp(prefix="encodingdb-suite-pack-", suffix=".tar.gz")
        os.close(fd)
        cleanup_output = True
    build_suite_pack_archive(suite_root_abs, temp_output, manifest=manifest_value)
    try:
        return {
            "schemaVersion": SUITE_PACK_SCHEMA_VERSION,
            "suiteId": "encodingdb-test-suite",
            "suiteVersion": manifest_value.suite_version,
            "manifestVersion": manifest_value.manifest_version,
            "suiteFingerprint": suite_fingerprint,
            "distributionMode": "external-suite-pack",
            "distribution": {
                "format": "tar.gz",
                "fileName": pack_file_name,
                "sha256": _sha256_of_file(temp_output),
                "byteSize": os.path.getsize(temp_output),
                "downloadUrls": [str(value).strip() for value in (download_urls or []) if str(value).strip()],
            },
            "contents": inventory,
        }
    finally:
        if cleanup_output:
            try:
                os.remove(temp_output)
            except FileNotFoundError:
                pass


def write_suite_pack_metadata(
    suite_root: str,
    *,
    pack_file_name: str = DEFAULT_SUITE_PACK_FILE_NAME,
    download_urls: Optional[Sequence[str]] = None,
    output_path: Optional[str] = None,
) -> str:
    metadata = build_suite_pack_metadata(
        suite_root,
        pack_file_name=pack_file_name,
        download_urls=download_urls,
    )
    destination = os.path.abspath(output_path or os.path.join(suite_root, "suite-pack.json"))
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(destination, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, sort_keys=False)
        handle.write("\n")
    return destination


def build_suite_pack_archive(
    suite_root: str,
    output_path: str,
    *,
    manifest: Optional[SuiteManifest] = None,
) -> str:
    suite_root_abs = os.path.abspath(suite_root)
    manifest_value = manifest
    if manifest_value is None:
        with open(os.path.join(suite_root_abs, "manifest.json"), "r", encoding="utf-8") as handle:
            manifest_value = manifest_from_payload(json.load(handle))
    entries = _suite_pack_source_entries(manifest_value, suite_root_abs)
    output_path_abs = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path_abs), exist_ok=True)
    fd, tar_path = tempfile.mkstemp(prefix="encodingdb-suite-pack-", suffix=".tar", dir=os.path.dirname(output_path_abs))
    os.close(fd)
    try:
        with tarfile.open(tar_path, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for relative_path, absolute_path in entries:
                info = tarfile.TarInfo(name=relative_path.replace("\\", "/"))
                info.size = os.path.getsize(absolute_path)
                info.mode = 0o644
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.mtime = 0
                with open(absolute_path, "rb") as source_handle:
                    archive.addfile(info, source_handle)
        _write_portable_stored_gzip(tar_path, output_path_abs)
    finally:
        try:
            os.remove(tar_path)
        except FileNotFoundError:
            pass
    return os.path.abspath(output_path)


def _write_portable_stored_gzip(source_path: str, output_path: str) -> None:
    """Write gzip without zlib-dependent compression decisions."""
    source_size = os.path.getsize(source_path)
    remaining = source_size
    checksum = 0
    with open(source_path, "rb") as source, open(output_path, "wb") as destination:
        destination.write(b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff")
        if remaining == 0:
            destination.write(b"\x01\x00\x00\xff\xff")
        while remaining > 0:
            chunk = source.read(min(65535, remaining))
            if not chunk:
                raise RuntimeError("unexpected end of deterministic suite tar stream")
            remaining -= len(chunk)
            destination.write(b"\x01" if remaining == 0 else b"\x00")
            destination.write(struct.pack("<HH", len(chunk), len(chunk) ^ 0xFFFF))
            destination.write(chunk)
            checksum = binascii.crc32(chunk, checksum)
        destination.write(struct.pack("<II", checksum & 0xFFFFFFFF, source_size & 0xFFFFFFFF))


def verify_suite_pack_metadata(
    suite_root: str,
    metadata: Mapping[str, Any],
) -> None:
    manifest = load_default_suite_manifest() if os.path.abspath(suite_root) == os.path.dirname(get_manifest_path()) else None
    expected = build_suite_pack_metadata(
        suite_root,
        manifest=manifest,
        pack_file_name=str(dict(metadata.get("distribution") or {}).get("fileName") or DEFAULT_SUITE_PACK_FILE_NAME),
        download_urls=list(dict(metadata.get("distribution") or {}).get("downloadUrls") or []),
    )
    actual = dict(metadata)
    if expected != actual:
        if expected.get("contents") != actual.get("contents"):
            mismatch = "contents inventory"
        elif expected.get("suiteFingerprint") != actual.get("suiteFingerprint"):
            mismatch = "suite fingerprint"
        elif expected.get("distribution") != actual.get("distribution"):
            mismatch = "distribution archive"
        else:
            mismatch = "top-level identity"
        raise RuntimeError(f"suite pack metadata does not match the current suite resources: {mismatch}")


def _verify_suite_pack_file(path: str, metadata: Mapping[str, Any]) -> ClipVerificationResult:
    distribution = dict(metadata.get("distribution") or {})
    expected_size = int(distribution.get("byteSize") or 0)
    expected_hash = str(distribution.get("sha256") or "").strip().lower()
    if not os.path.exists(path):
        return ClipVerificationResult(False, "suite pack not found", {"path": path})
    actual_size = os.path.getsize(path)
    if actual_size != expected_size:
        return ClipVerificationResult(
            False,
            "suite pack size mismatch",
            {"path": path, "expected": expected_size, "actual": actual_size, "field": "byteSize"},
        )
    actual_hash = _sha256_of_file(path)
    if actual_hash.lower() != expected_hash:
        return ClipVerificationResult(
            False,
            "suite pack checksum mismatch",
            {"path": path, "expected": expected_hash, "actual": actual_hash, "field": "sha256"},
        )
    return ClipVerificationResult(True, "ok", {"path": path})


def _verify_extracted_suite_pack(extract_root: str, metadata: Mapping[str, Any], *, verify_media: bool = True) -> None:
    contents = dict(metadata.get("contents") or {})
    required_files = (
        ("manifest", "manifest.json"),
        ("finalizationStatus", "finalization-status.json"),
    )
    for entry_key, relative_name in required_files:
        payload = dict(contents.get(entry_key) or {})
        absolute_path = os.path.join(extract_root, relative_name)
        if not os.path.exists(absolute_path):
            raise RuntimeError(f"extracted suite pack is missing {relative_name}")
        if os.path.getsize(absolute_path) != int(payload.get("byteSize") or 0) or _sha256_of_file(absolute_path) != str(payload.get("sha256") or "").lower():
            raise RuntimeError(f"extracted suite pack {relative_name} hash mismatch")
    lock_payload = contents.get("suiteLock")
    lock_path = os.path.join(extract_root, "suite-lock.json")
    if lock_payload is None:
        if os.path.exists(lock_path):
            raise RuntimeError("extracted suite pack unexpectedly includes suite-lock.json")
    else:
        if not os.path.exists(lock_path):
            raise RuntimeError("extracted suite pack is missing suite-lock.json")
        if os.path.getsize(lock_path) != int(dict(lock_payload).get("byteSize") or 0) or _sha256_of_file(lock_path) != str(dict(lock_payload).get("sha256") or "").lower():
            raise RuntimeError("extracted suite pack suite-lock.json hash mismatch")
    with open(os.path.join(extract_root, "manifest.json"), "r", encoding="utf-8") as handle:
        manifest = manifest_from_payload(json.load(handle))
    expected_notices = {}
    for notice in contents.get("notices") or []:
        name = str(notice["fileName"])
        if not name.startswith("notices/") or "/" in name[len("notices/"):] or ".." in name:
            raise RuntimeError("invalid suite notice path")
        expected_notices[name] = notice
    actual_notices = dict(_suite_notice_entries(manifest, extract_root))
    if set(actual_notices) != set(expected_notices):
        raise RuntimeError("extracted suite pack notices inventory mismatch")
    for name, path in actual_notices.items():
        notice = expected_notices[name]
        if os.path.getsize(path) != notice["byteSize"] or _sha256_of_file(path) != notice["sha256"]:
            raise RuntimeError(f"extracted suite pack notice hash mismatch: {name}")
    for clip in manifest.clips:
        path = os.path.join(extract_root, "canonical", clip.file_name)
        if verify_media:
            result = verify_suite_clip(path, clip)
            if not result.ok:
                raise RuntimeError(f"extracted suite pack verification failed for {clip.clip_id}: {result.message}")
        else:
            # Published caches already passed full media validation. Exact hashes
            # bind those validated bytes; each requested clip is probed again at use.
            if not os.path.isfile(path) or os.path.getsize(path) != clip.byte_size:
                raise RuntimeError(f"extracted suite pack size mismatch for {clip.clip_id}")
            if _sha256_of_file(path) != clip.sha256:
                raise RuntimeError(f"extracted suite pack checksum mismatch for {clip.clip_id}")


def _copy_preparation_stream(source, destination, *, path, total):
    completed = 0
    while True:
        preparation_progress("copy", path=path, completedBytes=completed, totalBytes=total)
        chunk = source.read(1024 * 1024)
        if not chunk:
            break
        destination.write(chunk)
        completed += len(chunk)
    check_preparation_cancelled()


def _copy_preparation_file(source, destination):
    with open(source, "rb") as reader, open(destination, "wb") as writer:
        _copy_preparation_stream(reader, writer, path=source, total=os.path.getsize(source))


def _suite_pack_target_access_error(target_root: str) -> Optional[str]:
    """Explain why an existing extracted root can be neither reused nor replaced.

    A folder write-protected against the current account is invisible to
    os.path.exists and undeletable or unreadable once found. The caller recovers
    into a writable alternate location; this only names the observed cause.
    """
    if not os.path.isdir(target_root):
        return None
    try:
        with os.scandir(target_root) as entries:
            for _ in entries:
                break
    except PermissionError as exc:
        return f"the existing cache folder {target_root} is not readable by the current user ({exc})"
    except OSError as exc:
        return f"the existing cache folder {target_root} cannot be inspected ({exc})"
    try:
        with open(os.path.join(target_root, "manifest.json"), "rb"):
            return None
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"the existing cache folder {target_root} cannot be read ({exc})"


def _suite_pack_recovered_root(pack_metadata: Mapping[str, Any], cache_root: Optional[str] = None) -> str:
    """Deterministic user-writable home for verified content when the primary
    extraction location is blocked by ACLs or locks. It lives beside, never inside,
    the blocked ".suite-pack" subtree, under the same suite cache root."""
    suite_fingerprint = str(pack_metadata.get("suiteFingerprint") or "").strip()
    if not suite_fingerprint:
        raise RuntimeError("suite pack metadata is missing suiteFingerprint")
    return os.path.join(cache_root or _suite_cache_root(), ".suite-pack-recovered", suite_fingerprint)


def _extract_suite_pack(pack_path: str, metadata: Mapping[str, Any], cache_root: Optional[str] = None) -> str:
    target_root = _suite_pack_extract_root(metadata, cache_root)
    canonical_root = os.path.join(target_root, "canonical")
    recovered_root = _suite_pack_recovered_root(metadata, cache_root)
    primary_error = _suite_pack_target_access_error(target_root)
    if primary_error is None:
        try:
            _verify_extracted_suite_pack(target_root, metadata, verify_media=False)
            return canonical_root
        except Exception:
            pass
    else:
        # A previous run may already have installed the verified recovered copy; reuse
        # it byte-for-byte without re-extracting.
        try:
            _verify_extracted_suite_pack(recovered_root, metadata, verify_media=False)
        except Exception:
            pass
        else:
            preparation_progress(
                "recovery", path=recovered_root,
                message=f"reusing the verified recovered suite cache copy at {recovered_root}",
            )
            return os.path.join(recovered_root, "canonical")
    staging_parent = os.path.dirname(recovered_root) if primary_error else os.path.dirname(target_root)
    try:
        os.makedirs(staging_parent, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"the configured suite cache under {cache_root or _suite_cache_root()} is not writable by "
            f"the current user ({exc}); point ENCODINGDB_SUITE_CACHE_DIR at a writable folder and "
            "start the run again"
        ) from exc
    staging_root = tempfile.mkdtemp(prefix="suite-pack-", dir=staging_parent)
    try:
        with tarfile.open(pack_path, "r:gz") as archive:
            for member in archive:
                preparation_progress("extract", path=member.name, totalBytes=member.size)
                parts = member.name.split("/")
                if not member.isfile() or member.name.startswith("/") or any(part in ("", ".", "..") for part in parts) or "\\" in member.name:
                    raise RuntimeError("suite pack contains an unsafe archive member")
                destination = os.path.join(staging_root, member.name)
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                with archive.extractfile(member) as source, open(destination, "xb") as target:
                    _copy_preparation_stream(source, target, path=member.name, total=member.size)
        _verify_extracted_suite_pack(staging_root, metadata)
        if primary_error is None:
            try:
                if os.path.isdir(target_root):
                    shutil.rmtree(target_root)
                os.replace(staging_root, target_root)
                return canonical_root
            except OSError as swap_exc:
                primary_error = (
                    f"the existing cache folder {target_root} could not be replaced ({swap_exc}); "
                    "it is held open or write-protected for this account"
                )
        try:
            os.makedirs(os.path.dirname(recovered_root), exist_ok=True)
            if os.path.isdir(recovered_root):
                shutil.rmtree(recovered_root)
            os.replace(staging_root, recovered_root)
        except OSError as recovered_exc:
            raise RuntimeError(
                "verified suite content could not be installed into the primary cache "
                f"(after re-extraction: {primary_error}) and could not be written to the recovered "
                f"cache location {recovered_root} ({recovered_exc}) either; configure a writable "
                "ENCODINGDB_SUITE_CACHE_DIR and start the run again"
            ) from recovered_exc
        preparation_progress(
            "recovery", path=recovered_root,
            message=f"the primary suite cache could not be used ({primary_error}); installed a fully "
                    f"verified copy at {recovered_root} and will reuse it on future runs",
        )
        return os.path.join(recovered_root, "canonical")
    except BaseException:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise


def _load_requests():
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r".*urllib3 v2 only supports OpenSSL.*",
        )
        import requests  # type: ignore
    return requests


# Network latency and user cancellation are separate bounds. A one-second read
# timeout rejected normal GitHub headers in release-preflight run 34815842143.
_SUITE_HTTP_TIMEOUT = (10, 30)
_SUITE_MAX_REDIRECTS = 5
_SUITE_CHUNK_BYTES = 64 * 1024


def _suite_download_events(url: str, headers: Mapping[str, str]):
    """Stream via a bounded queue; only the caller may write the owned .part.

    requests cannot reliably interrupt a blocked DNS/connect/header/body read.
    Keep that read on one daemon thread so Stop remains responsive. That thread
    owns response.close and discards late results after cancellation; it never
    writes files and never follows another redirect after cancellation.
    """
    events = queue.Queue(maxsize=2)
    stopped = threading.Event()

    def send(kind, value=None):
        while not stopped.is_set():
            try:
                events.put((kind, value), timeout=0.1)
                return True
            except queue.Full:
                pass
        return False

    def read_network():
        response = None
        try:
            requests = _load_requests()
            current_url = url
            for redirect in range(_SUITE_MAX_REDIRECTS + 1):
                if stopped.is_set():
                    return
                response = requests.get(current_url, stream=True, timeout=_SUITE_HTTP_TIMEOUT,
                                        headers=dict(headers), verify=config.REQUESTS_VERIFY,
                                        allow_redirects=False)
                if stopped.is_set():
                    return
                if response.status_code not in (301, 302, 303, 307, 308):
                    break
                location = response.headers.get("Location")
                if not location or redirect == _SUITE_MAX_REDIRECTS:
                    raise RuntimeError("Suite download exceeded redirect limit or has no redirect location")
                current_url = urljoin(current_url, location)
                response.close()
                response = None
            if response.status_code not in (200, 206):
                response.raise_for_status()
                raise RuntimeError(f"Unexpected suite download HTTP status {response.status_code}")
            if not send("status", response.status_code):
                return
            # An ignored Range is retried from zero by the caller; do not read
            # the body of that response into a partial file from another offset.
            if "Range" in headers and response.status_code != 206:
                return
            for chunk in response.iter_content(chunk_size=_SUITE_CHUNK_BYTES):
                if stopped.is_set():
                    return
                if chunk and not send("chunk", chunk):
                    return
        except BaseException as exc:
            send("error", exc)
        finally:
            try:
                if response is not None:
                    response.close()
            except Exception as exc:
                send("error", exc)
            send("done")

    worker = threading.Thread(target=read_network, name="encodingdb-suite-download", daemon=True)
    check_preparation_cancelled()
    try:
        start_owned_acquisition(worker)
        while True:
            check_preparation_cancelled()
            try:
                kind, value = events.get(timeout=0.1)
            except queue.Empty:
                continue
            check_preparation_cancelled()
            if kind == "error":
                raise value
            if kind == "done":
                return
            yield kind, value
    finally:
        stopped.set()
        # Never join or close a response here: either can wait on the socket.
        # The reader closes it on return/timeout and cannot mutate retained data.


def _download_verified_file(url: str, destination: str, *, expected_size: int,
                            verify: "Callable[[str], ClipVerificationResult]",
                            exceeds_message: str) -> None:
    """Resumable, size-bounded, hash-verified download into `destination`.

    Shared by the frozen suite pack and per-clip assets: one owned reader
    thread, `.part` resume via Range, hard stop at the declared size, and a
    caller-supplied final verification before the atomic install.
    """
    temp_path = f"{destination}.part"
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    resume_from = 0
    if os.path.exists(temp_path):
        size = os.path.getsize(temp_path)
        if 0 < size < expected_size:
            resume_from = size
        else:
            os.remove(temp_path)
    for allow_resume in (resume_from > 0, False):
        headers: Dict[str, str] = {}
        mode = "wb"
        if allow_resume and resume_from > 0:
            headers["Range"] = f"bytes={resume_from}-"
            mode = "ab"
        preparation_progress("download", path=destination, completedBytes=resume_from if mode == "ab" else 0, totalBytes=expected_size)
        events = _suite_download_events(url, headers)
        try:
            kind, status = next(events)
            if kind != "status":
                raise RuntimeError("Suite download did not provide an HTTP status")
            if allow_resume and status != 206:
                os.remove(temp_path)
                continue
            completed = resume_from if mode == "ab" else 0
            try:
                with open(temp_path, mode) as handle:
                    for kind, chunk in events:
                        if kind != "chunk":
                            raise RuntimeError("Unexpected suite download event")
                        check_preparation_cancelled()
                        if completed + len(chunk) > expected_size:
                            raise RuntimeError(exceeds_message)
                        handle.write(chunk)
                        completed += len(chunk)
                        preparation_progress("download", path=destination, completedBytes=completed, totalBytes=expected_size)
            except OSError as exc:
                if getattr(exc, "errno", None) in (errno.ENOSPC, errno.EDQUOT):
                    raise RuntimeError(
                        f"the suite cache volume ran out of free space while downloading "
                        f"{destination}: {exc}; free space on that volume and start the run again"
                    ) from exc
                if getattr(exc, "errno", None) in (errno.EACCES, errno.EPERM, errno.EROFS):
                    raise RuntimeError(
                        f"suite content could not be written to {destination}: the folder is "
                        f"write-protected or unwritable for this account ({exc})"
                    ) from exc
                raise
            break
        finally:
            events.close()
    result = verify(temp_path)
    if not result.ok:
        # The bytes are untrusted; never keep a corrupt partial for resume.
        try:
            os.remove(temp_path)
        except FileNotFoundError:
            pass
        raise RuntimeError(result.message)
    os.replace(temp_path, destination)


def _suite_free_bytes(path: str) -> Optional[int]:
    try:
        probe_path = path
        while not os.path.exists(probe_path):
            parent = os.path.dirname(probe_path)
            if parent == probe_path:
                break
            probe_path = parent
        return int(shutil.disk_usage(probe_path).free)
    except OSError:
        return None


def _suite_cache_write_error(cache_root: str) -> Optional[str]:
    """Return a clear cause when the cache root cannot accept new files."""
    try:
        os.makedirs(cache_root, exist_ok=True)
        probe_dir = os.path.join(cache_root, "canonical")
        os.makedirs(probe_dir, exist_ok=True)
        fd, probe_path = tempfile.mkstemp(prefix=".encodingdb-write-probe-", dir=probe_dir)
        os.close(fd)
        os.remove(probe_path)
    except OSError as exc:
        return f"the suite cache {cache_root} is not writable by this account ({exc})"
    return None


def _check_acquisition_storage(cache_root: str, required_bytes: int) -> None:
    """Gate a costly fetch on free space + writability before the first byte.

    Requires room for the transfer plus the ENCODINGDB_SUITE_MIN_FREE_MB floor
    (default 64 MiB; 0 disables). A declared-but-unwritable cache is reported
    as such instead of failing mid-download.
    """
    floor_mb = max(0, int(os.environ.get(SUITE_MIN_FREE_MB_ENV, "64") or "0"))
    required = int(required_bytes) + floor_mb * 1024 * 1024
    write_error = _suite_cache_write_error(cache_root)
    if write_error is not None:
        raise RuntimeError(write_error)
    free = _suite_free_bytes(cache_root)
    if free is not None and free < required:
        raise RuntimeError(
            f"acquiring suite content needs {required_bytes:,} bytes plus a "
            f"{floor_mb * 1024 * 1024:,} byte free-space floor, but the volume holding "
            f"{cache_root} has only {free:,} bytes free; free space or set "
            f"{SUITE_MIN_FREE_MB_ENV} to 0 to override the floor"
        )


def _download_suite_pack(url: str, destination: str, metadata: Mapping[str, Any]) -> None:
    distribution = dict(metadata.get("distribution") or {})
    expected_size = int(distribution.get("byteSize") or 0)
    _download_verified_file(
        url,
        destination,
        expected_size=expected_size,
        verify=lambda path: _verify_suite_pack_file(path, metadata),
        exceeds_message="Suite download exceeds declared pack size",
    )


def _full_pack_fallback_allowed(allow_full_pack: bool) -> bool:
    if not allow_full_pack:
        return False
    setting = os.environ.get(SUITE_ALLOW_FULL_PACK_ENV, "1").strip().lower()
    return setting not in ("0", "false", "no", "off")


def _disclose_large_download(clip: SuiteClip, pack_bytes: int, clip_error: Optional[str]) -> None:
    """Make an unexpected full-pack transfer visible before it starts."""
    reason = f" ({clip_error})" if clip_error else " (no per-clip assets are published for this suite yet)"
    message = (
        f"The small per-clip asset for {clip.clip_id} could not be acquired{reason}. "
        f"Falling back to the full frozen suite pack: {pack_bytes:,} bytes "
        f"(about {pack_bytes / (2 ** 30):.1f} GiB) will be transferred into the local suite cache. "
        f"Set {SUITE_CLIP_BASE_URL_ENV} to a host with published per-clip assets to avoid this."
    )
    preparation_progress("large-download", clipId=clip.clip_id, totalBytes=pack_bytes, message=message)
    print(f"EncodingDB: {message}", file=sys.stderr)


def _clip_asset_target(cache_base: str, clip: SuiteClip, asset: Mapping[str, Any]) -> str:
    if str(asset.get("role") or "") == "clip":
        return clip_cache_path(clip, cache_base)
    name = str(asset.get("path") or "").rsplit("notices/", 1)[-1]
    return os.path.join(cache_base, "notices", name)


def _verified_asset_result(path: str, asset: Mapping[str, Any], clip: SuiteClip) -> ClipVerificationResult:
    if str(asset.get("role") or "") == "clip":
        return _verify_suite_clip_bytes(path, clip)
    if not os.path.exists(path):
        return ClipVerificationResult(False, f"{os.path.basename(path)} not found", {"path": path})
    actual_size = os.path.getsize(path)
    if actual_size != int(asset.get("byteSize") or 0):
        return ClipVerificationResult(False, f"{os.path.basename(path)} size mismatch", {"path": path})
    if _sha256_of_file(path).lower() != str(asset.get("sha256") or "").lower():
        return ClipVerificationResult(False, f"{os.path.basename(path)} checksum mismatch", {"path": path})
    return ClipVerificationResult(True, "ok", {"path": path})


def _pending_clip_assets(clip: SuiteClip, cache_base: str,
                         assets: Sequence[Mapping[str, Any]]) -> Tuple[List[Tuple[Mapping[str, Any], str]], int]:
    pending: List[Tuple[Mapping[str, Any], str]] = []
    cached_bytes = 0
    for asset in assets:
        target = _clip_asset_target(cache_base, clip, asset)
        if _verified_asset_result(target, asset, clip).ok:
            cached_bytes += int(asset.get("byteSize") or 0)
        else:
            pending.append((asset, target))
    return pending, cached_bytes


def _materialize_clip_from_distribution(clip: SuiteClip, distribution: Mapping[str, Any],
                                        cache_base: str) -> str:
    """Fetch only this clip's canonical file plus its license notices.

    Each asset resumes via its own .part, stops at the declared size, and is
    hash-verified against the frozen manifest before the atomic install; a
    corrupt response never installs.
    """
    entry = dict(distribution.get("clips") or {}).get(clip.clip_id)
    if not entry:
        raise RuntimeError(f"clip distribution metadata has no entry for {clip.clip_id}")
    assets = list(dict(entry).get("assets") or [])
    pending, _ = _pending_clip_assets(clip, cache_base, assets)
    if not pending:
        return clip_cache_path(clip, cache_base)
    transfer_bytes = sum(int(asset.get("byteSize") or 0) for asset, _ in pending)
    headroom_bytes = max(64 * 1024 * 1024, transfer_bytes // 20)
    _check_acquisition_storage(cache_base, transfer_bytes + headroom_bytes)
    for _, target in pending:
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
        except OSError as exc:
            raise RuntimeError(
                f"the suite cache folder {os.path.dirname(target)} is not writable by this account ({exc})"
            ) from exc
    label = f"Suite clip download for {clip.clip_id}"
    for asset, target in pending:
        url = _clip_asset_url(distribution, str(asset.get("downloadName") or ""))
        _download_verified_file(
            url,
            target,
            expected_size=int(asset.get("byteSize") or 0),
            verify=lambda path, current=asset: _verified_asset_result(path, current, clip),
            exceeds_message=f"{label} exceeds declared file size",
        )
    result = _verify_suite_clip_bytes(clip_cache_path(clip, cache_base), clip)
    if not result.ok:
        raise RuntimeError(result.message)
    return clip_cache_path(clip, cache_base)


def _packaged_canonical_path(clip: SuiteClip) -> Optional[str]:
    for manifest_path in _manifest_resource_candidates():
        candidate = os.path.join(os.path.dirname(manifest_path), "canonical", clip.file_name)
        if os.path.exists(candidate):
            return candidate
    return None


def _pack_state(pack_metadata: Mapping[str, Any], cache_base: str) -> Dict[str, bool]:
    pack_cached = _verify_suite_pack_file(_cache_suite_pack_path(pack_metadata, cache_base), pack_metadata).ok
    fingerprint = str(pack_metadata.get("suiteFingerprint") or "").strip()
    # Without a fingerprint the extraction directory is unnameable; assume absent.
    extracted = bool(fingerprint) and os.path.isdir(
        os.path.join(_suite_pack_extract_root(pack_metadata, cache_base), "canonical"))
    return {"packCached": pack_cached, "extracted": extracted}


def _plan_clip_acquisition(clip: SuiteClip, cache_base: str, *, clip_route_available: bool,
                           pack_metadata: Mapping[str, Any], pack_state: Mapping[str, bool],
                           allow_full_pack: bool) -> Dict[str, Any]:
    """Decide one clip's acquisition without side effects beyond hash reads."""
    packaged = _packaged_canonical_path(clip)
    if packaged is not None and _verify_suite_clip_bytes(packaged, clip).ok:
        return {"source": "packaged", "transferBytes": 0, "cachedBytes": clip.byte_size, "peakBytes": 0,
                "note": "verified canonical asset is bundled with the client"}
    cached_path = clip_cache_path(clip, cache_base)
    if _verify_suite_clip_bytes(cached_path, clip).ok:
        return {"source": "cache", "transferBytes": 0, "cachedBytes": clip.byte_size, "peakBytes": 0, "note": "hash-verified cache hit"}
    pack_bytes = int(dict(pack_metadata.get("distribution") or {}).get("byteSize") or 0)
    if clip_route_available:
        distribution = load_clip_distribution_metadata(manifest=None)
        entry = dict((distribution or {}).get("clips") or {}).get(clip.clip_id) or {}
        assets = list(dict(entry).get("assets") or [])
        pending, cached_bytes = _pending_clip_assets(clip, cache_base, assets)
        transfer = sum(int(asset.get("byteSize") or 0) for asset, _ in pending)
        headroom = max(64 * 1024 * 1024, transfer // 20)
        return {"source": "clip", "transferBytes": transfer, "cachedBytes": cached_bytes,
                "peakBytes": transfer + headroom, "note": "per-clip assets are published for this suite"}
    if not _full_pack_fallback_allowed(allow_full_pack):
        return {"source": "unavailable", "transferBytes": 0, "cachedBytes": 0,
                "peakBytes": clip.byte_size,
                "note": (f"clip is not cached, no per-clip assets are available, and the full pack "
                         f"({pack_bytes:,} bytes) is disabled via {SUITE_ALLOW_FULL_PACK_ENV}/allow_full_pack")}
    transfer = 0 if pack_state.get("packCached") else pack_bytes
    extract_bytes = 0 if pack_state.get("extracted") else pack_bytes
    return {"source": "pack", "transferBytes": transfer, "cachedBytes": 0,
            "peakBytes": transfer + extract_bytes + clip.byte_size,
            "note": f"only the full frozen suite pack ({pack_bytes:,} bytes) is published for this suite"}


def acquisition_estimate(clip_ids: Optional[Sequence[str]] = None, *,
                         cache_root: Optional[str] = None,
                         allow_full_pack: bool = True,
                         manifest: Optional[SuiteManifest] = None) -> Dict[str, Any]:
    """Truthful, side-effect-free transfer/peak-storage estimate for a fetch.

    Stable read-only API for UIs: reports exactly what `ensure_suite_clip`/
    `ensure_suite` would transfer per clip (cache hit, per-clip assets, or the
    full pack) before any byte is downloaded.
    """
    suite_manifest = manifest or load_default_suite_manifest()
    resolved_cache_root = cache_root or _suite_cache_root()
    target_ids = list(clip_ids) if clip_ids else [clip.clip_id for clip in suite_manifest.clips]
    distribution = load_clip_distribution_metadata(manifest=suite_manifest)
    route_available = clip_distribution_available(distribution)
    pack_metadata = load_suite_pack_metadata()
    pack_state = _pack_state(pack_metadata, resolved_cache_root)
    plans: Dict[str, Any] = {}
    transfer_total = 0
    cached_total = 0
    peak_total = 0
    warnings: List[str] = []
    worst = "cache"
    pack_counted = False
    severity = {"cache": 0, "packaged": 0, "pack": 1, "clip": 1, "unavailable": 2}
    for clip_id in target_ids:
        clip = get_clip(suite_manifest, clip_id)
        plan = _plan_clip_acquisition(clip, resolved_cache_root, clip_route_available=route_available,
                                      pack_metadata=pack_metadata, pack_state=pack_state,
                                      allow_full_pack=allow_full_pack)
        if plan["source"] == "pack":
            if pack_counted:
                plan["transferBytes"] = 0
                plan["peakBytes"] = clip.byte_size
                plan["note"] = "shared full suite pack counted with the first missing clip"
            pack_counted = True
        plans[clip_id] = {"clipId": clip_id, "fileName": clip.file_name, **plan}
        transfer_total += int(plan["transferBytes"])
        cached_total += int(plan["cachedBytes"])
        peak_total += int(plan["peakBytes"])
        if severity.get(plan["source"], 0) > severity.get(worst, 0):
            worst = plan["source"]
        if plan["source"] in ("unavailable", "pack"):
            warnings.append(f"{clip_id}: {plan['note']}")
    free = _suite_free_bytes(resolved_cache_root)
    floor_mb = max(0, int(os.environ.get(SUITE_MIN_FREE_MB_ENV, "64") or "0"))
    storage_ok = free is None or free >= peak_total + floor_mb * 1024 * 1024
    return {
        "schemaVersion": 1,
        "suiteVersion": suite_manifest.suite_version,
        "cacheRoot": resolved_cache_root,
        "strategy": worst,
        "clipRouteAvailable": bool(route_available),
        "allowFullPack": bool(_full_pack_fallback_allowed(allow_full_pack)),
        "fullPackBytes": int(dict(pack_metadata.get("distribution") or {}).get("byteSize") or 0),
        "bytesToTransfer": transfer_total,
        "bytesAlreadyVerified": cached_total,
        "peakStorageBytes": peak_total,
        "freeBytes": free,
        "freeFloorBytes": floor_mb * 1024 * 1024,
        "storageOk": bool(storage_ok),
        "clips": plans,
        "warnings": warnings,
    }


def _acquire_missing_clip(clip: SuiteClip, cache_base: str, *, allow_full_pack: bool) -> str:
    distribution = load_clip_distribution_metadata(manifest=None)
    clip_error: Optional[str] = None
    if clip_distribution_available(distribution):
        try:
            return _materialize_clip_from_distribution(clip, distribution, cache_base)
        except RuntimeError as exc:
            clip_error = str(exc)
            preparation_progress("recovery", clipId=clip.clip_id,
                                 message=f"per-clip acquisition failed ({clip_error}); considering the full pack")
    pack_metadata = load_suite_pack_metadata()
    pack_bytes = int(dict(pack_metadata.get("distribution") or {}).get("byteSize") or 0)
    if not _full_pack_fallback_allowed(allow_full_pack):
        detail = f" Per-clip download failed: {clip_error}." if clip_error else ""
        raise RuntimeError(
            f"suite clip {clip.clip_id} is not cached and the full frozen suite pack "
            f"({pack_bytes:,} bytes) download is disabled. Set {SUITE_CLIP_BASE_URL_ENV} to a host with "
            "the published per-clip assets, provide the pack via ENCODINGDB_SUITE_PACK_PATH, or allow "
            f"{SUITE_ALLOW_FULL_PACK_ENV}." + detail
        )
    state = _pack_state(pack_metadata, cache_base)
    needed = clip.byte_size
    if not state["packCached"]:
        needed += pack_bytes
    if not state["extracted"]:
        needed += pack_bytes
    _check_acquisition_storage(cache_base, needed)
    if not state["packCached"] or not state["extracted"]:
        _disclose_large_download(clip, pack_bytes, clip_error)
    return _materialize_clip_from_suite_pack(clip, pack_metadata, cache_base)


def _local_suite_pack_candidates(file_name: str) -> List[str]:
    candidates: List[str] = []
    explicit = os.environ.get("ENCODINGDB_SUITE_PACK_PATH", "").strip()
    if explicit:
        candidates.append(os.path.abspath(explicit))
    if getattr(sys, "frozen", False):
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)), file_name))
    for manifest_path in _manifest_resource_candidates():
        suite_root = os.path.dirname(manifest_path)
        candidates.append(os.path.join(suite_root, "packs", file_name))
        candidates.append(os.path.join(suite_root, file_name))
    unique: List[str] = []
    seen = set()
    for candidate in candidates:
        normalized = os.path.abspath(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def _ensure_suite_pack_available(pack_metadata: Mapping[str, Any], cache_root: Optional[str] = None) -> str:
    cached_pack_path = _cache_suite_pack_path(pack_metadata, cache_root)
    result = _verify_suite_pack_file(cached_pack_path, pack_metadata)
    if result.ok:
        return cached_pack_path
    distribution = dict(pack_metadata.get("distribution") or {})
    file_name = str(distribution.get("fileName") or DEFAULT_SUITE_PACK_FILE_NAME)
    for candidate in _local_suite_pack_candidates(file_name):
        candidate_result = _verify_suite_pack_file(candidate, pack_metadata)
        if not candidate_result.ok:
            continue
        os.makedirs(os.path.dirname(cached_pack_path), exist_ok=True)
        staging = tempfile.NamedTemporaryFile(delete=False, dir=os.path.dirname(cached_pack_path), prefix=".suite-pack-", suffix=".tmp")
        staging.close()
        try:
            _copy_preparation_file(candidate, staging.name)
            verified = _verify_suite_pack_file(staging.name, pack_metadata)
            if not verified.ok:
                raise RuntimeError(verified.message)
            os.replace(staging.name, cached_pack_path)
            return cached_pack_path
        finally:
            try:
                os.remove(staging.name)
            except FileNotFoundError:
                pass
    download_urls = [str(value).strip() for value in distribution.get("downloadUrls") or [] if str(value).strip()]
    override_url = os.environ.get("ENCODINGDB_SUITE_PACK_URL", "").strip()
    if override_url:
        download_urls.insert(0, override_url)
    last_error: Optional[str] = None
    for url in download_urls:
        try:
            _download_suite_pack(url, cached_pack_path, pack_metadata)
            return cached_pack_path
        except Exception as exc:
            last_error = str(exc)
    if last_error:
        raise RuntimeError(f"EncodingDB suite pack could not be acquired: {last_error}")
    raise RuntimeError(
        f"EncodingDB suite pack is unavailable. Expected {file_name} next to the packaged client, "
        "at ENCODINGDB_SUITE_PACK_PATH, or from ENCODINGDB_SUITE_PACK_URL."
    )


def _materialize_clip_from_suite_pack(clip: SuiteClip, pack_metadata: Mapping[str, Any], cache_root: Optional[str] = None) -> str:
    cache_base = cache_root or _suite_cache_root()
    pack_path = _ensure_suite_pack_available(pack_metadata, cache_base)
    extracted_canonical_root = _extract_suite_pack(pack_path, pack_metadata, cache_base)
    source_path = os.path.join(extracted_canonical_root, clip.file_name)
    target_path = clip_cache_path(clip, cache_base)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    staging = tempfile.NamedTemporaryFile(delete=False, dir=os.path.dirname(target_path), prefix=f".{clip.clip_id}-", suffix=".staging")
    staging.close()
    try:
        _copy_preparation_file(source_path, staging.name)
        result = verify_suite_clip(staging.name, clip)
        if not result.ok:
            raise RuntimeError(result.message)
        os.replace(staging.name, target_path)
    finally:
        try:
            os.remove(staging.name)
        except FileNotFoundError:
            pass
    return target_path


def _verify_suite_clip_bytes(path: str, clip: SuiteClip) -> ClipVerificationResult:
    preparation_progress("validate", clipId=clip.clip_id, path=path)
    if not os.path.exists(path):
        return ClipVerificationResult(False, f"{clip.file_name} not found", {"path": path})
    actual_size = os.path.getsize(path)
    if actual_size != clip.byte_size:
        return ClipVerificationResult(
            False,
            f"{clip.file_name} size mismatch (expected {clip.byte_size}, got {actual_size})",
            {"path": path, "expected": clip.byte_size, "actual": actual_size, "field": "byteSize"},
        )
    actual_hash = _sha256_of_file(path)
    if actual_hash.lower() != clip.sha256.lower():
        return ClipVerificationResult(
            False,
            f"{clip.file_name} checksum mismatch",
            {"path": path, "expected": clip.sha256, "actual": actual_hash, "field": "sha256"},
        )

    return ClipVerificationResult(True, "ok", {"path": path})


def verify_suite_clip(path: str, clip: SuiteClip) -> ClipVerificationResult:
    result = _verify_suite_clip_bytes(path, clip)
    if not result.ok:
        return result
    probe = _probe_clip(path)
    expected_container = str(clip.acquisition.get("container") or "").strip()
    if expected_container and not _container_matches(expected_container, str(probe.get("containerFormat") or "")):
        return ClipVerificationResult(
            False,
            f"{clip.file_name} container mismatch (expected {expected_container}, got {probe.get('containerFormat')})",
            {"path": path, "field": "container", "expected": expected_container, "actual": probe.get("containerFormat")},
        )
    expected_codec = str(clip.acquisition.get("videoCodec") or "").strip().lower()
    actual_codec = str(probe.get("videoCodec") or "").strip().lower()
    if expected_codec and expected_codec != "retained-reference" and expected_codec != actual_codec:
        return ClipVerificationResult(
            False,
            f"{clip.file_name} videoCodec mismatch (expected {expected_codec}, got {actual_codec})",
            {"path": path, "field": "videoCodec", "expected": expected_codec, "actual": actual_codec},
        )
    expected_pairs: Tuple[Tuple[str, Any, Any], ...] = (
        ("width", clip.media.width, probe["width"]),
        ("height", clip.media.height, probe["height"]),
        ("pixelFormat", clip.media.pixel_format, probe["pixFmt"]),
        ("bitDepth", clip.media.bit_depth, probe["bitDepth"]),
        ("chromaSubsampling", clip.media.chroma_subsampling, probe["chromaSubsampling"]),
        ("colorRange", clip.media.color_range, probe["colorRange"]),
        ("colorMatrix", clip.media.color_matrix, probe["colorSpace"]),
        ("colorTransfer", clip.media.color_transfer, probe["colorTransfer"]),
        ("colorPrimaries", clip.media.color_primaries, probe["colorPrimaries"]),
        ("fieldOrder", clip.media.field_order, probe["fieldOrder"]),
        ("frameCount", clip.media.frame_count, probe["frameCount"]),
        ("frameRate", (clip.media.frame_rate_num, clip.media.frame_rate_den), probe["frameRate"]),
        ("duration", (clip.media.duration_num, clip.media.duration_den), probe["durationRatio"]),
    )
    for field_name, expected, actual in expected_pairs:
        if expected != actual:
            return ClipVerificationResult(
                False,
                f"{clip.file_name} {field_name} mismatch (expected {expected}, got {actual})",
                {"path": path, "field": field_name, "expected": expected, "actual": actual},
            )

    expected_hdr = clip.media.hdr_metadata
    actual_hdr = probe["hdrMetadata"]
    if expected_hdr is None:
        if actual_hdr not in (None, [], {}):
            return ClipVerificationResult(
                False,
                f"{clip.file_name} HDR metadata mismatch (expected none, got {actual_hdr})",
                {"path": path, "field": "hdrMetadata", "expected": None, "actual": actual_hdr},
            )
    elif expected_hdr != actual_hdr:
        return ClipVerificationResult(
            False,
            f"{clip.file_name} HDR metadata mismatch",
            {"path": path, "field": "hdrMetadata", "expected": expected_hdr, "actual": actual_hdr},
        )

    return ClipVerificationResult(True, "ok", {"path": path})


def ensure_suite_clip(
    clip: SuiteClip,
    *,
    cache_root: Optional[str] = None,
    regenerate_on_mismatch: bool = True,
    allow_full_pack: bool = True,
) -> PreparedSuiteClip:
    wait_for_owned_acquisition()
    resolved_cache_root = cache_root or _suite_cache_root()
    packaged_path: Optional[str] = None
    for manifest_path in _manifest_resource_candidates():
        candidate = os.path.join(os.path.dirname(manifest_path), "canonical", clip.file_name)
        if not os.path.exists(candidate):
            continue
        packaged_result = verify_suite_clip(candidate, clip)
        if not packaged_result.ok:
            raise RuntimeError(f"Packaged canonical suite asset is invalid: {packaged_result.message}")
        packaged_path = candidate
        break
    path = packaged_path
    if packaged_path is None:
        path = clip_cache_path(clip, resolved_cache_root)
        result = verify_suite_clip(path, clip)
        if not result.ok and regenerate_on_mismatch:
            path = _acquire_missing_clip(clip, resolved_cache_root, allow_full_pack=allow_full_pack)
            # The acquired stream passed this clip's complete media contract.
            # Recheck the renamed bytes, including SHA, before reusing that result.
            result = _verify_suite_clip_bytes(path, clip)
        if not result.ok:
            raise RuntimeError(result.message)
    elif cache_root is not None:
        path = clip_cache_path(clip, resolved_cache_root)
        result = verify_suite_clip(path, clip)
        if not result.ok and regenerate_on_mismatch:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            handle, staging_path = tempfile.mkstemp(prefix=f".{clip.clip_id}-", suffix=".staging", dir=os.path.dirname(path))
            os.close(handle)
            try:
                _copy_preparation_file(packaged_path, staging_path)
                os.replace(staging_path, path)
            finally:
                try:
                    os.remove(staging_path)
                except FileNotFoundError:
                    pass
            result = verify_suite_clip(path, clip)
    else:
        result = _verify_suite_clip_bytes(path, clip)
    if not result.ok:
        raise RuntimeError(result.message)

    return PreparedSuiteClip(
        suite_version=SUITE_VERSION,
        clip_id=clip.clip_id,
        canonical_content_class=clip.canonical_content_class,
        payload_content_class=clip.payload_content_class,
        workload_id=clip.clip_id,
        path=path,
        input_hash=clip.sha256,
        file_name=clip.file_name,
    )


def ensure_suite(
    manifest: Optional[SuiteManifest] = None,
    *,
    clip_ids: Optional[Sequence[str]] = None,
    cache_root: Optional[str] = None,
    allow_full_pack: bool = True,
) -> List[PreparedSuiteClip]:
    suite = manifest or load_default_suite_manifest()
    target_ids = set(clip_ids or [clip.clip_id for clip in suite.clips])
    prepared: List[PreparedSuiteClip] = []
    for index, clip in enumerate(suite.clips, 1):
        preparation_progress("clip", clipId=clip.clip_id, completedClips=index - 1, totalClips=len(suite.clips))
        if clip.clip_id in target_ids:
            prepared.append(ensure_suite_clip(clip, cache_root=cache_root, allow_full_pack=allow_full_pack))
    return prepared


def has_general_pl_coverage(prepared_clips: Iterable[PreparedSuiteClip]) -> bool:
    observed = {clip.canonical_content_class for clip in prepared_clips}
    return observed == set(REQUIRED_CONTENT_CLASSES)
