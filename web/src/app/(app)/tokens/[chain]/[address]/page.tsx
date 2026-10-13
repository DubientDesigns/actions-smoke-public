import { notFound } from "next/navigation";
import { Suspense } from "react";
import { Attribution, ChainBadge, Freshness, PageHeader, sourceLabel, Stat } from "@/components/data-display";
import { Guarded, Notice } from "@/components/guard";
import { SeriesChart, type Point } from "@/components/series-chart";
import { CheckList, ScoreBreakdown, SecuritySummary } from "@/components/security";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, Td, Th, Tr } from "@/components/ui/table";
import { getToken, isOwner, listResearch } from "@/lib/data";
import { requestResearch } from "@/lib/actions/research";
import { FormError, FormNotice } from "@/components/form";
import { PriorityBadge, StatusPill } from "@/components/research";
import { PaperBuyCard } from "@/components/paper";
import { str } from "@/components/filters";
import Link from "next/link";
import { formatDuration, formatInt, formatPct, formatPrice, formatSgt, formatUsd, toNum } from "@/lib/format";
import { EXPLORER } from "@/lib/nav";
import type { Snapshot } from "@/lib/types";

export default function TokenPage(props: PageProps<"/tokens/[chain]/[address]">) {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full" />}>
      <Guarded>
        <TokenDetail params={props.params} searchParams={props.searchParams} />
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

async function TokenDetail({
  params,
  searchParams,
}: {
  params: PageProps<"/tokens/[chain]/[address]">["params"];
  searchParams: PageProps<"/tokens/[chain]/[address]">["searchParams"];
}) {
  const [{ chain, address }, sp] = await Promise.all([params, searchParams]);
  if (!EXPLORER[chain]) notFound();
  const data = await getToken(chain, decodeURIComponent(address));
  if (!data) notFound();
  const { token: t, pools, snapshots, security, score } = data;
  const [reports, owner] = await Promise.all([listResearch({ tokenId: t.token_id }), isOwner()]);
  const here = `/tokens/${chain}/${address}`;
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
      <FormError error={str(sp.error)} />
      <FormNotice notice={str(sp.notice)} />
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
          <CardHeader title="Research-priority score" subtitle="Heuristic v1 — evidence and missing data per category" />
          <CardBody>
            {score ? (
              <ScoreBreakdown score={score} />
            ) : (
              <p className="text-[13px] text-fg-muted">
                Not scored. Scores are computed for tracked tokens whose best pool meets the liquidity threshold.
              </p>
            )}
          </CardBody>
        </Card>
      </div>
      <Card className="mt-4">
        <CardHeader
          title="AI research"
          subtitle="Generated only from this page's evidence; claims cite evidence ids."
          right={
            owner ? (
              <form action={requestResearch}>
                <input type="hidden" name="token_id" value={t.token_id} />
                <input type="hidden" name="back" value={here} />
                <button className="rounded border border-accent/60 px-2 py-0.5 text-xs text-accent hover:bg-accent/10">Request report</button>
              </form>
            ) : null
          }
        />
        <CardBody className="text-[13px]">
          {reports.length === 0 ? (
            <p className="text-fg-muted">No report yet. Reports are generated automatically for tokens above the score threshold, within the AI budget.</p>
          ) : (
            <ul className="space-y-1">
              {reports.slice(0, 5).map((r) => (
                <li key={r.id} className="flex flex-wrap items-center gap-2">
                  <Link href={`/research/${r.id}`} className="text-accent hover:underline">Report #{r.id}</Link>
                  <StatusPill s={r.status} />
                  <PriorityBadge p={r.research_priority} />
                  <span className="text-xs text-fg-dim">{formatSgt(r.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
      {owner ? <PaperBuyCard tokenId={t.token_id} back={here} /> : null}
      <Card className="mt-4">
        <CardHeader title="Security checks" subtitle="GoPlus heuristics — not an audit. Unknown ≠ pass." />
        <CardBody>
          {security ? (
            <div className="space-y-3">
              <SecuritySummary s={security} />
              <CheckList checks={security.checks} />
            </div>
          ) : (
            <p className="text-[13px] text-fg-muted">
              <Badge tone="unknown">NOT ASSESSED</Badge> No security checks have run for this token yet. This is{" "}
              <strong>unknown</strong>, not a pass.
            </p>
          )}
        </CardBody>
      </Card>
      <Attribution />
    </>
  );
}
