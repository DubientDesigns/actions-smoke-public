import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badge = cva(
  "inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-px text-[11px] font-medium leading-4",
  {
    variants: {
      tone: {
        neutral: "border-border-strong bg-panel-2 text-fg-muted",
        ok: "border-ok/30 bg-ok/10 text-ok",
        warn: "border-warn/30 bg-warn/10 text-warn",
        risk: "border-risk/30 bg-risk/10 text-risk",
        unknown: "border-unknown/30 bg-unknown/10 text-unknown",
        accent: "border-accent/30 bg-accent/10 text-accent",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export function Badge({
  className,
  tone,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badge>) {
  return <span className={cn(badge({ tone }), className)} {...props} />;
}
