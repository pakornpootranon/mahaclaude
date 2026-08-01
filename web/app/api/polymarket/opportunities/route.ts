import { NextRequest, NextResponse } from "next/server";
import { Prisma } from "@prisma/client";

import { prisma } from "@/lib/prisma";
import { parseLimit } from "@/lib/api-helpers";

// GET /api/polymarket/opportunities?edge=&category=&mode=&minLiquidity=&cursor=&limit=
// PM opportunities view (FR-V5), paginated newest-first (docs/02 §6).
export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const limit = parseLimit(searchParams);

  const where: Prisma.PmOpportunityWhereInput = {};
  const edge = searchParams.get("edge");
  if (edge) where.edgePoints = { gte: new Prisma.Decimal(edge) };
  const mode = searchParams.get("mode");
  if (mode) where.discovery = mode;

  const marketWhere: Prisma.PmMarketWhereInput = {};
  const category = searchParams.get("category");
  if (category) marketWhere.category = category;
  const minLiquidity = searchParams.get("minLiquidity");
  if (minLiquidity) marketWhere.liquidityUsd = { gte: new Prisma.Decimal(minLiquidity) };
  if (Object.keys(marketWhere).length > 0) where.market = marketWhere;

  const cursor = searchParams.get("cursor");

  const rows = await prisma.pmOpportunity.findMany({
    where,
    orderBy: [{ createdAt: "desc" }, { id: "desc" }],
    take: limit + 1,
    ...(cursor ? { cursor: { id: cursor }, skip: 1 } : {}),
    include: {
      market: true,
      analyses: { include: { analysis: { select: { id: true, storyKey: true } } } },
    },
  });

  const hasMore = rows.length > limit;
  const items = hasMore ? rows.slice(0, limit) : rows;

  return NextResponse.json({
    items: items.map((o) => ({
      id: o.id,
      discovery: o.discovery,
      side: o.side,
      marketPrice: o.marketPrice,
      estProbability: o.estProbability,
      edgePoints: o.edgePoints,
      confidence: o.confidence,
      reasoning: o.reasoning,
      createdAt: o.createdAt,
      market: {
        id: o.market.id,
        question: o.market.question,
        slug: o.market.slug,
        category: o.market.category,
        liquidityUsd: o.market.liquidityUsd,
        volume24hUsd: o.market.volume24hUsd,
        endDate: o.market.endDate,
        url: `https://polymarket.com/event/${o.market.slug}`,
      },
      relatedStorylines: o.analyses.map((a) => a.analysis.storyKey),
    })),
    nextCursor: hasMore ? items[items.length - 1]!.id : null,
  });
}
