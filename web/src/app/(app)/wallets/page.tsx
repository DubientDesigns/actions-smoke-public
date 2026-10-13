import { PlannedPage } from "@/components/planned-page";

export const metadata = { title: "Wallet Watchlist" };

export default function Page() {
  return (
    <PlannedPage
      title={"Wallet Watchlist"}
      phase={4}
      summary={"Activity of wallets you choose to track (deployers, team, smart money)."}
      bullets={["Manual wallet registry per chain", "Event ingestion via free tiers: Alchemy (EVM) and Helius (Solana)", "Alerts on significant transfers and liquidity removal"]}
      limitations={["Etherscan's free API no longer covers BNB Chain or Base; those chains will rely on Alchemy free tier limits."]}
    />
  );
}
