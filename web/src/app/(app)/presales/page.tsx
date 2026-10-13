import { PlannedPage } from "@/components/planned-page";

export const metadata = { title: "Presale Radar" };

export default function Page() {
  return (
    <PlannedPage
      title={"Presale Radar"}
      phase={4}
      summary={"Upcoming presales and private sales, tracked separately from trading tokens."}
      bullets={["Manual watchlist with per-claim provenance (presale_claims) and verification status", "Monitoring of official project announcement channels the operator registers", "Separate presale scorecard (no price history or liquidity exists yet)", "Deadline alerts for sale start/end and TGE"]}
      limitations={["No reliable free, ToS-compatible presale feed was found (CryptoRank free tier is non-commercial and overview-only; PinkSale/ICODrops publish no API). Coverage will be manual-first.", "Verification status describes provenance only \u2014 never that a sale is legitimate or safe."]}
    />
  );
}
