import { NextRequest, NextResponse } from "next/server";

import { prisma } from "@/lib/prisma";
import { jsonError } from "@/lib/api-helpers";

// GET /api/recommendations/:id - full detail + provenance (FR-V1, FR-A5):
// recommendation -> analysis JSON -> news item(s), plus the full rule_trace.
export async function GET(_request: NextRequest, { params }: { params: { id: string } }) {
  const rec = await prisma.recommendation.findUnique({
    where: { id: params.id },
    include: {
      topic: { select: { id: true, name: true, sensitivity: true } },
      cycle: { select: { id: true, scheduledFor: true, kind: true } },
      analysis: {
        select: {
          id: true,
          storyKey: true,
          promptVersion: true,
          model: true,
          result: true,
          eventPolarity: true,
          magnitude: true,
          confidence: true,
          createdAt: true,
          primaryItem: {
            select: { id: true, title: true, url: true, source: { select: { name: true } } },
          },
        },
      },
      sources: {
        include: {
          newsItem: {
            select: {
              id: true,
              title: true,
              url: true,
              summary: true,
              publishedAt: true,
              source: { select: { name: true } },
            },
          },
        },
      },
      outcome: true,
    },
  });

  if (!rec) return jsonError("recommendation not found", 404);

  return NextResponse.json({
    id: rec.id,
    action: rec.action,
    market: rec.market,
    sector: rec.sector,
    tickers: rec.tickers,
    confidence: rec.confidence,
    reasoning: rec.reasoning,
    ruleTrace: rec.ruleTrace,
    createdAt: rec.createdAt,
    topic: rec.topic,
    cycle: rec.cycle,
    analysis: {
      id: rec.analysis.id,
      storyKey: rec.analysis.storyKey,
      promptVersion: rec.analysis.promptVersion,
      model: rec.analysis.model,
      result: rec.analysis.result,
      eventPolarity: rec.analysis.eventPolarity,
      magnitude: rec.analysis.magnitude,
      confidence: rec.analysis.confidence,
      createdAt: rec.analysis.createdAt,
      primaryItem: rec.analysis.primaryItem,
    },
    sources: rec.sources.map((s) => ({
      id: s.newsItem.id,
      title: s.newsItem.title,
      url: s.newsItem.url,
      summary: s.newsItem.summary,
      publishedAt: s.newsItem.publishedAt,
      sourceName: s.newsItem.source.name,
    })),
    outcome: rec.outcome,
  });
}
