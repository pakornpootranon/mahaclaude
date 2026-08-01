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
    startedAt: string | null;
    finishedAt: string | null;
  } | null;
  sources: { id: string; name: string; enabled: boolean; health: string; lastSuccessAt: string | null }[];
  spend: { monthToDateUsd: number; capUsd: number | null };
}

const IDLE_POLL_MS = 30_000;
const RUNNING_POLL_MS = 5_000;

const TERMINAL_STATES = new Set(["DONE", "FAILED"]);

// Friendlier labels for the cycle state machine (worker/newswatch_worker/cycle.py STATES).
const STATE_LABELS: Record<string, string> = {
  PENDING: "queued",
  INGESTING: "ingesting news",
  TRIAGING: "triaging",
  ANALYZING: "analyzing storylines",
  TRIGGERING: "evaluating rules",
  PM_SCANNING: "scanning polymarket",
  SUMMARIZING: "writing digest",
  DONE: "done",
  FAILED: "failed",
};

function cycleStateVariant(state: string): "default" | "success" | "destructive" | "secondary" {
  if (state === "DONE") return "success";
  if (state === "FAILED") return "destructive";
  return "secondary";
}

function formatElapsed(since: string): string {
  const ms = Date.now() - new Date(since).getTime();
  const min = Math.max(0, Math.round(ms / 60000));
  if (min < 1) return "just started";
  if (min < 60) return `running ${min}m`;
  const hr = Math.floor(min / 60);
  const rem = min % 60;
  return `running ${hr}h ${rem}m`;
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

  const isRunning = health?.lastCycle ? !TERMINAL_STATES.has(health.lastCycle.state) : false;

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Poll faster while a cycle is actively running so "Last cycle" updates
  // through its states instead of looking stuck for up to 30s at a time.
  useEffect(() => {
    const id = setInterval(refresh, isRunning ? RUNNING_POLL_MS : IDLE_POLL_MS);
    return () => clearInterval(id);
  }, [refresh, isRunning]);

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
            {isRunning && (
              <span className="relative flex h-2 w-2" title="cycle in progress">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-sky-400 opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-sky-500" />
              </span>
            )}
            <Badge variant={cycleStateVariant(health.lastCycle.state)}>
              {STATE_LABELS[health.lastCycle.state] ?? health.lastCycle.state}
            </Badge>
            <span className="text-muted-foreground">
              {isRunning
                ? formatElapsed(health.lastCycle.startedAt ?? health.lastCycle.scheduledFor)
                : relativeFromNow(health.lastCycle.finishedAt ?? health.lastCycle.scheduledFor)}
            </span>
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
