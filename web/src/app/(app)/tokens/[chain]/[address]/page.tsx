import { notFound } from "next/navigation";
import { Suspense } from "react";
import { Attribution, ChainBadge, Freshness, PageHeader, sourceLabel, Stat } from "@/components/data-display";
import { Guarded, Notice } from "@/components/guard";
import { SeriesChart, type Point } from "@/components/series-chart";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, Td, Th, Tr } from "@/components/ui/table";
import { getToken } from "@/lib/data";
import { formatDuration, formatInt, formatPct, formatPrice, formatSgt, formatUsd, toNum } from "@/lib/format";
import { EXPLORER } from "@/lib/nav";
import type { Snapshot } from "@/lib/types";

export default function TokenPage(props: PageProps<"/tokens/[chain]/[address]">) {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full" />}>
      <Guarded>
        <TokenDetail params={props.params} />
      </Guarded>
    </Suspense>
  );
}

function series(snaps: Snapshot[], poolId: number | null, key: "price_usd" | "liquidity_usd"): Point[] {
  return snaps
    .filter((s) => s.pool_id === poolId)
    .map((s) => ({ t: new Date(s.observed_at).getTime(), v: toNum(s[key]) }))
    .filter((p): p is Point => p.v !== null);
}

async function TokenDetail({ params }: { params: PageProps<"/tokens/[chain]/[address]">["params"] }) {
  const { chain, address } = await params;
  if (!EXPLORER[chain]) notFound();
  const data = await getToken(chain, decodeURIComponent(address));
  if (!data) notFound();
  const { token: t, pools, snapshots } = data;
  return (
    <>
      <PageHeader
        title={`${t.symbol ?? "?"} · ${t.name ?? "Unnamed token"}`}
        right={
          <div className="flex items-center gap-2">
            <ChainBadge chain={t.chain} />
            <a href={EXPLORER[chain].token(t.address)} target="_blank" rel="noreferrer" className="num text-xs text-accent hover:underline">
              {t.address}
            </a>
          </div>
        }
      />
      {t.is_excluded ? <Notice title="Excluded">{t.exclusion_reason ?? "Excluded by a hard rule."}</Notice> : null}
      <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Price" value={formatPrice(t.price_usd)} sub={<Freshness at={t.market_observed_at} source={t.market_source} />} />
        <Stat label="Liquidity (best pool)" value={formatUsd(t.liquidity_usd)} />
        <Stat label="Volume 24h" value={formatUsd(t.volume_h24_usd)} />
        <Stat label="Market cap" value={formatUsd(t.market_cap_usd)} sub={<span className="text-[11px] text-fg-dim">{t.market_cap_usd ? "provider-reported" : "unknown (not inferred from FDV)"}</span>} />
        <Stat label="FDV" value={formatUsd(t.fdv_usd)} />
        <Stat
          label="Discovery latency"
          value={formatDuration(t.discovery_latency_s)}
          sub={<span className="text-[11px] text-fg-dim">first seen {formatSgt(t.first_observed_at)} via {sourceLabel(t.first_source)}</span>}
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader title="Price (best pool)" subtitle="USD, observed values only" />
          <CardBody><SeriesChart points={series(snapshots, t.best_pool_id, "price_usd")} kind="price" label="Price" /></CardBody>
        </Card>
        <Card>
          <CardHeader title="Liquidity (best pool)" subtitle="USD reserve as reported by the provider" />
          <CardBody><SeriesChart points={series(snapshots, t.best_pool_id, "liquidity_usd")} kind="usd" label="Liquidity" /></CardBody>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader title={`Pools (${pools.length})`} subtitle="One token can trade in several pools; tokens are deduplicated by chain + address." />
        <Table>
          <thead>
            <tr>
              <Th>Pool</Th><Th>DEX</Th><Th>Quote</Th><Th className="text-right">Price</Th><Th className="text-right">Liquidity</Th>
              <Th className="text-right">Vol 24h</Th><Th className="text-right">Buys/Sells 24h</Th><Th className="text-right">Δ 24h</Th>
              <Th>Created</Th><Th>Data</Th>
            </tr>
          </thead>
          <tbody>
            {pools.map((p) => (
              <Tr key={p.pool_id}>
                <Td className="num text-xs">{p.address.slice(0, 10)}…</Td>
                <Td>{p.dex ?? "—"}</Td>
                <Td>{p.quote_symbol ?? "—"}</Td>
                <Td className="num text-right">{formatPrice(p.price_usd)}</Td>
                <Td className="num text-right">{formatUsd(p.liquidity_usd)}</Td>
                <Td className="num text-right">{formatUsd(p.volume_h24_usd)}</Td>
                <Td className="num text-right">{formatInt(p.buys_h24)}/{formatInt(p.sells_h24)}</Td>
                <Td className="num text-right">{formatPct(p.price_change_h24)}</Td>
                <Td className="text-xs">{formatSgt(p.pool_created_at)}</Td>
                <Td><Freshness at={p.observed_at} source={p.market_source} /></Td>
              </Tr>
            ))}
          </tbody>
        </Table>
      </Card>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader title="Project links" subtitle="With provenance. Paid listings are promotional, not evidence of quality." />
          <CardBody className="space-y-1.5 text-[13px]">
            {t.links.length === 0 ? <p className="text-fg-dim">No links observed.</p> : null}
            {t.links.map((l) => (
              <div key={l.url} className="flex flex-wrap items-center gap-2">
                <Badge>{l.type}</Badge>
                <a href={l.url} target="_blank" rel="noreferrer nofollow" className="truncate text-accent hover:underline">{l.url}</a>
                <span className="text-[11px] text-fg-dim">{l.source}{l.source.includes("paid") ? " (paid)" : ""} · {formatSgt(l.observed_at)}</span>
              </div>
            ))}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Security" subtitle="Phase 3" />
          <CardBody className="text-[13px] text-fg-muted">
            <Badge tone="unknown">NOT ASSESSED</Badge>
            <p className="mt-2">No security checks have run for this token. This is <strong>unknown</strong>, not a pass.</p>
          </CardBody>
        </Card>
      </div>
      <Attribution />
    </>
  );
}
