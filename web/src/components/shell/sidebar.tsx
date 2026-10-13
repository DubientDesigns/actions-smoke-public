"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useState } from "react";
import { Menu, X } from "lucide-react";
import { CURRENT_PHASE, NAV } from "@/lib/nav";
import { cn } from "@/lib/utils";

// usePathname() is runtime data: it streams inside <Suspense>, with a static
// (un-highlighted) list as the prerendered fallback.
function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <Suspense fallback={<NavList pathname={null} onNavigate={onNavigate} />}>
      <ActiveNavList onNavigate={onNavigate} />
    </Suspense>
  );
}

function ActiveNavList({ onNavigate }: { onNavigate?: () => void }) {
  return <NavList pathname={usePathname()} onNavigate={onNavigate} />;
}

function NavList({ pathname, onNavigate }: { pathname: string | null; onNavigate?: () => void }) {
  return (
    <nav className="flex flex-col gap-px p-2">
      {NAV.map((item) => {
        const active = pathname !== null && (item.href === "/" ? pathname === "/" : pathname.startsWith(item.href));
        const pending = item.phase > CURRENT_PHASE;
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            className={cn(
              "flex items-center gap-2.5 rounded px-2.5 py-1.5 text-[13px] text-fg-muted hover:bg-panel-2 hover:text-fg",
              active && "bg-panel-2 text-fg",
            )}
          >
            <item.icon className="size-4 shrink-0" strokeWidth={1.75} />
            <span className="truncate">{item.label}</span>
            {pending ? <span className="ml-auto text-[10px] text-fg-dim">P{item.phase}</span> : null}
          </Link>
        );
      })}
    </nav>
  );
}

function Brand() {
  return (
    <div className="flex h-12 items-center gap-2 border-b border-border px-4">
      <div className="size-2 rounded-full bg-accent" />
      <span className="text-[13px] font-semibold tracking-wide">CRYPTO INTELLIGENCE</span>
    </div>
  );
}

export function Sidebar() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <aside className="hidden w-60 shrink-0 border-r border-border bg-panel lg:block">
        <div className="sticky top-0">
          <Brand />
          <NavLinks />
          <p className="px-4 pt-4 text-[11px] leading-relaxed text-fg-dim">
            Research only. No trading, no wallets, no keys. Nothing here is financial advice.
          </p>
        </div>
      </aside>
      <div className="flex h-12 items-center justify-between border-b border-border bg-panel px-4 lg:hidden">
        <span className="text-[13px] font-semibold tracking-wide">CIT</span>
        <button aria-label="Open navigation" onClick={() => setOpen(true)} className="p-1 text-fg-muted">
          <Menu className="size-5" />
        </button>
      </div>
      {open ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-64 overflow-y-auto border-r border-border bg-panel">
            <div className="flex items-center justify-between pr-2">
              <Brand />
              <button aria-label="Close navigation" onClick={() => setOpen(false)} className="p-1 text-fg-muted">
                <X className="size-5" />
              </button>
            </div>
            <NavLinks onNavigate={() => setOpen(false)} />
          </div>
        </div>
      ) : null}
    </>
  );
}
