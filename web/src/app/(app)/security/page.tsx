import Link from "next/link";
import { Suspense } from "react";
import { ChainBadge, PageHeader, Stat } from "@/components/data-display";
import { chainParam, str, toQuery } from "@/components/filters";
import { Guarded } from "@/components/guard";
import { SavedViews } from "@/components/saved-views";
import { RiskBadge } from "@/components/security";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { TableSkeleton } from "@/components/ui/skeleton";
import { Empty, Table, Td, Th, Tr } from "@/components/ui/table";
import { listSecurity, securityCounts } from "@/lib/data";
import { formatAge, formatShare, shortAddress } from "@/lib/format";

export const metadata = { title: "Security Analysis" };

const RISKS = ["critical", "high", "medium", "low", "unknown"];
const COVERAGE = ["complete", "partial", "not_found", "unsupported", "error"];

export default function SecurityPage(props: PageProps<"/security">) {
  return (
    <>
      <PageHeader
        title="Security Analysis"
        description="Contract and holder checks from GoPlus. Heuristics, not an audit: a clean result can still be a scam. Missing data is shown as unknown and never counts as a pass."
      />
      <Suspense fallback={<TableSkeleton rows={14} />}>
        <Guarded>
          <SecurityContent searchParams={props.searchParams} />
        </Guarded>
      </Suspense>
    </>
  );
}

async function SecurityContent({ searchParams }: { searchParams: PageProps<"/security">["searchParams"] }) {
  const sp = await searchParams;
  const risk = RISKS.includes(str(sp.risk) ?? "") ? str(sp.risk) : undefined;
  const coverage = COVERAGE.includes(str(sp.coverage) ?? "") ? str(sp.coverage) : undefined;
  const stale = str(sp.stale) === "only" ? "only" : str(sp.stale) === "hide" ? "hide" : undefined;
  const chain = chainParam(sp.chain);
  const [rows, counts] = await Promise.all([listSecurity({ chain, risk, coverage, stale }), securityCounts()]);
  const field = "rounded border border-border-strong bg-panel-2 px-2 py-1 text-[13px] outline-none focus:border-accent";

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {RISKS.map((r) => (
          <Link key={r} href={`/security?risk=${r}`} className="block">
            <Stat label={r === "unknown" ? "incomplete" : r} value={counts[r] ?? 0} />
          </Link>
        ))}
      </div>
      <Card>
        <CardHeader title="Latest assessment per token" subtitle="Assessments expire after 24h and are re-run for tracked tokens; expired ones are labelled stale." />
        <SavedViews page="security" path="/security" query={toQuery(sp)} />
        <form action="/security" method="get" className="flex flex-wrap items-end gap-2 border-b border-border px-4 py-3">
          <label className="text-[11px] text-fg-dim">
            Chain
            <select name="chain" defaultValue={chain ?? ""} className={`${field} mt-0.5 block`}>
              <option value="">All</option>
              <option value="bsc">BNB Chain</option>
              <option value="ethereum">Ethereum</option>
              <option value="solana">Solana</option>
              <option value="base">Base</option>
            </select>
          </label>
          <label className="text-[11px] text-fg-dim">
            Risk
            <select name="risk" defaultValue={risk ?? ""} className={`${field} mt-0.5 block`}>
              <option value="">All</option>
              {RISKS.map((r) => (
                <option key={r} value={r}>{r === "unknown" ? "incomplete" : r}</option>
              ))}
            </select>
          </label>
          <label className="text-[11px] text-fg-dim">
            Coverage
            <select name="coverage" defaultValue={coverage ?? ""} className={`${field} mt-0.5 block`}>
              <option value="">All</option>
              {COVERAGE.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>
          <label className="text-[11px] text-fg-dim">
            Freshness
            <select name="stale" defaultValue={stale ?? ""} className={`${field} mt-0.5 block`}>
              <option value="">All</option>
              <option value="hide">Current only</option>
              <option value="only">Stale only</option>
            </select>
          </label>
          <button className="rounded border border-border-strong bg-panel-2 px-3 py-1 text-[13px] hover:border-accent">Apply</button>
        </form>
        {rows.length === 0 ? (
          <Empty>No assessments match. Assessments run every 10 minutes for liquid tracked tokens.</Empty>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Token</Th><Th>Chain</Th><Th>Risk</Th><Th>Coverage</Th><Th>Top issues</Th>
                <Th className="text-right">Buy / sell tax</Th><Th className="text-right">Top-10 holders</Th><Th>Assessed</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const issues = r.checks.filter((c) => c.status === "risk" || c.status === "warn").slice(0, 4);
                const unknown = r.checks.filter((c) => c.status === "unknown").length;
                return (
                  <Tr key={r.assessment_id}>
                    <Td>
                      <Link href={`/tokens/${r.chain}/${r.address}`} className="font-medium hover:text-accent">
                        {r.symbol ?? "?"}
                      </Link>{" "}
                      <span className="num text-[11px] text-fg-dim">{shortAddress(r.address)}</span>
                    </Td>
                    <Td><ChainBadge chain={r.chain} /></Td>
                    <Td><RiskBadge level={r.risk_level} excluded={r.hard_excluded} stale={r.is_stale} /></Td>
                    <Td className="text-xs text-fg-muted">{r.coverage}{unknown ? ` · ${unknown} unknown` : ""}</Td>
                    <Td className="max-w-96">
                      <div className="flex flex-wrap gap-1">
                        {issues.map((c) => (
                          <Badge key={c.key} tone={c.status === "risk" ? "risk" : "warn"}>{c.label}</Badge>
                        ))}
                        {issues.length === 0 ? <span className="text-xs text-fg-dim">none detected</span> : null}
                      </div>
                    </Td>
                    <Td className="num text-right">{formatShare(r.buy_tax_pct)} / {formatShare(r.sell_tax_pct)}</Td>
                    <Td className="num text-right">{formatShare(r.top10_holder_pct)}</Td>
                    <Td className="text-xs text-fg-dim">{formatAge(r.assessed_at)} ago</Td>
                  </Tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </Card>
      <p className="text-[11px] text-fg-dim">
        Security data: GoPlus Security API. Exclusion and review rules are configured in Settings → security.policy.
      </p>
    </div>
  );
}
