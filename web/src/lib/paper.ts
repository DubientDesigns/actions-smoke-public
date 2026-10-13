// Pure helpers for the paper trading pages (unit-tested).
import { InputError, number } from "@/lib/validate";

export type PaperOrderBody =
  | { kind: "buy"; token_id: number; notional_usd: number; stop_loss_pct: number | null; take_profit: { gain_pct: number; sell_pct: number }[] }
  | { kind: "presale"; presale_id: number; notional_usd: number }
  | { kind: "sell"; position_id: number; sell_fraction: number };

function id(fd: FormData, key: string): number {
  const n = Number(fd.get(key));
  if (!Number.isInteger(n) || n <= 0) throw new InputError(`invalid ${key}`);
  return n;
}

/** "100:50, 300:100" -> [{gain_pct:100, sell_pct:50}, {gain_pct:300, sell_pct:100}] (ascending gains). */
export function parseTakeProfit(raw: string): { gain_pct: number; sell_pct: number }[] {
  const s = raw.trim();
  if (!s) return [];
  const legs = s.split(",").map((part) => {
    const m = /^\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*$/.exec(part);
    if (!m) throw new InputError("take-profit must look like 100:50, 300:100 (gain %: sell %)");
    const gain = Number(m[1]);
    const sell = Number(m[2]);
    if (gain <= 0 || gain > 10_000 || sell <= 0 || sell > 100) throw new InputError("take-profit gain must be 0-10000% and sell 0-100%");
    return { gain_pct: gain, sell_pct: sell };
  });
  if (legs.length > 5) throw new InputError("at most 5 take-profit legs");
  for (let i = 1; i < legs.length; i++) {
    if (legs[i].gain_pct <= legs[i - 1].gain_pct) throw new InputError("take-profit gains must be ascending");
  }
  return legs;
}

export function parsePaperOrder(fd: FormData): PaperOrderBody {
  const kind = String(fd.get("kind") ?? "");
  if (kind === "buy" || kind === "presale") {
    const notional = number(fd, "notional_usd", { min: 1, max: 1_000_000 });
    if (notional === null) throw new InputError("notional_usd is required");
    if (kind === "presale") return { kind, presale_id: id(fd, "presale_id"), notional_usd: notional };
    const sl = number(fd, "stop_loss_pct", { min: 0.1, max: 99 });
    return { kind, token_id: id(fd, "token_id"), notional_usd: notional, stop_loss_pct: sl, take_profit: parseTakeProfit(String(fd.get("take_profit") ?? "")) };
  }
  if (kind === "sell") {
    const pct = number(fd, "sell_pct", { min: 0.01, max: 100 });
    if (pct === null) throw new InputError("sell_pct is required");
    return { kind, position_id: id(fd, "position_id"), sell_fraction: pct / 100 };
  }
  throw new InputError("unknown order kind");
}

export type Mark = { marked_at: string; equity_usd: number | string | null };

/** Drawdown (%) from the running peak of the equity curve; null equity points are skipped, not zero-filled. */
export function drawdownSeries(marks: Mark[]): { t: number; v: number }[] {
  let peak = -Infinity;
  const out: { t: number; v: number }[] = [];
  for (const m of marks) {
    const e = m.equity_usd === null ? NaN : Number(m.equity_usd);
    if (!Number.isFinite(e)) continue;
    peak = Math.max(peak, e);
    out.push({ t: new Date(m.marked_at).getTime(), v: peak > 0 ? (e / peak - 1) * 100 : 0 });
  }
  return out;
}

export const STATUS_TONE: Record<string, "ok" | "warn" | "risk" | "neutral" | "accent" | "unknown"> = {
  open: "accent",
  vesting: "warn",
  closed: "neutral",
  untradeable: "risk",
  written_off: "risk",
  pending: "warn",
  filled: "ok",
  partially_filled: "warn",
  rejected: "risk",
  expired: "unknown",
  cancelled: "neutral",
  enter: "ok",
  reject: "neutral",
  missed: "warn",
};
