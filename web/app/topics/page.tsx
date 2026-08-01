"use client";

import { useCallback, useEffect, useState } from "react";

import { QuickAddTopicDialog } from "@/components/topics/quick-add-dialog";
import { TopicCard, type BoardTopic } from "@/components/topics/topic-card";

export default function TopicsBoardPage() {
  const [topics, setTopics] = useState<BoardTopic[] | null>(null);

  const load = useCallback(async () => {
    const res = await fetch("/api/topics/board", { cache: "no-store" });
    const data = await res.json();
    setTopics(data.items);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Topic / sector board</h1>
        <QuickAddTopicDialog onCreated={load} />
      </div>

      {topics === null && <p className="text-sm text-muted-foreground">Loading…</p>}

      {topics !== null && topics.length === 0 && (
        <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
          No watch topics configured yet. Add one to get started.
        </div>
      )}

      {topics && topics.length > 0 && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {topics.map((t) => (
            <TopicCard key={t.id} topic={t} />
          ))}
        </div>
      )}
    </div>
  );
}
