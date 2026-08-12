#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from fractions import Fraction
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from client import suite  # noqa: E402

LOCK_SCHEMA_VERSION = 1
STATUS_SCHEMA_VERSION = 1
DEFAULT_CLIENT_SUITE_DIR = ROOT_DIR / "client" / "resources" / "test_suite_v1"
DEFAULT_SERVER_SUITE_DIR = ROOT_DIR / "server" / "resources" / "test_suite_v1"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")


def load_review(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError("review file is invalid")
    return payload


def ensure_true(value: Any, message: str) -> None:
    if value is not True:
        raise RuntimeError(message)


def normalize_clip_path(base_dir: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def default_output_paths() -> Dict[str, Path]:
    return {
        "client_manifest_out": DEFAULT_CLIENT_SUITE_DIR / "manifest.json",
        "server_manifest_out": DEFAULT_SERVER_SUITE_DIR / "manifest.json",
        "client_lock_out": DEFAULT_CLIENT_SUITE_DIR / "suite-lock.json",
        "server_lock_out": DEFAULT_SERVER_SUITE_DIR / "suite-lock.json",
        "client_status_out": DEFAULT_CLIENT_SUITE_DIR / "finalization-status.json",
        "server_status_out": DEFAULT_SERVER_SUITE_DIR / "finalization-status.json",
        "client_pack_manifest_out": DEFAULT_CLIENT_SUITE_DIR / "suite-pack.json",
        "server_pack_manifest_out": DEFAULT_SERVER_SUITE_DIR / "suite-pack.json",
    }


def probe_media_contract(path: Path) -> Dict[str, Any]:
    probe = suite._probe_clip(str(path))
    frame_rate = probe.get("frameRate")
    duration_ratio = probe.get("durationRatio")
    if not frame_rate or not duration_ratio:
        raise RuntimeError(f"ffprobe contract is incomplete for {path.name}")
    return {
        "frameCount": int(probe.get("frameCount") or 0),
        "container": str(probe.get("containerFormat") or ""),
        "videoCodec": str(probe.get("videoCodec") or ""),
        "duration": {"numerator": int(duration_ratio[0]), "denominator": int(duration_ratio[1])},
        "frameRate": {"numerator": int(frame_rate[0]), "denominator": int(frame_rate[1])},
        "width": int(probe.get("width") or 0),
        "height": int(probe.get("height") or 0),
        "pixelFormat": str(probe.get("pixFmt") or ""),
        "bitDepth": int(probe.get("bitDepth") or 0),
        "chromaSubsampling": str(probe.get("chromaSubsampling") or ""),
        "colorPrimaries": str(probe.get("colorPrimaries") or ""),
        "colorTransfer": str(probe.get("colorTransfer") or ""),
        "colorMatrix": str(probe.get("colorSpace") or ""),
        "colorRange": str(probe.get("colorRange") or ""),
        "fieldOrder": str(probe.get("fieldOrder") or ""),
        "hdrMetadata": probe.get("hdrMetadata") or None,
    }


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"{label} must be an object")
    return value


def _normalize_rational(value: Any, label: str) -> Dict[str, int]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"{label} must be an object with numerator and denominator")
    numerator = int(value.get("numerator") or 0)
    denominator = int(value.get("denominator") or 0)
    if numerator <= 0 or denominator <= 0:
        raise RuntimeError(f"{label} must be a positive rational")
    return {"numerator": numerator, "denominator": denominator}


def _normalize_range_int(value: Any, label: str) -> Dict[str, int]:
    if isinstance(value, int):
        if value <= 0:
            raise RuntimeError(f"{label} must be positive")
        return {"min": value, "max": value}
    mapping = _require_mapping(value, label)
    minimum = int(mapping.get("min") or 0)
    maximum = int(mapping.get("max") or 0)
    if minimum <= 0 or maximum <= 0 or minimum > maximum:
        raise RuntimeError(f"{label} bounds are invalid")
    return {"min": minimum, "max": maximum}


