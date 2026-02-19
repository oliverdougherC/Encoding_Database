"""Test video catalog, download, and caching for multi-content benchmarks (Sprint 5)."""

import hashlib
import os
import sys
from typing import Dict, List, Optional, Tuple

from . import config

CONTENT_CLASSES: List[str] = [
    "mixed",
    "talkingHead",
    "action",
    "animation",
    "screen",
    "nature",
    "gaming",
]

CONTENT_CLASS_LABELS: Dict[str, str] = {
    "mixed": "Mixed (Original)",
    "talkingHead": "Talking Head",
    "action": "Action / Sports",
    "animation": "Animation / Cartoon",
    "screen": "Screen Recording",
    "nature": "Nature / Documentary",
    "gaming": "Gaming",
}

RESOLUTION_PRESETS: Dict[str, Tuple[int, int]] = {
    "480p": (854, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "4k": (3840, 2160),
}

RESOLUTION_ORDER: List[str] = ["480p", "720p", "1080p", "1440p", "4k"]

RELEASES_BASE_URL = (
    "https://github.com/oliverdougherC/Encoding_Database"
    "/releases/download/test-clips-v1"
)

TEST_VIDEO_CATALOG: List[Dict[str, object]] = [
    {
        "name": "sample.mp4",
        "contentClass": "mixed",
        "resolution": "1080p",
        "duration": 20.0,
        "sha256": config.SAMPLE_VIDEO_SHA256,
        "sizeBytes": config.SAMPLE_VIDEO_SIZE_BYTES,
    },
    {
        "name": "talking_head_1080p.mp4",
        "contentClass": "talkingHead",
        "resolution": "1080p",
        "duration": 15.0,
        "sha256": "",
        "sizeBytes": 0,
    },
    {
        "name": "action_1080p.mp4",
        "contentClass": "action",
        "resolution": "1080p",
        "duration": 15.0,
        "sha256": "",
        "sizeBytes": 0,
    },
    {
        "name": "animation_1080p.mp4",
        "contentClass": "animation",
        "resolution": "1080p",
        "duration": 15.0,
        "sha256": "",
        "sizeBytes": 0,
    },
    {
        "name": "screen_1080p.mp4",
        "contentClass": "screen",
        "resolution": "1080p",
        "duration": 15.0,
        "sha256": "",
        "sizeBytes": 0,
    },
    {
        "name": "nature_1080p.mp4",
        "contentClass": "nature",
        "resolution": "1080p",
        "duration": 15.0,
        "sha256": "",
        "sizeBytes": 0,
    },
    {
        "name": "gaming_1080p.mp4",
        "contentClass": "gaming",
        "resolution": "1080p",
        "duration": 15.0,
        "sha256": "",
        "sizeBytes": 0,
    },
]


def get_cache_dir() -> str:
    """Return the directory used to cache downloaded test clips."""
    home = os.path.expanduser("~")
    cache_dir = os.path.join(home, ".encodingdb", "test-clips")
    os.makedirs(cache_dir, mode=0o755, exist_ok=True)
    return cache_dir


def _sha256_file(path: str) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def download_test_video(video_meta: Dict[str, object], force: bool = False) -> Optional[str]:
    """Download a test video from GitHub Releases and verify its SHA256.

    Returns the local file path on success, or None on failure.
    """
    name = str(video_meta["name"])
    sha256 = str(video_meta.get("sha256") or "")
    size_bytes = int(video_meta.get("sizeBytes") or 0)

    if name == "sample.mp4":
        from .ffmpeg import get_default_sample_path
        local = get_default_sample_path()
        if local and os.path.exists(local):
            return local

    cache_dir = get_cache_dir()
    local_path = os.path.join(cache_dir, name)

    if not force and os.path.exists(local_path):
        if sha256 and _sha256_file(local_path) == sha256.lower():
            return local_path
        if not sha256 and os.path.getsize(local_path) > 0:
            return local_path

    url = f"{RELEASES_BASE_URL}/{name}"
    print(f"Downloading test clip: {name}...")

    try:
        import requests  # lazy import
        resp = requests.get(url, stream=True, timeout=120, verify=config.REQUESTS_VERIFY)
        resp.raise_for_status()

        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        tmp_path = local_path + ".tmp"

        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=256 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = (downloaded / total) * 100
                    print(f"\r  {downloaded / (1024*1024):.1f} / {total / (1024*1024):.1f} MB ({pct:.0f}%)", end="", flush=True)

        print()

        if sha256:
            actual = _sha256_file(tmp_path)
            if actual != sha256.lower():
                print(f"  SHA256 mismatch for {name}: expected {sha256[:16]}..., got {actual[:16]}...", file=sys.stderr)
                os.remove(tmp_path)
                return None

        if size_bytes > 0 and os.path.getsize(tmp_path) != size_bytes:
            print(f"  Size mismatch for {name}: expected {size_bytes}, got {os.path.getsize(tmp_path)}", file=sys.stderr)
            os.remove(tmp_path)
            return None

        os.replace(tmp_path, local_path)
        print(f"  Cached: {local_path}")
        return local_path

    except Exception as e:
        print(f"  Failed to download {name}: {e}", file=sys.stderr)
        return None


def ensure_test_videos(
    content_classes: Optional[List[str]] = None,
    resolutions: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Download and cache all required test clips.

    Returns a dict mapping "contentClass:resolution" keys to local file paths.
    """
    wanted_cc = set(content_classes) if content_classes else {"mixed"}
    wanted_res = set(resolutions) if resolutions else {"1080p"}
    result: Dict[str, str] = {}

    for meta in TEST_VIDEO_CATALOG:
        cc = str(meta["contentClass"])
        res = str(meta["resolution"])
        if cc not in wanted_cc:
            continue
        if res not in wanted_res:
            continue

        path = download_test_video(meta)
        if path:
            result[f"{cc}:{res}"] = path

    return result


def get_video_path(content_class: str, resolution: str = "1080p") -> Optional[str]:
    """Return the cached path for a specific test video, or None."""
    cache_key = f"{content_class}:{resolution}"

    if content_class == "mixed" and resolution == "1080p":
        from .ffmpeg import get_default_sample_path
        local = get_default_sample_path()
        if local and os.path.exists(local):
            return local

    cache_dir = get_cache_dir()
    for meta in TEST_VIDEO_CATALOG:
        if str(meta["contentClass"]) == content_class and str(meta["resolution"]) == resolution:
            name = str(meta["name"])
            local_path = os.path.join(cache_dir, name)
            if os.path.exists(local_path):
                return local_path

    return None


def available_content_classes() -> List[str]:
    """Return content classes that have at least one cached test video locally."""
    avail: List[str] = []
    for cc in CONTENT_CLASSES:
        for meta in TEST_VIDEO_CATALOG:
            if str(meta["contentClass"]) == cc:
                path = get_video_path(cc, str(meta["resolution"]))
                if path:
                    avail.append(cc)
                    break
    return avail
