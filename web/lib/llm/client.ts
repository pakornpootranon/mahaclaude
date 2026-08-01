// TypeScript mirror of worker/newswatch_worker/llm/client.py's budget guard
// and spend ledger, scoped to the one LLM call the web app makes directly
// (docs/04-llm-pipeline.md §11: POST /api/topics/suggest-mappings). Not a
// full pipeline client — no reasoning-tier/thinking config, since §11
// doesn't route this call through settings['llm'].tiers like the worker's
// four pipeline tiers.

import Anthropic from "@anthropic-ai/sdk";

import { prisma } from "@/lib/prisma";

export class BudgetExceededError extends Error {}
export class UnknownModelPriceError extends Error {}

export interface LlmSettings {
  available_models: string[];
  tiers: Record<string, { model: string; reasoning: string }>;
  max_items_per_cycle: number;
  monthly_budget_usd: number;
  prices_per_mtok: Record<string, { input: number; output: number }>;
}

export async function getLlmSettings(): Promise<LlmSettings> {
  const row = await prisma.setting.findUnique({ where: { key: "llm" } });
  if (!row) throw new Error("settings['llm'] is not seeded");
  return row.value as unknown as LlmSettings;
}

export async function resolveApiKey(): Promise<string | null> {
  const secret = await prisma.secret.findUnique({ where: { key: "anthropic_api_key" } });
  if (secret?.value) return secret.value;
  return process.env.ANTHROPIC_API_KEY ?? null;
}

export async function monthToDateSpend(): Promise<number> {
  const rows = await prisma.$queryRaw<{ spend_usd: unknown }[]>`SELECT spend_usd FROM spend_mtd_v`;
  return rows[0] ? Number(rows[0].spend_usd) : 0;
}

export async function checkBudget(llmSettings: LlmSettings): Promise<void> {
  const spend = await monthToDateSpend();
  if (spend >= llmSettings.monthly_budget_usd) {
    throw new BudgetExceededError(
      `month-to-date spend $${spend.toFixed(2)} >= cap $${llmSettings.monthly_budget_usd.toFixed(2)}`
    );
  }
}

export function priceForModel(llmSettings: LlmSettings, model: string) {
  const price = llmSettings.prices_per_mtok[model];
  if (!price) {
    throw new UnknownModelPriceError(`model ${model} has no prices_per_mtok entry; refusing call (fail closed)`);
  }
  return price;
}

export function computeCost(price: { input: number; output: number }, inputTokens: number, outputTokens: number) {
  return (inputTokens / 1_000_000) * price.input + (outputTokens / 1_000_000) * price.output;
}

export async function recordSpend(params: {
  cycleId: string | null;
  purpose: string;
  model: string;
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
}) {
  await prisma.llmCall.create({
    data: {
      cycleId: params.cycleId,
      purpose: params.purpose,
      model: params.model,
      inputTokens: params.inputTokens,
      outputTokens: params.outputTokens,
      costUsd: params.costUsd,
    },
  });
}

function responseText(message: Anthropic.Message): string {
  return message.content
    .filter((block): block is Anthropic.TextBlock => block.type === "text")
    .map((block) => block.text)
    .join("");
}

/**
 * Budget-checked structured call with one repair retry (docs/04 §8's
 * pattern, applied here too). Returns null (never throws for a bad
 * response) when both the primary call and the repair retry fail to
 * produce valid JSON. Throws BudgetExceededError / UnknownModelPriceError
 * before any network call.
 */
export async function callStructuredJson<T>(params: {
  purpose: string;
  model: string;
  system: string;
  userContent: string;
  schema: Record<string, unknown>;
  maxTokens?: number;
}): Promise<T | null> {
  const llmSettings = await getLlmSettings();
  await checkBudget(llmSettings);
  const price = priceForModel(llmSettings, params.model);

  const apiKey = await resolveApiKey();
  if (!apiKey) {
    throw new Error("no Anthropic API key configured (secrets table or ANTHROPIC_API_KEY)");
  }
  const client = new Anthropic({ apiKey });

  const messages: Anthropic.MessageParam[] = [{ role: "user", content: params.userContent }];

  const callOnce = async (): Promise<{ message: Anthropic.Message; text: string }> => {
    const message = await client.messages.create({
      model: params.model,
      max_tokens: params.maxTokens ?? 1024,
      system: params.system,
      output_config: { format: { type: "json_schema", schema: params.schema } },
      messages,
    });
    const cost = computeCost(price, message.usage.input_tokens, message.usage.output_tokens);
    await recordSpend({
      cycleId: null,
      purpose: params.purpose,
      model: params.model,
      inputTokens: message.usage.input_tokens,
      outputTokens: message.usage.output_tokens,
      costUsd: cost,
    });
    return { message, text: responseText(message) };
  };

  const first = await callOnce();
  try {
    return JSON.parse(first.text) as T;
  } catch (err) {
    messages.push({ role: "assistant", content: first.text });
    messages.push({
      role: "user",
      content: `Your last output was invalid JSON: ${(err as Error).message}. Re-emit valid JSON only.`,
    });
    try {
      await checkBudget(llmSettings);
    } catch {
      return null;
    }
    const repaired = await callOnce();
    try {
      return JSON.parse(repaired.text) as T;
    } catch {
      return null;
    }
  }
}
