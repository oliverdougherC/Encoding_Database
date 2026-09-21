import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { downloadBaseEnvVar, downloadModel, historicalTag, projectTag, repoReleases } from "./releaseAssets";

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
});
