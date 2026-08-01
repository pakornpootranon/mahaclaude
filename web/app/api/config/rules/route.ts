import { NextRequest, NextResponse } from "next/server";

import { jsonError } from "@/lib/api-helpers";
import { getSettingValue, upsertSettingValue, validateRulesSettings } from "@/lib/settings";

export const dynamic = "force-dynamic";

// GET/PATCH /api/config/rules - settings['rules'] (docs/05 §1, FR-C4).
export async function GET() {
  const value = await getSettingValue("rules");
  if (!value) return jsonError("settings['rules'] is not seeded", 500);
  return NextResponse.json(value);
}

export async function PATCH(request: NextRequest) {
  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return jsonError("invalid JSON body");
  }

  const current = (await getSettingValue<Record<string, unknown>>("rules")) ?? {};
  const merged = { ...current, ...body };
  const errors = validateRulesSettings(merged);
  if (errors.length) return jsonError(errors.join("; "));

  const saved = await upsertSettingValue("rules", merged);
  return NextResponse.json(saved);
}
