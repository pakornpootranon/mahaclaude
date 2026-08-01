import { NextRequest, NextResponse } from "next/server";
import { Prisma } from "@prisma/client";

import { prisma } from "@/lib/prisma";
import { jsonError } from "@/lib/api-helpers";

interface QuickAddMapping {
  market: string;
  sector: string;
  tickers?: string[];
  polarity: number;
  note?: string;
  suggestedBy?: "user" | "llm";
}

interface QuickAddBody {
  name: string;
  description: string;
  keywords?: string[];
  sensitivity?: number;
  mappings?: QuickAddMapping[];
}

// POST /api/topics/quick-add - board quick-add dialog (FR-V3a): creates the
// topic and any user-accepted mapping rows (LLM-suggested or hand-entered)
// in one call. Suggested rows are NEVER auto-applied - only rows the
// caller includes here (i.e. the user checked "accept") are saved.
export async function POST(request: NextRequest) {
  let body: QuickAddBody;
  try {
    body = await request.json();
  } catch {
    return jsonError("invalid JSON body");
  }

  if (!body.name?.trim()) return jsonError("name is required");
  if (!body.description?.trim()) return jsonError("description is required");
  const sensitivity = body.sensitivity ?? 0.7;
  if (sensitivity < 0 || sensitivity > 1) return jsonError("sensitivity must be between 0 and 1");

  for (const m of body.mappings ?? []) {
    if (!["US", "TH", "GLOBAL"].includes(m.market)) return jsonError(`invalid market: ${m.market}`);
    if (!m.sector?.trim()) return jsonError("mapping sector is required");
    if (![1, -1].includes(m.polarity)) return jsonError("mapping polarity must be 1 or -1");
  }

  try {
    const topic = await prisma.topic.create({
      data: {
        name: body.name.trim(),
        description: body.description.trim(),
        keywords: body.keywords ?? [],
        sensitivity: new Prisma.Decimal(sensitivity),
        mappings: {
          create: (body.mappings ?? []).map((m) => ({
            market: m.market,
            sector: m.sector.trim(),
            tickers: m.tickers ?? [],
            polarity: m.polarity,
            note: m.note ?? null,
            suggestedBy: m.suggestedBy ?? "user",
          })),
        },
      },
      include: { mappings: true },
    });
    return NextResponse.json(topic, { status: 201 });
  } catch (err) {
    if (err instanceof Prisma.PrismaClientKnownRequestError && err.code === "P2002") {
      return jsonError(`a topic named "${body.name}" already exists`, 409);
    }
    throw err;
  }
}
