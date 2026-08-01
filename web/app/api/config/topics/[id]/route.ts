import { NextRequest, NextResponse } from "next/server";
import { Prisma } from "@prisma/client";

import { jsonError } from "@/lib/api-helpers";
import { prisma } from "@/lib/prisma";

export async function GET(_request: NextRequest, { params }: { params: { id: string } }) {
  const topic = await prisma.topic.findUnique({
    where: { id: params.id },
    include: { mappings: { orderBy: [{ market: "asc" }, { sector: "asc" }] } },
  });
  if (!topic) return jsonError("topic not found", 404);
  return NextResponse.json(topic);
}

interface PatchTopicBody {
  name?: string;
  description?: string;
  keywords?: string[];
  sensitivity?: number;
  enabled?: boolean;
}

export async function PATCH(request: NextRequest, { params }: { params: { id: string } }) {
  let body: PatchTopicBody;
  try {
    body = await request.json();
  } catch {
    return jsonError("invalid JSON body");
  }
  if (body.sensitivity !== undefined && (body.sensitivity < 0 || body.sensitivity > 1)) {
    return jsonError("sensitivity must be between 0 and 1");
  }

  const data: Prisma.TopicUpdateInput = {};
  if (body.name !== undefined) data.name = body.name.trim();
  if (body.description !== undefined) data.description = body.description.trim();
  if (body.keywords !== undefined) data.keywords = body.keywords;
  if (body.sensitivity !== undefined) data.sensitivity = new Prisma.Decimal(body.sensitivity);
  if (body.enabled !== undefined) data.enabled = body.enabled;

  try {
    const topic = await prisma.topic.update({ where: { id: params.id }, data });
    return NextResponse.json(topic);
  } catch (err) {
    if (err instanceof Prisma.PrismaClientKnownRequestError) {
      if (err.code === "P2025") return jsonError("topic not found", 404);
      if (err.code === "P2002") return jsonError("a topic with that name already exists", 409);
    }
    throw err;
  }
}

// DELETE /api/config/topics/:id - cascades mappings; historical
// recommendations/analysis_topics referencing this topic are SET NULL, not
// deleted (docs/03's FK actions) - past provenance survives, just loses the
// topic label. The UI puts this behind a second confirm (docs/05 §7).
export async function DELETE(_request: NextRequest, { params }: { params: { id: string } }) {
  try {
    await prisma.topic.delete({ where: { id: params.id } });
    return NextResponse.json({ deleted: true });
  } catch (err) {
    if (err instanceof Prisma.PrismaClientKnownRequestError && err.code === "P2025") {
      return jsonError("topic not found", 404);
    }
    throw err;
  }
}
