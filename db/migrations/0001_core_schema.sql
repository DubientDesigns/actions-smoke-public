-- Crypto Intelligence Terminal — core schema.
--
-- Conventions
--   * All timestamps are timestamptz and stored in UTC.
--   * Monetary/price values use unbounded numeric (memecoin prices can be 1e-15).
--   * EVM addresses are stored lowercase; Solana mints are stored case-preserved.
--     The application normalises before writing (see cit.chains.normalize_address).
--   * "Unknown" is always NULL, never 0 / false. A NULL security field means the
--     check was not performed or not supported, NOT that it passed.
--   * Workers connect with a privileged role (bypasses RLS). The browser only
--     ever talks to PostgREST with the anon key + user JWT, governed by RLS
--     (see 0002_rls.sql).

create extension if not exists pgcrypto;
create extension if not exists citext;

-- ---------------------------------------------------------------------------
-- Users / settings / audit
-- ---------------------------------------------------------------------------

-- Allowlist of people permitted to use the app. There is no public sign-up:
-- rows are inserted manually (see docs/OPERATIONS.md).
create table app_users (
  user_id     uuid primary key,
  email       citext not null unique,
  role        text not null default 'viewer' check (role in ('owner', 'viewer')),
  created_at  timestamptz not null default now()
);

-- Global, typed-by-convention configuration (scoring weights, budgets, alert
-- quiet hours, ...). Values are validated by Pydantic models in the backend.
create table app_settings (
  key         text primary key,
  value       jsonb not null,
  description text,
  updated_at  timestamptz not null default now(),
  updated_by  text
);

create table audit_log (
  id          bigint generated always as identity primary key,
  occurred_at timestamptz not null default now(),
  actor       text not null,              -- 'worker:<job>', 'user:<uuid>', 'system'
  action      text not null,
  entity      text,
  entity_id   text,
  details     jsonb not null default '{}'::jsonb
);
create index audit_log_occurred_idx on audit_log (occurred_at desc);
create index audit_log_entity_idx on audit_log (entity, entity_id);

-- ---------------------------------------------------------------------------
-- Reference data
-- ---------------------------------------------------------------------------

create table chains (
  id                     smallint primary key,
  slug                   text not null unique,       -- internal slug
  name                   text not null,
  is_evm                 boolean not null,
  evm_chain_id           integer unique,             -- 56, 1, 8453; NULL for Solana
  native_symbol          text not null,
  geckoterminal_network  text,                       -- provider-specific identifiers
  dexscreener_chain      text,
  goplus_chain           text,
  explorer_url           text,
  enabled                boolean not null default true
);

insert into chains (id, slug, name, is_evm, evm_chain_id, native_symbol,
                    geckoterminal_network, dexscreener_chain, goplus_chain, explorer_url)
values
  (1, 'bsc',      'BNB Chain', true,  56,   'BNB', 'bsc',    'bsc',      '56',     'https://bscscan.com'),
  (2, 'ethereum', 'Ethereum',  true,  1,    'ETH', 'eth',    'ethereum', '1',      'https://etherscan.io'),
  (3, 'solana',   'Solana',    false, null, 'SOL', 'solana', 'solana',   'solana', 'https://solscan.io'),
  (4, 'base',     'Base',      true,  8453, 'ETH', 'base',   'base',     '8453',   'https://basescan.org');

create table data_sources (
  id                       smallint generated always as identity primary key,
  slug                     text not null unique,
  name                     text not null,
  kind                     text not null check (kind in
                             ('market', 'security', 'social', 'presale', 'onchain', 'ai', 'notification', 'manual')),
  base_url                 text,
  docs_url                 text,
  terms_url                text,
  enabled                  boolean not null default true,
  -- Conservative per-provider budget enforced by the in-process limiter.
  rate_limit_per_minute    integer,
  daily_call_cap           integer,
  -- Freshness: the dashboard flags the source as stale after this many seconds.
  freshness_sla_seconds    integer not null default 3600,
  last_attempt_at          timestamptz,
  last_success_at          timestamptz,
  last_failure_at          timestamptz,
  last_error               text,
  consecutive_failures     integer not null default 0,
  circuit_state            text not null default 'closed' check (circuit_state in ('closed', 'open', 'half_open')),
  circuit_open_until       timestamptz,
  notes                    text,
  created_at               timestamptz not null default now()
);

