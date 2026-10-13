import { PlannedPage } from "@/components/planned-page";

export const metadata = { title: "Paper Portfolio" };

export default function Page() {
  return (
    <PlannedPage
      title={"Paper Portfolio"}
      phase={6}
      summary={"Forward-only virtual portfolio (default S$10,000). No real funds, no wallets, no execution."}
      bullets={["Manual and rule-based paper entries with execution delay, fees, constant-product slippage and liquidity caps", "Database-enforced look-ahead guard: fills can never use prices observed before the signal", "Partial exits, stop-loss / take-profit simulation, untradeable marking, presale vesting", "All evaluations recorded, including rejected and missed opportunities"]}
      limitations={undefined}
    />
  );
}
