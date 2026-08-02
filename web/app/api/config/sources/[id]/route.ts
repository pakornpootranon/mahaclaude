import { NextRequest, NextResponse } from "next/server";
import { Prisma } from "@prisma/client";

import { jsonError } from "@/lib/api-helpers";
import { prisma } from "@/lib/prisma";
import { deleteSecret, mcpConnectorSecretKey, upsertSecret } from "@/lib/secrets";
import { validateSource } from "@/lib/settings";

interface PatchSourceBody {
  name?: string;
  sourceType?: string;
  config?: Record<string, unknown>;
  enabled?: boolean;
  pollOverrideMinutes?: number | null;
  language?: string;
  authToken?: string;
}

// PATCH /api/config/sources/:id (FR-C1). `authToken` (docs/02 §9 override,
// 2026-08-02): only meaningful for source_type='mcp' rows - rotates that
// connector's DB-stored credential (lib/secrets.ts's mcpConnectorSecretKey),
// mirroring the Claude key's rotate flow. Harmless no-op for other types.
export async function PATCH(request: NextRequest, { params }: { params: { id: string } }) {
  let body: PatchSourceBody;
  try {
    body = await request.json();
  } catch {
    return jsonError("invalid JSON body");
  }

  if (body.sourceType || body.config) {
    const existing = await prisma.source.findUnique({ where: { id: params.id } });
    if (!existing) return jsonError("source not found", 404);
    const errors = validateSource(body.sourceType ?? existing.sourceType, body.config ?? existing.config);
    if (errors.length) return jsonError(errors.join("; "));
  }

  const data: Prisma.SourceUpdateInput = {};
  if (body.name !== undefined) data.name = body.name.trim();
  if (body.sourceType !== undefined) data.sourceType = body.sourceType;
  if (body.config !== undefined) data.config = body.config as Prisma.InputJsonValue;
  if (body.enabled !== undefined) data.enabled = body.enabled;
  if (body.pollOverrideMinutes !== undefined) data.pollOverrideMinutes = body.pollOverrideMinutes;
  if (body.language !== undefined) data.language = body.language;

  if (body.authToken?.trim()) {
    await upsertSecret(mcpConnectorSecretKey(params.id), body.authToken);
  }

  try {
    const source = await prisma.source.update({ where: { id: params.id }, data });
    return NextResponse.json(source);
  } catch (err) {
    if (err instanceof Prisma.PrismaClientKnownRequestError) {
      if (err.code === "P2025") return jsonError("source not found", 404);
      if (err.code === "P2002") return jsonError("a source with that name already exists", 409);
    }
    throw err;
  }
}

// DELETE /api/config/sources/:id - RESTRICT at the DB level (news_items.source_id):
// a source with ingested items can't be deleted, only disabled ("danger-free",
// docs/05 §7 - "topics/sources are disabled, not deleted, by default").
export async function DELETE(_request: NextRequest, { params }: { params: { id: string } }) {
  try {
    await prisma.source.delete({ where: { id: params.id } });
    await deleteSecret(mcpConnectorSecretKey(params.id));
    return NextResponse.json({ deleted: true });
  } catch (err) {
    if (err instanceof Prisma.PrismaClientKnownRequestError) {
      if (err.code === "P2025") return jsonError("source not found", 404);
      if (err.code === "P2003") {
        return jsonError("this source has ingested news items and can't be deleted - disable it instead", 409);
      }
    }
    throw err;
  }
}
