"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/settings/sources", label: "Sources" },
  { href: "/settings/mcp-connectors", label: "MCP Connectors" },
  { href: "/settings/topics", label: "Topics & Mappings" },
  { href: "/settings/rules", label: "Rules" },
  { href: "/settings/schedule", label: "Schedule" },
  { href: "/settings/llm", label: "LLM" },
  { href: "/settings/polymarket", label: "Polymarket" },
  { href: "/settings/export-import", label: "Export / Import" },
];

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex flex-col gap-6 md:flex-row">
      <nav className="flex shrink-0 flex-row flex-wrap gap-1 md:w-48 md:flex-col">
        {LINKS.map((link) => {
          const active = pathname.startsWith(link.href);
          return (
            <Link
              key={link.href}
              href={link.href}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                active ? "bg-secondary text-secondary-foreground" : "text-muted-foreground hover:text-foreground"
              )}
            >
              {link.label}
            </Link>
          );
        })}
      </nav>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
