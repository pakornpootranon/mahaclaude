// Seed data per docs/05-config-schema.md §6. Upserts so re-running `make seed`
// is idempotent (Phase 1 working rule: idempotency everywhere).
//
// Builder notes on things verified/adjusted at implementation time:
//
// - RSS feed liveness: this sandboxed build environment's network policy
//   blocks outbound requests to news/Reddit domains entirely (proxy denies
//   the CONNECT), and even the hosted WebFetch tool got HTTP 403 from all of
//   them (routine anti-bot blocking of non-browser fetchers — Bangkok Post,
//   The Nation, CNBC, Google News, and Reddit all commonly 403 generic
//   fetchers while serving real RSS clients like `feedparser` fine). Neither
//   path is a live-connectivity check the worker itself will do, so the URLs
//   below are shipped as specified, unverified. The worker's own health
//   tracking (arch §4: 3 consecutive failures -> sources.health = 'failing')
//   is the real verification loop — check the health strip after the first
//   `run-cycle` and swap out anything that goes 'failing'.
// - Bigdata.com MCP tool shape: verified live against a real bigdata_search
//   call in this session. Two things differ from the spec's placeholder
//   example (docs/05 §4): the real input is nested under
//   `request.search_mode` / `request.query.text` (not a flat
//   `{query, limit}`), and the response has no per-document entity/sector
//   tag field the way `analysis_hints` assumed — `source.name` is the
//   closest available hint. args_template/result_mapping below reflect the
//   verified shape. The server_url is still the spec's placeholder pending
//   confirmation against Bigdata.com's own MCP docs (this session reaches
//   bigdata_search through an internal connector, not the public endpoint
//   an external worker process would dial).
// - "^SET.BK" (docs/05 §6.2, mapping 1): the spec flags this symbol as
//   unverified and names TDEX.BK as the fallback. yfinance-symbol
//   verification needs live network access this sandbox doesn't have, so we
//   use the spec's own fallback directly (also used in mapping 5) rather
//   than seed an unverified symbol.

import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

