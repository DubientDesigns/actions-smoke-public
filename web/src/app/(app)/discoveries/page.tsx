import { Suspense } from "react";
import { Attribution, PageHeader } from "@/components/data-display";
import { chainParam, DiscoveryFilters, num, riskParam, sortParam, str, toQuery } from "@/components/filters";
import { SavedViews } from "@/components/saved-views";
import { Guarded } from "@/components/guard";
import { TokenTable } from "@/components/token-table";
import { Card } from "@/components/ui/card";
import { TableSkeleton } from "@/components/ui/skeleton";
import { listTokens, requestTime } from "@/lib/data";

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
    minScore: num(sp.minScore),
    risk: riskParam(sp.risk),
    sort: sortParam(sp.sort),
    q: str(sp.q)?.slice(0, 64),
    limit: 200,
  };
  const rows = await listTokens(filters);
  return (
    <>
      <SavedViews page="discoveries" path="/discoveries" query={toQuery(sp)} />
      <DiscoveryFilters
        action="/discoveries"
        values={{
          chain: filters.chain,
          minLiquidity: str(sp.minLiquidity),
          maxAgeHours: String(filters.maxAgeHours),
          minScore: str(sp.minScore),
          risk: filters.risk,
          sort: filters.sort,
          q: filters.q,
        }}
      />
      <div className="px-4 py-2 text-[11px] text-fg-dim">{rows.length} tokens (max 200 shown)</div>
      <TokenTable rows={rows} now={requestTime()} empty="No tokens match these filters." />
    </>
  );
}
