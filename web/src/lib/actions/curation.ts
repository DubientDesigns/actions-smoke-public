"use server";

import { redirect, unstable_rethrow } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import {
  address,
  CHAIN_IDS,
  CHAINS,
  InputError,
  number,
  oneOf,
  sgtDateTime,
  slugify,
  text,
  url,
} from "@/lib/validate";

// Owner-only curation. RLS enforces "owner" on every write; these actions add
// server-side validation and friendly errors. Errors return to the page as
// ?error=… ; nothing is trusted from the browser.

type Supabase = Awaited<ReturnType<typeof createClient>>;

async function session(): Promise<{ supabase: Supabase; email: string }> {
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  if (!data?.claims?.sub) redirect("/login");
  return { supabase, email: String(data.claims.email ?? data.claims.sub) };
}

async function run(back: string, fn: () => Promise<string | void>): Promise<never> {
  let target = back;
  try {
    target = (await fn()) ?? back;
  } catch (e) {
    unstable_rethrow(e); // let Next.js redirects (e.g. to /login) through
    const msg = e instanceof InputError ? e.message : e instanceof Error ? e.message : "unexpected error";
    redirect(`${back}?error=${encodeURIComponent(msg.slice(0, 200))}`);
  }
  redirect(target);
}

function dbError(error: { message: string; code?: string } | null) {
  if (!error) return;
  if (error.code === "42501") throw new InputError("Only owners can make changes.");
  if (error.code === "23505") throw new InputError("That entry already exists.");
  throw new InputError(error.message);
}

// ---------------------------------------------------------------- presales

const SALE_TYPES = ["public", "private", "whitelist", "fair_launch", "unknown"] as const;
const STATUSES = ["rumoured", "announced", "upcoming", "live", "ended", "cancelled", "tge_done", "unknown"] as const;
const VERIFICATION = ["unverified", "official_source_seen", "partially_verified", "disputed", "red_flag"] as const;

export async function createPresale(fd: FormData) {
  await run("/presales", async () => {
    const { supabase, email } = await session();
    const name = text(fd, "project_name", { max: 120, required: true })!;
    const chain = oneOf(fd, "chain", ["", ...CHAINS] as const, "");
    const tge = number(fd, "tge_unlock_pct", { max: 100 });
    const vest = number(fd, "vesting_months", { max: 120 });
    const cliff = number(fd, "cliff_months", { max: 120 });
    const vesting = tge === null && vest === null && cliff === null ? null
      : { tge_unlock_pct: tge, cliff_months: cliff, vesting_months: vest, source: "operator entry (claimed)" };
    const sources = [url(fd, "source_url_1"), url(fd, "source_url_2")].filter(Boolean) as string[];
    const audit = text(fd, "audit_claims", { max: 300 });
    const row = {
      project_name: name,
      slug: `${slugify(name)}-${Date.now().toString(36)}`,
      official_website: url(fd, "official_website"),
      chain_id: chain ? CHAIN_IDS[chain] : null,
      platform: text(fd, "platform", { max: 120 }),
      platform_url: url(fd, "platform_url"),
      sale_type: oneOf(fd, "sale_type", SALE_TYPES, "unknown"),
      status: oneOf(fd, "status", STATUSES, "unknown"),
      sale_start_at: sgtDateTime(fd, "sale_start_at"),
      sale_end_at: sgtDateTime(fd, "sale_end_at"),
      tge_at: sgtDateTime(fd, "tge_at"),
      sale_price_usd: number(fd, "sale_price_usd"),
      claimed_valuation_usd: number(fd, "claimed_valuation_usd"),
      min_investment_usd: number(fd, "min_investment_usd"),
      hard_cap_usd: number(fd, "hard_cap_usd"),
      vesting_terms: vesting,
      lockup_terms: text(fd, "lockup_terms", { max: 500 }),
      audit_claims: audit ? [audit] : [],
      team_info: text(fd, "team_info", { max: 1000 }),
      verification_status: oneOf(fd, "verification_status", VERIFICATION, "unverified"),
      source_urls: sources,
      notes: text(fd, "notes", { max: 2000 }),
      created_by: email,
    };
    const { data, error } = await supabase.from("presales").insert(row).select("slug").single();
    dbError(error);
    return `/presales/${data!.slug}`;
  });
}

const CLAIM_KINDS = ["official", "launchpad", "third_party", "social", "manual"] as const;
const CLAIM_VERIFICATION = ["unverified", "consistent", "contradicted", "verified_onchain"] as const;

export async function addPresaleClaim(fd: FormData) {
  const slug = text(fd, "slug", { max: 120, required: true })!;
  await run(`/presales/${slug}`, async () => {
    const { supabase } = await session();
    const presaleId = number(fd, "presale_id", { min: 1 });
    if (!presaleId) throw new InputError("presale missing");
    const { error } = await supabase.from("presale_claims").insert({
      presale_id: presaleId,
      field: text(fd, "field", { max: 60, required: true }),
      value: text(fd, "value", { max: 500, required: true }),
      source_url: url(fd, "source_url"),
      source_kind: oneOf(fd, "source_kind", CLAIM_KINDS, "manual"),
      verification: oneOf(fd, "verification", CLAIM_VERIFICATION, "unverified"),
    });
    dbError(error);
  });
}

