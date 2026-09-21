#!/usr/bin/env python3
"""Assemble EncodingDB.app and EncodingDB-macOS-<arch>.dmg around the packaged CLI.

The published macOS surface must be a recognizable double-clickable application,
never a raw extensionless binary. This helper wraps the PyInstaller onefile CLI
in an app bundle whose executable opens the guided terminal interface through
Terminal.app (real stdin/stdout, readable window), then packs that bundle into a
read-only DMG with honest signing/support metadata.

Nothing here mutates the CLI bytes, the locked FFmpeg runtime, or the pinned
VMAF model; the bundle embeds a hash-verified copy of the audited binary and the
package-info sidecar binds the inner and outer digests together.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Sequence

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

PACKAGING_DIR = ROOT_DIR / "packaging" / "macos"
LAUNCHER_ASSET = PACKAGING_DIR / "launcher.sh"
COMMAND_ASSET = PACKAGING_DIR / "EncodingDB.command"
INSTALLER_README_ASSET = PACKAGING_DIR / "README-installer.txt"

APP_NAME = "EncodingDB"
BUNDLE_BINARY_NAME = "encodingdb"
DEFAULT_BUNDLE_ID = "com.encodingdb.client"
# Evidence for this floor lives in docs/NATIVE_RUNTIME_20260914.md: inside the
# locked macOS runtime, libpcre2-8.0.dylib and libharfbuzz.0.dylib declare
# minos 27.0. The outer PyInstaller header alone says 11.0 and must not be
# mistaken for the package floor. Never lower this without new load-command
# evidence from the exact bundled dylibs.
DOCUMENTED_MACOS_FLOOR = (27, 0)

ICONSET_ENTRIES = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def format_version(value: tuple) -> str:
    parts = [str(part) for part in value]
    while len(parts) > 2 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


def parse_version(text: str) -> tuple:
    parts = [int(part) for part in str(text).strip().split(".") if part != ""]
    while len(parts) < 2:
        parts.append(0)
    return tuple(parts)


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


# --- icon rendering (pure stdlib, deterministic) ---------------------------

_ACCENT = (79, 127, 240)
_TEAL = (93, 199, 182)
_LIGHT = (237, 242, 247)
_CANVAS = (13, 17, 23)


def _sdf_round_rect(x: float, y: float, half_w: float, half_h: float, radius: float) -> float:
    dx = abs(x) - half_w + radius
    dy = abs(y) - half_h + radius
    outside = ((max(dx, 0.0)) ** 2 + (max(dy, 0.0)) ** 2) ** 0.5
    inside = min(max(dx, dy), 0.0)
    return outside + inside - radius


def _coverage(distance: float) -> float:
    return max(0.0, min(1.0, 0.5 - distance))


def _blend(dst: Sequence[float], src: Sequence[int], alpha: float) -> Sequence[float]:
    if alpha <= 0.0:
        return dst
    return tuple(channel * (1.0 - alpha) + src[channel] * alpha for channel in range(4))


def _render_icon_png(size: int) -> bytes:
    center = size / 2.0
    tile = size / 2.0
    radius = size * 0.22
    inset = size * 0.055
    bar_half_h = size * 0.052
    bar_gap = size * 0.135
    bar_left = size * 0.205
    bar_lengths = (size * 0.245, size * 0.345, size * 0.445)
    bar_colors = (_LIGHT, _TEAL, _ACCENT)
    bar_radius = bar_half_h

    rows = bytearray()
    for py in range(size):
        rows.append(0)
        y = center - py
        for px in range(size):
            x = px - center
            bg = _sdf_round_rect(x, y, tile - inset, tile - inset, radius)
            color = _blend((0.0, 0.0, 0.0, 0.0), _CANVAS + (255,), _coverage(bg))
            for index, length in enumerate(bar_lengths):
                bar_y = bar_gap * (index - 1)
                half_w = length / 2.0
                bar_x = bar_left + half_w - center
                distance = _sdf_round_rect(x - bar_x, y - bar_y, half_w, bar_half_h, bar_radius)
                color = _blend(color, bar_colors[index] + (255,), _coverage(distance))
            for channel in range(4):
                rows.append(int(round(max(0.0, min(255.0, color[channel])))))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    raw = bytes(rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def render_app_icon(work_dir: Path) -> Optional[Path]:
    """Render the deterministic mark into AppIcon.icns via iconutil, if present."""
    iconutil = shutil.which("iconutil")
    if iconutil is None:
        return None
    iconset = work_dir / "AppIcon.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    for name, size in sorted(ICONSET_ENTRIES.items(), key=lambda item: item[1]):
        (iconset / name).write_bytes(_render_icon_png(size))
    target = work_dir / "AppIcon.icns"
    subprocess.run(
        [iconutil, "-c", "icns", str(iconset), "-o", str(target)],
        check=True, capture_output=True, timeout=300,
    )
    shutil.rmtree(iconset, ignore_errors=True)
    return target


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
    if icon_source is not None:
        if not icon_source.is_file():
            raise FileNotFoundError(f"Icon source not found: {icon_source}")
        shutil.copyfile(icon_source, contents / "Resources" / "AppIcon.icns")
        icon_file = "AppIcon"
    else:
        rendered = render_app_icon(output_dir)
        if rendered is not None:
            shutil.copyfile(rendered, contents / "Resources" / "AppIcon.icns")
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
        "cliSha256": inner_digest,
        "cliByteSize": cli_binary.stat().st_size,
        "iconIncluded": icon_file is not None,
        "minimumSystemVersion": floor,
        "runtimeLibFloorScanned": bool(runtime_lib_dir and runtime_lib_dir.is_dir()),
        "shortVersionString": short_version,
    }


# --- signing ---------------------------------------------------------------

def codesign_bundle(app: Path, identity: str) -> None:
    for target in (app / "Contents" / "Resources" / BUNDLE_BINARY_NAME, app):
        subprocess.run(
            ["/usr/bin/codesign", "--force", "--sign", identity, str(target)],
            check=True, capture_output=True, text=True, timeout=900,
        )


def codesign_inspect(app: Path) -> Dict[str, Any]:
    """Read-only inspection so the sidecar reports what the bundle actually is."""
    if shutil.which("codesign") is None:
        return {"verifiable": False, "detail": "host has no codesign tool"}
    result = subprocess.run(
        ["/usr/bin/codesign", "-d", "--verbose=4", str(app)],
        capture_output=True, text=True, timeout=300,
    )
    report = result.stderr + result.stdout
    fields: Dict[str, str] = {}
    for line in report.splitlines():
        if "=" in line and not line.startswith(("Executable", "Page size")):
            key, _, value = line.partition("=")
            fields[key.strip()] = value.strip()
    return {
        "verifiable": result.returncode == 0,
        "identifier": fields.get("Identifier"),
        "signature": fields.get("Signature"),
        "codeDirectory": fields.get("CodeDirectory"),
    }


def signing_status(identity: str, inspection: Dict[str, Any]) -> str:
    if identity == "none":
        return "unsigned (packaging skipped codesign)"
    if not inspection.get("verifiable"):
        return "unverified (codesign inspection failed)"
    if identity == "-":
        return "ad-hoc (not Developer ID, not notarized)"
    return f"{identity} (not notarized)"


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
    if INSTALLER_README_ASSET.is_file():
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


def collect_source_identity() -> Dict[str, Any]:
    from scripts import release_manifest_lib

    return release_manifest_lib.source_identity()


def package(args: argparse.Namespace) -> int:
    cli_binary = Path(args.cli_binary).resolve()
    output_dmg = Path(args.output_dmg)
    work_dir = Path(args.work_dir).resolve() if args.work_dir else output_dmg.parent / ".macos-package-work"
    icon_source = Path(args.icon_source) if args.icon_source else None
    info: Dict[str, Any] = {"schemaVersion": 1, "provisional": bool(args.provisional)}
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
    if identity != "none":
        codesign_bundle(Path(info["appPath"]), identity)
    inspection = codesign_inspect(Path(info["appPath"]))
    info["signing"] = {"identity": identity, "status": signing_status(identity, inspection),
                       "inspection": inspection}

    arch = executable_arch(cli_binary) or "unknown"
    if args.dmg_name_auto:
        output_dmg = output_dmg.with_name(f"{APP_NAME}-macOS-{arch}.dmg")
    if args.skip_dmg:
        info["dmg"] = None
        info["appArtifact"] = str(Path(info["appPath"]))
    else:
        make_dmg(Path(info["appPath"]), output_dmg, volume_name=args.volume_name)
        info["dmg"] = {
            "fileName": output_dmg.name,
            "sha256": sha256_path(output_dmg),
            "byteSize": output_dmg.stat().st_size,
            "volumeName": args.volume_name,
        }
    info["source"] = collect_source_identity()
    if args.skip_dmg:
        sidecar_base = Path(info["appArtifact"])
    else:
        sidecar_base = output_dmg
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
