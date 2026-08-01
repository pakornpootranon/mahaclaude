import type { Metadata } from "next";
import "./globals.css";

import { Nav } from "@/components/nav";
import { StatusBar } from "@/components/status-bar";

export const metadata: Metadata = {
  title: "newswatch",
  description: "Advisory news-to-action monitoring dashboard. Not financial advice.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen">
          <header className="border-b">
            <div className="flex items-center justify-between px-4 py-3">
              <div className="flex items-center gap-4">
                <span className="text-lg font-semibold">newswatch</span>
                <Nav />
              </div>
            </div>
            <StatusBar />
          </header>
          <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
        </div>
      </body>
    </html>
  );
}
