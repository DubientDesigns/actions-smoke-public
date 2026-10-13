import { PlannedPage } from "@/components/planned-page";

export const metadata = { title: "AI Research Reports" };

export default function Page() {
  return (
    <PlannedPage
      title={"AI Research Reports"}
      phase={5}
      summary={"Structured, schema-validated research reports generated only after deterministic filtering."}
      bullets={["Claude API with daily request/token caps and a monthly USD cap (default $10)", "Evidence bundle with provenance for every claim; retrieved web/Telegram text treated as untrusted data", "Cached by evidence hash; regenerated only on material change; Batch API where latency allows"]}
      limitations={["Disabled until you provide an API key and confirm the budget."]}
    />
  );
}
