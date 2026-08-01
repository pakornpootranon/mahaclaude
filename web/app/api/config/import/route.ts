import { NextRequest, NextResponse } from "next/server";
import { Prisma } from "@prisma/client";

import { jsonError } from "@/lib/api-helpers";
import { prisma } from "@/lib/prisma";

interface ImportMapping {
  market: string;
  sector: string;
  tickers?: string[];
  polarity: number;
  note?: string | null;
  enabled?: boolean;
}

interface ImportSource {
  name: string;
  source_type: string;
  config: Record<string, unknown>;
  enabled?: boolean;
  poll_override_minutes?: number | null;
  language?: string;
}

interface ImportTopic {
  name: string;
  description: string;
  keywords?: string[];
  sensitivity?: number | string;
  enabled?: boolean;
  mappings?: ImportMapping[];
}

interface ImportConfig {
  newswatch_config_version?: number;
  sources?: ImportSource[];
  topics?: ImportTopic[];
  settings?: { rules?: object; schedule?: object; llm?: object; polymarket?: object };
}

interface DiffEntry {
  name: string;
  action: "create" | "update";
  changes?: Record<string, { before: unknown; after: unknown }>;
}

function deepEqual(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function diffFields(before: Record<string, unknown>, after: Record<string, unknown>): Record<string, { before: unknown; after: unknown }> {
  const changes: Record<string, { before: unknown; after: unknown }> = {};
  for (const key of Object.keys(after)) {
    if (!deepEqual(before[key], after[key])) changes[key] = { before: before[key], after: after[key] };
  }
  return changes;
}

async function computeSourceDiffs(sources: ImportSource[]): Promise<DiffEntry[]> {
  const existing = await prisma.source.findMany({ where: { name: { in: sources.map((s) => s.name) } } });
  const byName = new Map(existing.map((s) => [s.name, s]));

  const diffs: DiffEntry[] = [];
  for (const s of sources) {
    const current = byName.get(s.name);
    const after = {
      source_type: s.source_type,
      config: s.config,
      enabled: s.enabled ?? true,
      poll_override_minutes: s.poll_override_minutes ?? null,
      language: s.language ?? "en",
    };
    if (!current) {
      diffs.push({ name: s.name, action: "create" });
      continue;
    }
    const before = {
      source_type: current.sourceType,
      config: current.config,
      enabled: current.enabled,
      poll_override_minutes: current.pollOverrideMinutes,
      language: current.language,
    };
    const changes = diffFields(before, after);
    if (Object.keys(changes).length > 0) diffs.push({ name: s.name, action: "update", changes });
  }
  return diffs;
}

async function computeTopicDiffs(topics: ImportTopic[]): Promise<DiffEntry[]> {
  const existing = await prisma.topic.findMany({
    where: { name: { in: topics.map((t) => t.name) } },
    include: { mappings: true },
  });
  const byName = new Map(existing.map((t) => [t.name, t]));

  const diffs: DiffEntry[] = [];
  for (const t of topics) {
    const current = byName.get(t.name);
    const after = {
      description: t.description,
      keywords: t.keywords ?? [],
      sensitivity: Number(t.sensitivity ?? 0.7),
      enabled: t.enabled ?? true,
    };
    if (!current) {
      diffs.push({ name: t.name, action: "create", changes: { mappings: { before: 0, after: (t.mappings ?? []).length } } });
      continue;
    }
    const before = {
      description: current.description,
      keywords: current.keywords,
      sensitivity: Number(current.sensitivity),
      enabled: current.enabled,
    };
    const changes = diffFields(before, after);

    const currentMappingsByKey = new Map(current.mappings.map((m) => [`${m.market}/${m.sector}`, m]));
    let mappingChanges = 0;
    for (const m of t.mappings ?? []) {
      const key = `${m.market}/${m.sector}`;
      const currentMapping = currentMappingsByKey.get(key);
      const mAfter = { tickers: m.tickers ?? [], polarity: m.polarity, note: m.note ?? null, enabled: m.enabled ?? true };
      if (!currentMapping) {
        mappingChanges += 1;
      } else {
        const mBefore = {
          tickers: currentMapping.tickers,
          polarity: currentMapping.polarity,
          note: currentMapping.note,
          enabled: currentMapping.enabled,
        };
        if (Object.keys(diffFields(mBefore, mAfter)).length > 0) mappingChanges += 1;
      }
    }
    if (mappingChanges > 0) changes.mappings = { before: 0, after: mappingChanges };

    if (Object.keys(changes).length > 0) diffs.push({ name: t.name, action: "update", changes });
  }
  return diffs;
}

async function computeSettingsDiff(settings: ImportConfig["settings"]): Promise<Record<string, { before: unknown; after: unknown }>> {
  const result: Record<string, { before: unknown; after: unknown }> = {};
  if (!settings) return result;
  for (const key of ["rules", "schedule", "llm", "polymarket"] as const) {
    const incoming = settings[key];
    if (incoming === undefined) continue;
    const current = await prisma.setting.findUnique({ where: { key } });
    if (!deepEqual(current?.value ?? null, incoming)) {
      result[key] = { before: current?.value ?? null, after: incoming };
    }
  }
  return result;
}

async function applyImport(config: ImportConfig): Promise<void> {
  for (const s of config.sources ?? []) {
    await prisma.source.upsert({
      where: { name: s.name },
      create: {
        name: s.name,
        sourceType: s.source_type,
        config: s.config as Prisma.InputJsonValue,
        enabled: s.enabled ?? true,
        pollOverrideMinutes: s.poll_override_minutes ?? null,
        language: s.language ?? "en",
      },
      update: {
        sourceType: s.source_type,
        config: s.config as Prisma.InputJsonValue,
        enabled: s.enabled ?? true,
        pollOverrideMinutes: s.poll_override_minutes ?? null,
        language: s.language ?? "en",
      },
    });
  }

  for (const t of config.topics ?? []) {
    const topic = await prisma.topic.upsert({
      where: { name: t.name },
      create: {
        name: t.name,
        description: t.description,
        keywords: t.keywords ?? [],
        sensitivity: new Prisma.Decimal(Number(t.sensitivity ?? 0.7)),
        enabled: t.enabled ?? true,
      },
      update: {
        description: t.description,
        keywords: t.keywords ?? [],
        sensitivity: new Prisma.Decimal(Number(t.sensitivity ?? 0.7)),
        enabled: t.enabled ?? true,
      },
    });
    for (const m of t.mappings ?? []) {
      await prisma.mapping.upsert({
        where: { topicId_market_sector: { topicId: topic.id, market: m.market, sector: m.sector } },
        create: {
          topicId: topic.id,
          market: m.market,
          sector: m.sector,
          tickers: m.tickers ?? [],
          polarity: m.polarity,
          note: m.note ?? null,
          enabled: m.enabled ?? true,
        },
        update: {
          tickers: m.tickers ?? [],
          polarity: m.polarity,
          note: m.note ?? null,
          enabled: m.enabled ?? true,
        },
      });
    }
  }

  for (const key of ["rules", "schedule", "llm", "polymarket"] as const) {
    const value = config.settings?.[key];
    if (value === undefined) continue;
    await prisma.setting.upsert({
      where: { key },
      create: { key, value: value as object },
      update: { value: value as object },
    });
  }
}

// POST /api/config/import - FR-C7. Upsert-by-name, never deletes rows
// absent from the file. `dryRun: true` (the default) returns a diff
// without writing anything; the UI shows that diff before a second call
// with `dryRun: false` actually applies it.
export async function POST(request: NextRequest) {
  let body: { config?: ImportConfig; dryRun?: boolean };
  try {
    body = await request.json();
  } catch {
    return jsonError("invalid JSON body");
  }
  const config = body.config;
  if (!config || typeof config !== "object") return jsonError("config is required");
  const dryRun = body.dryRun ?? true;

  if (dryRun) {
    const [sourceDiffs, topicDiffs, settingsDiff] = await Promise.all([
      computeSourceDiffs(config.sources ?? []),
      computeTopicDiffs(config.topics ?? []),
      computeSettingsDiff(config.settings),
    ]);
    return NextResponse.json({ dryRun: true, sources: sourceDiffs, topics: topicDiffs, settings: settingsDiff });
  }

  await applyImport(config);
  return NextResponse.json({ dryRun: false, applied: true });
}
