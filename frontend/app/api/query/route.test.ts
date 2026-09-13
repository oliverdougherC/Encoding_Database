import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GET } from "./route";

describe("frontend query proxy", () => {
  beforeEach(() => {
    delete process.env.INTERNAL_API_BASE_URL;
    delete process.env.ENABLE_QUERY_MOCK;
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("fails fast when upstream is missing and mocks are disabled", async () => {
    const response = await GET(new NextRequest("http://localhost:3000/api/query"));
    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toMatchObject({
      error: expect.stringContaining("ENABLE_QUERY_MOCK"),
    });
  });

  it("serves mock data only when ENABLE_QUERY_MOCK=1", async () => {
    process.env.ENABLE_QUERY_MOCK = "1";
    const response = await GET(new NextRequest("http://localhost:3000/api/query?limit=1"));
    expect(response.status).toBe(200);
    expect(response.headers.get("X-Total-Count")).toBe("2");
    await expect(response.json()).resolves.toHaveLength(1);
  });

  it("proxies upstream responses and forwards X-Total-Count", async () => {
    process.env.INTERNAL_API_BASE_URL = "http://backend.test";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([{ id: "row-1" }]), {
        status: 200,
        headers: { "X-Total-Count": "7" },
      }),
    );

    const response = await GET(new NextRequest("http://localhost:3000/api/query?limit=1"));
    expect(fetchMock).toHaveBeenCalledWith("http://backend.test/query?limit=1", expect.any(Object));
    expect(response.headers.get("X-Total-Count")).toBe("7");
    await expect(response.json()).resolves.toEqual([{ id: "row-1" }]);
  });

  it("returns a stable 502 without exposing upstream exception details", async () => {
    process.env.INTERNAL_API_BASE_URL = "http://backend.test";
    const internalMessage = "connect ECONNREFUSED 10.0.0.12:3001";
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error(internalMessage));
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);

    const response = await GET(new NextRequest("http://localhost:3000/api/query"));

    expect(response.status).toBe(502);
    const body = await response.json();
    expect(body).toEqual({ error: "Backend unavailable" });
    expect(JSON.stringify(body)).not.toContain(internalMessage);
    expect(consoleError).toHaveBeenCalledWith(
      "Upstream API request failed",
      expect.objectContaining({ upstreamPath: "/query", error: expect.any(Error) }),
    );
  });
});
