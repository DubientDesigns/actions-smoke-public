import { connection } from "next/server";
import { NotAllowlistedError, requireAllowlisted } from "@/lib/data";
import { supabaseConfigured } from "@/lib/env";

/**
 * Wraps data-bearing sections. Renders a clear message instead of an empty
 * page when Supabase is not configured or the user is not allowlisted.
 */
export async function Guarded({ children }: { children: React.ReactNode }) {
  // Always request-time: never prerender a data section (or its error state) at build.
  await connection();
  if (!supabaseConfigured()) {
    return <Notice title="Supabase is not configured">Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY.</Notice>;
  }
  try {
    await requireAllowlisted();
  } catch (e) {
    if (e instanceof NotAllowlistedError) {
      return (
        <Notice title="Account not allowlisted">
          You are signed in, but your user is not in <code>app_users</code>. An owner must add you (see docs/OPERATIONS.md).
        </Notice>
      );
    }
    throw e;
  }
  return <>{children}</>;
}

export function Notice({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-warn/40 bg-warn/5 px-4 py-3 text-[13px]">
      <div className="font-medium text-warn">{title}</div>
      <div className="mt-1 text-fg-muted">{children}</div>
    </div>
  );
}
