// Display formatting. Internally everything is UTC; display is Asia/Singapore.
// Unknown values render as an em dash, never as 0.

export const DISPLAY_TZ = "Asia/Singapore";

type Num = number | string | null | undefined;

export function toNum(v: Num): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 });

export function formatUsd(v: Num, opts: { compact?: boolean } = {}): string {
  const n = toNum(v);
  if (n === null) return "—";
  if (opts.compact !== false && Math.abs(n) >= 10_000) return `$${compact.format(n)}`;
  return `$${n.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
}

/** Prices span 1e-12..1e5. Small prices use the 0.0₅123 subscript-zero convention. */
export function formatPrice(v: Num): string {
  const n = toNum(v);
  if (n === null) return "—";
  if (n === 0) return "$0";
  if (n >= 1) return `$${n.toLocaleString("en-US", { maximumFractionDigits: 4 })}`;
  if (n >= 0.0001) return `$${n.toPrecision(4).replace(/0+$/, "")}`;
  const exp = Math.floor(Math.log10(n));
  const zeros = -exp - 1;
  const digits = Math.round(n * 10 ** (-exp + 3)).toString().slice(0, 4).replace(/0+$/, "");
  const sub = String(zeros)
    .split("")
    .map((d) => "₀₁₂₃₄₅₆₇₈₉"[Number(d)])
    .join("");
  return `$0.0${sub}${digits}`;
}

export function formatPct(v: Num, digits = 1): string {
  const n = toNum(v);
  if (n === null) return "—";
  const s = n.toFixed(digits);
  return `${n > 0 ? "+" : ""}${s}%`;
}

export function formatInt(v: Num): string {
  const n = toNum(v);
  return n === null ? "—" : Math.round(n).toLocaleString("en-US");
}

export function formatAge(from: string | Date | null | undefined, now: Date = new Date()): string {
  if (!from) return "—";
  const t = typeof from === "string" ? new Date(from) : from;
  const s = Math.max(0, (now.getTime() - t.getTime()) / 1000);
  if (s < 60) return `${Math.floor(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
}

const sgt = new Intl.DateTimeFormat("en-SG", {
  timeZone: DISPLAY_TZ,
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export function formatSgt(v: string | Date | null | undefined): string {
  if (!v) return "—";
  const d = typeof v === "string" ? new Date(v) : v;
  if (Number.isNaN(d.getTime())) return "—";
  return `${sgt.format(d)} SGT`;
}

export type Freshness = "fresh" | "aging" | "stale" | "unknown";

export function freshness(observedAt: string | null | undefined, slaSeconds: number, now = new Date()): Freshness {
  if (!observedAt) return "unknown";
  const age = (now.getTime() - new Date(observedAt).getTime()) / 1000;
  if (age <= slaSeconds) return "fresh";
  if (age <= slaSeconds * 3) return "aging";
  return "stale";
}

export function shortAddress(a: string): string {
  return a.length > 14 ? `${a.slice(0, 6)}…${a.slice(-4)}` : a;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  return formatAge(new Date(0), new Date(Math.max(0, seconds) * 1000));
}
