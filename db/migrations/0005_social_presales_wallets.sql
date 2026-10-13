-- Phase 4: social intelligence, presale watchlist, wallet tracking.

-- ---------------------------------------------------------------------------
-- New sources (disabled until the operator adds credentials and enables them)
-- ---------------------------------------------------------------------------
insert into data_sources (slug, name, kind, base_url, docs_url, terms_url, enabled,
                          rate_limit_per_minute, daily_call_cap, freshness_sla_seconds, notes)
values
  ('alchemy', 'Alchemy (EVM transfers)', 'onchain', 'https://{network}.g.alchemy.com/v2',
   'https://docs.alchemy.com/reference/alchemy-getassettransfers', 'https://www.alchemy.com/terms-conditions/terms',
   false, 30, 20000, 3600, 'Free tier. Wallet transfer history for Ethereum, Base, BNB Chain.'),
  ('helius', 'Helius (Solana transfers)', 'onchain', 'https://api.helius.xyz/v0',
   'https://www.helius.dev/docs/api-reference/enhanced-transactions', 'https://www.helius.dev/terms',
   false, 30, 20000, 3600, 'Free tier. Parsed Solana transactions for tracked wallets.')
on conflict (slug) do nothing;

update data_sources set notes = 'Bot API: outbound alerts (Phase 5) and inbound messages from chats the bot was added to and the operator approved. No user-account (MTProto) access.',
                        freshness_sla_seconds = 3600
where slug = 'telegram_bot';

-- ---------------------------------------------------------------------------
-- Worker-private state (bot update offsets, sync cursors). Never exposed.
-- ---------------------------------------------------------------------------
create table worker_state (
  key         text primary key,
  value       jsonb not null,
  updated_at  timestamptz not null default now()
);
alter table worker_state enable row level security;
revoke all on worker_state from anon, authenticated;

-- Chats that messaged/added the bot but are not (yet) in the source registry.
-- Their content is NOT stored; only metadata so the owner can approve or ignore.
create table social_chat_requests (
  id            bigint generated always as identity primary key,
  platform      text not null default 'telegram',
  external_id   text not null,
  title         text,
  chat_type     text,
  first_seen_at timestamptz not null default now(),
  last_seen_at  timestamptz not null default now(),
  messages_seen integer not null default 0,
  status        text not null default 'pending' check (status in ('pending', 'approved', 'ignored')),
  constraint social_chat_requests_uq unique (platform, external_id)
);

alter table social_mentions
  add column mentioned_symbols text[] not null default '{}',
  add column origin text not null default 'collector' check (origin in ('collector', 'manual')),
  add column entered_by text;

alter table tracked_wallets
  add column sync_cursor text,
  add column last_synced_at timestamptz,
  add column last_sync_error text;

create index social_mentions_published_idx on social_mentions (published_at desc);
create index social_mentions_contract_idx on social_mentions (contract_address) where contract_address is not null;

-- ---------------------------------------------------------------------------
-- Read models
-- ---------------------------------------------------------------------------

-- A mention is "independent" when it is original (not forwarded) and is the
-- first mention of that token by its coordination cluster. Accounts in the same
-- coordination_group, or channels without an influencer, are clustered by
-- group/influencer/channel respectively.
create view v_mention_detail with (security_invoker = true) as
select
  m.id, m.published_at, m.collected_at, m.origin, m.category, m.promo_disclosure, m.is_forwarded,
  m.forwarded_from, m.referral_links, m.text_excerpt, m.source_url, m.contract_address, m.mentioned_symbols,
  m.project_name, m.token_id, m.presale_id, c.slug as chain,
  ch.id as channel_id, ch.platform, ch.handle as channel_handle, ch.title as channel_title,
  i.id as influencer_id, i.display_name as influencer_name,
  coalesce('group:' || i.coordination_group, 'influencer:' || i.id::text, 'channel:' || ch.id::text) as cluster,
  t.symbol as token_symbol, t.address as token_address, tc.slug as token_chain,
  o.first_price_usd, o.first_price_observed_at, o.price_24h_usd, o.price_7d_usd, o.price_30d_usd,
  o.max_gain_pct, o.max_drawdown_pct, o.exit_feasible, o.outcome_status
from social_mentions m
join social_channels ch on ch.id = m.channel_id
left join influencers i on i.id = coalesce(m.influencer_id, ch.influencer_id)
left join chains c on c.id = m.chain_id
left join tokens t on t.id = m.token_id
left join chains tc on tc.id = t.chain_id
left join mention_outcomes o on o.mention_id = m.id;