def _normalize_range_rational(value: Any, label: str) -> Dict[str, Dict[str, int]]:
    if isinstance(value, Mapping) and "numerator" in value and "denominator" in value:
        exact = _normalize_rational(value, label)
        return {"min": exact, "max": exact}
    mapping = _require_mapping(value, label)
    minimum = _normalize_rational(mapping.get("min"), f"{label}.min")
    maximum = _normalize_rational(mapping.get("max"), f"{label}.max")
    minimum_fraction = minimum["numerator"] / minimum["denominator"]
    maximum_fraction = maximum["numerator"] / maximum["denominator"]
    if minimum_fraction > maximum_fraction:
        raise RuntimeError(f"{label} bounds are invalid")
    return {"min": minimum, "max": maximum}


def normalize_expected_media_contract(value: Any) -> Dict[str, Any]:
    mapping = _require_mapping(value, "expectedMedia")
    allowed_containers = mapping.get("allowedContainers")
    if isinstance(allowed_containers, str):
        allowed_containers = [allowed_containers]
    if not isinstance(allowed_containers, Sequence) or not allowed_containers:
        raise RuntimeError("expectedMedia.allowedContainers must declare at least one container")
    normalized_containers = [str(item).strip().lower() for item in allowed_containers if str(item).strip()]
    if not normalized_containers:
        raise RuntimeError("expectedMedia.allowedContainers must declare at least one container")

    allowed_codecs = mapping.get("allowedVideoCodecs")
    normalized_codecs: List[str] = []
    if allowed_codecs is not None:
        if isinstance(allowed_codecs, str):
            allowed_codecs = [allowed_codecs]
        if not isinstance(allowed_codecs, Sequence):
            raise RuntimeError("expectedMedia.allowedVideoCodecs must be a list when present")
        normalized_codecs = [str(item).strip().lower() for item in allowed_codecs if str(item).strip()]
        if not normalized_codecs:
            raise RuntimeError("expectedMedia.allowedVideoCodecs must not be empty when present")

    return {
        "allowedContainers": normalized_containers,
        "allowedVideoCodecs": normalized_codecs,
        "width": int(mapping.get("width") or 0),
        "height": int(mapping.get("height") or 0),
        "frameRate": _normalize_rational(mapping.get("frameRate"), "expectedMedia.frameRate"),
        "fieldOrder": str(mapping.get("fieldOrder") or "").strip(),
        "pixelFormat": str(mapping.get("pixelFormat") or "").strip(),
        "bitDepth": int(mapping.get("bitDepth") or 0),
        "chromaSubsampling": str(mapping.get("chromaSubsampling") or "").strip(),
        "colorPrimaries": str(mapping.get("colorPrimaries") or "").strip(),
        "colorTransfer": str(mapping.get("colorTransfer") or "").strip(),
        "colorMatrix": str(mapping.get("colorMatrix") or "").strip(),
        "colorRange": str(mapping.get("colorRange") or "").strip(),
        "hdrMetadata": mapping.get("hdrMetadata"),
        "frameCount": _normalize_range_int(mapping.get("frameCount"), "expectedMedia.frameCount"),
        "duration": _normalize_range_rational(mapping.get("duration"), "expectedMedia.duration"),
    }


def _fraction_value(value: Mapping[str, int]) -> Fraction:
    return Fraction(int(value["numerator"]), int(value["denominator"]))


