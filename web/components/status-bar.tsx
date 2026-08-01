"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { relativeFromNow } from "@/lib/time";

interface HealthPayload {
  lastCycle: {
    id: string;
    scheduledFor: string;
    state: string;
    budgetHit: boolean;
    error: string | null;
    finishedAt: string | null;
  } | null;
  sources: { id: string; name: string; enabled: boolean; health: string; lastSuccessAt: string | null }[];
  spend: { monthToDateUsd: number; capUsd: number | null };
}

const POLL_MS = 30_000;

function cycleStateVariant(state: string): "default" | "success" | "destructive" | "secondary" {
  if (state === "DONE") return "success";
  if (state === "FAILED") return "destructive";
  return "secondary";
}

export function StatusBar() {
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/health", { cache: "no-store" });
      if (res.ok) setHealth(await res.json());
    } catch {
      // health strip is best-effort; a fetch failure just leaves the last known state
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  async function runCycle() {
    setRunning(true);
    setMessage(null);
    try {
      const res = await fetch("/api/cycles/run", { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        setMessage(data.error ?? "failed to request a cycle run");
      } else {
        setMessage(data.message);
      }
      await refresh();
    } catch {
      setMessage("failed to reach the server");
    } finally {
      setRunning(false);
    }
  }

  const failingSources = health?.sources.filter((s) => s.enabled && s.health === "failing").length ?? 0;
  const spendPct = health?.spend.capUsd ? Math.round((health.spend.monthToDateUsd / health.spend.capUsd) * 100) : null;

  return (
    <div className="flex flex-wrap items-center gap-3 border-b bg-muted/40 px-4 py-2 text-xs">
      <div className="flex items-center gap-1.5">
        <span className="text-muted-foreground">Last cycle:</span>
        {health?.lastCycle ? (
          <>
            <Badge variant={cycleStateVariant(health.lastCycle.state)}>{health.lastCycle.state}</Badge>
            <span className="text-muted-foreground">{relativeFromNow(health.lastCycle.finishedAt ?? health.lastCycle.scheduledFor)}</span>
            {health.lastCycle.budgetHit && <Badge variant="warning">budget reached</Badge>}
          </>
        ) : (
          <span className="text-muted-foreground">none yet</span>
        )}
      </div>

      <div className="flex items-center gap-1.5">
        <span className="text-muted-foreground">Sources:</span>
        {failingSources > 0 ? (
          <Badge variant="destructive">{failingSources} failing</Badge>
        ) : (
          <Badge variant="success">all healthy</Badge>
        )}
      </div>

      <div className="flex items-center gap-1.5">
        <span className="text-muted-foreground">LLM spend:</span>
        <span>
          ${health?.spend.monthToDateUsd.toFixed(2) ?? "—"} / ${health?.spend.capUsd?.toFixed(2) ?? "—"}
          {spendPct !== null && <span className="text-muted-foreground"> ({spendPct}%)</span>}
        </span>
      </div>

      <div className="ml-auto flex items-center gap-2">
        {message && <span className="text-muted-foreground">{message}</span>}
        <Button size="sm" variant="outline" onClick={runCycle} disabled={running}>
          {running ? "Requesting…" : "Run cycle now"}
        </Button>
      </div>
    </div>
  );
}
