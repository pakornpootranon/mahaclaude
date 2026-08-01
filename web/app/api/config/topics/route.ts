import { NextRequest, NextResponse } from "next/server";
import { Prisma } from "@prisma/client";

import { jsonError } from "@/lib/api-helpers";
import { prisma } from "@/lib/prisma";

export const dynamic = "force-dynamic";

// GET /api/config/topics - full editor list (docs/05 §7: "Topics page:
// topic list -> drawer with ... mappings grid editor"). Distinct from
// /api/topics/board (the dashboard's fast-path view) - same tables, this
// one is the full CRUD surface.
export async function GET() {
  const topics = await prisma.topic.findMany({
    orderBy: { name: "asc" },
    include: { mappings: { orderBy: [{ market: "asc" }, { sector: "asc" }] } },
  });
  return NextResponse.json({ items: topics });
}

interface CreateTopicBody {
  name: string;
  description: string;
  keywords?: string[];
  sensitivity?: number;
  enabled?: boolean;
}

// POST /api/config/topics - create without mappings (the full editor adds
// mapping rows afterward via POST /api/config/topics/:id/mappings; the
// board's quick-add dialog is the one-shot path that also accepts
// mappings up front, see /api/topics/quick-add).
export async function POST(request: NextRequest) {
  let body: CreateTopicBody;
  try {
    body = await request.json();
  } catch {
    return jsonError("invalid JSON body");
  }
  if (!body.name?.trim()) return jsonError("name is required");
  if (!body.description?.trim()) return jsonError("description is required");
  const sensitivity = body.sensitivity ?? 0.7;
  if (sensitivity < 0 || sensitivity > 1) return jsonError("sensitivity must be between 0 and 1");

  try {
    const topic = await prisma.topic.create({
      data: {
        name: body.name.trim(),
        description: body.description.trim(),
        keywords: body.keywords ?? [],
        sensitivity: new Prisma.Decimal(sensitivity),
        enabled: body.enabled ?? true,
      },
    });
    return NextResponse.json(topic, { status: 201 });
  } catch (err) {
    if (err instanceof Prisma.PrismaClientKnownRequestError && err.code === "P2002") {
      return jsonError(`a topic named "${body.name}" already exists`, 409);
    }
    throw err;
  }
}
