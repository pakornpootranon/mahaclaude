import { describe, expect, it } from "vitest";

import {
  validateLlmSettings,
  validatePolymarketSettings,
  validateRulesSettings,
  validateScheduleSettings,
  validateSource,
} from "./settings";

const VALID_RULES = {
  global_confidence_floor: 0.6,
  global_magnitude_floor: 0.35,
  watch_floor: 0.45,
  unconfigured_magnitude_floor: 0.7,
  dedup_window_hours: 48,
  max_recommendations_per_cycle: 10,
  quiet_tickers: [] as string[],
  sector_scope: { allowlist: [] as string[], blocklist: [] as string[] },
};

describe("validateRulesSettings", () => {
  it("accepts the seeded defaults", () => {
    expect(validateRulesSettings(VALID_RULES)).toEqual([]);
  });

  it("rejects an out-of-range confidence floor", () => {
    const errors = validateRulesSettings({ ...VALID_RULES, global_confidence_floor: 1.5 });
    expect(errors).toContain("global_confidence_floor must be 0-1");
  });

  it("rejects a dedup window outside 1-336 hours", () => {
    expect(validateRulesSettings({ ...VALID_RULES, dedup_window_hours: 0 })).toContain(
      "dedup_window_hours must be 1-336"
    );
    expect(validateRulesSettings({ ...VALID_RULES, dedup_window_hours: 400 })).toContain(
      "dedup_window_hours must be 1-336"
    );
  });

  it("rejects non-string quiet_tickers entries", () => {
    const errors = validateRulesSettings({ ...VALID_RULES, quiet_tickers: [1, 2] });
    expect(errors).toContain("quiet_tickers must be a string array");
  });

  it("rejects a malformed sector_scope", () => {
    const errors = validateRulesSettings({ ...VALID_RULES, sector_scope: { allowlist: "not-an-array" } });
    expect(errors).toContain("sector_scope.allowlist/blocklist must be string arrays");
  });
});

const VALID_SCHEDULE = {
  timezone: "Asia/Bangkok",
  cycles: [
    { id: "morning", time: "07:00", enabled: true },
    { id: "evening", time: "20:30", enabled: true },
  ],
  outcomes_job_time: "07:30",
};

describe("validateScheduleSettings", () => {
  it("accepts the seeded defaults", () => {
    expect(validateScheduleSettings(VALID_SCHEDULE)).toEqual([]);
  });

  it("rejects a missing timezone", () => {
    expect(validateScheduleSettings({ ...VALID_SCHEDULE, timezone: "" })).toContain("timezone is required");
  });

  it("rejects zero or more than six cycle entries", () => {
    expect(validateScheduleSettings({ ...VALID_SCHEDULE, cycles: [] })).toContain("cycles must have 1-6 entries");
    const sevenCycles = Array.from({ length: 7 }, (_, i) => ({ id: `c${i}`, time: "07:00", enabled: true }));
    expect(validateScheduleSettings({ ...VALID_SCHEDULE, cycles: sevenCycles })).toContain(
      "cycles must have 1-6 entries"
    );
  });

  it("rejects duplicate cycle ids", () => {
    const errors = validateScheduleSettings({
      ...VALID_SCHEDULE,
      cycles: [
        { id: "morning", time: "07:00", enabled: true },
        { id: "morning", time: "12:00", enabled: true },
      ],
    });
    expect(errors).toContain("duplicate cycle id: morning");
  });

  it("rejects a malformed HH:MM time", () => {
    const errors = validateScheduleSettings({
      ...VALID_SCHEDULE,
      cycles: [{ id: "morning", time: "25:99", enabled: true }],
    });
    expect(errors).toContain("cycle morning: time must be HH:MM (24h)");
  });

  it("rejects a malformed outcomes_job_time", () => {
    expect(validateScheduleSettings({ ...VALID_SCHEDULE, outcomes_job_time: "bad" })).toContain(
      "outcomes_job_time must be HH:MM (24h)"
    );
  });
});

const VALID_LLM = {
  available_models: ["haiku", "sonnet", "opus"],
  tiers: {
    triage: { model: "haiku", reasoning: "off" },
    analysis: { model: "sonnet", reasoning: "low" },
    digest: { model: "sonnet", reasoning: "off" },
    pm_estimate: { model: "sonnet", reasoning: "medium" },
  },
  max_items_per_cycle: 150,
  monthly_budget_usd: 15,
  prices_per_mtok: {
    haiku: { input: 1, output: 5 },
    sonnet: { input: 3, output: 15 },
    opus: { input: 5, output: 25 },
  },
};

