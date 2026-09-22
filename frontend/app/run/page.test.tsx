import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import RunPage from "./page";
import { downloadBaseEnvVar, downloadModel, historicalTag, primaryAssets, projectTag, repoReleases, supersededAssets, supersededTag } from "./releaseAssets";

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

describe("downloadModel", () => {
  it("keeps primary hrefs null while assets are staged but unpublished", () => {
    const model = downloadModel({});
    expect(model.published).toBe(false);
    for (const item of model.items) {
      expect(item.href).toBeNull();
    }
  });

  it("never resolves staged current-tag names onto the deployed superseded base", () => {
    // The live deployment still points COLLECTION_DOWNLOAD_BASE at the
    // published predecessor path; concatenating current file names onto it
    // would 404 or, worse, serve superseded bytes under new names.
    const model = downloadModel({ [downloadBaseEnvVar]: `${repoReleases}/download/${supersededTag}` });
    expect(model.published).toBe(false);
    for (const item of model.items) expect(item.href).toBeNull();
  });

  it("links primary assets only under the exact current-tag base", () => {
    const plannedBase = `${repoReleases}/download/${projectTag}`;
    const model = downloadModel({ [downloadBaseEnvVar]: `${plannedBase}/` });
    expect(model.published).toBe(true);
    expect(model.items.map((i) => i.href)).toEqual(
      primaryAssets.map((a) => `${plannedBase}/${a.file}`),
    );
  });
});

describe("RunPage", () => {
  it("stages the packaged builds with verified digests but no download links until publication", () => {
    vi.stubEnv("COLLECTION_DOWNLOAD_BASE", "");
    render(<RunPage />);
    for (const asset of primaryAssets) {
      expect(screen.getAllByText(asset.file).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/pending publication/).length).toBeGreaterThan(0);
      if (asset.sha256) {
        expect(screen.getAllByText(new RegExp(asset.sha256)).length).toBeGreaterThan(0);
      }
    }
    expect(screen.getByRole("heading", { level: 1, name: "Contribute your results." })).toBeInTheDocument();
    expect(document.querySelector(`a[href*='download/${projectTag}/']`)).toBeNull();
    expect(document.querySelector(`a[href*='releases/tag/${projectTag}']`)).toBeNull();
    // Guided contract from the client brief: sweep sizes, one-time consent,
    // automatic submit, resumability.
    expect(screen.getAllByText(/Small, Medium, Large, or Full/).length).toBeGreaterThan(0);
    expect(screen.getByText(/submit automatically/)).toBeInTheDocument();
    // macOS floor/notarization honesty is visible, not buried.
    expect(screen.getAllByText(/requires macOS 27 or later/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/not notarized/).length).toBeGreaterThan(0);
    // Launch guidance follows current Apple/MS guidance; no bypass automation.
    expect(screen.getByText(/run \.\/start\.sh/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Apple’s instructions/ })).toHaveAttribute("href", "https://support.apple.com/en-us/102445");
    expect(screen.getAllByText(/Open Anyway/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/right-click/)).toBeNull();
    expect(screen.queryByText(/allow it past/)).toBeNull();
    // Source/CLI exists only as the optional advanced path.
  });

  it("does not activate current downloads when the environment still names the superseded base", () => {
    vi.stubEnv("COLLECTION_DOWNLOAD_BASE", `${repoReleases}/download/${supersededTag}`);
    render(<RunPage />);
    expect(screen.getByText(/is being prepared/)).toBeInTheDocument();
    expect(document.querySelector(`a[href*='download/${projectTag}/']`)).toBeNull();
    expect(screen.getAllByText(/pending publication/).length).toBeGreaterThan(0);
  });

  it("activates the primary downloads and release-notes link once the deployment names the current tag", () => {
    const plannedBase = `${repoReleases}/download/${projectTag}`;
    vi.stubEnv("COLLECTION_DOWNLOAD_BASE", plannedBase);
    render(<RunPage />);
    expect(screen.getByText(/is published/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download for macOS (Apple Silicon)" })).toHaveAttribute("href", `${plannedBase}/EncodingDB-macOS-arm64.dmg`);
    expect(screen.getByRole("link", { name: "Download for Windows (GUI)" })).toHaveAttribute("href", `${plannedBase}/encodingdb-client-windows.exe`);
    expect(screen.getByRole("link", { name: "Download for Linux (x86-64)" })).toHaveAttribute("href", `${plannedBase}/encodingdb-client-linux.tar.gz`);
    expect(screen.getByRole("link", { name: new RegExp(`Release notes, checksums, and build evidence`) })).toHaveAttribute("href", `${repoReleases}/tag/${projectTag}`);
    expect(screen.queryByText(/pending publication/)).toBeNull();
  });

  it("documents superseded and historical builds without presenting them as recommended", () => {
    render(<RunPage />);
    // The superseded release keeps its verified digests and links under its
    // own published tag. macOS/Linux digests intentionally equal the primary
    // ones (byte-identical republish), so match with getAllByText.
    for (const asset of supersededAssets) {
      expect(asset.sha256).toMatch(/^[0-9a-f]{64}$/);
      expect(screen.getAllByText(new RegExp(String(asset.sha256).slice(0, 16))).length).toBeGreaterThan(0);
      expect(document.querySelector(`a[href='${repoReleases}/download/${supersededTag}/${asset.file}']`)).not.toBeNull();
    }
    expect(screen.getByText(/bare extensionless executable/)).toBeInTheDocument();
    // 1.2.0 stays honest about incompatibility.
    expect(screen.getByText(/cannot submit to the server version shipped with this page/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Linux (0.2.0)" })).toHaveAttribute("href", expect.stringContaining(`/download/${historicalTag}/encodingdb-client-linux`));
    expect(screen.getByRole("link", { name: /1.2.0 requirements/ })).toHaveAttribute("href", `${repoReleases}/tag/${historicalTag}`);
  });
});
