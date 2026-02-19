import { NextRequest, NextResponse } from "next/server";

export async function GET(request: NextRequest) {
  const internal = process.env.INTERNAL_API_BASE_URL;
  const isProd = process.env.NODE_ENV === "production";

  // If we have a real backend, proxy the request with all query params
  if (internal) {
    const qs = request.nextUrl.search;
    const url = `${internal}/query${qs}`;
    const res = await fetch(url, { signal: AbortSignal.timeout(10000) });
    if (!res.ok) {
      return NextResponse.json({ error: "Backend error" }, { status: res.status });
    }
    const data = await res.json();
    const response = NextResponse.json(data);
    // Forward X-Total-Count header if present
    const totalCount = res.headers.get("X-Total-Count");
    if (totalCount) {
      response.headers.set("X-Total-Count", totalCount);
      response.headers.set("Access-Control-Expose-Headers", "X-Total-Count");
    }
    return response;
  }

  if (isProd) {
    return NextResponse.json(
      { error: "INTERNAL_API_BASE_URL is not configured" },
      { status: 503 },
    );
  }

  // Mock API for frontend-only development
  const sample = [
    {
      id: "mock-1",
      createdAt: new Date().toISOString(),
      cpuModel: "Intel Core i7-12700K",
      gpuModel: "NVIDIA GeForce RTX 3060",
      ramGB: 32,
      os: "Windows 11",
      codec: "h264_nvenc",
      crf: 22,
      preset: "p6",
      fps: 120.5,
      vmaf: 95.2,
      fileSizeBytes: 85 * 1024 * 1024,
      notes: null,
      ffmpegVersion: "5.1",
      encoderName: "h264_nvenc",
      clientVersion: "1.0.0",
      inputHash: null,
      runMs: 10000,
      status: "accepted",
      samples: 3,
      vmafSamples: 3,
    },
    {
      id: "mock-2",
      createdAt: new Date().toISOString(),
      cpuModel: "Apple M2",
      gpuModel: null,
      ramGB: 16,
      os: "macOS 15",
      codec: "hevc_videotoolbox",
      crf: 26,
      preset: "p6",
      fps: 80.2,
      vmaf: 92.4,
      fileSizeBytes: 70 * 1024 * 1024,
      notes: null,
      ffmpegVersion: "6.0",
      encoderName: "hevc_videotoolbox",
      clientVersion: "1.0.0",
      inputHash: null,
      runMs: 12000,
      status: "accepted",
      samples: 2,
      vmafSamples: 2,
    },
  ];
  const response = NextResponse.json(sample);
  response.headers.set("X-Total-Count", String(sample.length));
  return response;
}
