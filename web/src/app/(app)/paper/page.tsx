import Link from "next/link";
import { Suspense } from "react";
import { ChainBadge, PageHeader, Stat } from "@/components/data-display";
import { num, str } from "@/components/filters";
import { FormError, FormNotice } from "@/components/form";
import { Guarded } from "@/components/guard";
import { PaperStatus, SIMULATION_NOTE } from "@/components/paper";
import { SeriesChart } from "@/components/series-chart";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { TableSkeleton } from "@/components/ui/skeleton";
import { Empty, Table, Td, Th, Tr } from "@/components/ui/table";
import { cancelPaperOrder, placePaperOrder } from "@/lib/actions/paper";
import { getPaperPortfolio, getViewer, listPaperPortfolios } from "@/lib/data";
import { formatInt, formatPct, formatPrice, formatSgt, formatUsd, toNum } from "@/lib/format";
import type { PaperOrder, PaperPortfolio, PaperPosition } from "@/lib/types";
import { cn } from "@/lib/utils";

export const metadata = { title: "Paper Portfolio" };

export default function PaperPage(props: PageProps<"/paper">) {
  return (
    <>
      <PageHeader title="Paper Portfolio" description={`Forward-only virtual portfolios. ${SIMULATION_NOTE} Positions are valued at what selling them now would return, not at the displayed price.`} />
      <Suspense fallback={<TableSkeleton rows={10} />}>
        <Guarded>
          <Content searchParams={props.searchParams} />
        </Guarded>
      </Suspense>
    </>
  );
}

