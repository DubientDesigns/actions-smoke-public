import { Badge } from "@/components/ui/badge";
import { formatSgt, toNum } from "@/lib/format";
import type { CheckStatus, RiskLevel, ScoreLatest, SecurityCheck, SecurityLatest } from "@/lib/types";
import { cn } from "@/lib/utils";

const RISK_TONE: Record<RiskLevel, "risk" | "warn" | "ok" | "unknown"> = {
  critical: "risk",
  high: "risk",
  medium: "warn",
  low: "ok",
  unknown: "unknown",
};

/** "low" is only ever shown for complete, fresh assessments; anything else says what it is. */
export function RiskBadge({
  level,
  excluded,
  stale,
}: {
  level: RiskLevel | null | undefined;
  excluded?: boolean | null;
  stale?: boolean;
}) {
  if (!level) return <Badge tone="unknown">not assessed</Badge>;
  if (stale) return <Badge tone="unknown">stale</Badge>;
  return (
    <span className="inline-flex gap-1">
      <Badge tone={RISK_TONE[level]}>{level === "unknown" ? "incomplete" : level}</Badge>
      {excluded ? <Badge tone="risk">excluded</Badge> : null}
    </span>
  );
}

export function ScoreBadge({ total }: { total: number | string | null | undefined }) {
  const n = toNum(total);
  if (n === null) return <span className="text-fg-dim">—</span>;
  return <span className={cn("num", n >= 60 ? "text-fg" : "text-fg-muted")}>{n.toFixed(0)}</span>;
}

const CHECK_TONE: Record<CheckStatus, "ok" | "warn" | "risk" | "unknown" | "neutral"> = {
  pass: "ok",
  warn: "warn",
  risk: "risk",
  unknown: "unknown",
  unsupported: "neutral",
};

const ORDER: Record<CheckStatus, number> = { risk: 0, warn: 1, unknown: 2, pass: 3, unsupported: 4 };

function valueText(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "";
  if (typeof v === "object") return Object.keys(v as object).length ? JSON.stringify(v).slice(0, 80) : "";
  return String(v);
}

export function CheckList({ checks }: { checks: SecurityCheck[] }) {
  const sorted = [...checks].sort((a, b) => ORDER[a.status] - ORDER[b.status] || a.label.localeCompare(b.label));
  return (
    <ul className="divide-y divide-border/60">
      {sorted.map((c) => (
        <li key={c.key} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 py-1.5 text-[13px]">
          <Badge tone={CHECK_TONE[c.status]} className="w-[84px] justify-center">
            {c.status}
          </Badge>
          <span className={cn(c.status === "unsupported" && "text-fg-dim")}>{c.label}</span>
          {valueText(c.value) ? <span className="num text-xs text-fg-muted">{valueText(c.value)}</span> : null}
          {c.detail ? <span className="text-xs text-fg-dim">— {c.detail}</span> : null}
        </li>
      ))}
    </ul>
  );
}

export function SecuritySummary({ s }: { s: SecurityLatest }) {
  const counts = s.checks.reduce<Record<string, number>>((acc, c) => ({ ...acc, [c.status]: (acc[c.status] ?? 0) + 1 }), {});
  return (
    <div className="space-y-1 text-[13px]">
      <div className="flex flex-wrap items-center gap-2">
        <RiskBadge level={s.risk_level} excluded={s.hard_excluded} stale={s.is_stale} />
        {s.needs_review ? <Badge tone="warn">needs review</Badge> : null}
        <span className="text-xs text-fg-muted">coverage: {s.coverage}</span>
      </div>
      <div className="text-xs text-fg-dim">
        {(["risk", "warn", "pass", "unknown", "unsupported"] as const).map((k) => `${counts[k] ?? 0} ${k}`).join(" · ")}
      </div>
      <div className="text-xs text-fg-dim">
        Assessed {formatSgt(s.assessed_at)} via {s.source} · valid until {formatSgt(s.valid_until)} · ruleset{" "}
        {s.ruleset_version}
      </div>
    </div>
  );
}

const COMPONENT_LABEL: Record<string, string> = {
  market_structure: "Market structure",
  liquidity: "Liquidity & tradeability",
  security: "Security & tokenomics",
  social: "Social & development",
  data_quality: "Data quality & freshness",
};

export function ScoreBreakdown({ score }: { score: ScoreLatest }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="num text-2xl">{toNum(score.total)?.toFixed(1)}</span>
        <span className="text-xs text-fg-dim">/ 100 · {score.scoring_version} (heuristic weights)</span>
      </div>
      <p className="text-xs text-fg-dim">
        Research-priority ranking, not a prediction of returns. Unknown inputs score zero. Data cutoff{" "}
        {formatSgt(score.data_cutoff_at)}; scored {formatSgt(score.scored_at)}.
      </p>
      {score.risk_flags.length ? (
        <div className="flex flex-wrap gap-1">
          {score.risk_flags.map((f) => (
            <Badge key={f} tone="risk">
              {f}
            </Badge>
          ))}
        </div>
      ) : null}
      {Object.entries(score.components).map(([key, c]) => (
        <details key={key} className="rounded border border-border">
          <summary className="flex cursor-pointer items-center gap-3 px-3 py-2 text-[13px]">
            <span className="flex-1">{COMPONENT_LABEL[key] ?? key}</span>
            <span className="num">
              {c.score.toFixed(1)} / {c.max}
            </span>
            <span className="h-1.5 w-24 overflow-hidden rounded bg-panel-2" aria-hidden>
              <span className="block h-full rounded bg-accent" style={{ width: `${(c.score / c.max) * 100}%` }} />
            </span>
          </summary>
          <div className="space-y-2 border-t border-border px-3 py-2 text-xs">
            {c.evidence.length ? (
              <ul className="space-y-0.5 text-fg-muted">
                {c.evidence.map((e) => (
                  <li key={e}>✓ {e}</li>
                ))}
              </ul>
            ) : null}
            {c.missing.length ? (
              <ul className="space-y-0.5 text-unknown">
                {c.missing.map((m) => (
                  <li key={m}>? {m} (0 points)</li>
                ))}
              </ul>
            ) : null}
          </div>
        </details>
      ))}
    </div>
  );
}
