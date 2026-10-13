import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CheckList, RiskBadge, ScoreBreakdown } from "./security";
import type { ScoreLatest, SecurityCheck } from "@/lib/types";

const checks: SecurityCheck[] = [
  { key: "honeypot", label: "Honeypot (sell simulation)", status: "pass", value: false, detail: null, source: "goplus" },
  { key: "sell_tax", label: "Sell tax", status: "risk", value: "45.00", detail: "sell tax 45% >= 30%", source: "goplus" },
  { key: "lp_lock", label: "Liquidity locked or burned", status: "unknown", value: null, detail: "not reported", source: "goplus" },
  { key: "mint_authority", label: "Mint authority", status: "unsupported", value: null, detail: "Solana-specific", source: "goplus" },
];

describe("security components", () => {
  it("orders risks first and never renders unknown as pass", () => {
    const html = renderToStaticMarkup(<CheckList checks={checks} />);
    expect(html.indexOf("Sell tax")).toBeLessThan(html.indexOf("Honeypot"));
    expect(html).toContain(">unknown<");
    expect(html).toContain(">unsupported<");
  });

  it("labels missing and stale assessments explicitly", () => {
    expect(renderToStaticMarkup(<RiskBadge level={null} />)).toContain("not assessed");
    expect(renderToStaticMarkup(<RiskBadge level="low" stale />)).toContain("stale");
    expect(renderToStaticMarkup(<RiskBadge level="unknown" />)).toContain("incomplete");
    expect(renderToStaticMarkup(<RiskBadge level="critical" excluded />)).toContain("excluded");
  });

  it("renders score evidence and zero-point missing items", () => {
    const score: ScoreLatest = {
      score_id: 1, token_id: 1, scoring_version: "token-heuristic-v1", scored_at: "2026-10-13T00:00:00Z",
      data_cutoff_at: "2026-10-13T00:00:00Z", total: "42.5", risk_flags: ["possible_wash_trading"],
      missing_data: [], inputs_hash: "h",
      components: {
        security: { score: 5, max: 25, evidence: ["honeypot: pass (+5.0)"], missing: ["lp_lock: unknown"] },
      },
    };
    const html = renderToStaticMarkup(<ScoreBreakdown score={score} />);
    expect(html).toContain("42.5");
    expect(html).toContain("lp_lock: unknown (0 points)");
    expect(html).toContain("possible_wash_trading");
    expect(html).toContain("not a prediction of returns");
  });
});
