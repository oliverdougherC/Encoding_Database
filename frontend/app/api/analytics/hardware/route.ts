import { NextRequest } from "next/server";
import { buildMockHardware } from "../../_lib/mockData";
import { proxyOrMock } from "../../_lib/proxy";

export async function GET(request: NextRequest) {
  return proxyOrMock("/analytics/hardware", request.nextUrl.search, buildMockHardware);
}
