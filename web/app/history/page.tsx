"use client";

import { useCallback, useEffect, useState } from "react";

import { ActionBadge } from "@/components/action-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { formatDateBangkok } from "@/lib/time";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;
const ALL = "__all__";

function pct(value: unknown): string {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return "—";
  return `${(n * 100).toFixed(0)}%`;
}

function fmtNum(value: unknown, digits = 2): string {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  return Number.isNaN(n) ? "—" : n.toFixed(digits);
}

function HitIndicator({ hit }: { hit: boolean | null }) {
  if (hit === null) return <span className="text-muted-foreground">—</span>;
  return hit ? (
    <span className="text-success dark:text-emerald-400">✓</span>
  ) : (
    <span className="text-destructive dark:text-red-400">✗</span>
  );
}

interface RecommendationOutcome {
  ticker: string;
  entryPrice: string | number | null;
  ret1d: string | number | null;
  ret3d: string | number | null;
  ret7d: string | number | null;
  hit1d: boolean | null;
  hit3d: boolean | null;
  hit7d: boolean | null;
  status: string;
}

interface RecommendationHistoryItem {
  id: string;
  action: string;
  market: string;
  sector: string;
  tickers: string[];
  confidence: string | number;
  createdAt: string;
  topic: { id: string; name: string } | null;
  outcome: RecommendationOutcome | null;
}

interface HitRateRow {
  topicId: string | null;
  topicName: string;
  action: string;
  recommendationCount: number;
  avgConfidence: unknown;
  hitRate1d: unknown;
  hitRate3d: unknown;
  hitRate7d: unknown;
}

