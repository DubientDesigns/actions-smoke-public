import "server-only";

/** Server-to-server call to the internal FastAPI service. The browser never sees the URL or token. */
export async function postInternal<T>(path: string, body: unknown): Promise<{ ok: boolean; status: number; data: T | null; detail: string | null }> {
  const base = process.env.CIT_INTERNAL_API_URL;
  const token = process.env.CIT_INTERNAL_API_TOKEN;
  if (!base || !token) throw new Error("Internal API is not configured (CIT_INTERNAL_API_URL / CIT_INTERNAL_API_TOKEN).");
  const res = await fetch(`${base.replace(/\/$/, "")}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  const json = (await res.json().catch(() => null)) as (T & { detail?: unknown }) | null;
  const detail = json && typeof json.detail === "string" ? json.detail : null;
  return { ok: res.ok, status: res.status, data: res.ok ? json : null, detail };
}
