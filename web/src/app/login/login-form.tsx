"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { supabaseConfigured } from "@/lib/env";

function safeNext(): string {
  if (typeof window === "undefined") return "/";
  const next = new URLSearchParams(window.location.search).get("next") ?? "/";
  // Only same-origin relative paths: prevents open redirects.
  return next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export function LoginForm() {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!supabaseConfigured()) {
    return <p className="text-[13px] text-warn">Supabase environment variables are not configured.</p>;
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const form = new FormData(e.currentTarget);
    const { error } = await createClient().auth.signInWithPassword({
      email: String(form.get("email") ?? ""),
      password: String(form.get("password") ?? ""),
    });
    setBusy(false);
    if (error) {
      setError("Sign-in failed. Check your credentials.");
      return;
    }
    window.location.assign(safeNext());
  }

  return (
    <form onSubmit={onSubmit} className="space-y-3">
      <label className="block text-xs text-fg-muted">
        Email
        <input name="email" type="email" required autoComplete="email"
          className="mt-1 w-full rounded border border-border-strong bg-panel-2 px-2.5 py-1.5 text-[13px] outline-none focus:border-accent" />
      </label>
      <label className="block text-xs text-fg-muted">
        Password
        <input name="password" type="password" required autoComplete="current-password"
          className="mt-1 w-full rounded border border-border-strong bg-panel-2 px-2.5 py-1.5 text-[13px] outline-none focus:border-accent" />
      </label>
      {error ? <p className="text-xs text-risk">{error}</p> : null}
      <button type="submit" disabled={busy}
        className="w-full rounded bg-accent px-3 py-1.5 text-[13px] font-medium text-black disabled:opacity-50">
        {busy ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
