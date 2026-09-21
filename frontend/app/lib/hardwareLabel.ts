// Real hardware names over sentinels. Corpus rows may carry placeholder GPU
// strings ("not-applicable") or none at all - which does NOT prove CPU-only
// encoding (e.g. VideoToolbox on Apple silicon reports no discrete GPU).
// Normalize to "no named GPU" once; callers show the CPU name or "GPU not reported".
const GPU_SENTINELS: Record<string, true> = {
  none: true,
  null: true,
  "n/a": true,
  na: true,
  "no-gpu": true,
  "not applicable": true,
  "not-applicable": true,
  not_applicable: true,
};

export function realGpu(gpuModel: string | null | undefined): string | null {
  const text = gpuModel?.trim();
  if (!text) return null;
  return GPU_SENTINELS[text.toLowerCase()] === true ? null : text;
}
