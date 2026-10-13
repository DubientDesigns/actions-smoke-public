import { Suspense } from "react";
import { Attribution, PageHeader } from "@/components/data-display";
import { chainParam, DiscoveryFilters, num, sortParam, str } from "@/components/filters";
import { Guarded } from "@/components/guard";
import { TokenTable } from "@/components/token-table";
import { Card } from "@/components/ui/card";
import { TableSkeleton } from "@/components/ui/skeleton";
import { listTokens } from "@/lib/data";

export const metadata = { title: "Live Discoveries" };

export default function DiscoveriesPage(props: PageProps<"/discoveries">) {
  return (
    <>
      <PageHeader
        title="Live Discoveries"
        description="Newly observed tokens across all four chains. New pools are scanned every 10 minutes and tracked tokens refreshed every 15 minutes, within free-tier rate limits."
      />
      <Card>
        <Suspense fallback={<TableSkeleton rows={12} />}>
          <Guarded>
            <Results searchParams={props.searchParams} />
          </Guarded>
        </Suspense>
      </Card>
      <Attribution />
    </>
  );
}

async function Results({ searchParams }: { searchParams: PageProps<"/discoveries">["searchParams"] }) {
  const sp = await searchParams;
  const filters = {
    chain: chainParam(sp.chain),
    minLiquidity: num(sp.minLiquidity),
    maxAgeHours: num(sp.maxAgeHours) ?? 24,
    sort: sortParam(sp.sort),
    q: str(sp.q)?.slice(0, 64),
    limit: 200,
  };
  const rows = await listTokens(filters);
  return (
    <>
      <DiscoveryFilters
        action="/discoveries"
        values={{
          chain: filters.chain,
          minLiquidity: str(sp.minLiquidity),
          maxAgeHours: String(filters.maxAgeHours),
          sort: filters.sort,
          q: filters.q,
        }}
      />
      <div className="px-4 py-2 text-[11px] text-fg-dim">{rows.length} tokens (max 200 shown)</div>
      <TokenTable rows={rows} empty="No tokens match these filters." />
    </>
  );
}
