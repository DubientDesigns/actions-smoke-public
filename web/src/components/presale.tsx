import { Badge } from "@/components/ui/badge";

/** Provenance of a presale record — never a judgement of legitimacy. */
export function VerificationBadge({ v }: { v: string }) {
  const tone = v === "partially_verified" || v === "official_source_seen" ? "accent" : v === "unverified" ? "unknown" : "risk";
  return <Badge tone={tone}>{v.replaceAll("_", " ")}</Badge>;
}
