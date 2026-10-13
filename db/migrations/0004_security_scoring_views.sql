-- Phase 3 read models: latest security assessment and latest score per token,
-- surfaced on v_token_overview. security_invoker keeps base-table RLS in force.

create index if not exists security_assessments_token_latest_idx
  on security_assessments (token_id, assessed_at desc) include (valid_until, risk_level, hard_excluded);
create index if not exists opportunity_scores_token_latest_idx
  on opportunity_scores (token_id, scored_at desc) where scorecard = 'token';

create view v_security_latest with (security_invoker = true) as
select distinct on (a.token_id)
  a.id as assessment_id, a.token_id, c.slug as chain, t.address, t.symbol, t.name,
  a.assessed_at, a.valid_until, (a.valid_until < now()) as is_stale,
  a.coverage, a.risk_level, a.hard_excluded, a.needs_review, a.checks, a.risk_flags,
  a.is_honeypot, a.buy_tax_pct, a.sell_tax_pct, a.top10_holder_pct, a.ruleset_version, s.slug as source
from security_assessments a
join tokens t on t.id = a.token_id
join chains c on c.id = t.chain_id
join data_sources s on s.id = a.source_id
order by a.token_id, a.assessed_at desc;

create view v_score_latest with (security_invoker = true) as
select distinct on (o.token_id)
  o.id as score_id, o.token_id, o.scoring_version, o.scored_at, o.data_cutoff_at, o.total, o.components,
  o.missing_data, o.risk_flags, o.inputs_hash
from opportunity_scores o
where o.scorecard = 'token'
order by o.token_id, o.scored_at desc;

-- Columns may only be appended when replacing a view.
create or replace view v_token_overview with (security_invoker = true) as
select
  t.id                       as token_id,
  c.slug                     as chain,
  t.address,
  t.name,
  t.symbol,
  t.first_observed_at,
  t.earliest_pool_created_at,
  extract(epoch from (t.first_observed_at - t.earliest_pool_created_at))::bigint as discovery_latency_s,
  fs.slug                    as first_source,
  t.links,
  t.is_excluded,
  t.exclusion_reason,
  coalesce(pc.n, 0)          as pool_count,
  bp.pool_id                 as best_pool_id,
  bp.pool_address            as best_pool_address,
  bp.dex                     as best_pool_dex,
  bp.quote_symbol,
  bp.price_usd,
  bp.liquidity_usd,
  bp.volume_h1_usd,
  bp.volume_h24_usd,
  bp.buys_h24,
  bp.sells_h24,
  bp.price_change_h24,
  bp.market_cap_usd,
  bp.fdv_usd,
  bp.observed_at             as market_observed_at,
  bp.source                  as market_source,
  sec.risk_level,
  sec.hard_excluded,
  sec.needs_review,
  sec.coverage               as security_coverage,
  sec.assessed_at            as security_assessed_at,
  sec.valid_until            as security_valid_until,
  sc.total                   as score_total,
  sc.scored_at,
  sc.scoring_version,
  sc.risk_flags              as score_risk_flags
from tokens t
join chains c on c.id = t.chain_id
left join data_sources fs on fs.id = t.first_observed_source_id
left join lateral (
  select count(*) as n from pools p where p.base_token_id = t.id
) pc on true
left join lateral (
  select pl.pool_id, p.address as pool_address, p.dex, p.quote_symbol, pl.price_usd, pl.liquidity_usd,
         pl.volume_h1_usd, pl.volume_h24_usd, pl.buys_h24, pl.sells_h24, pl.price_change_h24,
         pl.market_cap_usd, pl.fdv_usd, pl.observed_at, s.slug as source
  from pool_latest pl
  join pools p on p.id = pl.pool_id
  join data_sources s on s.id = pl.source_id
  where pl.token_id = t.id
  order by pl.liquidity_usd desc nulls last, pl.observed_at desc
  limit 1
) bp on true
left join lateral (
  select a.risk_level, a.hard_excluded, a.needs_review, a.coverage, a.assessed_at, a.valid_until
  from security_assessments a where a.token_id = t.id
  order by a.assessed_at desc limit 1
) sec on true
left join lateral (
  select o.total, o.scored_at, o.scoring_version, o.risk_flags
  from opportunity_scores o where o.token_id = t.id and o.scorecard = 'token'
  order by o.scored_at desc limit 1
) sc on true
where not t.is_quote_asset;

grant select on v_security_latest, v_score_latest to authenticated;
revoke all on v_security_latest, v_score_latest from anon;
