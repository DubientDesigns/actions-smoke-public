import Link from "next/link";
import { Suspense } from "react";
import { Attribution, Freshness, PageHeader, Stat, StatusBadge } from "@/components/data-display";
import { Guarded } from "@/components/guard";
import { TokenTable } from "@/components/token-table";
import { Card, CardHeader } from "@/components/ui/card";
import { Skeleton, TableSkeleton } from "@/components/ui/skeleton";
import { getOverviewStats, listSources, listTokens } from "@/lib/data";
import { CHAIN_LABEL } from "@/lib/nav";

export const metadata = { title: "Overview" };

export default function OverviewPage() {
  return (
    <>
      <PageHeader
        title="Overview"
        description="Research-priority monitoring of new DEX pools on BNB Chain, Ethereum, Solana and Base. Rankings are not predictions of returns."
      />
      <Suspense fallback={<Skeleton className="h-40 w-full" />}>
        <Guarded>
          <OverviewContent />
        </Guarded>
      </Suspense>
    </>
  );
}

async function OverviewContent() {
  const [stats, sources, latest] = await Promise.all([
    getOverviewStats(),
    listSources(),
    listTokens({ sort: "newest", minLiquidity: 10000, maxAgeHours: 24, limit: 15 }),
  ]);
  const market = sources.filter((s) => s.kind === "market");
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {Object.entries(stats).map(([chain, n]) => (
          <Stat key={chain} label={`${CHAIN_LABEL[chain]} · new tokens 24h`} value={n.toLocaleString()} />
        ))}
      </div>
      <Card>
        <CardHeader
          title="Market data sources"
          right={<Link href="/system" className="text-xs text-accent hover:underline">All sources →</Link>}
        />
        <div className="grid gap-px bg-border sm:grid-cols-2">
          {market.map((s) => (
            <div key={s.slug} className="flex items-center justify-between bg-panel px-4 py-2.5">
              <span className="text-[13px]">{s.name}</span>
              <span className="flex items-center gap-2">
                <Freshness at={s.last_success_at} slaSeconds={s.freshness_sla_seconds} />
                <StatusBadge status={s.consecutive_failures > 0 ? "degraded" : s.last_success_at ? "ok" : "unknown"} />
              </span>
            </div>
          ))}
        </div>
      </Card>
      <Card>
        <CardHeader
          title="Latest discoveries with ≥ $10K liquidity"
          subtitle="Seen in the last 24 hours. Liquidity alone says nothing about safety; security checks arrive in Phase 3."
          right={<Link href="/discoveries" className="text-xs text-accent hover:underline">All discoveries →</Link>}
        />
        <Suspense fallback={<TableSkeleton />}>
          <TokenTable rows={latest} empty="No tokens above the liquidity threshold in the last 24 hours." />
        </Suspense>
      </Card>
      <Attribution />
    </div>
  );
}
