import { NextRequest, NextResponse } from "next/server";

import { getLlmSettings, BudgetExceededError, UnknownModelPriceError } from "@/lib/llm/client";
import { suggestMappings } from "@/lib/llm/suggest-mappings";
import { jsonError } from "@/lib/api-helpers";

interface SuggestMappingsBody {
  name: string;
  description: string;
  keywords?: string[];
}

// POST /api/topics/suggest-mappings - the one web-triggered LLM call
// (docs/04 §11). Returns proposed mapping rows; applies nothing. The board
// quick-add dialog renders these as editable, individually-checked rows -
// only what the user accepts gets sent on to /api/topics/quick-add.
export async function POST(request: NextRequest) {
  let body: SuggestMappingsBody;
  try {
    body = await request.json();
  } catch {
    return jsonError("invalid JSON body");
  }
  if (!body.name?.trim()) return jsonError("name is required");
  if (!body.description?.trim()) return jsonError("description is required");

  try {
    const llmSettings = await getLlmSettings();
    // §11 doesn't route this ad-hoc call through settings['llm'].tiers (that
    // config is for the worker's 4 pipeline tiers) - reusing the analysis
    // tier's model is the closest fit for a reasoning-ish, one-off task.
    const model = llmSettings.tiers.analysis?.model ?? llmSettings.available_models[0];
    if (!model) return jsonError("no model configured", 500);

    const mappings = await suggestMappings({
      name: body.name.trim(),
      description: body.description.trim(),
      keywords: body.keywords ?? [],
      model,
    });

    if (mappings === null) {
      return jsonError("the model did not return valid mapping suggestions; try again or add mappings manually", 502);
    }

    return NextResponse.json({ mappings });
  } catch (err) {
    if (err instanceof BudgetExceededError) {
      return jsonError(`monthly LLM budget reached: ${err.message}`, 429);
    }
    if (err instanceof UnknownModelPriceError) {
      return jsonError(err.message, 500);
    }
    // Covers "no Anthropic API key configured" and any other unexpected
    // failure - the dialog's Suggest-mappings button should show a message
    // and let the user fall back to manual rows, not crash on a raw 500.
    const message = err instanceof Error ? err.message : "failed to get mapping suggestions";
    return jsonError(message, 502);
  }
}
