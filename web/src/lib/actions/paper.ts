"use server";

import { redirect, unstable_rethrow } from "next/navigation";
import { getViewer } from "@/lib/data";
import { postInternal } from "@/lib/internal-api";
import { parsePaperOrder } from "@/lib/paper";

// Paper orders are simulations only: the internal API records an order that the
// worker fills against later observed prices. There is no wallet, key or swap.

function backTo(fd: FormData): string {
  const back = String(fd.get("back") ?? "/paper");
  return back.startsWith("/") && !back.startsWith("//") ? back : "/paper";
}

async function ownerId(): Promise<string> {
  const viewer = await getViewer();
  if (viewer.role !== "owner" || !viewer.userId) throw new Error("Only owners can place paper orders.");
  return viewer.userId;
}

export async function placePaperOrder(fd: FormData) {
  const back = backTo(fd);
  let msg = "Paper order queued. It fills with the first price observed after the execution delay.";
  try {
    const body = parsePaperOrder(fd);
    const res = await postInternal<{ order_id: number }>("/v1/paper/orders", { ...body, requested_by: await ownerId() });
    if (!res.ok) throw new Error(res.detail ?? `Request failed (${res.status}).`);
    if (body.kind === "presale") msg = "Paper presale allocation queued at the recorded sale price; tokens stay locked per the vesting schedule.";
  } catch (e) {
    unstable_rethrow(e);
    redirect(`${back}?error=${encodeURIComponent(e instanceof Error ? e.message : "request failed")}`);
  }
  redirect(`${back}?notice=${encodeURIComponent(msg)}`);
}

export async function cancelPaperOrder(fd: FormData) {
  const back = backTo(fd);
  try {
    const orderId = Number(fd.get("order_id"));
    if (!Number.isInteger(orderId) || orderId <= 0) throw new Error("Invalid order.");
    const res = await postInternal(`/v1/paper/orders/${orderId}/cancel`, { requested_by: await ownerId() });
    if (!res.ok) throw new Error(res.detail ?? `Request failed (${res.status}).`);
  } catch (e) {
    unstable_rethrow(e);
    redirect(`${back}?error=${encodeURIComponent(e instanceof Error ? e.message : "request failed")}`);
  }
  redirect(`${back}?notice=${encodeURIComponent("Order cancelled.")}`);
}
