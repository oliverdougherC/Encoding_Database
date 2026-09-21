#!/usr/bin/env python3
"""Assemble EncodingDB.app and EncodingDB-macOS-<arch>.dmg around the packaged CLI.

The published macOS surface must be a recognizable double-clickable application,
never a raw extensionless binary. This helper wraps the PyInstaller onefile CLI
in an app bundle whose executable opens the guided terminal interface through
Terminal.app (real stdin/stdout, readable window), then packs that bundle into a
read-only DMG with honest signing/support metadata.

Provenance rules (packaging review 2026-09-21):
  • Audited CLI bytes are preserved whenever the inner Mach-O already carries a
    valid code signature; only the bundle wrapper is signed then.
  • When signing legitimately rewrites the inner binary, the sidecar records the
    source and final embedded digests separately — never one claimed as the other.
  • Signing verification fails closed: `codesign --verify --strict` must pass,
    and the final embedded identity is re-checked from a read-only DMG mount.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Sequence

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

PACKAGING_DIR = ROOT_DIR / "packaging" / "macos"
LAUNCHER_ASSET = PACKAGING_DIR / "launcher.sh"
COMMAND_ASSET = PACKAGING_DIR / "EncodingDB.command"
INSTALLER_README_ASSET = PACKAGING_DIR / "README-installer.txt"
REPO_FAVICON = ROOT_DIR / "frontend" / "app" / "favicon.ico"

APP_NAME = "EncodingDB"
BUNDLE_BINARY_NAME = "encodingdb"
DEFAULT_BUNDLE_ID = "com.encodingdb.client"
# Evidence for this floor lives in docs/NATIVE_RUNTIME_20260914.md and was
# re-confirmed against the load commands of the locked runtime bundle
# (libpcre2-8.0.dylib and libharfbuzz.0.dylib declare minos 27.0). The outer
# PyInstaller header alone says 11.0 and must not be mistaken for the package
# floor. Never lower this without new load-command evidence.
DOCUMENTED_MACOS_FLOOR = (27, 0)

ICONSET_SIZES = [16, 32, 64, 128, 256, 512]


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_version(text: str) -> tuple:
    parts = [int(part) for part in str(text).strip().split(".") if part != ""]
    while len(parts) < 2:
        parts.append(0)
    return tuple(parts)


def format_version(value: tuple) -> str:
    parts = [str(part) for part in value]
    while len(parts) > 2 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


def macho_minimum_os(path: Path) -> Optional[tuple]:
    """Return the minimum macOS version declared in a Mach-O header, if any."""
    try:
        with path.open("rb") as handle:
            header = handle.read(65536)
    except OSError:
        return None
    if header[:4] != b"\xcf\xfa\xed\xfe":
        return None
    ncmds = struct.unpack_from("<I", header, 16)[0]
    offset = 32
    for _ in range(ncmds):
        if offset + 8 > len(header):
            break
        cmd, size = struct.unpack_from("<II", header, offset)
        if size < 8 or offset + size > len(header):
            break
        if cmd == 0x32 and size >= 24:  # LC_BUILD_VERSION
            value = struct.unpack_from("<I", header, offset + 12)[0]
            return (value >> 16, (value >> 8) & 255, value & 255)
        if cmd == 0x24 and size >= 12:  # LC_VERSION_MIN_MACOSX
            value = struct.unpack_from("<I", header, offset + 8)[0]
            return (value >> 16, (value >> 8) & 255, value & 255)
        offset += size
    return None


def runtime_floor(directory: Path) -> Optional[tuple]:
    """Maximum declared minos across every Mach-O below a staged runtime dir."""
    highest: Optional[tuple] = None
    if not directory.is_dir():
        return None
    for candidate in sorted(directory.rglob("*")):
        if candidate.is_symlink() or not candidate.is_file():
            continue
        declared = macho_minimum_os(candidate)
        if declared is not None and (highest is None or declared > highest):
            highest = declared
    return highest


def derive_minimum_os(
    cli_binary: Path,
    override: Optional[str] = None,
    runtime_dirs: Sequence[Path] = (),
) -> str:
    """Honest floor: documented runtime floor, raised by any Mach-O header that
    demands more (CLI plus every staged runtime library). Never lowered below
    the runtime evidence."""
    floor = DOCUMENTED_MACOS_FLOOR
    if override:
        floor = max(floor, parse_version(override))
    binary_floor = macho_minimum_os(cli_binary)
    if binary_floor is not None:
        floor = max(floor, binary_floor)
    for directory in runtime_dirs:
        declared = runtime_floor(directory)
        if declared is not None:
            floor = max(floor, declared)
    return format_version(tuple(floor))


def executable_arch(path: Path) -> Optional[str]:
    try:
        with path.open("rb") as handle:
            header = handle.read(16)
    except OSError:
        return None
    if header[:4] != b"\xcf\xfa\xed\xfe":
        return None
    cpu = struct.unpack_from("<I", header, 4)[0]
    return {0x0100000C: "arm64", 0x01000007: "x86_64"}.get(cpu)


# --- icon handling (native tools only; generic icon when no usable art) ----

def ico_usable(path: Path) -> bool:
    """True only if the ICO carries a real >=16px image payload (not stubs)."""
    try:
        with path.open("rb") as handle:
            data = handle.read(65536)
    except OSError:
        return False
    if data[:4] != b"\0\0\1\0":
        return False
    count = struct.unpack_from("<H", data, 4)[0]
    for index in range(count):
        offset = 6 + 16 * index
        if offset + 16 > len(data):
            break
        width, height = data[offset], data[offset + 1]
        size, entry_offset = struct.unpack_from("<II", data, offset + 8)
        longest = max(width or 256, height or 256)
        if longest >= 16 and size > 64 and entry_offset + size <= len(data):
            return True
    return False


def _sips(args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["/usr/bin/sips", *args], capture_output=True, text=True,
                          timeout=120, check=True)


def icon_from_repo_asset(work_dir: Path) -> Optional[Path]:
    """Convert frontend/app/favicon.ico with stock sips/iconutil when it holds
    real art; return None (generic app icon) whenever it does not."""
    if shutil.which("iconutil") is None or not Path("/usr/bin/sips").exists():
        return None
    if not REPO_FAVICON.is_file() or not ico_usable(REPO_FAVICON):
        return None
    iconset: Optional[Path] = None
    try:
        iconset = work_dir / "AppIcon.iconset"
        iconset.mkdir(parents=True, exist_ok=True)
        png = work_dir / "brand.png"
        _sips(["-s", "format", "png", str(REPO_FAVICON), "--out", str(png)])
        probe = _sips(["-g", "pixelWidth", "-g", "pixelHeight", str(png)])
        dims = [int(line.split(":")[1]) for line in probe.stdout.splitlines()
                if ":" in line and line.split(":")[1].strip().isdigit()]
        if not dims or max(dims) < 16:
            return None
        for size in ICONSET_SIZES:
            _sips(["-z", str(size), str(size), str(png), "--out",
                   str(iconset / f"icon_{size}x{size}.png")])
        target = work_dir / "AppIcon.icns"
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(target)],
                       check=True, capture_output=True, timeout=300)
        return target if target.is_file() else None
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None
    finally:
        if iconset is not None:
            shutil.rmtree(iconset, ignore_errors=True)


# --- bundle assembly ---------------------------------------------------------

def build_info_plist(
    *,
    bundle_id: str,
    short_version: str,
    minimum_os: str,
    icon_file: Optional[str],
) -> Dict[str, Any]:
    plist: Dict[str, Any] = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleDisplayName": APP_NAME,
        "CFBundleExecutable": APP_NAME,
        "CFBundleIdentifier": bundle_id,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": APP_NAME,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": short_version,
        "CFBundleVersion": short_version,
        "LSMinimumSystemVersion": minimum_os,
        "LSApplicationCategoryType": "public.app-category.developer-tools",
        "NSHighResolutionCapable": True,
    }
    if icon_file:
        plist["CFBundleIconFile"] = icon_file
    return plist


def _install_executable(source: Path, target: Path) -> None:
    shutil.copyfile(source, target)
    target.chmod(0o755)


def resolve_project_version(value: Optional[str]) -> str:
    if value and value != "auto":
        return value
    from scripts import release_manifest_lib

    return release_manifest_lib.detect_project_version()


def assemble_app(
    *,
    cli_binary: Path,
    output_dir: Path,
    bundle_id: str = DEFAULT_BUNDLE_ID,
    project_version: Optional[str] = None,
    minimum_os: Optional[str] = None,
    icon_source: Optional[Path] = None,
    runtime_lib_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    if not cli_binary.is_file():
        raise FileNotFoundError(f"CLI binary not found: {cli_binary}")
    for asset in (LAUNCHER_ASSET, COMMAND_ASSET):
        if not asset.is_file():
            raise FileNotFoundError(f"Missing packaging asset: {asset}")
    short_version = resolve_project_version(project_version)
    floor = derive_minimum_os(
        cli_binary, minimum_os, [runtime_lib_dir] if runtime_lib_dir else [])

    output_dir.mkdir(parents=True, exist_ok=True)
    app = output_dir / f"{APP_NAME}.app"
    if app.exists():
        shutil.rmtree(app)
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "Resources").mkdir(parents=True)

    _install_executable(LAUNCHER_ASSET, contents / "MacOS" / APP_NAME)
    _install_executable(COMMAND_ASSET, contents / "Resources" / COMMAND_ASSET.name)
    _install_executable(cli_binary, contents / "Resources" / BUNDLE_BINARY_NAME)

    icon_file = None
    icon_path: Optional[Path] = None
    if icon_source is not None:
        if not icon_source.is_file():
            raise FileNotFoundError(f"Icon source not found: {icon_source}")
        icon_path = icon_source
    else:
        icon_path = icon_from_repo_asset(output_dir)
    if icon_path is not None:
        shutil.copyfile(icon_path, contents / "Resources" / "AppIcon.icns")
        icon_file = "AppIcon"

    plist = build_info_plist(
        bundle_id=bundle_id,
        short_version=short_version,
        minimum_os=floor,
        icon_file=icon_file,
    )
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump(plist, handle)
    (contents / "PkgInfo").write_bytes(b"APPL????")

    inner_digest = sha256_path(cli_binary)
    copied_digest = sha256_path(contents / "Resources" / BUNDLE_BINARY_NAME)
    if inner_digest != copied_digest:
        raise RuntimeError("Bundled CLI copy diverged from the audited binary during assembly")
    return {
        "appPath": str(app),
        "bundleId": bundle_id,
        "bundleExecutable": APP_NAME,
        "cliBinaryName": BUNDLE_BINARY_NAME,
        "cliSourceSha256": inner_digest,
        "cliByteSize": cli_binary.stat().st_size,
        "iconIncluded": icon_file is not None,
        "minimumSystemVersion": floor,
        "runtimeLibFloorScanned": bool(runtime_lib_dir and runtime_lib_dir.is_dir()),
        "shortVersionString": short_version,
    }


# --- signing -----------------------------------------------------------------

def _codesign(args: List[str], timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(["/usr/bin/codesign", *args], capture_output=True,
                          text=True, timeout=timeout)


def inner_signature_valid(path: Path) -> bool:
    """True only when strict verification accepts the existing inner signature."""
    if shutil.which("codesign") is None:
        return False
    result = _codesign(["--verify", "--strict", str(path)], timeout=300)
    return result.returncode == 0


def codesign_bundle(app: Path, identity: str) -> str:
    """Sign the bundle; preserve audited inner bytes when its signature already
    verifies strictly. Returns 'preserved-existing' or 're-signed-inner'.
    Fails closed: any codesign error raises, and the outer strict verification
    must pass before returning."""
    inner = app / "Contents" / "Resources" / BUNDLE_BINARY_NAME
    if inner_signature_valid(inner):
        mode = "preserved-existing"
    else:
        res = _codesign(["--force", "--sign", identity, str(inner)])
        if res.returncode != 0:
            raise RuntimeError(f"codesign of embedded CLI failed: {res.stderr.strip()}")
        if not inner_signature_valid(inner):
            raise RuntimeError("embedded CLI still fails codesign --verify --strict after signing")
        mode = "re-signed-inner"
    outer = _codesign(["--force", "--sign", identity, str(app)])
    if outer.returncode != 0:
        raise RuntimeError(f"codesign of {APP_NAME}.app failed: {outer.stderr.strip()}")
    verify = _codesign(["--verify", "--strict", str(app)])
    if verify.returncode != 0:
        raise RuntimeError(f"{APP_NAME}.app fails codesign --verify --strict: {verify.stderr.strip()}")
    return mode


def codesign_inspect(app: Path) -> Dict[str, Any]:
    """Read-only inspection plus strict verification; 'verifiable' means an
    actual validity check, not merely readable display output."""
    if shutil.which("codesign") is None:
        return {"verifiable": False, "detail": "host has no codesign tool"}
    display = _codesign(["-d", "--verbose=4", str(app)], timeout=300)
    report = display.stderr + display.stdout
    fields: Dict[str, str] = {}
    for line in report.splitlines():
        if "=" in line and not line.startswith(("Executable", "Page size")):
            key, _, value = line.partition("=")
            fields[key.strip()] = value.strip()
    validity = _codesign(["--verify", "--strict", str(app)], timeout=300)
    return {
        "verifiable": validity.returncode == 0,
        "identifier": fields.get("Identifier"),
        "signature": fields.get("Signature"),
        "codeDirectory": fields.get("CodeDirectory"),
    }


def signing_status(identity: str, mode: str, inspection: Dict[str, Any]) -> str:
    if identity == "none":
        return "unsigned (packaging skipped codesign)"
    if not inspection.get("verifiable"):
        return "unverified (codesign --verify --strict failed)"
    basis = {
        "preserved-existing": "embedded CLI signature preserved byte-for-byte",
        "re-signed-inner": "embedded CLI re-signed by packaging (bytes changed)",
    }.get(mode, mode)
    label = "ad-hoc" if identity == "-" else identity
    return f"{label} ({basis}; not Developer ID, not notarized)"


# --- DMG --------------------------------------------------------------------

def make_dmg(app: Path, output: Path, *, volume_name: str = APP_NAME) -> None:
    hdiutil = shutil.which("hdiutil")
    if hdiutil is None:
        raise RuntimeError("hdiutil is required to build the macOS DMG")
    if not INSTALLER_README_ASSET.is_file():
        raise FileNotFoundError(f"Missing packaging asset: {INSTALLER_README_ASSET}")
    staging = output.parent / (output.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    shutil.copytree(app, staging / app.name, symlinks=True)
    shutil.copyfile(INSTALLER_README_ASSET, staging / "README.txt")
    (staging / "Applications").symlink_to(PurePosixPath("/Applications"))
    if output.exists():
        output.unlink()
    subprocess.run(
        [hdiutil, "create", "-quiet", "-srcfolder", str(staging), "-volname", volume_name,
         "-format", "UDZO", str(output)],
        check=True, capture_output=True, text=True, timeout=1800,
    )
    shutil.rmtree(staging, ignore_errors=True)
    subprocess.run(
        [hdiutil, "verify", str(output)], check=True, capture_output=True, text=True, timeout=900,
    )


def verify_mounted_dmg(dmg: Path, expected_embedded_sha: str, *,
                       require_codesign: bool = True) -> Dict[str, Any]:
    """Re-read the inner CLI from a fresh read-only mount and enforce identity.

    The provenance claim is only made after the artifact itself passes this
    check; any mismatch raises before the package is reported complete.
    """
    mount = Path(tempfile.mkdtemp(prefix="encodingdb-dmg-check-"))
    attach = subprocess.run(
        ["hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(dmg)],
        capture_output=True, text=True, timeout=300,
    )
    if attach.returncode != 0:
        raise RuntimeError(f"verification mount failed: {attach.stdout}{attach.stderr}")
    try:
        inner = mount / f"{APP_NAME}.app" / "Contents" / "Resources" / BUNDLE_BINARY_NAME
        observed = sha256_path(inner)
        if observed != expected_embedded_sha:
            raise RuntimeError(
                f"DMG inner CLI hash {observed} != packaged identity {expected_embedded_sha}")
        if not (mount / "README.txt").is_file():
            raise RuntimeError("mounted DMG is missing README.txt")
        result: Dict[str, Any] = {"mounted": True, "innerSha256": observed,
                                  "codesignVerified": None}
        if require_codesign:
            if shutil.which("codesign") is None:
                raise RuntimeError("signing verification requested but codesign is unavailable")
            for target in (inner, mount / f"{APP_NAME}.app"):
                check = _codesign(["--verify", "--strict", str(target)], timeout=300)
                if check.returncode != 0:
                    raise RuntimeError(
                        f"mounted artifact fails codesign --verify --strict: {check.stderr.strip()}")
            result["codesignVerified"] = True
        return result
    finally:
        subprocess.run(["hdiutil", "detach", "-force", str(mount)],
                       capture_output=True, timeout=300)
        shutil.rmtree(mount, ignore_errors=True)


def collect_source_identity() -> Dict[str, Any]:
    from scripts import release_manifest_lib

    return release_manifest_lib.source_identity()


def package(args: argparse.Namespace) -> int:
    cli_binary = Path(args.cli_binary).resolve()
    output_dmg = Path(args.output_dmg)
    work_dir = Path(args.work_dir).resolve() if args.work_dir else output_dmg.parent / ".macos-package-work"
    icon_source = Path(args.icon_source) if args.icon_source else None
    info: Dict[str, Any] = {"schemaVersion": 2, "provisional": bool(args.provisional)}
    info.update(assemble_app(
        cli_binary=cli_binary,
        output_dir=work_dir,
        bundle_id=args.bundle_id,
        project_version=args.project_version,
        minimum_os=None if args.minimum_os == "auto" else args.minimum_os,
        icon_source=icon_source,
        runtime_lib_dir=Path(args.runtime_lib_dir) if args.runtime_lib_dir else None,
    ))

    identity = args.sign
    if identity == "auto":
        identity = "-" if shutil.which("codesign") else "none"
    sign_mode = "skipped (signing disabled)"
    if identity != "none":
        sign_mode = codesign_bundle(Path(info["appPath"]), identity)
    embedded_sha = sha256_path(Path(info["appPath"]) / "Contents" / "Resources" / BUNDLE_BINARY_NAME)
    inspection = codesign_inspect(Path(info["appPath"]))
    if identity != "none" and not inspection["verifiable"]:
        raise RuntimeError("signing was requested but codesign --verify --strict fails on the bundle")
    info["cliEmbeddedSha256"] = embedded_sha
    info["cliBytesChangedByPackaging"] = embedded_sha != info["cliSourceSha256"]
    info["signing"] = {"identity": identity, "mode": sign_mode,
                       "status": signing_status(identity, sign_mode, inspection),
                       "inspection": inspection}

    arch = executable_arch(cli_binary) or "unknown"
    if args.dmg_name_auto:
        output_dmg = output_dmg.with_name(f"{APP_NAME}-macOS-{arch}.dmg")
    if args.skip_dmg:
        info["dmg"] = None
        info["appArtifact"] = str(Path(info["appPath"]))
    else:
        make_dmg(Path(info["appPath"]), output_dmg, volume_name=args.volume_name)
        mount_proof = None if args.skip_mount_verify else verify_mounted_dmg(
            output_dmg, embedded_sha, require_codesign=identity != "none")
        info["dmg"] = {
            "fileName": output_dmg.name,
            "sha256": sha256_path(output_dmg),
            "byteSize": output_dmg.stat().st_size,
            "volumeName": args.volume_name,
            "readOnlyMountVerification": mount_proof,
        }
    info["source"] = collect_source_identity()
    sidecar_base = Path(info["appArtifact"]) if args.skip_dmg else output_dmg
    info_path = sidecar_base.with_name(sidecar_base.name + ".package-info.json")
    info_path.write_text(json.dumps(info, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
                         encoding="utf-8")
    if not args.skip_dmg:
        from scripts import release_manifest_lib

        release_manifest_lib.write_sha256sums(
            sidecar_base.with_name(sidecar_base.name + ".SHA256SUMS"), [output_dmg])
    print(f"[macOS package] {json.dumps(info, sort_keys=True)}")
    return 0


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cli_binary", help="audited PyInstaller onefile CLI binary")
    parser.add_argument("output_dmg", help="DMG output path; name is corrected to the real arch unless --no-dmg-name-auto")
    parser.add_argument("--work-dir", default="", help="staging directory for the .app")
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    parser.add_argument("--project-version", default="auto")
    parser.add_argument("--minimum-os", default="auto",
                        help='"auto" derives from load commands plus documented runtime floor')
    parser.add_argument("--icon-source", default="", help="optional prebuilt .icns")
    parser.add_argument("--runtime-lib-dir", default="",
                        help="staged runtime dylib directory to scan for the real support floor")
    parser.add_argument("--sign", default="auto",
                        help='"auto" (ad-hoc), "none", or a codesign identity string')
    parser.add_argument("--volume-name", default=APP_NAME)
    parser.add_argument("--skip-dmg", action="store_true", help="assemble the .app only")
    parser.add_argument("--skip-mount-verify", action="store_true",
                        help="skip the post-build read-only mount identity check (tests only)")
    parser.add_argument("--provisional", action="store_true",
                        help="mark the package-info as a non-publishable provisional wrapper")
    parser.add_argument("--no-dmg-name-auto", dest="dmg_name_auto", action="store_false",
                        help="keep the requested DMG name even if it disagrees with the arch")
    parser.set_defaults(dmg_name_auto=True)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    return package(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
