import Link from "next/link";
import { notFound } from "next/navigation";

import { ActionBadge } from "@/components/action-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { prisma } from "@/lib/prisma";
import { formatDateTimeBangkok } from "@/lib/time";

export default async function RecommendationDetailPage({ params }: { params: { id: string } }) {
  const rec = await prisma.recommendation.findUnique({
    where: { id: params.id },
    include: {
      topic: true,
      cycle: true,
      analysis: {
        include: { primaryItem: { include: { source: true } } },
      },
      sources: { include: { newsItem: { include: { source: true } } } },
      outcome: true,
    },
  });

  if (!rec) notFound();

  const result = rec.analysis.result as {
    horizon?: string;
    caveats?: string;
    unmapped_sectors?: { sector: string; note: string }[];
  } | null;

  return (
    <div className="flex flex-col gap-4">
      <Link href="/" className="text-sm text-muted-foreground hover:underline">
        ← Back to feed
      </Link>

      <div className="flex flex-wrap items-center gap-2">
        <ActionBadge action={rec.action} />
        <Badge variant="outline">{rec.market}</Badge>
        <span className="text-lg font-semibold">{rec.sector}</span>
        {rec.tickers.map((t) => (
          <Badge key={t} variant="secondary">
            {t}
          </Badge>
        ))}
        <span className="ml-auto text-sm text-muted-foreground">{formatDateTimeBangkok(rec.createdAt)}</span>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Reasoning</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <p className="text-sm">{rec.reasoning}</p>
          <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
            <span>confidence: {Number(rec.confidence).toFixed(2)}</span>
            {rec.topic && <span>topic: {rec.topic.name} (sensitivity {Number(rec.topic.sensitivity).toFixed(2)})</span>}
            {!rec.topic && <span>unconfigured but significant</span>}
            {result?.horizon && <span>horizon: {result.horizon}</span>}
          </div>
          {result?.caveats && <p className="text-xs italic text-muted-foreground">Caveats: {result.caveats}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Provenance</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          <div>
            <span className="font-medium">Cycle:</span>{" "}
            <Link href={`/digests/${rec.cycle.id}`} className="text-primary hover:underline">
              {formatDateTimeBangkok(rec.cycle.scheduledFor)} ({rec.cycle.kind})
            </Link>
          </div>
          <div>
            <span className="font-medium">Analysis:</span> story_key=
            <code className="rounded bg-muted px-1 py-0.5 text-xs">{rec.analysis.storyKey}</code>, prompt_version=
            <code className="rounded bg-muted px-1 py-0.5 text-xs">{rec.analysis.promptVersion}</code>, model=
            <code className="rounded bg-muted px-1 py-0.5 text-xs">{rec.analysis.model}</code>
          </div>
          <div>
            <span className="font-medium">News items ({rec.sources.length}):</span>
            <ul className="mt-1 flex flex-col gap-1">
              {rec.sources.map((s) => (
                <li key={s.newsItem.id}>
                  <a href={s.newsItem.url} target="_blank" rel="noreferrer" className="text-primary hover:underline">
                    {s.newsItem.title}
                  </a>{" "}
                  <span className="text-xs text-muted-foreground">
                    — {s.newsItem.source.name}
                    {s.newsItem.id === rec.analysis.primaryItemId ? " (primary)" : ""}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Rule evaluation trace</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">
            {JSON.stringify(rec.ruleTrace, null, 2)}
          </pre>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Full analysis JSON</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">
            {JSON.stringify(rec.analysis.result, null, 2)}
          </pre>
        </CardContent>
      </Card>

      {rec.outcome && (
        <Card>
          <CardHeader>
            <CardTitle>Outcome</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-4 text-sm">
            <span>status: {rec.outcome.status}</span>
            {rec.outcome.ret1d !== null && <span>T+1: {Number(rec.outcome.ret1d).toFixed(2)}%</span>}
            {rec.outcome.ret3d !== null && <span>T+3: {Number(rec.outcome.ret3d).toFixed(2)}%</span>}
            {rec.outcome.ret7d !== null && <span>T+7: {Number(rec.outcome.ret7d).toFixed(2)}%</span>}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
