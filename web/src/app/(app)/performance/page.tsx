import Link from "next/link";
import { Suspense } from "react";
import { ChainBadge, PageHeader } from "@/components/data-display";
import { num, str } from "@/components/filters";
import { Options } from "@/components/form";
import { Guarded } from "@/components/guard";
import { PaperStatus } from "@/components/paper";
import { SeriesChart } from "@/components/series-chart";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { TableSkeleton } from "@/components/ui/skeleton";
import { Empty, Table, Td, Th, Tr } from "@/components/ui/table";
import { listEquityMarks, listEvaluations, listPaperPerformance, listStrategies } from "@/lib/data";
import { formatInt, formatPct, formatSgt, formatUsd, toNum } from "@/lib/format";
import { drawdownSeries } from "@/lib/paper";
import { cn } from "@/lib/utils";

export const metadata = { title: "Historical Performance" };

const DECISIONS = ["enter", "reject", "missed"] as const;

export default function PerformancePage(props: PageProps<"/performance">) {
  return (
    <>
      <PageHeader
        title="Historical Performance"
        description="Forward-only results of paper portfolios. Nothing here is backfilled: a strategy is judged only on decisions it made at the time, all of which are recorded (entries, rejections and missed fills). Small samples say little; the execution model is optimistic for concentrated-liquidity pools."
      />
      <Suspense fallback={<TableSkeleton rows={10} />}>
        <Guarded>
          <Content searchParams={props.searchParams} />
        </Guarded>
      </Suspense>
    </>
  );
}

const fmtNum = (v: unknown, digits = 2) => {
  const n = toNum(v as number | string | null);
  return n === null ? "—" : n.toFixed(digits);
};

