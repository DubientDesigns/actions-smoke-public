// Allowlist for saved-view parameters (validated server-side before storage).
export const VIEW_PAGES: Record<string, string> = { discoveries: "/discoveries", tokens: "/tokens", security: "/security" };

const ALLOWED_KEYS = new Set(["chain", "minLiquidity", "maxAgeHours", "minScore", "risk", "sort", "q", "coverage", "stale"]);

export function sanitizeParams(query: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of new URLSearchParams(query)) {
    if (ALLOWED_KEYS.has(k) && v.length > 0 && v.length <= 64) out[k] = v;
  }
  return out;
}