describe("validateLlmSettings", () => {
  it("accepts a well-formed settings object", () => {
    expect(validateLlmSettings(VALID_LLM)).toEqual([]);
  });

  it("rejects a tier model not present in available_models", () => {
    const errors = validateLlmSettings({
      ...VALID_LLM,
      tiers: { ...VALID_LLM.tiers, triage: { model: "gpt-5", reasoning: "off" } },
    });
    expect(errors).toContain("tiers.triage.model must be one of available_models");
  });

  it("rejects an invalid reasoning level", () => {
    const errors = validateLlmSettings({
      ...VALID_LLM,
      tiers: { ...VALID_LLM.tiers, digest: { model: "sonnet", reasoning: "extreme" } },
    });
    expect(errors).toContain("tiers.digest.reasoning must be one of off/low/medium/high");
  });

  it("rejects a model missing from prices_per_mtok", () => {
    const { opus: _opus, ...pricesWithoutOpus } = VALID_LLM.prices_per_mtok;
    const errors = validateLlmSettings({ ...VALID_LLM, prices_per_mtok: pricesWithoutOpus });
    expect(errors).toContain("prices_per_mtok.opus needs numeric input/output - every available model must be priced");
  });

  it("rejects a negative monthly budget", () => {
    expect(validateLlmSettings({ ...VALID_LLM, monthly_budget_usd: -1 })).toContain(
      "monthly_budget_usd must be >= 0"
    );
  });
});

describe("validateSource", () => {
  it("accepts a well-formed rss config", () => {
    expect(validateSource("rss", { url: "https://example.com/feed" })).toEqual([]);
  });

  it("rejects an unknown source_type", () => {
    const errors = validateSource("carrier_pigeon", {});
    expect(errors).toContain("source_type must be one of rss/finnhub/newsapi/reddit_rss/mcp");
  });

  it("rejects an rss config missing a url", () => {
    expect(validateSource("rss", {})).toContain("rss config needs a url");
  });

  it("accepts a finnhub config with either category or symbol", () => {
    expect(validateSource("finnhub", { category: "general" })).toEqual([]);
    expect(validateSource("finnhub", { symbol: "AAPL" })).toEqual([]);
    expect(validateSource("finnhub", {})).toContain("finnhub config needs category or symbol");
  });

  it("rejects an mcp config missing required fields", () => {
    const errors = validateSource("mcp", { server_url: "https://mcp.example.com" });
    expect(errors).toContain("mcp config needs a tool_name");
    expect(errors).toContain("mcp config needs a result_mapping object");
  });

  it("accepts a complete mcp config", () => {
    const errors = validateSource("mcp", {
      server_url: "https://mcp.example.com",
      tool_name: "search",
      result_mapping: { items_path: "$.results[*]" },
    });
    expect(errors).toEqual([]);
  });
});

const VALID_POLYMARKET = {
  enabled: true,
  scan_top_n: 20,
  reestimate_hours: 24,
  min_edge_points: 10,
  min_confidence: 0.55,
  min_liquidity_usd: 10000,
  min_days_to_end: 2,
  price_floor: 0.05,
  price_ceiling: 0.95,
  dedup_window_hours: 48,
  max_opportunities_per_cycle: 5,
  categories: [] as string[],
};

describe("validatePolymarketSettings", () => {
  it("accepts the seeded defaults", () => {
    expect(validatePolymarketSettings(VALID_POLYMARKET)).toEqual([]);
  });

  it("rejects price_floor >= price_ceiling", () => {
    const errors = validatePolymarketSettings({ ...VALID_POLYMARKET, price_floor: 0.9, price_ceiling: 0.5 });
    expect(errors).toContain("price_floor must be less than price_ceiling");
  });

  it("rejects a non-boolean enabled flag", () => {
    expect(validatePolymarketSettings({ ...VALID_POLYMARKET, enabled: "yes" })).toContain(
      "enabled must be a boolean"
    );
  });

  it("rejects scan_top_n outside 1-200", () => {
    expect(validatePolymarketSettings({ ...VALID_POLYMARKET, scan_top_n: 0 })).toContain(
      "scan_top_n must be 1-200"
    );
    expect(validatePolymarketSettings({ ...VALID_POLYMARKET, scan_top_n: 500 })).toContain(
      "scan_top_n must be 1-200"
    );
  });

  it("rejects non-string categories entries", () => {
    expect(validatePolymarketSettings({ ...VALID_POLYMARKET, categories: [1, 2] })).toContain(
      "categories must be a string array"
    );
  });
});
