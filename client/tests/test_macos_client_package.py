"""Regression coverage for the double-clickable macOS packaging surface.

Covers: bundle identity metadata and launch wiring, load-command-derived support
floor, TTY launch quoting through the Terminal wrapper, launcher hand-off to a
checked Terminal candidate, failure-status retention, real code-signing
provenance transitions (preserve vs re-sign, verified from a read-only DMG
mount), and the DMG sidecar contract. All GUI-level behavior is exercised via
this isolated pty/CLI harness — no Finder/Terminal acceptance is claimed here.
"""
import json
import os
import plistlib
import select
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import macos_client_package as mcp

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
sys.exit(int(os.environ.get("ENCODINGDB_STUB_EXIT", "0")))
"""

FAKE_OPEN = """#!/bin/sh
printf '%s\\n' "$@" >> "$ENCODINGDB_OPEN_LOG"
exit ${ENCODINGDB_FAKE_OPEN_EXIT:-0}
"""


def macho_stub_bytes(minos: int, cmd: int = 0x32, cpu: int = 0x0100000C) -> bytes:
    """Thin Mach-O header with a single min-version load command."""
    load_cmd = struct.pack("<IIIII", cmd, 24, 1, minos, 0x000F0000) + b"\0" * 4
    header = struct.pack("<IiiIIIII", 0xFEEDFACF, cpu, 0, 2, 1, 24, 0, 0)
    return header + load_cmd


def os_version(major: int, minor: int = 0, patch: int = 0) -> int:
    return (major << 16) | (minor << 8) | patch


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def run_with_pty(command, env, cwd, feed=b"") -> tuple:
    """Run `command` with all stdio on a pty; return (exit status, output text)."""
    master, slave = os.openpty()
    slave_open = True
    try:
        proc = subprocess.Popen(
            [str(command)], stdin=slave, stdout=slave, stderr=slave,
            cwd=str(cwd), env=env,
        )
        os.close(slave)
        slave_open = False
        if feed:
            os.write(master, feed)
        chunks = []
        while True:
            readable, _, _ = select.select([master], [], [], 15)
            if not readable:
                proc.kill()
                raise TimeoutError("wrapped command hung on the pty")
            try:
                data = os.read(master, 4096)
            except OSError:
                break
            if not data:
                break
            chunks.append(data)
            if proc.poll() is not None and not select.select([master], [], [], 0.2)[0]:
                break
        status = proc.wait(timeout=20)
        return status, b"".join(chunks).decode("utf-8", "replace")
    finally:
        if slave_open:
            os.close(slave)
        os.close(master)


class MacosBundlePackagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write_stub_cli(self, directory: Path) -> Path:
        cli = directory / "cli"
        cli.write_text(STUB_CLI, encoding="utf-8")
        cli.chmod(0o755)
        return cli

    def assemble(self, cli: Path, work: Path) -> dict:
        return mcp.assemble_app(cli_binary=cli, output_dir=work, project_version="9.9.9-test")

    def test_minimum_floor_never_below_runtime_evidence(self) -> None:
        script = self.root / "script-cli"
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.assertEqual(mcp.derive_minimum_os(script), "27.0")
        low = self.root / "low"
        low.write_bytes(macho_stub_bytes(os_version(11)))
        self.assertEqual(mcp.derive_minimum_os(low), "27.0")
        legacy = self.root / "legacy"
        legacy.write_bytes(macho_stub_bytes(os_version(26, 5), cmd=0x24))
        self.assertEqual(mcp.derive_minimum_os(legacy), "27.0")
        high = self.root / "high"
        high.write_bytes(macho_stub_bytes(os_version(28, 5)))
        self.assertEqual(mcp.derive_minimum_os(high), "28.5")
        lib_dir = self.root / "lib"
        lib_dir.mkdir()
        (lib_dir / "libpcre2-8.0.dylib").write_bytes(macho_stub_bytes(os_version(26, 5)))
        (lib_dir / "libharfbuzz.0.dylib").write_bytes(macho_stub_bytes(os_version(28, 0)))
        (lib_dir / "not-a-macho.txt").write_text("data", encoding="utf-8")
        self.assertEqual(mcp.derive_minimum_os(script, None, [lib_dir]), "28.0")
        self.assertIsNone(mcp.runtime_floor(self.root / "absent"))
        self.assertEqual(mcp.derive_minimum_os(script, "30.1"), "30.1")

    def test_bundle_identity_and_launch_wiring(self) -> None:
        cli = self.write_stub_cli(self.root)
        info = self.assemble(cli, self.root / "work")
        app = Path(info["appPath"])
        contents = app / "Contents"
        with (contents / "Info.plist").open("rb") as handle:
            plist = plistlib.load(handle)
        self.assertEqual(plist["CFBundleExecutable"], "EncodingDB")
        self.assertEqual(plist["CFBundleName"], "EncodingDB")
        self.assertEqual(plist["CFBundleDisplayName"], "EncodingDB")
        self.assertEqual(plist["CFBundleIdentifier"], mcp.DEFAULT_BUNDLE_ID)
        self.assertEqual(plist["CFBundlePackageType"], "APPL")
        self.assertEqual(plist["CFBundleShortVersionString"], "9.9.9-test")
        self.assertEqual(plist["LSMinimumSystemVersion"], "27.0")
        self.assertEqual(info["cliSourceSha256"], mcp.sha256_path(cli))
        self.assertEqual(mcp.sha256_path(contents / "Resources" / "encodingdb"),
                         info["cliSourceSha256"])
        usable_art = shutil.which("iconutil") and mcp.ico_usable(mcp.REPO_FAVICON)
        if usable_art:
            self.assertEqual(plist["CFBundleIconFile"], "AppIcon")
        else:
            # Off macOS hosts lack iconutil, so the bundle honestly ships the
            # generic app icon rather than claiming a converted brand asset.
            self.assertNotIn("CFBundleIconFile", plist)
            self.assertFalse(info["iconIncluded"])
        for executable in (contents / "MacOS" / "EncodingDB",
                           contents / "Resources" / "EncodingDB.command",
                           contents / "Resources" / "encodingdb"):
            self.assertTrue(executable.is_file(), str(executable))
            self.assertTrue(executable.stat().st_mode & stat.S_IXUSR, str(executable))
        self.assertEqual((contents / "PkgInfo").read_bytes(), b"APPL????")

    def test_explicit_icon_source_is_embedded(self) -> None:
        cli = self.write_stub_cli(self.root)
        icns = self.root / "brand.icns"
        icns.write_bytes(b"icns" + b"\0" * 32)
        info = mcp.assemble_app(cli_binary=cli, output_dir=self.root / "work",
                                project_version="9.9.9-test", icon_source=icns)
        plist_path = Path(info["appPath"]) / "Contents" / "Info.plist"
        with plist_path.open("rb") as handle:
            plist = plistlib.load(handle)
        self.assertEqual(plist["CFBundleIconFile"], "AppIcon")
        self.assertEqual((Path(info["appPath"]) / "Contents" / "Resources" / "AppIcon.icns")
                         .read_bytes(), icns.read_bytes())

    def test_favicon_is_real_art_and_converts_to_icns(self) -> None:
        self.assertTrue(mcp.ico_usable(mcp.REPO_FAVICON),
                        "frontend/app/favicon.ico carries a real 256px PNG entry")
        if sys.platform != "darwin" or not (shutil.which("iconutil")
                                            and Path("/usr/bin/sips").exists()):
            self.skipTest("native sips/iconutil conversion requires macOS")
        icns = mcp.icon_from_repo_asset(self.root / "icon-work")
        self.assertIsNotNone(icns)
        self.assertEqual(icns.read_bytes()[:4], b"icns")

    def test_wrapper_runs_bundled_cli_on_real_tty_with_hostile_paths(self) -> None:
        if sys.platform == "win32":
            self.skipTest("POSIX pty launch path is not exercisable on Windows")
        nasty_root = self.root / NASTY_DIR
        nasty_root.mkdir()
        cli = self.write_stub_cli(nasty_root)
        info = self.assemble(cli, nasty_root / "work")
        wrapper = Path(info["appPath"]) / "Contents" / "Resources" / "EncodingDB.command"
        report = nasty_root / "report.json"
        cwd = nasty_root / "cwd"
        cwd.mkdir()
        args = ["plain", "two words", "ünïcode $'`ü", "quote'd", "semi;colon|pipe&", "back\\slash"]
        env = dict(os.environ)
        env.update({
            "ENCODINGDB_STUB_REPORT": str(report),
            "ENCODINGDB_NO_HOLD": "1",
        })
        cwd_before = sorted(p.name for p in cwd.iterdir())
        status, _ = self._run_wrapped(wrapper, cwd, env, args)
        self.assertEqual(status, 0)
        observed = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(observed["argv"], args)
        self.assertTrue(observed["stdinTty"], "guided interface must receive a real TTY")
        self.assertEqual(observed["cwd"], os.path.realpath(str(cwd)))
        self.assertEqual(sorted(p.name for p in cwd.iterdir()), cwd_before,
                         "launch must not write into the caller's working directory")

    def _run_wrapped(self, wrapper, cwd, env, args, feed=b""):
        script = self.root / "invoke.sh"
        quoted = " ".join(_shell_quote(arg) for arg in args)
        script.write_text(f'#!/bin/sh\nexec "{wrapper}" {quoted}\n', encoding="utf-8")
        script.chmod(0o755)
        return run_with_pty(script, env, cwd, feed)

    def test_failure_status_is_reported_and_held(self) -> None:
        if sys.platform == "win32":
            self.skipTest("POSIX pty launch path is not exercisable on Windows")
        cli = self.write_stub_cli(self.root)
        info = self.assemble(cli, self.root / "work")
        wrapper = Path(info["appPath"]) / "Contents" / "Resources" / "EncodingDB.command"
        env = dict(os.environ)
        env.update({
            "ENCODINGDB_STUB_REPORT": str(self.root / "report.json"),
            "ENCODINGDB_STUB_EXIT": "7",
        })
        status, output = self._run_wrapped(wrapper, self.root, env, [], feed=b"\n")
        self.assertEqual(status, 7)
        self.assertIn("exited with status 7", output)
        self.assertIn("Press Return to close", output)

    def _launcher_fixture(self):
        nasty_root = self.root / NASTY_DIR
        nasty_root.mkdir()
        cli = self.write_stub_cli(nasty_root)
        info = self.assemble(cli, nasty_root / "work")
        launcher = Path(info["appPath"]) / "Contents" / "MacOS" / "EncodingDB"
        fake_open = nasty_root / "fake-open"
        fake_open.write_text(FAKE_OPEN, encoding="utf-8")
        fake_open.chmod(0o755)
        open_log = nasty_root / "open.log"
        env = dict(os.environ)
        env.update({"ENCODINGDB_OPEN_BIN": str(fake_open),
                    "ENCODINGDB_OPEN_LOG": str(open_log),
                    "ENCODINGDB_SUPPRESS_ALERT": "1"})
        wrapper = Path(info["appPath"]) / "Contents" / "Resources" / "EncodingDB.command"
        return launcher, env, open_log, wrapper

    def test_launcher_prefers_checked_terminal_candidate(self) -> None:
        if sys.platform == "win32":
            self.skipTest("POSIX launcher hand-off is not exercisable on Windows")
        launcher, env, open_log, wrapper = self._launcher_fixture()
        fake_terminal = self.root / NASTY_DIR / "Fake Terminal.app"
        fake_terminal.mkdir()
        env["ENCODINGDB_TERMINAL_CANDIDATES"] = str(fake_terminal) + ":/nonexistent/Terminal.app"
        ok = subprocess.run([str(launcher)], env=env, capture_output=True, timeout=30,
                            cwd=str(self.root))
        self.assertEqual(ok.returncode, 0, ok.stderr.decode("utf-8", "replace"))
        logged = open_log.read_text(encoding="utf-8").splitlines()
        def normalize(entry: str) -> str:
            return os.path.realpath(entry) if entry.startswith("/") else entry
        self.assertEqual([normalize(entry) for entry in logged],
                         ["-a", os.path.realpath(str(fake_terminal)),
                          os.path.realpath(str(wrapper))])
    def test_launcher_falls_back_to_default_handler(self) -> None:
        if sys.platform == "win32":
            self.skipTest("POSIX launcher hand-off is not exercisable on Windows")
        launcher, env, open_log, wrapper = self._launcher_fixture()
        env["ENCODINGDB_TERMINAL_CANDIDATES"] = "/nonexistent/Terminal.app"
        ok = subprocess.run([str(launcher)], env=env, capture_output=True, timeout=30,
                            cwd=str(self.root))
        self.assertEqual(ok.returncode, 0, ok.stderr.decode("utf-8", "replace"))
        logged = open_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual([os.path.realpath(entry) for entry in logged],
                         [os.path.realpath(str(wrapper))])

        # Missing wrapper must fail loudly, not vanish into the background.
        wrapper.unlink()
        missing = subprocess.run([str(launcher)], env=env, capture_output=True, timeout=30,
                                 cwd=str(self.root))
        self.assertEqual(missing.returncode, 72)
        self.assertIn("could not open Terminal", missing.stderr.decode("utf-8", "replace"))

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("hdiutil"),
                         "DMG sidecar contract requires macOS hdiutil")
    def test_package_sidecars_and_arch_truthful_dmg_name(self) -> None:
        cli = self.root / "cli"
        cli.write_bytes(macho_stub_bytes(os_version(11), cpu=0x01000007))  # x86_64 header
        cli.chmod(0o755)
        requested = self.root / "EncodingDB-macOS-arm64.dmg"
        self.assertEqual(mcp.main([
            str(cli), str(requested),
            "--work-dir", str(self.root / "work"),
            "--project-version", "9.9.9-test",
            "--sign", "none",
            "--provisional",
        ]), 0)
        dmg = self.root / "EncodingDB-macOS-x86_64.dmg"
        self.assertTrue(dmg.is_file(), "arm64-named DMG must be renamed to the real arch")
        self.assertFalse(requested.exists())
        info = json.loads(dmg.with_name(dmg.name + ".package-info.json").read_text())
        self.assertTrue(info["provisional"])
        self.assertEqual(info["cliSourceSha256"], mcp.sha256_path(cli))
        self.assertEqual(info["cliEmbeddedSha256"], info["cliSourceSha256"])
        self.assertFalse(info["cliBytesChangedByPackaging"])
        self.assertEqual(info["minimumSystemVersion"], "27.0")
        self.assertEqual(info["shortVersionString"], "9.9.9-test")
        self.assertEqual(info["dmg"]["sha256"], mcp.sha256_path(dmg))
        self.assertEqual(info["signing"]["status"], "unsigned (packaging skipped codesign)")
        proof = info["dmg"]["readOnlyMountVerification"]
        self.assertIsNotNone(proof, "read-only mount verification is mandatory")
        self.assertEqual(proof["innerSha256"], info["cliEmbeddedSha256"])
        self.assertIn(dmg.name, dmg.with_name(dmg.name + ".SHA256SUMS").read_text(encoding="utf-8"))

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("hdiutil")
                         and shutil.which("codesign") and shutil.which("cc"),
                         "signing provenance regressions need macOS hdiutil, codesign and cc")
    def test_preserves_existing_inner_signature_and_audited_bytes(self) -> None:
        cli = self._compile_cli("cli_preserved")
        source_sha = mcp.sha256_path(cli)
        self.assertTrue(mcp.inner_signature_valid(cli),
                        "freshly linked macOS binaries carry a valid ad-hoc signature")
        dmg = self.root / "EncodingDB-macOS-arm64.dmg"
        self.assertEqual(mcp.main([
            str(cli), str(dmg), "--work-dir", str(self.root / "work"),
            "--project-version", "9.9.9-test", "--provisional",
        ]), 0)
        info = json.loads(dmg.with_name(dmg.name + ".package-info.json").read_text())
        self.assertEqual(info["signing"]["mode"], "preserved-existing")
        self.assertIn("preserved byte-for-byte", info["signing"]["status"])
        self.assertEqual(info["cliSourceSha256"], source_sha)
        self.assertEqual(info["cliEmbeddedSha256"], source_sha)
        self.assertFalse(info["cliBytesChangedByPackaging"])
        proof = info["dmg"]["readOnlyMountVerification"]
        self.assertTrue(proof["mounted"])
        self.assertTrue(proof["codesignVerified"])
        self.assertEqual(proof["innerSha256"], source_sha)

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("hdiutil")
                         and shutil.which("codesign") and shutil.which("cc"),
                         "signing provenance regressions need macOS hdiutil, codesign and cc")
    def test_resign_transition_records_source_and_embedded_separately(self) -> None:
        cli = self._compile_cli("cli_resigned")
        strip = subprocess.run(["codesign", "--remove-signature", str(cli)],
                               capture_output=True, text=True, timeout=120)
        self.assertEqual(strip.returncode, 0, strip.stderr)
        source_sha = mcp.sha256_path(cli)
        self.assertFalse(mcp.inner_signature_valid(cli))
        dmg = self.root / "EncodingDB-macOS-arm64.dmg"
        self.assertEqual(mcp.main([
            str(cli), str(dmg), "--work-dir", str(self.root / "work"),
            "--project-version", "9.9.9-test", "--sign", "-", "--provisional",
        ]), 0)
        info = json.loads(dmg.with_name(dmg.name + ".package-info.json").read_text())
        self.assertEqual(info["signing"]["mode"], "re-signed-inner")
        self.assertIn("bytes changed", info["signing"]["status"])
        self.assertEqual(info["cliSourceSha256"], source_sha)
        embedded = info["cliEmbeddedSha256"]
        self.assertNotEqual(embedded, source_sha,
                            "ad-hoc signing must legitimately change the binary and say so")
        self.assertTrue(info["cliBytesChangedByPackaging"])
        proof = info["dmg"]["readOnlyMountVerification"]
        self.assertEqual(proof["innerSha256"], embedded,
                         "mounted artifact must match the recorded post-sign identity")
        self.assertTrue(proof["codesignVerified"])

    def _compile_cli(self, name: str) -> Path:
        source = self.root / f"{name}.c"
        source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
        output = self.root / name
        subprocess.run(["cc", str(source), "-o", str(output)], check=True,
                       capture_output=True, timeout=180)
        return output

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("hdiutil"),
                         "DMG mount round trip requires macOS hdiutil")
    def test_cli_runs_from_read_only_dmg_mount(self) -> None:
        cli = self.write_stub_cli(self.root)
        info = self.assemble(cli, self.root / "work")
        app = Path(info["appPath"])
        dmg = self.root / "EncodingDB-provisional.dmg"
        mcp.make_dmg(app, dmg)
        mount = self.root / "mnt"
        attach = subprocess.run(
            ["hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(dmg)],
            capture_output=True, text=True, timeout=180,
        )
        self.assertEqual(attach.returncode, 0, attach.stdout + attach.stderr)
        self.addCleanup(lambda: subprocess.run(
            ["hdiutil", "detach", "-force", str(mount)], capture_output=True, timeout=180))
        volume_app = mount / "EncodingDB.app"
        self.assertTrue((volume_app / "Contents" / "Info.plist").is_file())
        self.assertTrue((mount / "README.txt").is_file())
        self.assertTrue((mount / "Applications").is_symlink())
        wrapper = volume_app / "Contents" / "Resources" / "EncodingDB.command"
        report = self.root / "mounted-report.json"
        env = dict(os.environ)
        env.update({"ENCODINGDB_STUB_REPORT": str(report), "ENCODINGDB_NO_HOLD": "1"})
        script = self.root / "invoke-mount.sh"
        quoted_argument = _shell_quote("ünïcode $'`")
        script.write_text(f'#!/bin/sh\nexec "{wrapper}" {quoted_argument}\n',
                          encoding="utf-8")
        script.chmod(0o755)
        status, output = run_with_pty(script, env, self.root)
        self.assertEqual(status, 0, output)
        self.assertEqual(json.loads(report.read_text())["argv"], ["ünïcode $'`"])
        self.assertTrue(json.loads(report.read_text())["stdinTty"])


if __name__ == "__main__":
    unittest.main()
