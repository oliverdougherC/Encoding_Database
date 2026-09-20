import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchWorkbenchPage } from "./api";

describe("fetchWorkbenchPage", () => {
  afterEach(() => {
    delete process.env.INTERNAL_API_BASE_URL;
    vi.restoreAllMocks();
  });

  it("sends My Hardware filters and aggregate sorting before server pagination", async () => {
    process.env.INTERNAL_API_BASE_URL = "http://backend.test";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("[]", {
      status: 200,
      headers: { "X-Total-Count": "3" },
    }));

    await expect(fetchWorkbenchPage({
      page: 2,
      cpu: "Ryzen 7950X",
      gpu: "RTX 4070",
      search: "nvenc",
      preset: "p6",
      sort: "samples",
      dir: "asc",
      encoderType: "hardware",
    })).resolves.toEqual({ rows: [], totalCount: 3 });

    const requested = new URL(String(fetchMock.mock.calls[0][0]));
    expect(requested.pathname).toBe("/corpus");
    expect(Object.fromEntries(requested.searchParams)).toMatchObject({
      limit: "50",
      skip: "50",
      total: "1",
      cpu: "Ryzen 7950X",
      gpu: "RTX 4070",
      search: "nvenc",
      sort: "samples",
      dir: "asc",
    });
    expect(requested.searchParams.has("codecSearch")).toBe(false);
  });
});

describe("fetchCorpusResult", () => {
  afterEach(() => { delete process.env.INTERNAL_API_BASE_URL; vi.restoreAllMocks(); });
  it("looks up the exact encoded aggregate identity without scanning pages", async () => {
    process.env.INTERNAL_API_BASE_URL = "http://backend.test";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ id: "protocol::workload/a" })));
    const { fetchCorpusResult } = await import("./api");
    expect(await fetchCorpusResult("protocol::workload/a")).toEqual({ id: "protocol::workload/a" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toBe("http://backend.test/corpus/protocol%3A%3Aworkload%2Fa");
  });
  it("accepts a still-encoded id from Next page params without double-escaping", async () => {
    process.env.INTERNAL_API_BASE_URL = "http://backend.test";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ id: "ctx::clip::recipe::run::model" })));
    const { fetchCorpusResult } = await import("./api");
    await expect(fetchCorpusResult("ctx%3A%3Aclip%3A%3Arecipe%3A%3Arun%3A%3Amodel")).resolves.toEqual({ id: "ctx::clip::recipe::run::model" });
    expect(String(fetchMock.mock.calls[0][0])).toBe("http://backend.test/corpus/ctx%3A%3Aclip%3A%3Arecipe%3A%3Arun%3A%3Amodel");
  });
  it("treats a withdrawn or missing result as unavailable", async () => {
    process.env.INTERNAL_API_BASE_URL = "http://backend.test";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 404 }));
    const { fetchCorpusResult } = await import("./api");
    expect(await fetchCorpusResult("withdrawn")).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