insert into data_sources (slug, name, kind, base_url, docs_url, terms_url,
                          rate_limit_per_minute, daily_call_cap, freshness_sla_seconds, notes)
values
  ('geckoterminal', 'GeckoTerminal', 'market', 'https://api.geckoterminal.com/api/v2',
   'https://www.geckoterminal.com/dex-api', 'https://www.geckoterminal.com/terms-conditions',
   8, 8000, 1800, 'Public API; attribution to GeckoTerminal required when displaying data.'),
  ('dexscreener', 'DEX Screener', 'market', 'https://api.dexscreener.com',
   'https://docs.dexscreener.com/api/reference', 'https://docs.dexscreener.com/api/api-terms-and-conditions',
   50, 40000, 1800, 'Public API; per-endpoint limits (60 or 300 rpm). Budget kept well below.'),
  ('goplus', 'GoPlus Security', 'security', 'https://api.gopluslabs.io/api/v1',
   'https://docs.gopluslabs.io/reference/api-overview', 'https://gopluslabs.io/terms',
   20, 5000, 86400, 'Token security heuristics. Not an audit.'),
  ('rugcheck', 'RugCheck', 'security', 'https://api.rugcheck.xyz/v1',
   'https://api.rugcheck.xyz/swagger/index.html', null,
   10, 2000, 86400, 'Solana-specific risk report. Disabled until verified.'),
  ('telegram_bot', 'Telegram Bot API', 'notification', 'https://api.telegram.org',
   'https://core.telegram.org/bots/api', 'https://telegram.org/tos/bot-developers',
   20, null, 86400, 'Outbound alerts only.'),
  ('anthropic', 'Anthropic Claude API', 'ai', 'https://api.anthropic.com',
   'https://docs.anthropic.com', 'https://www.anthropic.com/legal/commercial-terms',
   10, 200, 86400, 'Optional. Hard-capped by ai_budget settings.'),
  ('manual', 'Manual entry', 'manual', null, null, null, null, null, 31536000,
   'Data entered by an operator. Always shown with its entering user and time.');

update data_sources set enabled = false where slug in ('rugcheck', 'telegram_bot', 'anthropic');

create table ingestion_runs (
  id              bigint generated always as identity primary key,
  source_id       smallint not null references data_sources(id),
  job_name        text not null,
  chain_id        smallint references chains(id),
  started_at      timestamptz not null default now(),
  finished_at     timestamptz,
  status          text not null default 'running'
                    check (status in ('running', 'success', 'partial', 'failed', 'skipped')),
  http_calls      integer not null default 0,
  items_fetched   integer not null default 0,
  items_new       integer not null default 0,
  items_updated   integer not null default 0,
  error           text,
  details         jsonb not null default '{}'::jsonb
);
create index ingestion_runs_source_started_idx on ingestion_runs (source_id, started_at desc);
create index ingestion_runs_job_started_idx on ingestion_runs (job_name, started_at desc);
create index ingestion_runs_running_idx on ingestion_runs (status) where status = 'running';

-- ---------------------------------------------------------------------------
-- Market data
-- ---------------------------------------------------------------------------

create table tokens (
  id                       bigint generated always as identity primary key,
  chain_id                 smallint not null references chains(id),
  address                  text not null,             -- normalised contract / mint address
  name                     text,
  symbol                   text,
  decimals                 smallint,
  -- Earliest moment *we* saw the token (discovery latency = this - earliest pool creation).
  first_observed_at        timestamptz not null default now(),
  first_observed_source_id smallint references data_sources(id),
  earliest_pool_created_at timestamptz,
  -- Project links with provenance: [{"type":"website","url":"...","source":"dexscreener","observed_at":"..."}]
  links                    jsonb not null default '[]'::jsonb,
  -- Quote/base assets (WETH, WBNB, USDC...) are flagged so discovery ignores them.
  is_quote_asset           boolean not null default false,
  is_excluded              boolean not null default false,
  exclusion_reason         text,
  updated_at               timestamptz not null default now(),
  constraint tokens_chain_address_uq unique (chain_id, address)
);
create index tokens_first_observed_idx on tokens (first_observed_at desc);
create index tokens_symbol_idx on tokens (lower(symbol));
create index tokens_chain_observed_idx on tokens (chain_id, first_observed_at desc);

