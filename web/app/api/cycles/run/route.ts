import { NextResponse } from "next/server";

import { prisma } from "@/lib/prisma";

// POST /api/cycles/run - "Run cycle now" (FR-S1). Per docs/03 §2.2,
// requested_manual is "web sets true; worker picks up" - this route only
// inserts (or reuses) the cycle row; a running worker (the APScheduler loop,
// Phase 5) or a manual `newswatch run-cycle` invocation is what actually
// walks it through the state machine, via cycle.py's existing
// _find_resumable_cycle (any cycle not in DONE/FAILED).
export async function POST() {
  const inProgress = await prisma.cycle.findFirst({
    where: { state: { notIn: ["DONE", "FAILED"] } },
    orderBy: { scheduledFor: "desc" },
  });

  if (inProgress) {
    return NextResponse.json({
      cycleId: inProgress.id,
      state: inProgress.state,
      created: false,
      message: "A cycle is already in progress; it will pick up any pending manual request too.",
    });
  }

  const cycle = await prisma.cycle.create({
    data: {
      scheduledFor: new Date(),
      kind: "manual",
      requestedManual: true,
      state: "PENDING",
      stats: {},
    },
  });

  return NextResponse.json({
    cycleId: cycle.id,
    state: cycle.state,
    created: true,
    message: "Cycle requested. It runs the next time the worker picks up pending manual requests.",
  });
}
