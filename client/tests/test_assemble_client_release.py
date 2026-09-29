import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.assemble_client_release import assemble


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class AssembleClientReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.entries = []
        for role, platform, name in (
            ("macos-dmg", "mac", "EncodingDB-macOS-arm64.dmg"),
            ("windows-gui", "win", "encodingdb-client-windows.exe"),
            ("windows-console", "win", "encodingdb-client-windows-console.exe"),
            ("linux-archive", "linux", "encodingdb-client-linux.tar.gz"),
        ):
            data = role.encode()
            artifact = self.root / name
            artifact.write_bytes(data)
            binary_sha = digest((role + "-binary").encode()) if role in {"macos-dmg", "linux-archive"} else digest(data)
            manifest = {
                "schemaVersion": 1, "source": {"revision": "a" * 40, "trackedChanges": False},
                "projectVersion": "1.3.0-rc.6", "platform": platform,
                "protocol": {"clientVersion": "client/0.3.4", "benchmarkProtocolVersion": "7.1",
                             "minimumClientVersion": "client/0.3.0"},
                "suite": {"suiteVersion": "encodingdb-test-suite-v1", "manifestVersion": 2,
                          "suiteFingerprint": "f" * 64, "isFrozen": True},
                "runtime": {"fingerprint": platform + "-runtime"},
                "artifact": {"fileName": name, "sha256": binary_sha, "byteSize": len(data),
                             "executableIdentity": {
                                 "format": {"mac": "Mach-O", "win": "PE", "linux": "ELF"}[platform],
                                 "architecture": "arm64" if platform == "mac" else "x86_64",
                             }},
            }
            manifest_path = self.root / f"{name}.release-manifest.json"
            manifest_path.write_text(json.dumps(manifest))
            entry = {"role": role, "artifact": name, "releaseManifest": manifest_path.name}
            if role in {"macos-dmg", "linux-archive"}:
                wrapper = {"fileName": name, "sha256": digest(data), "byteSize": len(data)}
                if role == "macos-dmg":
                    wrapper["readOnlyMountVerification"] = {"mounted": True, "innerSha256": binary_sha}
                    package = {"provisional": False, "source": manifest["source"], "dmg": wrapper,
                               "cliEmbeddedSha256": binary_sha, "cliBytesChangedByPackaging": False,
                               "minimumSystemVersion": "27.0"}
                else:
                    wrapper["members"] = [{"sha256": binary_sha}]
                    package = {"provisional": False, "source": manifest["source"], "archive": wrapper,
                               "verification": {"verified": True}}
                package_path = self.root / f"{name}.package-info.json"
                package_path.write_text(json.dumps(package))
                entry["packageInfo"] = package_path.name
            self.entries.append(entry)

    def spec(self):
        return {"expectedSourceRevision": "a" * 40, "expectedProjectVersion": "1.3.0-rc.6",
                "assets": self.entries}

    def test_assembles_four_verified_assets_from_one_clean_identity(self):
        release = assemble(self.spec(), self.root)
        self.assertEqual(release["sourceRevision"], "a" * 40)
        self.assertEqual(release["clientVersion"], "client/0.3.4")
        self.assertEqual(len(release["assets"]), 4)
        self.assertEqual(release["lifecycle"], {
            "builtFromReviewedSource": True,
            "nativeAcceptance": "not_certified",
            "published": False,
            "independentRedownloadVerified": False,
        })
        self.assertEqual({asset["role"] for asset in release["assets"]},
                         {"macos-dmg", "windows-gui", "windows-console", "linux-archive"})
        support = {asset["role"]: asset["support"] for asset in release["assets"]}
        self.assertEqual(support["macos-dmg"], {
            "operatingSystem": "macOS", "architecture": "arm64", "minimumVersion": "27.0"})
        self.assertEqual(support["windows-gui"], {
            "operatingSystem": "Windows", "architecture": "x86_64", "supportedVersion": "11",
            "otherVersions": "unverified"})
        self.assertEqual(support["linux-archive"], {
            "operatingSystem": "Ubuntu Linux", "architecture": "x86_64",
            "supportedVersion": "24.04", "otherDistributions": "unverified"})

    def test_rejects_tampered_asset_and_mixed_revision(self):
        (self.root / "encodingdb-client-windows.exe").write_bytes(b"different")
        with self.assertRaisesRegex(ValueError, "file bytes differ"):
            assemble(self.spec(), self.root)
        (self.root / "encodingdb-client-windows.exe").write_bytes(b"windows-gui")
        path = self.root / "encodingdb-client-windows.exe.release-manifest.json"
        receipt = json.loads(path.read_text())
        receipt["source"]["revision"] = "b" * 40
        path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, "differs from the reviewed source/version"):
            assemble(self.spec(), self.root)

    def test_rejects_missing_package_proof_and_dirty_source(self):
        path = self.root / "EncodingDB-macOS-arm64.dmg.package-info.json"
        package = json.loads(path.read_text())
        package["dmg"]["readOnlyMountVerification"] = None
        path.write_text(json.dumps(package))
        with self.assertRaisesRegex(ValueError, "read-only mount verification"):
            assemble(self.spec(), self.root)
        package["dmg"]["readOnlyMountVerification"] = {"mounted": True, "innerSha256": package["cliEmbeddedSha256"]}
        path.write_text(json.dumps(package))
        path = self.root / "encodingdb-client-linux.tar.gz.release-manifest.json"
        receipt = json.loads(path.read_text())
        receipt["source"]["trackedChanges"] = True
        path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, "clean committed source"):
            assemble(self.spec(), self.root)

    def test_rejects_different_runtime_for_windows_pair(self):
        path = self.root / "encodingdb-client-windows-console.exe.release-manifest.json"
        receipt = json.loads(path.read_text())
        receipt["runtime"]["fingerprint"] = "other-runtime"
        path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, "different win runtime identities"):
            assemble(self.spec(), self.root)

    def test_rejects_architecture_or_macos_floor_missing_from_native_receipts(self):
        path = self.root / "encodingdb-client-windows.exe.release-manifest.json"
        receipt = json.loads(path.read_text())
        receipt["artifact"]["executableIdentity"]["architecture"] = "arm64"
        path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, "supported architecture"):
            assemble(self.spec(), self.root)
        receipt["artifact"]["executableIdentity"]["architecture"] = "x86_64"
        path.write_text(json.dumps(receipt))
        package_path = self.root / "EncodingDB-macOS-arm64.dmg.package-info.json"
        package = json.loads(package_path.read_text())
        package.pop("minimumSystemVersion")
        package_path.write_text(json.dumps(package))
        with self.assertRaisesRegex(ValueError, "minimum OS version"):
            assemble(self.spec(), self.root)
        package["minimumSystemVersion"] = "26.0"
        package_path.write_text(json.dumps(package))
        with self.assertRaisesRegex(ValueError, "qualified runtime floor"):
            assemble(self.spec(), self.root)


if __name__ == "__main__":
    unittest.main()
