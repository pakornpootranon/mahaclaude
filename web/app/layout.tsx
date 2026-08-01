import type { Metadata } from "next";
import "./globals.css";

import { Badge } from "@/components/ui/badge";
import { Nav } from "@/components/nav";
import { StatusBar } from "@/components/status-bar";
import { ThemeProvider, THEME_INIT_SCRIPT } from "@/components/theme-provider";
import { ThemeToggle } from "@/components/theme-toggle";
import { APP_VERSION } from "@/lib/version";

export const metadata: Metadata = {
  title: "Mahachai Market Watch",
  description: "Advisory news-to-action monitoring dashboard. Not financial advice.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Runs before paint so the theme is correct on first render - no
            flash of the wrong theme when a dark-mode user reloads. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body>
        <ThemeProvider>
          <div className="min-h-screen">
            <header className="border-b">
              <div className="flex items-center gap-4 overflow-x-auto px-4 py-3">
                <span className="flex shrink-0 items-center gap-2 text-lg font-semibold">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src="/logo.png" alt="" className="h-8 w-8 rounded-full" />
                  Mahachai Market Watch
                  <Badge variant="outline" className="align-middle text-[10px] font-normal">
                    v{APP_VERSION}
                  </Badge>
                </span>
                <Nav />
                <ThemeToggle />
              </div>
              <p className="border-t border-blue-200 bg-blue-50 px-4 py-1.5 text-center text-xs font-medium text-blue-900 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-200">
                Not financial advice — just opinion for your own further research. You are solely
                responsible for your own investment decisions.
              </p>
              <StatusBar />
            </header>
            <main className="mx-auto max-w-5xl overflow-x-hidden px-4 py-6">{children}</main>
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
