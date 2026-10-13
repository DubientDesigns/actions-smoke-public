import Link from "next/link";
import { Suspense } from "react";
import { PageHeader, Stat } from "@/components/data-display";
import { str } from "@/components/filters";
import { Options } from "@/components/form";
import { Guarded, Notice } from "@/components/guard";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { TableSkeleton } from "@/components/ui/skeleton";
import { Empty, Table, Td, Th, Tr } from "@/components/ui/table";
import { getSetting, listAlerts, requestTime } from "@/lib/data";
import { formatAge, formatSgt } from "@/lib/format";

export const metadata = { title: "Alerts" };

const CATEGORIES = ["new_token", "multi_source_mention", "liquidity_change", "wallet_activity", "contract_risk", "presale", "paper_rule", "source_outage", "spend_threshold"] as const;
const SEVERITIES = ["critical", "high", "medium", "low", "info"] as const;
const STATUSES = ["pending", "sent", "deferred", "digested", "failed", "suppressed"] as const;
const SEV_TONE = { critical: "risk", high: "risk", medium: "warn", low: "neutral", info: "neutral" } as const;

type AlertCfg = { enabled?: boolean; quiet_hours_start?: string; quiet_hours_end?: string; quiet_hours_min_severity?: string; max_alerts_per_hour?: number };

export default function AlertsPage(props: PageProps<"/alerts">) {
  return (
    <>
      <PageHeader
        title="Alerts"
        description="Deduplicated signals sent to Telegram by severity. Low-severity items and anything during quiet hours (unless high/critical) go to the 08:00 SGT daily digest. Alerts are research prompts, not trade signals."
      />
      <Suspense fallback={<TableSkeleton rows={12} />}>
        <Guarded>
          <Content searchParams={props.searchParams} />
        </Guarded>
      </Suspense>
    </>
  );
}

function linkFor(body: string): string | null {
  const line = body.split("\n").find((l) => l.startsWith("/tokens/") || l.startsWith("/presales/"));
  return line ?? null;
}

async function Content({ searchParams }: { searchParams: PageProps<"/alerts">["searchParams"] }) {
  const sp = await searchParams;
  const pick = <T extends string>(v: string | undefined, allowed: readonly T[]) => (allowed.includes(v as T) ? (v as T) : undefined);
  const f = { category: pick(str(sp.category), CATEGORIES), severity: pick(str(sp.severity), SEVERITIES), status: pick(str(sp.status), STATUSES) };
  const [rows, cfg] = await Promise.all([listAlerts(f), getSetting<AlertCfg>("alerts")]);
  const now = requestTime().getTime();
  const last24 = rows.filter((r) => now - new Date(r.created_at).getTime() < 86400_000);
  const sent = rows.filter((r) => r.status === "sent").length;
  const pending = rows.filter((r) => r.status === "pending").length;
  const field = "rounded border border-border-strong bg-panel-2 px-2 py-0.5";
  return (
    <div className="space-y-4">
      {pending > 0 && sent === 0 ? (
        <Notice title="Alerts are not being delivered">
          {pending} alert(s) are waiting. Set CIT_TELEGRAM_BOT_TOKEN and CIT_TELEGRAM_ALERT_CHAT_ID (see docs/OPERATIONS.md); until then alerts are visible here only.
        </Notice>
      ) : null}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Last 24h" value={last24.length} />
        <Stat label="Delivery" value={cfg?.enabled === false ? "off" : "on"} sub={<span className="text-[11px] text-fg-dim">max {cfg?.max_alerts_per_hour ?? 12}/hour</span>} />
        <Stat label="Quiet hours (SGT)" value={`${cfg?.quiet_hours_start ?? "23:00"}–${cfg?.quiet_hours_end ?? "07:30"}`} sub={<span className="text-[11px] text-fg-dim">{cfg?.quiet_hours_min_severity ?? "high"}+ still sent</span>} />
        <Stat label="Digest" value="08:00 SGT" sub={<span className="text-[11px] text-fg-dim">with daily health report</span>} />
      </div>
      <Card>
        <CardHeader
          title="Alert log"
          right={
            <form action="/alerts" method="get" className="flex flex-wrap items-center gap-1 text-xs">
              <select name="category" defaultValue={f.category ?? ""} className={field}><option value="">All categories</option><Options values={CATEGORIES} /></select>
              <select name="severity" defaultValue={f.severity ?? ""} className={field}><option value="">All severities</option><Options values={SEVERITIES} /></select>
              <select name="status" defaultValue={f.status ?? ""} className={field}><option value="">All statuses</option><Options values={STATUSES} /></select>
              <button className="rounded border border-border-strong px-2 py-0.5 hover:border-accent">Filter</button>
            </form>
          }
        />
        {rows.length === 0 ? <Empty>No alerts.</Empty> : (
          <Table>
            <thead><tr><Th>When</Th><Th>Severity</Th><Th>Category</Th><Th>Alert</Th><Th>Delivery</Th></tr></thead>
            <tbody>
              {rows.map((r) => {
                const href = linkFor(r.body);
                return (
                  <Tr key={r.id}>
                    <Td className="text-xs whitespace-nowrap" title={formatSgt(r.created_at)}>{formatAge(r.created_at)} ago</Td>
                    <Td><Badge tone={SEV_TONE[r.severity]}>{r.severity}</Badge></Td>
                    <Td className="text-xs text-fg-muted">{r.category.replaceAll("_", " ")}</Td>
                    <Td className="max-w-[36rem]">
                      {href ? <Link href={href} className="font-medium hover:text-accent">{r.title}</Link> : <span className="font-medium">{r.title}</span>}
                      <div className="truncate text-xs text-fg-dim" title={r.body}>{r.body.split("\n").filter((l) => !l.startsWith("/")).join(" ")}</div>
                    </Td>
                    <Td className="text-xs">
                      <Badge tone={r.status === "sent" ? "ok" : r.status === "failed" ? "risk" : "unknown"}>{r.status}</Badge>
                      {r.status_reason ? <span className="ml-1 text-fg-dim">{r.status_reason}</span> : null}
                    </Td>
                  </Tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
