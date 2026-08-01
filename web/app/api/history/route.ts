import { NextRequest, NextResponse } from "next/server";
import { Prisma } from "@prisma/client";

import { prisma } from "@/lib/prisma";
import { parseLimit } from "@/lib/api-helpers";

interface HitRateRow {
  topic_id: string | null;
  topic_name: string | null;
  action: string;
  recommendation_count: bigint;
  avg_confidence: unknown;
  hit_rate_1d: unknown;
  hit_rate_3d: unknown;
  hit_rate_7d: unknown;
}

// GET /api/history?topic=&action=&market=&cursor=&limit=
// Outcomes table + hit-rate aggregates (FR-V4, docs/02 §6).
export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const limit = parseLimit(searchParams);

  const where: Prisma.RecommendationWhereInput = {};
  const topic = searchParams.get("topic");
  if (topic) where.topicId = topic;
  const action = searchParams.get("action");
  if (action) where.action = action;
  const market = searchParams.get("market");
  if (market) where.market = market;

  const cursor = searchParams.get("cursor");

  const [rows, hitRateRows] = await Promise.all([
    prisma.recommendation.findMany({
      where,
      orderBy: [{ createdAt: "desc" }, { id: "desc" }],
      take: limit + 1,
      ...(cursor ? { cursor: { id: cursor }, skip: 1 } : {}),
      include: { topic: { select: { id: true, name: true } }, outcome: true },
    }),
    prisma.$queryRaw<HitRateRow[]>`SELECT * FROM hit_rates_v ORDER BY topic_name NULLS LAST, action`,
  ]);

  const hasMore = rows.length > limit;
  const items = hasMore ? rows.slice(0, limit) : rows;

  return NextResponse.json({
    items: items.map((r) => ({
      id: r.id,
      action: r.action,
      market: r.market,
      sector: r.sector,
      tickers: r.tickers,
      confidence: r.confidence,
      createdAt: r.createdAt,
      topic: r.topic,
      outcome: r.outcome
        ? {
            ticker: r.outcome.ticker,
            entryPrice: r.outcome.entryPrice,
            ret1d: r.outcome.ret1d,
            ret3d: r.outcome.ret3d,
            ret7d: r.outcome.ret7d,
            hit1d: r.outcome.hit1d,
            hit3d: r.outcome.hit3d,
            hit7d: r.outcome.hit7d,
            status: r.outcome.status,
          }
        : null,
    })),
    nextCursor: hasMore ? items[items.length - 1]!.id : null,
    hitRates: hitRateRows.map((h) => ({
      topicId: h.topic_id,
      topicName: h.topic_name ?? "unconfigured but significant",
      action: h.action,
      recommendationCount: Number(h.recommendation_count),
      avgConfidence: h.avg_confidence,
      hitRate1d: h.hit_rate_1d,
      hitRate3d: h.hit_rate_3d,
      hitRate7d: h.hit_rate_7d,
    })),
  });
}
