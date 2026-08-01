import { NextResponse } from "next/server";

import { prisma } from "@/lib/prisma";

// No request-dependent input (no searchParams/cookies), so Next.js would
// otherwise statically cache this at build time and freeze health data.
export const dynamic = "force-dynamic";

// GET /api/health - health strip payload (FR-S2): last cycle time/status,
// per-source last success, LLM spend month-to-date vs cap.
export async function GET() {
  const [lastCycle, sources, spendRows, llmSettings] = await Promise.all([
    prisma.cycle.findFirst({ orderBy: { scheduledFor: "desc" } }),
    prisma.source.findMany({
      orderBy: { name: "asc" },
      select: { id: true, name: true, enabled: true, health: true, consecutiveFailures: true, lastSuccessAt: true },
    }),
    prisma.$queryRaw<{ spend_usd: unknown }[]>`SELECT spend_usd FROM spend_mtd_v`,
    prisma.setting.findUnique({ where: { key: "llm" } }),
  ]);

  const monthToDateUsd = spendRows[0] ? Number(spendRows[0].spend_usd) : 0;
  const capUsd = (llmSettings?.value as { monthly_budget_usd?: number } | undefined)?.monthly_budget_usd ?? null;

  return NextResponse.json({
    lastCycle: lastCycle
      ? {
          id: lastCycle.id,
          scheduledFor: lastCycle.scheduledFor,
          state: lastCycle.state,
          kind: lastCycle.kind,
          budgetHit: lastCycle.budgetHit,
          error: lastCycle.error,
          startedAt: lastCycle.startedAt,
          finishedAt: lastCycle.finishedAt,
        }
      : null,
    sources: sources.map((s) => ({
      id: s.id,
      name: s.name,
      enabled: s.enabled,
      health: s.health,
      consecutiveFailures: s.consecutiveFailures,
      lastSuccessAt: s.lastSuccessAt,
    })),
    spend: { monthToDateUsd, capUsd },
  });
}
