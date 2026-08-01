import { NextRequest, NextResponse } from "next/server";

import { prisma } from "@/lib/prisma";
import { parseLimit } from "@/lib/api-helpers";

// GET /api/cycles?cursor=&limit= - digest history nav (FR-V2).
export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const limit = parseLimit(searchParams);
  const cursor = searchParams.get("cursor");

  const rows = await prisma.cycle.findMany({
    orderBy: [{ scheduledFor: "desc" }, { id: "desc" }],
    take: limit + 1,
    ...(cursor ? { cursor: { id: cursor }, skip: 1 } : {}),
    include: {
      digest: { select: { marketMood: true, synthesis: true } },
      _count: { select: { recommendations: true } },
    },
  });

  const hasMore = rows.length > limit;
  const items = hasMore ? rows.slice(0, limit) : rows;

  return NextResponse.json({
    items: items.map((c) => ({
      id: c.id,
      scheduledFor: c.scheduledFor,
      kind: c.kind,
      state: c.state,
      stats: c.stats,
      budgetHit: c.budgetHit,
      startedAt: c.startedAt,
      finishedAt: c.finishedAt,
      marketMood: c.digest?.marketMood ?? null,
      synthesis: c.digest?.synthesis ?? null,
      recommendationCount: c._count.recommendations,
    })),
    nextCursor: hasMore ? items[items.length - 1]!.id : null,
  });
}
