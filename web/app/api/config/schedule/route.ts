import { NextRequest, NextResponse } from "next/server";

import { jsonError } from "@/lib/api-helpers";
import { getSettingValue, upsertSettingValue, validateScheduleSettings } from "@/lib/settings";

export const dynamic = "force-dynamic";

// GET/PATCH /api/config/schedule - settings['schedule'] (docs/05 §2, FR-C5).
// Picked up without restart: scheduler.py polls updated_at every 60s
// (docs/02 §3) - Prisma's @updatedAt on the settings row is what makes
// that detectable, see schema.prisma's note on the Setting model.
export async function GET() {
  const value = await getSettingValue("schedule");
  if (!value) return jsonError("settings['schedule'] is not seeded", 500);
  return NextResponse.json(value);
}

export async function PATCH(request: NextRequest) {
  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return jsonError("invalid JSON body");
  }

  const current = (await getSettingValue<Record<string, unknown>>("schedule")) ?? {};
  const merged = { ...current, ...body };
  const errors = validateScheduleSettings(merged);
  if (errors.length) return jsonError(errors.join("; "));

  const saved = await upsertSettingValue("schedule", merged);
  return NextResponse.json(saved);
}
