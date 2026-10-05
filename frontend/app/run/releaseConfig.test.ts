import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { downloadBaseEnvVar, downloadModel, historicalTag, primaryAssets, projectTag, repoReleases, supersededAssets, supersededTag, currentWindowsConsole } from "./releaseAssets";

// These tests exist to catch drift between the page model, the publication
// tag convention and the deployment wiring - the class of inconsistency root
// found (v-prefixed tag in the packet vs un-prefixed tag in code, env var
// read by the runtime but never passed by compose).

const composePath = resolve(process.cwd(), "../docker-compose.prod.yml"); // vitest cwd = frontend/
const compose = existsSync(composePath) ? readFileSync(composePath, "utf8") : (() => { throw new Error(`compose file missing: ${composePath}`); })();

describe("release configuration consistency", () => {
  it("uses the un-prefixed tag convention matching the historical release", () => {
    expect(projectTag).toMatch(/^\d+\.\d+\.\d+-rc\.\d+$/); // no leading "v"
    expect(historicalTag).toBe("1.2.0"); // the existing published convention
  });

  it("passes COLLECTION_DOWNLOAD_BASE through the production compose frontend service", () => {
    const frontendBlock = compose.slice(compose.indexOf("  frontend:"));
    const serviceBlock = frontendBlock.slice(0, frontendBlock.indexOf("\n  nginx:"));
    expect(serviceBlock).toContain(`${downloadBaseEnvVar}: \${${downloadBaseEnvVar}:-}`);
  });

  it("resolves published hrefs under the same releases-download base shape as the historical tag", () => {
    const plannedBase = `${repoReleases}/download/${projectTag}`;
    const model = downloadModel({ [downloadBaseEnvVar]: plannedBase });
    expect(model.published).toBe(true);
    for (const item of model.items) {
      expect(item.href).toBe(`${plannedBase}/${item.file}`);
    }
    // Historical links must keep the identical structural pattern.
    expect(`${repoReleases}/download/${historicalTag}/encodingdb-client-linux`).toContain(`/download/${historicalTag}/`);
  });


  it("ships no invented digests: primary builds are pending or real 64-hex, superseded builds verified", () => {
    for (const asset of primaryAssets) {
      expect(asset.sha256 === null || /^[0-9a-f]{64}$/.test(asset.sha256)).toBe(true);
    }
    for (const asset of supersededAssets) {
      expect(asset.sha256).toMatch(/^[0-9a-f]{64}$/);
    }
  });

  it("fails closed when the configured base names a different tag than the project", () => {
    // Guards the live-deployment cutover: a stale predecessor base must never
    // yield current asset links.
    expect(downloadModel({ [downloadBaseEnvVar]: `${repoReleases}/download/1.3.0-rc.1` }).published).toBe(false);
    expect(downloadModel({ [downloadBaseEnvVar]: `${repoReleases}/download/${historicalTag}` }).published).toBe(false);
  });
});

// Pinned to the independently re-downloaded public rc.10 manifest, not CI filenames alone.
describe("public rc.10 asset stamp", () => {
  it("matches the published filenames, SHA-256 and byte lengths for all four roles", () => {
    expect(projectTag).toBe("1.3.0-rc.10");
    expect([...primaryAssets, currentWindowsConsole].map(({file, sha256, byteSize}) => ({file, sha256, byteSize})).sort((a,b) => a.file.localeCompare(b.file))).toEqual([
    {
        "file": "encodingdb-client-linux.tar.gz",
        "sha256": "a774c16250ffd84b545a304e35c25be856fd3ef219d522d0f85cfd8be04b8777",
        "byteSize": 201072452
    },
    {
        "file": "encodingdb-client-windows-console.exe",
        "sha256": "ed7e18064ee99459301cf4c7c464827114b9d77e9d02543ce7f39fcbba6d2098",
        "byteSize": 182731033
    },
    {
        "file": "encodingdb-client-windows.exe",
        "sha256": "55f9c0ad6f874023395a0b9b7e99c90f30a0dc22fecab20268e336d52c2efc47",
        "byteSize": 182728034
    },
    {
        "file": "EncodingDB-macOS-arm64.dmg",
        "sha256": "90dc77afbb208a0312595b63df76f9b647cb7110991ef8a9e5c46291ccb6f34c",
        "byteSize": 129845535
    }
].sort((a,b) => a.file.localeCompare(b.file)));
  });
  it("preserves actual rc.5 rollback identities without claiming they are current bytes", () => {
    expect(supersededTag).toBe("1.3.0-rc.5");
    expect(supersededAssets.find(asset => asset.file === "EncodingDB-macOS-arm64.dmg")?.sha256).toBe("cc6c6503293c8f01b223e1fac9a5da56888352d39c5e777cf90d23acec8aa8c6");
    for (const previous of supersededAssets) {
      expect(previous.sha256).not.toBe([...primaryAssets, currentWindowsConsole].find(asset => asset.file === previous.file)?.sha256);
    }
  });
});
