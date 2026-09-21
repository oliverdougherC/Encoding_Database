"""Regression coverage for encodingdb-client-linux.tar.gz.

The primary Linux artifact must keep executable bits, be byte-deterministic,
lead to the guided menu with no injected arguments, and forward hostile quoting
untouched without writing to the caller's directory.
"""
import gzip
import io
import json
import os
import select
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts import linux_client_package as lcp

NASTY_DIR = "Wéird $'bäck' (x;y|&ü)"

STUB_CLI = """#!/usr/bin/env python3
import json, os, sys
report = {
    "argv": sys.argv[1:],
    "stdinTty": sys.stdin.isatty(),
    "cwd": os.getcwd(),
}
path = os.environ.get("ENCODINGDB_STUB_REPORT")
if path:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False)
sys.exit(0)
"""


def run_with_pty(command, env, cwd) -> tuple:
    master, slave = os.openpty()
    slave_open = True
    try:
        proc = subprocess.Popen([str(command)], stdin=slave, stdout=slave, stderr=slave,
                                cwd=str(cwd), env=env)
        os.close(slave)
        slave_open = False
        chunks = []
        while True:
            readable, _, _ = select.select([master], [], [], 15)
            if not readable:
                proc.kill()
                raise TimeoutError("start.sh hung on the pty")
            try:
                data = os.read(master, 4096)
            except OSError:
                break
            if not data:
                break
            chunks.append(data)
            if proc.poll() is not None and not select.select([master], [], [], 0.2)[0]:
                break
        return proc.wait(timeout=20), b"".join(chunks).decode("utf-8", "replace")
    finally:
        if slave_open:
            os.close(slave)
        os.close(master)


class LinuxClientPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.binary = self.root / "encodingdb-client-linux"
        self.binary.write_text(STUB_CLI, encoding="utf-8")
        self.binary.chmod(0o755)

    def build(self, output: Path) -> dict:
        return lcp.build_archive(self.binary, output)

    def test_archive_modes_membership_and_determinism(self) -> None:
        first = self.build(self.root / "one.tar.gz")
        second = self.build(self.root / "two.tar.gz")
        self.assertEqual(first["sha256"], second["sha256"],
                         "identical inputs must produce byte-identical archives")
        with tarfile.open(self.root / "one.tar.gz", "r:gz") as archive:
            modes = {member.name: member.mode & 0o777 for member in archive.getmembers()}
        self.assertEqual(modes, {
            "encodingdb-client-linux/encodingdb-client-linux": 0o755,
            "encodingdb-client-linux/start.sh": 0o755,
            "encodingdb-client-linux/README.md": 0o644,
        })
        verification = lcp.verify_archive(self.root / "one.tar.gz")
        self.assertTrue(verification["verified"])

    def test_verify_rejects_unsafe_or_unrunnable_archives(self) -> None:
        raw = io.BytesIO()
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as archive:
                payload = b"#!/bin/sh\nexit 0\n"
                info = tarfile.TarInfo("encodingdb-client-linux/encodingdb-client-linux")
                info.size = len(payload)
                info.mode = 0o644  # not executable: extraction would need chmod
                archive.addfile(info, io.BytesIO(payload))
        bad = self.root / "bad.tar.gz"
        bad.write_bytes(raw.getvalue())
        with self.assertRaisesRegex(RuntimeError, "membership/modes drifted"):
            lcp.verify_archive(bad)

    def test_start_script_forwards_hostile_args_on_tty_without_cwd_writes(self) -> None:
        if sys.platform == "win32":
            self.skipTest("POSIX pty launch path is not exercisable on Windows")
        archive = self.root / "client.tar.gz"
        self.build(archive)
        extract_root = self.root / NASTY_DIR
        extract_root.mkdir()
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(extract_root)
        start = extract_root / "encodingdb-client-linux" / "start.sh"
        self.assertTrue(start.stat().st_mode & 0o111,
                        "tar extraction of the shipped modes yields runnable launchers")

        cwd = extract_root / "cwd"
        cwd.mkdir()
        report = extract_root / "report.json"
        env = dict(os.environ)
        env.update({"ENCODINGDB_STUB_REPORT": str(report)})

        # Guided default: no arguments means no injected sweep/legacy flags.
        status, _ = run_with_pty(start, env, cwd)
        self.assertEqual(status, 0)
        observed = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(observed["argv"], [])
        self.assertTrue(observed["stdinTty"], "guided menu must receive a real TTY")
        self.assertEqual(observed["cwd"], os.path.realpath(str(cwd)))

        # Hostile arguments survive the wrapper untouched.
        args = ["--flag", "two words", "ünïcode $'`ü", "quote'd", "semi;colon|pipe&"]
        quoted = " ".join("'" + a.replace("'", "'\\''") + "'" for a in args)
        runner = extract_root / "invoke.sh"
        runner.write_text(f'#!/bin/sh\nexec "{start}" {quoted}\n', encoding="utf-8")
        runner.chmod(0o755)
        status, _ = run_with_pty(runner, env, cwd)
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["argv"], args)

        entries = sorted(p.name for p in cwd.iterdir())
        self.assertEqual(entries, [], "launch must not write into the caller's directory")

    def test_package_writes_sidecars_and_source_identity(self) -> None:
        output = self.root / "encodingdb-client-linux.tar.gz"
        self.assertEqual(lcp.main([str(self.binary), str(output), "--provisional"]), 0)
        info = json.loads(output.with_name(output.name + ".package-info.json").read_text())
        self.assertTrue(info["provisional"])
        self.assertEqual(info["archive"]["sha256"], lcp.sha256_path(output))
        self.assertTrue(info["verification"]["verified"])
        self.assertIn("revision", info["source"])
        sums = output.with_name(output.name + ".SHA256SUMS")
        self.assertTrue(any(line.endswith("  encodingdb-client-linux.tar.gz")
                            for line in sums.read_text(encoding="utf-8").splitlines()))


if __name__ == "__main__":
    unittest.main()
