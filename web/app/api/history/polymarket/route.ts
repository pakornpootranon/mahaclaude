import { NextRequest, NextResponse } from "next/server";
import { Prisma } from "@prisma/client";

import { prisma } from "@/lib/prisma";
import { parseLimit } from "@/lib/api-helpers";

interface CalibrationRow {
  edge_bucket: number;
  opportunity_count: bigint;
  share_moved_toward_estimate_7d: unknown;
  resolution_accuracy: unknown;
}

// GET /api/history/polymarket?discovery=&cursor=&limit=
// Past PM opportunities with price drift + resolution status, plus
// pm_calibration_v aggregates for the History page's Polymarket tab (FR-V4).
export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const limit = parseLimit(searchParams);

  const where: Prisma.PmOpportunityWhereInput = {};
  const discovery = searchParams.get("discovery");
  if (discovery) where.discovery = discovery;

  const cursor = searchParams.get("cursor");

  const [rows, calibrationRows] = await Promise.all([
    prisma.pmOpportunity.findMany({
      where,
      orderBy: [{ createdAt: "desc" }, { id: "desc" }],
      take: limit + 1,
      ...(cursor ? { cursor: { id: cursor }, skip: 1 } : {}),
      include: { market: true, outcome: true },
    }),
    prisma.$queryRaw<CalibrationRow[]>`SELECT * FROM pm_calibration_v ORDER BY edge_bucket`,
  ]);

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
      createdAt: o.createdAt,
      market: {
        question: o.market.question,
        slug: o.market.slug,
        category: o.market.category,
        url: `https://polymarket.com/event/${o.market.slug}`,
      },
      outcome: o.outcome
        ? {
            price1d: o.outcome.price1d,
            price3d: o.outcome.price3d,
            price7d: o.outcome.price7d,
            movedTowardEstimate7d: o.outcome.movedTowardEstimate7d,
            resolved: o.outcome.resolved,
            resolution: o.outcome.resolution,
            estimateCorrect: o.outcome.estimateCorrect,
            status: o.outcome.status,
          }
        : null,
    })),
    nextCursor: hasMore ? items[items.length - 1]!.id : null,
    calibration: calibrationRows.map((c) => ({
      edgeBucket: c.edge_bucket,
      opportunityCount: Number(c.opportunity_count),
      shareMovedTowardEstimate7d: c.share_moved_toward_estimate_7d,
      resolutionAccuracy: c.resolution_accuracy,
    })),
  });
}
