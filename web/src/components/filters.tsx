// Plain GET form: works without JavaScript and every filter state is a shareable URL.
export function DiscoveryFilters({
  action,
  values,
  showAge = true,
}: {
  action: string;
  values: {
    chain?: string;
    minLiquidity?: string;
    maxAgeHours?: string;
    minScore?: string;
    risk?: string;
    sort?: string;
    q?: string;
  };
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
      <label className="text-[11px] text-fg-dim">
        Min score
        <input name="minScore" type="number" min={0} max={100} step={5} defaultValue={values.minScore} className={`${field} mt-0.5 block w-20`} />
      </label>
      <label className="text-[11px] text-fg-dim">
        Security
        <select name="risk" defaultValue={values.risk ?? "all"} className={`${field} mt-0.5 block`}>
          <option value="all">All</option>
          <option value="hide_excluded">Hide excluded</option>
          <option value="assessed_clean">Assessed: low/medium only</option>
          <option value="excluded">Excluded only</option>
        </select>
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
          <option value="score">Score</option>
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

export function sortParam(v: string | string[] | undefined): "newest" | "liquidity" | "volume" | "score" {
  const s = str(v);
  return s === "liquidity" || s === "volume" || s === "score" ? s : "newest";
}

export function riskParam(v: string | string[] | undefined): "all" | "hide_excluded" | "assessed_clean" | "excluded" {
  const s = str(v);
  return s === "hide_excluded" || s === "assessed_clean" || s === "excluded" ? s : "all";
}

/** Serialise the current search params for saved views (allowlisted again server-side). */
export function toQuery(sp: Record<string, string | string[] | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(sp)) {
    const s = str(v);
    if (s) u.set(k, s);
  }
  return u.toString();
}

export function chainParam(v: string | string[] | undefined): string | undefined {
  const s = str(v);
  return s && ["bsc", "ethereum", "solana", "base"].includes(s) ? s : undefined;
}
