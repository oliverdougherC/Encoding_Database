export function formatCodecLabel(encoderLower: string): string {
  const suffix = (name: string) => {
    if (name.endsWith("_videotoolbox")) return " VideoToolbox";
    if (name.endsWith("_nvenc")) return " NVENC";
    if (name.endsWith("_qsv")) return " QSV";
    if (name.endsWith("_amf")) return " AMF";
    if (name.endsWith("_vaapi")) return " VAAPI";
    return "";
  };
  const suf = suffix(encoderLower);
  if (encoderLower.includes("av1")) return `AV1${suf}`.trim();
  if (encoderLower.includes("hevc") || encoderLower.includes("h265") || encoderLower.includes("x265")) return `HEVC (H.265)${suf}`.trim();
  if (encoderLower.includes("h264") || encoderLower.includes("x264") || encoderLower.includes("avc")) return `H.264${suf}`.trim();
  if (encoderLower.includes("vp9") || encoderLower.includes("libvpx")) return `VP9${suf}`.trim();
  return encoderLower;
}