def validate_expected_media_match(review_clip: Mapping[str, Any], expected: Mapping[str, Any], probed: Mapping[str, Any]) -> None:
    clip_id = str(review_clip.get("id") or "<unknown>")
    allowed_containers = [str(item).strip().lower() for item in expected.get("allowedContainers") or []]
    actual_container = str(probed.get("container") or "").strip().lower()
    if not any(suite._container_matches(container, actual_container) for container in allowed_containers):
        raise RuntimeError(f"clip {clip_id} container {actual_container or '<none>'} is outside the reviewed allowedContainers contract")
    allowed_codecs = [str(item).strip().lower() for item in expected.get("allowedVideoCodecs") or []]
    actual_codec = str(probed.get("videoCodec") or "").strip().lower()
    if allowed_codecs and actual_codec not in allowed_codecs:
        raise RuntimeError(f"clip {clip_id} codec {actual_codec or '<none>'} is outside the reviewed allowedVideoCodecs contract")
    for field_name in (
        "width",
        "height",
        "fieldOrder",
        "pixelFormat",
        "bitDepth",
        "chromaSubsampling",
        "colorPrimaries",
        "colorTransfer",
        "colorMatrix",
        "colorRange",
    ):
        if expected.get(field_name) != probed.get(field_name):
            raise RuntimeError(f"clip {clip_id} {field_name} mismatch: expected {expected.get(field_name)}, got {probed.get(field_name)}")
    if expected.get("frameRate") != probed.get("frameRate"):
        raise RuntimeError(f"clip {clip_id} frameRate mismatch: expected {expected.get('frameRate')}, got {probed.get('frameRate')}")
    frame_bounds = _require_mapping(expected.get("frameCount"), "expectedMedia.frameCount")
    actual_frame_count = int(probed.get("frameCount") or 0)
    if not (int(frame_bounds["min"]) <= actual_frame_count <= int(frame_bounds["max"])):
        raise RuntimeError(
            f"clip {clip_id} frameCount {actual_frame_count} is outside the reviewed bounds "
            f"{frame_bounds['min']}..{frame_bounds['max']}"
        )
    duration_bounds = _require_mapping(expected.get("duration"), "expectedMedia.duration")
    actual_duration = _fraction_value(_require_mapping(probed.get("duration"), "probed duration"))
    minimum_duration = _fraction_value(_require_mapping(duration_bounds.get("min"), "expectedMedia.duration.min"))
    maximum_duration = _fraction_value(_require_mapping(duration_bounds.get("max"), "expectedMedia.duration.max"))
    if actual_duration < minimum_duration or actual_duration > maximum_duration:
        raise RuntimeError(
            f"clip {clip_id} duration {actual_duration.numerator}/{actual_duration.denominator} "
            f"is outside the reviewed bounds "
            f"{minimum_duration.numerator}/{minimum_duration.denominator}..{maximum_duration.numerator}/{maximum_duration.denominator}"
        )
    if expected.get("hdrMetadata") != probed.get("hdrMetadata"):
        raise RuntimeError(f"clip {clip_id} hdrMetadata mismatch: expected {expected.get('hdrMetadata')}, got {probed.get('hdrMetadata')}")


def canonical_review_metadata(review: Mapping[str, Any]) -> Dict[str, Any]:
    suite_review = _require_mapping(review.get("suiteReview"), "suiteReview")
    raw_clips = review.get("clips")
    if not isinstance(raw_clips, list):
        raise RuntimeError("review file is missing clips[]")
    normalized_clips = []
    for clip in raw_clips:
        clip_mapping = _require_mapping(clip, "clip")
        source = _require_mapping(clip_mapping.get("source"), f"clip {clip_mapping.get('id')} source")
        normalized_clips.append(
            {
                "id": str(clip_mapping.get("id") or "").strip(),
                "fileName": str(clip_mapping.get("fileName") or "").strip(),
                "displayName": str(clip_mapping.get("displayName") or "").strip(),
                "contentClass": str(clip_mapping.get("contentClass") or "").strip(),
                "payloadContentClass": str(clip_mapping.get("payloadContentClass") or "").strip(),
                "description": str(clip_mapping.get("description") or "").strip(),
                "source": {
                    "kind": str(source.get("kind") or "").strip(),
                    "provenance": str(source.get("provenance") or "").strip(),
                    "license": str(source.get("license") or "").strip(),
                    "reviewed": bool(source.get("reviewed")),
                    "redistributionApproved": bool(source.get("redistributionApproved")),
                },
                "expectedMedia": normalize_expected_media_contract(clip_mapping.get("expectedMedia")),
            }
        )
    normalized_clips.sort(key=lambda item: item["id"])
    return {
        "schemaVersion": int(review.get("schemaVersion") or 1),
        "suiteId": str(review.get("suiteId") or "").strip(),
        "suiteVersion": str(review.get("suiteVersion") or "").strip(),
        "displayName": str(review.get("displayName") or "").strip(),
        "defaultQuickClipId": str(review.get("defaultQuickClipId") or "").strip(),
        "suiteReview": {
            "reviewed": bool(suite_review.get("reviewed")),
            "reviewer": str(suite_review.get("reviewer") or "").strip(),
            "redistributionApproved": bool(suite_review.get("redistributionApproved")),
            "distributionLicense": str(suite_review.get("distributionLicense") or "").strip(),
            "notes": str(suite_review.get("notes") or "").strip(),
        },
        "clips": normalized_clips,
    }


def build_review_hash(review: Mapping[str, Any]) -> str:
    return sha256_text(canonical_json(canonical_review_metadata(review)))


