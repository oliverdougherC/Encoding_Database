import { NextRequest } from "next/server";
import { buildMockEncoders } from "../../_lib/mockData";
import { proxyOrMock } from "../../_lib/proxy";

export async function GET(request: NextRequest) {
  return proxyOrMock("/analytics/encoders", request.nextUrl.search, buildMockEncoders);
}
