import { Sidebar } from "@/components/shell/sidebar";

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      <Sidebar />
      <main className="min-w-0 flex-1 px-4 py-5 lg:px-6">{children}</main>
    </div>
  );
}
