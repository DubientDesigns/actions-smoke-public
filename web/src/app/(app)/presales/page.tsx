import Link from "next/link";
import { Suspense } from "react";
import { ChainBadge, PageHeader } from "@/components/data-display";
import { str } from "@/components/filters";
import { Field, fieldCls, FormError, FormPanel, Options, Submit } from "@/components/form";
import { Guarded } from "@/components/guard";
import { VerificationBadge } from "@/components/presale";
import { ScoreBadge } from "@/components/security";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { TableSkeleton } from "@/components/ui/skeleton";
import { Empty, Table, Td, Th, Tr } from "@/components/ui/table";
import { createPresale } from "@/lib/actions/curation";
import { isOwner, listPresales } from "@/lib/data";
import { formatSgt, formatUsd } from "@/lib/format";
import { CHAIN_BY_ID } from "@/lib/nav";

export const metadata = { title: "Presale Radar" };

const STATUSES = ["rumoured", "announced", "upcoming", "live", "ended", "cancelled", "tge_done", "unknown"] as const;
const VERIFICATION = ["unverified", "official_source_seen", "partially_verified", "disputed", "red_flag"] as const;

export default function PresalesPage(props: PageProps<"/presales">) {
  return (
    <>
      <PageHeader
        title="Presale Radar"
        description="Manually curated watchlist of upcoming sales, kept separate from trading tokens. Every figure is a claim with a source; verification describes where a claim came from, never that a sale is legitimate or safe."
      />
      <Suspense fallback={<TableSkeleton rows={10} />}>
        <Guarded>
          <PresalesContent searchParams={props.searchParams} />
        </Guarded>
      </Suspense>
    </>
  );
}

async function PresalesContent({ searchParams }: { searchParams: PageProps<"/presales">["searchParams"] }) {
  const sp = await searchParams;
  const status = STATUSES.includes(str(sp.status) as (typeof STATUSES)[number]) ? str(sp.status) : undefined;
  const [rows, owner] = await Promise.all([listPresales(status), isOwner()]);
  return (
    <div className="space-y-4">
      <FormError error={str(sp.error)} />
      {owner ? (
        <FormPanel title="Add presale">
          <form action={createPresale} className="grid gap-3 md:grid-cols-3">
            <Field label="Project name *"><input name="project_name" required maxLength={120} className={fieldCls} /></Field>
            <Field label="Official website"><input name="official_website" type="url" className={fieldCls} /></Field>
            <Field label="Chain">
              <select name="chain" className={fieldCls}>
                <option value="">Unknown</option>
                <Options values={["bsc", "ethereum", "solana", "base"]} />
              </select>
            </Field>
            <Field label="Platform / launchpad"><input name="platform" maxLength={120} className={fieldCls} /></Field>
            <Field label="Platform URL"><input name="platform_url" type="url" className={fieldCls} /></Field>
            <Field label="Sale type">
              <select name="sale_type" className={fieldCls} defaultValue="unknown"><Options values={["public", "private", "whitelist", "fair_launch", "unknown"]} /></select>
            </Field>
            <Field label="Status"><select name="status" className={fieldCls} defaultValue="announced"><Options values={STATUSES} /></select></Field>
            <Field label="Sale start (SGT)"><input name="sale_start_at" type="datetime-local" className={fieldCls} /></Field>
            <Field label="Sale end (SGT)"><input name="sale_end_at" type="datetime-local" className={fieldCls} /></Field>
            <Field label="TGE (SGT)"><input name="tge_at" type="datetime-local" className={fieldCls} /></Field>
            <Field label="Sale price (USD)"><input name="sale_price_usd" type="number" step="any" min={0} className={fieldCls} /></Field>
            <Field label="Claimed valuation (USD)"><input name="claimed_valuation_usd" type="number" step="any" min={0} className={fieldCls} /></Field>
            <Field label="Hard cap (USD)"><input name="hard_cap_usd" type="number" step="any" min={0} className={fieldCls} /></Field>
            <Field label="Min investment (USD)"><input name="min_investment_usd" type="number" step="any" min={0} className={fieldCls} /></Field>
            <Field label="TGE unlock %"><input name="tge_unlock_pct" type="number" step="any" min={0} max={100} className={fieldCls} /></Field>
            <Field label="Cliff (months)"><input name="cliff_months" type="number" min={0} max={120} className={fieldCls} /></Field>
            <Field label="Vesting (months)"><input name="vesting_months" type="number" min={0} max={120} className={fieldCls} /></Field>
            <Field label="Lock-up terms"><input name="lockup_terms" maxLength={500} className={fieldCls} /></Field>
            <Field label="Audit claim"><input name="audit_claims" maxLength={300} placeholder="e.g. AuditCo (claimed)" className={fieldCls} /></Field>
            <Field label="Team info" className="md:col-span-2"><input name="team_info" maxLength={1000} className={fieldCls} /></Field>
            <Field label="Verification">
              <select name="verification_status" className={fieldCls} defaultValue="unverified"><Options values={VERIFICATION} /></select>
            </Field>
            <Field label="Source URL 1"><input name="source_url_1" type="url" className={fieldCls} /></Field>
            <Field label="Source URL 2"><input name="source_url_2" type="url" className={fieldCls} /></Field>
            <Field label="Notes" className="md:col-span-3"><textarea name="notes" maxLength={2000} rows={2} className={fieldCls} /></Field>
            <div className="md:col-span-3"><Submit>Save presale</Submit></div>
          </form>
        </FormPanel>
      ) : null}
      <Card>
        <CardHeader
          title="Watchlist"
          subtitle="Score = presale heuristic v1 (documentation, verification, tokenomics, risk controls). It measures how checkable a sale is, not whether it is a good investment."
          right={
            <form action="/presales" method="get" className="flex items-center gap-1 text-xs">
              <select name="status" defaultValue={status ?? ""} className="rounded border border-border-strong bg-panel-2 px-2 py-0.5">
                <option value="">All statuses</option>
                <Options values={STATUSES} />
              </select>
              <button className="rounded border border-border-strong px-2 py-0.5 hover:border-accent">Filter</button>
            </form>
          }
        />
        {rows.length === 0 ? (
          <Empty>No presales yet. There is no reliable free presale feed, so entries are added manually from official sources.</Empty>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Project</Th><Th>Chain</Th><Th>Status</Th><Th>Verification</Th><Th className="text-right">Score</Th>
                <Th>Sale window</Th><Th className="text-right">Claimed valuation</Th><Th className="text-right">Hard cap</Th><Th>Flags</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <Tr key={p.id}>
                  <Td><Link href={`/presales/${p.slug}`} className="font-medium hover:text-accent">{p.project_name}</Link></Td>
                  <Td>{p.chain_id ? <ChainBadge chain={CHAIN_BY_ID[p.chain_id]} /> : <span className="text-fg-dim">—</span>}</Td>
                  <Td><Badge>{p.status.replaceAll("_", " ")}</Badge></Td>
                  <Td><VerificationBadge v={p.verification_status} /></Td>
                  <Td className="text-right"><ScoreBadge total={p.score?.total} /></Td>
                  <Td className="text-xs">{formatSgt(p.sale_start_at)} → {formatSgt(p.sale_end_at)}</Td>
                  <Td className="num text-right">{formatUsd(p.claimed_valuation_usd)}</Td>
                  <Td className="num text-right">{formatUsd(p.hard_cap_usd)}</Td>
                  <Td>
                    <div className="flex flex-wrap gap-1">
                      {(p.score?.risk_flags ?? []).map((f) => <Badge key={f} tone="risk">{f}</Badge>)}
                    </div>
                  </Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
