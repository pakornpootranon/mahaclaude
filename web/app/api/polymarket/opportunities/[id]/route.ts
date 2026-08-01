import { NextRequest, NextResponse } from "next/server";

import { prisma } from "@/lib/prisma";
import { jsonError } from "@/lib/api-helpers";

// GET /api/polymarket/opportunities/:id - PM opportunity detail + provenance (docs/02 §6).
export async function GET(_request: NextRequest, { params }: { params: { id: string } }) {
  const opportunity = await prisma.pmOpportunity.findUnique({
    where: { id: params.id },
    include: {
      market: true,
      cycle: { select: { id: true, scheduledFor: true, kind: true } },
      analyses: { include: { analysis: { select: { id: true, storyKey: true, promptVersion: true, model: true } } } },
      outcome: true,
    },
  });

  if (!opportunity) return jsonError("not found", 404);

  return NextResponse.json({
    id: opportunity.id,
    discovery: opportunity.discovery,
    side: opportunity.side,
    marketPrice: opportunity.marketPrice,
    estProbability: opportunity.estProbability,
    edgePoints: opportunity.edgePoints,
    confidence: opportunity.confidence,
    reasoning: opportunity.reasoning,
    ruleTrace: opportunity.ruleTrace,
    promptVersion: opportunity.promptVersion,
    model: opportunity.model,
    createdAt: opportunity.createdAt,
    market: {
      id: opportunity.market.id,
      question: opportunity.market.question,
      slug: opportunity.market.slug,
      category: opportunity.market.category,
      liquidityUsd: opportunity.market.liquidityUsd,
      volume24hUsd: opportunity.market.volume24hUsd,
      endDate: opportunity.market.endDate,
      url: `https://polymarket.com/event/${opportunity.market.slug}`,
    },
    cycle: opportunity.cycle,
    relatedAnalyses: opportunity.analyses.map((a) => a.analysis),
    outcome: opportunity.outcome,
  });
}
