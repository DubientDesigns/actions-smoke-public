import { Suspense } from "react";
import { PageHeader } from "@/components/data-display";
import { Guarded } from "@/components/guard";
import { Card, CardHeader } from "@/components/ui/card";
import { TableSkeleton } from "@/components/ui/skeleton";
import { listSettings, getViewer } from "@/lib/data";
import { formatSgt } from "@/lib/format";

export const metadata = { title: "Settings" };

export default function SettingsPage() {
  return (
    <>
      <PageHeader
        title="Settings"
        description="Runtime configuration stored in app_settings and validated by the backend. Read-only in this phase; edit via SQL or the CLI (see docs/OPERATIONS.md)."
      />
      <Suspense fallback={<TableSkeleton />}>
        <Guarded>
          <SettingsContent />
        </Guarded>
      </Suspense>
    </>
  );
}

async function SettingsContent() {
  const [viewer, settings] = await Promise.all([getViewer(), listSettings()]);
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="Account"
          right={
            <form action="/auth/signout" method="post">
              <button className="rounded border border-border-strong px-2.5 py-1 text-xs hover:border-risk hover:text-risk">Sign out</button>
            </form>
          }
        />
        <div className="px-4 py-3 text-[13px] text-fg-muted">
          {viewer.email ?? "unknown"} · role <span className="text-fg">{viewer.role}</span>
        </div>
      </Card>
      {settings.map((s) => (
        <Card key={s.key}>
          <CardHeader title={s.key} subtitle={`Updated ${formatSgt(s.updated_at)} by ${s.updated_by ?? "unknown"}`} />
          <pre className="num overflow-x-auto p-4 text-[12px] text-fg-muted">{JSON.stringify(s.value, null, 2)}</pre>
        </Card>
      ))}
    </div>
  );
}
