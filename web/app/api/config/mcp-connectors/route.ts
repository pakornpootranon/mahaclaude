import { NextRequest, NextResponse } from "next/server";
import { Prisma } from "@prisma/client";

import { jsonError } from "@/lib/api-helpers";
import { prisma } from "@/lib/prisma";
import { validateSource } from "@/lib/settings";

export const dynamic = "force-dynamic";

// GET/POST /api/config/mcp-connectors - FR-C8: "filtered view of
// source_type='mcp' sources". Same table, same validation as
// /api/config/sources, just scoped to source_type='mcp' so the page can
// have connector-specific fields without a parallel CRUD surface.
export async function GET() {
  const items = await prisma.source.findMany({ where: { sourceType: "mcp" }, orderBy: { name: "asc" } });
  return NextResponse.json({
    items: items.map((s) => {
      const authEnvVar = (s.config as { auth_env_var?: string }).auth_env_var;
      return {
        ...s,
        // Presence only - the value itself never leaves the process
        // (docs/02 §9, docs/05 §7's "env-var set/unset indicator").
        authEnvVarSet: authEnvVar ? Boolean(process.env[authEnvVar]) : null,
      };
    }),
  });
}

interface CreateConnectorBody {
  name: string;
  config: Record<string, unknown>;
  enabled?: boolean;
}

export async function POST(request: NextRequest) {
  let body: CreateConnectorBody;
  try {
    body = await request.json();
  } catch {
    return jsonError("invalid JSON body");
  }
  if (!body.name?.trim()) return jsonError("name is required");

  const errors = validateSource("mcp", body.config);
  if (errors.length) return jsonError(errors.join("; "));

  try {
    const source = await prisma.source.create({
      data: {
        name: body.name.trim(),
        sourceType: "mcp",
        config: body.config as Prisma.InputJsonValue,
        enabled: body.enabled ?? false,
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
