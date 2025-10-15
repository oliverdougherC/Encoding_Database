import { NextResponse } from "next/server";

// Simple mock API for frontend-only development.
// If INTERNAL_API_BASE_URL is set, the frontend pages bypass this and hit the server directly.

export async function GET() {
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
  return NextResponse.json(sample);
}


