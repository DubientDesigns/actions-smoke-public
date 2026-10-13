import { describe, expect, it } from "vitest";
import { drawdownSeries, parsePaperOrder, parseTakeProfit } from "./paper";
import { InputError } from "./validate";

const fd = (o: Record<string, string>) => {
  const f = new FormData();
  Object.entries(o).forEach(([k, v]) => f.set(k, v));
  return f;
};

describe("paper order parsing", () => {
  it("parses a buy with stop-loss and take-profit legs", () => {
    expect(parsePaperOrder(fd({ kind: "buy", token_id: "7", notional_usd: "250", stop_loss_pct: "30", take_profit: "100:50, 300:100" }))).toEqual({
      kind: "buy",
      token_id: 7,
      notional_usd: 250,
      stop_loss_pct: 30,
      take_profit: [
        { gain_pct: 100, sell_pct: 50 },
        { gain_pct: 300, sell_pct: 100 },
      ],
    });
  });
  it("rejects bad input", () => {
    expect(() => parsePaperOrder(fd({ kind: "buy", token_id: "x", notional_usd: "1" }))).toThrow(InputError);
    expect(() => parsePaperOrder(fd({ kind: "buy", token_id: "1", notional_usd: "0" }))).toThrow(InputError);
    expect(() => parsePaperOrder(fd({ kind: "swap" }))).toThrow(InputError);
    expect(() => parseTakeProfit("300:50, 100:50")).toThrow(InputError);
    expect(() => parseTakeProfit("100:150")).toThrow(InputError);
  });
  it("converts a sell percentage to a fraction", () => {
    expect(parsePaperOrder(fd({ kind: "sell", position_id: "3", sell_pct: "25" }))).toEqual({ kind: "sell", position_id: 3, sell_fraction: 0.25 });
  });
});

describe("drawdown", () => {
  it("measures from the running peak and skips unknown points", () => {
    const dd = drawdownSeries([
      { marked_at: "2026-01-01T00:00:00Z", equity_usd: 100 },
      { marked_at: "2026-01-01T01:00:00Z", equity_usd: "120" },
      { marked_at: "2026-01-01T02:00:00Z", equity_usd: null },
      { marked_at: "2026-01-01T03:00:00Z", equity_usd: 90 },
    ]);
    expect(dd.map((p) => Math.round(p.v))).toEqual([0, 0, -25]);
  });
});
