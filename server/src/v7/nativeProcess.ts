import { spawn } from 'node:child_process';
import { AsyncLocalStorage } from 'node:async_hooks';

export const nativeProcessSignal = new AsyncLocalStorage<AbortSignal>();
const active = new Set<() => void>();
export function stopNativeProcesses(): void { for (const stop of active) stop(); }

/** Own a process group so descendants cannot survive deadline, shutdown or a lost lease. */
export async function runNativeProcess(command: string, args: readonly string[], options: {
  timeoutMs?: number; maxBuffer?: number; signal?: AbortSignal;
} = {}): Promise<{stdout: string; stderr: string}> {
  const timeoutMs = options.timeoutMs ?? Number(process.env.ARTIFACT_NATIVE_TIMEOUT_MS || 300_000);
  const limit = options.maxBuffer ?? 10 * 1024 * 1024;
  const signal = options.signal ?? nativeProcessSignal.getStore();
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0 || !Number.isFinite(limit) || limit <= 0) throw new Error('Invalid native process budget');
  if (signal?.aborted) throw new Error('Native process cancelled');
  return await new Promise((resolve, reject) => {
    const nativeArgs = command === 'ffmpeg' && !args.includes('-version') ? ['-nostdin', '-filter_threads', '1', '-filter_complex_threads', '1', ...args.flatMap(arg => arg === '-i' ? ['-threads', '1', arg] : [arg])] : command === 'ffprobe' ? ['-threads', '1', ...args] : [...args];
    const child = spawn(command, nativeArgs, { detached: process.platform !== 'win32', stdio: ['ignore', 'pipe', 'pipe'] });
    const stdout: Buffer[] = [], stderr: Buffer[] = [];
    let size = 0, failure: Error | null = null;
    const stop = (reason = 'Native process cancelled') => {
      failure ??= new Error(reason);
      if (child.pid) {
        try { process.kill(process.platform === 'win32' ? child.pid : -child.pid, 'SIGKILL'); } catch { child.kill('SIGKILL'); }
      }
    };
    const cancel = () => stop();
    active.add(cancel);
    const timer = setTimeout(() => stop(`Native process deadline exceeded (${timeoutMs} ms): ${command}`), timeoutMs);
    timer.unref();
    signal?.addEventListener('abort', cancel, { once: true });
    const collect = (target: Buffer[]) => (chunk: Buffer) => {
      size += chunk.length;
      if (size > limit) { stop(`Native process output exceeded ${limit} bytes: ${command}`); return; }
      target.push(chunk);
    };
    child.stdout.on('data', collect(stdout));
    child.stderr.on('data', collect(stderr));
    child.once('error', error => { failure = error; });
    child.once('close', code => {
      clearTimeout(timer); active.delete(cancel); signal?.removeEventListener('abort', cancel);
      const output = { stdout: Buffer.concat(stdout).toString(), stderr: Buffer.concat(stderr).toString() };
      if (failure) reject(failure);
      else if (code !== 0) reject(new Error(`${command} exited ${code}: ${output.stderr.slice(-4096)}`));
      else resolve(output);
    });
  });
}
