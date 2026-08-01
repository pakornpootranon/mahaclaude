"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";

interface DiffEntry {
  name: string;
  action: "create" | "update";
  changes?: Record<string, { before: unknown; after: unknown }>;
}

interface ImportDiff {
  dryRun: true;
  sources: DiffEntry[];
  topics: DiffEntry[];
  settings: Record<string, { before: unknown; after: unknown }>;
}

function DiffList({ title, entries }: { title: string; entries: DiffEntry[] }) {
  if (entries.length === 0) return null;
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground">{title}</p>
      <ul className="mt-1 flex flex-col gap-1 text-xs">
        {entries.map((e) => (
          <li key={e.name}>
            <span className={e.action === "create" ? "text-success dark:text-emerald-400" : "text-amber-700 dark:text-amber-400"}>
              {e.action === "create" ? "+ create" : "~ update"}
            </span>{" "}
            {e.name}
            {e.changes && <span className="text-muted-foreground"> ({Object.keys(e.changes).join(", ")})</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function ExportImportSettingsPage() {
  const [exported, setExported] = useState<string | null>(null);
  const [importText, setImportText] = useState("");
  const [diff, setDiff] = useState<ImportDiff | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function doExport() {
    const res = await fetch("/api/config/export");
    const data = await res.json();
    setExported(JSON.stringify(data, null, 2));
  }

  function downloadExport() {
    if (!exported) return;
    const blob = new Blob([exported], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `newswatch-config-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function previewImport() {
    setMessage(null);
    setDiff(null);
    let config: unknown;
    try {
      config = JSON.parse(importText);
    } catch {
      setMessage("not valid JSON");
      return;
    }
    setBusy(true);
    try {
      const res = await fetch("/api/config/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config, dryRun: true }),
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(data.error ?? "failed to preview import");
        return;
      }
      setDiff(data);
      if (data.sources.length === 0 && data.topics.length === 0 && Object.keys(data.settings).length === 0) {
        setMessage("No changes - import(export(x)) is a no-op here.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function applyImport() {
    setBusy(true);
    setMessage(null);
    try {
      const config = JSON.parse(importText);
      const res = await fetch("/api/config/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config, dryRun: false }),
      });
      const data = await res.json();
      setMessage(res.ok ? "Applied." : data.error ?? "failed to apply import");
      setDiff(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Export / Import</h1>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Export</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <p className="text-xs text-muted-foreground">
            Never includes the Claude API key or any connector secret values - only env-var names.
          </p>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={doExport}>
              Generate export
            </Button>
            {exported && (
              <Button size="sm" variant="outline" onClick={downloadExport}>
                Download
              </Button>
            )}
          </div>
          {exported && <Textarea className="h-48 font-mono text-xs" readOnly value={exported} />}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Import</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <p className="text-xs text-muted-foreground">
            Upsert-by-name for sources and topics - nothing absent from the file is deleted.
          </p>
          <Textarea
            className="h-40 font-mono text-xs"
            placeholder="Paste exported config JSON here"
            value={importText}
            onChange={(e) => setImportText(e.target.value)}
          />
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={previewImport} disabled={!importText || busy}>
              Preview diff
            </Button>
            {diff && (diff.sources.length > 0 || diff.topics.length > 0 || Object.keys(diff.settings).length > 0) && (
              <Button size="sm" onClick={applyImport} disabled={busy}>
                Apply
              </Button>
            )}
          </div>
          {message && <p className="text-sm text-muted-foreground">{message}</p>}
          {diff && (
            <div className="flex flex-col gap-2 rounded-md border p-3">
              <DiffList title="Sources" entries={diff.sources} />
              <DiffList title="Topics" entries={diff.topics} />
              {Object.keys(diff.settings).length > 0 && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground">Settings</p>
                  <ul className="mt-1 text-xs">
                    {Object.keys(diff.settings).map((k) => (
                      <li key={k}>~ {k}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
