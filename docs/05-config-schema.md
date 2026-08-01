# Configuration Schema & Seed Config — `newswatch`

Everything the user can change without touching code (FR-C1..C7). Sources, topics, and mappings
live in their own tables (03-data-model.md §2.1/2.4/2.5); rules, schedule, and LLM settings live
in the `settings` key/value table. This doc defines the JSON schemas and the seed dataset.

---

## 1. `settings['rules']` (FR-C4)

```json
{
  "global_confidence_floor": 0.60,
  "global_magnitude_floor": 0.35,
  "watch_floor": 0.45,
  "unconfigured_magnitude_floor": 0.70,
  "dedup_window_hours": 48,
  "max_recommendations_per_cycle": 10,
  "quiet_tickers": [],
  "sector_scope": { "allowlist": [], "blocklist": [] }
}
```

| Field | Meaning | Constraints |
|---|---|---|
| `global_confidence_floor` | Minimum effective confidence for any trigger; per-topic `sensitivity` can only raise it | 0–1 |
| `global_magnitude_floor` | Below this the analysis never triggers anything | 0–1 |
| `watch_floor` | Magnitude below this downgrades BUY/SELL → WATCH | 0–1, ≤ magnitude floor semantics per 04 §6 |
| `unconfigured_magnitude_floor` | Floor for "significant but no topic matched" WATCH items | 0–1 |
| `dedup_window_hours` | Same topic+ticker+action can't re-trigger inside this window | 1–336 |
| `max_recommendations_per_cycle` | Highest-confidence-first cap | 1–50 |
| `quiet_tickers` | Never recommend these symbols | uppercase strings |
| `sector_scope.allowlist` | If non-empty, ONLY these sectors may be recommended (case-insensitive match on mapping `sector`) | strings |
| `sector_scope.blocklist` | These sectors are never recommended; wins over allowlist | strings |

## 2. `settings['schedule']` (FR-C5)

```json
{
  "timezone": "Asia/Bangkok",
  "cycles": [
    { "id": "morning", "time": "07:00", "enabled": true,  "label": "Post-US-close wrap" },
    { "id": "midday",  "time": "12:30", "enabled": true,  "label": "SET midday" },
    { "id": "evening", "time": "20:30", "enabled": true,  "label": "Pre-US-open" }
  ],
  "outcomes_job_time": "07:30"
}
```

`timezone` is display + cron zone; fixed to Asia/Bangkok in v1 UI but stored for portability.
1–6 cycles allowed; times `HH:MM` 24h; ids must be unique slugs.

## 3. `settings['llm']` (FR-C6)

```json
{
  "available_models": ["<haiku id>", "<sonnet id>", "<opus id>"],
  "tiers": {
    "triage":      { "model": "<haiku id>",  "reasoning": "off" },
    "analysis":    { "model": "<sonnet id>", "reasoning": "low" },
    "digest":      { "model": "<sonnet id>", "reasoning": "off" },
    "pm_estimate": { "model": "<sonnet id>", "reasoning": "medium" }
  },
  "max_items_per_cycle": 150,
  "monthly_budget_usd": 15.0,
  "prices_per_mtok": {
    "<haiku id>":  { "input": 0.0, "output": 0.0 },
    "<sonnet id>": { "input": 0.0, "output": 0.0 },
    "<opus id>":   { "input": 0.0, "output": 0.0 }
  }
}
```

- `reasoning`: `"off" | "low" | "medium" | "high"` — extended-thinking level per tier, mapped to
  thinking-token budgets in `llm/client.py` (04 §1). Thinking tokens count as output in the ledger.
- `available_models` populates the model dropdowns; the user can add new model IDs as Anthropic
  ships them (must also add a `prices_per_mtok` entry — the form enforces this).
- **API key** is NOT in this JSON — it lives in the `secrets` table (03 §2.12). The Settings → LLM
  page has a key field that POSTs write-only to `/api/config/llm`; GET returns `{set, last4}` for
  masked display (`sk-ant-…1234`). `.env` `ANTHROPIC_API_KEY` is the fallback when unset.
- Builder notes: fill real current model IDs and per-MTok prices at implementation time
  (they change; check docs.claude.com/en/docs/about-claude/models). `prices_per_mtok` drives the
  spend ledger math; unknown model in the map → refuse the call (fail closed, protects the cap).

## 3b. `settings['polymarket']` (FR-V5)

