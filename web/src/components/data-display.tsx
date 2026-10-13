import { Badge } from "@/components/ui/badge";
import { formatAge, formatSgt, freshness } from "@/lib/format";
import { CHAIN_LABEL } from "@/lib/nav";
import { cn } from "@/lib/utils";

export function ChainBadge({ chain }: { chain: string }) {
  return <Badge className="font-mono">{CHAIN_LABEL[chain] ?? chain}</Badge>;
}

const SOURCE_LABEL: Record<string, string> = {
  geckoterminal: "GeckoTerminal",
  dexscreener: "DEX Screener",
  goplus: "GoPlus",
  manual: "Manual",
};

export function sourceLabel(slug: string | null | undefined) {
  if (!slug) return "unknown source";
  return SOURCE_LABEL[slug] ?? slug;
}

/** Every important metric shows where it came from and how old it is. */
export function Freshness({
  at,
  source,
  slaSeconds = 1800,
  className,
}: {
  at: string | null | undefined;
  source?: string | null;
  slaSeconds?: number;
  className?: string;
}) {
  const f = freshness(at, slaSeconds);
  const tone = { fresh: "text-fg-dim", aging: "text-warn", stale: "text-risk", unknown: "text-unknown" }[f];
  return (
    <span className={cn("text-[11px] whitespace-nowrap", tone, className)} title={`${formatSgt(at)} · ${sourceLabel(source)}`}>
      {at ? `${formatAge(at)} ago` : "no data"}
      {source ? ` · ${sourceLabel(source)}` : ""}
      {f === "stale" ? " · stale" : ""}
    </span>
  );
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const tone =
    status === "ok" || status === "success"
      ? "ok"
      : status === "degraded" || status === "partial"
        ? "warn"
        : status === "down" || status === "failed"
          ? "risk"
          : "unknown";
  return <Badge tone={tone}>{status ?? "unknown"}</Badge>;
}

export function PageHeader({ title, description, right }: { title: string; description?: string; right?: React.ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
        {description ? <p className="mt-0.5 max-w-3xl text-[13px] text-fg-muted">{description}</p> : null}
      </div>
      {right}
    </div>
  );
}

export function Attribution() {
  return (
    <p className="mt-3 text-[11px] text-fg-dim">
      Market data:{" "}
      <a className="underline hover:text-fg-muted" href="https://www.geckoterminal.com" target="_blank" rel="noreferrer">
        GeckoTerminal
      </a>{" "}
      and{" "}
      <a className="underline hover:text-fg-muted" href="https://dexscreener.com" target="_blank" rel="noreferrer">
        DEX Screener
      </a>
      . Coverage of new pools is incomplete. Market cap is shown only when a provider reports a value distinct from FDV.
    </p>
  );
}

export function Stat({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border bg-panel px-4 py-3">
      <div className="text-[11px] uppercase tracking-wider text-fg-dim">{label}</div>
      <div className="num mt-1 text-xl">{value}</div>
      {sub ? <div className="mt-0.5">{sub}</div> : null}
    </div>
  );
}
