import Link from "next/link";
import { X } from "lucide-react";
import { deleteView, saveView } from "@/lib/actions/saved-views";
import { listSavedViews } from "@/lib/data";

export async function SavedViews({ page, path, query }: { page: string; path: string; query: string }) {
  const views = await listSavedViews(page);
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2 text-[12px]">
      <span className="text-fg-dim">Saved views:</span>
      {views.length === 0 ? <span className="text-fg-dim">none</span> : null}
      {views.map((v) => (
        <span key={v.id} className="inline-flex items-center gap-1 rounded border border-border-strong bg-panel-2 pl-2">
          <Link href={`${path}?${new URLSearchParams(v.params)}`} className="hover:text-accent">
            {v.name}
          </Link>
          <form action={deleteView}>
            <input type="hidden" name="id" value={v.id} />
            <input type="hidden" name="page" value={page} />
            <button aria-label={`Delete view ${v.name}`} className="px-1 py-0.5 text-fg-dim hover:text-risk">
              <X className="size-3" />
            </button>
          </form>
        </span>
      ))}
      <form action={saveView} className="ml-auto flex items-center gap-1">
        <input type="hidden" name="page" value={page} />
        <input type="hidden" name="query" value={query} />
        <input
          name="name"
          required
          maxLength={40}
          placeholder="Name this view"
          className="w-36 rounded border border-border-strong bg-panel-2 px-2 py-0.5 outline-none focus:border-accent"
        />
        <button className="rounded border border-border-strong px-2 py-0.5 hover:border-accent">Save</button>
      </form>
    </div>
  );
}