export async function updatePresaleStatus(fd: FormData) {
  const slug = text(fd, "slug", { max: 120, required: true })!;
  await run(`/presales/${slug}`, async () => {
    const { supabase } = await session();
    const { error } = await supabase
      .from("presales")
      .update({
        status: oneOf(fd, "status", STATUSES, "unknown"),
        verification_status: oneOf(fd, "verification_status", VERIFICATION, "unverified"),
      })
      .eq("slug", slug);
    dbError(error);
  });
}

// ----------------------------------------------------------------- social

const PLATFORMS = ["telegram", "x", "youtube", "web", "rss", "other"] as const;
const ACCESS = ["public", "authorised_member", "official_project"] as const;

export async function createInfluencer(fd: FormData) {
  await run("/influencers", async () => {
    const { supabase } = await session();
    const { error } = await supabase.from("influencers").insert({
      display_name: text(fd, "display_name", { max: 120, required: true }),
      coordination_group: text(fd, "coordination_group", { max: 60 }),
      notes: text(fd, "notes", { max: 1000 }),
    });
    dbError(error);
  });
}

export async function createChannel(fd: FormData) {
  await run("/influencers", async () => {
    const { supabase } = await session();
    const influencer = number(fd, "influencer_id", { min: 1 });
    const access = oneOf(fd, "access_basis", ACCESS, "public");
    const { error } = await supabase.from("social_channels").insert({
      platform: oneOf(fd, "platform", PLATFORMS, "telegram"),
      external_id: text(fd, "external_id", { max: 200, required: true }),
      handle: text(fd, "handle", { max: 120 }),
      title: text(fd, "title", { max: 200 }),
      url: url(fd, "url"),
      influencer_id: influencer,
      access_basis: access,
      is_official_project: access === "official_project",
    });
    dbError(error);
  });
}

export async function resolveChatRequest(fd: FormData) {
  await run("/influencers", async () => {
    const { supabase } = await session();
    const id = number(fd, "id", { min: 1 });
    const decision = oneOf(fd, "decision", ["approve", "ignore"] as const, "ignore");
    const { data: req, error } = await supabase.from("social_chat_requests").select("*").eq("id", id!).single();
    dbError(error);
    if (decision === "approve") {
      const { error: e2 } = await supabase.from("social_channels").insert({
        platform: "telegram",
        external_id: req!.external_id,
        title: req!.title,
        access_basis: oneOf(fd, "access_basis", ACCESS, "authorised_member"),
        influencer_id: number(fd, "influencer_id", { min: 1 }),
      });
      dbError(e2);
    }
    const { error: e3 } = await supabase
      .from("social_chat_requests")
      .update({ status: decision === "approve" ? "approved" : "ignored" })
      .eq("id", id!);
    dbError(e3);
  });
}

const CATEGORIES = ["call", "promotion", "announcement", "news", "analysis", "warning", "other"] as const;
const DISCLOSURE = ["disclosed", "not_disclosed", "unknown"] as const;

export async function addManualMention(fd: FormData) {
  await run("/influencers", async () => {
    const { supabase, email } = await session();
    const chain = oneOf(fd, "chain", CHAINS, "bsc");
    const channel = number(fd, "channel_id", { min: 1 });
    if (!channel) throw new InputError("choose a source channel");
    const publishedAt = sgtDateTime(fd, "published_at", { required: true })!;
    if (new Date(publishedAt).getTime() > Date.now() + 5 * 60_000) throw new InputError("published_at is in the future");
    const contract = address(chain, text(fd, "contract_address", { max: 64 }));
    const { error } = await supabase.from("social_mentions").insert({
      channel_id: channel,
      external_message_id: `manual:${Date.now().toString(36)}`,
      published_at: publishedAt,
      chain_id: contract ? CHAIN_IDS[chain] : null,
      contract_address: contract,
      project_name: text(fd, "project_name", { max: 120 }),
      source_url: url(fd, "source_url", { required: true }),
      category: oneOf(fd, "category", CATEGORIES, "other"),
      promo_disclosure: oneOf(fd, "promo_disclosure", DISCLOSURE, "unknown"),
      is_forwarded: fd.get("is_forwarded") === "on",
      text_excerpt: text(fd, "text_excerpt", { max: 280 }),
      origin: "manual",
      entered_by: email,
    });
    dbError(error);
  });
}

// ---------------------------------------------------------------- wallets

const WALLET_CATEGORIES = ["deployer", "smart_money", "team", "exchange", "influencer", "whale", "other"] as const;

export async function addWallet(fd: FormData) {
  await run("/wallets", async () => {
    const { supabase, email } = await session();
    const chain = oneOf(fd, "chain", CHAINS, "ethereum");
    const { error } = await supabase.from("tracked_wallets").insert({
      chain_id: CHAIN_IDS[chain],
      address: address(chain, text(fd, "address", { max: 64, required: true })),
      label: text(fd, "label", { max: 80, required: true }),
      category: oneOf(fd, "category", WALLET_CATEGORIES, "other"),
      notes: text(fd, "notes", { max: 500 }),
      created_by: email,
    });
    dbError(error);
  });
}

export async function toggleWallet(fd: FormData) {
  await run("/wallets", async () => {
    const { supabase } = await session();
    const id = number(fd, "id", { min: 1 });
    const { error } = await supabase.from("tracked_wallets").update({ enabled: fd.get("enabled") === "true" }).eq("id", id!);
    dbError(error);
  });
}
