# Client release parity gate

For the next candidate, build the macOS app/DMG, Windows GUI and console, and
Linux launcher/archive from the **same clean commit**. Keep the native
`*.release-manifest.json` sidecars and the macOS/Linux `*.package-info.json`
beside the downloaded build artifacts. The native build helpers already emit
these receipts; new sidecars also record `protocol.clientVersion`.

Create a spec on the machine holding all four artifacts:

```json
{
  "expectedSourceRevision": "<reviewed 40-character commit SHA>",
  "expectedProjectVersion": "<candidate project version>",
  "assets": [
    {"role": "macos-dmg", "artifact": "EncodingDB-macOS-arm64.dmg", "releaseManifest": "encodingdb-client-macos.release-manifest.json", "packageInfo": "EncodingDB-macOS-arm64.dmg.package-info.json"},
    {"role": "windows-gui", "artifact": "encodingdb-client-windows.exe", "releaseManifest": "encodingdb-client-windows.exe.release-manifest.json"},
    {"role": "windows-console", "artifact": "encodingdb-client-windows-console.exe", "releaseManifest": "encodingdb-client-windows-console.exe.release-manifest.json"},
    {"role": "linux-archive", "artifact": "encodingdb-client-linux.tar.gz", "releaseManifest": "encodingdb-client-linux.release-manifest.json", "packageInfo": "encodingdb-client-linux.tar.gz.package-info.json"}
  ]
}
```

Paths are relative to the spec. Use the actual sidecar file names emitted by
each build. Then run:

```bash
python scripts/assemble_client_release.py --spec candidate-spec.json --output client-release-manifest.json
```

The command rehashes each artifact, checks wrapper/embedded executable
identity, and rejects mixed source revisions, dirty builds, protocol/client
versions, frozen-suite fingerprints and runtime identities. The output gives
per-asset sizes and hashes for the release page. It does not publish an asset
or replace the platform-specific G01 checks in Linear PLA-90. Promotion also
requires rehashing the public download and matching its bytes to the manifest.
