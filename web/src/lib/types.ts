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
  risk_level: RiskLevel | null;
  hard_excluded: boolean | null;
  needs_review: boolean | null;
  security_coverage: string | null;
  security_assessed_at: string | null;
  security_valid_until: string | null;
  score_total: N;
  scored_at: string | null;
  scoring_version: string | null;
  score_risk_flags: string[] | null;
};

export type RiskLevel = "critical" | "high" | "medium" | "low" | "unknown";
export type CheckStatus = "pass" | "warn" | "risk" | "unknown" | "unsupported";

export type SecurityCheck = {
  key: string;
  label: string;
  status: CheckStatus;
  value: unknown;
  detail: string | null;
  source: string;
};

export type SecurityLatest = {
  assessment_id: number;
  token_id: number;
  chain: string;
  address: string;
  symbol: string | null;
  name: string | null;
  assessed_at: string;
  valid_until: string;
  is_stale: boolean;
  coverage: string;
  risk_level: RiskLevel;
  hard_excluded: boolean;
  needs_review: boolean;
  checks: SecurityCheck[];
  risk_flags: string[];
  is_honeypot: boolean | null;
  buy_tax_pct: N;
  sell_tax_pct: N;
  top10_holder_pct: N;
  ruleset_version: string;
  source: string;
};

export type ScoreComponent = { score: number; max: number; evidence: string[]; missing: string[] };

export type ScoreLatest = {
  score_id: number;
  token_id: number;
  scoring_version: string;
  scored_at: string;
  data_cutoff_at: string;
  total: N;
  components: Record<string, ScoreComponent>;
  missing_data: string[];
  risk_flags: string[];
  inputs_hash: string;
};

export type SavedView = { id: number; page: string; name: string; params: Record<string, string> };

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

export type Presale = {
  id: number;
  project_name: string;
  slug: string;
  official_website: string | null;
  chain_id: number | null;
  platform: string | null;
  platform_url: string | null;
  sale_type: string;
  status: string;
  sale_start_at: string | null;
  sale_end_at: string | null;
  tge_at: string | null;
  sale_price_usd: N;
  claimed_valuation_usd: N;
  min_investment_usd: N;
  hard_cap_usd: N;
  vesting_terms: Record<string, unknown> | null;
  lockup_terms: string | null;
  audit_claims: string[];
  team_info: string | null;
  verification_status: string;
  source_urls: string[];
  notes: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
};

export type PresaleClaim = {
  id: number;
  field: string;
  value: unknown;
  source_url: string | null;
  source_kind: string;
  observed_at: string;
  verification: string;
};

export type PresaleScore = Omit<ScoreLatest, "token_id" | "inputs_hash"> & { presale_id: number };

export type InfluencerStats = {
  influencer_id: number;
  display_name: string;
  coordination_group: string | null;
  mentions: number;
  projects: number;
  first_mention_at: string | null;
  last_mention_at: string | null;
  disclosed_promos: number;
  with_24h: number;
  avg_return_24h_pct: N;
  avg_return_7d_pct: N;
  median_return_7d_pct: N;
  avg_max_gain_pct: N;
  avg_max_drawdown_pct: N;
  failed: number;
  no_price: number;
  exit_infeasible: number;
};

export type MentionDetail = {
  id: number;
  published_at: string;
  origin: string;
  category: string;
  promo_disclosure: string;
  is_forwarded: boolean;
  forwarded_from: string | null;
  referral_links: string[];
  text_excerpt: string | null;
  source_url: string | null;
  contract_address: string | null;
  mentioned_symbols: string[];
  project_name: string | null;
  token_id: number | null;
  chain: string | null;
  channel_id: number;
  platform: string;
  channel_handle: string | null;
  channel_title: string | null;
  influencer_name: string | null;
  cluster: string;
  token_symbol: string | null;
  token_address: string | null;
  token_chain: string | null;
  first_price_usd: N;
  price_24h_usd: N;
  price_7d_usd: N;
  max_gain_pct: N;
  max_drawdown_pct: N;
  exit_feasible: boolean | null;
  outcome_status: string | null;
};

export type CoordinationSignal = { signal: string; subject: string; first_at: string; clusters: string[] };

export type Channel = {
  id: number;
  platform: string;
  external_id: string;
  handle: string | null;
  title: string | null;
  url: string | null;
  influencer_id: number | null;
  access_basis: string;
  is_official_project: boolean;
  enabled: boolean;
  last_collected_at: string | null;
};

export type ChatRequest = {
  id: number;
  external_id: string;
  title: string | null;
  chat_type: string | null;
  first_seen_at: string;
  last_seen_at: string;
  messages_seen: number;
  status: string;
};

export type WalletOverview = {
  id: number;
  chain: string;
  address: string;
  label: string;
  category: string;
  enabled: boolean;
  notes: string | null;
  last_synced_at: string | null;
  last_sync_error: string | null;
  events_7d: number;
  last_event_at: string | null;
};

export type WalletEvent = {
  id: number;
  wallet_id: number;
  wallet_label: string;
  chain: string;
  tx_hash: string;
  block_time: string;
  event_type: string;
  token_id: number | null;
  token: string | null;
  token_address: string | null;
  amount: N;
  value_usd: N;
  counterparty: string | null;
  source: string;
};

