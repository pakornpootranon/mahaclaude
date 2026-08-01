import { NextRequest, NextResponse } from "next/server";

import { jsonError } from "@/lib/api-helpers";
import { prisma } from "@/lib/prisma";
import { getSettingValue, upsertSettingValue, validateLlmSettings } from "@/lib/settings";

export const dynamic = "force-dynamic";

// GET/PATCH /api/config/llm - settings['llm'] (docs/05 §3, FR-C6) plus the
// masked API key (docs/02 §9: DB-stored, never rendered unmasked, never
// exported). PATCH accepts an optional write-only `apiKey` field to rotate
// it - the response never echoes the key back, only {set, last4, status}.
export async function GET() {
  const value = await getSettingValue<Record<string, unknown>>("llm");
  if (!value) return jsonError("settings['llm'] is not seeded", 500);

  const secret = await prisma.secret.findUnique({ where: { key: "anthropic_api_key" } });
  return NextResponse.json({
    ...value,
    apiKey: {
      set: Boolean(secret),
      last4: secret?.last4 ?? null,
      status: secret?.status ?? "unknown",
      lastCheckedAt: secret?.lastCheckedAt ?? null,
    },
  });
}

export async function PATCH(request: NextRequest) {
  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return jsonError("invalid JSON body");
  }

  const { apiKey, ...settingsPatch } = body;

  if (Object.keys(settingsPatch).length > 0) {
    const current = (await getSettingValue<Record<string, unknown>>("llm")) ?? {};
    const merged = { ...current, ...settingsPatch };
    const errors = validateLlmSettings(merged);
    if (errors.length) return jsonError(errors.join("; "));
    await upsertSettingValue("llm", merged);
  }

  if (typeof apiKey === "string" && apiKey.trim()) {
    const trimmed = apiKey.trim();
    if (trimmed.length < 8) return jsonError("API key looks too short");
    await prisma.secret.upsert({
      where: { key: "anthropic_api_key" },
      // Re-read on every worker call (docs/02 §9) - rotating here needs no
      // restart. status resets to 'unknown' until the next real call
      // proves it one way or the other (docs/04 §1's 401 handling).
      update: { value: trimmed, last4: trimmed.slice(-4), status: "unknown", lastCheckedAt: null },
      create: { key: "anthropic_api_key", value: trimmed, last4: trimmed.slice(-4), status: "unknown" },
    });
  }

  const value = await getSettingValue<Record<string, unknown>>("llm");
  const secret = await prisma.secret.findUnique({ where: { key: "anthropic_api_key" } });
  return NextResponse.json({
    ...value,
    apiKey: {
      set: Boolean(secret),
      last4: secret?.last4 ?? null,
      status: secret?.status ?? "unknown",
      lastCheckedAt: secret?.lastCheckedAt ?? null,
    },
  });
}
