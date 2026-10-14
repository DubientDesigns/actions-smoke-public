import { Field, fieldCls, Submit } from "@/components/form";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { placePaperOrder } from "@/lib/actions/paper";
import { STATUS_TONE } from "@/lib/paper";

export function PaperStatus({ s }: { s: string }) {
  return <Badge tone={STATUS_TONE[s] ?? "neutral"}>{s.replaceAll("_", " ")}</Badge>;
}

export const SIMULATION_NOTE =
  "Simulation only: no wallet, key, signature or swap is involved. Fills use the first price observed after the execution delay, with fees, constant-product price impact and a liquidity cap.";

/** Owner-only manual paper buy (goes to the owner's manual paper portfolio). */
export function PaperBuyCard({ tokenId, back }: { tokenId: number; back: string }) {
  return (
    <Card className="mt-4">
      <CardHeader title="Paper trade" subtitle={SIMULATION_NOTE} />
      <form action={placePaperOrder} className="grid gap-3 p-4 md:grid-cols-5">
        <input type="hidden" name="kind" value="buy" />
        <input type="hidden" name="token_id" value={tokenId} />
        <input type="hidden" name="back" value={back} />
        <Field label="Notional (US$) *"><input name="notional_usd" type="number" min={1} max={1000000} step="any" required defaultValue={200} className={fieldCls} /></Field>
        <Field label="Stop-loss %" hint="optional, e.g. 30"><input name="stop_loss_pct" type="number" min={0.1} max={99} step="any" className={fieldCls} /></Field>
        <Field label="Take-profit legs" hint="gain%:sell%, e.g. 100:50, 300:100" className="md:col-span-2"><input name="take_profit" maxLength={100} placeholder="100:50, 300:100" className={fieldCls} /></Field>
        <div className="flex items-end"><Submit>Paper buy</Submit></div>
      </form>
    </Card>
  );
}

/** Owner-only paper allocation into an open presale at its recorded sale price. */
export function PresaleAllocationCard({ presaleId, back }: { presaleId: number; back: string }) {
  return (
    <Card className="mt-4">
      <CardHeader
        title="Paper allocation"
        subtitle="Simulated allocation at the recorded sale price. Tokens stay locked per the recorded vesting schedule; an unknown schedule keeps everything locked, and locked tokens are valued at zero."
      />
      <form action={placePaperOrder} className="flex flex-wrap items-end gap-3 p-4">
        <input type="hidden" name="kind" value="presale" />
        <input type="hidden" name="presale_id" value={presaleId} />
        <input type="hidden" name="back" value={back} />
        <Field label="Notional (US$) *"><input name="notional_usd" type="number" min={1} max={1000000} step="any" required defaultValue={200} className={fieldCls} /></Field>
        <Submit>Paper allocate</Submit>
      </form>
    </Card>
  );
}
