import { Suspense } from "react";
import { Freshness, PageHeader, StatusBadge } from "@/components/data-display";
import { Guarded } from "@/components/guard";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { TableSkeleton } from "@/components/ui/skeleton";
import { Empty, Table, Td, Th, Tr } from "@/components/ui/table";
import { listHealth, listJobFreshness, listSources, listUsage } from "@/lib/data";
import { formatInt, formatSgt, toNum } from "@/lib/format";
import { CHAIN_LABEL } from "@/lib/nav";

export const metadata = { title: "Data Sources & Health" };

export default function SystemPage() {
  return (
    <>
      <PageHeader
        title="Data Sources & System Health"
        description="Latest successful refresh for every source and chain, worker heartbeats, circuit breakers, and API usage against budgets."
      />
      <Suspense fallback={<TableSkeleton rows={14} />}>
        <Guarded>
          <SystemContent />
        </Guarded>
      </Suspense>
    </>
  );
}

async function SystemContent() {
  const [sources, jobs, health, usage] = await Promise.all([listSources(), listJobFreshness(), listHealth(), listUsage(7)]);
  const report = health.find((h) => h.component === "daily_health_report");
  const components = health.filter((h) => !h.component.startsWith("source:") && h.component !== "daily_health_report");
  const today = new Date().toISOString().slice(0, 10);
  const usageToday = new Map(usage.filter((u) => u.day.slice(0, 10) === today).map((u) => [u.source, u]));

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="Sources" subtitle="Budgets are conservative fractions of documented free-tier limits." />
        <Table>
          <thead>
            <tr>
              <Th>Source</Th><Th>Kind</Th><Th>Status</Th><Th>Last success</Th><Th>Circuit</Th>
              <Th className="text-right">Calls today / cap</Th><Th className="text-right">Rate / min</Th><Th>Last error</Th>
            </tr>
          </thead>
          <tbody>
            {sources.filter((s) => s.kind !== "manual").map((s) => {
              const u = usageToday.get(s.slug);
              const status = !s.enabled ? "disabled" : s.circuit_state === "open" ? "down" : s.consecutive_failures > 0 ? "degraded" : s.last_success_at ? "ok" : "unknown";
              return (
                <Tr key={s.slug}>
                  <Td>
                    <a href={s.docs_url ?? undefined} target="_blank" rel="noreferrer" className="hover:text-accent">{s.name}</a>
                  </Td>
                  <Td className="text-fg-muted">{s.kind}</Td>
                  <Td>{s.enabled ? <StatusBadge status={status} /> : <Badge>disabled</Badge>}</Td>
                  <Td><Freshness at={s.last_success_at} slaSeconds={s.freshness_sla_seconds} /></Td>
                  <Td>{s.circuit_state === "closed" ? <span className="text-fg-dim">closed</span> : <Badge tone="risk">{s.circuit_state} until {formatSgt(s.circuit_open_until)}</Badge>}</Td>
                  <Td className="num text-right">{formatInt(u?.calls ?? 0)} / {s.daily_call_cap ? formatInt(s.daily_call_cap) : "—"}</Td>
                  <Td className="num text-right">{s.rate_limit_per_minute ?? "—"}</Td>
                  <Td className="max-w-80 truncate text-xs text-fg-dim" title={s.last_error ?? undefined}>{s.last_error ?? ""}</Td>
                </Tr>
              );
            })}
          </tbody>
        </Table>
      </Card>

      <Card>
        <CardHeader title="Ingestion jobs by chain" subtitle="'partial' = page limit reached before catching up; some new pools may have been missed." />
        {jobs.length === 0 ? <Empty>No ingestion runs recorded yet. Is the worker running?</Empty> : (
          <Table>
            <thead>
              <tr><Th>Job</Th><Th>Chain</Th><Th>Last status</Th><Th>Last success</Th><Th className="text-right">Runs 24h</Th><Th className="text-right">Failed 24h</Th><Th>Last error</Th></tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <Tr key={`${j.job_name}-${j.chain}`}>
                  <Td className="num text-xs">{j.job_name}</Td>
                  <Td>{j.chain ? CHAIN_LABEL[j.chain] : "—"}</Td>
                  <Td><StatusBadge status={j.last_status} /></Td>
                  <Td><Freshness at={j.last_success_at} source={j.source} /></Td>
                  <Td className="num text-right">{j.runs_24h}</Td>
                  <Td className="num text-right">{j.failed_24h}</Td>
                  <Td className="max-w-80 truncate text-xs text-fg-dim" title={j.last_error ?? undefined}>{j.last_error ?? ""}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader title="Components" subtitle="Worker heartbeat every minute; jobs report after each run." />
          {components.length === 0 ? <Empty>No heartbeats yet.</Empty> : (
            <Table>
              <thead><tr><Th>Component</Th><Th>Status</Th><Th>Checked</Th><Th>Message</Th></tr></thead>
              <tbody>
                {components.map((h) => (
                  <Tr key={h.component}>
                    <Td className="num text-xs">{h.component}</Td>
                    <Td><StatusBadge status={h.status} /></Td>
                    <Td><Freshness at={h.checked_at} slaSeconds={h.component === "worker" ? 180 : 3600} /></Td>
                    <Td className="max-w-72 truncate text-xs text-fg-dim" title={h.message ?? undefined}>{h.message ?? ""}</Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
        <Card>
          <CardHeader title="Daily operational health report" subtitle={report ? `Generated ${formatSgt(report.checked_at)}` : "Generated daily at 08:00 SGT"} />
          {report && typeof report.details?.text === "string" ? (
            <pre className="num overflow-x-auto p-4 text-[11px] leading-relaxed text-fg-muted">{report.details.text}</pre>
          ) : <Empty>No report generated yet.</Empty>}
        </Card>
      </div>

      <Card>
        <CardHeader title="API usage, last 7 days" subtitle="Metered cost is zero for free tiers; AI spend appears here from Phase 5." />
        {usage.length === 0 ? <Empty>No API calls recorded.</Empty> : (
          <Table>
            <thead><tr><Th>Day (UTC)</Th><Th>Source</Th><Th className="text-right">Calls</Th><Th className="text-right">Failed</Th><Th className="text-right">Cost (USD)</Th></tr></thead>
            <tbody>
              {usage.slice().reverse().map((u) => (
                <Tr key={`${u.day}-${u.source}`}>
                  <Td className="num text-xs">{u.day.slice(0, 10)}</Td>
                  <Td>{u.source}</Td>
                  <Td className="num text-right">{formatInt(u.calls)}</Td>
                  <Td className="num text-right">{formatInt(u.failed_calls)}</Td>
                  <Td className="num text-right">${(toNum(u.cost_usd) ?? 0).toFixed(4)}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
