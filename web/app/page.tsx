"use client";

import { useCallback, useEffect, useState } from "react";

import { RecommendationCard, type RecommendationListItem } from "@/components/recommendation-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const PAGE_SIZE = 20;

interface TopicOption {
  id: string;
  name: string;
}

const ALL = "__all__";

export default function ActionFeedPage() {
  const [items, setItems] = useState<RecommendationListItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [topics, setTopics] = useState<TopicOption[]>([]);

  const [market, setMarket] = useState(ALL);
  const [action, setAction] = useState(ALL);
  const [topic, setTopic] = useState(ALL);
  const [minConfidence, setMinConfidence] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const buildParams = useCallback(
    (cursorValue: string | null) => {
      const params = new URLSearchParams();
      params.set("limit", String(PAGE_SIZE));
      if (market !== ALL) params.set("market", market);
      if (action !== ALL) params.set("action", action);
      if (topic !== ALL) params.set("topic", topic);
      if (minConfidence) params.set("minConfidence", minConfidence);
      if (from) params.set("from", new Date(from).toISOString());
      if (to) params.set("to", new Date(to).toISOString());
      if (cursorValue) params.set("cursor", cursorValue);
      return params;
    },
    [market, action, topic, minConfidence, from, to]
  );

  const load = useCallback(
    async (reset: boolean) => {
      setLoading(true);
      try {
        const params = buildParams(reset ? null : cursor);
        const res = await fetch(`/api/recommendations?${params.toString()}`, { cache: "no-store" });
        const data = await res.json();
        setItems((prev) => (reset ? data.items : [...prev, ...data.items]));
        setCursor(data.nextCursor);
        setHasMore(Boolean(data.nextCursor));
      } finally {
        setLoading(false);
      }
    },
    [buildParams, cursor]
  );

  useEffect(() => {
    fetch("/api/topics/board")
      .then((r) => r.json())
      .then((data) => setTopics(data.items.map((t: { id: string; name: string }) => ({ id: t.id, name: t.name }))));
  }, []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    load(true);
  }, [market, action, topic, minConfidence, from, to]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Action feed</h1>
      </div>

      <div className="grid grid-cols-2 gap-3 rounded-lg border p-3 sm:grid-cols-3 md:grid-cols-6">
        <div className="flex flex-col gap-1">
          <Label className="text-xs" htmlFor="feed-market">Market</Label>
          <Select value={market} onValueChange={setMarket}>
            <SelectTrigger id="feed-market">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All</SelectItem>
              <SelectItem value="US">US</SelectItem>
              <SelectItem value="TH">TH</SelectItem>
              <SelectItem value="GLOBAL">GLOBAL</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1">
          <Label className="text-xs" htmlFor="feed-action">Action</Label>
          <Select value={action} onValueChange={setAction}>
            <SelectTrigger id="feed-action">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All</SelectItem>
              <SelectItem value="BUY">BUY</SelectItem>
              <SelectItem value="SELL">SELL</SelectItem>
              <SelectItem value="WATCH">WATCH</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1">
          <Label className="text-xs" htmlFor="feed-topic">Topic</Label>
          <Select value={topic} onValueChange={setTopic}>
            <SelectTrigger id="feed-topic">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All</SelectItem>
              {topics.map((t) => (
                <SelectItem key={t.id} value={t.id}>
                  {t.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1">
          <Label className="text-xs" htmlFor="feed-min-confidence">Min confidence</Label>
          <Input
            id="feed-min-confidence"
            type="number"
            min={0}
            max={1}
            step={0.05}
            value={minConfidence}
            onChange={(e) => setMinConfidence(e.target.value)}
            placeholder="0.0–1.0"
          />
        </div>

        <div className="flex flex-col gap-1">
          <Label className="text-xs" htmlFor="feed-from">From</Label>
          <Input id="feed-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </div>

        <div className="flex flex-col gap-1">
          <Label className="text-xs" htmlFor="feed-to">To</Label>
          <Input id="feed-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </div>
      </div>

      {items.length === 0 && !loading && (
        <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
          No recommendations match these filters yet. Run a cycle or widen the filters.
        </div>
      )}

      <div className="flex flex-col gap-3">
        {items.map((rec) => (
          <RecommendationCard key={rec.id} rec={rec} />
        ))}
      </div>

      {hasMore && (
        <Button variant="outline" onClick={() => load(false)} disabled={loading}>
          {loading ? "Loading…" : "Load more"}
        </Button>
      )}
    </div>
  );
}