create table pools (
  id                       bigint generated always as identity primary key,
  chain_id                 smallint not null references chains(id),
  address                  text not null,             -- pair / pool / AMM id
  base_token_id            bigint not null references tokens(id) on delete cascade,
  quote_token_id           bigint references tokens(id),
  quote_symbol             text,
  dex                      text,                       -- provider dex slug, e.g. 'pancakeswap_v2'
  pool_created_at          timestamptz,               -- as reported by provider; NULL if unknown
  first_observed_at        timestamptz not null default now(),
  first_observed_source_id smallint references data_sources(id),
  updated_at               timestamptz not null default now(),
  constraint pools_chain_address_uq unique (chain_id, address)
);
create index pools_base_token_idx on pools (base_token_id);
create index pools_created_idx on pools (pool_created_at desc);

-- Point-in-time observations. observed_at is the time the provider response was
-- received (our clock, UTC). Paper fills may only use snapshots whose
-- observed_at is >= the order's earliest permissible fill time (see 0001 trigger).
create table market_snapshots (
  id                 bigint generated always as identity primary key,
  pool_id            bigint not null references pools(id) on delete cascade,
  token_id           bigint not null references tokens(id) on delete cascade,
  source_id          smallint not null references data_sources(id),
  ingestion_run_id   bigint references ingestion_runs(id) on delete set null,
  observed_at        timestamptz not null,
  price_usd          numeric,
  price_native       numeric,
  liquidity_usd      numeric,
  volume_m5_usd      numeric,
  volume_h1_usd      numeric,
  volume_h6_usd      numeric,
  volume_h24_usd     numeric,
  buys_m5            integer,
  sells_m5           integer,
  buys_h1            integer,
  sells_h1           integer,
  buys_h24           integer,
  sells_h24          integer,
  price_change_m5    numeric,   -- percent
  price_change_h1    numeric,
  price_change_h24   numeric,
  -- Market cap is only stored when the provider reports a circulating-supply
  -- based value. FDV is stored separately. They are never substituted.
  market_cap_usd     numeric,
  fdv_usd            numeric,
  -- 'raw' = as fetched; 'hourly'/'daily' = retention downsampled rows.
  resolution         text not null default 'raw' check (resolution in ('raw', 'hourly', 'daily'))
);
create index market_snapshots_token_time_idx on market_snapshots (token_id, observed_at desc);
create index market_snapshots_pool_time_idx on market_snapshots (pool_id, observed_at desc);
create index market_snapshots_time_idx on market_snapshots (observed_at);

-- Latest-known state per pool, maintained by the worker (cheap dashboard reads).
create table pool_latest (
  pool_id            bigint primary key references pools(id) on delete cascade,
  token_id           bigint not null references tokens(id) on delete cascade,
  snapshot_id        bigint references market_snapshots(id) on delete set null,
  source_id          smallint not null references data_sources(id),
  observed_at        timestamptz not null,
  price_usd          numeric,
  liquidity_usd      numeric,
  volume_h24_usd     numeric,
  volume_h1_usd      numeric,
  buys_h24           integer,
  sells_h24          integer,
  price_change_h24   numeric,
  market_cap_usd     numeric,
  fdv_usd            numeric
);
create index pool_latest_token_idx on pool_latest (token_id);
create index pool_latest_liquidity_idx on pool_latest (liquidity_usd desc nulls last);

-- ---------------------------------------------------------------------------
-- Security
-- ---------------------------------------------------------------------------

create table security_assessments (
  id               bigint generated always as identity primary key,
  token_id         bigint not null references tokens(id) on delete cascade,
  source_id        smallint not null references data_sources(id),
  assessed_at      timestamptz not null default now(),
  -- Stale after this moment; stale assessments are displayed as stale and
  -- treated as 'unknown' by scoring.
  valid_until      timestamptz not null,
  coverage         text not null check (coverage in ('complete', 'partial', 'unsupported', 'not_found', 'error')),
  -- Overall label is derived from checks; 'unknown' when coverage is insufficient.
  risk_level       text not null check (risk_level in ('critical', 'high', 'medium', 'low', 'unknown')),
  hard_excluded    boolean not null default false,
  needs_review     boolean not null default false,
  -- [{"key":"honeypot","status":"pass|risk|warn|unknown|unsupported","value":...,"detail":"...","source":"goplus"}]
  checks           jsonb not null default '[]'::jsonb,
  risk_flags       text[] not null default '{}',
  -- Denormalised for filtering; NULL = unknown.
  is_honeypot      boolean,
  buy_tax_pct      numeric,
  sell_tax_pct     numeric,
  top10_holder_pct numeric,
  raw              jsonb,
  ruleset_version  text not null
);
create index security_assessments_token_time_idx on security_assessments (token_id, assessed_at desc);
create index security_assessments_excluded_idx on security_assessments (hard_excluded) where hard_excluded;

