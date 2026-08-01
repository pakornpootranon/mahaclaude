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
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { TestButton } from "@/components/settings/test-button";

interface McpConfig {
  server_url: string;
  transport?: string;
  tool_name: string;
  args_template?: Record<string, unknown>;
  result_mapping?: Record<string, unknown>;
  auth_env_var?: string;
  max_calls_per_cycle?: number;
}

interface ConnectorRow {
  id: string;
  name: string;
  config: McpConfig;
  enabled: boolean;
  health: string;
  authEnvVarSet: boolean | null;
}

function ConnectorFormDialog({
  trigger,
  initial,
  onSaved,
}: {
  trigger: React.ReactNode;
  initial?: ConnectorRow;
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(initial?.name ?? "");
  const [serverUrl, setServerUrl] = useState(initial?.config.server_url ?? "");
  const [toolName, setToolName] = useState(initial?.config.tool_name ?? "");
  const [authEnvVar, setAuthEnvVar] = useState(initial?.config.auth_env_var ?? "");
  const [maxCalls, setMaxCalls] = useState(String(initial?.config.max_calls_per_cycle ?? 10));
  const [argsTemplateText, setArgsTemplateText] = useState(
    JSON.stringify(initial?.config.args_template ?? { query: "{topic_keywords} latest news", limit: 10 }, null, 2)
  );
  const [resultMappingText, setResultMappingText] = useState(
    JSON.stringify(
      initial?.config.result_mapping ?? {
        items_path: "$.results[*]",
        title: "$.headline",
        url: "$.url",
        summary: "$.snippet",
        published_at: "$.published",
        hints: "$.entities",
      },
      null,
      2
    )
  );
  const [enabled, setEnabled] = useState(initial?.enabled ?? false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setError(null);
    let argsTemplate: Record<string, unknown>;
    let resultMapping: Record<string, unknown>;
    try {
      argsTemplate = JSON.parse(argsTemplateText);
      resultMapping = JSON.parse(resultMappingText);
    } catch {
      setError("args_template and result_mapping must be valid JSON");
      return;
    }
    setSaving(true);
    try {
      const url = initial ? `/api/config/sources/${initial.id}` : "/api/config/mcp-connectors";
      const method = initial ? "PATCH" : "POST";
      const config: McpConfig = {
        server_url: serverUrl,
        transport: "streamable_http",
        tool_name: toolName,
        args_template: argsTemplate,
        result_mapping: resultMapping,
        auth_env_var: authEnvVar || undefined,
        max_calls_per_cycle: Number(maxCalls) || 10,
      };
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, config, enabled, ...(initial ? {} : {}) }),
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
          <DialogTitle>{initial ? "Edit MCP connector" : "Add MCP connector"}</DialogTitle>
        </DialogHeader>
        <div className="flex max-h-[60vh] flex-col gap-3 overflow-y-auto">
          <div className="flex flex-col gap-1">
            <Label htmlFor="mcp-connector-name">Name</Label>
            <Input id="mcp-connector-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Bigdata.com (MCP)" />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="mcp-connector-server-url">Server URL</Label>
            <Input id="mcp-connector-server-url" value={serverUrl} onChange={(e) => setServerUrl(e.target.value)} placeholder="https://mcp.example.com/mcp" />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="mcp-connector-tool-name">Tool name</Label>
            <Input id="mcp-connector-tool-name" value={toolName} onChange={(e) => setToolName(e.target.value)} placeholder="e.g. bigdata_search" />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="mcp-connector-auth-env-var">Auth env var name</Label>
            <Input id="mcp-connector-auth-env-var" value={authEnvVar} onChange={(e) => setAuthEnvVar(e.target.value)} placeholder="e.g. BIGDATA_API_KEY" />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="mcp-connector-max-calls">Max calls per cycle</Label>
            <Input id="mcp-connector-max-calls" type="number" min={1} value={maxCalls} onChange={(e) => setMaxCalls(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="mcp-connector-args-template">args_template (JSON, raw-JSON escape hatch)</Label>
            <Textarea id="mcp-connector-args-template" className="font-mono text-xs" rows={4} value={argsTemplateText} onChange={(e) => setArgsTemplateText(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="mcp-connector-result-mapping">result_mapping (JSON, raw-JSON escape hatch)</Label>
            <Textarea
              id="mcp-connector-result-mapping"
              className="font-mono text-xs"
              rows={6}
              value={resultMappingText}
              onChange={(e) => setResultMappingText(e.target.value)}
            />
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
          <Button onClick={save} disabled={!name || !serverUrl || !toolName || saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function McpConnectorsSettingsPage() {
  const [connectors, setConnectors] = useState<ConnectorRow[] | null>(null);

  const load = useCallback(async () => {
    const res = await fetch("/api/config/mcp-connectors", { cache: "no-store" });
    const data = await res.json();
    setConnectors(data.items);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function toggleEnabled(connector: ConnectorRow) {
    setConnectors((prev) => prev?.map((c) => (c.id === connector.id ? { ...c, enabled: !c.enabled } : c)) ?? null);
    await fetch(`/api/config/sources/${connector.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !connector.enabled }),
    });
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">MCP Connectors</h1>
        <ConnectorFormDialog trigger={<Button>+ Add connector</Button>} onSaved={load} />
      </div>

      {connectors === null && <p className="text-sm text-muted-foreground">Loading…</p>}
      {connectors?.length === 0 && (
        <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
          No MCP connectors configured.
        </div>
      )}

      <div className="flex flex-col gap-2">
        {connectors?.map((c) => (
          <Card key={c.id}>
            <CardContent className="flex flex-col gap-2 p-4">
              <div className="flex flex-wrap items-center gap-3">
                <Switch checked={c.enabled} onCheckedChange={() => toggleEnabled(c)} />
                <span className="font-medium">{c.name}</span>
                <Badge variant={c.health === "ok" ? "success" : c.health === "failing" ? "destructive" : "secondary"}>
                  {c.health}
                </Badge>
                {c.config.auth_env_var && (
                  <Badge variant={c.authEnvVarSet ? "success" : "warning"}>
                    {c.config.auth_env_var}: {c.authEnvVarSet ? "set" : "unset"}
                  </Badge>
                )}
                <div className="ml-auto flex items-center gap-2">
                  <TestButton sourceId={c.id} />
                  <ConnectorFormDialog
                    trigger={
                      <Button size="sm" variant="outline">
                        Edit
                      </Button>
                    }
                    initial={c}
                    onSaved={load}
                  />
                </div>
              </div>
              <div className="text-xs text-muted-foreground">
                {c.config.server_url} — tool: {c.config.tool_name} — max {c.config.max_calls_per_cycle ?? 10} calls/cycle
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
