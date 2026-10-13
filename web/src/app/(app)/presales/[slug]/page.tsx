import { notFound } from "next/navigation";
import { Suspense } from "react";
import { ChainBadge, PageHeader } from "@/components/data-display";
import { str } from "@/components/filters";
import { Field, fieldCls, FormError, Options, Submit } from "@/components/form";
import { Guarded } from "@/components/guard";
import { VerificationBadge } from "@/components/presale";
import { ScoreBreakdown } from "@/components/security";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Empty, Table, Td, Th, Tr } from "@/components/ui/table";
import { addPresaleClaim, updatePresaleStatus } from "@/lib/actions/curation";
import { getPresale, isOwner } from "@/lib/data";
import { formatSgt, formatUsd } from "@/lib/format";
import { CHAIN_BY_ID } from "@/lib/nav";

const STATUSES = ["rumoured", "announced", "upcoming", "live", "ended", "cancelled", "tge_done", "unknown"] as const;
const VERIFICATION = ["unverified", "official_source_seen", "partially_verified", "disputed", "red_flag"] as const;

export default function PresalePage(props: PageProps<"/presales/[slug]">) {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full" />}>
      <Guarded>
        <PresaleDetail params={props.params} searchParams={props.searchParams} />
      </Guarded>
    </Suspense>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex gap-3 border-b border-border/60 py-1.5 text-[13px]">
      <span className="w-40 shrink-0 text-fg-dim">{k}</span>
      <span className="min-w-0 break-words">{v ?? <span className="text-unknown">unknown</span>}</span>
    </div>
  );
}

