import { prisma } from "@/lib/prisma";

export async function getSettingValue<T>(key: string): Promise<T | null> {
  const row = await prisma.setting.findUnique({ where: { key } });
  return row ? (row.value as unknown as T) : null;
}

export async function upsertSettingValue<T>(key: string, value: T): Promise<T> {
  const row = await prisma.setting.upsert({
    where: { key },
    update: { value: value as object },
    create: { key, value: value as object },
  });
  return row.value as unknown as T;
}

function inRange(n: unknown, min: number, max: number): n is number {
  return typeof n === "number" && Number.isFinite(n) && n >= min && n <= max;
}

// docs/05 §1
export function validateRulesSettings(value: Record<string, unknown>): string[] {
  const errors: string[] = [];
  if (!inRange(value.global_confidence_floor, 0, 1)) errors.push("global_confidence_floor must be 0-1");
  if (!inRange(value.global_magnitude_floor, 0, 1)) errors.push("global_magnitude_floor must be 0-1");
  if (!inRange(value.watch_floor, 0, 1)) errors.push("watch_floor must be 0-1");
  if (!inRange(value.unconfigured_magnitude_floor, 0, 1)) errors.push("unconfigured_magnitude_floor must be 0-1");
  if (!inRange(value.dedup_window_hours, 1, 336)) errors.push("dedup_window_hours must be 1-336");
  if (!inRange(value.max_recommendations_per_cycle, 1, 50)) errors.push("max_recommendations_per_cycle must be 1-50");
  if (!Array.isArray(value.quiet_tickers) || !value.quiet_tickers.every((t) => typeof t === "string")) {
    errors.push("quiet_tickers must be a string array");
  }
  const scope = value.sector_scope as { allowlist?: unknown; blocklist?: unknown } | undefined;
  if (
    !scope ||
    !Array.isArray(scope.allowlist) ||
    !Array.isArray(scope.blocklist) ||
    !scope.allowlist.every((s) => typeof s === "string") ||
    !scope.blocklist.every((s) => typeof s === "string")
  ) {
    errors.push("sector_scope.allowlist/blocklist must be string arrays");
  }
  return errors;
}

const TIME_RE = /^([01]\d|2[0-3]):([0-5]\d)$/;

// docs/05 §2
export function validateScheduleSettings(value: Record<string, unknown>): string[] {
  const errors: string[] = [];
  if (typeof value.timezone !== "string" || !value.timezone) errors.push("timezone is required");
  const cycles = value.cycles;
  if (!Array.isArray(cycles) || cycles.length < 1 || cycles.length > 6) {
    errors.push("cycles must have 1-6 entries");
    return errors;
  }
  const ids = new Set<string>();
  for (const c of cycles as Record<string, unknown>[]) {
    if (typeof c.id !== "string" || !c.id) {
      errors.push("each cycle needs a slug id");
      continue;
    }
    if (ids.has(c.id)) errors.push(`duplicate cycle id: ${c.id}`);
    ids.add(c.id);
    if (typeof c.time !== "string" || !TIME_RE.test(c.time)) errors.push(`cycle ${c.id}: time must be HH:MM (24h)`);
    if (typeof c.enabled !== "boolean") errors.push(`cycle ${c.id}: enabled must be a boolean`);
  }
  if (typeof value.outcomes_job_time !== "string" || !TIME_RE.test(value.outcomes_job_time as string)) {
    errors.push("outcomes_job_time must be HH:MM (24h)");
  }
  return errors;
}

const REASONING_LEVELS = ["off", "low", "medium", "high"];
const LLM_TIERS = ["triage", "analysis", "digest", "pm_estimate"];

