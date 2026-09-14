import { spawn } from 'node:child_process';
import crypto from 'node:crypto';
import path from 'node:path';
import { constants, createReadStream } from 'node:fs';
import { access, realpath, stat } from 'node:fs/promises';
import { AsyncLocalStorage } from 'node:async_hooks';

export async function sha256InstalledFile(filePath: string): Promise<string> {
  const hash = crypto.createHash('sha256');
  for await (const chunk of createReadStream(filePath)) hash.update(chunk);
  return hash.digest('hex');
}
const installedTools = new Map<string, Promise<{ path: string; sha256: string; byteSize: number; signature: string }>>();
function signature(value: Awaited<ReturnType<typeof stat>>): string { return `${value.dev}:${value.ino}:${value.size}:${value.mtimeMs}:${value.ctimeMs}`; }
export async function installedMediaTool(command: 'ffmpeg' | 'ffprobe'): Promise<{ path: string; sha256: string; byteSize: number }> {
  let pending = installedTools.get(command);
  if (!pending) {
    pending = (async () => {
      for (const directory of (process.env.PATH ?? '').split(path.delimiter).filter(Boolean)) {
        const candidate = path.resolve(directory, command + (process.platform === 'win32' ? '.exe' : ''));
        try {
          await access(candidate, constants.X_OK);
          const resolved = await realpath(candidate);
          const before = await stat(resolved);
          if (!before.isFile()) continue;
          const sha256 = await sha256InstalledFile(resolved);
          if (signature(before) !== signature(await stat(resolved))) throw new Error(`Installed ${command} changed while hashing`);
          return { path: resolved, sha256, byteSize: before.size, signature: signature(before) };
        } catch (error) {
          if (['ENOENT', 'EACCES', 'ENOTDIR'].includes(String((error as NodeJS.ErrnoException).code))) continue;
          throw error;
        }
      }
      throw new Error(`Installed ${command} executable was not found on PATH`);
    })();
    installedTools.set(command, pending);
  }
  const installed = await pending;
  if (signature(await stat(installed.path)) !== installed.signature) throw new Error(`Installed ${command} changed; restart the worker before analysis`);
  return { path: installed.path, sha256: installed.sha256, byteSize: installed.byteSize };
}

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
  const executable = command === 'ffmpeg' || command === 'ffprobe' ? (await installedMediaTool(command)).path : command;
  if (signal?.aborted) throw new Error('Native process cancelled');
  return await new Promise((resolve, reject) => {
    const nativeArgs = command === 'ffmpeg' && !args.includes('-version') ? ['-nostdin', '-filter_threads', '1', '-filter_complex_threads', '1', ...args.flatMap(arg => arg === '-i' ? ['-threads', '1', arg] : [arg])] : command === 'ffprobe' ? ['-threads', '1', ...args] : [...args];
    const child = spawn(executable, nativeArgs, { detached: process.platform !== 'win32', stdio: ['ignore', 'pipe', 'pipe'] });
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
