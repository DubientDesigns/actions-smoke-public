-- Phase 6: paper trading engine. No real funds, keys, wallets or execution.

alter table paper_portfolios
  add column starting_capital_usd numeric,
  add column fx_sgd_per_usd numeric,          -- operator reference rate at creation
  add column min_liquidity_usd numeric not null default 10000,
  add column max_fill_window_minutes integer not null default 30 check (max_fill_window_minutes between 1 and 1440),
  add column notes text;

alter table paper_positions
  add column pool_id bigint references pools(id) on delete set null,
  add column entry_price_usd numeric,
  add column last_price_usd numeric,
  add column last_value_usd numeric,          -- liquidation value (price impact + fees), not naive mark
  add column last_marked_at timestamptz,
  add column tp_done jsonb not null default '[]'::jsonb,
  add column strategy_evaluation_id bigint references strategy_evaluations(id);

alter table paper_orders
  add column expires_at timestamptz,
  add column note text;

alter table paper_fills
  add column notional_usd numeric;            -- buy: total spent incl. fee; sell: received after fee

create index paper_positions_token_idx on paper_positions (token_id);
create index paper_orders_token_idx on paper_orders (token_id);
create index strategy_evaluations_token_strategy_idx on strategy_evaluations (strategy_id, token_id);

-- Strategy versions are immutable: changing rules means a new version row.
create function strategy_definitions_immutable() returns trigger language plpgsql as $$
begin
  if new.rules is distinct from old.rules or new.slug is distinct from old.slug
     or new.version is distinct from old.version then
    raise exception 'strategy % v% is immutable; create a new version', old.slug, old.version
      using errcode = 'check_violation';
  end if;
  return new;
end
$$;
create trigger strategy_definitions_immutable_trg before update on strategy_definitions
  for each row execute function strategy_definitions_immutable();

-- Strategy evaluations are an append-only record (no cherry-picking by deletion/edit).
create function strategy_evaluations_append_only() returns trigger language plpgsql as $$
begin
  raise exception 'strategy_evaluations is append-only' using errcode = 'check_violation';
end
$$;
create trigger strategy_evaluations_append_only_trg before update or delete on strategy_evaluations
  for each row execute function strategy_evaluations_append_only();

-- ---------------------------------------------------------------------------
-- Read models
-- ---------------------------------------------------------------------------

create view v_paper_cash with (security_invoker = true) as
select p.id as portfolio_id,
  p.starting_capital_usd
    - coalesce(sum(f.notional_usd) filter (where o.side = 'buy'), 0)
    + coalesce(sum(f.notional_usd) filter (where o.side = 'sell'), 0) as cash_usd,
  coalesce(sum(f.fee_usd), 0) as fees_usd
from paper_portfolios p
left join paper_orders o on o.portfolio_id = p.id
left join paper_fills f on f.order_id = o.id
group by p.id, p.starting_capital_usd;

create view v_paper_positions with (security_invoker = true) as
select pos.*, c.slug as chain, t.address, t.symbol, pr.project_name as presale_name,
       pos.last_value_usd - pos.cost_basis_usd as unrealised_pnl_usd
from paper_positions pos
left join tokens t on t.id = pos.token_id
left join chains c on c.id = t.chain_id
left join presales pr on pr.id = pos.presale_id;

create view v_paper_portfolio_summary with (security_invoker = true) as
select p.id, p.name, p.owner_id, p.strategy_id, sd.slug as strategy_slug, sd.version as strategy_version,
  p.base_currency, p.starting_capital, p.starting_capital_usd, p.fx_sgd_per_usd, p.fee_bps,
  p.execution_delay_seconds, p.max_pool_liquidity_pct, p.min_liquidity_usd, p.is_active, p.created_at,
  cash.cash_usd, cash.fees_usd,
  coalesce(sum(pos.last_value_usd) filter (where pos.status in ('open', 'vesting', 'untradeable')), 0)
    as positions_value_usd,
  cash.cash_usd + coalesce(sum(pos.last_value_usd) filter (where pos.status in ('open', 'vesting', 'untradeable')), 0)
    as equity_usd,
  coalesce(sum(pos.realised_pnl_usd), 0) as realised_pnl_usd,
  count(pos.id) filter (where pos.status = 'open') as open_positions,
  count(pos.id) filter (where pos.status = 'closed') as closed_positions,
  count(pos.id) filter (where pos.status = 'untradeable') as untradeable_positions
