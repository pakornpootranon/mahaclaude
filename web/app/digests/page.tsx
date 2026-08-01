import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { prisma } from "@/lib/prisma";
import { formatDateTimeBangkok } from "@/lib/time";

// No request-dependent input, so Next.js would otherwise statically cache
// this at build time and freeze the cycle list.
export const dynamic = "force-dynamic";

const PAGE_SIZE = 30;

const MOOD_VARIANT: Record<string, "success" | "destructive" | "secondary" | "outline"> = {
  bullish: "success",
  bearish: "destructive",
  mixed: "secondary",
  cautious: "outline",
  quiet: "outline",
};

export default async function DigestsPage() {
  const cycles = await prisma.cycle.findMany({
    orderBy: [{ scheduledFor: "desc" }],
    take: PAGE_SIZE,
    include: { digest: true, _count: { select: { recommendations: true } } },
  });

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Digest history</h1>

      {cycles.length === 0 && (
        <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
          No cycles have run yet.
        </div>
      )}

      <div className="flex flex-col gap-2">
        {cycles.map((c) => (
          <Link key={c.id} href={`/digests/${c.id}`}>
            <Card className="transition-colors hover:bg-accent/50">
              <CardContent className="flex flex-wrap items-center gap-3 p-4">
                <span className="font-medium">{formatDateTimeBangkok(c.scheduledFor)}</span>
                <Badge variant="outline">{c.kind}</Badge>
                <Badge variant={c.state === "DONE" ? "success" : c.state === "FAILED" ? "destructive" : "secondary"}>
                  {c.state}
                </Badge>
                {c.digest && <Badge variant={MOOD_VARIANT[c.digest.marketMood] ?? "outline"}>{c.digest.marketMood}</Badge>}
                {c.budgetHit && <Badge variant="warning">budget reached</Badge>}
                <span className="text-sm text-muted-foreground">{c._count.recommendations} recommendation(s)</span>
                {c.digest && <p className="w-full text-sm text-muted-foreground line-clamp-1">{c.digest.synthesis}</p>}
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
