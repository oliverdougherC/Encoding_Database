#!/usr/bin/env python3
"""Recover the reviewed FFmpeg bytes from immutable candidate archives.

The original BtbN autobuild tag was removed upstream. These existing public
EncodingDB candidate archives embed the *same* FFmpeg/FFprobe bytes. Verify
the archive digest and each extracted binary against the checked-in runtime
lock before CI or a native build may use them. Requires the already-pinned
PyInstaller build dependency; does not register a new runtime identity.
"""

import argparse
import hashlib
import json
import stat
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE = "https://github.com/oliverdougherC/Encoding_Database/releases/download/encodingdb-beta-review-assets-20260909"
SOURCES = {
    "linux": {
        "archive": "encodingdb-linux-candidate-ci34430919675-2d3ed7d4d167.tar.gz",
        "archiveSha256": "cb2712b94b705cf447eb4b550e8f3b2be1bfcc6120db1f361a6534234bfb325c",
        "archiveBytes": 169129799,
        "member": "encodingdb-linux-candidate-ci34430919675-2d3ed7d4d167/encodingdb-client-linux",
        "directory": "ffmpeg-n8.1.2-51-g7ba069f4f1-linux64-gpl-8.1",
        "toc": {"ffmpeg": "bin/linux/ffmpeg", "ffprobe": "bin/linux/ffprobe"},
    },
    "win": {
        "archive": "encodingdb-windows-candidate-ci34430919675-2d3ed7d4d167.zip",
        "archiveSha256": "9e00b681397044ced552ec9539d10af42c731fe5a8b583eb9efb72de917fbe05",
        "archiveBytes": 294384846,
        "member": "encodingdb-client-windows-console.exe",
        "directory": "ffmpeg-n8.1.2-51-g7ba069f4f1-win64-gpl-8.1",
        "toc": {"ffmpeg": r"bin\win\ffmpeg.exe", "ffprobe": r"bin\win\ffprobe.exe"},
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, target: Path) -> None:
    with urllib.request.urlopen(url, timeout=30) as response, target.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)


def provision(platform: str, output_root: Path, *, archive_path: Path | None = None) -> Path:
    spec = SOURCES[platform]
    lock = json.loads((ROOT / "client/resources/runtime/ffmpeg-lock.json").read_text())["platforms"][platform]
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="reviewed-runtime-") as temp:
        temp_root = Path(temp)
        candidate = archive_path or temp_root / spec["archive"]
        if archive_path is None:
            _download(f"{RELEASE}/{spec['archive']}", candidate)
        if candidate.stat().st_size != spec["archiveBytes"] or _sha256(candidate) != spec["archiveSha256"]:
            raise RuntimeError("candidate archive differs from reviewed SHA-256/size")

        onefile = temp_root / Path(spec["member"]).name
        if platform == "linux":
            with tarfile.open(candidate, "r:gz") as archive:
                member = archive.getmember(spec["member"])
                if not member.isfile():
                    raise RuntimeError("candidate executable is not a regular file")
                source = archive.extractfile(member)
                if source is None:
                    raise RuntimeError("candidate executable cannot be read")
                with source, onefile.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
        else:
            with zipfile.ZipFile(candidate) as archive, archive.open(spec["member"]) as source, onefile.open("wb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)

        from PyInstaller.archive.readers import CArchiveReader
        reader = CArchiveReader(str(onefile))
        bundle = output_root / spec["directory"] / "bin"
        bundle.mkdir(parents=True, exist_ok=True)
        for name, toc_name in spec["toc"].items():
            data = reader.extract(toc_name)
            expected = lock[name]
            if len(data) != expected["byteSize"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
                raise RuntimeError(f"embedded {name} differs from reviewed runtime lock")
            target = bundle / Path(toc_name.replace("\\", "/")).name
            target.write_bytes(data)
            if platform == "linux":
                target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            if _sha256(target) != expected["sha256"]:
                raise RuntimeError(f"installed {name} changed after verification")
        receipt = {"platform": platform, "archive": spec["archive"],
                   "archiveSha256": spec["archiveSha256"],
                   "runtime": {name: lock[name]["sha256"] for name in spec["toc"]}}
        (bundle.parent / "provision-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=sorted(SOURCES), required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--archive-path", type=Path, help="Use an already-downloaded candidate archive")
    args = parser.parse_args()
    bundle = provision(args.platform, args.output_root, archive_path=args.archive_path)
    print(f"Reviewed {args.platform} runtime: {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
