import Link from "next/link";
import { notFound } from "next/navigation";

import { ActionBadge } from "@/components/action-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { prisma } from "@/lib/prisma";
import { formatDateTimeBangkok } from "@/lib/time";

const MOOD_VARIANT: Record<string, "success" | "destructive" | "secondary" | "outline"> = {
  bullish: "success",
  bearish: "destructive",
  mixed: "secondary",
  cautious: "outline",
  quiet: "outline",
};

export default async function DigestDetailPage({ params }: { params: { cycleId: string } }) {
  const cycle = await prisma.cycle.findUnique({
    where: { id: params.cycleId },
    include: {
      digest: true,
      recommendations: {
        orderBy: { confidence: "desc" },
        include: { topic: { select: { name: true } } },
      },
    },
  });

  if (!cycle) notFound();

  const [prev, next] = await Promise.all([
    prisma.cycle.findFirst({ where: { scheduledFor: { lt: cycle.scheduledFor } }, orderBy: { scheduledFor: "desc" } }),
    prisma.cycle.findFirst({ where: { scheduledFor: { gt: cycle.scheduledFor } }, orderBy: { scheduledFor: "asc" } }),
  ]);

  const stats = cycle.stats as Record<string, number | boolean | undefined>;
  const themes = (cycle.digest?.topThemes as { theme: string; why: string; item_count: number }[] | undefined) ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <Link href="/digests" className="text-sm text-muted-foreground hover:underline">
          ← All digests
        </Link>
        <div className="flex gap-3 text-sm">
          {prev ? (
            <Link href={`/digests/${prev.id}`} className="text-primary hover:underline">
              ← earlier
            </Link>
          ) : (
            <span className="text-muted-foreground">← earlier</span>
          )}
          {next ? (
            <Link href={`/digests/${next.id}`} className="text-primary hover:underline">
              later →
            </Link>
          ) : (
            <span className="text-muted-foreground">later →</span>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold">{formatDateTimeBangkok(cycle.scheduledFor)}</h1>
        <Badge variant="outline">{cycle.kind}</Badge>
        <Badge variant={cycle.state === "DONE" ? "success" : cycle.state === "FAILED" ? "destructive" : "secondary"}>
          {cycle.state}
        </Badge>
        {cycle.digest && <Badge variant={MOOD_VARIANT[cycle.digest.marketMood] ?? "outline"}>{cycle.digest.marketMood}</Badge>}
        {cycle.budgetHit && <Badge variant="warning">LLM budget reached this cycle</Badge>}
      </div>

      {cycle.error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
          {cycle.error}
        </div>
      )}

      {cycle.digest ? (
        <Card>
          <CardHeader>
            <CardTitle>Market synthesis</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <p className="text-sm">{cycle.digest.synthesis}</p>
            {themes.length > 0 && (
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">Top themes</p>
                <ul className="flex flex-col gap-1">
                  {themes.map((t, i) => (
                    <li key={i} className="text-sm">
                      <span className="font-medium">{t.theme}</span> — {t.why}{" "}
                      <span className="text-xs text-muted-foreground">({t.item_count} item(s))</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
          No digest yet — this cycle hasn&apos;t reached SUMMARIZING.
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Cycle stats</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
            {Object.entries(stats).map(([key, value]) => (
              <div key={key} className="flex justify-between gap-2 sm:flex-col sm:justify-start">
                <dt className="text-xs text-muted-foreground">{key}</dt>
                <dd>{String(value)}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recommendations ({cycle.recommendations.length})</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          {cycle.recommendations.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nothing triggered this cycle.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-1 pr-2">Action</th>
                  <th className="py-1 pr-2">Market</th>
                  <th className="py-1 pr-2">Sector</th>
                  <th className="py-1 pr-2">Tickers</th>
                  <th className="py-1 pr-2">Topic</th>
                  <th className="py-1 pr-2">Confidence</th>
                </tr>
              </thead>
              <tbody>
                {cycle.recommendations.map((r) => (
                  <tr key={r.id} className="border-b last:border-0">
                    <td className="py-1.5 pr-2">
                      <Link href={`/recommendations/${r.id}`} className="hover:underline">
                        <ActionBadge action={r.action} />
                      </Link>
                    </td>
                    <td className="py-1.5 pr-2">{r.market}</td>
                    <td className="py-1.5 pr-2">{r.sector}</td>
                    <td className="py-1.5 pr-2">{r.tickers.join(", ") || "—"}</td>
                    <td className="py-1.5 pr-2">{r.topic?.name ?? "unconfigured"}</td>
                    <td className="py-1.5 pr-2">{Number(r.confidence).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
