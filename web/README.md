# CIT web (Next.js 16)

Dashboard for the Crypto Intelligence Terminal. Reads data through Supabase
with the signed-in user's JWT, so Postgres row-level security decides what is
visible. No privileged credentials ever reach this app.

```bash
npm ci
cp ../.env.example .env.local   # set NEXT_PUBLIC_SUPABASE_URL / _ANON_KEY
npm run dev        # http://localhost:3000
npm run lint && npm run typecheck && npm test && npm run build
```

Notes for Next.js 16: auth gating lives in `src/proxy.ts` (formerly
middleware); `cookies()`, `params` and `searchParams` are async; Cache
Components is on, so request-time data is rendered inside `<Suspense>`
(see `src/components/guard.tsx`).
