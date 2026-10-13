import { PlannedPage } from "@/components/planned-page";

export const metadata = { title: "Influencer Intelligence" };

export default function Page() {
  return (
    <PlannedPage
      title={"Influencer Intelligence"}
      phase={4}
      summary={"Public mentions from registered sources and the forward performance of what they promote."}
      bullets={["Source registry with explicit access basis (public / authorised member / official)", "Mentions with exact contract, forward/original flag, promo disclosure and referral links", "Forward performance from the first price observed after the mention (24h/7d/30d, max gain, max drawdown, exit feasibility) including failed and delisted tokens", "Coordination clusters: accounts are never assumed independent"]}
      limitations={["Telegram's 2026 terms prohibit scraping and AI use of platform data; collection will use a bot only in chats where it is explicitly added, plus manual entry. A user-account (MTProto) reader needs your explicit approval.", "X/Twitter API access is paid; not planned within budget."]}
    />
  );
}
