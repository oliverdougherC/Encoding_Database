import { NextRequest, NextResponse } from "next/server";
import { MOCK_QUERY_ROWS } from "../_lib/mockData";
import { proxyOrMock } from "../_lib/proxy";

function createMockResponse(searchParams: URLSearchParams) {
  const limit = Number(searchParams.get("limit") || 50);
  const skip = Number(searchParams.get("skip") || 0);
  const sliced = MOCK_QUERY_ROWS.slice(Math.max(0, skip), Math.max(0, skip) + Math.max(1, limit));
  return NextResponse.json(sliced, {
    headers: {
      "X-Total-Count": String(MOCK_QUERY_ROWS.length),
      "Access-Control-Expose-Headers": "X-Total-Count",
    },
  });
}

export async function GET(request: NextRequest) {
  return proxyOrMock("/corpus", request.nextUrl.search, () => createMockResponse(request.nextUrl.searchParams));
}