def build_clip_entry(
    review_clip: Mapping[str, Any],
    review_hash: str,
    source_path: Path,
) -> Dict[str, Any]:
    source = review_clip.get("source")
    if not isinstance(source, Mapping):
        raise RuntimeError(f"clip {review_clip.get('id')} is missing source metadata")
    ensure_true(source.get("reviewed"), f"clip {review_clip.get('id')} source metadata is not reviewed")
    ensure_true(source.get("redistributionApproved"), f"clip {review_clip.get('id')} redistribution is not approved")

    if not source_path.exists():
        raise RuntimeError(f"clip {review_clip.get('id')} source file does not exist: {source_path}")

    media = probe_media_contract(source_path)
    expected_media = normalize_expected_media_contract(review_clip.get("expectedMedia"))
    validate_expected_media_match(review_clip, expected_media, media)
    if media["frameCount"] <= 0:
        raise RuntimeError(f"clip {review_clip.get('id')} has no decoded frames")
    if not media["pixelFormat"] or not media["colorPrimaries"] or not media["fieldOrder"]:
        raise RuntimeError(f"clip {review_clip.get('id')} ffprobe contract is incomplete")

    file_name = str(review_clip.get("fileName") or source_path.name).strip()
    if (
        not file_name
        or Path(file_name).is_absolute()
        or Path(file_name).name != file_name
        or file_name in {".", ".."}
        or "/" in file_name
        or "\\" in file_name
    ):
        raise RuntimeError(f"clip {review_clip.get('id')} fileName must be one safe basename")
    return {
        "id": str(review_clip["id"]),
        "displayName": str(review_clip.get("displayName") or "").strip(),
        "contentClass": str(review_clip.get("contentClass") or "").strip(),
        "payloadContentClass": str(review_clip.get("payloadContentClass") or "").strip(),
        "description": str(review_clip.get("description") or "").strip(),
        "fileName": file_name,
        "source": {
            "kind": str(source.get("kind") or "").strip(),
            "provenance": str(source.get("provenance") or "").strip(),
            "license": str(source.get("license") or "").strip(),
            "reviewed": True,
            "redistributionApproved": True,
            "reviewHash": review_hash,
        },
        "acquisition": {
            "kind": "retained-original",
            "container": suite._normalize_container_alias(str(media.get("container") or source_path.suffix.lstrip(".").lower() or "unknown")),
            "videoCodec": str(media.get("videoCodec") or "").strip().lower() or "retained-reference",
            "packagedRelativePath": f"canonical/{file_name}",
            "originalFileName": source_path.name,
        },
        "media": {key: value for key, value in media.items() if key not in {"container", "videoCodec"}},
        "sha256": sha256_path(source_path),
        "byteSize": source_path.stat().st_size,
    }


def validate_review(review: Mapping[str, Any]) -> None:
    ensure_true(review.get("suiteReview", {}).get("reviewed"), "suite review is not marked reviewed")
    ensure_true(
        review.get("suiteReview", {}).get("redistributionApproved"),
        "suite redistribution approval is not marked reviewed",
    )
    review_hash = str(review.get("suiteReview", {}).get("reviewHash") or "").strip().lower()
    if not review_hash or not re_fullmatch_hex(review_hash):
        raise RuntimeError("suite reviewHash must be a 64-character SHA-256 hex string")
    expected_hash = build_review_hash(review)
    if review_hash != expected_hash:
        raise RuntimeError(f"suite reviewHash does not match the reviewed metadata SHA-256 (expected {expected_hash}, got {review_hash})")
    distribution_license = str(review.get("suiteReview", {}).get("distributionLicense") or "").strip()
    if not distribution_license:
        raise RuntimeError("suite distributionLicense is required")


def re_fullmatch_hex(value: str) -> bool:
    return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value.lower())