-- ---------------------------------------------------------------------------
-- Presales (separate from trading tokens)
-- ---------------------------------------------------------------------------

create table presales (
  id                     bigint generated always as identity primary key,
  project_name           text not null,
  slug                   text not null unique,
  official_website       text,
  chain_id               smallint references chains(id),
  platform               text,                       -- launchpad / self-hosted / unknown
  platform_url           text,
  sale_type              text not null default 'unknown'
                           check (sale_type in ('public', 'private', 'whitelist', 'fair_launch', 'unknown')),
  status                 text not null default 'unknown'
                           check (status in ('rumoured', 'announced', 'upcoming', 'live', 'ended', 'cancelled', 'tge_done', 'unknown')),
  announced_at           timestamptz,
  sale_start_at          timestamptz,
  sale_end_at            timestamptz,
  tge_at                 timestamptz,
  sale_price_usd         numeric,
  claimed_valuation_usd  numeric,
  min_investment_usd     numeric,
  hard_cap_usd           numeric,
  soft_cap_usd           numeric,
  vesting_terms          jsonb,      -- structured schedule when known, see docs/SCHEMA.md
  lockup_terms           text,
  audit_claims           jsonb not null default '[]'::jsonb,
  team_info              text,
  token_id               bigint references tokens(id),  -- set once it trades
  -- Verification describes the provenance of the record, never the project's quality.
  verification_status    text not null default 'unverified'
                           check (verification_status in
                             ('unverified', 'official_source_seen', 'partially_verified', 'disputed', 'red_flag')),
  source_urls            text[] not null default '{}',
  notes                  text,
  created_by             text not null,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);
create index presales_status_idx on presales (status, sale_end_at);
create index presales_chain_idx on presales (chain_id);

-- Individual claims with provenance; presales.* columns hold the operator's
-- current best value, claims hold where each value came from.
create table presale_claims (
  id            bigint generated always as identity primary key,
  presale_id    bigint not null references presales(id) on delete cascade,
  field         text not null,
  value         jsonb not null,
  source_url    text,
  source_kind   text not null check (source_kind in ('official', 'launchpad', 'third_party', 'social', 'manual')),
  observed_at   timestamptz not null default now(),
  verification  text not null default 'unverified'
                  check (verification in ('unverified', 'consistent', 'contradicted', 'verified_onchain'))
);
create index presale_claims_presale_idx on presale_claims (presale_id, field);

-- ---------------------------------------------------------------------------
-- Social intelligence
-- ---------------------------------------------------------------------------

create table influencers (
  id                 bigint generated always as identity primary key,
  display_name       text not null,
  notes              text,
  -- Operator-assigned cluster for suspected coordinated accounts. Accounts in the
  -- same cluster are never counted as independent mentions.
  coordination_group text,
  created_at         timestamptz not null default now()
);

-- Source registry: a channel/account we are authorised to read.
create table social_channels (
  id                 bigint generated always as identity primary key,
  platform           text not null check (platform in ('telegram', 'x', 'youtube', 'web', 'rss', 'other')),
  external_id        text not null,                 -- channel id / handle / feed URL
  handle             text,
  title              text,
  url                text,
  influencer_id      bigint references influencers(id) on delete set null,
  -- Why we are allowed to read it. Private groups require explicit authorisation.
  access_basis       text not null check (access_basis in ('public', 'authorised_member', 'official_project')),
  is_official_project boolean not null default false,
  enabled            boolean not null default true,
  last_collected_at  timestamptz,
  created_at         timestamptz not null default now(),
  constraint social_channels_platform_ext_uq unique (platform, external_id)
);

