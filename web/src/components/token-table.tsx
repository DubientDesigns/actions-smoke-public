import Link from "next/link";
import { ChainBadge, Freshness } from "@/components/data-display";
import { Badge } from "@/components/ui/badge";
import { Empty, Table, Td, Th, Tr } from "@/components/ui/table";
import { formatAge, formatInt, formatPct, formatPrice, formatUsd, shortAddress, toNum } from "@/lib/format";
import type { TokenOverview } from "@/lib/types";
import { cn } from "@/lib/utils";

export function TokenTable({ rows, empty }: { rows: TokenOverview[]; empty: string }) {
  if (rows.length === 0) return <Empty>{empty}</Empty>;
  return (
    <Table>
      <thead>
        <tr>
          <Th>Token</Th>
          <Th>Chain</Th>
          <Th className="text-right">Price</Th>
          <Th className="text-right">Liquidity</Th>
          <Th className="text-right">Vol 1h</Th>
          <Th className="text-right">Vol 24h</Th>
          <Th className="text-right">Buys/Sells 24h</Th>
          <Th className="text-right">Δ 24h</Th>
          <Th className="text-right">FDV</Th>
          <Th className="text-right">Pool age</Th>
          <Th className="text-right">Seen</Th>
          <Th>Market data</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((t) => {
          const chg = toNum(t.price_change_h24);
          return (
            <Tr key={t.token_id}>
              <Td className="max-w-56">
                <Link href={`/tokens/${t.chain}/${t.address}`} className="block truncate font-medium hover:text-accent">
                  {t.symbol ?? "?"} <span className="font-normal text-fg-dim">{t.name ?? ""}</span>
                </Link>
                <span className="num text-[11px] text-fg-dim">{shortAddress(t.address)}</span>
                {t.pool_count > 1 ? <Badge className="ml-1">{t.pool_count} pools</Badge> : null}
              </Td>
              <Td><ChainBadge chain={t.chain} /></Td>
              <Td className="num text-right">{formatPrice(t.price_usd)}</Td>
              <Td className="num text-right">{formatUsd(t.liquidity_usd)}</Td>
              <Td className="num text-right">{formatUsd(t.volume_h1_usd)}</Td>
              <Td className="num text-right">{formatUsd(t.volume_h24_usd)}</Td>
              <Td className="num text-right">
                {formatInt(t.buys_h24)}/{formatInt(t.sells_h24)}
              </Td>
              <Td className={cn("num text-right", chg !== null && (chg >= 0 ? "text-ok" : "text-risk"))}>
                {formatPct(t.price_change_h24)}
              </Td>
              <Td className="num text-right">{formatUsd(t.fdv_usd)}</Td>
              <Td className="num text-right">{formatAge(t.earliest_pool_created_at)}</Td>
              <Td className="num text-right" title={t.first_source ?? undefined}>{formatAge(t.first_observed_at)}</Td>
              <Td><Freshness at={t.market_observed_at} source={t.market_source} /></Td>
            </Tr>
          );
        })}
      </tbody>
    </Table>
  );
}