const SOURCES = [
  {
    name: "Reuters Business (via Google News RSS)",
    sourceType: "rss",
    config: {
      url: "https://news.google.com/rss/search?q=site:reuters.com+business&hl=en-US&gl=US&ceid=US:en",
    },
  },
  {
    name: "CNBC Top News",
    sourceType: "rss",
    config: {
      url: "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    },
  },
  {
    name: "MarketWatch Top Stories",
    sourceType: "rss",
    config: {
      url: "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    },
  },
  {
    name: "Bangkok Post Business",
    sourceType: "rss",
    config: { url: "https://www.bangkokpost.com/rss/data/business.xml" },
  },
  {
    name: "The Nation Thailand Business",
    sourceType: "rss",
    config: { url: "https://www.nationthailand.com/rss/business" },
  },
  {
    name: "Finnhub General News",
    sourceType: "finnhub",
    config: { category: "general" },
  },
  {
    name: "r/stocks hot",
    sourceType: "reddit_rss",
    config: { subreddit: "stocks", listing: "hot", limit: 25 },
  },
  {
    name: "r/wallstreetbets hot",
    sourceType: "reddit_rss",
    config: { subreddit: "wallstreetbets", listing: "hot", limit: 25 },
  },
  {
    name: "Bigdata.com (MCP)",
    sourceType: "mcp",
    enabled: false,
    config: {
      server_url: "https://mcp.bigdata.com/mcp",
      transport: "streamable_http",
      tool_name: "bigdata_search",
      args_template: {
        request: {
          search_mode: "smart",
          query: {
            text: "{topic_keywords} latest news",
            context: "search in news",
          },
        },
      },
      result_mapping: {
        items_path: "$.results[*]",
        title: "$.headline",
        url: "$.url",
        summary: "$.chunks[0].text",
        published_at: "$.timestamp",
        hints: "$.source",
      },
      auth_env_var: "BIGDATA_API_KEY",
      max_calls_per_cycle: 10,
    },
  },
] as const;

const TOPICS = [
  {
    name: "Fed rate decisions",
    description:
      "US Federal Reserve rate decisions and forward guidance. Positive framing (+1) = easing / dovish surprise.",
    keywords: ["FOMC", "rate cut", "rate hike", "Powell", "dot plot", "fed funds"],
    sensitivity: 0.65,
    mappings: [
      { market: "US", sector: "Broad market", tickers: ["SPY", "QQQ"], polarity: 1 },
      { market: "US", sector: "Banks", tickers: ["XLF"], polarity: -1 },
      { market: "US", sector: "Real estate", tickers: ["XLRE"], polarity: 1 },
      { market: "TH", sector: "Thai banks", tickers: ["KBANK.BK", "SCB.BK"], polarity: -1 },
      { market: "TH", sector: "SET proxy", tickers: ["TDEX.BK"], polarity: 1 },
    ],
  },
  {
    name: "Oil supply shocks",
    description:
      "OPEC/supply-side shocks to crude oil. Positive framing (+1) = supply disruption / price up.",
    keywords: ["OPEC", "production cut", "crude", "sanctions oil", "Strait of Hormuz", "pipeline"],
    sensitivity: 0.70,
    mappings: [
      { market: "US", sector: "Energy producers", tickers: ["XLE", "CVX", "XOM"], polarity: 1 },
      { market: "US", sector: "Airlines", tickers: ["JETS", "DAL"], polarity: -1 },
      { market: "TH", sector: "Thai energy", tickers: ["PTT.BK", "TOP.BK", "PTTEP.BK"], polarity: 1 },
      { market: "TH", sector: "Thai airlines", tickers: ["AAV.BK"], polarity: -1 },
    ],
  },
  {
    name: "Chip export controls / semiconductor cycle",
    description:
      "Export restrictions and demand cycle for semiconductors. Positive framing (+1) = demand growth / restriction easing.",
    keywords: ["export ban", "NVIDIA", "TSMC", "chip restrictions", "semiconductor", "AI chips"],
    sensitivity: 0.70,
    mappings: [
      { market: "US", sector: "Semiconductors", tickers: ["SMH", "NVDA", "AMD"], polarity: 1 },
      { market: "TH", sector: "Thai electronics", tickers: ["DELTA.BK", "HANA.BK", "KCE.BK"], polarity: 1 },
    ],
  },
  {
    name: "China stimulus & growth",
    description:
      "Chinese monetary/fiscal stimulus and growth signals. Positive framing (+1) = stimulus / stronger growth.",
    keywords: ["PBOC", "stimulus", "China GDP", "property crisis", "yuan"],
    sensitivity: 0.70,
    mappings: [
      { market: "US", sector: "China ADR proxy", tickers: ["FXI", "KWEB"], polarity: 1 },
      {
        market: "GLOBAL",
        sector: "Commodities",
        tickers: ["GLD", "COPX"],
        polarity: 1,
        note: "GLD is a mixed signal (safe-haven + China demand) — direction is more contested than the other rows.",
      },
      { market: "TH", sector: "Thai tourism", tickers: ["AOT.BK", "CENTEL.BK", "ERW.BK"], polarity: 1 },
    ],
  },
  {
    name: "Thai politics & policy",
    description:
      "Bank of Thailand policy and Thai political/fiscal stability. Positive framing (+1) = stability / stimulus / rate cuts.",
    keywords: ["Bank of Thailand", "Thai cabinet", "baht", "digital wallet", "Thai election", "BOT rate"],
    sensitivity: 0.75,
    mappings: [
      { market: "TH", sector: "SET proxy", tickers: ["TDEX.BK"], polarity: 1 },
      { market: "TH", sector: "Thai banks", tickers: ["KBANK.BK", "SCB.BK", "BBL.BK"], polarity: 1 },
      { market: "TH", sector: "Thai retail", tickers: ["CPALL.BK", "CRC.BK"], polarity: 1 },
    ],
  },
] as const;

// Current Claude model IDs and per-Mtok prices (USD), verified at
// implementation time (docs/04-llm-pipeline.md §1 default tiers).
const HAIKU_MODEL = "claude-haiku-4-5";
const SONNET_MODEL = "claude-sonnet-5";
const OPUS_MODEL = "claude-opus-5";

async function main() {
  for (const s of SOURCES) {
    await prisma.source.upsert({
      where: { name: s.name },
      update: {
        sourceType: s.sourceType,
        config: s.config,
        enabled: "enabled" in s ? s.enabled : true,
      },
      create: {
        name: s.name,
        sourceType: s.sourceType,
        config: s.config,
        enabled: "enabled" in s ? s.enabled : true,
      },
    });
  }

  for (const t of TOPICS) {
    const topic = await prisma.topic.upsert({
      where: { name: t.name },
      update: {
        description: t.description,
        keywords: [...t.keywords],
        sensitivity: t.sensitivity,
      },
      create: {
        name: t.name,
        description: t.description,
        keywords: [...t.keywords],
        sensitivity: t.sensitivity,
      },
    });

    for (const m of t.mappings) {
      await prisma.mapping.upsert({
        where: {
          topicId_market_sector: {
            topicId: topic.id,
            market: m.market,
            sector: m.sector,
          },
        },
        update: {
          tickers: [...m.tickers],
          polarity: m.polarity,
          note: "note" in m ? m.note : null,
        },
        create: {
          topicId: topic.id,
          market: m.market,
          sector: m.sector,
          tickers: [...m.tickers],
          polarity: m.polarity,
          note: "note" in m ? m.note : null,
        },
      });
    }
  }

  await prisma.setting.upsert({
    where: { key: "rules" },
    update: {},
    create: {
      key: "rules",
      value: {
        global_confidence_floor: 0.6,
        global_magnitude_floor: 0.35,
        watch_floor: 0.45,
        unconfigured_magnitude_floor: 0.7,
        dedup_window_hours: 48,
        max_recommendations_per_cycle: 10,
        quiet_tickers: [],
        sector_scope: { allowlist: [], blocklist: [] },
      },
    },
  });

  await prisma.setting.upsert({
    where: { key: "schedule" },
    update: {},
    create: {
      key: "schedule",
      value: {
        timezone: "Asia/Bangkok",
        cycles: [
          { id: "morning", time: "07:00", enabled: true, label: "Post-US-close wrap" },
          { id: "midday", time: "12:30", enabled: true, label: "SET midday" },
          { id: "evening", time: "20:30", enabled: true, label: "Pre-US-open" },
        ],
        outcomes_job_time: "07:30",
      },
    },
  });

  await prisma.setting.upsert({
    where: { key: "llm" },
    update: {},
    create: {
      key: "llm",
      value: {
        available_models: [HAIKU_MODEL, SONNET_MODEL, OPUS_MODEL],
        tiers: {
          triage: { model: HAIKU_MODEL, reasoning: "off" },
          analysis: { model: SONNET_MODEL, reasoning: "low" },
          digest: { model: SONNET_MODEL, reasoning: "off" },
          pm_estimate: { model: SONNET_MODEL, reasoning: "medium" },
        },
        max_items_per_cycle: 150,
        monthly_budget_usd: 15.0,
        prices_per_mtok: {
          [HAIKU_MODEL]: { input: 1.0, output: 5.0 },
          [SONNET_MODEL]: { input: 3.0, output: 15.0 },
          [OPUS_MODEL]: { input: 5.0, output: 25.0 },
        },
      },
    },
  });

  await prisma.setting.upsert({
    where: { key: "polymarket" },
    update: {},
    create: {
      key: "polymarket",
      value: {
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
        categories: [],
      },
    },
  });

  console.log("Seed complete.");
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
