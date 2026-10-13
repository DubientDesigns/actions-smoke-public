import { Badge } from "@/components/ui/badge";

export function PriorityBadge({ p }: { p: string | null }) {
  if (!p) return <span className="text-fg-dim">—</span>;
  const tone = p === "high" ? "accent" : p === "avoid" ? "risk" : p === "insufficient_data" ? "unknown" : "neutral";
  return <Badge tone={tone}>{p.replaceAll("_", " ")}</Badge>;
}

export function StatusPill({ s }: { s: string }) {
  const tone = s === "complete" ? "ok" : s === "failed" || s === "rejected_schema" ? "risk" : s === "skipped_budget" ? "warn" : "unknown";
  return <Badge tone={tone}>{s.replaceAll("_", " ")}</Badge>;
}

