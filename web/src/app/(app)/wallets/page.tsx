import Link from "next/link";
import { Suspense } from "react";
import { ChainBadge, PageHeader } from "@/components/data-display";
import { str } from "@/components/filters";
import { Field, fieldCls, FormError, FormPanel, Options, Submit } from "@/components/form";
import { Guarded, Notice } from "@/components/guard";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { TableSkeleton } from "@/components/ui/skeleton";
import { Empty, Table, Td, Th, Tr } from "@/components/ui/table";
import { addWallet, toggleWallet } from "@/lib/actions/curation";
import { isOwner, listSources, listWalletEvents, listWallets } from "@/lib/data";
import { formatAge, formatSgt, formatUsd, shortAddress, toNum } from "@/lib/format";
import { EXPLORER } from "@/lib/nav";

export const metadata = { title: "Wallet Watchlist" };

const TX_URL: Record<string, (h: string) => string> = {
  bsc: (h) => `https://bscscan.com/tx/${h}`,
  ethereum: (h) => `https://etherscan.io/tx/${h}`,
  base: (h) => `https://basescan.org/tx/${h}`,
  solana: (h) => `https://solscan.io/tx/${h}`,
};

export default function WalletsPage(props: PageProps<"/wallets">) {
  return (
    <>
      <PageHeader
        title="Wallet Watchlist"
        description="Transfers for wallets you choose to follow (deployers, team, notable traders). Synced every 15 minutes via free tiers: Alchemy for Ethereum/Base/BNB Chain and Helius for Solana."
      />
      <Suspense fallback={<TableSkeleton rows={10} />}>
        <Guarded>
          <Content searchParams={props.searchParams} />
        </Guarded>
      </Suspense>
    </>
  );
}

async function Content({ searchParams }: { searchParams: PageProps<"/wallets">["searchParams"] }) {
  const sp = await searchParams;
  const [wallets, events, sources, owner] = await Promise.all([listWallets(), listWalletEvents(100), listSources(), isOwner()]);
  const onchain = sources.filter((s) => s.slug === "alchemy" || s.slug === "helius");
  const disabled = onchain.filter((s) => !s.enabled);
  return (
    <div className="space-y-4">
      <FormError error={str(sp.error)} />
      {disabled.length ? (
        <Notice title="On-chain sources not enabled">
          {disabled.map((s) => s.name).join(" and ")} {disabled.length > 1 ? "are" : "is"} disabled. Add the free API key(s)
          (CIT_ALCHEMY_API_KEY / CIT_HELIUS_API_KEY) to .env and enable the source (docs/OPERATIONS.md). Wallets can be
          added now; they sync once enabled.
        </Notice>
      ) : null}
      {owner ? (
        <FormPanel title="Track a wallet">
          <form action={addWallet} className="grid gap-3 md:grid-cols-5">
            <Field label="Chain"><select name="chain" className={fieldCls}><Options values={["ethereum", "base", "bsc", "solana"]} /></select></Field>
            <Field label="Address *" className="md:col-span-2"><input name="address" required maxLength={64} className={fieldCls} /></Field>
            <Field label="Label *"><input name="label" required maxLength={80} className={fieldCls} /></Field>
            <Field label="Category"><select name="category" className={fieldCls}><Options values={["deployer", "smart_money", "team", "exchange", "influencer", "whale", "other"]} /></select></Field>
            <Field label="Notes" className="md:col-span-4"><input name="notes" maxLength={500} className={fieldCls} /></Field>
            <div className="flex items-end"><Submit>Track wallet</Submit></div>
          </form>
        </FormPanel>
      ) : null}
      <Card>
        <CardHeader title={`Tracked wallets (${wallets.length})`} />
        {wallets.length === 0 ? <Empty>No wallets tracked.</Empty> : (
          <Table>
            <thead><tr><Th>Label</Th><Th>Chain</Th><Th>Address</Th><Th>Category</Th><Th className="text-right">Events 7d</Th><Th>Last event</Th><Th>Sync</Th><Th /></tr></thead>
            <tbody>
              {wallets.map((w) => (
                <Tr key={w.id}>
                  <Td className="font-medium">{w.label}</Td>
                  <Td><ChainBadge chain={w.chain} /></Td>
                  <Td className="num text-xs"><a className="hover:text-accent" href={EXPLORER[w.chain]?.token(w.address).replace("/token/", w.chain === "solana" ? "/account/" : "/address/")} target="_blank" rel="noreferrer">{shortAddress(w.address)}</a></Td>
                  <Td><Badge>{w.category.replaceAll("_", " ")}</Badge></Td>
                  <Td className="num text-right">{w.events_7d}</Td>
                  <Td className="text-xs text-fg-dim">{w.last_event_at ? `${formatAge(w.last_event_at)} ago` : "—"}</Td>
                  <Td className="text-xs">
                    {w.last_sync_error ? <span className="text-risk" title={w.last_sync_error}>error</span>
                      : w.last_synced_at ? <span className="text-fg-dim">{formatAge(w.last_synced_at)} ago</span>
                      : <span className="text-unknown">never</span>}
                    {!w.enabled ? <Badge className="ml-1">paused</Badge> : null}
                  </Td>
                  <Td>
                    {owner ? (
                      <form action={toggleWallet}>
                        <input type="hidden" name="id" value={w.id} />
                        <input type="hidden" name="enabled" value={w.enabled ? "false" : "true"} />
                        <button className="text-xs text-fg-dim hover:text-accent">{w.enabled ? "Pause" : "Resume"}</button>
                      </form>
                    ) : null}
                  </Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <Card>
        <CardHeader title="Recent activity" subtitle="USD value uses our latest observed price when we track the token; otherwise unknown." />
        {events.length === 0 ? <Empty>No wallet activity recorded.</Empty> : (
          <Table>
            <thead><tr><Th>When</Th><Th>Wallet</Th><Th>Type</Th><Th>Token</Th><Th className="text-right">Amount</Th><Th className="text-right">Value</Th><Th>Counterparty</Th><Th>Tx</Th></tr></thead>
            <tbody>
              {events.map((e) => (
                <Tr key={e.id}>
                  <Td className="text-xs" title={formatSgt(e.block_time)}>{formatAge(e.block_time)} ago</Td>
                  <Td>{e.wallet_label} <ChainBadge chain={e.chain} /></Td>
                  <Td><Badge tone={e.event_type === "buy" ? "ok" : e.event_type === "sell" ? "warn" : "neutral"}>{e.event_type.replaceAll("_", " ")}</Badge></Td>
                  <Td>
                    {e.token_id && e.token_address ? <Link className="hover:text-accent" href={`/tokens/${e.chain}/${e.token_address}`}>{e.token}</Link>
                      : e.token ? <span className="num text-xs">{e.token.length > 14 ? shortAddress(e.token) : e.token}</span> : <span className="text-fg-dim">native</span>}
                  </Td>
                  <Td className="num text-right">{toNum(e.amount) === null ? "—" : Number(e.amount).toLocaleString("en-US", { maximumFractionDigits: 4 })}</Td>
                  <Td className="num text-right">{formatUsd(e.value_usd)}</Td>
                  <Td className="num text-xs text-fg-dim">{e.counterparty ? shortAddress(e.counterparty) : "—"}</Td>
                  <Td className="num text-xs"><a className="text-accent hover:underline" href={TX_URL[e.chain](e.tx_hash)} target="_blank" rel="noreferrer">{shortAddress(e.tx_hash)}</a></Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
