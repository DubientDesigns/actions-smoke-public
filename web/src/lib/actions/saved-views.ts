"use server";

import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";

import { sanitizeParams, VIEW_PAGES as PAGES } from "@/lib/view-params";

// Only known pages and allowlisted filter keys are stored; RLS restricts every
// row to its owner.

async function ownerId() {
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  const uid = data?.claims?.sub as string | undefined;
  if (!uid) redirect("/login");
  return { supabase, uid };
}

export async function saveView(formData: FormData) {
  const page = String(formData.get("page") ?? "");
  const name = String(formData.get("name") ?? "").trim().slice(0, 40);
  const base = PAGES[page];
  if (!base) redirect("/");
  const params = sanitizeParams(String(formData.get("query") ?? ""));
  if (name) {
    const { supabase, uid } = await ownerId();
    const { error } = await supabase
      .from("saved_views")
      .upsert({ owner_id: uid, page, name, params }, { onConflict: "owner_id,page,name" });
    if (error) throw new Error(error.message);
  }
  redirect(`${base}?${new URLSearchParams(params)}`);
}

export async function deleteView(formData: FormData) {
  const id = Number(formData.get("id"));
  const page = String(formData.get("page") ?? "");
  if (Number.isInteger(id) && id > 0) {
    const { supabase } = await ownerId();
    const { error } = await supabase.from("saved_views").delete().eq("id", id);
    if (error) throw new Error(error.message);
  }
  redirect(PAGES[page] ?? "/");
}
