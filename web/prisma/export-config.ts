// Standalone config-export script for `make backup` (CLAUDE.md Phase 7),
// runnable outside a live Next.js server via `npx tsx prisma/export-config.ts`.
// Prints the same shape as `GET /api/config/export` to stdout - kept as a
// second, deliberately duplicated implementation (mirrors seed.ts's own
// standalone PrismaClient rather than importing `@/lib/prisma`, which is a
// Next.js-request-scoped singleton not meant for one-shot scripts) so a
// backup never depends on the web server being up.
//
// Never includes the Claude API key (it isn't in this JSON at all - it
// lives in the secrets table, arch §9) or any auth_env_var *values*
// (sources.config only ever stores the env var *name*, docs/05 §4).

import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

async function main() {
  const [sources, topics, rules, schedule, llm, polymarket] = await Promise.all([
    prisma.source.findMany({ orderBy: { name: "asc" } }),
    prisma.topic.findMany({ orderBy: { name: "asc" }, include: { mappings: true } }),
    prisma.setting.findUnique({ where: { key: "rules" } }),
    prisma.setting.findUnique({ where: { key: "schedule" } }),
    prisma.setting.findUnique({ where: { key: "llm" } }),
    prisma.setting.findUnique({ where: { key: "polymarket" } }),
  ]);

  const config = {
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
  };

  process.stdout.write(JSON.stringify(config, null, 2) + "\n");
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