async function Content({ searchParams }: { searchParams: PageProps<"/performance">["searchParams"] }) {
  const sp = await searchParams;
  const [perf, strategies] = await Promise.all([listPaperPerformance(), listStrategies()]);
  const selected = perf.find((p) => p.portfolio_id === num(sp.pf)) ?? perf.find((p) => p.strategy_slug) ?? perf[0];
  const decision = DECISIONS.includes(str(sp.decision) as (typeof DECISIONS)[number]) ? str(sp.decision) : undefined;
  const strategyId = num(sp.strategy);
  const [marks, evaluations] = await Promise.all([
    selected ? listEquityMarks(selected.portfolio_id) : Promise.resolve([]),
    listEvaluations({ strategyId, decision }),
  ]);
  const equity = marks.map((m) => ({ t: new Date(m.marked_at).getTime(), v: toNum(m.equity_usd) })).filter((p): p is { t: number; v: number } => p.v !== null);
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="Portfolios" subtitle="Win rate and profit factor count closed positions only. Equity and return use liquidation value (fees + price impact), with untradeable positions at zero." />
        {perf.length === 0 ? <Empty>No paper portfolios yet.</Empty> : (
          <Table>
            <thead>
              <tr>
                <Th>Portfolio</Th><Th className="text-right">Return</Th><Th className="text-right">Max DD</Th><Th className="text-right">Closed (W/L)</Th>
                <Th className="text-right">Win rate</Th><Th className="text-right">Profit factor</Th><Th className="text-right">Avg MFE / MAE</Th><Th className="text-right">Avg hold</Th>
                <Th className="text-right">Orders filled / rejected / expired</Th><Th className="text-right">Avg slippage</Th><Th className="text-right">Evaluations enter / reject / missed</Th>
              </tr>
            </thead>
            <tbody>
              {perf.map((p) => (
                <Tr key={p.portfolio_id} className={cn(p.portfolio_id === selected?.portfolio_id && "bg-panel-2")}>
                  <Td>
                    <Link href={`/performance?pf=${p.portfolio_id}`} className="font-medium hover:text-accent">{p.name}</Link>
                    {p.strategy_slug ? <div className="text-[11px] text-fg-dim">strategy {p.strategy_slug} v{p.strategy_version}</div> : <div className="text-[11px] text-fg-dim">manual</div>}
                  </Td>
                  <Td className={cn("num text-right text-xs", (toNum(p.return_pct) ?? 0) < 0 ? "text-risk" : "text-ok")}>{formatPct(p.return_pct, 2)}</Td>
                  <Td className="num text-right text-xs">{formatPct(p.max_drawdown_pct, 2)}</Td>
                  <Td className="num text-right text-xs">{p.closed_positions} ({p.wins}/{p.losses})</Td>
                  <Td className="num text-right text-xs">{toNum(p.win_rate_pct) === null ? "—" : `${fmtNum(p.win_rate_pct, 0)}%`}</Td>
                  <Td className="num text-right text-xs">{fmtNum(p.profit_factor)}</Td>
                  <Td className="num text-right text-xs">{formatPct(p.avg_mfe_pct)} / {formatPct(p.avg_mae_pct)}</Td>
                  <Td className="num text-right text-xs">{toNum(p.avg_hold_hours) === null ? "—" : `${fmtNum(p.avg_hold_hours, 1)}h`}</Td>
                  <Td className="num text-right text-xs">{p.orders_filled} / {p.orders_rejected} / {p.orders_expired}</Td>
                  <Td className="num text-right text-xs">{toNum(p.avg_slippage_bps) === null ? "—" : `${formatInt(p.avg_slippage_bps)} bps`}</Td>
                  <Td className="num text-right text-xs">{p.strategy_slug ? `${p.evaluations_enter} / ${p.evaluations_reject} / ${p.evaluations_missed}` : "—"}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {selected ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader title={`Equity — ${selected.name}`} subtitle={`US$, hourly marks${selected.first_mark_at ? ` since ${formatSgt(selected.first_mark_at)}` : ""}. Start ${formatUsd(selected.starting_capital_usd, { compact: false })}.`} />
            <CardBody><SeriesChart points={equity} kind="usd" label="Equity" /></CardBody>
          </Card>
          <Card>
            <CardHeader title="Drawdown" subtitle="Percent below the running equity peak." />
            <CardBody><SeriesChart points={drawdownSeries(marks)} kind="pct" label="Drawdown" /></CardBody>
          </Card>
        </div>
      ) : null}
      <Card>
        <CardHeader title="Strategy versions" subtitle="Versions are immutable (enforced in the database); changing a rule means a new version with its own record." />
        {strategies.length === 0 ? <Empty>No strategies defined.</Empty> : (
          <Table>
            <thead><tr><Th>Strategy</Th><Th>Status</Th><Th>Created</Th><Th>Rules</Th></tr></thead>
            <tbody>
              {strategies.map((s) => (
                <Tr key={s.id}>
                  <Td>
                    <Link href={`/performance?strategy=${s.id}`} className="font-medium hover:text-accent">{s.slug} v{s.version}</Link>
                    <div className="max-w-72 text-[11px] text-fg-dim">{s.description}</div>
                  </Td>
                  <Td className="text-xs">{s.is_active ? "active" : "inactive"}</Td>
                  <Td className="text-xs">{formatSgt(s.created_at)}</Td>
                  <Td><pre className="max-h-40 max-w-xl overflow-auto whitespace-pre-wrap text-[11px] text-fg-muted">{JSON.stringify(s.rules, null, 1)}</pre></Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <Card>
        <CardHeader
          title="Evaluation log"
          subtitle="Every decision with its reasons and the hash of its exact inputs; re-running the rules on stored inputs reproduces the decision."
          right={
            <form action="/performance" method="get" className="flex items-center gap-1 text-xs">
              {strategyId ? <input type="hidden" name="strategy" value={strategyId} /> : null}
              {selected ? <input type="hidden" name="pf" value={selected.portfolio_id} /> : null}
              <select name="decision" defaultValue={decision ?? ""} className="rounded border border-border-strong bg-panel-2 px-2 py-0.5">
                <option value="">All decisions</option>
                <Options values={DECISIONS} />
              </select>
              <button className="rounded border border-border-strong px-2 py-0.5 hover:border-accent">Filter</button>
            </form>
          }
        />
        {evaluations.length === 0 ? <Empty>No evaluations yet.</Empty> : (
          <Table>
            <thead><tr><Th>Evaluated (SGT)</Th><Th>Strategy</Th><Th>Token</Th><Th>Decision</Th><Th>Reasons</Th><Th>Data cutoff</Th><Th>Inputs hash</Th></tr></thead>
            <tbody>
              {evaluations.map((e) => (
                <Tr key={e.id}>
                  <Td className="text-xs">{formatSgt(e.evaluated_at)}</Td>
                  <Td className="text-xs">{e.slug} v{e.version}</Td>
                  <Td>
                    {e.chain && e.address ? (
                      <><Link href={`/tokens/${e.chain}/${e.address}`} className="font-medium hover:text-accent">{e.symbol ?? "?"}</Link> <ChainBadge chain={e.chain} /></>
                    ) : "—"}
                  </Td>
                  <Td><PaperStatus s={e.decision} /></Td>
                  <Td className="max-w-96 text-xs text-fg-muted">{e.reasons.join("; ")}</Td>
                  <Td className="text-xs">{formatSgt(e.data_cutoff_at)}</Td>
                  <Td className="num text-[11px] text-fg-dim" title={e.inputs_hash}>{e.inputs_hash.slice(0, 10)}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
