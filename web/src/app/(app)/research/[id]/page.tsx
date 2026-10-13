import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { ChainBadge, PageHeader } from "@/components/data-display";
import { Guarded } from "@/components/guard";
import { PriorityBadge, StatusPill } from "@/components/research";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { getResearch } from "@/lib/data";
import { formatSgt, toNum } from "@/lib/format";
import type { EvidenceItem, ReportClaim, ReportSection } from "@/lib/types";

export default function ReportPage(props: PageProps<"/research/[id]">) {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full" />}>
      <Guarded>
        <Report params={props.params} />
      </Guarded>
    </Suspense>
  );
}

function Refs({ ids }: { ids: string[] }) {
  if (!ids.length) return <span className="text-[11px] text-unknown"> (no evidence cited)</span>;
  return (
    <span className="ml-1 inline-flex flex-wrap gap-0.5">
      {ids.map((id) => (
        <a key={id} href={`#${id}`} className="rounded border border-border-strong px-1 text-[10px] text-accent hover:bg-panel-2">
          {id}
        </a>
      ))}
    </span>
  );
}

function Claims({ items, empty }: { items: ReportClaim[]; empty: string }) {
  if (!items.length) return <p className="text-[13px] text-fg-dim">{empty}</p>;
  return (
    <ul className="space-y-1.5 text-[13px]">
      {items.map((c, i) => (
        <li key={i}>{c.statement}<Refs ids={c.evidence_ids} /></li>
      ))}
    </ul>
  );
}

function SectionCard({ title, s }: { title: string; s: ReportSection }) {
  return (
    <Card>
      <CardHeader title={title} right={<Badge tone={s.confidence === "high" ? "ok" : s.confidence === "medium" ? "neutral" : "unknown"}>{s.confidence} confidence</Badge>} />
      <CardBody className="text-[13px]">{s.assessment}<Refs ids={s.evidence_ids} /></CardBody>
    </Card>
  );
}

function evidenceSummary(e: EvidenceItem): string {
  const skip = new Set(["id", "kind", "source", "observed_at", "untrusted_text"]);
  return Object.entries(e)
    .filter(([k, v]) => !skip.has(k) && v !== null && v !== undefined)
    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(" · ")
    .slice(0, 600);
}

async function Report({ params }: { params: PageProps<"/research/[id]">["params"] }) {
  const { id } = await params;
  const n = Number(id);
  if (!Number.isInteger(n) || n <= 0) notFound();
  const data = await getResearch(n);
  if (!data) notFound();
  const { row, content, evidence } = data;
  return (
    <>
      <PageHeader
        title={`Research note · ${row.symbol ?? "?"}`}
        description="AI-generated from the evidence listed below. Not investment advice. May contain errors — check every claim against its cited evidence."
        right={
          <div className="flex items-center gap-2">
            {row.chain ? <ChainBadge chain={row.chain} /> : null}
            <StatusPill s={row.status} />
            <PriorityBadge p={row.research_priority} />
          </div>
        }
      />
      <p className="mb-4 text-xs text-fg-dim">
        {row.model ?? "model n/a"} · prompt {row.prompt_version} · created {formatSgt(row.created_at)}
        {row.completed_at ? ` · completed ${formatSgt(row.completed_at)}` : ""} · {row.input_tokens ?? 0} in / {row.output_tokens ?? 0} out tokens
        {toNum(row.cost_usd) !== null ? ` · $${toNum(row.cost_usd)!.toFixed(4)}` : ""}
        {row.chain && row.address ? <> · <Link className="text-accent hover:underline" href={`/tokens/${row.chain}/${row.address}`}>token page</Link></> : null}
      </p>
      {row.status !== "complete" ? (
        <Card className="mb-4 border-warn/40">
          <CardBody className="text-[13px]">
            <div className="font-medium text-warn">This report is {row.status.replaceAll("_", " ")}.</div>
            {row.error ? <div className="mt-1 text-fg-muted">{row.error}</div> : null}
            {row.status === "rejected_schema" ? (
              <div className="mt-1 text-fg-dim">The model output failed validation and is not shown as a finding.</div>
            ) : null}
          </CardBody>
        </Card>
      ) : null}
      {content && row.status === "complete" ? (
        <div className="space-y-4">
          <Card>
            <CardHeader title="Executive summary" right={<PriorityBadge p={content.research_priority} />} />
            <CardBody className="space-y-2 text-[13px]">
              <p>{content.executive_summary}</p>
              <p className="text-fg-muted"><span className="text-fg-dim">Priority rationale:</span> {content.priority_rationale}</p>
              <p className="text-fg-muted"><span className="text-fg-dim">Project:</span> {content.project_description}</p>
            </CardBody>
          </Card>
          <div className="grid gap-4 xl:grid-cols-2">
            <Card><CardHeader title="Evidence supporting further research" /><CardBody><Claims items={content.evidence_for} empty="None identified." /></CardBody></Card>
            <Card><CardHeader title="Evidence against" /><CardBody><Claims items={content.evidence_against} empty="None identified." /></CardBody></Card>
          </div>
          <div className="grid gap-4 xl:grid-cols-3">
            <SectionCard title="Tokenomics" s={content.tokenomics} />
            <SectionCard title="Contract risks" s={content.contract_risks} />
            <SectionCard title="Liquidity risks" s={content.liquidity_risks} />
            <SectionCard title="Community quality" s={content.community_quality} />
            <SectionCard title="Insider concentration" s={content.insider_concentration} />
            <SectionCard title="Known catalysts" s={content.catalysts} />
          </div>
          <Card>
            <CardHeader title="Unknowns" />
            <CardBody>
              {content.unknowns.length ? (
                <ul className="list-disc space-y-1 pl-5 text-[13px] text-fg-muted">{content.unknowns.map((u) => <li key={u}>{u}</li>)}</ul>
              ) : <p className="text-[13px] text-fg-dim">None listed.</p>}
            </CardBody>
          </Card>
        </div>
      ) : null}
      <Card className="mt-4">
        <CardHeader title={`Evidence (${evidence.length})`} subtitle="Exactly what the model was given. Text marked untrusted is third-party content." />
        <CardBody className="space-y-2">
          {evidence.map((e) => (
            <div key={e.id} id={e.id} className="scroll-mt-4 rounded border border-border px-3 py-2 text-xs target:border-accent">
              <div className="flex flex-wrap items-center gap-2">
                <Badge className="font-mono">{e.id}</Badge>
                <span className="font-medium">{e.kind.replaceAll("_", " ")}</span>
                <span className="text-fg-dim">{e.source ?? "unknown source"} · {e.observed_at ? formatSgt(e.observed_at) : "time n/a"}</span>
                {e.self_reported ? <Badge tone="warn">self-reported</Badge> : null}
              </div>
              <div className="num mt-1 break-words text-fg-muted">{evidenceSummary(e)}</div>
              {typeof e.untrusted_text === "string" ? (
                <blockquote className="mt-1 border-l-2 border-warn/60 pl-2 text-fg-muted">
                  <span className="text-[10px] uppercase tracking-wider text-warn">untrusted text</span> {e.untrusted_text}
                </blockquote>
              ) : null}
            </div>
          ))}
        </CardBody>
      </Card>
    </>
  );
}
