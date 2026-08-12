import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import config

SUITE_VERSION = "encodingdb-test-suite-v1"
DEFAULT_QUICK_CLIP_ID = "sports-action-960x540-24p"
MANIFEST_RELATIVE_PATH = os.path.join("resources", "test_suite_v1", "manifest.json")

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
    lavfi: str
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


def load_default_suite_manifest() -> SuiteManifest:
    with open(get_manifest_path(), "r", encoding="utf-8") as handle:
        payload = json.load(handle)
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
                lavfi=str(clip["acquisition"]["ffmpegLavfi"]),
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
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
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


def _probe_clip(path: str) -> Dict[str, Any]:
    cmd = [
        config.ffprobe_exe(),
        "-v", "error",
        "-count_frames",
        "-select_streams", "v:0",
        "-show_entries",
        "stream=width,height,pix_fmt,bits_per_raw_sample,color_range,color_space,color_transfer,color_primaries,field_order,avg_frame_rate,r_frame_rate,nb_read_frames:stream_side_data",
        "-of", "json",
        path,
    ]
    proc = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    payload = json.loads(proc.stdout or "{}")
    streams = payload.get("streams") if isinstance(payload, dict) else None
    stream = streams[0] if isinstance(streams, list) and streams else {}
    if not isinstance(stream, dict):
        stream = {}

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
    subprocess.run(_generation_command(lavfi, output_path, frame_count), check=True)


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
    return os.path.join(cache_root or _suite_cache_root(), clip.file_name)


def verify_suite_clip(path: str, clip: SuiteClip) -> ClipVerificationResult:
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

    probe = _probe_clip(path)
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
) -> PreparedSuiteClip:
    root = cache_root or _suite_cache_root()
    path = clip_cache_path(clip, root)
    if not os.path.exists(path):
        _generate_clip(clip.lavfi, path, clip.media.frame_count)

    result = verify_suite_clip(path, clip)
    if not result.ok and regenerate_on_mismatch:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        _generate_clip(clip.lavfi, path, clip.media.frame_count)
        result = verify_suite_clip(path, clip)
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
) -> List[PreparedSuiteClip]:
    suite = manifest or load_default_suite_manifest()
    target_ids = set(clip_ids or [clip.clip_id for clip in suite.clips])
    prepared: List[PreparedSuiteClip] = []
    for clip in suite.clips:
        if clip.clip_id in target_ids:
            prepared.append(ensure_suite_clip(clip, cache_root=cache_root))
    return prepared


def has_general_pl_coverage(prepared_clips: Iterable[PreparedSuiteClip]) -> bool:
    observed = {clip.canonical_content_class for clip in prepared_clips}
    return observed == set(REQUIRED_CONTENT_CLASSES)
