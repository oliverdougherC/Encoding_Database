#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from client import config, runtime_lock, suite  # noqa: E402

RELEASE_MANIFEST_SCHEMA_VERSION = 1
SMOKE_SCHEMA_VERSION = 1
SIGNING_SCHEMA_VERSION = 1
SHA256SUMS_NAME = "SHA256SUMS"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")
        temp_name = handle.name
    os.replace(temp_name, path)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def detect_project_version() -> str:
    override = os.environ.get("ENCODINGDB_PROJECT_VERSION", "").strip()
    if override:
        return override
    payload = json.loads(read_text(ROOT_DIR / "release.json"))
    version = payload.get("projectVersion")
    if not isinstance(version, str) or not version.strip():
        raise RuntimeError(
            "Project release version is unassigned; set projectVersion in release.json "
            "or ENCODINGDB_PROJECT_VERSION before building final clients"
        )
    return version.strip()


def read_client_minimum_version() -> str:
    client_match = re.search(r'CLIENT_VERSION\s*=\s*"([^"]+)"', read_text(ROOT_DIR / "client" / "main.py"))
    server_match = re.search(
        r"SERVER_CANONICAL_MINIMUM_CLIENT_VERSION\s*=\s*'([^']+)'",
        read_text(ROOT_DIR / "server" / "src" / "v7" / "artifacts.ts"),
    )
    if not client_match or not server_match:
        raise RuntimeError("Unable to read client minimum version contract")
    if client_match.group(1) != server_match.group(1):
        raise RuntimeError(
            f"client minimum version mismatch: client={client_match.group(1)} server={server_match.group(1)}"
        )
    return client_match.group(1)


def load_vmaf_manifest() -> Dict[str, Any]:
    with (ROOT_DIR / "client" / "resources" / "vmaf" / "manifest.json").open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError("VMAF manifest is invalid")
    return payload


def release_sidecar_paths(artifact_path: Path, output_dir: Path) -> Dict[str, Path]:
    base = artifact_path.name
    return {
        "runtime_lock": output_dir / f"{base}.runtime-lock.json",
        "release_manifest": output_dir / f"{base}.release-manifest.json",
        "signing": output_dir / f"{base}.signing.json",
        "smoke": output_dir / f"{base}.smoke.json",
        "sha256sums": output_dir / f"{base}.SHA256SUMS",
    }


def select_smoke_encoder(capabilities: Mapping[str, Any]) -> str:
    available = [str(value) for value in capabilities.get("encoders") or [] if str(value).strip()]
    for preferred in ("libx264", "libx265", "libaom-av1", "libvpx-vp9", "libopenh264"):
        if preferred in available:
            return preferred
    if not available:
        raise RuntimeError("runtime lock does not declare any smoke-testable encoders")
    return available[0]


def run_smoke_check(
    *,
    artifact_path: Path,
    smoke_encoder: str,
    queue_dir: Path,
    suite_cache_dir: Path,
) -> Dict[str, Any]:
    base_env = dict(os.environ)
    base_env.update(
        {
            "BACKEND_BASE_URL": "http://127.0.0.1:9",
            "QUEUE_DIR": str(queue_dir),
            "ENCODINGDB_SUITE_CACHE_DIR": str(suite_cache_dir),
        }
    )
    queue_dir.mkdir(parents=True, exist_ok=True)
    suite_cache_dir.mkdir(parents=True, exist_ok=True)
    commands: List[Dict[str, Any]] = []
    smoke_specs: Sequence[Sequence[str]] = (
        (str(artifact_path), "--help"),
        (
            str(artifact_path),
            "--codec",
            smoke_encoder,
            "--presets",
            "fast",
            "--crf",
            "24",
            "--no-submit",
        ),
    )
    for index, command in enumerate(smoke_specs):
        proc = subprocess.run(
            list(command),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=base_env,
            timeout=300,
        )
        commands.append(
            {
                "name": "help" if index == 0 else "no-submit-suite",
                "argv": [os.path.basename(part) if part == str(artifact_path) else part for part in command],
                "returnCode": proc.returncode,
            }
        )
        if proc.returncode != 0:
            raise RuntimeError(f"packaged smoke check failed for {' '.join(command)}")
    return {
        "schemaVersion": SMOKE_SCHEMA_VERSION,
        "submissionMode": "no-submit",
        "commands": commands,
    }


def build_signing_payload(signing_status: str, signing_evidence_path: Optional[Path]) -> Dict[str, Any]:
    normalized = str(signing_status or "unsigned").strip().lower()
    payload: Dict[str, Any] = {
        "schemaVersion": SIGNING_SCHEMA_VERSION,
        "status": normalized,
        "evidence": None,
        "note": "Build is unsigned; no signing evidence was supplied." if normalized == "unsigned" else None,
    }
    if signing_evidence_path:
        payload["evidence"] = {
            "fileName": signing_evidence_path.name,
            "sha256": sha256_path(signing_evidence_path),
            "byteSize": signing_evidence_path.stat().st_size,
        }
        if normalized == "unsigned":
            payload["note"] = "Signing evidence file was supplied but signing status remained unsigned."
    return payload


