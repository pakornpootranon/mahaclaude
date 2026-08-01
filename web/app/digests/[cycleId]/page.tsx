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

const SIGNAL_VARIANT: Record<string, "success" | "destructive" | "outline"> = {
  BUY: "success",
  SELL: "destructive",
  "No Action": "outline",
};

interface RankedTicker {
  ticker: string;
  market: string;
  topics: string[];
  signal: "BUY" | "SELL" | "No Action";
  confidence: number | null;
  asOf: Date | null;
}

// Ranked BUY/SELL/No Action view across every topic's tickers, "as of" this
// cycle (latest recommendation with createdAt <= the cycle's own reference
// time) so a historical digest page stays reproducible rather than always
// reflecting today's state. Deterministic, not LLM-derived — mirrors the
// rules engine's own actions (CLAUDE.md: "the LLM never decides triggers").
async function rankTickerSignals(referenceTime: Date): Promise<RankedTicker[]> {
  const [mappings, recs] = await Promise.all([
    prisma.mapping.findMany({
      where: { enabled: true, topic: { enabled: true } },
      select: { market: true, tickers: true, topic: { select: { name: true } } },
    }),
    prisma.recommendation.findMany({
      where: { createdAt: { lte: referenceTime } },
      orderBy: { createdAt: "desc" },
      select: { tickers: true, action: true, confidence: true, createdAt: true },
    }),
  ]);

  const tickerMeta = new Map<string, { market: string; topics: Set<string> }>();
  for (const m of mappings) {
    for (const ticker of m.tickers) {
      const meta = tickerMeta.get(ticker) ?? { market: m.market, topics: new Set<string>() };
      if (m.topic) meta.topics.add(m.topic.name);
      tickerMeta.set(ticker, meta);
    }
  }

  const ranked: RankedTicker[] = [];
  for (const [ticker, meta] of tickerMeta) {
    const hit = recs.find((r) => r.tickers.includes(ticker));
    let signal: RankedTicker["signal"] = "No Action";
    if (hit?.action === "BUY") signal = "BUY";
    else if (hit?.action === "SELL") signal = "SELL";
    ranked.push({
      ticker,
      market: meta.market,
      topics: Array.from(meta.topics),
      signal,
      confidence: hit ? Number(hit.confidence) : null,
      asOf: hit?.createdAt ?? null,
    });
  }

  ranked.sort((a, b) => {
    const pa = a.signal === "No Action" ? 1 : 0;
    const pb = b.signal === "No Action" ? 1 : 0;
    if (pa !== pb) return pa - pb;
    if (pa === 0) return (b.confidence ?? 0) - (a.confidence ?? 0);
    return a.ticker.localeCompare(b.ticker);
  });
  return ranked;
}

