export const CODEC_COLORS: Record<string, string> = {
  av1: "#52b788",
  h264: "#6C8FD5",
  hevc: "#9693CC",
  vp9: "#d4a843",
  other: "#e07a5f",
};

export function codecColorKey(codec: string): string {
  const c = codec.toLowerCase();
  if (c.includes("av1")) return "av1";
  if (c.includes("265") || c.includes("hevc") || c.includes("x265")) return "hevc";
  if (c.includes("264") || c.includes("avc") || c.includes("x264")) return "h264";
  if (c.includes("vp9") || c.includes("libvpx")) return "vp9";
  return "other";
}
