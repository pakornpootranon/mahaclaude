import { NextResponse } from "next/server";

import { prisma } from "@/lib/prisma";

export const dynamic = "force-dynamic";

// GET /api/config/export - FR-C7. Never includes any credential (Claude
// API key, Finnhub/NewsAPI keys, MCP connector tokens) - none of them are
// in this JSON at all, they all live in the secrets table (arch §9) which
// this route never queries. sources.config only ever stores the env var
// *name* as a fallback label (e.g. "BIGDATA_API_KEY"), never a secret value
// - see docs/05 §4.
export async function GET() {
  const [sources, topics, rules, schedule, llm, polymarket] = await Promise.all([
    prisma.source.findMany({ orderBy: { name: "asc" } }),
    prisma.topic.findMany({ orderBy: { name: "asc" }, include: { mappings: true } }),
    prisma.setting.findUnique({ where: { key: "rules" } }),
    prisma.setting.findUnique({ where: { key: "schedule" } }),
    prisma.setting.findUnique({ where: { key: "llm" } }),
    prisma.setting.findUnique({ where: { key: "polymarket" } }),
  ]);

  return NextResponse.json({
    newswatch_config_version: 1,
    exported_at: new Date().toISOString(),
    sources: sources.map((s) => ({
      name: s.name,
      source_type: s.sourceType,
      config: s.config,
      enabled: s.enabled,
      poll_override_minutes: s.pollOverrideMinutes,
      language: s.language,
    })),
    topics: topics.map((t) => ({
      name: t.name,
      description: t.description,
      keywords: t.keywords,
      sensitivity: t.sensitivity,
      enabled: t.enabled,
      mappings: t.mappings.map((m) => ({
        market: m.market,
        sector: m.sector,
        tickers: m.tickers,
        polarity: m.polarity,
        note: m.note,
        enabled: m.enabled,
      })),
    })),
    settings: {
      rules: rules?.value ?? {},
      schedule: schedule?.value ?? {},
      llm: llm?.value ?? {},
      polymarket: polymarket?.value ?? {},
    },
  });
}
