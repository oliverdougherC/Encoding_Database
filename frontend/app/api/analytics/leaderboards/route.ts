import { NextRequest } from "next/server";
import { buildMockLeaderboards } from "../../_lib/mockData";
import { proxyOrMock } from "../../_lib/proxy";

export async function GET(request: NextRequest) {
  return proxyOrMock("/analytics/leaderboards", request.nextUrl.search, buildMockLeaderboards);
}