const sgd = (usd: unknown, fx: unknown) => {
  const u = toNum(usd as number | string | null);
  const f = toNum(fx as number | string | null) ?? 1.3;
  return u === null ? "—" : `S$${(u * f).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
};

function positionLabel(p: PaperPosition | PaperOrder) {
  if (p.chain && p.address) {
    return (
      <>
        <Link href={`/tokens/${p.chain}/${p.address}`} className="font-medium hover:text-accent">{p.symbol ?? "?"}</Link> <ChainBadge chain={p.chain} />
      </>
    );
  }
  return <span className="font-medium">{p.presale_name ?? "?"} <span className="text-[11px] text-fg-dim">(presale)</span></span>;
}

async function Content({ searchParams }: { searchParams: PageProps<"/paper">["searchParams"] }) {
  const sp = await searchParams;
  const [portfolios, viewer] = await Promise.all([listPaperPortfolios(), getViewer()]);
  const mine = portfolios.find((p) => p.owner_id && p.owner_id === viewer.userId);
  const selected = portfolios.find((p) => p.id === num(sp.pf)) ?? mine ?? portfolios[0];
  return (
    <div className="space-y-4">
      <FormError error={str(sp.error)} />
      <FormNotice notice={str(sp.notice)} />
      <nav className="flex flex-wrap gap-2 text-[13px]" aria-label="Portfolios">
        {portfolios.map((p) => (
          <Link
            key={p.id}
            href={`/paper?pf=${p.id}`}
            className={cn("rounded border px-2.5 py-1", p.id === selected?.id ? "border-accent text-accent" : "border-border-strong text-fg-muted hover:border-accent")}
          >
            {p.name}
          </Link>
        ))}
      </nav>
      {!mine && viewer.role === "owner" ? (
        <p className="text-xs text-fg-dim">You have no manual paper portfolio yet. Place a paper buy from any token page (or an allocation from an open presale); a S$10,000 manual portfolio is created with the first order.</p>
      ) : null}
      {selected ? <PortfolioView pf={selected} editable={Boolean(viewer.role === "owner" && selected.owner_id === viewer.userId)} /> : <Empty>No paper portfolios are visible.</Empty>}
    </div>
  );
}

async function PortfolioView({ pf, editable }: { pf: PaperPortfolio; editable: boolean }) {
  const { positions, orders, marks } = await getPaperPortfolio(pf.id);
  const ret = toNum(pf.starting_capital_usd) ? ((toNum(pf.equity_usd) ?? 0) / toNum(pf.starting_capital_usd)! - 1) * 100 : null;
  const equity = marks.map((m) => ({ t: new Date(m.marked_at).getTime(), v: toNum(m.equity_usd) })).filter((p): p is { t: number; v: number } => p.v !== null);
  const back = `/paper?pf=${pf.id}`;
  const live = positions.filter((p) => p.status !== "closed");
  const closed = positions.filter((p) => p.status === "closed");
  return (
    <>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
        <Stat label="Equity" value={sgd(pf.equity_usd, pf.fx_sgd_per_usd)} sub={<span className="text-[11px] text-fg-dim">{formatUsd(pf.equity_usd, { compact: false })}</span>} />
        <Stat label="Return" value={formatPct(ret)} sub={<span className="text-[11px] text-fg-dim">from {sgd(pf.starting_capital_usd, pf.fx_sgd_per_usd)}</span>} />
        <Stat label="Cash" value={formatUsd(pf.cash_usd, { compact: false })} />
        <Stat label="Positions (liquidation value)" value={formatUsd(pf.positions_value_usd, { compact: false })} />
        <Stat label="Realised P&L" value={formatUsd(pf.realised_pnl_usd, { compact: false })} sub={<span className="text-[11px] text-fg-dim">fees {formatUsd(pf.fees_usd, { compact: false })}</span>} />
        <Stat label="Positions" value={`${pf.open_positions} open`} sub={<span className="text-[11px] text-fg-dim">{pf.untradeable_positions} untradeable · {pf.closed_positions} closed</span>} />
      </div>
      <Card>
        <CardHeader
          title="Equity (US$)"
          subtitle={`Hourly marks at liquidation value. Delay ${pf.execution_delay_seconds}s · fee ${pf.fee_bps} bps/side · max ${pf.max_pool_liquidity_pct}% of pool liquidity · min liquidity ${formatUsd(pf.min_liquidity_usd)} · SGD at ${pf.fx_sgd_per_usd ?? "?"} per USD (reference rate).`}
          right={pf.strategy_slug ? <Link href={`/performance?pf=${pf.id}`} className="text-xs text-accent hover:underline">Strategy {pf.strategy_slug} v{pf.strategy_version} →</Link> : null}
        />
        <CardBody>
          <SeriesChart points={equity} kind="usd" label="Equity" />
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Open, vesting and untradeable positions" subtitle="Untradeable positions (pool below minimum liquidity or no price for 72h) are valued at zero and kept, never dropped." />
        {live.length === 0 ? <Empty>No open positions.</Empty> : (
          <Table>
            <thead>
              <tr>
                <Th>Asset</Th><Th>Status</Th><Th className="text-right">Qty (locked)</Th><Th className="text-right">Entry</Th><Th className="text-right">Last</Th>
                <Th className="text-right">Value</Th><Th className="text-right">Unrealised</Th><Th className="text-right">MFE / MAE</Th><Th>Exits</Th><Th>Opened</Th>{editable ? <Th>Sell</Th> : null}
              </tr>
            </thead>
            <tbody>
              {live.map((p) => (
                <Tr key={p.id}>
                  <Td>{positionLabel(p)}</Td>
                  <Td><PaperStatus s={p.status} />{p.untradeable_reason ? <div className="text-[11px] text-risk">{p.untradeable_reason}</div> : null}</Td>
                  <Td className="num text-right text-xs">{formatInt(p.quantity)}{toNum(p.locked_quantity) ? <span className="text-fg-dim"> ({formatInt(p.locked_quantity)})</span> : null}</Td>
                  <Td className="num text-right text-xs">{formatPrice(p.entry_price_usd)}</Td>
                  <Td className="num text-right text-xs" title={p.last_marked_at ? `marked ${formatSgt(p.last_marked_at)}` : undefined}>{formatPrice(p.last_price_usd)}</Td>
                  <Td className="num text-right text-xs">{formatUsd(p.last_value_usd, { compact: false })}</Td>
                  <Td className={cn("num text-right text-xs", (toNum(p.unrealised_pnl_usd) ?? 0) < 0 ? "text-risk" : "text-ok")}>{formatUsd(p.unrealised_pnl_usd, { compact: false })}</Td>
                  <Td className="num text-right text-xs">{formatPct(p.max_favourable_pct)} / {formatPct(p.max_adverse_pct)}</Td>
                  <Td className="text-xs text-fg-muted">
                    {p.stop_loss_pct !== null ? `SL ${p.stop_loss_pct}%` : "no SL"}
                    {p.take_profit?.length ? ` · TP ${p.take_profit.map((l) => `${l.gain_pct}%→${l.sell_pct}%`).join(", ")}` : ""}
                  </Td>
                  <Td className="text-xs" title={formatSgt(p.opened_at)}>{formatSgt(p.opened_at)}</Td>
                  {editable ? (
                    <Td>
                      <form action={placePaperOrder} className="flex items-center gap-1">
                        <input type="hidden" name="kind" value="sell" />
                        <input type="hidden" name="position_id" value={p.id} />
                        <input type="hidden" name="back" value={back} />
                        <input name="sell_pct" type="number" min={1} max={100} step="any" defaultValue={100} aria-label="Percent to sell" className="w-16 rounded border border-border-strong bg-panel-2 px-1 py-0.5 text-xs" />
                        <button className="rounded border border-border-strong px-2 py-0.5 text-xs hover:border-accent">%</button>
                      </form>
                    </Td>
                  ) : null}
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <Card>
        <CardHeader title="Orders" subtitle="Every order is kept, including rejected and expired ones. Signal = when the information was available; fills never use a price observed before signal + delay." />
        {orders.length === 0 ? <Empty>No orders yet.</Empty> : (
          <Table>
            <thead>
              <tr>
                <Th>Asset</Th><Th>Side</Th><Th>Origin</Th><Th>Status</Th><Th>Signal (SGT)</Th><Th>Price observed</Th>
                <Th className="text-right">Ref → exec</Th><Th className="text-right">Slippage</Th><Th className="text-right">Notional</Th><Th>Note</Th>{editable ? <Th /> : null}
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <Tr key={o.id}>
                  <Td>{positionLabel(o)}</Td>
                  <Td className="text-xs">{o.side} <span className="text-fg-dim">{o.order_type.replaceAll("_", " ")}</span>{o.sell_fraction ? <span className="text-fg-dim"> {Math.round((toNum(o.sell_fraction) ?? 0) * 100)}%</span> : null}</Td>
                  <Td className="text-xs">{o.origin}</Td>
                  <Td><PaperStatus s={o.status} />{o.reject_reason ? <div className="max-w-56 text-[11px] text-fg-dim">{o.reject_reason}</div> : null}</Td>
                  <Td className="text-xs">{formatSgt(o.signal_at)}</Td>
                  <Td className="text-xs">{o.price_observed_at ? formatSgt(o.price_observed_at) : <span className="text-fg-dim">earliest {formatSgt(o.earliest_fill_at)}</span>}</Td>
                  <Td className="num text-right text-xs">{o.reference_price_usd !== null ? `${formatPrice(o.reference_price_usd)} → ${formatPrice(o.executed_price_usd)}` : "—"}</Td>
                  <Td className="num text-right text-xs">{o.slippage_bps !== null ? `${formatInt(o.slippage_bps)} bps` : "—"}</Td>
                  <Td className="num text-right text-xs">{formatUsd(o.filled_notional_usd ?? o.requested_notional_usd, { compact: false })}</Td>
                  <Td className="max-w-56 truncate text-xs text-fg-dim" title={o.note ?? undefined}>{o.note && !o.note.startsWith("{") ? o.note : ""}</Td>
                  {editable ? (
                    <Td>
                      {o.status === "pending" ? (
                        <form action={cancelPaperOrder}>
                          <input type="hidden" name="order_id" value={o.id} />
                          <input type="hidden" name="back" value={back} />
                          <button className="rounded border border-border-strong px-2 py-0.5 text-xs hover:border-risk">Cancel</button>
                        </form>
                      ) : null}
                    </Td>
                  ) : null}
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {closed.length ? (
        <Card>
          <CardHeader title="Closed positions" />
          <Table>
            <thead><tr><Th>Asset</Th><Th className="text-right">Realised P&L</Th><Th className="text-right">MFE / MAE</Th><Th>Opened</Th><Th>Closed</Th></tr></thead>
            <tbody>
              {closed.map((p) => (
                <Tr key={p.id}>
                  <Td>{positionLabel(p)}</Td>
                  <Td className={cn("num text-right text-xs", (toNum(p.realised_pnl_usd) ?? 0) < 0 ? "text-risk" : "text-ok")}>{formatUsd(p.realised_pnl_usd, { compact: false })}</Td>
                  <Td className="num text-right text-xs">{formatPct(p.max_favourable_pct)} / {formatPct(p.max_adverse_pct)}</Td>
                  <Td className="text-xs">{formatSgt(p.opened_at)}</Td>
                  <Td className="text-xs">{formatSgt(p.closed_at)}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        </Card>
      ) : null}
    </>
  );
}