-- Per-influencer forward performance. Every promoted token counts, including
-- untradeable / delisted / no-price outcomes (no survivorship bias).
create view v_influencer_stats with (security_invoker = true) as
with firsts as (
  -- first mention of each token per influencer
  select distinct on (d.influencer_id, d.token_id) d.*
  from v_mention_detail d
  where d.influencer_id is not null and d.token_id is not null
  order by d.influencer_id, d.token_id, d.published_at
)
select
  i.id as influencer_id, i.display_name, i.coordination_group,
  (select count(*) from social_mentions m join social_channels ch on ch.id = m.channel_id
     where coalesce(m.influencer_id, ch.influencer_id) = i.id) as mentions,
  count(f.token_id) as projects,
  min(f.published_at) as first_mention_at,
  max(f.published_at) as last_mention_at,
  count(*) filter (where f.promo_disclosure = 'disclosed') as disclosed_promos,
  count(*) filter (where f.first_price_usd is not null and f.price_24h_usd is not null) as with_24h,
  avg((f.price_24h_usd / f.first_price_usd - 1) * 100)
    filter (where f.first_price_usd > 0 and f.price_24h_usd is not null) as avg_return_24h_pct,
  avg((f.price_7d_usd / f.first_price_usd - 1) * 100)
    filter (where f.first_price_usd > 0 and f.price_7d_usd is not null) as avg_return_7d_pct,
  percentile_cont(0.5) within group (order by (f.price_7d_usd / f.first_price_usd - 1) * 100)
    filter (where f.first_price_usd > 0 and f.price_7d_usd is not null) as median_return_7d_pct,
  avg(f.max_gain_pct) as avg_max_gain_pct,
  avg(f.max_drawdown_pct) as avg_max_drawdown_pct,
  count(*) filter (where f.outcome_status in ('untradeable', 'delisted') or f.max_drawdown_pct <= -80) as failed,
  count(*) filter (where f.outcome_status = 'no_price') as no_price,
  count(*) filter (where f.exit_feasible is false) as exit_infeasible
from influencers i
left join firsts f on f.influencer_id = i.id
group by i.id, i.display_name, i.coordination_group;

-- Possible coordinated promotion: the same token pushed by >= 2 clusters within
-- 30 minutes, the same referral link across clusters, or identical text.
create view v_coordination_signals with (security_invoker = true) as
select 'same_token_30min'::text as signal, a.token_id::text as subject,
       min(least(a.published_at, b.published_at)) as first_at,
       array_agg(distinct a.cluster) || array_agg(distinct b.cluster) as clusters
from v_mention_detail a
join v_mention_detail b on b.token_id = a.token_id and b.cluster <> a.cluster
  and b.published_at between a.published_at - interval '30 minutes' and a.published_at + interval '30 minutes'
where a.token_id is not null
group by a.token_id
union all
select 'shared_referral_link', r.link, min(d.published_at), array_agg(distinct d.cluster)
from v_mention_detail d cross join lateral unnest(d.referral_links) as r(link)
group by r.link having count(distinct d.cluster) >= 2
union all
select 'identical_text', m.content_hash, min(d.published_at), array_agg(distinct d.cluster)
from social_mentions m join v_mention_detail d on d.id = m.id
where m.content_hash is not null
group by m.content_hash having count(distinct d.cluster) >= 2;

create view v_presale_score_latest with (security_invoker = true) as
select distinct on (o.presale_id)
  o.id as score_id, o.presale_id, o.scoring_version, o.scored_at, o.data_cutoff_at, o.total, o.components,
  o.missing_data, o.risk_flags
from opportunity_scores o where o.scorecard = 'presale'
order by o.presale_id, o.scored_at desc;

create view v_wallet_overview with (security_invoker = true) as
select w.id, c.slug as chain, w.address, w.label, w.category, w.enabled, w.notes, w.created_at,
       w.last_synced_at, w.last_sync_error,
       (select count(*) from wallet_events e where e.wallet_id = w.id and e.block_time > now() - interval '7 days') as events_7d,
       (select max(e.block_time) from wallet_events e where e.wallet_id = w.id) as last_event_at
from tracked_wallets w join chains c on c.id = w.chain_id;

create view v_wallet_events with (security_invoker = true) as
select e.id, e.wallet_id, w.label as wallet_label, c.slug as chain, e.tx_hash, e.block_time, e.event_type,
       e.token_id, coalesce(t.symbol, e.token_address) as token, e.token_address, e.amount, e.value_usd,
       e.counterparty, s.slug as source
from wallet_events e
join tracked_wallets w on w.id = e.wallet_id
join chains c on c.id = e.chain_id
left join tokens t on t.id = e.token_id
join data_sources s on s.id = e.source_id;

-- ---------------------------------------------------------------------------
-- RLS: owners curate the social registry, mentions (manual), presale claims.
-- ---------------------------------------------------------------------------
alter table social_chat_requests enable row level security;
revoke all on social_chat_requests from anon;
grant select, update on social_chat_requests to authenticated;
create policy social_chat_requests_read on social_chat_requests for select to authenticated using (public.is_app_user());
create policy social_chat_requests_owner on social_chat_requests for update to authenticated
  using (public.is_app_owner()) with check (public.is_app_owner());

do $$
declare t text;
begin
  foreach t in array array['influencers', 'social_channels', 'social_mentions', 'presale_claims']
  loop
    execute format('grant insert, update, delete on public.%I to authenticated', t);
    execute format(
      'create policy %I on public.%I for insert to authenticated with check (public.is_app_owner())',
      t || '_owner_insert', t);
    execute format(
      'create policy %I on public.%I for update to authenticated using (public.is_app_owner()) with check (public.is_app_owner())',
      t || '_owner_update', t);
    execute format(
      'create policy %I on public.%I for delete to authenticated using (public.is_app_owner())',
      t || '_owner_delete', t);
  end loop;
end
$$;

grant select on v_mention_detail, v_influencer_stats, v_coordination_signals, v_presale_score_latest,
  v_wallet_overview, v_wallet_events to authenticated;
revoke all on v_mention_detail, v_influencer_stats, v_coordination_signals, v_presale_score_latest,
  v_wallet_overview, v_wallet_events from anon;
