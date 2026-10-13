import { Suspense } from "react";
import { PageHeader } from "@/components/data-display";
import { chainParam, DiscoveryFilters, num, riskParam, sortParam, str, toQuery } from "@/components/filters";
import { SavedViews } from "@/components/saved-views";
import { Guarded } from "@/components/guard";
import { TokenTable } from "@/components/token-table";
import { Card } from "@/components/ui/card";
import { TableSkeleton } from "@/components/ui/skeleton";
import { listTokens, requestTime } from "@/lib/data";

export const metadata = { title: "Token Explorer" };

export default function TokensPage(props: PageProps<"/tokens">) {
  return (
    <>
      <PageHeader
        title="Token Explorer"
        description="Search every token the platform has observed by symbol, name or exact contract/mint address."
      />
      <Card>
        <Suspense fallback={<TableSkeleton rows={12} />}>
          <Guarded>
            <Results searchParams={props.searchParams} />
          </Guarded>
        </Suspense>
      </Card>
    </>
  );
}

async function Results({ searchParams }: { searchParams: PageProps<"/tokens">["searchParams"] }) {
  const sp = await searchParams;
  const q = str(sp.q)?.slice(0, 64);
  const filters = {
    chain: chainParam(sp.chain),
    minLiquidity: num(sp.minLiquidity),
    minScore: num(sp.minScore),
    risk: riskParam(sp.risk),
    sort: sortParam(sp.sort),
    q,
    limit: 100,
  };
  const rows = await listTokens(filters);
  return (
    <>
      <SavedViews page="tokens" path="/tokens" query={toQuery(sp)} />
      <DiscoveryFilters
        action="/tokens"
        showAge={false}
        values={{
          chain: filters.chain,
          minLiquidity: str(sp.minLiquidity),
          minScore: str(sp.minScore),
          risk: filters.risk,
          sort: filters.sort,
          q,
        }}
      />
      <TokenTable rows={rows} now={requestTime()} empty={q ? `Nothing found for “${q}”.` : "No tokens observed yet."} />
    </>
  );
}
