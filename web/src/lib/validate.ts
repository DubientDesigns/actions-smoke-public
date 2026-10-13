// Server-side input validation for curation forms. Never trust the browser.

export class InputError extends Error {}

export function text(fd: FormData, key: string, { max = 500, required = false } = {}): string | null {
  const v = String(fd.get(key) ?? "").trim();
  if (!v) {
    if (required) throw new InputError(`${key} is required`);
    return null;
  }
  if (v.length > max) throw new InputError(`${key} is too long (max ${max})`);
  return v;
}

export function oneOf<T extends string>(fd: FormData, key: string, allowed: readonly T[], fallback: T): T {
  const v = String(fd.get(key) ?? "");
  return (allowed as readonly string[]).includes(v) ? (v as T) : fallback;
}

export function url(fd: FormData, key: string, opts: { required?: boolean } = {}): string | null {
  const v = text(fd, key, { max: 2048, required: opts.required });
  if (v === null) return null;
  let u: URL;
  try {
    u = new URL(v);
  } catch {
    throw new InputError(`${key} is not a valid URL`);
  }
  if (u.protocol !== "https:" && u.protocol !== "http:") throw new InputError(`${key} must be http(s)`);
  return u.toString();
}

export function number(fd: FormData, key: string, { min = 0, max = 1e15 } = {}): number | null {
  const raw = String(fd.get(key) ?? "").trim();
  if (!raw) return null;
  const n = Number(raw);
  if (!Number.isFinite(n) || n < min || n > max) throw new InputError(`${key} must be a number between ${min} and ${max}`);
  return n;
}

/** <input type="datetime-local"> has no zone; the UI is Asia/Singapore (UTC+8, no DST). */
export function sgtDateTime(fd: FormData, key: string, { required = false } = {}): string | null {
  const raw = String(fd.get(key) ?? "").trim();
  if (!raw) {
    if (required) throw new InputError(`${key} is required`);
    return null;
  }
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(raw)) throw new InputError(`${key} is not a valid date/time`);
  const d = new Date(`${raw.length === 16 ? `${raw}:00` : raw}+08:00`);
  if (Number.isNaN(d.getTime())) throw new InputError(`${key} is not a valid date/time`);
  return d.toISOString();
}

export const CHAINS = ["bsc", "ethereum", "solana", "base"] as const;
export const CHAIN_IDS: Record<(typeof CHAINS)[number], number> = { bsc: 1, ethereum: 2, solana: 3, base: 4 };

const EVM = /^0x[0-9a-fA-F]{40}$/;
const SOL = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;

export function address(chain: (typeof CHAINS)[number], raw: string | null): string | null {
  if (!raw) return null;
  if (chain === "solana") {
    if (!SOL.test(raw)) throw new InputError("not a valid Solana address");
    return raw;
  }
  if (!EVM.test(raw)) throw new InputError("not a valid EVM address");
  return raw.toLowerCase();
}

export function slugify(name: string): string {
  return name
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
}
