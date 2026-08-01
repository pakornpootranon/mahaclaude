"use client";

import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

interface TierSetting {
  model: string;
  reasoning: "off" | "low" | "medium" | "high";
}

interface LlmSettings {
  available_models: string[];
  tiers: Record<string, TierSetting>;
  max_items_per_cycle: number;
  monthly_budget_usd: number;
  prices_per_mtok: Record<string, { input: number; output: number }>;
  apiKey: { set: boolean; last4: string | null; status: string; lastCheckedAt: string | null };
}

const TIER_NAMES = ["triage", "analysis", "digest", "pm_estimate"] as const;
const REASONING_LEVELS = ["off", "low", "medium", "high"] as const;

// Rough per-tier token baselines for the cost-delta estimate (docs/05 §7's
// "live estimated cost-per-cycle delta") - not measured from real usage,
// just plausible magnitudes so changing model/reasoning shows a directionally
// useful number. Labeled "estimate" in the UI; not a billing guarantee.
const TIER_TOKEN_BASELINE: Record<string, { input: number; output: number; calls: number }> = {
  triage: { input: 3000, output: 400, calls: 4 },
  analysis: { input: 2500, output: 600, calls: 5 },
  digest: { input: 1500, output: 300, calls: 1 },
  pm_estimate: { input: 1200, output: 300, calls: 5 },
};
const REASONING_OUTPUT_MULTIPLIER: Record<string, number> = { off: 1, low: 1.3, medium: 1.8, high: 2.5 };

function estimateCostPerCycle(tierName: string, tier: TierSetting, prices: LlmSettings["prices_per_mtok"]): number | null {
  const price = prices[tier.model];
  const baseline = TIER_TOKEN_BASELINE[tierName];
  if (!price || !baseline) return null;
  const outputTokens = baseline.output * (REASONING_OUTPUT_MULTIPLIER[tier.reasoning] ?? 1);
  const perCall = (baseline.input / 1_000_000) * price.input + (outputTokens / 1_000_000) * price.output;
  return perCall * baseline.calls;
}

