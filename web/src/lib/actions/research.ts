"use server";

import { redirect, unstable_rethrow } from "next/navigation";
import { getViewer } from "@/lib/data";

// Owners can queue an AI research report. The request goes to the internal API
// (server-to-server, bearer token) which queues it; budget caps still apply in
// the worker. The browser never sees the internal URL or token.
export async function requestResearch(fd: FormData) {
  const tokenId = Number(fd.get("token_id"));
  const back = String(fd.get("back") ?? "/research");
  const safeBack = back.startsWith("/") && !back.startsWith("//") ? back : "/research";
  let msg = "Report queued; it will be generated within the hour if the AI budget allows.";
  try {
    const viewer = await getViewer();
    if (viewer.role !== "owner") throw new Error("Only owners can request reports.");
    if (!Number.isInteger(tokenId) || tokenId <= 0) throw new Error("Invalid token.");
    const base = process.env.CIT_INTERNAL_API_URL;
    const token = process.env.CIT_INTERNAL_API_TOKEN;
    if (!base || !token) throw new Error("Internal API is not configured (CIT_INTERNAL_API_URL / CIT_INTERNAL_API_TOKEN).");
    const res = await fetch(`${base.replace(/\/$/, "")}/v1/research/requests`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
      body: JSON.stringify({ token_id: tokenId, requested_by: viewer.userId }),
      cache: "no-store",
    });
    if (!res.ok) throw new Error(`Request failed (${res.status}).`);
    const body = (await res.json()) as { status: string };
    if (body.status === "already_queued") msg = "A report for this token is already queued.";
  } catch (e) {
    unstable_rethrow(e);
    redirect(`${safeBack}?error=${encodeURIComponent(e instanceof Error ? e.message : "request failed")}`);
  }
  redirect(`${safeBack}?notice=${encodeURIComponent(msg)}`);
}
