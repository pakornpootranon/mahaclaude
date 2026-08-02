import { prisma } from "@/lib/prisma";

// Shared masked-secret pattern (docs/02 §9 override, 2026-08-02): originally
// only the Claude API key (app/api/config/llm/route.ts) lived in the
// `secrets` table, with Finnhub/NewsAPI/MCP tokens env-only. That's now
// generalized to any connector credential - same table, same DB-wins /
// masked-display / never-exported rules, just keyed differently per secret.
export interface SecretStatus {
  set: boolean;
  last4: string | null;
}

export async function getSecretStatus(key: string): Promise<SecretStatus> {
  const row = await prisma.secret.findUnique({ where: { key } });
  return { set: Boolean(row), last4: row?.last4 ?? null };
}

export async function upsertSecret(key: string, value: string): Promise<SecretStatus> {
  const trimmed = value.trim();
  const row = await prisma.secret.upsert({
    where: { key },
    update: { value: trimmed, last4: trimmed.slice(-4), status: "unknown", lastCheckedAt: null },
    create: { key, value: trimmed, last4: trimmed.slice(-4), status: "unknown" },
  });
  return { set: true, last4: row.last4 };
}

export async function deleteSecret(key: string): Promise<void> {
  await prisma.secret.deleteMany({ where: { key } });
}

export const FINNHUB_SECRET_KEY = "finnhub_api_key";
export const NEWSAPI_SECRET_KEY = "newsapi_api_key";

// Mirrors worker/newswatch_worker/secrets.py's mcp_connector_secret_key -
// each MCP connector is a user-added row that can point at a different
// server, so its token is scoped per source id rather than shared.
export function mcpConnectorSecretKey(sourceId: string): string {
  return `mcp_connector_token:${sourceId}`;
}
