import { execFile } from 'node:child_process';

let thresholdGb = Math.max(1, Number(process.env.DISK_MIN_FREE_GB || 25));
let diskPath = String(process.env.DISK_PATH || '/');

export let ingestReadOnly = false;
let freeGb = Number.NaN;

function parseDfKB(out: string): { freeBytes: number } | null {
  // Expect lines like: Filesystem 1K-blocks Used Available Use% Mounted on
  // We will pick the line for diskPath (best-effort: last column equals diskPath)
  const lines = out.split('\n').map(l => l.trim()).filter(Boolean);
  if (lines.length < 2) return null;
  // Skip header, find a line whose last column matches diskPath
  for (let i = 1; i < lines.length; i++) {
    const parts = lines[i].split(/\s+/);
    if (parts.length < 6) continue;
    const mount = parts[parts.length - 1];
    if (mount === diskPath) {
      const availableKb = Number(parts[parts.length - 3]);
      if (Number.isFinite(availableKb)) {
        return { freeBytes: availableKb * 1024 };
      }
    }
  }
  // Fallback: try the second line if no exact match
  const parts = lines[1].split(/\s+/);
  if (parts.length >= 6) {
    const availableKb = Number(parts[parts.length - 3]);
    if (Number.isFinite(availableKb)) {
      return { freeBytes: availableKb * 1024 };
    }
  }
  return null;
}

export function getState() {
  return {
    ingestReadOnly,
    freeGB: freeGb,
    thresholdGB: thresholdGb,
    path: diskPath,
  } as const;
}

export function startWatchdog(intervalMs: number = 10_000) {
  tryTick();
  setInterval(tryTick, Math.max(2_000, intervalMs)).unref();
}

function tryTick() {
  execFile('df', ['-k', diskPath], { timeout: 5000 }, (err, stdout) => {
    if (err || !stdout) {
      return; // keep previous state
    }
    const parsed = parseDfKB(stdout);
    if (!parsed) return;
    const gb = parsed.freeBytes / (1024 * 1024 * 1024);
    freeGb = gb;
    const nextReadOnly = gb < thresholdGb;
    ingestReadOnly = nextReadOnly;
  });
}


