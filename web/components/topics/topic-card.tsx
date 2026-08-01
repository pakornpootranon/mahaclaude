"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { relativeFromNow } from "@/lib/time";

export interface BoardMapping {
  id: string;
  market: string;
  sector: string;
  tickers: string[];
  polarity: number;
  enabled: boolean;
  suggestedBy: string;
  note: string | null;
}

export interface BoardTopic {
  id: string;
  name: string;
  description: string;
  keywords: string[];
  sensitivity: string | number;
  enabled: boolean;
  status: "quiet" | "active" | "hot";
  hits48h: number;
  lastTriggeredAt: string | null;
  recentHeadlines: { title: string; newsItemId: string; matchedAt: string }[];
  impactedTickers: string[];
  mappings: BoardMapping[];
}

const STATUS_VARIANT: Record<BoardTopic["status"], "outline" | "secondary" | "destructive"> = {
  quiet: "outline",
  active: "secondary",
  hot: "destructive",
};

export function TopicCard({ topic }: { topic: BoardTopic }) {
  const [mappings, setMappings] = useState(topic.mappings);
  const [pending, setPending] = useState<string | null>(null);

  async function toggleMapping(mapping: BoardMapping) {
    setPending(mapping.id);
    const nextEnabled = !mapping.enabled;
    setMappings((prev) => prev.map((m) => (m.id === mapping.id ? { ...m, enabled: nextEnabled } : m)));
    try {
      const res = await fetch(`/api/mappings/${mapping.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: nextEnabled }),
      });
      if (!res.ok) {
        // revert on failure
        setMappings((prev) => prev.map((m) => (m.id === mapping.id ? { ...m, enabled: mapping.enabled } : m)));
      }
    } catch {
      setMappings((prev) => prev.map((m) => (m.id === mapping.id ? { ...m, enabled: mapping.enabled } : m)));
    } finally {
      setPending(null);
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <div>
          <CardTitle className="text-base">{topic.name}</CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">{topic.description}</p>
        </div>
        <Badge variant={STATUS_VARIANT[topic.status]}>{topic.status}</Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap gap-1">
          {topic.keywords.map((k) => (
            <Badge key={k} variant="outline" className="text-[10px]">
              {k}
            </Badge>
          ))}
        </div>

        <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
          <span>sensitivity {Number(topic.sensitivity).toFixed(2)}</span>
          <span>{topic.hits48h} hit(s) / 48h</span>
          <span>last triggered: {topic.lastTriggeredAt ? relativeFromNow(topic.lastTriggeredAt) : "never"}</span>
        </div>

        {topic.impactedTickers.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {topic.impactedTickers.map((t) => (
              <Badge key={t} variant="secondary" className="text-[10px]">
                {t}
              </Badge>
            ))}
          </div>
        )}

        {topic.recentHeadlines.length > 0 && (
          <div>
            <p className="mb-1 text-xs font-medium text-muted-foreground">Recent matches</p>
            <ul className="flex flex-col gap-0.5 text-xs">
              {topic.recentHeadlines.map((h) => (
                <li key={h.newsItemId} className="truncate">
                  {h.title}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div>
          <p className="mb-1 text-xs font-medium text-muted-foreground">Mapping rows ({mappings.length})</p>
          <div className="flex flex-col gap-1">
            {mappings.length === 0 && <p className="text-xs text-muted-foreground">No mapping rows configured.</p>}
            {mappings.map((m) => (
              <div key={m.id} className="flex items-center gap-2 rounded-md border px-2 py-1 text-xs">
                <Switch checked={m.enabled} disabled={pending === m.id} onCheckedChange={() => toggleMapping(m)} />
                <span className="font-medium">
                  {m.market}/{m.sector}
                </span>
                <span className="text-muted-foreground">{m.polarity > 0 ? "+1" : "-1"}</span>
                <span className="truncate text-muted-foreground">{m.tickers.join(", ") || "(no tickers)"}</span>
                {m.suggestedBy === "llm" && (
                  <Badge variant="outline" className="ml-auto text-[10px]">
                    LLM
                  </Badge>
                )}
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
