import Link from "next/link";
import { Suspense } from "react";
import { ChainBadge, PageHeader } from "@/components/data-display";
import { str } from "@/components/filters";
import { Field, fieldCls, FormError, FormPanel, Options, Submit } from "@/components/form";
import { Guarded } from "@/components/guard";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { TableSkeleton } from "@/components/ui/skeleton";
import { Empty, Table, Td, Th, Tr } from "@/components/ui/table";
import { addManualMention, createChannel, createInfluencer, resolveChatRequest } from "@/lib/actions/curation";
import {
  isOwner,
  listChannels,
  listChatRequests,
  listCoordination,
  listInfluencerStats,
  listMentions,
} from "@/lib/data";
import { formatAge, formatPct, formatSgt, shortAddress, toNum } from "@/lib/format";
import { cn } from "@/lib/utils";

export const metadata = { title: "Influencer Intelligence" };

export default function InfluencersPage(props: PageProps<"/influencers">) {
  return (
    <>
      <PageHeader
        title="Influencer Intelligence"
        description="Forward performance of what monitored sources promote, measured from the first price observed after each mention. Every promoted token counts, including ones that failed or vanished. Accounts are never assumed independent."
      />
      <Suspense fallback={<TableSkeleton rows={12} />}>
        <Guarded>
          <Content searchParams={props.searchParams} />
        </Guarded>
      </Suspense>
    </>
  );
}

function Ret({ v }: { v: unknown }) {
  const n = toNum(v as number | string | null);
  return <span className={cn("num", n === null ? "text-fg-dim" : n >= 0 ? "text-ok" : "text-risk")}>{formatPct(n)}</span>;
}

