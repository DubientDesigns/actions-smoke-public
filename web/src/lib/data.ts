import "server-only";

import { createClient } from "@/lib/supabase/server";
import type {
  DataSource,
  HealthRow,
  JobFreshness,
  PoolDetail,
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

export type DiscoveryFilters = {
  chain?: string;
  minLiquidity?: number;
  maxAgeHours?: number;
  q?: string;
  sort?: "newest" | "liquidity" | "volume";
  limit?: number;
};

const SORTS = {
  newest: { column: "first_observed_at", ascending: false },
  liquidity: { column: "liquidity_usd", ascending: false },
  volume: { column: "volume_h24_usd", ascending: false },
} as const;

export async function listTokens(f: DiscoveryFilters): Promise<TokenOverview[]> {
  const supabase = await createClient();
  let q = supabase.from("v_token_overview").select("*");
  if (f.chain) q = q.eq("chain", f.chain);
  if (f.minLiquidity && f.minLiquidity > 0) q = q.gte("liquidity_usd", f.minLiquidity);
  if (f.maxAgeHours && f.maxAgeHours > 0) {
    q = q.gte("first_observed_at", new Date(Date.now() - f.maxAgeHours * 3600_000).toISOString());
  }
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
  const [pools, snaps] = await Promise.all([
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
  ]);
  return {
    token,
    pools: check(pools) as PoolDetail[],
    snapshots: (check(snaps) as Snapshot[]).reverse(),
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
