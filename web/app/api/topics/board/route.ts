import { NextResponse } from "next/server";

import { prisma } from "@/lib/prisma";

// No request-dependent input, so Next.js would otherwise statically cache
// this at build time and freeze the board (mapping toggles, hit counts).
export const dynamic = "force-dynamic";

// GET /api/topics/board - topic/sector board aggregate (FR-V3): status
// chip, recent matched headlines, mapping rows (with enable toggles),
// impacted tickers, last-triggered time.
//
// Status chip thresholds (hits = distinct analyses matching the topic in
// the last 48h) aren't specified numerically in docs/01 FR-V3 ("quiet /
// active / hot based on hits in last 48h") - authored here: 0 = quiet,
// 1-2 = active, 3+ = hot.
const HOT_THRESHOLD = 3;
const ACTIVE_THRESHOLD = 1;

interface HitRow {
  id: string;
  hits_48h: number;
  last_triggered_at: Date | null;
}

export async function GET() {
  const topics = await prisma.topic.findMany({ orderBy: { name: "asc" } });
  if (topics.length === 0) {
    return NextResponse.json({ items: [] });
  }
  const topicIds = topics.map((t) => t.id);

  const hitRows = await prisma.$queryRaw<HitRow[]>`
    SELECT
      t.id,
      (SELECT count(DISTINCT at.analysis_id)::int FROM analysis_topics at
         JOIN analyses a ON a.id = at.analysis_id
         WHERE at.topic_id = t.id AND a.created_at >= now() - interval '48 hours') AS hits_48h,
      (SELECT max(r.created_at) FROM recommendations r WHERE r.topic_id = t.id) AS last_triggered_at
    FROM topics t
    WHERE t.id = ANY(${topicIds}::uuid[])
  `;
  const hitsById = new Map(hitRows.map((r) => [r.id, r]));

  const mappings = await prisma.mapping.findMany({
    where: { topicId: { in: topicIds } },
    orderBy: [{ market: "asc" }, { sector: "asc" }],
  });
  const mappingsByTopic = new Map<string, typeof mappings>();
  for (const m of mappings) {
    const list = mappingsByTopic.get(m.topicId) ?? [];
    list.push(m);
    mappingsByTopic.set(m.topicId, list);
  }

  const headlineRows = await prisma.$queryRaw<
    { topic_id: string; title: string; news_item_id: string; matched_at: Date }[]
  >`
    SELECT at.topic_id, ni.title, ni.id AS news_item_id, a.created_at AS matched_at
    FROM analysis_topics at
    JOIN analyses a ON a.id = at.analysis_id
    JOIN news_items ni ON ni.id = a.primary_item_id
    WHERE at.topic_id = ANY(${topicIds}::uuid[])
    ORDER BY a.created_at DESC
  `;
  const headlinesByTopic = new Map<string, { title: string; newsItemId: string; matchedAt: Date }[]>();
  for (const row of headlineRows) {
    const list = headlinesByTopic.get(row.topic_id) ?? [];
    if (list.length < 5) {
      list.push({ title: row.title, newsItemId: row.news_item_id, matchedAt: row.matched_at });
    }
    headlinesByTopic.set(row.topic_id, list);
  }

  const items = topics.map((topic) => {
    const hits = hitsById.get(topic.id)?.hits_48h ?? 0;
    const status = hits >= HOT_THRESHOLD ? "hot" : hits >= ACTIVE_THRESHOLD ? "active" : "quiet";
    const topicMappings = mappingsByTopic.get(topic.id) ?? [];
    const impactedTickers = Array.from(new Set(topicMappings.flatMap((m) => m.tickers))).sort();

    return {
      id: topic.id,
      name: topic.name,
      description: topic.description,
      keywords: topic.keywords,
      sensitivity: topic.sensitivity,
      enabled: topic.enabled,
      status,
      hits48h: hits,
      lastTriggeredAt: hitsById.get(topic.id)?.last_triggered_at ?? null,
      recentHeadlines: headlinesByTopic.get(topic.id) ?? [],
      impactedTickers,
      mappings: topicMappings.map((m) => ({
        id: m.id,
        market: m.market,
        sector: m.sector,
        tickers: m.tickers,
        polarity: m.polarity,
        enabled: m.enabled,
        suggestedBy: m.suggestedBy,
        note: m.note,
      })),
    };
  });

  return NextResponse.json({ items });
}