export default async function DigestDetailPage({ params }: { params: { cycleId: string } }) {
  const cycle = await prisma.cycle.findUnique({
    where: { id: params.cycleId },
    include: {
      digest: true,
      recommendations: {
        orderBy: { confidence: "desc" },
        include: { topic: { select: { name: true } }, analysis: { select: { magnitude: true, result: true } } },
      },
      pmOpportunities: {
        orderBy: { edgePoints: "desc" },
        include: { market: true },
      },
      analyses: {
        orderBy: { magnitude: "desc" },
        include: {
          primaryItem: { select: { title: true } },
          analysisTopics: { include: { topic: { select: { name: true } } } },
          recommendations: { select: { id: true } },
        },
      },
    },
  });

  if (!cycle) notFound();

  const [prev, next, rankedTickers] = await Promise.all([
    prisma.cycle.findFirst({ where: { scheduledFor: { lt: cycle.scheduledFor } }, orderBy: { scheduledFor: "desc" } }),
    prisma.cycle.findFirst({ where: { scheduledFor: { gt: cycle.scheduledFor } }, orderBy: { scheduledFor: "asc" } }),
    rankTickerSignals(cycle.finishedAt ?? cycle.scheduledFor),
  ]);

  const stats = cycle.stats as Record<string, number | boolean | undefined>;
  const themes = (cycle.digest?.topThemes as { theme: string; why: string; item_count: number }[] | undefined) ?? [];
  const topicSummaries =
    (cycle.digest?.topicSummaries as { topic_id: string; topic_name: string; summary: string }[] | undefined) ?? [];

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
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive dark:bg-destructive/10 dark:text-red-400">
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
          <CardTitle>อันดับหุ้นแนะนำ (Ranked stock signals) — {rankedTickers.length}</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          {rankedTickers.length === 0 ? (
            <p className="text-sm text-muted-foreground">ยังไม่มีหุ้นในระบบ (no tickers configured across any topic&apos;s mappings yet).</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-1 pr-2">#</th>
                  <th className="py-1 pr-2">Ticker</th>
                  <th className="py-1 pr-2">Market</th>
                  <th className="py-1 pr-2">Signal</th>
                  <th className="py-1 pr-2">Confidence</th>
                  <th className="py-1 pr-2">As of</th>
                  <th className="py-1 pr-2">Topics</th>
                </tr>
              </thead>
              <tbody>
                {rankedTickers.map((t, i) => (
                  <tr key={t.ticker} className="border-b last:border-0">
                    <td className="py-1.5 pr-2 text-xs text-muted-foreground">{i + 1}</td>
                    <td className="py-1.5 pr-2 font-medium">{t.ticker}</td>
                    <td className="py-1.5 pr-2">{t.market}</td>
                    <td className="py-1.5 pr-2">
                      <Badge variant={SIGNAL_VARIANT[t.signal]}>{t.signal}</Badge>
                    </td>
                    <td className="py-1.5 pr-2">{t.confidence !== null ? t.confidence.toFixed(2) : "—"}</td>
                    <td className="py-1.5 pr-2 text-xs text-muted-foreground">
                      {t.asOf ? formatDateTimeBangkok(t.asOf) : "—"}
                    </td>
                    <td className="py-1.5 pr-2 text-xs text-muted-foreground">{t.topics.join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {topicSummaries.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>สรุปรายหัวข้อ (Topic summaries) — {topicSummaries.length}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {topicSummaries.map((t) => (
              <div key={t.topic_id} className="border-b pb-2 text-sm last:border-0">
                <p className="font-medium">{t.topic_name}</p>
                <p className="text-muted-foreground">{t.summary}</p>
              </div>
            ))}
          </CardContent>
        </Card>
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

      {cycle.pmOpportunities.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>
              <Link href="/polymarket" className="hover:underline">
                Polymarket opportunities ({cycle.pmOpportunities.length})
              </Link>
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {cycle.pmOpportunities.map((opp) => (
              <div key={opp.id} className="flex flex-wrap items-center gap-2 border-b pb-2 text-sm last:border-0">
                <Badge variant={opp.side === "YES" ? "success" : "destructive"}>{opp.side}</Badge>
                <Link href={`/polymarket/${opp.id}`} className="hover:underline">
                  {opp.market.question}
                </Link>
                <span className="ml-auto text-xs text-muted-foreground">
                  edge {Number(opp.edgePoints).toFixed(1)} pts, price {Number(opp.marketPrice).toFixed(2)} → est{" "}
                  {Number(opp.estProbability).toFixed(2)}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Recommendations ({cycle.recommendations.length})</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          {cycle.recommendations.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nothing triggered this cycle — see analyzed storylines below for what was reviewed and why it didn&apos;t
              clear the trigger thresholds.
            </p>
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
                  <th className="py-1 pr-2">Magnitude</th>
                  <th className="py-1 pr-2">Horizon</th>
                </tr>
              </thead>
              <tbody>
                {cycle.recommendations.map((r) => {
                  const result = r.analysis.result as { horizon?: string } | null;
                  return (
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
                      <td className="py-1.5 pr-2">{Number(r.analysis.magnitude).toFixed(2)}</td>
                      <td className="py-1.5 pr-2">{result?.horizon ?? "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Analyzed storylines ({cycle.analyses.length})</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          {cycle.analyses.length === 0 ? (
            <p className="text-sm text-muted-foreground">No storylines reached analysis this cycle.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-1 pr-2">Headline</th>
                  <th className="py-1 pr-2">Topics matched</th>
                  <th className="py-1 pr-2">Magnitude</th>
                  <th className="py-1 pr-2">Confidence</th>
                  <th className="py-1 pr-2">Horizon</th>
                  <th className="py-1 pr-2">Triggered</th>
                </tr>
              </thead>
              <tbody>
                {cycle.analyses.map((a) => {
                  const result = a.result as { horizon?: string } | null;
                  const matchedTopics = a.analysisTopics.map((at) => at.topic?.name ?? "unconfigured").join(", ");
                  return (
                    <tr key={a.id} className="border-b last:border-0">
                      <td className="max-w-xs truncate py-1.5 pr-2" title={a.primaryItem.title}>
                        {a.primaryItem.title}
                      </td>
                      <td className="py-1.5 pr-2 text-xs text-muted-foreground">{matchedTopics || "—"}</td>
                      <td className="py-1.5 pr-2">{Number(a.magnitude).toFixed(2)}</td>
                      <td className="py-1.5 pr-2">{Number(a.confidence).toFixed(2)}</td>
                      <td className="py-1.5 pr-2">{result?.horizon ?? "—"}</td>
                      <td className="py-1.5 pr-2">
                        {a.recommendations.length > 0 ? (
                          <Badge variant="success">yes ({a.recommendations.length})</Badge>
                        ) : (
                          <Badge variant="outline">no</Badge>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
