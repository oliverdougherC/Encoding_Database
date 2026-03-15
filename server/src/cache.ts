export class BoundedTtlCache<Value> {
  private readonly ttlMs: number;
  private readonly maxEntries: number;
  private readonly store = new Map<string, { value: Value; expiresAt: number }>();

  constructor(opts: { ttlMs: number; maxEntries: number }) {
    this.ttlMs = Math.max(1, Math.trunc(opts.ttlMs));
    this.maxEntries = Math.max(1, Math.trunc(opts.maxEntries));
  }

  clear(): void {
    this.store.clear();
  }

  get(key: string, now = Date.now()): Value | undefined {
    const entry = this.store.get(key);
    if (!entry) return undefined;
    if (entry.expiresAt <= now) {
      this.store.delete(key);
      return undefined;
    }
    // Reinsert to keep frequently used keys hot.
    this.store.delete(key);
    this.store.set(key, entry);
    return entry.value;
  }

  set(key: string, value: Value, now = Date.now()): void {
    this.prune(now);
    if (this.store.has(key)) {
      this.store.delete(key);
    }
    this.store.set(key, { value, expiresAt: now + this.ttlMs });
    while (this.store.size > this.maxEntries) {
      const oldest = this.store.keys().next().value;
      if (!oldest) break;
      this.store.delete(oldest);
    }
  }

  size(now = Date.now()): number {
    this.prune(now);
    return this.store.size;
  }

  private prune(now: number): void {
    for (const [key, entry] of this.store.entries()) {
      if (entry.expiresAt <= now) {
        this.store.delete(key);
      }
    }
  }
}
