#!/usr/bin/env python3
"""Publish the three primary downloads from an assembled native candidate."""

import argparse
import subprocess
from pathlib import Path

from assemble_client_release import _path, _read_json, assemble

PUBLIC_ROLES = {"linux-archive", "macos-dmg", "windows-gui"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True, help="Native assembly spec")
    parser.add_argument("--notes", type=Path, required=True, help="Reviewed release notes")
    parser.add_argument("--prerelease", action="store_true")
    args = parser.parse_args()

    spec = _read_json(args.spec)
    manifest = assemble(spec, args.spec.parent)
    tag = manifest["projectVersion"]
    commit = subprocess.check_output(
        ["gh", "api", "--method", "GET", "repos/{owner}/{repo}/commits",
         "-f", f"sha=refs/tags/{tag}", "-F", "per_page=1", "--jq", ".[0].sha"],
        text=True,
    ).strip()
    if commit != manifest["sourceRevision"]:
        parser.error("the remote release tag must point to the reviewed build revision")

    files = sorted(
        _path(args.spec.parent, entry["artifact"]).resolve()
        for entry in spec["assets"]
        if entry["role"] in PUBLIC_ROLES
    )
    if len({file.name for file in files}) != len(PUBLIC_ROLES):
        parser.error("the three public downloads must have distinct filenames")

    command = ["gh", "release", "create", "--verify-tag", "--title", f"EncodingDB {tag}",
               "--notes-file", str(args.notes), "--fail-on-no-commits"]
    if args.prerelease:
        command.append("--prerelease")
    subprocess.run([*command, "--", tag, *map(str, files)], check=True)


if __name__ == "__main__":
    main()
