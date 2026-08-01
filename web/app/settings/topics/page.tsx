"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

interface MappingRow {
  id: string;
  market: string;
  sector: string;
  tickers: string[];
  polarity: number;
  enabled: boolean;
  suggestedBy: string;
  note: string | null;
}

interface TopicRow {
  id: string;
  name: string;
  description: string;
  keywords: string[];
  sensitivity: string | number;
  enabled: boolean;
  mappings: MappingRow[];
}

function MappingEditor({ topicId, mapping, onChanged }: { topicId: string; mapping: MappingRow; onChanged: () => void }) {
  const [tickersText, setTickersText] = useState(mapping.tickers.join(", "));

  async function patch(data: Record<string, unknown>) {
    await fetch(`/api/mappings/${mapping.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    onChanged();
  }

  async function remove() {
    if (!confirm(`Remove mapping ${mapping.market}/${mapping.sector}?`)) return;
    await fetch(`/api/mappings/${mapping.id}`, { method: "DELETE" });
    onChanged();
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border p-2 text-xs">
      <Switch checked={mapping.enabled} onCheckedChange={(v) => patch({ enabled: v })} />
      <span className="font-medium">
        {mapping.market}/{mapping.sector}
      </span>
      <span className="text-muted-foreground">{mapping.polarity > 0 ? "+1" : "-1"}</span>
      <Input
        className="h-7 w-56"
        value={tickersText}
        onChange={(e) => setTickersText(e.target.value)}
        onBlur={() => patch({ tickers: tickersText.split(",").map((t) => t.trim().toUpperCase()).filter(Boolean) })}
      />
      {mapping.suggestedBy === "llm" && (
        <Badge variant="outline" className="text-[10px]">
          LLM
        </Badge>
      )}
      <Button size="sm" variant="ghost" className="ml-auto" onClick={remove}>
        Remove
      </Button>
    </div>
  );
}

function AddMappingRow({ topicId, onAdded }: { topicId: string; onAdded: () => void }) {
  const [market, setMarket] = useState("US");
  const [sector, setSector] = useState("");
  const [tickers, setTickers] = useState("");
  const [polarity, setPolarity] = useState("1");
  const [error, setError] = useState<string | null>(null);

  async function add() {
    setError(null);
    const res = await fetch(`/api/config/topics/${topicId}/mappings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        market,
        sector,
        tickers: tickers.split(",").map((t) => t.trim()).filter(Boolean),
        polarity: Number(polarity),
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      setError(data.error ?? "failed to add mapping");
      return;
    }
    setSector("");
    setTickers("");
    onAdded();
  }

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <Input className="h-7 w-16" value={market} onChange={(e) => setMarket(e.target.value.toUpperCase())} />
      <Input className="h-7 w-32" placeholder="sector" value={sector} onChange={(e) => setSector(e.target.value)} />
      <Input className="h-7 w-56" placeholder="tickers, comma-separated" value={tickers} onChange={(e) => setTickers(e.target.value)} />
      <Input className="h-7 w-14" value={polarity} onChange={(e) => setPolarity(e.target.value)} />
      <Button size="sm" variant="outline" onClick={add} disabled={!sector}>
        + Row
      </Button>
      {error && <span className="text-destructive">{error}</span>}
    </div>
  );
}

