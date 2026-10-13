// Plain GET form: works without JavaScript and every filter state is a shareable URL.
export function DiscoveryFilters({
  action,
  values,
  showAge = true,
}: {
  action: string;
  values: { chain?: string; minLiquidity?: string; maxAgeHours?: string; sort?: string; q?: string };
  showAge?: boolean;
}) {
  const field = "rounded border border-border-strong bg-panel-2 px-2 py-1 text-[13px] outline-none focus:border-accent";
  return (
    <form action={action} method="get" className="flex flex-wrap items-end gap-2 border-b border-border px-4 py-3">
      <label className="text-[11px] text-fg-dim">
        Search
        <input name="q" defaultValue={values.q} placeholder="symbol, name or address" className={`${field} mt-0.5 block w-56`} />
      </label>
      <label className="text-[11px] text-fg-dim">
        Chain
        <select name="chain" defaultValue={values.chain ?? ""} className={`${field} mt-0.5 block`}>
          <option value="">All</option>
          <option value="bsc">BNB Chain</option>
          <option value="ethereum">Ethereum</option>
          <option value="solana">Solana</option>
          <option value="base">Base</option>
        </select>
      </label>
      <label className="text-[11px] text-fg-dim">
        Min liquidity (USD)
        <input name="minLiquidity" type="number" min={0} step={1000} defaultValue={values.minLiquidity} className={`${field} mt-0.5 block w-32`} />
      </label>
      {showAge ? (
        <label className="text-[11px] text-fg-dim">
          Seen within
          <select name="maxAgeHours" defaultValue={values.maxAgeHours ?? "24"} className={`${field} mt-0.5 block`}>
            <option value="1">1 hour</option>
            <option value="6">6 hours</option>
            <option value="24">24 hours</option>
            <option value="168">7 days</option>
            <option value="0">Any time</option>
          </select>
        </label>
      ) : null}
      <label className="text-[11px] text-fg-dim">
        Sort
        <select name="sort" defaultValue={values.sort ?? "newest"} className={`${field} mt-0.5 block`}>
          <option value="newest">Newest</option>
          <option value="liquidity">Liquidity</option>
          <option value="volume">Volume 24h</option>
        </select>
      </label>
      <button className="rounded border border-border-strong bg-panel-2 px-3 py-1 text-[13px] hover:border-accent">Apply</button>
    </form>
  );
}

export function str(v: string | string[] | undefined): string | undefined {
  return Array.isArray(v) ? v[0] : v;
}

export function num(v: string | string[] | undefined): number | undefined {
  const s = str(v);
  if (s === undefined || s === "") return undefined;
  const n = Number(s);
  return Number.isFinite(n) && n >= 0 ? n : undefined;
}

export function sortParam(v: string | string[] | undefined): "newest" | "liquidity" | "volume" {
  const s = str(v);
  return s === "liquidity" || s === "volume" ? s : "newest";
}

export function chainParam(v: string | string[] | undefined): string | undefined {
  const s = str(v);
  return s && ["bsc", "ethereum", "solana", "base"].includes(s) ? s : undefined;
}
