import Link from "next/link";
import { Suspense } from "react";
import { ChainBadge, PageHeader, Stat } from "@/components/data-display";
import { str } from "@/components/filters";
import { FormError, FormNotice, Options } from "@/components/form";
import { Guarded } from "@/components/guard";
import { PriorityBadge, StatusPill } from "@/components/research";
import { Card, CardHeader } from "@/components/ui/card";
import { TableSkeleton } from "@/components/ui/skeleton";
import { Empty, Table, Td, Th, Tr } from "@/components/ui/table";
import { getSetting, listResearch, listSources, listSpend } from "@/lib/data";
import { formatAge, formatSgt, toNum } from "@/lib/format";

export const metadata = { title: "AI Research Reports" };

const STATUSES = ["queued", "generating", "complete", "failed", "rejected_schema", "skipped_budget"] as const;
const PRIORITIES = ["high", "medium", "low", "avoid", "insufficient_data"] as const;

export default function ResearchPage(props: PageProps<"/research">) {
  return (
    <>
      <PageHeader
        title="AI Research Reports"
        description="Structured notes written by Claude from a deterministic evidence bundle, only for tokens that pass the filters (or that an owner requests). Every claim cites evidence; reports that cite missing evidence or numbers not in the evidence are rejected. AI output can still be wrong — verify against the cited sources."
      />
      <Suspense fallback={<TableSkeleton rows={10} />}>
        <Guarded>
          <Content searchParams={props.searchParams} />
        </Guarded>
      </Suspense>
    </>
  );
}

type AiBudget = { enabled?: boolean; model?: string; monthly_usd_cap?: number; daily_request_cap?: number; min_score?: number };

async function Content({ searchParams }: { searchParams: PageProps<"/research">["searchParams"] }) {
  const sp = await searchParams;
  const status = STATUSES.includes(str(sp.status) as (typeof STATUSES)[number]) ? str(sp.status) : undefined;
  const priority = PRIORITIES.includes(str(sp.priority) as (typeof PRIORITIES)[number]) ? str(sp.priority) : undefined;
  const [rows, spend, budget, sources] = await Promise.all([
    listResearch({ status, priority }),
    listSpend(),
    getSetting<AiBudget>("ai.budget"),
    listSources(),
  ]);
  const thisMonth = new Date().toISOString().slice(0, 7);
  const aiSpend = spend.filter((s) => s.source === "anthropic" && s.month.slice(0, 7) === thisMonth);
  const spent = aiSpend.reduce((a, s) => a + (toNum(s.cost_usd) ?? 0), 0);
  const calls = aiSpend.reduce((a, s) => a + s.calls, 0);
  const anthropic = sources.find((s) => s.slug === "anthropic");
  const active = Boolean(budget?.enabled) && Boolean(anthropic?.enabled);
  return (
    <div className="space-y-4">
      <FormError error={str(sp.error)} />
      <FormNotice notice={str(sp.notice)} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="AI reports" value={active ? "enabled" : "off"} sub={<span className="text-[11px] text-fg-dim">{active ? budget?.model : "needs API key + source enabled"}</span>} />
        <Stat label="Spend this month (US$)" value={`$${spent.toFixed(4)}`} sub={<span className="text-[11px] text-fg-dim">cap ${budget?.monthly_usd_cap ?? "?"}</span>} />
        <Stat label="Calls this month" value={calls} sub={<span className="text-[11px] text-fg-dim">daily cap {budget?.daily_request_cap ?? "?"}</span>} />
        <Stat label="Auto-report threshold" value={`score ≥ ${budget?.min_score ?? "?"}`} sub={<span className="text-[11px] text-fg-dim">assessed, not excluded</span>} />
      </div>
      <Card>
        <CardHeader
          title="Reports"
          subtitle="Request a report from a token's page (owners)."
          right={
            <form action="/research" method="get" className="flex items-center gap-1 text-xs">
              <select name="status" defaultValue={status ?? ""} className="rounded border border-border-strong bg-panel-2 px-2 py-0.5">
                <option value="">All statuses</option>
                <Options values={STATUSES} />
              </select>
              <select name="priority" defaultValue={priority ?? ""} className="rounded border border-border-strong bg-panel-2 px-2 py-0.5">
                <option value="">All priorities</option>
                <Options values={PRIORITIES} />
              </select>
              <button className="rounded border border-border-strong px-2 py-0.5 hover:border-accent">Filter</button>
            </form>
          }
        />
        {rows.length === 0 ? <Empty>No reports yet.</Empty> : (
          <Table>
            <thead><tr><Th>Token</Th><Th>Status</Th><Th>Priority</Th><Th>Model</Th><Th className="text-right">Tokens in/out</Th><Th className="text-right">Cost</Th><Th>Created</Th><Th>Note</Th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <Tr key={r.id}>
                  <Td>
                    <Link href={`/research/${r.id}`} className="font-medium hover:text-accent">{r.symbol ?? "?"}</Link>{" "}
                    {r.chain ? <ChainBadge chain={r.chain} /> : null}
                  </Td>
                  <Td><StatusPill s={r.status} /></Td>
                  <Td><PriorityBadge p={r.research_priority} /></Td>
                  <Td className="text-xs text-fg-muted">{r.model ?? "—"}</Td>
                  <Td className="num text-right text-xs">{r.input_tokens ?? "—"} / {r.output_tokens ?? "—"}</Td>
                  <Td className="num text-right text-xs">{toNum(r.cost_usd) === null ? "—" : `$${toNum(r.cost_usd)!.toFixed(4)}`}</Td>
                  <Td className="text-xs" title={formatSgt(r.created_at)}>{formatAge(r.created_at)} ago</Td>
                  <Td className="max-w-80 truncate text-xs text-fg-dim" title={r.error ?? undefined}>{r.error ?? ""}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
