import { NextRequest, NextResponse } from "next/server";

import { jsonError } from "@/lib/api-helpers";
import { FINNHUB_SECRET_KEY, NEWSAPI_SECRET_KEY, getSecretStatus, upsertSecret } from "@/lib/secrets";

export const dynamic = "force-dynamic";

// GET/PATCH /api/config/connector-keys - provider-level API keys shared by
// every source row of that type (Finnhub, NewsAPI). Same masked-secret
// pattern as /api/config/llm's Claude key (docs/02 §9 override): PATCH is
// write-only, GET/response never echo the value back, only {set, last4}.
// MCP connector tokens are per-connector, not provider-level - those live
// on /api/config/mcp-connectors and /api/config/sources/:id instead.
export async function GET() {
  const [finnhub, newsapi] = await Promise.all([
    getSecretStatus(FINNHUB_SECRET_KEY),
    getSecretStatus(NEWSAPI_SECRET_KEY),
  ]);
  return NextResponse.json({ finnhub, newsapi });
}

interface PatchBody {
  finnhub?: string;
  newsapi?: string;
}

export async function PATCH(request: NextRequest) {
  let body: PatchBody;
  try {
    body = await request.json();
  } catch {
    return jsonError("invalid JSON body");
  }

  if (typeof body.finnhub === "string" && body.finnhub.trim()) {
    await upsertSecret(FINNHUB_SECRET_KEY, body.finnhub);
  }
  if (typeof body.newsapi === "string" && body.newsapi.trim()) {
    await upsertSecret(NEWSAPI_SECRET_KEY, body.newsapi);
  }

  const [finnhub, newsapi] = await Promise.all([
    getSecretStatus(FINNHUB_SECRET_KEY),
    getSecretStatus(NEWSAPI_SECRET_KEY),
  ]);
  return NextResponse.json({ finnhub, newsapi });
}
