-- Read models for the dashboard. security_invoker = true makes every view run
-- with the caller's privileges, so base-table RLS still applies to browser users.

create view v_token_overview with (security_invoker = true) as
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
  bp.source                  as market_source
from tokens t
join chains c on c.id = t.chain_id
left join data_sources fs on fs.id = t.first_observed_source_id
left join lateral (
  select count(*) as n from pools p where p.base_token_id = t.id
) pc on true
left join lateral (
  -- "Best" pool = deepest liquidity among latest observations.
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
where not t.is_quote_asset;

create view v_pool_detail with (security_invoker = true) as
select
  p.id as pool_id, c.slug as chain, p.address, p.base_token_id as token_id, p.dex, p.quote_symbol,
  p.pool_created_at, p.first_observed_at, fs.slug as first_source,
  pl.price_usd, pl.liquidity_usd, pl.volume_h24_usd, pl.volume_h1_usd, pl.buys_h24, pl.sells_h24,
  pl.price_change_h24, pl.market_cap_usd, pl.fdv_usd, pl.observed_at, s.slug as market_source
from pools p
join chains c on c.id = p.chain_id
left join data_sources fs on fs.id = p.first_observed_source_id
left join pool_latest pl on pl.pool_id = p.id
left join data_sources s on s.id = pl.source_id;

-- Latest successful run per (job, chain) — "every source displays its latest successful refresh".
create view v_job_freshness with (security_invoker = true) as
select
  r.job_name, s.slug as source, c.slug as chain,
  max(r.finished_at) filter (where r.status in ('success', 'partial')) as last_success_at,
  max(r.started_at) as last_attempt_at,
  (array_agg(r.status order by r.started_at desc))[1] as last_status,
  (array_agg(r.error order by r.started_at desc))[1] as last_error,
  count(*) filter (where r.started_at > now() - interval '24 hours') as runs_24h,
  count(*) filter (where r.status = 'failed' and r.started_at > now() - interval '24 hours') as failed_24h
from ingestion_runs r
join data_sources s on s.id = r.source_id
left join chains c on c.id = r.chain_id
group by r.job_name, s.slug, c.slug;

grant select on v_token_overview, v_pool_detail, v_job_freshness to authenticated;
revoke all on v_token_overview, v_pool_detail, v_job_freshness from anon;