def build_suite_payload(
    review: Mapping[str, Any],
    manifest_version: int,
    source_paths: Mapping[str, Path],
) -> Dict[str, Any]:
    validate_review(review)
    review_hash = str(review["suiteReview"]["reviewHash"]).strip().lower()
    raw_clips = review.get("clips")
    if not isinstance(raw_clips, list):
        raise RuntimeError("review file is missing clips[]")
    if len(raw_clips) != len(suite.REQUIRED_CONTENT_CLASSES):
        raise RuntimeError(f"review file must declare exactly {len(suite.REQUIRED_CONTENT_CLASSES)} clips")
    built_clips = [
        build_clip_entry(clip, review_hash, source_paths[str(clip["id"])])
        for clip in raw_clips
    ]

    ids = {clip["id"] for clip in built_clips}
    classes = [clip["contentClass"] for clip in built_clips]
    if len(ids) != len(built_clips):
        raise RuntimeError("review file contains duplicate clip ids")
    if set(classes) != set(suite.REQUIRED_CONTENT_CLASSES):
        raise RuntimeError("review file content classes do not match the required seven-class contract")
    for clip in built_clips:
        if not clip["displayName"] or not clip["payloadContentClass"] or not clip["description"]:
            raise RuntimeError(f"clip {clip['id']} is missing reviewed metadata")
        if not clip["source"]["kind"] or not clip["source"]["provenance"] or not clip["source"]["license"]:
            raise RuntimeError(f"clip {clip['id']} is missing reviewed provenance/license metadata")

    return {
        "suiteId": "encodingdb-test-suite",
        "suiteVersion": str(review.get("suiteVersion") or suite.SUITE_VERSION),
        "displayName": str(review.get("displayName") or "EncodingDB Test Suite v1").strip(),
        "manifestVersion": int(manifest_version),
        "defaultQuickClipId": str(review.get("defaultQuickClipId") or suite.DEFAULT_QUICK_CLIP_ID),
        "requiredContentClasses": list(suite.REQUIRED_CONTENT_CLASSES),
        "generalPlPolicy": {
            "requiresCompleteCoverage": True,
            "weighting": "equal-class-geometric-mean",
            "legacySingleClipGeneralPlAllowed": False,
        },
        "redistribution": {
            "license": str(review["suiteReview"].get("distributionLicense") or "").strip(),
            "notes": str(review["suiteReview"].get("notes") or "Reviewed final suite metadata; redistribution approved by operator.").strip(),
            "reviewed": True,
            "redistributionApproved": True,
            "reviewHash": review_hash,
            "spdxExpression": str(review["suiteReview"].get("distributionLicense") or "").strip(),
        },
        "clips": built_clips,
    }


def build_lock_payload(manifest_payload: Mapping[str, Any], review_hash: str) -> Dict[str, Any]:
    unsigned = {
        "schemaVersion": LOCK_SCHEMA_VERSION,
        "suiteId": manifest_payload["suiteId"],
        "suiteVersion": manifest_payload["suiteVersion"],
        "manifestSha256": sha256_text(canonical_json(manifest_payload)),
        "reviewHash": review_hash,
        "reviewedMetadataSha256": review_hash,
        "clips": [
            {
                "id": clip["id"],
                "sha256": clip["sha256"],
                "byteSize": clip["byteSize"],
                "container": clip["acquisition"]["container"],
                "videoCodec": clip["acquisition"]["videoCodec"],
                "frameCount": clip["media"]["frameCount"],
                "frameRate": clip["media"]["frameRate"],
                "fieldOrder": clip["media"]["fieldOrder"],
                "hdrMetadata": clip["media"]["hdrMetadata"],
            }
            for clip in manifest_payload["clips"]
        ],
    }
    unsigned["fingerprint"] = sha256_text(canonical_json(unsigned))
    return unsigned


def build_status_payload(lock_name: str, suite_version: str) -> Dict[str, Any]:
    return {
        "schemaVersion": STATUS_SCHEMA_VERSION,
        "suiteId": "encodingdb-test-suite",
        "suiteVersion": suite_version,
        "distribution": "reviewed-final",
        "isFrozen": True,
        "finalLockPath": lock_name,
        "reason": "Final suite lock exists and was produced from reviewed provenance/license metadata.",
    }


def source_clip_paths(
    review: Mapping[str, Any],
    review_base_dir: Path,
    source_dir: Optional[Path] = None,
) -> Dict[str, Path]:
    raw_clips = review.get("clips")
    if not isinstance(raw_clips, list):
        raise RuntimeError("review file is missing clips[]")
    resolved: Dict[str, Path] = {}
    for clip in raw_clips:
        clip_id = str(clip.get("id") or "").strip()
        if not clip_id:
            raise RuntimeError("review clip is missing id")
        local_path = str(clip.get("localPath") or "").strip()
        if local_path:
            resolved_path = normalize_clip_path(review_base_dir, local_path)
        else:
            if source_dir is None:
                raise RuntimeError(f"clip {clip_id} is missing localPath and no --source-dir was provided")
            file_name = str(clip.get("fileName") or "").strip()
            if not file_name:
                raise RuntimeError(f"clip {clip_id} is missing fileName")
            resolved_path = (source_dir / file_name).resolve()
        resolved[clip_id] = resolved_path
    if len(resolved) != len(suite.REQUIRED_CONTENT_CLASSES):
        raise RuntimeError(f"expected exactly {len(suite.REQUIRED_CONTENT_CLASSES)} reviewed files")
    return resolved


