import { NextRequest, NextResponse } from "next/server";

import { jsonError } from "@/lib/api-helpers";
import { getSettingValue, upsertSettingValue, validatePolymarketSettings } from "@/lib/settings";

export const dynamic = "force-dynamic";

// GET/PATCH /api/config/polymarket - settings['polymarket'] (docs/05 §3b, FR-V5).
export async function GET() {
  const value = await getSettingValue("polymarket");
  if (!value) return jsonError("settings['polymarket'] is not seeded", 500);
  return NextResponse.json(value);
}

export async function PATCH(request: NextRequest) {
  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return jsonError("invalid JSON body");
  }

  const current = (await getSettingValue<Record<string, unknown>>("polymarket")) ?? {};
  const merged = { ...current, ...body };
  const errors = validatePolymarketSettings(merged);
  if (errors.length) return jsonError(errors.join("; "));

  const saved = await upsertSettingValue("polymarket", merged);
  return NextResponse.json(saved);
}
