"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

interface PolymarketSettings {
  enabled: boolean;
  scan_top_n: number;
  reestimate_hours: number;
  min_edge_points: number;
  min_confidence: number;
  min_liquidity_usd: number;
  min_days_to_end: number;
  price_floor: number;
  price_ceiling: number;
  dedup_window_hours: number;
  max_opportunities_per_cycle: number;
  categories: string[];
}

function Field({
  label,
  description,
  children,
}: {
  label: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <Label className="text-xs">{label}</Label>
      <p className="text-xs text-muted-foreground">{description}</p>
      {children}
    </div>
  );
}

export default function PolymarketSettingsPage() {
  const [settings, setSettings] = useState<PolymarketSettings | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/config/polymarket")
      .then((r) => r.json())
      .then(setSettings);
  }, []);

  async function save() {
    if (!settings) return;
    setSaveMessage(null);
    const res = await fetch("/api/config/polymarket", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    });
    const data = await res.json();
    setSaveMessage(res.ok ? "Saved." : data.error ?? "failed to save");
  }

  if (!settings) return <p className="text-sm text-muted-foreground">Loading…</p>;

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Polymarket</h1>

      <Card>
        <CardContent className="flex items-center gap-3 p-4">
          <Switch checked={settings.enabled} onCheckedChange={(v) => setSettings({ ...settings, enabled: v })} />
          <div>
            <p className="text-sm font-medium">Polymarket opportunities module</p>
            <p className="text-xs text-muted-foreground">
              When off, PM_SCANNING is skipped entirely for every cycle - no calls, no cost.
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Discovery</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Scan top N markets" description="How many top-volume active markets to sweep each cycle.">
            <Input
              type="number"
              min={1}
              value={settings.scan_top_n}
              onChange={(e) => setSettings({ ...settings, scan_top_n: Number(e.target.value) })}
            />
          </Field>
          <Field label="Re-estimate hours" description="Don't re-estimate a market's probability more often than this.">
            <Input
              type="number"
              min={1}
              value={settings.reestimate_hours}
              onChange={(e) => setSettings({ ...settings, reestimate_hours: Number(e.target.value) })}
            />
          </Field>
          <Field label="Min days to end" description="Skip markets resolving sooner than this - avoids near-certain markets.">
            <Input
              type="number"
              min={0}
              value={settings.min_days_to_end}
              onChange={(e) => setSettings({ ...settings, min_days_to_end: Number(e.target.value) })}
            />
          </Field>
          <Field label="Categories (empty = all)" description="Restrict the top-volume scan to these Polymarket categories.">
            <Input
              value={settings.categories.join(", ")}
              onChange={(e) => setSettings({ ...settings, categories: e.target.value.split(",").map((c) => c.trim()).filter(Boolean) })}
            />
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Flagging thresholds</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Minimum edge (points)" description="Minimum |estimate - market price| x 100 before a market is flagged.">
            <Input
              type="number"
              min={0}
              value={settings.min_edge_points}
              onChange={(e) => setSettings({ ...settings, min_edge_points: Number(e.target.value) })}
            />
          </Field>
          <Field label="Minimum confidence" description="Minimum LLM confidence (0-1) in its own probability estimate.">
            <Input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={settings.min_confidence}
              onChange={(e) => setSettings({ ...settings, min_confidence: Number(e.target.value) })}
            />
          </Field>
          <Field label="Minimum liquidity (USD)" description="Markets below this liquidity are never flagged.">
            <Input
              type="number"
              min={0}
              value={settings.min_liquidity_usd}
              onChange={(e) => setSettings({ ...settings, min_liquidity_usd: Number(e.target.value) })}
            />
          </Field>
          <Field label="Max opportunities per cycle" description="Cap on flagged markets per cycle, highest edge first.">
            <Input
              type="number"
              min={1}
              max={50}
              value={settings.max_opportunities_per_cycle}
              onChange={(e) => setSettings({ ...settings, max_opportunities_per_cycle: Number(e.target.value) })}
            />
          </Field>
          <Field label="Price floor" description="Ignore markets with YES price below this (too close to 0).">
            <Input
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={settings.price_floor}
              onChange={(e) => setSettings({ ...settings, price_floor: Number(e.target.value) })}
            />
          </Field>
          <Field label="Price ceiling" description="Ignore markets with YES price above this (too close to 1).">
            <Input
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={settings.price_ceiling}
              onChange={(e) => setSettings({ ...settings, price_ceiling: Number(e.target.value) })}
            />
          </Field>
          <Field label="Dedup window (hours)" description="Same market+side can't re-flag inside this window.">
            <Input
              type="number"
              min={1}
              value={settings.dedup_window_hours}
              onChange={(e) => setSettings({ ...settings, dedup_window_hours: Number(e.target.value) })}
            />
          </Field>
        </CardContent>
      </Card>

      <div className="flex items-center gap-3">
        <Button onClick={save}>Save</Button>
        {saveMessage && <span className="text-sm text-muted-foreground">{saveMessage}</span>}
      </div>
    </div>
  );
}