```json
{
  "enabled": true,
  "scan_top_n": 20,
  "reestimate_hours": 24,
  "min_edge_points": 10,
  "min_confidence": 0.55,
  "min_liquidity_usd": 10000,
  "min_days_to_end": 2,
  "price_floor": 0.05,
  "price_ceiling": 0.95,
  "dedup_window_hours": 48,
  "max_opportunities_per_cycle": 5,
  "categories": []
}
```

`categories`: empty = all Polymarket categories; otherwise restrict the scan (news-driven matches
ignore this filter). Semantics of the rest: `04-llm-pipeline.md` §9. Polymarket's public Gamma API
needs no key for read-only market data (builder: verify endpoints at implementation time).

## 4. `sources.config` per `source_type` (FR-C1)

| source_type | config JSON | secret env var |
|---|---|---|
| `rss` | `{ "url": "https://..." }` | — |
| `finnhub` | `{ "category": "general" }` (or `{"symbol": "AAPL"}` for company news) | `FINNHUB_KEY` |
| `newsapi` | `{ "query": "OPEC OR \"oil supply\"", "domains": ["reuters.com"], "language": "en" }` | `NEWSAPI_KEY` |
| `reddit_rss` | `{ "subreddit": "stocks", "listing": "hot", "limit": 25 }` (via subreddit .rss URL, no key) | — |
| `mcp` | see below | per-connector, named in `auth_env_var` |

`mcp` connector config (arch §4b):

```json
{
  "server_url": "https://mcp.bigdata.com/mcp",
  "transport": "streamable_http",
  "tool_name": "bigdata_search",
  "args_template": { "query": "{topic_keywords} latest news", "limit": 10 },
  "result_mapping": {
    "items_path": "$.results[*]",
    "title": "$.headline", "url": "$.url", "summary": "$.snippet",
    "published_at": "$.published", "hints": "$.entities"
  },
  "auth_env_var": "BIGDATA_API_KEY",
  "max_calls_per_cycle": 10
}
```

