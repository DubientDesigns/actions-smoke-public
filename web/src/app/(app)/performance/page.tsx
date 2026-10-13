import { PlannedPage } from "@/components/planned-page";

export const metadata = { title: "Historical Performance" };

export default function Page() {
  return (
    <PlannedPage
      title={"Historical Performance"}
      phase={6}
      summary={"Equity curve, drawdown and strategy statistics from forward paper trading."}
      bullets={["Equity curve and drawdown from daily liquidity-haircut marks", "Win rate, profit factor, MAE/MFE per strategy version", "Reproducible evaluations keyed by strategy version and input hash"]}
      limitations={undefined}
    />
  );
}
