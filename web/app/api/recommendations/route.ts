import { NextRequest, NextResponse } from "next/server";
import { Prisma } from "@prisma/client";

import { prisma } from "@/lib/prisma";
import { parseLimit } from "@/lib/api-helpers";

// GET /api/recommendations?market=&action=&topic=&minConfidence=&from=&to=&cursor=&limit=
// Action feed (FR-V1), paginated newest-first (docs/02 §6).
export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const limit = parseLimit(searchParams);

  const where: Prisma.RecommendationWhereInput = {};
  const market = searchParams.get("market");
  if (market) where.market = market;
  const action = searchParams.get("action");
  if (action) where.action = action;
  const topic = searchParams.get("topic");
  if (topic) where.topicId = topic;
  const minConfidence = searchParams.get("minConfidence");
  if (minConfidence) where.confidence = { gte: new Prisma.Decimal(minConfidence) };
  const from = searchParams.get("from");
  const to = searchParams.get("to");
  if (from || to) {
    where.createdAt = {
      ...(from ? { gte: new Date(from) } : {}),
      ...(to ? { lte: new Date(to) } : {}),
    };
  }

  const cursor = searchParams.get("cursor");

  const rows = await prisma.recommendation.findMany({
    where,
    orderBy: [{ createdAt: "desc" }, { id: "desc" }],
    take: limit + 1,
    ...(cursor ? { cursor: { id: cursor }, skip: 1 } : {}),
    include: {
      topic: { select: { id: true, name: true } },
      analysis: { select: { id: true, storyKey: true } },
      sources: {
        take: 3,
        include: { newsItem: { include: { source: { select: { name: true } } } } },
      },
    },
  });

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
      reasoning: r.reasoning,
      createdAt: r.createdAt,
      topic: r.topic,
      analysisId: r.analysis.id,
      storyKey: r.analysis.storyKey,
      sources: r.sources.map((s) => ({
        title: s.newsItem.title,
        url: s.newsItem.url,
        sourceName: s.newsItem.source.name,
      })),
    })),
    nextCursor: hasMore ? items[items.length - 1]!.id : null,
  });
}