from paper_portfolios p
join v_paper_cash cash on cash.portfolio_id = p.id
left join paper_positions pos on pos.portfolio_id = p.id
left join strategy_definitions sd on sd.id = p.strategy_id
group by p.id, sd.slug, sd.version, cash.cash_usd, cash.fees_usd;

create view v_paper_orders with (security_invoker = true) as
select o.*, c.slug as chain, t.address, t.symbol, pr.project_name as presale_name,
       f.filled_at, f.executed_price_usd, f.reference_price_usd, f.quantity as filled_quantity,
       f.notional_usd as filled_notional_usd, f.fee_usd, f.slippage_bps, f.price_observed_at
from paper_orders o
left join tokens t on t.id = o.token_id
left join chains c on c.id = t.chain_id
left join presales pr on pr.id = o.presale_id
left join paper_fills f on f.order_id = o.id;

create view v_strategy_evaluations with (security_invoker = true) as
select e.id, e.strategy_id, sd.slug, sd.version, e.token_id, c.slug as chain, t.address, t.symbol,
       e.evaluated_at, e.data_cutoff_at, e.decision, e.reasons, e.inputs_hash
from strategy_evaluations e
join strategy_definitions sd on sd.id = e.strategy_id
left join tokens t on t.id = e.token_id
left join chains c on c.id = t.chain_id;

-- Forward performance. Wins/losses count CLOSED positions only; untradeable and
-- open positions are reported separately (never silently dropped).
create view v_paper_performance with (security_invoker = true) as
with eq as (
  select portfolio_id, marked_at, equity_usd,
         max(equity_usd) over (partition by portfolio_id order by marked_at) as peak
  from paper_equity_marks
), dd as (
  select portfolio_id, min(equity_usd / nullif(peak, 0) - 1) * 100 as max_drawdown_pct,
         count(*) as equity_marks, min(marked_at) as first_mark_at, max(marked_at) as last_mark_at
  from eq group by portfolio_id
), closed as (
  select portfolio_id, count(*) as closed_n,
         count(*) filter (where realised_pnl_usd > 0) as wins,
         count(*) filter (where realised_pnl_usd <= 0) as losses,
         sum(realised_pnl_usd) filter (where realised_pnl_usd > 0) as gross_profit_usd,
         -sum(realised_pnl_usd) filter (where realised_pnl_usd < 0) as gross_loss_usd,
         avg(max_favourable_pct) as avg_mfe_pct, avg(max_adverse_pct) as avg_mae_pct,
         avg(extract(epoch from (closed_at - opened_at)) / 3600) as avg_hold_hours
  from paper_positions where status = 'closed' group by portfolio_id
), ord as (
  select portfolio_id, count(*) as orders_n,
         count(*) filter (where status in ('filled', 'partially_filled')) as orders_filled,
         count(*) filter (where status = 'rejected') as orders_rejected,
         count(*) filter (where status = 'expired') as orders_expired,
         avg(f.slippage_bps) as avg_slippage_bps
  from paper_orders o left join paper_fills f on f.order_id = o.id group by portfolio_id
), ev as (
  select strategy_id, count(*) as evaluations,
         count(*) filter (where decision = 'enter') as ev_enter,
         count(*) filter (where decision = 'reject') as ev_reject,
         count(*) filter (where decision = 'missed') as ev_missed
  from strategy_evaluations group by strategy_id
)
select s.id as portfolio_id, s.name, s.strategy_slug, s.strategy_version, s.starting_capital_usd, s.equity_usd,
  (s.equity_usd / nullif(s.starting_capital_usd, 0) - 1) * 100 as return_pct,
  s.realised_pnl_usd, s.fees_usd, s.open_positions, s.untradeable_positions,
  dd.max_drawdown_pct, dd.equity_marks, dd.first_mark_at, dd.last_mark_at,
  coalesce(closed.closed_n, 0) as closed_positions, coalesce(closed.wins, 0) as wins,
  coalesce(closed.losses, 0) as losses,
  closed.wins * 100.0 / nullif(closed.closed_n, 0) as win_rate_pct,
  closed.gross_profit_usd, closed.gross_loss_usd,
  closed.gross_profit_usd / nullif(closed.gross_loss_usd, 0) as profit_factor,
  closed.avg_mfe_pct, closed.avg_mae_pct, closed.avg_hold_hours,
  coalesce(ord.orders_n, 0) as orders, coalesce(ord.orders_filled, 0) as orders_filled,
  coalesce(ord.orders_rejected, 0) as orders_rejected, coalesce(ord.orders_expired, 0) as orders_expired,
  ord.avg_slippage_bps,
  coalesce(ev.evaluations, 0) as evaluations, coalesce(ev.ev_enter, 0) as evaluations_enter,
  coalesce(ev.ev_reject, 0) as evaluations_reject, coalesce(ev.ev_missed, 0) as evaluations_missed
