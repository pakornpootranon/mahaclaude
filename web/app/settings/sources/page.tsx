"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { TestButton } from "@/components/settings/test-button";
import { relativeFromNow } from "@/lib/time";

interface SourceRow {
  id: string;
  name: string;
  sourceType: string;
  config: Record<string, unknown>;
  enabled: boolean;
  pollOverrideMinutes: number | null;
  language: string;
  health: string;
  consecutiveFailures: number;
  lastSuccessAt: string | null;
}

const SOURCE_TYPES = ["rss", "finnhub", "newsapi", "reddit_rss", "mcp"];

function healthVariant(health: string): "success" | "destructive" | "secondary" {
  if (health === "ok") return "success";
  if (health === "failing") return "destructive";
  return "secondary";
}

function SourceFormDialog({
  trigger,
  initial,
  onSaved,
}: {
  trigger: React.ReactNode;
  initial?: SourceRow;
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(initial?.name ?? "");
  const [sourceType, setSourceType] = useState(initial?.sourceType ?? "rss");
  const [configText, setConfigText] = useState(JSON.stringify(initial?.config ?? { url: "" }, null, 2));
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);
  const [pollOverride, setPollOverride] = useState(initial?.pollOverrideMinutes?.toString() ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setError(null);
    let config: Record<string, unknown>;
    try {
      config = JSON.parse(configText);
    } catch {
      setError("config must be valid JSON");
      return;
    }
    setSaving(true);
    try {
      const url = initial ? `/api/config/sources/${initial.id}` : "/api/config/sources";
      const method = initial ? "PATCH" : "POST";
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          sourceType,
          config,
          enabled,
          pollOverrideMinutes: pollOverride ? Number(pollOverride) : null,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error ?? "failed to save");
        return;
      }
      setOpen(false);
      onSaved();
    } catch {
      setError("failed to reach the server");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{initial ? "Edit source" : "Add source"}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <Label htmlFor="settings-sources-name">Name</Label>
            <Input id="settings-sources-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="settings-sources-type">Type</Label>
            <Select value={sourceType} onValueChange={setSourceType}>
              <SelectTrigger id="settings-sources-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SOURCE_TYPES.map((t) => (
                  <SelectItem key={t} value={t}>
                    {t}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="settings-sources-config">Config (JSON)</Label>
            <Textarea id="settings-sources-config" className="font-mono text-xs" rows={6} value={configText} onChange={(e) => setConfigText(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="settings-sources-poll-override">Poll override (minutes, optional)</Label>
            <Input id="settings-sources-poll-override" type="number" min={1} value={pollOverride} onChange={(e) => setPollOverride(e.target.value)} />
          </div>
          <div className="flex items-center gap-2">
            <Switch checked={enabled} onCheckedChange={setEnabled} />
            <Label>Enabled</Label>
          </div>
          {error && <p className="text-sm text-destructive dark:text-red-400">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={save} disabled={!name || saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function SourcesSettingsPage() {
  const [sources, setSources] = useState<SourceRow[] | null>(null);

  const load = useCallback(async () => {
    const res = await fetch("/api/config/sources", { cache: "no-store" });
    const data = await res.json();
    setSources(data.items);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function toggleEnabled(source: SourceRow) {
    setSources((prev) => prev?.map((s) => (s.id === source.id ? { ...s, enabled: !s.enabled } : s)) ?? null);
    await fetch(`/api/config/sources/${source.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !source.enabled }),
    });
  }

  async function deleteSource(source: SourceRow) {
    if (!confirm(`Delete source "${source.name}"? This can't be undone.`)) return;
    const res = await fetch(`/api/config/sources/${source.id}`, { method: "DELETE" });
    if (!res.ok) {
      const data = await res.json();
      alert(data.error ?? "failed to delete");
      return;
    }
    load();
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Sources</h1>
        <SourceFormDialog trigger={<Button>+ Add source</Button>} onSaved={load} />
      </div>

      {sources === null && <p className="text-sm text-muted-foreground">Loading…</p>}

      <div className="flex flex-col gap-2">
        {sources
          ?.filter((s) => s.sourceType !== "mcp")
          .map((s) => (
            <Card key={s.id}>
              <CardContent className="flex flex-wrap items-center gap-3 p-4">
                <Switch checked={s.enabled} onCheckedChange={() => toggleEnabled(s)} />
                <span className="font-medium">{s.name}</span>
                <Badge variant="outline">{s.sourceType}</Badge>
                <Badge variant={healthVariant(s.health)}>{s.health}</Badge>
                <span className="text-xs text-muted-foreground">
                  last success: {s.lastSuccessAt ? relativeFromNow(s.lastSuccessAt) : "never"}
                </span>
                {s.consecutiveFailures > 0 && (
                  <span className="text-xs text-muted-foreground">{s.consecutiveFailures} consecutive failure(s)</span>
                )}
                <div className="ml-auto flex items-center gap-2">
                  <TestButton sourceId={s.id} />
                  <SourceFormDialog
                    trigger={
                      <Button size="sm" variant="outline">
                        Edit
                      </Button>
                    }
                    initial={s}
                    onSaved={load}
                  />
                  <Button size="sm" variant="ghost" onClick={() => deleteSource(s)}>
                    Delete
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
      </div>

      <p className="text-xs text-muted-foreground">MCP connectors have their own page.</p>
    </div>
  );
}
