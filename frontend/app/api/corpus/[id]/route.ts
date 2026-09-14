import { NextRequest, NextResponse } from "next/server";
import { MOCK_QUERY_ROWS } from "../../_lib/mockData";
import { proxyOrMock } from "../../_lib/proxy";

export async function GET(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return proxyOrMock(`/corpus/${encodeURIComponent(id)}`, "", () => {
    const row = MOCK_QUERY_ROWS.find(row => row.id === id);
    return row ? NextResponse.json(row) : NextResponse.json({ error: "Result not found" }, { status: 404 });
  });
}
