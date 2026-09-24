#!/usr/bin/env python3
"""Verify one candidate's native assets and write a shared release manifest.

The JSON input declares ``expectedSourceRevision`` and ``expectedProjectVersion``
and has an ``assets`` array with one entry per role: ``macos-dmg``,
``windows-gui``, ``windows-console`` and ``linux-archive``. Each entry names
``artifact`` and ``releaseManifest`` paths, plus ``packageInfo`` for macOS
and Linux wrappers. Relative paths resolve beside the spec file. Use native
build receipts from one clean committed revision. This gate does not publish
assets or replace the physical G01 acceptance runs.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.release_manifest_lib import atomic_write_json, sha256_path

ROLES = {"macos-dmg", "windows-gui", "windows-console", "linux-archive"}


def _path(base: Path, value: Any) -> Path:
    path = Path(str(value or ""))
    if not str(value or "").strip():
        raise ValueError("asset path is missing")
    return path if path.is_absolute() else base / path


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return payload


def _check_file(path: Path, identity: dict[str, Any]) -> str:
    if path.name != identity.get("fileName"):
        raise ValueError(f"file name differs from native receipt: {path.name}")
    if path.stat().st_size != identity.get("byteSize"):
        raise ValueError(f"file bytes differ from native receipt: {path.name}")
    observed_sha = sha256_path(path)
    if observed_sha != identity.get("sha256"):
        raise ValueError(f"file bytes differ from native receipt: {path.name}")
    return observed_sha


def _source_revision(receipt: dict[str, Any]) -> str:
    source = receipt.get("source") or {}
    revision = source.get("revision")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision) or source.get("trackedChanges") is not False:
        raise ValueError("native receipt must identify a clean committed source revision")
    return revision


def assemble(spec: dict[str, Any], base: Path) -> dict[str, Any]:
    expected_revision = spec.get("expectedSourceRevision")
    expected_version = spec.get("expectedProjectVersion")
    if not isinstance(expected_revision, str) or not re.fullmatch(r"[0-9a-f]{40}", expected_revision):
        raise ValueError("spec must name the reviewed source revision")
    if not isinstance(expected_version, str) or not expected_version.strip():
        raise ValueError("spec must name the candidate project version")
    entries = spec.get("assets")
    if not isinstance(entries, list) or len(entries) != len(ROLES):
        raise ValueError("spec must contain one entry for each native release role")
    assets = []
    common: dict[str, Any] | None = None
    roles_seen: set[str] = set()
    runtimes: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("each asset entry must be an object")
        role = entry.get("role")
        if not isinstance(role, str) or role not in ROLES or role in roles_seen:
            raise ValueError(f"unexpected or repeated native release role: {role}")
        roles_seen.add(role)
        artifact = _path(base, entry.get("artifact"))
        receipt = _read_json(_path(base, entry.get("releaseManifest")))
        if receipt.get("schemaVersion") != 1:
            raise ValueError(f"unsupported native manifest for {role}")
        protocol = receipt.get("protocol") or {}
        suite = receipt.get("suite") or {}
        runtime = receipt.get("runtime") or {}
        identity = {
            "sourceRevision": _source_revision(receipt),
            "projectVersion": receipt.get("projectVersion"),
            "clientVersion": protocol.get("clientVersion"),
            "protocolVersion": protocol.get("benchmarkProtocolVersion"),
            "minimumClientVersion": protocol.get("minimumClientVersion"),
            "suiteVersion": suite.get("suiteVersion"),
            "suiteManifestVersion": suite.get("manifestVersion"),
            "suiteFingerprint": suite.get("suiteFingerprint"),
        }
        if not all(identity.values()) or suite.get("isFrozen") is not True:
            raise ValueError(f"incomplete frozen client identity for {role}")
        if identity["sourceRevision"] != expected_revision or identity["projectVersion"] != expected_version:
            raise ValueError(f"{role} differs from the reviewed source/version in the spec")
        if common is None:
            common = identity
        elif identity != common:
            raise ValueError(f"{role} was built from a different client/protocol/suite identity")
        platform = {"macos-dmg": "mac", "linux-archive": "linux"}.get(role, "win")
        if receipt.get("platform") != platform or not isinstance(runtime.get("fingerprint"), str):
            raise ValueError(f"invalid {role} platform/runtime identity")
        if platform in runtimes and runtimes[platform] != runtime["fingerprint"]:
            raise ValueError(f"different {platform} runtime identities in one release")
        runtimes[platform] = runtime["fingerprint"]

        binary = receipt.get("artifact") or {}
        wrapper = None
        if role in {"macos-dmg", "linux-archive"}:
            package = _read_json(_path(base, entry.get("packageInfo")))
            if package.get("provisional") is not False or _source_revision(package) != identity["sourceRevision"]:
                raise ValueError(f"unverified package source for {role}")
            wrapper = package.get("dmg") if role == "macos-dmg" else package.get("archive")
            if not isinstance(wrapper, dict):
                raise ValueError(f"missing package identity for {role}")
            artifact_sha = _check_file(artifact, wrapper)
            if role == "macos-dmg":
                if package.get("cliEmbeddedSha256") != binary.get("sha256") or package.get("cliBytesChangedByPackaging") is not False:
                    raise ValueError("macOS DMG embeds a different client executable")
                mount = wrapper.get("readOnlyMountVerification") or {}
                if mount.get("mounted") is not True or mount.get("innerSha256") != binary.get("sha256"):
                    raise ValueError("macOS DMG lacks read-only mount verification")
            else:
                members = wrapper.get("members") or []
                if not any(isinstance(member, dict) and member.get("sha256") == binary.get("sha256") for member in members):
                    raise ValueError("Linux archive does not contain the audited client executable")
                if (package.get("verification") or {}).get("verified") is not True:
                    raise ValueError("Linux archive lacks launch-contract verification")
        else:
            artifact_sha = _check_file(artifact, binary)
        assets.append({
            "role": role, "fileName": artifact.name,
            "sha256": artifact_sha, "byteSize": artifact.stat().st_size,
            "embeddedExecutableSha256": binary.get("sha256"),
            "runtimeFingerprint": runtime["fingerprint"],
        })
    if roles_seen != ROLES or common is None:
        raise ValueError("native release roles are incomplete")
    return {"schemaVersion": 1, **common, "assets": sorted(assets, key=lambda item: item["role"])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True, help="JSON mapping each release role to artifact and native receipts")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    spec = _read_json(args.spec)
    atomic_write_json(args.output, assemble(spec, args.spec.parent))
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