def stage_outputs(
    *,
    staging_root: Path,
    manifest_payload: Mapping[str, Any],
    lock_payload: Mapping[str, Any],
    status_payload: Mapping[str, Any],
    pack_manifest_payload: Mapping[str, Any],
    client_manifest_out: Path,
    server_manifest_out: Path,
    client_lock_out: Path,
    server_lock_out: Path,
    client_status_out: Path,
    server_status_out: Path,
    client_pack_manifest_out: Path,
    server_pack_manifest_out: Path,
    source_paths: Mapping[str, Path],
) -> List[Tuple[Path, Path]]:
    replacements: List[Tuple[Path, Path]] = []
    for label, final_path, payload in (
        ("client-manifest", client_manifest_out, manifest_payload),
        ("server-manifest", server_manifest_out, manifest_payload),
        ("client-lock", client_lock_out, lock_payload),
        ("server-lock", server_lock_out, lock_payload),
        ("client-status", client_status_out, status_payload),
        ("server-status", server_status_out, status_payload),
        ("client-pack-manifest", client_pack_manifest_out, pack_manifest_payload),
        ("server-pack-manifest", server_pack_manifest_out, pack_manifest_payload),
    ):
        staged_path = staging_root / label / final_path.name
        write_json_file(staged_path, payload)
        replacements.append((staged_path, final_path))

    for tree_label, manifest_out in (("client", client_manifest_out), ("server", server_manifest_out)):
        canonical_dir = manifest_out.parent / "canonical"
        for clip in manifest_payload["clips"]:
            source_path = source_paths[str(clip["id"])]
            staged_path = staging_root / tree_label / "canonical" / str(clip["fileName"])
            staged_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, staged_path)
            replacements.append((staged_path, canonical_dir / str(clip["fileName"])))
    return replacements


def verify_staged_suite(manifest_payload: Mapping[str, Any], staged_manifest_path: Path, staged_canonical_dir: Path, staged_suite_root: Path) -> None:
    manifest = suite.manifest_from_payload(manifest_payload)
    for clip in manifest.clips:
        result = suite.verify_suite_clip(str(staged_canonical_dir / clip.file_name), clip)
        if not result.ok:
            raise RuntimeError(f"staged suite verification failed for {clip.clip_id}: {result.message}")
    if not staged_manifest_path.exists():
        raise RuntimeError("staged manifest was not written")
    suite.verify_suite_pack_metadata(str(staged_suite_root), suite.load_suite_pack_metadata(str(staged_suite_root / "suite-pack.json")))


