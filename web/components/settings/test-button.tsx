"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";

export function TestButton({ sourceId }: { sourceId: string }) {
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  async function runTest() {
    setTesting(true);
    setResult(null);
    try {
      const res = await fetch(`/api/config/sources/${sourceId}/test`, { method: "POST" });
      const data = await res.json();
      if (res.status === 202) {
        setResult(data.message);
      } else if (data.status === "completed") {
        const r = data.result as { ok?: boolean; sample_titles?: string[]; error?: string } | null;
        setResult(r?.ok ? `OK - ${r.sample_titles?.length ?? 0} sample item(s)` : `Failed: ${r?.error ?? "unknown error"}`);
      } else {
        setResult(`status: ${data.status}`);
      }
    } catch {
      setResult("failed to reach the server");
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <Button size="sm" variant="outline" onClick={runTest} disabled={testing}>
        {testing ? "Testing…" : "Test"}
      </Button>
      {result && <span className="text-xs text-muted-foreground">{result}</span>}
    </div>
  );
}
