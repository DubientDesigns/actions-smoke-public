import { Suspense } from "react";
import { PageHeader } from "@/components/data-display";
import { chainParam, DiscoveryFilters, num, sortParam, str } from "@/components/filters";
import { Guarded } from "@/components/guard";
import { TokenTable } from "@/components/token-table";
import { Card } from "@/components/ui/card";
import { TableSkeleton } from "@/components/ui/skeleton";
import { listTokens } from "@/lib/data";

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
  const filters = { chain: chainParam(sp.chain), minLiquidity: num(sp.minLiquidity), sort: sortParam(sp.sort), q, limit: 100 };
  const rows = await listTokens(filters);
  return (
    <>
      <DiscoveryFilters
        action="/tokens"
        showAge={false}
        values={{ chain: filters.chain, minLiquidity: str(sp.minLiquidity), sort: filters.sort, q }}
      />
      <TokenTable rows={rows} empty={q ? `Nothing found for “${q}”.` : "No tokens observed yet."} />
    </>
  );
}
