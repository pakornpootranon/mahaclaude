import { NextRequest, NextResponse } from "next/server";

import { jsonError } from "@/lib/api-helpers";
import { prisma } from "@/lib/prisma";
import { validateRulesSettings } from "@/lib/settings";

interface Impact {
  market: string;
  sector: string;
  direction: "bullish" | "bearish";
  tickers?: string[];
  strength: number;
}

interface AnalysisResultJson {
  horizon?: string;
  impacts?: Impact[];
  unmapped_sectors?: { sector: string; note?: string }[];
}

function sectorScopePass(sector: string, scope: { allowlist: string[]; blocklist: string[] }): boolean {
  const s = sector.toLowerCase();
  if (scope.blocklist.some((b) => b.toLowerCase() === s)) return false;
  if (scope.allowlist.length > 0 && !scope.allowlist.some((a) => a.toLowerCase() === s)) return false;
  return true;
}

// POST /api/config/rules/preview - "what would have triggered last cycle"
// (docs/05 §7). A simplified, TypeScript-side port of worker/rules.py's
// core gate conditions (topic/mapping enabled, sector_scope, confidence
// and magnitude floors) run against the most recent cycle's analyses.
// Deliberately excludes rules.py's dedup-window and per-cycle-cap/ranking
// steps - those only ever REDUCE the final count relative to this preview,
// and re-implementing them for a live slider preview isn't worth the
// duplication; this documents that gap rather than silently overstating
// precision the count doesn't have.
export async function POST(request: NextRequest) {
  let draft: Record<string, unknown>;
  try {
    draft = await request.json();
  } catch {
    return jsonError("invalid JSON body");
  }
  const errors = validateRulesSettings(draft);
  if (errors.length) return jsonError(errors.join("; "));

  const lastCycle = await prisma.cycle.findFirst({ orderBy: { scheduledFor: "desc" } });
  if (!lastCycle) {
    return NextResponse.json({ cycleId: null, candidateCount: 0, byAction: { BUY: 0, SELL: 0, WATCH: 0 } });
  }

  const [analyses, topics, mappings] = await Promise.all([
    prisma.analysis.findMany({
      where: { cycleId: lastCycle.id },
      include: { analysisTopics: true },
    }),
    prisma.topic.findMany(),
    prisma.mapping.findMany(),
  ]);

  const topicsById = new Map(topics.map((t) => [t.id, t]));
  const mappingsByKey = new Map(mappings.map((m) => [`${m.topicId}/${m.market}/${m.sector}`, m]));

  const scope = draft.sector_scope as { allowlist: string[]; blocklist: string[] };

  const byAction = { BUY: 0, SELL: 0, WATCH: 0 };
  let candidateCount = 0;

  for (const analysis of analyses) {
    const result = analysis.result as AnalysisResultJson;
    const magnitude = Number(analysis.magnitude);
    const confidence = Number(analysis.confidence);
    const matchedTopicIds = analysis.analysisTopics.map((at) => at.topicId).filter((id): id is string => id !== null);

    if (matchedTopicIds.length > 0) {
      for (const topicId of matchedTopicIds) {
        const topic = topicsById.get(topicId);
        for (const impact of result.impacts ?? []) {
          const mapping = mappingsByKey.get(`${topicId}/${impact.market}/${impact.sector}`);
          const effectiveConfidence = confidence * impact.strength;
          const confidenceFloor = Math.max(Number(topic?.sensitivity ?? 0), draft.global_confidence_floor as number);

          const passes =
            Boolean(topic?.enabled) &&
            Boolean(mapping?.enabled) &&
            sectorScopePass(impact.sector, scope) &&
            effectiveConfidence >= confidenceFloor &&
            magnitude >= (draft.global_magnitude_floor as number);

          if (!passes) continue;

          let action: "BUY" | "SELL" | "WATCH" = impact.direction === "bullish" ? "BUY" : "SELL";
          if (magnitude < (draft.watch_floor as number) || result.horizon === "months") action = "WATCH";

          candidateCount += 1;
          byAction[action] += 1;
        }
      }
    } else {
      for (const unmapped of result.unmapped_sectors ?? []) {
        const passes = magnitude >= (draft.unconfigured_magnitude_floor as number) && sectorScopePass(unmapped.sector, scope);
        if (!passes) continue;
        candidateCount += 1;
        byAction.WATCH += 1;
      }
    }
  }

  return NextResponse.json({ cycleId: lastCycle.id, candidateCount, byAction });
}
