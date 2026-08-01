import Link from "next/link";
import { notFound } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { prisma } from "@/lib/prisma";
import { formatDateTimeBangkok } from "@/lib/time";

export default async function PmOpportunityDetailPage({ params }: { params: { id: string } }) {
  const opp = await prisma.pmOpportunity.findUnique({
    where: { id: params.id },
    include: {
      market: true,
      cycle: true,
      analyses: { include: { analysis: { select: { id: true, storyKey: true, promptVersion: true, model: true } } } },
      outcome: true,
    },
  });

  if (!opp) notFound();

  return (
    <div className="flex flex-col gap-4">
      <Link href="/polymarket" className="text-sm text-muted-foreground hover:underline">
        ← Back to Polymarket opportunities
      </Link>

      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={opp.side === "YES" ? "success" : "destructive"}>{opp.side} looks cheap</Badge>
        <Badge variant="outline">{opp.discovery === "news" ? "news-driven" : "top-volume scan"}</Badge>
        {opp.market.category && <Badge variant="secondary">{opp.market.category}</Badge>}
        <span className="ml-auto text-sm text-muted-foreground">{formatDateTimeBangkok(opp.createdAt)}</span>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{opp.market.question}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <p className="text-sm">{opp.reasoning}</p>
          <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
            <span>market price: {Number(opp.marketPrice).toFixed(2)}</span>
            <span>LLM estimate: {Number(opp.estProbability).toFixed(2)}</span>
            <span className="font-medium text-foreground">edge: {Number(opp.edgePoints).toFixed(1)} pts</span>
            <span>confidence: {Number(opp.confidence).toFixed(2)}</span>
            {opp.market.liquidityUsd !== null && <span>liquidity: ${Number(opp.market.liquidityUsd).toLocaleString()}</span>}
            {opp.market.volume24hUsd !== null && <span>24h volume: ${Number(opp.market.volume24hUsd).toLocaleString()}</span>}
            {opp.market.endDate && <span>resolves: {formatDateTimeBangkok(opp.market.endDate)}</span>}
          </div>
          <p className="text-xs text-muted-foreground">
            Link to the live market on polymarket.com is coming in a future version.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Provenance</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          <div>
            <span className="font-medium">Cycle:</span>{" "}
            <Link href={`/digests/${opp.cycle.id}`} className="text-primary hover:underline">
              {formatDateTimeBangkok(opp.cycle.scheduledFor)} ({opp.cycle.kind})
            </Link>
          </div>
          <div>
            <span className="font-medium">Model:</span>{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">{opp.model}</code>, prompt_version=
            <code className="rounded bg-muted px-1 py-0.5 text-xs">{opp.promptVersion}</code>
          </div>
          {opp.analyses.length > 0 ? (
            <div>
              <span className="font-medium">Related news storylines ({opp.analyses.length}):</span>
              <ul className="mt-1 flex flex-col gap-1">
                {opp.analyses.map((a) => (
                  <li key={a.analysis.id}>
                    <code className="rounded bg-muted px-1 py-0.5 text-xs">{a.analysis.storyKey}</code>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">Discovered via top-volume scan — no matched news storylines.</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Rule evaluation trace</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">{JSON.stringify(opp.ruleTrace, null, 2)}</pre>
        </CardContent>
      </Card>

      {opp.outcome && (
        <Card>
          <CardHeader>
            <CardTitle>Outcome</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-4 text-sm">
            <span>status: {opp.outcome.status}</span>
            {opp.outcome.price1d !== null && <span>T+1 price: {Number(opp.outcome.price1d).toFixed(2)}</span>}
            {opp.outcome.price3d !== null && <span>T+3 price: {Number(opp.outcome.price3d).toFixed(2)}</span>}
            {opp.outcome.price7d !== null && <span>T+7 price: {Number(opp.outcome.price7d).toFixed(2)}</span>}
            {opp.outcome.resolved && <span>resolution: {opp.outcome.resolution}</span>}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