async function PresaleDetail({
  params,
  searchParams,
}: {
  params: PageProps<"/presales/[slug]">["params"];
  searchParams: PageProps<"/presales/[slug]">["searchParams"];
}) {
  const [{ slug }, sp] = await Promise.all([params, searchParams]);
  const [data, owner] = await Promise.all([getPresale(slug), isOwner()]);
  if (!data) notFound();
  const { presale: p, claims, score } = data;
  const vesting = p.vesting_terms as Record<string, number | null> | null;
  return (
    <>
      <PageHeader
        title={p.project_name}
        description="All values below are claims. The source column says where each came from."
        right={
          <div className="flex items-center gap-2">
            {p.chain_id ? <ChainBadge chain={CHAIN_BY_ID[p.chain_id]} /> : null}
            <Badge>{p.status.replaceAll("_", " ")}</Badge>
            <VerificationBadge v={p.verification_status} />
          </div>
        }
      />
      <FormError error={str(sp.error)} />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader title="Sale details (claimed)" subtitle={`Added by ${p.created_by} · ${formatSgt(p.created_at)}`} />
          <CardBody>
            <Row k="Official website" v={p.official_website ? <a className="text-accent hover:underline" href={p.official_website} target="_blank" rel="noreferrer nofollow">{p.official_website}</a> : null} />
            <Row k="Platform" v={p.platform} />
            <Row k="Sale type" v={p.sale_type} />
            <Row k="Sale window" v={p.sale_start_at || p.sale_end_at ? `${formatSgt(p.sale_start_at)} → ${formatSgt(p.sale_end_at)}` : null} />
            <Row k="TGE" v={p.tge_at ? formatSgt(p.tge_at) : null} />
            <Row k="Sale price" v={p.sale_price_usd !== null ? formatUsd(p.sale_price_usd, { compact: false }) : null} />
            <Row k="Claimed valuation" v={p.claimed_valuation_usd !== null ? formatUsd(p.claimed_valuation_usd) : null} />
            <Row k="Hard cap" v={p.hard_cap_usd !== null ? formatUsd(p.hard_cap_usd) : null} />
            <Row k="Min investment" v={p.min_investment_usd !== null ? formatUsd(p.min_investment_usd) : null} />
            <Row k="Vesting" v={vesting ? `TGE ${vesting.tge_unlock_pct ?? "?"}% · cliff ${vesting.cliff_months ?? "?"}m · vesting ${vesting.vesting_months ?? "?"}m` : null} />
            <Row k="Lock-up" v={p.lockup_terms} />
            <Row k="Audit claims" v={p.audit_claims.length ? p.audit_claims.join("; ") : null} />
            <Row k="Team" v={p.team_info} />
            <Row k="Sources" v={p.source_urls.length ? p.source_urls.map((u) => <a key={u} href={u} className="block text-accent hover:underline" target="_blank" rel="noreferrer nofollow">{u}</a>) : null} />
            {p.notes ? <Row k="Notes" v={p.notes} /> : null}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Presale score" subtitle="Heuristic v1 — documentation and checkability, not quality" />
          <CardBody>{score ? <ScoreBreakdown score={score} /> : <p className="text-[13px] text-fg-muted">Not scored yet (runs every 30 minutes).</p>}</CardBody>
        </Card>
      </div>
      <Card className="mt-4">
        <CardHeader title={`Claims (${claims.length})`} subtitle="Individual statements with their source; mark contradictions so they lower the score." />
        {claims.length === 0 ? <Empty>No claims recorded.</Empty> : (
          <Table>
            <thead><tr><Th>Field</Th><Th>Value</Th><Th>Source</Th><Th>Kind</Th><Th>Verification</Th><Th>Recorded</Th></tr></thead>
            <tbody>
              {claims.map((c) => (
                <Tr key={c.id}>
                  <Td className="num text-xs">{c.field}</Td>
                  <Td>{typeof c.value === "string" ? c.value : JSON.stringify(c.value)}</Td>
                  <Td className="max-w-64 truncate text-xs">{c.source_url ? <a className="text-accent hover:underline" href={c.source_url} target="_blank" rel="noreferrer nofollow">{c.source_url}</a> : "—"}</Td>
                  <Td>{c.source_kind}</Td>
                  <Td><Badge tone={c.verification === "contradicted" ? "risk" : c.verification === "unverified" ? "unknown" : "accent"}>{c.verification}</Badge></Td>
                  <Td className="text-xs text-fg-dim">{formatSgt(c.observed_at)}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
        {owner ? (
          <form action={addPresaleClaim} className="grid gap-3 border-t border-border p-4 md:grid-cols-6">
            <input type="hidden" name="slug" value={p.slug} />
            <input type="hidden" name="presale_id" value={p.id} />
            <Field label="Field *"><input name="field" required maxLength={60} placeholder="hard_cap_usd" className={fieldCls} /></Field>
            <Field label="Value *" className="md:col-span-2"><input name="value" required maxLength={500} className={fieldCls} /></Field>
            <Field label="Source URL"><input name="source_url" type="url" className={fieldCls} /></Field>
            <Field label="Kind"><select name="source_kind" className={fieldCls}><Options values={["official", "launchpad", "third_party", "social", "manual"]} /></select></Field>
            <Field label="Verification"><select name="verification" className={fieldCls}><Options values={["unverified", "consistent", "contradicted", "verified_onchain"]} /></select></Field>
            <div className="md:col-span-6"><Submit>Add claim</Submit></div>
          </form>
        ) : null}
      </Card>
      {owner ? (
        <Card className="mt-4">
          <CardHeader title="Update status" />
          <form action={updatePresaleStatus} className="flex flex-wrap items-end gap-3 p-4">
            <input type="hidden" name="slug" value={p.slug} />
            <Field label="Status"><select name="status" defaultValue={p.status} className={fieldCls}><Options values={STATUSES} /></select></Field>
            <Field label="Verification"><select name="verification_status" defaultValue={p.verification_status} className={fieldCls}><Options values={VERIFICATION} /></select></Field>
            <Submit>Update</Submit>
          </form>
        </Card>
      ) : null}
    </>
  );
}
