"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

interface SuggestedMapping {
  market: "US" | "TH" | "GLOBAL";
  sector: string;
  tickers: string[];
  polarity: 1 | -1;
  note: string;
}

interface DraftMapping extends SuggestedMapping {
  accepted: boolean;
  suggestedBy: "user" | "llm";
}

export function QuickAddTopicDialog({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [keywords, setKeywords] = useState("");
  const [sensitivity, setSensitivity] = useState("0.7");
  const [mappings, setMappings] = useState<DraftMapping[]>([]);
  const [suggesting, setSuggesting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Distinct ticker counts across currently-accepted rows, per market — lets
  // the user see at a glance whether the "at least 5 US + 5 TH" coverage the
  // suggest-mappings prompt targets actually landed (and stays live as they
  // accept/reject/edit rows).
  const tickerCounts = useMemo(() => {
    const byMarket = new Map<string, Set<string>>();
    for (const m of mappings) {
      if (!m.accepted) continue;
      const set = byMarket.get(m.market) ?? new Set<string>();
      for (const t of m.tickers) set.add(t);
      byMarket.set(m.market, set);
    }
    return { US: byMarket.get("US")?.size ?? 0, TH: byMarket.get("TH")?.size ?? 0 };
  }, [mappings]);

  function reset() {
    setName("");
    setDescription("");
    setKeywords("");
    setSensitivity("0.7");
    setMappings([]);
    setError(null);
  }

  async function suggestMappings() {
    setError(null);
    setSuggesting(true);
    try {
      const res = await fetch("/api/topics/suggest-mappings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          description,
          keywords: keywords.split(",").map((k) => k.trim()).filter(Boolean),
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error ?? "failed to get suggestions");
        return;
      }
      const suggested: SuggestedMapping[] = data.mappings;
      setMappings((prev) => [
        ...prev,
        ...suggested.map((m) => ({ ...m, accepted: true, suggestedBy: "llm" as const })),
      ]);
    } catch {
      setError("failed to reach the server");
    } finally {
      setSuggesting(false);
    }
  }

  function addBlankRow() {
    setMappings((prev) => [
      ...prev,
      { market: "US", sector: "", tickers: [], polarity: 1, note: "", accepted: true, suggestedBy: "user" },
    ]);
  }

  function updateRow(index: number, patch: Partial<DraftMapping>) {
    setMappings((prev) => prev.map((m, i) => (i === index ? { ...m, ...patch } : m)));
  }

  function removeRow(index: number) {
    setMappings((prev) => prev.filter((_, i) => i !== index));
  }

  async function submit() {
    setError(null);
    setSubmitting(true);
    try {
      const res = await fetch("/api/topics/quick-add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          description,
          keywords: keywords.split(",").map((k) => k.trim()).filter(Boolean),
          sensitivity: Number(sensitivity),
          mappings: mappings
            .filter((m) => m.accepted)
            .map((m) => ({
              market: m.market,
              sector: m.sector,
              tickers: m.tickers,
              polarity: m.polarity,
              note: m.note,
              suggestedBy: m.suggestedBy,
            })),
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error ?? "failed to create topic");
        return;
      }
      reset();
      setOpen(false);
      onCreated();
    } catch {
      setError("failed to reach the server");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button>+ Add topic</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a watch topic</DialogTitle>
          <DialogDescription>Live on the next cycle. Mapping rows are optional and never auto-applied.</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <Label htmlFor="quick-add-name">Name</Label>
            <Input id="quick-add-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Shipping disruptions" />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="quick-add-description">Description</Label>
            <Textarea
              id="quick-add-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What events should count, and what does a 'positive' event mean?"
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="quick-add-keywords">Keywords (comma-separated)</Label>
            <Input id="quick-add-keywords" value={keywords} onChange={(e) => setKeywords(e.target.value)} placeholder="e.g. Suez, Red Sea, freight rates" />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="quick-add-sensitivity">Sensitivity (min confidence to trigger, 0–1)</Label>
            <Input id="quick-add-sensitivity" type="number" min={0} max={1} step={0.05} value={sensitivity} onChange={(e) => setSensitivity(e.target.value)} />
          </div>

          <div className="flex items-center justify-between">
            <Label>Mapping rows</Label>
            <div className="flex gap-2">
              <Button type="button" size="sm" variant="outline" onClick={addBlankRow}>
                + Row
              </Button>
              <Button type="button" size="sm" variant="secondary" onClick={suggestMappings} disabled={!name || !description || suggesting}>
                {suggesting ? "Asking Claude…" : "Prepopulate tickers (AI)"}
              </Button>
            </div>
          </div>

          {mappings.length === 0 && (
            <p className="text-xs text-muted-foreground">
              No mapping rows yet. &quot;Prepopulate tickers&quot; asks Claude, from the name &amp; description above,
              to propose at least 5 US and 5 Thailand (&quot;.BK&quot;) tickers to review before saving — or add rows
              manually.
            </p>
          )}

          {mappings.length > 0 && (
            <div className="flex flex-wrap gap-3 text-xs">
              <span className={tickerCounts.US >= 5 ? "text-muted-foreground" : "font-medium text-amber-600 dark:text-amber-400"}>
                US tickers: {tickerCounts.US} {tickerCounts.US < 5 && "(target ≥5)"}
              </span>
              <span className={tickerCounts.TH >= 5 ? "text-muted-foreground" : "font-medium text-amber-600 dark:text-amber-400"}>
                Thailand tickers: {tickerCounts.TH} {tickerCounts.TH < 5 && "(target ≥5)"}
              </span>
            </div>
          )}

          <div className="flex flex-col gap-2">
            {mappings.map((m, i) => (
              <div key={i} className="flex flex-col gap-1 rounded-md border p-2 text-xs">
                <div className="flex items-center gap-2">
                  <Checkbox checked={m.accepted} onCheckedChange={(v) => updateRow(i, { accepted: Boolean(v) })} />
                  {m.suggestedBy === "llm" && <span className="rounded bg-secondary px-1 py-0.5">LLM suggested</span>}
                  <Input
                    className="h-7 w-20"
                    value={m.market}
                    onChange={(e) => updateRow(i, { market: e.target.value.toUpperCase() as DraftMapping["market"] })}
                  />
                  <Input
                    className="h-7 flex-1"
                    value={m.sector}
                    placeholder="sector"
                    onChange={(e) => updateRow(i, { sector: e.target.value })}
                  />
                  <Input
                    className="h-7 w-16"
                    value={m.polarity}
                    onChange={(e) => updateRow(i, { polarity: (Number(e.target.value) as 1 | -1) || 1 })}
                  />
                  <Button type="button" size="sm" variant="ghost" onClick={() => removeRow(i)}>
                    remove
                  </Button>
                </div>
                <Input
                  className="h-7"
                  value={m.tickers.join(", ")}
                  placeholder="tickers, comma-separated"
                  onChange={(e) => updateRow(i, { tickers: e.target.value.split(",").map((t) => t.trim()).filter(Boolean) })}
                />
                {m.note && <p className="text-muted-foreground">{m.note}</p>}
              </div>
            ))}
          </div>

          {error && <p className="text-sm text-destructive dark:text-red-400">{error}</p>}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={!name || !description || submitting}>
            {submitting ? "Saving…" : "Save topic"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