`{topic_keywords}` in `args_template` expands per enabled watch topic (one call per topic, capped
by `max_calls_per_cycle`, highest-sensitivity topics first). `hints` maps provider entity/sector
tags into `news_items.analysis_hints`. Builder: verify the actual Bigdata.com MCP endpoint, tool
name, and result shape at implementation time; the seed row ships **disabled** until the user sets
the env var and flips the toggle (PRD acceptance #8 tests the toggle both ways).

## 5. Config export/import format (FR-C7)

Single JSON document:

```json
{
  "newswatch_config_version": 1,
  "exported_at": "2026-08-01T12:00:00+07:00",
  "sources": [ { "name": "...", "source_type": "...", "config": {}, "enabled": true,
                 "poll_override_minutes": null, "language": "en" } ],
  "topics":  [ { "name": "...", "description": "...", "keywords": [], "sensitivity": 0.7,
                 "enabled": true,
                 "mappings": [ { "market": "US", "sector": "...", "tickers": [], "polarity": 1, "note": null } ] } ],
  "settings": { "rules": {}, "schedule": {}, "llm": {}, "polymarket": {} }
}
```

Import is upsert-by-name (sources, topics) — never deletes rows absent from the file; UI shows a
diff preview before applying. Export NEVER includes the Claude API key or any `auth_env_var`
values (env-var *names* in MCP configs are fine); the `llm` settings export excludes nothing else.
Topic mappings export includes each row's `enabled` flag so sector scoping survives round-trips.

## 6. Seed config (ships in `web/prisma/seed.ts`)

### 6.1 Sources (all free, no key needed except where noted)

| Name | Type | Config |
|---|---|---|
| Reuters Business (via Google News RSS) | rss | `{"url": "https://news.google.com/rss/search?q=site:reuters.com+business&hl=en-US&gl=US&ceid=US:en"}` |
| CNBC Top News | rss | `{"url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"}` |
| MarketWatch Top Stories | rss | `{"url": "https://feeds.content.dowjones.io/public/rss/mw_topstories"}` |
| Bangkok Post Business | rss | `{"url": "https://www.bangkokpost.com/rss/data/business.xml"}` |
| The Nation Thailand Business | rss | `{"url": "https://www.nationthailand.com/rss/business"}` |
| Finnhub General News | finnhub | `{"category": "general"}` (needs `FINNHUB_KEY`, free tier) |
| r/stocks hot | reddit_rss | `{"subreddit": "stocks", "listing": "hot", "limit": 25}` |
| r/wallstreetbets hot | reddit_rss | `{"subreddit": "wallstreetbets", "listing": "hot", "limit": 25}` |
| Bigdata.com (MCP) — **disabled by default** | mcp | the reference config in §4 (needs `BIGDATA_API_KEY`) |

Builder note: verify each URL at implementation time (feeds rot); replace dead ones with
equivalents and note substitutions in the README.

### 6.2 Watch topics + mappings

**1. Fed rate decisions** — sensitivity 0.65
Keywords: `FOMC, rate cut, rate hike, Powell, dot plot, fed funds`
Positive framing (+1) = easing / dovish surprise.

| Market | Sector | Tickers | Polarity |
|---|---|---|---|
| US | Broad market | SPY, QQQ | +1 |
| US | Banks | XLF | -1 |
| US | Real estate | XLRE | +1 |
| TH | Thai banks | KBANK.BK, SCB.BK | -1 |
| TH | SET proxy | ^SET.BK *(builder: verify yfinance symbol; fallback TDEX.BK)* | +1 |

**2. Oil supply shocks** — sensitivity 0.70
Keywords: `OPEC, production cut, crude, sanctions oil, Strait of Hormuz, pipeline`
Positive framing (+1) = supply disruption / price up.

| Market | Sector | Tickers | Polarity |
|---|---|---|---|
| US | Energy producers | XLE, CVX, XOM | +1 |
| US | Airlines | JETS, DAL | -1 |
| TH | Thai energy | PTT.BK, TOP.BK, PTTEP.BK | +1 |
| TH | Thai airlines | AAV.BK | -1 |

**3. Chip export controls / semiconductor cycle** — sensitivity 0.70
Keywords: `export ban, NVIDIA, TSMC, chip restrictions, semiconductor, AI chips`
Positive framing (+1) = demand growth / restriction easing.

| Market | Sector | Tickers | Polarity |
|---|---|---|---|
| US | Semiconductors | SMH, NVDA, AMD | +1 |
| TH | Thai electronics | DELTA.BK, HANA.BK, KCE.BK | +1 |

**4. China stimulus & growth** — sensitivity 0.70
Keywords: `PBOC, stimulus, China GDP, property crisis, yuan`
Positive framing (+1) = stimulus / stronger growth.

| Market | Sector | Tickers | Polarity |
|---|---|---|---|
| US | China ADR proxy | FXI, KWEB | +1 |
| GLOBAL | Commodities | GLD *(note: mixed)*, COPX | +1 |
| TH | Thai tourism | AOT.BK, CENTEL.BK, ERW.BK | +1 |

**5. Thai politics & policy** — sensitivity 0.75
Keywords: `Bank of Thailand, Thai cabinet, baht, digital wallet, Thai election, BOT rate`
Positive framing (+1) = stability / stimulus / rate cuts.

| Market | Sector | Tickers | Polarity |
|---|---|---|---|
| TH | SET proxy | TDEX.BK | +1 |
| TH | Thai banks | KBANK.BK, SCB.BK, BBL.BK | +1 |
| TH | Thai retail | CPALL.BK, CRC.BK | +1 |

### 6.3 Settings

Rules, schedule, LLM, and Polymarket exactly as the defaults in §1–§3b above.

## 7. Settings UI requirements (summary; full UX left to builder)

- Each settings page: form ↔ table hybrid, optimistic save, inline validation mirroring the
  constraints tables above, "revert to defaults" per page.
- Sources page: health badge, last-success time, Test button (async via `source_tests`).
- MCP connectors page (FR-C8): filtered view of `source_type='mcp'` sources with connector fields
  (server URL, tool, args template, result mapping as a guided form with raw-JSON escape hatch),
  prominent enable/disable toggle, env-var set/unset indicator, Test button.
- Topics page: topic list → drawer with keywords chips, sensitivity slider, mappings grid editor
  (add row: market select, sector text, tickers tag-input uppercased, polarity toggle, per-row
  enabled switch). Note: quick-add + inline scoping ALSO live on the dashboard topic board
  (FR-V3a/b) — the Settings page is the full editor, the board is the fast path; both write the
  same tables.
- LLM page: masked API key field with rotate action (04 §1 key resolution), per-tier model
  dropdown + reasoning level select with live estimated cost-per-cycle delta, model list editor
  (enforces a price entry per model), budget cap with month-to-date spend bar.
- Polymarket page: master enable toggle + the §3b knobs with plain-language descriptions
  ("minimum edge in points before a market is flagged").
- Rules page: sliders with live "what would have triggered last cycle" preview count (query
  existing analyses against draft values — cheap and very useful).
- Danger-free: no destructive action without confirm; topics/sources are disabled, not deleted,
  by default (delete behind a second confirm, cascades per schema).