export default function LlmSettingsPage() {
  const [settings, setSettings] = useState<LlmSettings | null>(null);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [newModel, setNewModel] = useState("");
  const [newModelInput, setNewModelInput] = useState("");
  const [newModelOutput, setNewModelOutput] = useState("");

  function load() {
    fetch("/api/config/llm")
      .then((r) => r.json())
      .then(setSettings);
  }

  useEffect(load, []);

  function updateTier(tierName: string, patch: Partial<TierSetting>) {
    setSettings((prev) =>
      prev ? { ...prev, tiers: { ...prev.tiers, [tierName]: { ...prev.tiers[tierName], ...patch } } } : prev
    );
  }

  async function save() {
    if (!settings) return;
    setSaveMessage(null);
    const body: Record<string, unknown> = {
      available_models: settings.available_models,
      tiers: settings.tiers,
      max_items_per_cycle: settings.max_items_per_cycle,
      monthly_budget_usd: settings.monthly_budget_usd,
      prices_per_mtok: settings.prices_per_mtok,
    };
    if (apiKeyInput.trim()) body.apiKey = apiKeyInput.trim();

    const res = await fetch("/api/config/llm", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (res.ok) {
      setApiKeyInput("");
      setSaveMessage("Saved.");
      setSettings(data);
    } else {
      setSaveMessage(data.error ?? "failed to save");
    }
  }

  function addModel() {
    if (!settings || !newModel.trim() || !newModelInput || !newModelOutput) return;
    setSettings({
      ...settings,
      available_models: [...settings.available_models, newModel.trim()],
      prices_per_mtok: {
        ...settings.prices_per_mtok,
        [newModel.trim()]: { input: Number(newModelInput), output: Number(newModelOutput) },
      },
    });
    setNewModel("");
    setNewModelInput("");
    setNewModelOutput("");
  }

  if (!settings) return <p className="text-sm text-muted-foreground">Loading…</p>;

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">LLM</h1>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Claude API key</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <div className="flex items-center gap-2 text-sm">
            <span>
              {settings.apiKey.set ? `sk-ant-…${settings.apiKey.last4}` : "not set (falls back to ANTHROPIC_API_KEY env)"}
            </span>
            <Badge
              variant={
                settings.apiKey.status === "valid" ? "success" : settings.apiKey.status === "invalid" ? "destructive" : "secondary"
              }
            >
              {settings.apiKey.status}
            </Badge>
          </div>
          <div className="flex gap-2">
            <Input
              type="password"
              placeholder="sk-ant-…"
              value={apiKeyInput}
              onChange={(e) => setApiKeyInput(e.target.value)}
              className="max-w-xs"
            />
            <span className="self-center text-xs text-muted-foreground">Rotating takes effect on the next call, no restart.</span>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Per-tier model &amp; reasoning</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {TIER_NAMES.map((tierName) => {
            const tier = settings.tiers[tierName];
            const cost = estimateCostPerCycle(tierName, tier, settings.prices_per_mtok);
            return (
              <div key={tierName} className="flex flex-wrap items-center gap-2">
                <span className="w-28 text-sm font-medium">{tierName}</span>
                <Select value={tier.model} onValueChange={(v) => updateTier(tierName, { model: v })}>
                  <SelectTrigger className="w-56">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {settings.available_models.map((m) => (
                      <SelectItem key={m} value={m}>
                        {m}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select value={tier.reasoning} onValueChange={(v) => updateTier(tierName, { reasoning: v as TierSetting["reasoning"] })}>
                  <SelectTrigger className="w-32">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {REASONING_LEVELS.map((r) => (
                      <SelectItem key={r} value={r}>
                        {r}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <span className="text-xs text-muted-foreground">
                  {cost !== null ? `~$${cost.toFixed(3)}/cycle (estimate)` : "no price data"}
                </span>
              </div>
            );
          })}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Available models &amp; pricing (per MTok)</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {settings.available_models.map((m) => (
            <div key={m} className="flex items-center gap-2 text-sm">
              <span className="w-64 font-mono text-xs">{m}</span>
              <span className="text-xs text-muted-foreground">
                in: ${settings.prices_per_mtok[m]?.input ?? "—"} / out: ${settings.prices_per_mtok[m]?.output ?? "—"}
              </span>
            </div>
          ))}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Input className="w-56" placeholder="new model id" value={newModel} onChange={(e) => setNewModel(e.target.value)} />
            <Input className="w-24" placeholder="$/Mtok in" value={newModelInput} onChange={(e) => setNewModelInput(e.target.value)} />
            <Input className="w-24" placeholder="$/Mtok out" value={newModelOutput} onChange={(e) => setNewModelOutput(e.target.value)} />
            <Button size="sm" variant="outline" onClick={addModel}>
              + Add model
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Budget &amp; item cap</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <div className="flex flex-col gap-1">
            <Label className="text-xs">Monthly budget (USD)</Label>
            <Input
              type="number"
              min={0}
              step={0.5}
              className="w-40"
              value={settings.monthly_budget_usd}
              onChange={(e) => setSettings({ ...settings, monthly_budget_usd: Number(e.target.value) })}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label className="text-xs">Max items triaged per cycle</Label>
            <Input
              type="number"
              min={1}
              className="w-40"
              value={settings.max_items_per_cycle}
              onChange={(e) => setSettings({ ...settings, max_items_per_cycle: Number(e.target.value) })}
            />
          </div>
          <p className="text-xs text-muted-foreground">Month-to-date spend vs this cap is shown on the health strip.</p>
        </CardContent>
      </Card>

      <div className="flex items-center gap-3">
        <Button onClick={save}>Save</Button>
        {saveMessage && <span className="text-sm text-muted-foreground">{saveMessage}</span>}
      </div>
    </div>
  );
}
