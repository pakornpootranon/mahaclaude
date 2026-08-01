"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface RulesSettings {
  global_confidence_floor: number;
  global_magnitude_floor: number;
  watch_floor: number;
  unconfigured_magnitude_floor: number;
  dedup_window_hours: number;
  max_recommendations_per_cycle: number;
  quiet_tickers: string[];
  sector_scope: { allowlist: string[]; blocklist: string[] };
}

interface PreviewResult {
  cycleId: string | null;
  candidateCount: number;
  byAction: { BUY: number; SELL: number; WATCH: number };
}

function Slider({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div className="flex flex-col gap-1">
      <Label className="text-xs">
        {label}: {value.toFixed(2)}
      </Label>
      <input type="range" min={0} max={1} step={0.05} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </div>
  );
}

export default function RulesSettingsPage() {
  const [rules, setRules] = useState<RulesSettings | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    fetch("/api/config/rules")
      .then((r) => r.json())
      .then(setRules);
  }, []);

  const fetchPreview = useCallback(async (draft: RulesSettings) => {
    setPreviewLoading(true);
    try {
      const res = await fetch("/api/config/rules/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft),
      });
      if (res.ok) setPreview(await res.json());
    } finally {
      setPreviewLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!rules) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => fetchPreview(rules), 400);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rules]);

  function update(patch: Partial<RulesSettings>) {
    setRules((prev) => (prev ? { ...prev, ...patch } : prev));
  }

  async function save() {
    if (!rules) return;
    setSaveMessage(null);
    const res = await fetch("/api/config/rules", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(rules),
    });
    const data = await res.json();
    setSaveMessage(res.ok ? "Saved." : data.error ?? "failed to save");
  }

  if (!rules) return <p className="text-sm text-muted-foreground">Loading…</p>;

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Rules</h1>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Thresholds</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Slider
            label="Global confidence floor"
            value={rules.global_confidence_floor}
            onChange={(v) => update({ global_confidence_floor: v })}
          />
          <Slider
            label="Global magnitude floor"
            value={rules.global_magnitude_floor}
            onChange={(v) => update({ global_magnitude_floor: v })}
          />
          <Slider label="Watch floor (below this, BUY/SELL downgrades to WATCH)" value={rules.watch_floor} onChange={(v) => update({ watch_floor: v })} />
          <Slider
            label="Unconfigured magnitude floor (unconfigured-but-significant WATCH items)"
            value={rules.unconfigured_magnitude_floor}
            onChange={(v) => update({ unconfigured_magnitude_floor: v })}
          />
          <div className="flex flex-col gap-1">
            <Label className="text-xs" htmlFor="rules-dedup-window">Dedup window (hours, 1-336)</Label>
            <Input
              id="rules-dedup-window"
              type="number"
              min={1}
              max={336}
              value={rules.dedup_window_hours}
              onChange={(e) => update({ dedup_window_hours: Number(e.target.value) })}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label className="text-xs" htmlFor="rules-max-recs-per-cycle">Max recommendations per cycle (1-50)</Label>
            <Input
              id="rules-max-recs-per-cycle"
              type="number"
              min={1}
              max={50}
              value={rules.max_recommendations_per_cycle}
              onChange={(e) => update({ max_recommendations_per_cycle: Number(e.target.value) })}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label className="text-xs" htmlFor="rules-quiet-tickers">Quiet tickers (never recommend, comma-separated)</Label>
            <Input
              id="rules-quiet-tickers"
              value={rules.quiet_tickers.join(", ")}
              onChange={(e) => update({ quiet_tickers: e.target.value.split(",").map((t) => t.trim().toUpperCase()).filter(Boolean) })}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label className="text-xs" htmlFor="rules-sector-allowlist">Sector allowlist (empty = all sectors allowed)</Label>
            <Input
              id="rules-sector-allowlist"
              value={rules.sector_scope.allowlist.join(", ")}
              onChange={(e) =>
                update({
                  sector_scope: {
                    ...rules.sector_scope,
                    allowlist: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                  },
                })
              }
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label className="text-xs" htmlFor="rules-sector-blocklist">Sector blocklist (always wins over allowlist)</Label>
            <Input
              id="rules-sector-blocklist"
              value={rules.sector_scope.blocklist.join(", ")}
              onChange={(e) =>
                update({
                  sector_scope: {
                    ...rules.sector_scope,
                    blocklist: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                  },
                })
              }
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">What would have triggered last cycle</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          {previewLoading && <span className="text-xs text-muted-foreground">recalculating…</span>}
          {preview && !preview.cycleId && <span className="text-sm text-muted-foreground">No cycles have run yet.</span>}
          {preview?.cycleId && (
            <>
              <Badge variant="secondary">{preview.candidateCount} candidate(s)</Badge>
              <span className="text-xs text-muted-foreground">
                BUY {preview.byAction.BUY} / SELL {preview.byAction.SELL} / WATCH {preview.byAction.WATCH}
              </span>
              <span className="text-xs text-muted-foreground">
                (before dedup-window and per-cycle-cap ranking - see note below)
              </span>
            </>
          )}
        </CardContent>
      </Card>
      <p className="text-xs text-muted-foreground">
        This preview approximates rules.py&apos;s gate conditions (topic/mapping enabled, sector scope, confidence and
        magnitude floors) against the most recent cycle&apos;s analyses. It does not apply the dedup window or the
        per-cycle cap/ranking, so the real count on a live cycle can be lower than shown here.
      </p>

      <div className="flex items-center gap-3">
        <Button onClick={save}>Save</Button>
        {saveMessage && <span className="text-sm text-muted-foreground">{saveMessage}</span>}
      </div>
    </div>
  );
}
