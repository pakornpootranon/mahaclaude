"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

interface ScheduleCycle {
  id: string;
  time: string;
  enabled: boolean;
  label: string;
}

interface ScheduleSettings {
  timezone: string;
  cycles: ScheduleCycle[];
  outcomes_job_time: string;
}

export default function ScheduleSettingsPage() {
  const [schedule, setSchedule] = useState<ScheduleSettings | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/config/schedule")
      .then((r) => r.json())
      .then(setSchedule);
  }, []);

  function updateCycle(index: number, patch: Partial<ScheduleCycle>) {
    setSchedule((prev) => {
      if (!prev) return prev;
      const cycles = prev.cycles.map((c, i) => (i === index ? { ...c, ...patch } : c));
      return { ...prev, cycles };
    });
  }

  function removeCycle(index: number) {
    setSchedule((prev) => (prev ? { ...prev, cycles: prev.cycles.filter((_, i) => i !== index) } : prev));
  }

  function addCycle() {
    setSchedule((prev) => {
      if (!prev) return prev;
      if (prev.cycles.length >= 6) return prev;
      const id = `cycle-${prev.cycles.length + 1}-${Date.now().toString(36).slice(-4)}`;
      return { ...prev, cycles: [...prev.cycles, { id, time: "12:00", enabled: true, label: "New cycle" }] };
    });
  }

  async function save() {
    if (!schedule) return;
    setSaveMessage(null);
    const res = await fetch("/api/config/schedule", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(schedule),
    });
    const data = await res.json();
    setSaveMessage(res.ok ? "Saved - picked up by the worker within a minute, no restart needed." : data.error ?? "failed to save");
  }

  if (!schedule) return <p className="text-sm text-muted-foreground">Loading…</p>;

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Schedule</h1>
      <p className="text-xs text-muted-foreground">
        Timezone: {schedule.timezone} (fixed in v1). Changes here apply to the next cycle without restarting the worker.
      </p>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Cycles ({schedule.cycles.length}/6)</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {schedule.cycles.map((c, i) => (
            <div key={c.id} className="flex flex-wrap items-center gap-2">
              <Switch checked={c.enabled} onCheckedChange={(v) => updateCycle(i, { enabled: v })} />
              <Input className="w-28" type="time" value={c.time} onChange={(e) => updateCycle(i, { time: e.target.value })} />
              <Input className="w-56" value={c.label} onChange={(e) => updateCycle(i, { label: e.target.value })} />
              <span className="text-xs text-muted-foreground">id: {c.id}</span>
              <Button size="sm" variant="ghost" className="ml-auto" onClick={() => removeCycle(i)}>
                Remove
              </Button>
            </div>
          ))}
          <Button size="sm" variant="outline" onClick={addCycle} disabled={schedule.cycles.length >= 6}>
            + Add cycle
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Outcomes job</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-1">
          <Label className="text-xs" htmlFor="settings-schedule-outcomes-time">Nightly outcomes job time</Label>
          <Input
            id="settings-schedule-outcomes-time"
            className="w-28"
            type="time"
            value={schedule.outcomes_job_time}
            onChange={(e) => setSchedule({ ...schedule, outcomes_job_time: e.target.value })}
          />
        </CardContent>
      </Card>

      <div className="flex items-center gap-3">
        <Button onClick={save}>Save</Button>
        {saveMessage && <span className="text-sm text-muted-foreground">{saveMessage}</span>}
      </div>
    </div>
  );
}