def commit_replacements(replacements: Sequence[Tuple[Path, Path]]) -> None:
    backups: List[Tuple[Optional[Path], Path]] = []
    with tempfile.TemporaryDirectory(prefix="encodingdb-suite-commit-") as backup_root:
        backup_root_path = Path(backup_root)
        try:
            for index, (staged_path, final_path) in enumerate(replacements):
                final_path.parent.mkdir(parents=True, exist_ok=True)
                backup_path = backup_root_path / f"{index}"
                if final_path.exists():
                    shutil.copy2(final_path, backup_path)
                    backups.append((backup_path, final_path))
                else:
                    backups.append((None, final_path))
                os.replace(staged_path, final_path)
        except Exception:
            for backup_path, final_path in reversed(backups):
                if backup_path is None:
                    try:
                        if final_path.exists():
                            final_path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                if backup_path.exists():
                    shutil.copy2(backup_path, final_path)
            raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freeze a reviewed EncodingDB Test Suite v1 manifest without transcoding originals.")
    parser.add_argument("--review-json", required=True)
    parser.add_argument("--source-dir", default=None, help="Directory containing the reviewed seven-file source set. Used when clips omit localPath.")
    parser.add_argument("--client-manifest-out", default=str(default_output_paths()["client_manifest_out"]))
    parser.add_argument("--server-manifest-out", default=str(default_output_paths()["server_manifest_out"]))
    parser.add_argument("--client-lock-out", default=str(default_output_paths()["client_lock_out"]))
    parser.add_argument("--server-lock-out", default=str(default_output_paths()["server_lock_out"]))
    parser.add_argument("--client-status-out", default=str(default_output_paths()["client_status_out"]))
    parser.add_argument("--server-status-out", default=str(default_output_paths()["server_status_out"]))
    parser.add_argument("--client-pack-manifest-out", default=str(default_output_paths()["client_pack_manifest_out"]))
    parser.add_argument("--server-pack-manifest-out", default=str(default_output_paths()["server_pack_manifest_out"]))
    parser.add_argument("--manifest-version", type=int, default=1)
    parser.add_argument("--print-review-hash", action="store_true", help="Print the deterministic review metadata SHA-256 and exit.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    review_path = Path(args.review_json).resolve()
    review = load_review(review_path)
    if args.print_review_hash:
        print(build_review_hash(review))
        return 0
    source_dir = Path(args.source_dir).resolve() if args.source_dir else None
    source_paths = source_clip_paths(review, review_path.parent, source_dir)
    manifest_payload = build_suite_payload(review, int(args.manifest_version), source_paths)
    review_hash = str(review["suiteReview"]["reviewHash"]).strip().lower()
    lock_payload = build_lock_payload(manifest_payload, review_hash)
    status_payload = build_status_payload(Path(args.client_lock_out).name, str(manifest_payload["suiteVersion"]))
    client_manifest_out = Path(args.client_manifest_out).resolve()
    server_manifest_out = Path(args.server_manifest_out).resolve()
    client_lock_out = Path(args.client_lock_out).resolve()
    server_lock_out = Path(args.server_lock_out).resolve()
    client_status_out = Path(args.client_status_out).resolve()
    server_status_out = Path(args.server_status_out).resolve()
    client_pack_manifest_out = Path(args.client_pack_manifest_out).resolve()
    server_pack_manifest_out = Path(args.server_pack_manifest_out).resolve()

    with tempfile.TemporaryDirectory(prefix="encodingdb-suite-stage-") as staging_root:
        staging_root_path = Path(staging_root)
        for tree_label in ("client", "server"):
            suite_root = staging_root_path / tree_label
            suite_root.mkdir(parents=True, exist_ok=True)
            write_json_file(suite_root / "manifest.json", manifest_payload)
            write_json_file(suite_root / "finalization-status.json", status_payload)
            write_json_file(suite_root / "suite-lock.json", lock_payload)
        for tree_label in ("client", "server"):
            canonical_dir = staging_root_path / tree_label / "canonical"
            canonical_dir.mkdir(parents=True, exist_ok=True)
            for clip in manifest_payload["clips"]:
                source_path = source_paths[str(clip["id"])]
                shutil.copy2(source_path, canonical_dir / str(clip["fileName"]))
            suite.write_suite_pack_metadata(str(staging_root_path / tree_label))
        with open(staging_root_path / "client" / "suite-pack.json", "r", encoding="utf-8") as handle:
            pack_manifest_payload = json.load(handle)
        replacements = stage_outputs(
            staging_root=staging_root_path,
            manifest_payload=manifest_payload,
            lock_payload=lock_payload,
            status_payload=status_payload,
            pack_manifest_payload=pack_manifest_payload,
            client_manifest_out=client_manifest_out,
            server_manifest_out=server_manifest_out,
            client_lock_out=client_lock_out,
            server_lock_out=server_lock_out,
            client_status_out=client_status_out,
            server_status_out=server_status_out,
            client_pack_manifest_out=client_pack_manifest_out,
            server_pack_manifest_out=server_pack_manifest_out,
            source_paths=source_paths,
        )
        verify_staged_suite(
            manifest_payload,
            staging_root_path / "client-manifest" / client_manifest_out.name,
            staging_root_path / "client" / "canonical",
            staging_root_path / "client",
        )
        verify_staged_suite(
            manifest_payload,
            staging_root_path / "server-manifest" / server_manifest_out.name,
            staging_root_path / "server" / "canonical",
            staging_root_path / "server",
        )
        commit_replacements(replacements)
    print(f"frozen suite fingerprint: {lock_payload['fingerprint']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