create table social_mentions (
  id                     bigint generated always as identity primary key,
  channel_id             bigint not null references social_channels(id) on delete cascade,
  influencer_id          bigint references influencers(id) on delete set null,
  external_message_id    text not null,
  published_at           timestamptz not null,
  collected_at           timestamptz not null default now(),
  token_id               bigint references tokens(id) on delete set null,
  presale_id             bigint references presales(id) on delete set null,
  chain_id               smallint references chains(id),
  contract_address       text,                       -- exact address when present in the message
  project_name           text,
  source_url             text,
  category               text not null default 'other'
                           check (category in ('call', 'promotion', 'announcement', 'news', 'analysis', 'warning', 'other')),
  promo_disclosure       text not null default 'unknown'
                           check (promo_disclosure in ('disclosed', 'not_disclosed', 'unknown')),
  is_forwarded           boolean not null default false,
  forwarded_from         text,
  referral_links         text[] not null default '{}',
  -- Short excerpt only; full private-chat content is never stored.
  text_excerpt           text,
  content_hash           text,
  constraint social_mentions_channel_msg_uq unique (channel_id, external_message_id)
);
create index social_mentions_token_time_idx on social_mentions (token_id, published_at desc);
create index social_mentions_influencer_time_idx on social_mentions (influencer_id, published_at desc);
create index social_mentions_hash_idx on social_mentions (content_hash);

