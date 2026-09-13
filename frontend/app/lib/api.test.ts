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
