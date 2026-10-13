import "server-only";

import { createClient } from "@/lib/supabase/server";
import type {
  Channel,
  ChatRequest,
  CoordinationSignal,
  InfluencerStats,
  MentionDetail,
  Presale,
  PresaleClaim,
  PresaleScore,
  WalletEvent,
  WalletOverview,
  DataSource,
  HealthRow,
  JobFreshness,
  PoolDetail,
  SavedView,
  ScoreLatest,
  SecurityLatest,
  Snapshot,
  TokenOverview,
  UsageDaily,
} from "@/lib/types";

/** Thrown when the signed-in user is not on the allowlist (RLS returns nothing). */
export class NotAllowlistedError extends Error {}

export async function getViewer() {
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  const userId = data?.claims?.sub as string | undefined;
  const email = (data?.claims?.email as string | undefined) ?? null;
  if (!userId) return { userId: null, email: null, role: null as string | null };
  const { data: row } = await supabase.from("app_users").select("role").eq("user_id", userId).maybeSingle();
  return { userId, email, role: (row?.role as string | undefined) ?? null };
}

export async function requireAllowlisted() {
  const viewer = await getViewer();
  if (!viewer.role) throw new NotAllowlistedError("not allowlisted");
  return viewer;
}

function check<T>(res: { data: T | null; error: { message: string } | null }): T {
  if (res.error) throw new Error(res.error.message);
  return res.data as T;
}

export type RiskFilter = "all" | "hide_excluded" | "assessed_clean" | "excluded";

export type DiscoveryFilters = {
  chain?: string;
  minLiquidity?: number;
  maxAgeHours?: number;
  minScore?: number;
  risk?: RiskFilter;
  q?: string;
  sort?: "newest" | "liquidity" | "volume" | "score";
  limit?: number;
};

const SORTS = {
  newest: { column: "first_observed_at", ascending: false },
  liquidity: { column: "liquidity_usd", ascending: false },
  volume: { column: "volume_h24_usd", ascending: false },
  score: { column: "score_total", ascending: false },
} as const;

