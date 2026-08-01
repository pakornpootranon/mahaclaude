import Link from "next/link";

import { ActionBadge } from "@/components/action-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { formatDateTimeBangkok } from "@/lib/time";

export interface RecommendationListItem {
  id: string;
  action: string;
  market: string;
  sector: string;
  tickers: string[];
  confidence: string | number;
  reasoning: string;
  createdAt: string;
  topic: { id: string; name: string } | null;
  sources: { title: string; url: string; sourceName: string }[];
}

export function RecommendationCard({ rec }: { rec: RecommendationListItem }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-2 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <ActionBadge action={rec.action} />
          <Badge variant="outline">{rec.market}</Badge>
          <span className="font-medium">{rec.sector}</span>
          {rec.tickers.map((t) => (
            <Badge key={t} variant="secondary">
              {t}
            </Badge>
          ))}
          <span className="ml-auto text-xs text-muted-foreground">{formatDateTimeBangkok(rec.createdAt)}</span>
        </div>

        <p className="text-sm">{rec.reasoning}</p>

        <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
          <span>confidence {Number(rec.confidence).toFixed(2)}</span>
          {rec.topic && <span>topic: {rec.topic.name}</span>}
          {rec.sources.slice(0, 2).map((s) => (
            <a
              key={s.url}
              href={s.url}
              target="_blank"
              rel="noreferrer"
              className="underline hover:text-foreground"
              onClick={(e) => e.stopPropagation()}
            >
              {s.sourceName}: {s.title}
            </a>
          ))}
        </div>

        <Link href={`/recommendations/${rec.id}`} className="text-xs font-medium text-primary hover:underline">
          View detail & provenance →
        </Link>
      </CardContent>
    </Card>
  );
}