function TopicDrawer({ topic, onChanged, onDeleted }: { topic: TopicRow; onChanged: () => void; onDeleted: () => void }) {
  const [description, setDescription] = useState(topic.description);
  const [keywordsText, setKeywordsText] = useState(topic.keywords.join(", "));
  const [sensitivity, setSensitivity] = useState(String(topic.sensitivity));

  async function patch(data: Record<string, unknown>) {
    await fetch(`/api/config/topics/${topic.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    onChanged();
  }

  async function remove() {
    if (!confirm(`Delete topic "${topic.name}"? This can't be undone (mappings are removed too).`)) return;
    await fetch(`/api/config/topics/${topic.id}`, { method: "DELETE" });
    onDeleted();
  }

  return (
    <CardContent className="flex flex-col gap-3 border-t pt-3">
      <div className="flex flex-col gap-1">
        <Label className="text-xs">Description</Label>
        <Textarea value={description} onChange={(e) => setDescription(e.target.value)} onBlur={() => patch({ description })} />
      </div>
      <div className="flex flex-col gap-1">
        <Label className="text-xs">Keywords (comma-separated)</Label>
        <Input
          value={keywordsText}
          onChange={(e) => setKeywordsText(e.target.value)}
          onBlur={() => patch({ keywords: keywordsText.split(",").map((k) => k.trim()).filter(Boolean) })}
        />
      </div>
      <div className="flex flex-col gap-1">
        <Label className="text-xs">Sensitivity: {Number(sensitivity).toFixed(2)}</Label>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={sensitivity}
          onChange={(e) => setSensitivity(e.target.value)}
          onMouseUp={() => patch({ sensitivity: Number(sensitivity) })}
          onTouchEnd={() => patch({ sensitivity: Number(sensitivity) })}
        />
      </div>

      <div>
        <Label className="text-xs">Mapping rows</Label>
        <div className="mt-1 flex flex-col gap-1">
          {topic.mappings.map((m) => (
            <MappingEditor key={m.id} topicId={topic.id} mapping={m} onChanged={onChanged} />
          ))}
          <AddMappingRow topicId={topic.id} onAdded={onChanged} />
        </div>
      </div>

      <div className="flex justify-end">
        <Button size="sm" variant="ghost" className="text-destructive" onClick={remove}>
          Delete topic
        </Button>
      </div>
    </CardContent>
  );
}

export default function TopicsSettingsPage() {
  const [topics, setTopics] = useState<TopicRow[] | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");

  const load = useCallback(async () => {
    const res = await fetch("/api/config/topics", { cache: "no-store" });
    const data = await res.json();
    setTopics(data.items);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function toggleEnabled(topic: TopicRow) {
    setTopics((prev) => prev?.map((t) => (t.id === topic.id ? { ...t, enabled: !t.enabled } : t)) ?? null);
    await fetch(`/api/config/topics/${topic.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !topic.enabled }),
    });
  }

  async function createTopic() {
    const res = await fetch("/api/config/topics", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName, description: newDescription }),
    });
    if (res.ok) {
      setNewName("");
      setNewDescription("");
      load();
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Topics &amp; Mappings</h1>
      <p className="text-xs text-muted-foreground">
        The full editor. Quick-add and inline mapping toggles are also on the dashboard&apos;s Topic board — both write the
        same tables.
      </p>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Add topic</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Input className="w-64" placeholder="name" value={newName} onChange={(e) => setNewName(e.target.value)} />
          <Input className="flex-1" placeholder="description" value={newDescription} onChange={(e) => setNewDescription(e.target.value)} />
          <Button onClick={createTopic} disabled={!newName || !newDescription}>
            Add
          </Button>
        </CardContent>
      </Card>

      {topics === null && <p className="text-sm text-muted-foreground">Loading…</p>}

      <div className="flex flex-col gap-2">
        {topics?.map((t) => (
          <Card key={t.id}>
            <CardContent className="flex flex-wrap items-center gap-3 p-4">
              <Switch checked={t.enabled} onCheckedChange={() => toggleEnabled(t)} />
              <span className="font-medium">{t.name}</span>
              <span className="text-xs text-muted-foreground">{t.mappings.length} mapping row(s)</span>
              <Button
                size="sm"
                variant="outline"
                className="ml-auto"
                onClick={() => setExpanded(expanded === t.id ? null : t.id)}
              >
                {expanded === t.id ? "Collapse" : "Edit"}
              </Button>
            </CardContent>
            {expanded === t.id && <TopicDrawer topic={t} onChanged={load} onDeleted={load} />}
          </Card>
        ))}
      </div>
    </div>
  );
}