function RecommendationsTab() {
  const [items, setItems] = useState<RecommendationHistoryItem[]>([]);
  const [hitRates, setHitRates] = useState<HitRateRow[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState(ALL);
  const [market, setMarket] = useState(ALL);

  const buildParams = useCallback(
    (cursorValue: string | null) => {
      const params = new URLSearchParams();
      params.set("limit", String(PAGE_SIZE));
      if (action !== ALL) params.set("action", action);
      if (market !== ALL) params.set("market", market);
      if (cursorValue) params.set("cursor", cursorValue);
      return params;
    },
    [action, market]
  );

  const load = useCallback(
    async (reset: boolean) => {
      setLoading(true);
      try {
        const params = buildParams(reset ? null : cursor);
        const res = await fetch(`/api/history?${params.toString()}`, { cache: "no-store" });
        const data = await res.json();
        setItems((prev) => (reset ? data.items : [...prev, ...data.items]));
        setCursor(data.nextCursor);
        setHasMore(Boolean(data.nextCursor));
        if (reset) setHitRates(data.hitRates);
      } finally {
        setLoading(false);
      }
    },
    [buildParams, cursor]
  );

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    load(true);
  }, [action, market]);

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Hit rates by topic &amp; action</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          {hitRates.length === 0 ? (
            <p className="text-sm text-muted-foreground">No recommendations with outcome data yet.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-1 pr-2">Topic</th>
                  <th className="py-1 pr-2">Action</th>
                  <th className="py-1 pr-2">Count</th>
                  <th className="py-1 pr-2">Avg confidence</th>
                  <th className="py-1 pr-2">Hit rate T+1</th>
                  <th className="py-1 pr-2">Hit rate T+3</th>
                  <th className="py-1 pr-2">Hit rate T+7</th>
                </tr>
              </thead>
              <tbody>
                {hitRates.map((h, i) => (
                  <tr key={i} className="border-b last:border-0">
                    <td className="py-1.5 pr-2">{h.topicName}</td>
                    <td className="py-1.5 pr-2">
                      <ActionBadge action={h.action} />
                    </td>
                    <td className="py-1.5 pr-2">{h.recommendationCount}</td>
                    <td className="py-1.5 pr-2">{fmtNum(h.avgConfidence)}</td>
                    <td className="py-1.5 pr-2">{pct(h.hitRate1d)}</td>
                    <td className="py-1.5 pr-2">{pct(h.hitRate3d)}</td>
                    <td className="py-1.5 pr-2">{pct(h.hitRate7d)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      <div className="flex gap-3 rounded-lg border p-3">
        <div className="flex flex-col gap-1">
          <Label className="text-xs" htmlFor="history-rec-action">Action</Label>
          <Select value={action} onValueChange={setAction}>
            <SelectTrigger className="w-40" id="history-rec-action">
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
          <Label className="text-xs" htmlFor="history-rec-market">Market</Label>
          <Select value={market} onValueChange={setMarket}>
            <SelectTrigger className="w-40" id="history-rec-market">
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
      </div>

      <Card>
        <CardContent className="overflow-x-auto p-4">
          {items.length === 0 && !loading ? (
            <p className="text-sm text-muted-foreground">No recommendations match these filters yet.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-1 pr-2">Date</th>
                  <th className="py-1 pr-2">Action</th>
                  <th className="py-1 pr-2">Ticker</th>
                  <th className="py-1 pr-2">Entry</th>
                  <th className="py-1 pr-2">T+1</th>
                  <th className="py-1 pr-2">T+3</th>
                  <th className="py-1 pr-2">T+7</th>
                  <th className="py-1 pr-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {items.map((r) => (
                  <tr key={r.id} className="border-b last:border-0">
                    <td className="py-1.5 pr-2">{formatDateBangkok(r.createdAt)}</td>
                    <td className="py-1.5 pr-2">
                      <ActionBadge action={r.action} />
                    </td>
                    <td className="py-1.5 pr-2">{r.outcome?.ticker ?? r.tickers[0] ?? "(sector-only)"}</td>
                    <td className="py-1.5 pr-2">{fmtNum(r.outcome?.entryPrice)}</td>
                    <td className="py-1.5 pr-2">
                      {fmtNum(r.outcome?.ret1d)}% <HitIndicator hit={r.outcome?.hit1d ?? null} />
                    </td>
                    <td className="py-1.5 pr-2">
                      {fmtNum(r.outcome?.ret3d)}% <HitIndicator hit={r.outcome?.hit3d ?? null} />
                    </td>
                    <td className="py-1.5 pr-2">
                      {fmtNum(r.outcome?.ret7d)}% <HitIndicator hit={r.outcome?.hit7d ?? null} />
                    </td>
                    <td className="py-1.5 pr-2">
                      <Badge variant="outline">{r.outcome?.status ?? "pending"}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {hasMore && (
        <Button variant="outline" onClick={() => load(false)} disabled={loading}>
          {loading ? "Loading…" : "Load more"}
        </Button>
      )}
    </div>
  );
}

interface PmOutcome {
  price1d: string | number | null;
  price3d: string | number | null;
  price7d: string | number | null;
  movedTowardEstimate7d: boolean | null;
  resolved: boolean;
  resolution: string | null;
  estimateCorrect: boolean | null;
  status: string;
}

interface PmHistoryItem {
  id: string;
  discovery: string;
  side: string;
  marketPrice: string | number;
  estProbability: string | number;
  edgePoints: string | number;
  createdAt: string;
  market: { question: string; slug: string; category: string | null; url: string };
  outcome: PmOutcome | null;
}

interface CalibrationRow {
  edgeBucket: number;
  opportunityCount: number;
  shareMovedTowardEstimate7d: unknown;
  resolutionAccuracy: unknown;
}

function PolymarketTab() {
  const [items, setItems] = useState<PmHistoryItem[]>([]);
  const [calibration, setCalibration] = useState<CalibrationRow[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [discovery, setDiscovery] = useState(ALL);

  const buildParams = useCallback(
    (cursorValue: string | null) => {
      const params = new URLSearchParams();
      params.set("limit", String(PAGE_SIZE));
      if (discovery !== ALL) params.set("discovery", discovery);
      if (cursorValue) params.set("cursor", cursorValue);
      return params;
    },
    [discovery]
  );

  const load = useCallback(
    async (reset: boolean) => {
      setLoading(true);
      try {
        const params = buildParams(reset ? null : cursor);
        const res = await fetch(`/api/history/polymarket?${params.toString()}`, { cache: "no-store" });
        const data = await res.json();
        setItems((prev) => (reset ? data.items : [...prev, ...data.items]));
        setCursor(data.nextCursor);
        setHasMore(Boolean(data.nextCursor));
        if (reset) setCalibration(data.calibration);
      } finally {
        setLoading(false);
      }
    },
    [buildParams, cursor]
  );

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    load(true);
  }, [discovery]);

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Calibration by edge bucket</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          {calibration.length === 0 ? (
            <p className="text-sm text-muted-foreground">No Polymarket opportunities with outcome data yet.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-1 pr-2">Edge bucket</th>
                  <th className="py-1 pr-2">Count</th>
                  <th className="py-1 pr-2">Price moved toward estimate (7d)</th>
                  <th className="py-1 pr-2">Resolution accuracy</th>
                </tr>
              </thead>
              <tbody>
                {calibration.map((c) => (
                  <tr key={c.edgeBucket} className="border-b last:border-0">
                    <td className="py-1.5 pr-2">bucket {c.edgeBucket}</td>
                    <td className="py-1.5 pr-2">{c.opportunityCount}</td>
                    <td className="py-1.5 pr-2">{pct(c.shareMovedTowardEstimate7d)}</td>
                    <td className="py-1.5 pr-2">{pct(c.resolutionAccuracy)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      <div className="flex gap-3 rounded-lg border p-3">
        <div className="flex flex-col gap-1">
          <Label className="text-xs" htmlFor="history-pm-discovery">Discovery</Label>
          <Select value={discovery} onValueChange={setDiscovery}>
            <SelectTrigger className="w-40" id="history-pm-discovery">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All</SelectItem>
              <SelectItem value="news">News-driven</SelectItem>
              <SelectItem value="scan">Top-volume scan</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <Card>
        <CardContent className="overflow-x-auto p-4">
          {items.length === 0 && !loading ? (
            <p className="text-sm text-muted-foreground">No Polymarket opportunities match these filters yet.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-1 pr-2">Date</th>
                  <th className="py-1 pr-2">Market</th>
                  <th className="py-1 pr-2">Side</th>
                  <th className="py-1 pr-2">Price → est</th>
                  <th className="py-1 pr-2">T+7 price</th>
                  <th className="py-1 pr-2">Moved toward est.</th>
                  <th className="py-1 pr-2">Resolution</th>
                </tr>
              </thead>
              <tbody>
                {items.map((o) => (
                  <tr key={o.id} className="border-b last:border-0">
                    <td className="py-1.5 pr-2">{formatDateBangkok(o.createdAt)}</td>
                    <td className="py-1.5 pr-2">
                      <a href={o.market.url} target="_blank" rel="noreferrer" className="hover:underline">
                        {o.market.question}
                      </a>
                    </td>
                    <td className="py-1.5 pr-2">
                      <Badge variant={o.side === "YES" ? "success" : "destructive"}>{o.side}</Badge>
                    </td>
                    <td className="py-1.5 pr-2">
                      {fmtNum(o.marketPrice)} → {fmtNum(o.estProbability)}
                    </td>
                    <td className="py-1.5 pr-2">{fmtNum(o.outcome?.price7d)}</td>
                    <td className="py-1.5 pr-2">
                      <HitIndicator hit={o.outcome?.movedTowardEstimate7d ?? null} />
                    </td>
                    <td className="py-1.5 pr-2">
                      {o.outcome?.resolved ? (
                        <Badge variant={o.outcome.estimateCorrect ? "success" : "destructive"}>{o.outcome.resolution}</Badge>
                      ) : (
                        <span className="text-muted-foreground">unresolved</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {hasMore && (
        <Button variant="outline" onClick={() => load(false)} disabled={loading}>
          {loading ? "Loading…" : "Load more"}
        </Button>
      )}
    </div>
  );
}

export default function HistoryPage() {
  const [tab, setTab] = useState<"recommendations" | "polymarket">("recommendations");

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">History &amp; outcomes</h1>

      <div className="flex gap-1 border-b">
        <button
          className={cn(
            "px-3 py-2 text-sm font-medium",
            tab === "recommendations" ? "border-b-2 border-primary text-foreground" : "text-muted-foreground"
          )}
          onClick={() => setTab("recommendations")}
        >
          Recommendations
        </button>
        <button
          className={cn(
            "px-3 py-2 text-sm font-medium",
            tab === "polymarket" ? "border-b-2 border-primary text-foreground" : "text-muted-foreground"
          )}
          onClick={() => setTab("polymarket")}
        >
          Polymarket
        </button>
      </div>

      {tab === "recommendations" ? <RecommendationsTab /> : <PolymarketTab />}
    </div>
  );
}