-- Forward performance of a mention, measured from the first price we could
-- observe AFTER the mention was published (never before).
create table mention_outcomes (
  mention_id               bigint primary key references social_mentions(id) on delete cascade,
  first_price_usd          numeric,
  first_price_observed_at  timestamptz,
  liquidity_at_first_usd   numeric,
  price_24h_usd            numeric,
  price_7d_usd             numeric,
  price_30d_usd            numeric,
  max_gain_pct             numeric,
  max_drawdown_pct         numeric,
  exit_feasible            boolean,           -- could a reference position exit within slippage limits
  outcome_status           text not null default 'pending'
                             check (outcome_status in ('pending', 'tracking', 'final', 'untradeable', 'delisted', 'no_price')),
  updated_at               timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Wallets
-- ---------------------------------------------------------------------------

create table tracked_wallets (
  id          bigint generated always as identity primary key,
  chain_id    smallint not null references chains(id),
  address     text not null,
  label       text not null,
  category    text not null default 'other'
                check (category in ('deployer', 'smart_money', 'team', 'exchange', 'influencer', 'whale', 'other')),
  notes       text,
  enabled     boolean not null default true,
  created_by  text not null,
  created_at  timestamptz not null default now(),
  constraint tracked_wallets_chain_address_uq unique (chain_id, address)
);

create table wallet_events (
  id               bigint generated always as identity primary key,
  wallet_id        bigint not null references tracked_wallets(id) on delete cascade,
  chain_id         smallint not null references chains(id),
  tx_hash          text not null,
  log_index        integer not null default -1,
  block_number     bigint,
  block_time       timestamptz not null,
  event_type       text not null check (event_type in
                     ('buy', 'sell', 'transfer_in', 'transfer_out', 'deploy', 'add_liquidity', 'remove_liquidity', 'other')),
  token_id         bigint references tokens(id) on delete set null,
  token_address    text,
  amount           numeric,
  value_usd        numeric,
  counterparty     text,
  source_id        smallint not null references data_sources(id),
  raw              jsonb,
  collected_at     timestamptz not null default now(),
  constraint wallet_events_uq unique (wallet_id, chain_id, tx_hash, log_index)
);
create index wallet_events_wallet_time_idx on wallet_events (wallet_id, block_time desc);
create index wallet_events_token_time_idx on wallet_events (token_id, block_time desc);

-- ---------------------------------------------------------------------------
-- Scoring and research
-- ---------------------------------------------------------------------------

create table opportunity_scores (
  id                bigint generated always as identity primary key,
  token_id          bigint references tokens(id) on delete cascade,
  presale_id        bigint references presales(id) on delete cascade,
  scorecard         text not null check (scorecard in ('token', 'presale')),
  scoring_version   text not null,
  scored_at         timestamptz not null default now(),
  -- Latest data timestamp used; nothing observed after this went into the score.
  data_cutoff_at    timestamptz not null,
  total             numeric not null check (total >= 0 and total <= 100),
  components        jsonb not null,    -- {"market_structure":{"score":..,"max":25,"evidence":[..],"missing":[..]}, ...}
  missing_data      text[] not null default '{}',
  risk_flags        text[] not null default '{}',
  inputs_hash       text not null,
  constraint opportunity_scores_target_ck check (
    (scorecard = 'token' and token_id is not null and presale_id is null) or
    (scorecard = 'presale' and presale_id is not null and token_id is null))
);
create index opportunity_scores_token_time_idx on opportunity_scores (token_id, scored_at desc);
create index opportunity_scores_presale_time_idx on opportunity_scores (presale_id, scored_at desc);
create index opportunity_scores_total_idx on opportunity_scores (scored_at desc, total desc);

create table research_reports (
  id               bigint generated always as identity primary key,
  token_id         bigint references tokens(id) on delete cascade,
  presale_id       bigint references presales(id) on delete cascade,
  status           text not null check (status in ('queued', 'generating', 'complete', 'failed', 'rejected_schema', 'skipped_budget')),
  prompt_version   text not null,
  model            text,
  -- Hash of the evidence bundle; reports regenerate only when it changes.
  input_hash       text not null,
  evidence         jsonb not null,       -- the exact (sanitised) inputs given to the model, with provenance
  content          jsonb,                -- schema-validated output
  research_priority text check (research_priority in ('high', 'medium', 'low', 'avoid', 'insufficient_data')),
  input_tokens     integer,
  output_tokens    integer,
  cost_usd         numeric,
  error            text,
  created_at       timestamptz not null default now(),
  completed_at     timestamptz,
  constraint research_reports_target_ck check (num_nonnulls(token_id, presale_id) = 1)
);
create unique index research_reports_dedup_uq
  on research_reports (coalesce(token_id, 0), coalesce(presale_id, 0), prompt_version, input_hash)
  where status in ('queued', 'generating', 'complete');
create index research_reports_token_idx on research_reports (token_id, created_at desc);
create index research_reports_presale_idx on research_reports (presale_id, created_at desc);

-- ---------------------------------------------------------------------------
-- Watchlists
-- ---------------------------------------------------------------------------

create table watchlists (
  id          bigint generated always as identity primary key,
  owner_id    uuid not null,
  name        text not null,
  created_at  timestamptz not null default now(),
  constraint watchlists_owner_name_uq unique (owner_id, name)
);

create table watchlist_items (
  id            bigint generated always as identity primary key,
  watchlist_id  bigint not null references watchlists(id) on delete cascade,
  token_id      bigint references tokens(id) on delete cascade,
  presale_id    bigint references presales(id) on delete cascade,
  wallet_id     bigint references tracked_wallets(id) on delete cascade,
  note          text,
  added_at      timestamptz not null default now(),
  constraint watchlist_items_target_ck check (num_nonnulls(token_id, presale_id, wallet_id) = 1)
);
create unique index watchlist_items_uq
  on watchlist_items (watchlist_id, coalesce(token_id, 0), coalesce(presale_id, 0), coalesce(wallet_id, 0));
create index watchlist_items_token_idx on watchlist_items (token_id);

-- Saved dashboard filters per user.
create table saved_views (
  id          bigint generated always as identity primary key,
  owner_id    uuid not null,
  page        text not null,
  name        text not null,
  params      jsonb not null,
  created_at  timestamptz not null default now(),
  constraint saved_views_uq unique (owner_id, page, name)
);

-- ---------------------------------------------------------------------------
-- Alerts
-- ---------------------------------------------------------------------------

create table alerts (
  id                 bigint generated always as identity primary key,
  category           text not null check (category in (
                       'new_token', 'multi_source_mention', 'liquidity_change', 'wallet_activity',
                       'contract_risk', 'presale', 'paper_rule', 'source_outage', 'spend_threshold',
                       'daily_digest', 'health_report')),
  severity           text not null check (severity in ('info', 'low', 'medium', 'high', 'critical')),
  -- Same dedup_key within the category cooldown is suppressed.
  dedup_key          text not null,
  title              text not null,
  body               text not null,
  token_id           bigint references tokens(id) on delete set null,
  presale_id         bigint references presales(id) on delete set null,
  payload            jsonb not null default '{}'::jsonb,
  created_at         timestamptz not null default now(),
  status             text not null default 'pending'
                       check (status in ('pending', 'sent', 'suppressed', 'deferred', 'digested', 'failed')),
  status_reason      text,
  attempts           integer not null default 0,
  sent_at            timestamptz
);
create index alerts_dedup_idx on alerts (dedup_key, created_at desc);
create index alerts_status_idx on alerts (status, created_at);
create index alerts_created_idx on alerts (created_at desc);

-- ---------------------------------------------------------------------------
-- Paper trading (no real funds; no keys; no execution)
-- ---------------------------------------------------------------------------

create table strategy_definitions (
  id           bigint generated always as identity primary key,
  slug         text not null,
  version      integer not null,
  name         text not null,
  description  text,
  -- Immutable once created: changing rules means a new version.
  rules        jsonb not null,
  is_active    boolean not null default false,
  created_at   timestamptz not null default now(),
  constraint strategy_definitions_slug_version_uq unique (slug, version)
);

create table paper_portfolios (
  id                   bigint generated always as identity primary key,
  owner_id             uuid,                       -- NULL for system/strategy portfolios
  name                 text not null,
  base_currency        text not null default 'SGD',
  starting_capital     numeric not null default 10000 check (starting_capital > 0),
  -- SGD per USD used to convert; recorded per fill too.
  fee_bps              numeric not null default 30,     -- per side, DEX LP fee + aggregator
  execution_delay_seconds integer not null default 60,  -- earliest fill = signal_at + delay
  max_pool_liquidity_pct numeric not null default 2,    -- refuse fills larger than this % of pool liquidity
  slippage_model       jsonb not null default '{"type":"constant_product","extra_bps":50}'::jsonb,
  strategy_id          bigint references strategy_definitions(id),
  is_active            boolean not null default true,
  created_at           timestamptz not null default now()
);

create table paper_positions (
  id                  bigint generated always as identity primary key,
  portfolio_id        bigint not null references paper_portfolios(id) on delete cascade,
  token_id            bigint references tokens(id),
  presale_id          bigint references presales(id),
  status              text not null default 'open'
                        check (status in ('pending_entry', 'open', 'vesting', 'closed', 'untradeable', 'written_off')),
  opened_at           timestamptz,
  closed_at           timestamptz,
  quantity            numeric not null default 0,
  locked_quantity     numeric not null default 0,      -- presale vesting
  cost_basis_usd      numeric not null default 0,
  realised_pnl_usd    numeric not null default 0,
  stop_loss_pct       numeric,
  take_profit         jsonb,                           -- [{"gain_pct":100,"sell_pct":50}, ...]
  vesting_schedule    jsonb,
  max_favourable_pct  numeric,                         -- MFE
  max_adverse_pct     numeric,                         -- MAE
  untradeable_reason  text,
  constraint paper_positions_target_ck check (num_nonnulls(token_id, presale_id) >= 1)
);
create index paper_positions_portfolio_idx on paper_positions (portfolio_id, status);

create table strategy_evaluations (
  id                 bigint generated always as identity primary key,
  strategy_id        bigint not null references strategy_definitions(id),
  token_id           bigint references tokens(id) on delete cascade,
  presale_id         bigint references presales(id) on delete cascade,
  evaluated_at       timestamptz not null default now(),
  data_cutoff_at     timestamptz not null,
  -- Every evaluation is recorded, including rejections, to prevent cherry-picking.
  decision           text not null check (decision in ('enter', 'exit', 'reject', 'skip', 'missed', 'failed')),
  reasons            jsonb not null default '[]'::jsonb,
  inputs             jsonb not null,
  inputs_hash        text not null
);
create index strategy_evaluations_strategy_time_idx on strategy_evaluations (strategy_id, evaluated_at desc);
create index strategy_evaluations_token_idx on strategy_evaluations (token_id);

create table paper_orders (
  id                     bigint generated always as identity primary key,
  portfolio_id           bigint not null references paper_portfolios(id) on delete cascade,
  position_id            bigint references paper_positions(id) on delete set null,
  token_id               bigint references tokens(id),
  presale_id             bigint references presales(id),
  side                   text not null check (side in ('buy', 'sell')),
  order_type             text not null check (order_type in ('market', 'stop_loss', 'take_profit', 'presale_allocation', 'vesting_unlock')),
  origin                 text not null check (origin in ('manual', 'strategy')),
  strategy_evaluation_id bigint references strategy_evaluations(id),
  -- The moment the information motivating the order became available to us.
  signal_at              timestamptz not null,
  -- No fill may use a price observed before this (signal_at + execution delay).
  earliest_fill_at       timestamptz not null,
  requested_notional_usd numeric,
  requested_quantity     numeric,
  sell_fraction          numeric check (sell_fraction is null or (sell_fraction > 0 and sell_fraction <= 1)),
  status                 text not null default 'pending'
                           check (status in ('pending', 'filled', 'partially_filled', 'rejected', 'expired', 'cancelled')),
  reject_reason          text,
  created_at             timestamptz not null default now(),
  constraint paper_orders_fill_after_signal_ck check (earliest_fill_at >= signal_at)
);
create index paper_orders_portfolio_idx on paper_orders (portfolio_id, created_at desc);
create index paper_orders_pending_idx on paper_orders (status) where status = 'pending';

create table paper_fills (
  id                   bigint generated always as identity primary key,
  order_id             bigint not null references paper_orders(id) on delete cascade,
  snapshot_id          bigint references market_snapshots(id) on delete set null,
  price_observed_at    timestamptz not null,         -- observed_at of the price used
  filled_at            timestamptz not null default now(),
  reference_price_usd  numeric not null,             -- quoted price
  executed_price_usd   numeric not null,             -- after slippage
  quantity             numeric not null check (quantity > 0),
  fee_usd              numeric not null default 0,
  slippage_bps         numeric not null default 0,
  liquidity_usd        numeric,
  fx_sgd_per_usd       numeric
);
create index paper_fills_order_idx on paper_fills (order_id);

-- Look-ahead guard: a fill may never use a price observed before the order's
-- earliest_fill_at. Enforced in the database so no code path can bypass it.
create function paper_fills_no_lookahead() returns trigger
language plpgsql as $$
declare
  v_earliest timestamptz;
begin
  select earliest_fill_at into v_earliest from paper_orders where id = new.order_id;
  if new.price_observed_at < v_earliest then
    raise exception 'look-ahead violation: price observed at % is before earliest fill time %',
      new.price_observed_at, v_earliest using errcode = 'check_violation';
  end if;
  return new;
end
$$;

create trigger paper_fills_no_lookahead_trg
  before insert or update on paper_fills
  for each row execute function paper_fills_no_lookahead();

-- Daily equity marks for the equity curve and drawdown.
create table paper_equity_marks (
  portfolio_id     bigint not null references paper_portfolios(id) on delete cascade,
  marked_at        timestamptz not null,
  cash_usd         numeric not null,
  positions_value_usd numeric not null,       -- liquidity-haircut value, not naive mark
  equity_usd       numeric not null,
  equity_sgd       numeric,
  primary key (portfolio_id, marked_at)
);

-- ---------------------------------------------------------------------------
-- Operations
-- ---------------------------------------------------------------------------

create table api_usage (
  id              bigint generated always as identity primary key,
  source_id       smallint not null references data_sources(id),
  occurred_at     timestamptz not null default now(),
  job_name        text,
  endpoint        text not null,
  status_code     integer,
  latency_ms      integer,
  ok              boolean not null,
  input_tokens    integer,
  output_tokens   integer,
  cost_usd        numeric not null default 0
);
create index api_usage_source_time_idx on api_usage (source_id, occurred_at desc);
create index api_usage_time_idx on api_usage (occurred_at);

-- Latest heartbeat / status per component (scheduler, each job, web, db, backups).
create table system_health (
  component     text primary key,
  status        text not null check (status in ('ok', 'degraded', 'down', 'unknown')),
  checked_at    timestamptz not null default now(),
  last_ok_at    timestamptz,
  message       text,
  details       jsonb not null default '{}'::jsonb
);

create view api_usage_daily as
select
  date_trunc('day', u.occurred_at) as day,
  s.slug as source,
  count(*) as calls,
  count(*) filter (where not u.ok) as failed_calls,
  coalesce(sum(u.input_tokens), 0) as input_tokens,
  coalesce(sum(u.output_tokens), 0) as output_tokens,
  coalesce(sum(u.cost_usd), 0) as cost_usd
from api_usage u
join data_sources s on s.id = u.source_id
group by 1, 2;

-- Generic updated_at maintenance.
create function set_updated_at() returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end
$$;

create trigger tokens_updated_at before update on tokens for each row execute function set_updated_at();
create trigger pools_updated_at before update on pools for each row execute function set_updated_at();
create trigger presales_updated_at before update on presales for each row execute function set_updated_at();
create trigger app_settings_updated_at before update on app_settings for each row execute function set_updated_at();
