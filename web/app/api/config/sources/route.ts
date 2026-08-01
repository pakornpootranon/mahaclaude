import { NextRequest, NextResponse } from "next/server";
import { Prisma } from "@prisma/client";

import { jsonError } from "@/lib/api-helpers";
import { prisma } from "@/lib/prisma";
import { validateSource } from "@/lib/settings";

export const dynamic = "force-dynamic";

// GET /api/config/sources?type= - sources list (FR-C1). `?type=mcp` is what
// /api/config/mcp-connectors delegates to (FR-C8: "filtered view of
// source_type='mcp' sources").
export async function GET(request: NextRequest) {
  const type = request.nextUrl.searchParams.get("type");
  const sources = await prisma.source.findMany({
    where: type ? { sourceType: type } : undefined,
    orderBy: { name: "asc" },
  });
  return NextResponse.json({ items: sources });
}

interface CreateSourceBody {
  name: string;
  sourceType: string;
  config: Record<string, unknown>;
  enabled?: boolean;
  pollOverrideMinutes?: number | null;
  language?: string;
}

// POST /api/config/sources - create (FR-C1).
export async function POST(request: NextRequest) {
  let body: CreateSourceBody;
  try {
    body = await request.json();
  } catch {
    return jsonError("invalid JSON body");
  }
  if (!body.name?.trim()) return jsonError("name is required");

  const errors = validateSource(body.sourceType, body.config);
  if (errors.length) return jsonError(errors.join("; "));

  try {
    const source = await prisma.source.create({
      data: {
        name: body.name.trim(),
        sourceType: body.sourceType,
        config: body.config as Prisma.InputJsonValue,
        enabled: body.enabled ?? true,
        pollOverrideMinutes: body.pollOverrideMinutes ?? null,
        language: body.language ?? "en",
      },
    });
    return NextResponse.json(source, { status: 201 });
  } catch (err) {
    if (err instanceof Prisma.PrismaClientKnownRequestError && err.code === "P2002") {
      return jsonError(`a source named "${body.name}" already exists`, 409);
    }
    throw err;
  }
}
