import { PlannedPage } from "@/components/planned-page";

export const metadata = { title: "Alerts" };

export default function Page() {
  return (
    <PlannedPage
      title={"Alerts"}
      phase={5}
      summary={"Telegram notifications with deduplication, severity, quiet hours and cooldowns."}
      bullets={["Categories: new tokens meeting filters, independent multi-source mentions, liquidity changes, wallet activity, new contract risks, presale deadlines, paper rules, source outages, spend thresholds", "Quiet hours (default 23:00\u201307:30 SGT), per-category cooldowns, hourly cap and daily digest"]}
      limitations={["Requires a Telegram bot token and chat id."]}
    />
  );
}