async function Content({ searchParams }: { searchParams: PageProps<"/influencers">["searchParams"] }) {
  const sp = await searchParams;
  const [stats, mentions, signals, channels, requests, owner] = await Promise.all([
    listInfluencerStats(),
    listMentions(100),
    listCoordination(),
    listChannels(),
    listChatRequests(),
    isOwner(),
  ]);
  const influencerName = new Map(stats.map((s) => [s.influencer_id, s.display_name]));

  return (
    <div className="space-y-4">
      <FormError error={str(sp.error)} />

      <Card>
        <CardHeader
          title="Track record"
          subtitle="First mention per token per influencer. Returns use observed prices only; 'failed' = untradeable, delisted or ≥80% drawdown. Small samples are noise."
        />
        {stats.length === 0 ? <Empty>No influencers registered yet.</Empty> : (
          <Table>
            <thead>
              <tr>
                <Th>Influencer</Th><Th>Group</Th><Th className="text-right">Mentions</Th><Th className="text-right">Projects</Th>
                <Th className="text-right">Avg 24h</Th><Th className="text-right">Avg 7d</Th><Th className="text-right">Median 7d</Th>
                <Th className="text-right">Avg max gain</Th><Th className="text-right">Avg max DD</Th><Th className="text-right">Failed</Th>
                <Th className="text-right">No price</Th><Th className="text-right">Exit infeasible</Th><Th className="text-right">Disclosed promos</Th>
              </tr>
            </thead>
            <tbody>
              {stats.map((s) => (
                <Tr key={s.influencer_id}>
                  <Td className="font-medium">{s.display_name}</Td>
                  <Td>{s.coordination_group ? <Badge tone="warn">{s.coordination_group}</Badge> : <span className="text-fg-dim">—</span>}</Td>
                  <Td className="num text-right">{s.mentions}</Td>
                  <Td className="num text-right">{s.projects}</Td>
                  <Td className="text-right"><Ret v={s.avg_return_24h_pct} /></Td>
                  <Td className="text-right"><Ret v={s.avg_return_7d_pct} /></Td>
                  <Td className="text-right"><Ret v={s.median_return_7d_pct} /></Td>
                  <Td className="text-right"><Ret v={s.avg_max_gain_pct} /></Td>
                  <Td className="text-right"><Ret v={s.avg_max_drawdown_pct} /></Td>
                  <Td className="num text-right">{s.failed}</Td>
                  <Td className="num text-right">{s.no_price}</Td>
                  <Td className="num text-right">{s.exit_infeasible}</Td>
                  <Td className="num text-right">{s.disclosed_promos}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Card>
        <CardHeader title="Possible coordinated promotion" subtitle="Same token from ≥2 clusters within 30 min, shared referral links, or identical text. A signal to investigate, not proof." />
        {signals.length === 0 ? <Empty>No coordination signals.</Empty> : (
          <Table>
            <thead><tr><Th>Signal</Th><Th>Subject</Th><Th>First seen</Th><Th>Clusters</Th></tr></thead>
            <tbody>
              {signals.map((s, i) => (
                <Tr key={`${s.signal}-${s.subject}-${i}`}>
                  <Td><Badge tone="warn">{s.signal.replaceAll("_", " ")}</Badge></Td>
                  <Td className="max-w-80 truncate text-xs">{s.subject}</Td>
                  <Td className="text-xs">{formatSgt(s.first_at)}</Td>
                  <Td className="text-xs text-fg-muted">{Array.from(new Set(s.clusters)).join(", ")}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Card>
        <CardHeader title="Recent mentions" subtitle="Excerpts only. Message text is untrusted input and is never used as instructions." />
        {mentions.length === 0 ? <Empty>No mentions collected yet.</Empty> : (
          <Table>
            <thead>
              <tr>
                <Th>When</Th><Th>Source</Th><Th>Token</Th><Th>Category</Th><Th>Flags</Th>
                <Th className="text-right">Since mention (7d)</Th><Th className="text-right">Max gain / DD</Th><Th>Outcome</Th><Th>Excerpt</Th>
              </tr>
            </thead>
            <tbody>
              {mentions.map((m) => {
                const first = toNum(m.first_price_usd);
                const p7 = toNum(m.price_7d_usd);
                return (
                  <Tr key={m.id}>
                    <Td className="text-xs whitespace-nowrap" title={formatSgt(m.published_at)}>{formatAge(m.published_at)} ago</Td>
                    <Td className="text-xs">
                      {m.source_url ? <a href={m.source_url} className="hover:text-accent" target="_blank" rel="noreferrer nofollow">{m.channel_title ?? m.channel_handle ?? m.platform}</a> : (m.channel_title ?? m.channel_handle ?? m.platform)}
                      {m.influencer_name ? <span className="block text-fg-dim">{m.influencer_name}</span> : null}
                    </Td>
                    <Td>
                      {m.token_id && m.token_chain && m.token_address ? (
                        <Link href={`/tokens/${m.token_chain}/${m.token_address}`} className="hover:text-accent">
                          {m.token_symbol ?? shortAddress(m.token_address)}
                        </Link>
                      ) : m.contract_address ? <span className="num text-xs text-fg-dim">{shortAddress(m.contract_address)} (unresolved)</span>
                        : m.mentioned_symbols.length ? <span className="text-xs text-fg-muted">${m.mentioned_symbols.join(" $")}</span> : "—"}
                      {m.token_chain ? <span className="ml-1"><ChainBadge chain={m.token_chain} /></span> : null}
                    </Td>
                    <Td><Badge>{m.category}</Badge></Td>
                    <Td>
                      <div className="flex flex-wrap gap-1">
                        {m.is_forwarded ? <Badge tone="unknown">forwarded{m.forwarded_from ? `: ${m.forwarded_from}` : ""}</Badge> : null}
                        {m.promo_disclosure === "disclosed" ? <Badge tone="warn">disclosed promo</Badge> : null}
                        {m.referral_links.length ? <Badge tone="warn">referral link</Badge> : null}
                        {m.origin === "manual" ? <Badge>manual</Badge> : null}
                      </div>
                    </Td>
                    <Td className="text-right"><Ret v={first && p7 !== null ? (p7 / first - 1) * 100 : null} /></Td>
                    <Td className="text-right text-xs"><Ret v={m.max_gain_pct} /> / <Ret v={m.max_drawdown_pct} /></Td>
                    <Td><Badge tone={m.outcome_status === "untradeable" || m.outcome_status === "delisted" ? "risk" : "unknown"}>{m.outcome_status ?? "pending"}</Badge></Td>
                    <Td className="max-w-96 truncate text-xs text-fg-muted" title={m.text_excerpt ?? undefined}>{m.text_excerpt ?? ""}</Td>
                  </Tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </Card>

      <Card>
        <CardHeader
          title="Source registry"
          subtitle="Only registered, enabled sources are collected. Telegram: add the bot to a channel/group you are authorised to monitor, then approve it below. No user-account scraping."
        />
        {channels.length === 0 ? <Empty>No sources registered.</Empty> : (
          <Table>
            <thead><tr><Th>Platform</Th><Th>Source</Th><Th>Influencer</Th><Th>Access basis</Th><Th>Status</Th><Th>Last collected</Th></tr></thead>
            <tbody>
              {channels.map((c) => (
                <Tr key={c.id}>
                  <Td>{c.platform}</Td>
                  <Td>{c.title ?? c.handle ?? c.external_id} <span className="num text-[11px] text-fg-dim">{c.external_id}</span></Td>
                  <Td>{c.influencer_id ? influencerName.get(c.influencer_id) ?? c.influencer_id : <span className="text-fg-dim">—</span>}</Td>
                  <Td><Badge tone={c.is_official_project ? "accent" : "neutral"}>{c.access_basis.replaceAll("_", " ")}</Badge></Td>
                  <Td>{c.enabled ? <Badge tone="ok">enabled</Badge> : <Badge>disabled</Badge>}</Td>
                  <Td className="text-xs text-fg-dim">{c.last_collected_at ? `${formatAge(c.last_collected_at)} ago` : "never"}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
        {requests.length ? (
          <div className="border-t border-border p-4">
            <h3 className="mb-2 text-xs uppercase tracking-wider text-fg-dim">Chats waiting for approval (content not stored until approved)</h3>
            <ul className="space-y-2">
              {requests.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center gap-2 text-[13px]">
                  <span>{r.title ?? r.external_id}</span>
                  <span className="text-xs text-fg-dim">{r.chat_type} · {r.messages_seen} msgs · last {formatAge(r.last_seen_at)} ago</span>
                  {owner ? (
                    <form action={resolveChatRequest} className="ml-auto flex items-center gap-1 text-xs">
                      <input type="hidden" name="id" value={r.id} />
                      <select name="influencer_id" className="rounded border border-border-strong bg-panel-2 px-1 py-0.5">
                        <option value="">No influencer</option>
                        {stats.map((s) => <option key={s.influencer_id} value={s.influencer_id}>{s.display_name}</option>)}
                      </select>
                      <select name="access_basis" className="rounded border border-border-strong bg-panel-2 px-1 py-0.5" defaultValue="authorised_member">
                        <Options values={["public", "authorised_member", "official_project"]} />
                      </select>
                      <button name="decision" value="approve" className="rounded border border-ok/50 px-2 py-0.5 text-ok">Approve</button>
                      <button name="decision" value="ignore" className="rounded border border-border-strong px-2 py-0.5">Ignore</button>
                    </form>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </Card>

      {owner ? (
        <div className="grid gap-4 xl:grid-cols-3">
          <FormPanel title="Add influencer">
            <form action={createInfluencer} className="space-y-3">
              <Field label="Display name *"><input name="display_name" required maxLength={120} className={fieldCls} /></Field>
              <Field label="Coordination group" hint="Accounts in the same group count as one source."><input name="coordination_group" maxLength={60} className={fieldCls} /></Field>
              <Field label="Notes"><input name="notes" maxLength={1000} className={fieldCls} /></Field>
              <Submit>Add influencer</Submit>
            </form>
          </FormPanel>
          <FormPanel title="Register a source">
            <form action={createChannel} className="space-y-3">
              <Field label="Platform"><select name="platform" className={fieldCls}><Options values={["telegram", "x", "youtube", "web", "rss", "other"]} /></select></Field>
              <Field label="External id *" hint="Telegram chat id (e.g. -100…), handle or feed URL."><input name="external_id" required maxLength={200} className={fieldCls} /></Field>
              <Field label="Handle"><input name="handle" maxLength={120} className={fieldCls} /></Field>
              <Field label="Title"><input name="title" maxLength={200} className={fieldCls} /></Field>
              <Field label="URL"><input name="url" type="url" className={fieldCls} /></Field>
              <Field label="Influencer">
                <select name="influencer_id" className={fieldCls}>
                  <option value="">None</option>
                  {stats.map((s) => <option key={s.influencer_id} value={s.influencer_id}>{s.display_name}</option>)}
                </select>
              </Field>
              <Field label="Access basis"><select name="access_basis" className={fieldCls}><Options values={["public", "authorised_member", "official_project"]} /></select></Field>
              <Submit>Register</Submit>
            </form>
          </FormPanel>
          <FormPanel title="Record a mention manually">
            <form action={addManualMention} className="space-y-3">
              <Field label="Source *">
                <select name="channel_id" required className={fieldCls}>
                  {channels.map((c) => <option key={c.id} value={c.id}>{c.title ?? c.handle ?? c.external_id} ({c.platform})</option>)}
                </select>
              </Field>
              <Field label="Published at (SGT) *"><input name="published_at" type="datetime-local" required className={fieldCls} /></Field>
              <Field label="Link to the post *"><input name="source_url" type="url" required className={fieldCls} /></Field>
              <Field label="Chain"><select name="chain" className={fieldCls}><Options values={["bsc", "ethereum", "solana", "base"]} /></select></Field>
              <Field label="Contract / mint address"><input name="contract_address" maxLength={64} className={fieldCls} /></Field>
              <Field label="Project name"><input name="project_name" maxLength={120} className={fieldCls} /></Field>
              <Field label="Category"><select name="category" className={fieldCls}><Options values={["call", "promotion", "announcement", "news", "analysis", "warning", "other"]} /></select></Field>
              <Field label="Promotion disclosure"><select name="promo_disclosure" className={fieldCls} defaultValue="unknown"><Options values={["disclosed", "not_disclosed", "unknown"]} /></select></Field>
              <label className="flex items-center gap-2 text-[11px] text-fg-dim"><input type="checkbox" name="is_forwarded" /> Forwarded / reposted</label>
              <Field label="Excerpt (≤280 chars)"><textarea name="text_excerpt" maxLength={280} rows={2} className={fieldCls} /></Field>
              <Submit>Save mention</Submit>
            </form>
          </FormPanel>
        </div>
      ) : null}
    </div>
  );
}
