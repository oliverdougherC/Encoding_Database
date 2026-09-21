// Real hardware names over sentinels. Some corpus rows carry placeholder GPU
// strings ("not-applicable") for CPU-only runs; `gpuModel || cpuModel` then
// displays the placeholder instead of the actual CPU name. Normalize once,
// shared by the results table, detail dialog, compare panel, and hardware index.
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