export async function listTokens(f: DiscoveryFilters): Promise<TokenOverview[]> {
  const supabase = await createClient();
  let q = supabase.from("v_token_overview").select("*");
  if (f.chain) q = q.eq("chain", f.chain);
  if (f.minLiquidity && f.minLiquidity > 0) q = q.gte("liquidity_usd", f.minLiquidity);
  if (f.maxAgeHours && f.maxAgeHours > 0) {
    q = q.gte("first_observed_at", new Date(Date.now() - f.maxAgeHours * 3600_000).toISOString());
  }
  if (f.minScore && f.minScore > 0) q = q.gte("score_total", f.minScore);
  if (f.risk === "hide_excluded") q = q.or("hard_excluded.is.null,hard_excluded.eq.false");
  if (f.risk === "assessed_clean") q = q.in("risk_level", ["low", "medium"]).eq("hard_excluded", false);
  if (f.risk === "excluded") q = q.eq("hard_excluded", true);
  if (f.q) {
    const term = f.q.trim();
    // Exact address match, or symbol/name prefix. PostgREST filter values are escaped by quoting.
    const safe = term.replace(/[",()]/g, "");
    q = q.or(`address.eq.${safe.toLowerCase()},address.eq.${safe},symbol.ilike.${safe}*,name.ilike.${safe}*`);
  }
  const sort = SORTS[f.sort ?? "newest"];
  q = q.order(sort.column, { ascending: sort.ascending, nullsFirst: false }).limit(f.limit ?? 100);
  return check(await q);
}

export async function getToken(chain: string, address: string) {
  const supabase = await createClient();
  const token = check(
    await supabase.from("v_token_overview").select("*").eq("chain", chain).eq("address", address).maybeSingle(),
  ) as TokenOverview | null;
  if (!token) return null;
  const [pools, snaps, security, score] = await Promise.all([
    supabase.from("v_pool_detail").select("*").eq("token_id", token.token_id).order("liquidity_usd", {
      ascending: false,
      nullsFirst: false,
    }),
    supabase
      .from("market_snapshots")
      .select("observed_at, price_usd, liquidity_usd, volume_h24_usd, pool_id, resolution")
      .eq("token_id", token.token_id)
      .order("observed_at", { ascending: false })
      .limit(2000),
    supabase.from("v_security_latest").select("*").eq("token_id", token.token_id).maybeSingle(),
    supabase.from("v_score_latest").select("*").eq("token_id", token.token_id).maybeSingle(),
  ]);
  return {
    token,
    pools: check(pools) as PoolDetail[],
    snapshots: (check(snaps) as Snapshot[]).reverse(),
    security: check(security) as SecurityLatest | null,
    score: check(score) as ScoreLatest | null,
  };
}

export async function getOverviewStats() {
  const supabase = await createClient();
  const since = new Date(Date.now() - 24 * 3600_000).toISOString();
  const chains = ["bsc", "ethereum", "solana", "base"];
  const counts = await Promise.all(
    chains.map(async (c) => {
      const { count, error } = await supabase
        .from("v_token_overview")
        .select("token_id", { count: "exact", head: true })
        .eq("chain", c)
        .gte("first_observed_at", since);
      if (error) throw new Error(error.message);
      return [c, count ?? 0] as const;
    }),
  );
  return Object.fromEntries(counts) as Record<string, number>;
}

export async function listSources(): Promise<DataSource[]> {
  const supabase = await createClient();
  return check(await supabase.from("data_sources").select("*").order("id"));
}

export async function listJobFreshness(): Promise<JobFreshness[]> {
  const supabase = await createClient();
  return check(await supabase.from("v_job_freshness").select("*").order("job_name").order("chain"));
}

export async function listHealth(): Promise<HealthRow[]> {
  const supabase = await createClient();
  return check(await supabase.from("system_health").select("*").order("component"));
}

export async function listUsage(days = 7): Promise<UsageDaily[]> {
  const supabase = await createClient();
  const since = new Date(Date.now() - days * 86400_000).toISOString();
  return check(
    await supabase.from("api_usage_daily").select("day, source, calls, failed_calls, cost_usd").gte("day", since).order("day"),
  );
}

export async function listSettings(): Promise<{ key: string; value: unknown; updated_at: string; updated_by: string | null }[]> {
  const supabase = await createClient();
  return check(await supabase.from("app_settings").select("key, value, updated_at, updated_by").order("key"));
}

export type SecurityFilters = {
  chain?: string;
  risk?: string;
  coverage?: string;
  stale?: "only" | "hide";
  limit?: number;
};

export async function listSecurity(f: SecurityFilters): Promise<SecurityLatest[]> {
  const supabase = await createClient();
  let q = supabase.from("v_security_latest").select("*");
  if (f.chain) q = q.eq("chain", f.chain);
  if (f.risk) q = q.eq("risk_level", f.risk);
  if (f.coverage) q = q.eq("coverage", f.coverage);
  if (f.stale === "only") q = q.eq("is_stale", true);
  if (f.stale === "hide") q = q.eq("is_stale", false);
  return check(await q.order("assessed_at", { ascending: false }).limit(f.limit ?? 200));
}

export async function securityCounts(): Promise<Record<string, number>> {
  const supabase = await createClient();
  const levels = ["critical", "high", "medium", "low", "unknown"];
  const res = await Promise.all(
    levels.map(async (l) => {
      const { count, error } = await supabase
        .from("v_security_latest")
        .select("token_id", { count: "exact", head: true })
        .eq("risk_level", l);
      if (error) throw new Error(error.message);
      return [l, count ?? 0] as const;
    }),
  );
  return Object.fromEntries(res);
}

export async function listSavedViews(page: string): Promise<SavedView[]> {
  const supabase = await createClient();
  return check(await supabase.from("saved_views").select("id, page, name, params").eq("page", page).order("name"));
}

/** Request-time clock for staleness checks in server components (kept out of render bodies). */
export function requestTime(): Date {
  return new Date();
}

export async function isOwner(): Promise<boolean> {
  return (await getViewer()).role === "owner";
}

export async function listPresales(status?: string): Promise<(Presale & { score: PresaleScore | null })[]> {
  const supabase = await createClient();
  let q = supabase.from("presales").select("*");
  if (status) q = q.eq("status", status);
  const presales = check(await q.order("sale_start_at", { ascending: true, nullsFirst: false }).limit(200)) as Presale[];
  const ids = presales.map((p) => p.id);
  const scores = ids.length
    ? (check(await supabase.from("v_presale_score_latest").select("*").in("presale_id", ids)) as PresaleScore[])
    : [];
  const byId = new Map(scores.map((s) => [s.presale_id, s]));
  return presales.map((p) => ({ ...p, score: byId.get(p.id) ?? null }));
}

export async function getPresale(slug: string) {
  const supabase = await createClient();
  const presale = check(await supabase.from("presales").select("*").eq("slug", slug).maybeSingle()) as Presale | null;
  if (!presale) return null;
  const [claims, score] = await Promise.all([
    supabase.from("presale_claims").select("*").eq("presale_id", presale.id).order("observed_at", { ascending: false }),
    supabase.from("v_presale_score_latest").select("*").eq("presale_id", presale.id).maybeSingle(),
  ]);
  return { presale, claims: check(claims) as PresaleClaim[], score: check(score) as PresaleScore | null };
}

export async function listInfluencerStats(): Promise<InfluencerStats[]> {
  const supabase = await createClient();
  return check(await supabase.from("v_influencer_stats").select("*").order("projects", { ascending: false }));
}

export async function listMentions(limit = 100): Promise<MentionDetail[]> {
  const supabase = await createClient();
  return check(await supabase.from("v_mention_detail").select("*").order("published_at", { ascending: false }).limit(limit));
}

export async function listCoordination(): Promise<CoordinationSignal[]> {
  const supabase = await createClient();
  return check(await supabase.from("v_coordination_signals").select("*").order("first_at", { ascending: false }).limit(50));
}

export async function listChannels(): Promise<Channel[]> {
  const supabase = await createClient();
  return check(await supabase.from("social_channels").select("*").order("created_at", { ascending: false }));
}

export async function listChatRequests(): Promise<ChatRequest[]> {
  const supabase = await createClient();
  return check(await supabase.from("social_chat_requests").select("*").eq("status", "pending").order("last_seen_at", { ascending: false }));
}

export async function listWallets(): Promise<WalletOverview[]> {
  const supabase = await createClient();
  return check(await supabase.from("v_wallet_overview").select("*").order("created_at", { ascending: false }));
}

export async function listWalletEvents(limit = 100): Promise<WalletEvent[]> {
  const supabase = await createClient();
  return check(await supabase.from("v_wallet_events").select("*").order("block_time", { ascending: false }).limit(limit));
}