// docs/05 §3. API key is intentionally NOT validated/read here - it lives
// in the secrets table (arch §9), never in this JSON.
export function validateLlmSettings(value: Record<string, unknown>): string[] {
  const errors: string[] = [];
  const availableModels = value.available_models;
  if (!Array.isArray(availableModels) || availableModels.length === 0 || !availableModels.every((m) => typeof m === "string")) {
    errors.push("available_models must be a non-empty string array");
  }
  const tiers = value.tiers as Record<string, { model?: unknown; reasoning?: unknown }> | undefined;
  if (!tiers) {
    errors.push("tiers is required");
  } else {
    for (const tierName of LLM_TIERS) {
      const tier = tiers[tierName];
      if (!tier || typeof tier.model !== "string" || !tier.model) {
        errors.push(`tiers.${tierName}.model is required`);
      } else if (Array.isArray(availableModels) && !availableModels.includes(tier.model)) {
        errors.push(`tiers.${tierName}.model must be one of available_models`);
      }
      if (!REASONING_LEVELS.includes(tier?.reasoning as string)) {
        errors.push(`tiers.${tierName}.reasoning must be one of ${REASONING_LEVELS.join("/")}`);
      }
    }
  }
  if (!inRange(value.max_items_per_cycle, 1, 10000)) errors.push("max_items_per_cycle must be a positive number");
  if (!inRange(value.monthly_budget_usd, 0, 100000)) errors.push("monthly_budget_usd must be >= 0");
  const prices = value.prices_per_mtok as Record<string, { input?: unknown; output?: unknown }> | undefined;
  if (!prices) {
    errors.push("prices_per_mtok is required");
  } else if (Array.isArray(availableModels)) {
    for (const model of availableModels as string[]) {
      const p = prices[model];
      if (!p || typeof p.input !== "number" || typeof p.output !== "number") {
        errors.push(`prices_per_mtok.${model} needs numeric input/output - every available model must be priced`);
      }
    }
  }
  return errors;
}

const SOURCE_TYPES = ["rss", "finnhub", "newsapi", "reddit_rss", "mcp"];

// docs/05 §4 - per source_type config shape. Kept permissive (existence +
// basic type checks, not full deep validation) since sources.config is
// deliberately free-form JSON per type.
export function validateSource(sourceType: unknown, config: unknown): string[] {
  const errors: string[] = [];
  if (typeof sourceType !== "string" || !SOURCE_TYPES.includes(sourceType)) {
    errors.push(`source_type must be one of ${SOURCE_TYPES.join("/")}`);
    return errors;
  }
  const c = (config ?? {}) as Record<string, unknown>;
  switch (sourceType) {
    case "rss":
      if (typeof c.url !== "string" || !c.url) errors.push("rss config needs a url");
      break;
    case "finnhub":
      if (typeof c.category !== "string" && typeof c.symbol !== "string") {
        errors.push("finnhub config needs category or symbol");
      }
      break;
    case "newsapi":
      if (typeof c.query !== "string" || !c.query) errors.push("newsapi config needs a query");
      break;
    case "reddit_rss":
      if (typeof c.subreddit !== "string" || !c.subreddit) errors.push("reddit_rss config needs a subreddit");
      break;
    case "mcp":
      if (typeof c.server_url !== "string" || !c.server_url) errors.push("mcp config needs a server_url");
      if (typeof c.tool_name !== "string" || !c.tool_name) errors.push("mcp config needs a tool_name");
      if (typeof c.result_mapping !== "object" || c.result_mapping === null) {
        errors.push("mcp config needs a result_mapping object");
      }
      break;
  }
  return errors;
}

// docs/05 §3b
export function validatePolymarketSettings(value: Record<string, unknown>): string[] {
  const errors: string[] = [];
  if (typeof value.enabled !== "boolean") errors.push("enabled must be a boolean");
  if (!inRange(value.scan_top_n, 1, 200)) errors.push("scan_top_n must be 1-200");
  if (!inRange(value.reestimate_hours, 1, 720)) errors.push("reestimate_hours must be positive");
  if (!inRange(value.min_edge_points, 0, 100)) errors.push("min_edge_points must be 0-100");
  if (!inRange(value.min_confidence, 0, 1)) errors.push("min_confidence must be 0-1");
  if (!inRange(value.min_liquidity_usd, 0, 10_000_000)) errors.push("min_liquidity_usd must be >= 0");
  if (!inRange(value.min_days_to_end, 0, 365)) errors.push("min_days_to_end must be >= 0");
  if (!inRange(value.price_floor, 0, 1)) errors.push("price_floor must be 0-1");
  if (!inRange(value.price_ceiling, 0, 1)) errors.push("price_ceiling must be 0-1");
  if (inRange(value.price_floor, 0, 1) && inRange(value.price_ceiling, 0, 1) && (value.price_floor as number) >= (value.price_ceiling as number)) {
    errors.push("price_floor must be less than price_ceiling");
  }
  if (!inRange(value.dedup_window_hours, 1, 720)) errors.push("dedup_window_hours must be positive");
  if (!inRange(value.max_opportunities_per_cycle, 1, 50)) errors.push("max_opportunities_per_cycle must be 1-50");
  if (!Array.isArray(value.categories) || !value.categories.every((c) => typeof c === "string")) {
    errors.push("categories must be a string array");
  }
  return errors;
}
