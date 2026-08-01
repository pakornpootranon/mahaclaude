// docs/04-llm-pipeline.md §11 (suggest-mappings-v1). Spec gives the output
// shape and inputs but not a verbatim system prompt (unlike triage/analyze/
// pm-estimate) - authored here to match the described behavior.

import { callStructuredJson } from "@/lib/llm/client";

export const PROMPT_VERSION = "suggest-mappings-v1";

// Same block as worker/newswatch_worker/llm/watch_context.py's
// MARKETS_IN_SCOPE - kept in sync by hand since this is TypeScript and that
// is Python; docs/04 §2 defines it once for both.
const MARKETS_IN_SCOPE =
  '## Markets in scope\nUS (NYSE/NASDAQ, sector ETFs), TH (SET/mai, ".BK" tickers), GLOBAL (map to US/TH tradable proxies).';

const SYSTEM_PROMPT = `You are helping a user configure sector/ticker mappings for a new watch topic on a personal financial news-monitoring dashboard (NOT financial advice; nothing is executed automatically).

Given the draft topic below, propose up to 10 mapping rows: which (market, sector) pairs this topic's news would plausibly move, with a short list of liquid, well-known tickers per row (index ETFs or large-caps only), and the polarity (+1 or -1) of what counts as a "positive framing" event for that topic on that sector. Use the '.BK' suffix for Thai SET-listed tickers. These rows are suggestions only - the user will review, edit, and accept or reject each one individually before anything is saved.

Coverage requirement: across all US rows combined, include at least 5 distinct US tickers; across all TH rows combined, include at least 5 distinct TH ('.BK') tickers. If the topic's direct impact on one market is thin, broaden to the closest plausible correlated sectors (e.g. regional proxies, supply-chain-linked names, sector ETFs) to reach 5 - stay grounded in a real, explainable mechanism per ticker (state it in that row's note) rather than padding with irrelevant names. Only fall short of 5 in a market if you genuinely cannot name 5 plausibly-linked liquid tickers there, and say why in that row's note.

Output JSON only.

${MARKETS_IN_SCOPE}`;

const SCHEMA = {
  type: "object",
  properties: {
    mappings: {
      // Note: Claude's structured-output json_schema validation rejects
      // "maxItems" on array types (400 "property 'maxItems' is not
      // supported") - the row-count cap lives in the prompt text instead.
      type: "array",
      items: {
        type: "object",
        properties: {
          market: { type: "string", enum: ["US", "TH", "GLOBAL"] },
          sector: { type: "string" },
          tickers: { type: "array", items: { type: "string" } },
          polarity: { type: "integer", enum: [1, -1] },
          note: { type: "string" },
        },
        required: ["market", "sector", "tickers", "polarity", "note"],
        additionalProperties: false,
      },
    },
  },
  required: ["mappings"],
  additionalProperties: false,
};

export interface SuggestedMapping {
  market: "US" | "TH" | "GLOBAL";
  sector: string;
  tickers: string[];
  polarity: 1 | -1;
  note: string;
}

export async function suggestMappings(params: {
  name: string;
  description: string;
  keywords: string[];
  model: string;
}): Promise<SuggestedMapping[] | null> {
  const userContent = [
    "## Draft topic",
    `name: ${params.name}`,
    `description: ${params.description}`,
    `keywords: ${params.keywords.join(", ") || "(none)"}`,
  ].join("\n");

  const result = await callStructuredJson<{ mappings: SuggestedMapping[] }>({
    purpose: "suggest_mappings",
    model: params.model,
    system: SYSTEM_PROMPT,
    userContent,
    schema: SCHEMA,
    maxTokens: 2048,
  });

  return result ? result.mappings : null;
}