export type ResearchRow = {
  id: number;
  token_id: number | null;
  chain: string | null;
  address: string | null;
  symbol: string | null;
  name: string | null;
  status: string;
  prompt_version: string;
  model: string | null;
  research_priority: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: N;
  error: string | null;
  created_at: string;
  completed_at: string | null;
};

export type ReportClaim = { statement: string; evidence_ids: string[] };
export type ReportSection = { assessment: string; evidence_ids: string[]; confidence: string };
export type ReportContent = {
  executive_summary: string;
  project_description: string;
  evidence_for: ReportClaim[];
  evidence_against: ReportClaim[];
  tokenomics: ReportSection;
  contract_risks: ReportSection;
  liquidity_risks: ReportSection;
  community_quality: ReportSection;
  insider_concentration: ReportSection;
  catalysts: ReportSection;
  unknowns: string[];
  research_priority: string;
  priority_rationale: string;
};
export type EvidenceItem = { id: string; kind: string; source: string | null; observed_at: string | null } & Record<string, unknown>;

export type AlertRow = {
  id: number;
  category: string;
  severity: "info" | "low" | "medium" | "high" | "critical";
  title: string;
  body: string;
  token_id: number | null;
  presale_id: number | null;
  created_at: string;
  status: string;
  status_reason: string | null;
  attempts: number;
  sent_at: string | null;
};

export type SpendRow = { source: string; month: string; calls: number; input_tokens: number; output_tokens: number; cost_usd: N };

// Paper trading (simulation only).
export type PaperPortfolio = {
  id: number;
  name: string;
  owner_id: string | null;
  strategy_id: number | null;
  strategy_slug: string | null;
  strategy_version: number | null;
  base_currency: string;
  starting_capital: N;
  starting_capital_usd: N;
  fx_sgd_per_usd: N;
  fee_bps: N;
  execution_delay_seconds: number;
  max_pool_liquidity_pct: N;
  min_liquidity_usd: N;
  is_active: boolean;
  created_at: string;
  cash_usd: N;
  fees_usd: N;
  positions_value_usd: N;
  equity_usd: N;
  realised_pnl_usd: N;
  open_positions: number;
  closed_positions: number;
  untradeable_positions: number;
};

export type PaperPosition = {
  id: number;
  portfolio_id: number;
  token_id: number | null;
  presale_id: number | null;
  chain: string | null;
  address: string | null;
  symbol: string | null;
  presale_name: string | null;
  status: string;
  opened_at: string | null;
  closed_at: string | null;
  quantity: N;
  locked_quantity: N;
  cost_basis_usd: N;
  realised_pnl_usd: N;
  entry_price_usd: N;
  last_price_usd: N;
  last_value_usd: N;
  last_marked_at: string | null;
  unrealised_pnl_usd: N;
  stop_loss_pct: N;
  take_profit: { gain_pct: number; sell_pct: number }[] | null;
  max_favourable_pct: N;
  max_adverse_pct: N;
  untradeable_reason: string | null;
};

export type PaperOrder = {
  id: number;
  portfolio_id: number;
  position_id: number | null;
  chain: string | null;
  address: string | null;
  symbol: string | null;
  presale_name: string | null;
  side: "buy" | "sell";
  order_type: string;
  origin: "manual" | "strategy";
  signal_at: string;
  earliest_fill_at: string;
  expires_at: string | null;
  requested_notional_usd: N;
  sell_fraction: N;
  status: string;
  reject_reason: string | null;
  note: string | null;
  created_at: string;
  filled_at: string | null;
  price_observed_at: string | null;
  reference_price_usd: N;
  executed_price_usd: N;
  filled_quantity: N;
  filled_notional_usd: N;
  fee_usd: N;
  slippage_bps: N;
};

export type EquityMark = { portfolio_id: number; marked_at: string; cash_usd: N; positions_value_usd: N; equity_usd: N; equity_sgd: N };

export type PaperPerformance = {
  portfolio_id: number;
  name: string;
  strategy_slug: string | null;
  strategy_version: number | null;
  starting_capital_usd: N;
  equity_usd: N;
  return_pct: N;
  realised_pnl_usd: N;
  fees_usd: N;
  open_positions: number;
  untradeable_positions: number;
  max_drawdown_pct: N;
  equity_marks: number | null;
  first_mark_at: string | null;
  last_mark_at: string | null;
  closed_positions: number;
  wins: number;
  losses: number;
  win_rate_pct: N;
  gross_profit_usd: N;
  gross_loss_usd: N;
  profit_factor: N;
  avg_mfe_pct: N;
  avg_mae_pct: N;
  avg_hold_hours: N;
  orders: number;
  orders_filled: number;
  orders_rejected: number;
  orders_expired: number;
  avg_slippage_bps: N;
  evaluations: number;
  evaluations_enter: number;
  evaluations_reject: number;
  evaluations_missed: number;
};

export type StrategyEvaluation = {
  id: number;
  strategy_id: number;
  slug: string;
  version: number;
  token_id: number | null;
  chain: string | null;
  address: string | null;
  symbol: string | null;
  evaluated_at: string;
  data_cutoff_at: string;
  decision: string;
  reasons: string[];
  inputs_hash: string;
};

export type StrategyDefinition = {
  id: number;
  slug: string;
  version: number;
  name: string;
  description: string | null;
  rules: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
};
