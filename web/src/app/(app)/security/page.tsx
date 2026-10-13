import { PlannedPage } from "@/components/planned-page";

export const metadata = { title: "Security Analysis" };

export default function Page() {
  return (
    <PlannedPage
      title={"Security Analysis"}
      phase={3}
      summary={"Contract and liquidity risk checks with explicit unknowns."}
      bullets={["GoPlus token security for EVM chains and Solana; RugCheck as an optional Solana cross-check", "Every check is pass / risk / warn / unknown / unsupported \u2014 missing data is never a pass", "Configurable hard exclusions, warnings and review requirements; stale assessments flagged", "Holder and LP concentration, mint/freeze authority, taxes, proxies, blacklists, ownership"]}
      limitations={["Security heuristics are not an audit and can miss malicious contracts.", "GoPlus free-tier terms may change (reports of a move to paid plans); the system degrades to 'unknown' rather than 'safe'."]}
    />
  );
}
