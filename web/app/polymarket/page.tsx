"use client";

import { useCallback, useEffect, useState } from "react";

import { PmOpportunityCard, type PmOpportunityListItem } from "@/components/polymarket/opportunity-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const PAGE_SIZE = 20;
const ALL = "__all__";

export default function PolymarketOpportunitiesPage() {
  const [items, setItems] = useState<PmOpportunityListItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);

  const [mode, setMode] = useState(ALL);
  const [category, setCategory] = useState("");
  const [minEdge, setMinEdge] = useState("");
  const [minLiquidity, setMinLiquidity] = useState("");

  const buildParams = useCallback(
    (cursorValue: string | null) => {
      const params = new URLSearchParams();
      params.set("limit", String(PAGE_SIZE));
      if (mode !== ALL) params.set("mode", mode);
      if (category) params.set("category", category);
      if (minEdge) params.set("edge", minEdge);
      if (minLiquidity) params.set("minLiquidity", minLiquidity);
      if (cursorValue) params.set("cursor", cursorValue);
      return params;
    },
    [mode, category, minEdge, minLiquidity]
  );

  const load = useCallback(
    async (reset: boolean) => {
      setLoading(true);
      try {
        const params = buildParams(reset ? null : cursor);
        const res = await fetch(`/api/polymarket/opportunities?${params.toString()}`, { cache: "no-store" });
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

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    load(true);
  }, [mode, category, minEdge, minLiquidity]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Polymarket opportunities</h1>
      </div>

      <div className="grid grid-cols-2 gap-3 rounded-lg border p-3 sm:grid-cols-4">
        <div className="flex flex-col gap-1">
          <Label className="text-xs" htmlFor="polymarket-discovery">Discovery</Label>
          <Select value={mode} onValueChange={setMode}>
            <SelectTrigger id="polymarket-discovery">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All</SelectItem>
              <SelectItem value="news">News-driven</SelectItem>
              <SelectItem value="scan">Top-volume scan</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1">
          <Label className="text-xs" htmlFor="polymarket-category">Category</Label>
          <Input id="polymarket-category" value={category} onChange={(e) => setCategory(e.target.value)} placeholder="e.g. Economy" />
        </div>

        <div className="flex flex-col gap-1">
          <Label className="text-xs" htmlFor="polymarket-min-edge">Min edge (points)</Label>
          <Input id="polymarket-min-edge" type="number" min={0} value={minEdge} onChange={(e) => setMinEdge(e.target.value)} placeholder="0" />
        </div>

        <div className="flex flex-col gap-1">
          <Label className="text-xs" htmlFor="polymarket-min-liquidity">Min liquidity (USD)</Label>
          <Input id="polymarket-min-liquidity" type="number" min={0} value={minLiquidity} onChange={(e) => setMinLiquidity(e.target.value)} placeholder="0" />
        </div>
      </div>

      {items.length === 0 && !loading && (
        <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
          No Polymarket opportunities match these filters yet. Run a cycle or widen the filters.
        </div>
      )}

      <div className="flex flex-col gap-3">
        {items.map((opp) => (
          <PmOpportunityCard key={opp.id} opp={opp} />
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
