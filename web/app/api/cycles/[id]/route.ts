import { NextRequest, NextResponse } from "next/server";

import { prisma } from "@/lib/prisma";
import { jsonError } from "@/lib/api-helpers";

// GET /api/cycles/:id - digest detail: mood/synthesis/themes, triggered
// recommendations, cycle stats (FR-V2).
export async function GET(_request: NextRequest, { params }: { params: { id: string } }) {
  const cycle = await prisma.cycle.findUnique({
    where: { id: params.id },
    include: {
      digest: true,
      recommendations: {
        orderBy: { confidence: "desc" },
        include: { topic: { select: { id: true, name: true } } },
      },
    },
  });

  if (!cycle) return jsonError("cycle not found", 404);

  return NextResponse.json({
    id: cycle.id,
    scheduledFor: cycle.scheduledFor,
    kind: cycle.kind,
    state: cycle.state,
    stats: cycle.stats,
    budgetHit: cycle.budgetHit,
    error: cycle.error,
    startedAt: cycle.startedAt,
    finishedAt: cycle.finishedAt,
    digest: cycle.digest
      ? { marketMood: cycle.digest.marketMood, synthesis: cycle.digest.synthesis, topThemes: cycle.digest.topThemes }
      : null,
    recommendations: cycle.recommendations.map((r) => ({
      id: r.id,
      action: r.action,
      market: r.market,
      sector: r.sector,
      tickers: r.tickers,
      confidence: r.confidence,
      reasoning: r.reasoning,
      topic: r.topic,
      createdAt: r.createdAt,
    })),
  });
}
