import { NextRequest, NextResponse } from "next/server";
import { Prisma } from "@prisma/client";

import { prisma } from "@/lib/prisma";
import { jsonError } from "@/lib/api-helpers";

interface PatchBody {
  enabled?: boolean;
  tickers?: string[];
  sector?: string;
  market?: string;
  polarity?: number;
  note?: string | null;
}

// PATCH /api/mappings/:id - inline per-mapping enable toggle + edit
// (FR-V3b). Most callers only send { enabled }.
export async function PATCH(request: NextRequest, { params }: { params: { id: string } }) {
  let body: PatchBody;
  try {
    body = await request.json();
  } catch {
    return jsonError("invalid JSON body");
  }

  if (body.market && !["US", "TH", "GLOBAL"].includes(body.market)) {
    return jsonError(`invalid market: ${body.market}`);
  }
  if (body.polarity !== undefined && ![1, -1].includes(body.polarity)) {
    return jsonError("polarity must be 1 or -1");
  }

  const data: Prisma.MappingUpdateInput = {};
  if (body.enabled !== undefined) data.enabled = body.enabled;
  if (body.tickers !== undefined) data.tickers = body.tickers;
  if (body.sector !== undefined) data.sector = body.sector;
  if (body.market !== undefined) data.market = body.market;
  if (body.polarity !== undefined) data.polarity = body.polarity;
  if (body.note !== undefined) data.note = body.note;

  try {
    const mapping = await prisma.mapping.update({ where: { id: params.id }, data });
    return NextResponse.json(mapping);
  } catch (err) {
    if (err instanceof Prisma.PrismaClientKnownRequestError && err.code === "P2025") {
      return jsonError("mapping not found", 404);
    }
    throw err;
  }
}

// DELETE /api/mappings/:id - the Topics editor's per-row remove action
// (docs/05 §7). Unlike disabling, this actually removes the row.
export async function DELETE(_request: NextRequest, { params }: { params: { id: string } }) {
  try {
    await prisma.mapping.delete({ where: { id: params.id } });
    return NextResponse.json({ deleted: true });
  } catch (err) {
    if (err instanceof Prisma.PrismaClientKnownRequestError && err.code === "P2025") {
      return jsonError("mapping not found", 404);
    }
    throw err;
  }
}
