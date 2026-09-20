import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import RunPage from "./page";
import { collectionAssets, downloadModel } from "./releaseAssets";

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

describe("downloadModel", () => {
  it("keeps collection hrefs null while assets are staged but unpublished", () => {
    const model = downloadModel({});
    expect(model.published).toBe(false);
    for (const item of model.items) {
      expect(item.href).toBeNull();
      expect(item.sha256).toMatch(/^[0-9a-f]{64}$/);
    }
  });

  it("links collection assets under the configured base once published", () => {
    const model = downloadModel({ COLLECTION_DOWNLOAD_BASE: "https://example.invalid/releases/download/1.3.0-rc.1/" });
    expect(model.published).toBe(true);
    expect(model.items.map((i) => i.href)).toEqual([
      "https://example.invalid/releases/download/1.3.0-rc.1/encodingdb-client-windows.exe",
      "https://example.invalid/releases/download/1.3.0-rc.1/encodingdb-client-windows-console.exe",
      "https://example.invalid/releases/download/1.3.0-rc.1/encodingdb-client-linux",
      "https://example.invalid/releases/download/1.3.0-rc.1/encodingdb-client-macos",
    ]);
  });
});

describe("RunPage", () => {
  it("stages the 1.3.0-rc.1 builds without claiming they are downloadable, and keeps source commands", () => {
    vi.stubEnv("COLLECTION_DOWNLOAD_BASE", "");
    render(<RunPage />);
    expect(screen.getByText(/not downloadable here until they are published/)).toBeInTheDocument();
    expect(screen.getByText(/staged for publication, checksums verified/)).toBeInTheDocument();
    for (const asset of collectionAssets) {
      expect(screen.getByText(asset.file)).toBeInTheDocument();
      expect(screen.getByText(new RegExp(asset.sha256.slice(0, 16)))).toBeInTheDocument();
    }
    expect(document.querySelector("a[href*='1.3.0-rc.1/encodingdb-client']")).toBeNull();
    expect(screen.getAllByText(/pending publication/)).toHaveLength(collectionAssets.length);
    // Historical 1.2.0 assets stay reachable, explicitly flagged as non-submitting.
    expect(screen.getByRole("link", { name: "Linux (0.2.0)" })).toHaveAttribute("href", expect.stringContaining("/1.2.0/encodingdb-client-linux"));
    expect(screen.getByText(/cannot submit to the current server/)).toBeInTheDocument();
    // Stale support claims are gone; real signing/support facts are present.
    expect(document.body).not.toHaveTextContent("requires Rosetta");
    expect(document.body).toHaveTextContent("no Rosetta");
    expect(document.body).toHaveTextContent("not notarized");
    // Source flow unchanged.
    expect(screen.getByText("python -m client --resume-campaign CAMPAIGN_ID --submit")).toBeInTheDocument();
    expect(screen.getByText(/python -m client --upload-only/)).toBeInTheDocument();
    expect(document.body).toHaveTextContent("--campaign full");
    expect(document.body).not.toHaveTextContent("--suite-mode");
    expect(document.body).toHaveTextContent("An upload receipt means analysis is pending");
  });

  it("advertises the published collection downloads once the deployment sets the base", () => {
    vi.stubEnv("COLLECTION_DOWNLOAD_BASE", "https://github.com/oliverdougherC/Encoding_Database/releases/download/1.3.0-rc.1");
    render(<RunPage />);
    expect(screen.getByText(/Collection update published/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Windows GUI" })).toHaveAttribute("href", "https://github.com/oliverdougherC/Encoding_Database/releases/download/1.3.0-rc.1/encodingdb-client-windows.exe");
    expect(screen.getByRole("link", { name: "macOS (Apple Silicon)" })).toHaveAttribute("href", expect.stringContaining("/1.3.0-rc.1/encodingdb-client-macos"));
    expect(screen.queryByText(/pending publication/)).toBeNull();
  });
});
