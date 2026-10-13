// Row shapes of the views/tables the dashboard reads (see db/migrations).
// Numeric columns arrive from PostgREST as numbers or strings; keep them loose
// and format via lib/format.

type N = number | string | null;

export type Link = { type: string; url: string; label?: string | null; source: string; observed_at: string };

export type TokenOverview = {
  token_id: number;
  chain: string;
  address: string;
  name: string | null;
  symbol: string | null;
  first_observed_at: string;
  earliest_pool_created_at: string | null;
  discovery_latency_s: number | null;
  first_source: string | null;
  links: Link[];
  is_excluded: boolean;
  exclusion_reason: string | null;
  pool_count: number;
  best_pool_id: number | null;
  best_pool_address: string | null;
  best_pool_dex: string | null;
  quote_symbol: string | null;
  price_usd: N;
  liquidity_usd: N;
  volume_h1_usd: N;
  volume_h24_usd: N;
  buys_h24: number | null;
  sells_h24: number | null;
  price_change_h24: N;
  market_cap_usd: N;
  fdv_usd: N;
  market_observed_at: string | null;
  market_source: string | null;
};

export type PoolDetail = {
  pool_id: number;
  chain: string;
  address: string;
  token_id: number;
  dex: string | null;
  quote_symbol: string | null;
  pool_created_at: string | null;
  first_observed_at: string;
  first_source: string | null;
  price_usd: N;
  liquidity_usd: N;
  volume_h24_usd: N;
  volume_h1_usd: N;
  buys_h24: number | null;
  sells_h24: number | null;
  price_change_h24: N;
  market_cap_usd: N;
  fdv_usd: N;
  observed_at: string | null;
  market_source: string | null;
};

export type Snapshot = {
  observed_at: string;
  price_usd: N;
  liquidity_usd: N;
  volume_h24_usd: N;
  pool_id: number;
  resolution: string;
};

export type DataSource = {
  id: number;
  slug: string;
  name: string;
  kind: string;
  enabled: boolean;
  rate_limit_per_minute: number | null;
  daily_call_cap: number | null;
  freshness_sla_seconds: number;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
  circuit_state: string;
  circuit_open_until: string | null;
  docs_url: string | null;
  terms_url: string | null;
  notes: string | null;
};

export type JobFreshness = {
  job_name: string;
  source: string;
  chain: string | null;
  last_success_at: string | null;
  last_attempt_at: string | null;
  last_status: string | null;
  last_error: string | null;
  runs_24h: number;
  failed_24h: number;
};

export type HealthRow = {
  component: string;
  status: "ok" | "degraded" | "down" | "unknown";
  checked_at: string;
  last_ok_at: string | null;
  message: string | null;
  details: Record<string, unknown>;
};

export type UsageDaily = {
  day: string;
  source: string;
  calls: number;
  failed_calls: number;
  cost_usd: N;
};
