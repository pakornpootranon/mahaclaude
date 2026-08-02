import { NextRequest, NextResponse } from "next/server";
import { Prisma } from "@prisma/client";

import { jsonError } from "@/lib/api-helpers";
import { prisma } from "@/lib/prisma";
import { getSecretStatus, mcpConnectorSecretKey, upsertSecret } from "@/lib/secrets";
import { validateSource } from "@/lib/settings";

export const dynamic = "force-dynamic";

// GET/POST /api/config/mcp-connectors - FR-C8: "filtered view of
// source_type='mcp' sources". Same table, same validation as
// /api/config/sources, just scoped to source_type='mcp' so the page can
// have connector-specific fields without a parallel CRUD surface.
//
// authToken (docs/02 §9 override, 2026-08-02): each connector's token is
// now also settable via this UI, stored in the shared `secrets` table keyed
// per source id (mcpConnectorSecretKey) - DB value wins over the
// `auth_env_var` env fallback, same pattern as the Claude key. `config.
// auth_env_var` is kept as the fallback path for anyone who prefers .env.
export async function GET() {
  const items = await prisma.source.findMany({ where: { sourceType: "mcp" }, orderBy: { name: "asc" } });
  const withStatus = await Promise.all(
    items.map(async (s) => {
      const authEnvVar = (s.config as { auth_env_var?: string }).auth_env_var;
      const tokenStatus = await getSecretStatus(mcpConnectorSecretKey(s.id));
      return {
        ...s,
        authTokenSet: tokenStatus.set,
        authTokenLast4: tokenStatus.last4,
        // Presence only - the value itself never leaves the process
        // (docs/02 §9, docs/05 §7's "env-var set/unset indicator").
        authEnvVarSet: authEnvVar ? Boolean(process.env[authEnvVar]) : null,
      };
    })
  );
  return NextResponse.json({ items: withStatus });
}

interface CreateConnectorBody {
  name: string;
  config: Record<string, unknown>;
  enabled?: boolean;
  authToken?: string;
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
    if (body.authToken?.trim()) {
      await upsertSecret(mcpConnectorSecretKey(source.id), body.authToken);
    }
    return NextResponse.json(source, { status: 201 });
  } catch (err) {
    if (err instanceof Prisma.PrismaClientKnownRequestError && err.code === "P2002") {
      return jsonError(`a source named "${body.name}" already exists`, 409);
    }
    throw err;
  }
}
