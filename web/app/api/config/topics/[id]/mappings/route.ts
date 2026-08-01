import { NextRequest, NextResponse } from "next/server";
import { Prisma } from "@prisma/client";

import { jsonError } from "@/lib/api-helpers";
import { prisma } from "@/lib/prisma";

interface CreateMappingBody {
  market: string;
  sector: string;
  tickers?: string[];
  polarity: number;
  note?: string;
  enabled?: boolean;
  suggestedBy?: "user" | "llm";
}

// POST /api/config/topics/:id/mappings - add a mapping row to an existing
// topic (docs/05 §7's "mappings grid editor: add row"). Tickers are
// uppercased per the spec's "tag-input uppercased" field description.
export async function POST(request: NextRequest, { params }: { params: { id: string } }) {
  let body: CreateMappingBody;
  try {
    body = await request.json();
  } catch {
    return jsonError("invalid JSON body");
  }
  if (!["US", "TH", "GLOBAL"].includes(body.market)) return jsonError(`invalid market: ${body.market}`);
  if (!body.sector?.trim()) return jsonError("sector is required");
  if (![1, -1].includes(body.polarity)) return jsonError("polarity must be 1 or -1");

  const topic = await prisma.topic.findUnique({ where: { id: params.id } });
  if (!topic) return jsonError("topic not found", 404);

  try {
    const mapping = await prisma.mapping.create({
      data: {
        topicId: params.id,
        market: body.market,
        sector: body.sector.trim(),
        tickers: (body.tickers ?? []).map((t) => t.toUpperCase()),
        polarity: body.polarity,
        note: body.note ?? null,
        enabled: body.enabled ?? true,
        suggestedBy: body.suggestedBy ?? "user",
      },
    });
    return NextResponse.json(mapping, { status: 201 });
  } catch (err) {
    if (err instanceof Prisma.PrismaClientKnownRequestError && err.code === "P2002") {
      return jsonError("a mapping row for this topic/market/sector already exists", 409);
    }
    throw err;
  }
}
