import { NextResponse } from "next/server";

export function queryMockEnabled(): boolean {
  return String(process.env.ENABLE_QUERY_MOCK || "").trim() === "1";
}

export async function proxyOrMock<T>(
  upstreamPath: string,
  search: string,
  mockFactory: () => T | NextResponse,
): Promise<NextResponse> {
  const internal = process.env.INTERNAL_API_BASE_URL?.replace(/\/+$/, "");
  const mockEnabled = queryMockEnabled();

  if (internal) {
    try {
      const res = await fetch(`${internal}${upstreamPath}${search}`, {
        signal: AbortSignal.timeout(10_000),
      });
      if (!res.ok) {
        if (mockEnabled) {
          const mock = mockFactory();
          return mock instanceof NextResponse ? mock : NextResponse.json(mock);
        }
        return NextResponse.json({ error: "Backend error" }, { status: res.status });
      }
      const data = await res.json();
      const response = NextResponse.json(data);
      const totalCount = res.headers.get("X-Total-Count");
      if (totalCount) {
        response.headers.set("X-Total-Count", totalCount);
        response.headers.set("Access-Control-Expose-Headers", "X-Total-Count");
      }
      return response;
    } catch (error) {
      if (mockEnabled) {
        const mock = mockFactory();
        return mock instanceof NextResponse ? mock : NextResponse.json(mock);
      }
      return NextResponse.json(
        { error: `Upstream request failed: ${error instanceof Error ? error.message : String(error)}` },
        { status: 502 },
      );
    }
  }

  if (mockEnabled) {
    const mock = mockFactory();
    return mock instanceof NextResponse ? mock : NextResponse.json(mock);
  }
  return NextResponse.json(
    { error: "INTERNAL_API_BASE_URL is not configured and ENABLE_QUERY_MOCK is disabled" },
    { status: 503 },
  );
}
