import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET } from "./route";

afterEach(() => { delete process.env.INTERNAL_API_BASE_URL; delete process.env.ENABLE_QUERY_MOCK; vi.restoreAllMocks(); });

describe("GET exact corpus result", () => {
  it("forwards the exact encoded identity and preserves withdrawal status", async () => {
    process.env.INTERNAL_API_BASE_URL = "http://backend.test";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 404 }));
    const response = await GET(new NextRequest("http://frontend.test/api/corpus/proto%3A%3Aclip"), { params: Promise.resolve({ id: "proto::clip" }) });
    expect(response.status).toBe(404);
    expect(String(fetchMock.mock.calls[0][0])).toBe("http://backend.test/corpus/proto%3A%3Aclip");
  });
  it("does not fabricate a result when the backend is unavailable", async () => {
    process.env.INTERNAL_API_BASE_URL = "http://backend.test";
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 503 }));
    expect((await GET(new NextRequest("http://frontend.test/api/corpus/id"), { params: Promise.resolve({ id: "id" }) })).status).toBe(503);
  });
});
