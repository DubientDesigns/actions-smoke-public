import { cn } from "@/lib/utils";

export const fieldCls =
  "mt-0.5 block w-full rounded border border-border-strong bg-panel-2 px-2 py-1 text-[13px] outline-none focus:border-accent";

export function Field({ label, hint, children, className }: { label: string; hint?: string; children: React.ReactNode; className?: string }) {
  return (
    <label className={cn("block text-[11px] text-fg-dim", className)}>
      {label}
      {children}
      {hint ? <span className="mt-0.5 block text-[10px] text-fg-dim">{hint}</span> : null}
    </label>
  );
}

export function Submit({ children }: { children: React.ReactNode }) {
  return (
    <button type="submit" className="rounded border border-accent/60 bg-accent/10 px-3 py-1 text-[13px] text-accent hover:bg-accent/20">
      {children}
    </button>
  );
}

export function FormError({ error }: { error?: string }) {
  if (!error) return null;
  return <div className="mb-3 rounded border border-risk/40 bg-risk/10 px-3 py-2 text-[13px] text-risk">{error}</div>;
}

export function Options({ values, labels }: { values: readonly string[]; labels?: Record<string, string> }) {
  return (
    <>
      {values.map((v) => (
        <option key={v} value={v}>
          {labels?.[v] ?? v.replaceAll("_", " ")}
        </option>
      ))}
    </>
  );
}

/** Collapsible owner-only form panel. */
export function FormPanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <details className="rounded-md border border-border bg-panel">
      <summary className="cursor-pointer px-4 py-2.5 text-[13px] font-medium hover:text-accent">+ {title}</summary>
      <div className="border-t border-border p-4">{children}</div>
    </details>
  );
}

export function FormNotice({ notice }: { notice?: string }) {
  if (!notice) return null;
  return <div className="mb-3 rounded border border-ok/40 bg-ok/10 px-3 py-2 text-[13px] text-ok">{notice}</div>;
}
