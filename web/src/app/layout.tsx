import type { Metadata, Viewport } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Crypto Intelligence Terminal", template: "%s · CIT" },
  description: "Private research terminal. Not financial advice. No trading functionality.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { themeColor: "#0d0f12" };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable} h-full antialiased`}>
      <body className="min-h-full bg-bg text-fg">{children}</body>
    </html>
  );
}
