import { Card, CardBody } from "@/components/ui/card";
import { PageHeader } from "@/components/data-display";

/** Honest placeholder for modules scheduled in later phases. Never shows mock data. */
export function PlannedPage({
  title,
  phase,
  summary,
  bullets,
  limitations,
}: {
  title: string;
  phase: number;
  summary: string;
  bullets: string[];
  limitations?: string[];
}) {
  return (
    <>
      <PageHeader title={title} description={summary} />
      <Card>
        <CardBody className="space-y-4 text-[13px]">
          <p className="text-fg-muted">
            <span className="rounded border border-warn/40 bg-warn/10 px-1.5 py-0.5 text-[11px] font-medium text-warn">
              NOT BUILT YET · PHASE {phase}
            </span>{" "}
            This module has its database tables in place but no ingestion or UI yet. No data is shown rather than
            placeholder data.
          </p>
          <div>
            <h3 className="mb-1 text-xs uppercase tracking-wider text-fg-dim">Planned scope</h3>
            <ul className="list-disc space-y-1 pl-5 text-fg-muted">
              {bullets.map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          </div>
          {limitations?.length ? (
            <div>
              <h3 className="mb-1 text-xs uppercase tracking-wider text-fg-dim">Known limitations</h3>
              <ul className="list-disc space-y-1 pl-5 text-fg-muted">
                {limitations.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </CardBody>
      </Card>
    </>
  );
}
