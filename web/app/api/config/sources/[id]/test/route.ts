import { NextRequest, NextResponse } from "next/server";

import { jsonError } from "@/lib/api-helpers";
import { prisma } from "@/lib/prisma";

const POLL_INTERVAL_MS = 400;
const POLL_TIMEOUT_MS = 10_000;

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// POST /api/config/sources/:id/test - async test-fetch handshake (docs/02
// §6, arch §6 note: "web inserts request row, polls result <=10s"). Actual
// execution happens in the worker (scheduler.py polls source_tests every
// 15s, or `newswatch process-source-tests` run manually) - this route only
// enqueues and waits; if nothing picks it up within the poll window it
// returns 202 "still processing" rather than blocking forever.
export async function POST(_request: NextRequest, { params }: { params: { id: string } }) {
  const source = await prisma.source.findUnique({ where: { id: params.id } });
  if (!source) return jsonError("source not found", 404);

  const test = await prisma.sourceTest.create({ data: { sourceId: params.id } });

  const deadline = Date.now() + POLL_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const current = await prisma.sourceTest.findUnique({ where: { id: test.id } });
    if (current && current.status !== "requested") {
      return NextResponse.json({
        testId: current.id,
        status: current.status,
        result: current.result,
        completedAt: current.completedAt,
      });
    }
    await sleep(POLL_INTERVAL_MS);
  }

  return NextResponse.json(
    {
      testId: test.id,
      status: "requested",
      message: "Still processing - no worker has picked this up yet. Check back, or run `newswatch process-source-tests`.",
    },
    { status: 202 }
  );
}