from v_paper_portfolio_summary s
left join dd on dd.portfolio_id = s.id
left join closed on closed.portfolio_id = s.id
left join ord on ord.portfolio_id = s.id
left join ev on ev.strategy_id = s.strategy_id;

grant select on v_paper_cash, v_paper_positions, v_paper_portfolio_summary, v_paper_orders,
  v_strategy_evaluations, v_paper_performance to authenticated;
revoke all on v_paper_cash, v_paper_positions, v_paper_portfolio_summary, v_paper_orders,
  v_strategy_evaluations, v_paper_performance from anon;
grant select on paper_equity_marks to authenticated;

-- Equity marks readable with the same visibility as their portfolio.
drop policy if exists paper_equity_marks_read on paper_equity_marks;
create policy paper_equity_marks_read on paper_equity_marks for select to authenticated
  using (exists (select 1 from paper_portfolios p where p.id = portfolio_id
                 and public.is_app_user() and (p.owner_id is null or p.owner_id = auth.uid())));

-- ---------------------------------------------------------------------------
-- Seed: baseline strategy (heuristic, to be judged by forward results only)
-- ---------------------------------------------------------------------------
insert into strategy_definitions (slug, version, name, description, rules, is_active)
values ('baseline', 1, 'Baseline research-score entry',
        'Enter new, liquid, security-assessed tokens with score >= 70; 30% stop, staged take-profits, 7-day max hold. A heuristic benchmark, not a recommendation.',
        '{"notional_usd": 200, "max_open_positions": 10,
          "entry": {"min_score": 70, "max_risk_level": "medium", "require_complete_security": true,
                    "min_liquidity_usd": 50000, "max_token_age_hours": 72,
                    "exclude_flags": ["possible_wash_trading", "price_collapse_24h", "hard_excluded", "security_stale"]},
          "exits": {"stop_loss_pct": 30, "take_profit": [{"gain_pct": 100, "sell_pct": 50}, {"gain_pct": 300, "sell_pct": 100}],
                    "max_hold_hours": 168}}'::jsonb,
        true);

insert into paper_portfolios (owner_id, name, base_currency, starting_capital, starting_capital_usd, fx_sgd_per_usd,
                              strategy_id)
select null, 'Strategy: baseline v1', 'SGD', 10000, round(10000 / 1.30, 2), 1.30, id
from strategy_definitions where slug = 'baseline' and version = 1;
