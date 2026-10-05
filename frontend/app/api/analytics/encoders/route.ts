import { NextRequest } from "next/server";
import { buildMockCoverage, buildMockEncoders } from "../../_lib/mockData";
import { proxyOrMock } from "../../_lib/proxy";

export async function GET(request: NextRequest) {
  return proxyOrMock("/analytics/encoders", request.nextUrl.search, () => request.nextUrl.searchParams.get("mode") === "coverage" ? buildMockCoverage("encoders") : buildMockEncoders());
}