def build_release_manifest(
    *,
    artifact_path: Path,
    platform: str,
    runtime_lock_payload: Mapping[str, Any],
    signing_payload: Mapping[str, Any],
) -> Dict[str, Any]:
    suite_manifest = suite.load_default_suite_manifest()
    finalization_status = suite.load_finalization_status()
    vmaf_manifest = load_vmaf_manifest()
    runtime_fingerprint = hashlib.sha256(canonical_json(runtime_lock_payload).encode("utf-8")).hexdigest()
    artifact_sha = sha256_path(artifact_path)
    return {
        "schemaVersion": RELEASE_MANIFEST_SCHEMA_VERSION,
        "projectVersion": detect_project_version(),
        "platform": str(platform).strip().lower(),
        "artifact": {
            "fileName": artifact_path.name,
            "sha256": artifact_sha,
            "byteSize": artifact_path.stat().st_size,
            "mode": stat.S_IMODE(artifact_path.stat().st_mode),
        },
        "protocol": {
            "benchmarkProtocolVersion": config.BENCHMARK_PROTOCOL_VERSION,
            "minimumClientVersion": read_client_minimum_version(),
        },
        "suite": {
            "suiteId": "encodingdb-test-suite",
            "suiteVersion": suite_manifest.suite_version,
            "manifestVersion": suite_manifest.manifest_version,
            "distribution": str(finalization_status.get("distribution") or "unknown"),
            "isFrozen": bool(finalization_status.get("isFrozen")),
            "finalLockPath": finalization_status.get("finalLockPath"),
        },
        "qualityModel": {
            "metricModelId": vmaf_manifest.get("metricModelId"),
            "metricModelVersion": vmaf_manifest.get("metricModelVersion"),
            "sha256": vmaf_manifest.get("sha256"),
            "bundleRelativePath": vmaf_manifest.get("bundleRelativePath"),
        },
        "runtime": {
            "fingerprint": runtime_fingerprint,
            "payload": runtime_lock_payload,
            "checkedInLockPath": str((ROOT_DIR / "client" / "resources" / "runtime" / "ffmpeg-lock.json").resolve()),
        },
        "signing": signing_payload,
    }


def write_sha256sums(sha256_path_out: Path, files: Iterable[Path]) -> None:
    lines = []
    for path in sorted(files, key=lambda value: value.name):
        if path.name == sha256_path_out.name:
            continue
        lines.append(f"{sha256_path(path)}  {path.name}")
    sha256_path_out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def finalize_release(
    *,
    artifact_path: Path,
    platform: str,
    ffmpeg_path: Path,
    ffprobe_path: Path,
    output_dir: Path,
    signing_status: str,
    signing_evidence_path: Optional[Path],
    skip_smoke: bool = False,
) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    sidecars = release_sidecar_paths(artifact_path, output_dir)
    verified_runtime = runtime_lock.verify_runtime_lock(
        platform_key=platform,
        ffmpeg_path=str(ffmpeg_path),
        ffprobe_path=str(ffprobe_path),
    )
    runtime_lock_payload = runtime_lock.filtered_runtime_lock_payload(verified_runtime["payload"], str(platform).strip().lower())
    signing_payload = build_signing_payload(signing_status, signing_evidence_path)
    if skip_smoke:
        smoke_payload = {
            "schemaVersion": SMOKE_SCHEMA_VERSION,
            "submissionMode": "not-run",
            "commands": [],
            "reason": "Smoke checks were intentionally skipped for this artifact.",
        }
    else:
        with tempfile.TemporaryDirectory(prefix=f"{artifact_path.name}-smoke-") as smoke_root:
            smoke_root_path = Path(smoke_root)
            smoke_payload = run_smoke_check(
                artifact_path=artifact_path,
                smoke_encoder=select_smoke_encoder(runtime_lock_payload["platforms"][str(platform).strip().lower()]["capabilities"]),
                queue_dir=smoke_root_path / "queue",
                suite_cache_dir=smoke_root_path / "suite-cache",
            )
    manifest_payload = build_release_manifest(
        artifact_path=artifact_path,
        platform=platform,
        runtime_lock_payload=runtime_lock_payload,
        signing_payload=signing_payload,
    )
    atomic_write_json(sidecars["runtime_lock"], runtime_lock_payload)
    atomic_write_json(sidecars["signing"], signing_payload)
    atomic_write_json(sidecars["smoke"], smoke_payload)
    atomic_write_json(sidecars["release_manifest"], manifest_payload)
    write_sha256sums(
        sidecars["sha256sums"],
        [
            artifact_path,
            sidecars["runtime_lock"],
            sidecars["signing"],
            sidecars["smoke"],
            sidecars["release_manifest"],
            *( [signing_evidence_path] if signing_evidence_path else [] ),
        ],
    )
    return sidecars


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write deterministic client release sidecars and smoke evidence.")
    parser.add_argument("--artifact-path", required=True)
    parser.add_argument("--platform", required=True, choices=("linux", "mac", "win"))
    parser.add_argument("--ffmpeg-path", required=True)
    parser.add_argument("--ffprobe-path", required=True)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--signing-status", default="unsigned")
    parser.add_argument("--signing-evidence-path", default=None)
    parser.add_argument("--skip-smoke", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact_path = Path(args.artifact_path).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else artifact_path.parent
    sidecars = finalize_release(
        artifact_path=artifact_path,
        platform=str(args.platform),
        ffmpeg_path=Path(args.ffmpeg_path).resolve(),
        ffprobe_path=Path(args.ffprobe_path).resolve(),
        output_dir=output_dir,
        signing_status=str(args.signing_status),
        signing_evidence_path=Path(args.signing_evidence_path).resolve() if args.signing_evidence_path else None,
        skip_smoke=bool(args.skip_smoke),
    )
    for label, path in sidecars.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
