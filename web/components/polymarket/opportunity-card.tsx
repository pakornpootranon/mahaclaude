import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { formatDateTimeBangkok } from "@/lib/time";

export interface PmOpportunityListItem {
  id: string;
  discovery: string;
  side: string;
  marketPrice: string | number;
  estProbability: string | number;
  edgePoints: string | number;
  confidence: string | number;
  reasoning: string;
  createdAt: string;
  market: {
    id: string;
    question: string;
    slug: string;
    category: string | null;
    liquidityUsd: string | number | null;
    volume24hUsd: string | number | null;
    endDate: string | null;
    url: string;
  };
  relatedStorylines: string[];
}

export function PmOpportunityCard({ opp }: { opp: PmOpportunityListItem }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-2 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={opp.side === "YES" ? "success" : "destructive"}>{opp.side} looks cheap</Badge>
          <Badge variant="outline">{opp.discovery === "news" ? "news-driven" : "top-volume scan"}</Badge>
          {opp.market.category && <Badge variant="secondary">{opp.market.category}</Badge>}
          <span className="ml-auto text-xs text-muted-foreground">{formatDateTimeBangkok(opp.createdAt)}</span>
        </div>

        <p className="font-medium">{opp.market.question}</p>
        <p className="text-sm">{opp.reasoning}</p>

        <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
          <span>market price {Number(opp.marketPrice).toFixed(2)}</span>
          <span>LLM estimate {Number(opp.estProbability).toFixed(2)}</span>
          <span className="font-medium text-foreground">edge {Number(opp.edgePoints).toFixed(1)} pts</span>
          <span>confidence {Number(opp.confidence).toFixed(2)}</span>
          {opp.market.liquidityUsd !== null && <span>liquidity ${Number(opp.market.liquidityUsd).toLocaleString()}</span>}
        </div>

        {opp.relatedStorylines.length > 0 && (
          <p className="text-xs text-muted-foreground">related storylines: {opp.relatedStorylines.join(", ")}</p>
        )}

        <div className="flex items-center gap-3">
          <Link href={`/polymarket/${opp.id}`} className="text-xs font-medium text-primary hover:underline">
            View detail & provenance →
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}
