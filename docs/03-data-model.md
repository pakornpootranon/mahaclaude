# Data Model — Mahachai Market Watch (codename `newswatch`, Postgres 16)

Canonical schema. Implemented in `web/prisma/schema.prisma`; the Python worker reflects the same
tables via SQLAlchemy. Shown here as annotated SQL for precision. All timestamps `timestamptz`,
stored UTC, displayed Asia/Bangkok.

---

## 1. Entity relationship overview

```
 sources 1──* news_items *──1 cycles
                 │
                 1
                 │
             analyses *──────────┐ (topic matches via analysis_topics)
                 │               │
                 * recommendations *──* recommendation_sources ──* news_items
                        │
                        1 outcomes
 topics 1──* mappings
 topics 1──* analysis_topics
 cycles 1──1 digests
 pm_markets 1──* pm_opportunities *──1 cycles ; pm_opportunities 1──1 pm_outcomes
 pm_opportunities *──* analyses (via pm_opportunity_analyses, news-driven discovery)
 settings (singleton rows)   secrets (API key)   llm_calls (ledger)   source_tests (async test-fetch)
```

## 2. Tables

### 2.1 `sources` — configured news inputs (FR-C1)

```sql
CREATE TABLE sources (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name          text NOT NULL,                 -- "Reuters Business RSS"
  source_type   text NOT NULL,                 -- 'rss' | 'finnhub' | 'newsapi' | 'reddit_rss' | 'mcp'
  config        jsonb NOT NULL,                -- type-specific: {url} | {categories} | {query, domains} | {subreddit}
                                               --   | mcp: {server_url, transport, tool_name, args_template,
                                               --          result_mapping, auth_env_var, max_calls_per_cycle}
  enabled       boolean NOT NULL DEFAULT true,
  poll_override_minutes int,                   -- NULL = only at digest cycles
  language      text NOT NULL DEFAULT 'en',
  health        text NOT NULL DEFAULT 'ok',    -- 'ok' | 'failing' | 'disabled'
  consecutive_failures int NOT NULL DEFAULT 0,
  last_success_at timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);
```

*API keys are NOT stored here* — `config` holds non-secret parameters only; keys come from env.

### 2.2 `cycles` — one digest run

```sql
CREATE TABLE cycles (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scheduled_for timestamptz NOT NULL,          -- the slot (07:00 ICT etc.) or manual request time
  kind          text NOT NULL DEFAULT 'scheduled',  -- 'scheduled' | 'manual'
  requested_manual boolean NOT NULL DEFAULT false,  -- web sets true; worker picks up
  state         text NOT NULL DEFAULT 'PENDING',
    -- PENDING|INGESTING|TRIAGING|ANALYZING|TRIGGERING|SUMMARIZING|DONE|FAILED
  stats         jsonb NOT NULL DEFAULT '{}',   -- {ingested, deduped, triaged_in, analyzed, triggered}
  budget_hit    boolean NOT NULL DEFAULT false,
  error         text,
  started_at    timestamptz,
  finished_at   timestamptz
);
CREATE INDEX ON cycles (scheduled_for DESC);
```

### 2.3 `news_items`

```sql
CREATE TABLE news_items (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id     uuid NOT NULL REFERENCES sources(id),
  cycle_id      uuid REFERENCES cycles(id),    -- cycle that first ingested it
  dedupe_key    text NOT NULL UNIQUE,          -- sha256(canonical_url)  (arch §5)
  story_key     text,                          -- triage-assigned storyline cluster id
  url           text NOT NULL,
  title         text NOT NULL,
  summary       text,
  body_excerpt  text,                          -- ≤2000 chars
  language      text NOT NULL DEFAULT 'en',
  published_at  timestamptz,
  fetched_at    timestamptz NOT NULL DEFAULT now(),
  analysis_hints jsonb,                        -- provider-supplied entity/sector tags (e.g. Bigdata.com)
  triage_status text NOT NULL DEFAULT 'pending'  -- 'pending'|'relevant'|'irrelevant'|'skipped_budget'
);
CREATE INDEX ON news_items (story_key);
CREATE INDEX ON news_items (published_at DESC);
```

### 2.4 `topics` — watch topics (FR-C2)

```sql
CREATE TABLE topics (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name          text NOT NULL UNIQUE,          -- "Fed rate decisions"
  description   text NOT NULL,                 -- shown to the LLM; be specific
  keywords      text[] NOT NULL DEFAULT '{}',  -- hint phrases for triage
  sensitivity   numeric(3,2) NOT NULL DEFAULT 0.70,  -- min confidence for THIS topic to trigger
  enabled       boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);
```

### 2.5 `mappings` — topic → sector/ticker impact rows (FR-C3)

```sql
CREATE TABLE mappings (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  topic_id      uuid NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
  market        text NOT NULL,                 -- 'US' | 'TH' | 'GLOBAL'
  sector        text NOT NULL,                 -- "Energy", "Airlines", "Semiconductors", "Thai Banks"
  tickers       text[] NOT NULL DEFAULT '{}',  -- ['XLE','CVX'] or ['PTT.BK','TOP.BK']
  polarity      int NOT NULL,                  -- +1: topic-positive news bullish for these; -1: inverse
  enabled       boolean NOT NULL DEFAULT true, -- FR-V3b sector scoping: disabled rows never recommend
  suggested_by  text NOT NULL DEFAULT 'user',  -- 'user' | 'llm' (accepted quick-add suggestion, FR-V3a)
  note          text,
  UNIQUE (topic_id, market, sector)
);
```

`polarity` example: topic "Oil supply shocks", positive development = supply disruption/price up.
Energy producers row polarity `+1`; Airlines row polarity `-1`.

### 2.6 `analyses` — LLM tier-2 output per storyline (FR-A1/A2)

```sql
CREATE TABLE analyses (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cycle_id       uuid NOT NULL REFERENCES cycles(id),
  story_key      text NOT NULL,                -- analyses are per-storyline, not per-item
  primary_item_id uuid NOT NULL REFERENCES news_items(id),
  prompt_version text NOT NULL,                -- e.g. 'analyze-v1'
  model          text NOT NULL,
  result         jsonb NOT NULL,               -- full AnalysisResult (04-llm-pipeline.md §5.2)
  event_polarity int NOT NULL,                 -- -1|0|+1 : direction of the event w.r.t. topic framing
  magnitude      numeric(3,2) NOT NULL,        -- 0.00–1.00
  confidence     numeric(3,2) NOT NULL,        -- 0.00–1.00
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (story_key, prompt_version)           -- idempotent re-runs
);

CREATE TABLE analysis_topics (                 -- which watch topics this analysis matched
  analysis_id   uuid NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
  topic_id      uuid REFERENCES topics(id),    -- NULL = "unconfigured but significant" flag (FR-A2)
  match_strength numeric(3,2) NOT NULL,
  PRIMARY KEY (analysis_id, topic_id)
);
```

### 2.7 `recommendations` (FR-A3/A4/A5)

```sql
CREATE TABLE recommendations (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cycle_id       uuid NOT NULL REFERENCES cycles(id),
  analysis_id    uuid NOT NULL REFERENCES analyses(id),
  topic_id       uuid REFERENCES topics(id),
  dedupe_key     text NOT NULL UNIQUE,
    -- sha256(topic_id|ticker_or_sector|action|window_bucket) — window_bucket = floor(epoch/dedup_window)
  action         text NOT NULL,                -- 'BUY' | 'SELL' | 'WATCH'
  market         text NOT NULL,                -- 'US' | 'TH' | 'GLOBAL'
  sector         text NOT NULL,
  tickers        text[] NOT NULL DEFAULT '{}', -- may be empty when sector-only (FR-A4)
  confidence     numeric(3,2) NOT NULL,
  reasoning      text NOT NULL,                -- one-paragraph, user-facing
  rule_trace     jsonb NOT NULL,               -- which thresholds passed/failed (provenance, FR-A5)
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON recommendations (created_at DESC);

CREATE TABLE recommendation_sources (          -- provenance: all storyline items
  recommendation_id uuid NOT NULL REFERENCES recommendations(id) ON DELETE CASCADE,
  news_item_id      uuid NOT NULL REFERENCES news_items(id),
  PRIMARY KEY (recommendation_id, news_item_id)
);
```

### 2.8 `outcomes` (FR-V4, arch §7)

```sql
CREATE TABLE outcomes (
  recommendation_id uuid PRIMARY KEY REFERENCES recommendations(id) ON DELETE CASCADE,
  ticker         text NOT NULL,                -- first ticker of the recommendation (v1 tracks one)
  entry_price    numeric,                      -- first close at/after created_at
  ret_1d         numeric, ret_3d numeric, ret_7d numeric,   -- simple returns, adjusted closes
  hit_1d         boolean, hit_3d boolean, hit_7d boolean,   -- direction-adjusted
  status         text NOT NULL DEFAULT 'pending',  -- 'pending'|'partial'|'complete'|'unavailable'
  attempts       int NOT NULL DEFAULT 0,
  updated_at     timestamptz NOT NULL DEFAULT now()
);
```

### 2.9 `digests` (FR-V2)

```sql
CREATE TABLE digests (
  cycle_id      uuid PRIMARY KEY REFERENCES cycles(id) ON DELETE CASCADE,
  market_mood   text NOT NULL,                 -- 'bullish' | 'bearish' | 'mixed'
  synthesis     text NOT NULL,                 -- LLM one-paragraph summary
  top_themes    jsonb NOT NULL,                -- [{theme, why, item_count}]
  created_at    timestamptz NOT NULL DEFAULT now()
);
```

### 2.10 `settings` — key/value singleton config (FR-C4/C5/C6/C8)

```sql
CREATE TABLE settings (
  key           text PRIMARY KEY,              -- 'rules' | 'schedule' | 'llm' | 'polymarket'
  value         jsonb NOT NULL,                -- schemas in 05-config-schema.md
  updated_at    timestamptz NOT NULL DEFAULT now()
);
```

### 2.11 `llm_calls` — spend ledger (arch §8)

```sql
CREATE TABLE llm_calls (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cycle_id      uuid REFERENCES cycles(id),
  purpose       text NOT NULL,                 -- 'triage' | 'analyze' | 'digest'
  model         text NOT NULL,
  input_tokens  int NOT NULL,
  output_tokens int NOT NULL,
  cost_usd      numeric(10,6) NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON llm_calls (created_at);
```

### 2.12 `secrets` — UI-managed secrets (arch §9)

```sql
CREATE TABLE secrets (
  key           text PRIMARY KEY,              -- 'anthropic_api_key' | 'finnhub_api_key' |
                                                --   'newsapi_api_key' | 'mcp_connector_token:{source_id}'
  value         text NOT NULL,                 -- stored as-is (localhost single-user, approved)
  last4         text NOT NULL,                 -- for masked display without decrypt round-trip
  updated_at    timestamptz NOT NULL DEFAULT now()
);
```

`key` has no enum/check constraint — any string is a valid row, which is what let the
Finnhub/NewsAPI/MCP-connector keys move into this table (2026-08-02) without a migration; only
the resolution order in `worker/secrets.py` and the routes in `web/lib/secrets.ts` changed.
MCP connector tokens are keyed per source id (`mcp_connector_token:{source_id}`) rather than a
single shared key, since each connector row can point at a different server.

Never joined into any export/read API; each settings GET returns only `{set: true, last4}` for
whichever key(s) it owns (`/api/config/llm`, `/api/config/connector-keys`,
`/api/config/mcp-connectors`).

### 2.13 `pm_markets` — Polymarket market snapshots

```sql
CREATE TABLE pm_markets (
  id            text PRIMARY KEY,              -- Polymarket market/condition id
  question      text NOT NULL,
  slug          text NOT NULL,                 -- for https://polymarket.com/event/<slug> links
  category      text,                          -- 'Politics' | 'Economy' | 'Crypto' | ...
  end_date      timestamptz,
  yes_price     numeric(6,4),                  -- latest snapshot 0–1
  volume_24h_usd numeric,
  liquidity_usd numeric,
  active        boolean NOT NULL DEFAULT true,
  resolved      boolean NOT NULL DEFAULT false,
  resolution    text,                          -- 'YES' | 'NO' | 'INVALID' | NULL
  snapshot_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON pm_markets (active, volume_24h_usd DESC);
```

### 2.14 `pm_opportunities` + provenance + outcomes (FR-V5)

```sql
CREATE TABLE pm_opportunities (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cycle_id      uuid NOT NULL REFERENCES cycles(id),
  market_id     text NOT NULL REFERENCES pm_markets(id),
  dedupe_key    text NOT NULL UNIQUE,          -- sha256(market_id|side|window_bucket)
  discovery     text NOT NULL,                 -- 'news' | 'scan'
  side          text NOT NULL,                 -- 'YES' | 'NO'  (which side looks cheap)
  market_price  numeric(6,4) NOT NULL,         -- YES price at flag time
  est_probability numeric(6,4) NOT NULL,       -- LLM estimate of YES
  edge_points   numeric(6,2) NOT NULL,         -- |est - price| × 100
  confidence    numeric(3,2) NOT NULL,
  reasoning     text NOT NULL,
  rule_trace    jsonb NOT NULL,                -- edge/liquidity/confidence checks pass/fail
  prompt_version text NOT NULL,
  model         text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON pm_opportunities (created_at DESC);

CREATE TABLE pm_opportunity_analyses (         -- news-driven provenance
  pm_opportunity_id uuid NOT NULL REFERENCES pm_opportunities(id) ON DELETE CASCADE,
  analysis_id       uuid NOT NULL REFERENCES analyses(id),
  PRIMARY KEY (pm_opportunity_id, analysis_id)
);

CREATE TABLE pm_outcomes (
  pm_opportunity_id uuid PRIMARY KEY REFERENCES pm_opportunities(id) ON DELETE CASCADE,
  price_1d      numeric(6,4), price_3d numeric(6,4), price_7d numeric(6,4),
  moved_toward_estimate_7d boolean,
  resolved      boolean NOT NULL DEFAULT false,
  resolution    text,                          -- 'YES' | 'NO' | 'INVALID'
  estimate_correct boolean,                    -- side matched resolution
  status        text NOT NULL DEFAULT 'pending', -- 'pending'|'partial'|'complete'|'unavailable'
  attempts      int NOT NULL DEFAULT 0,
  updated_at    timestamptz NOT NULL DEFAULT now()
);
```

### 2.15 `source_tests` — async test-fetch handshake (arch §6)

```sql
CREATE TABLE source_tests (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id     uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  status        text NOT NULL DEFAULT 'requested', -- 'requested'|'ok'|'error'
  result        jsonb,                          -- {item_count, sample_titles[], error?}
  requested_at  timestamptz NOT NULL DEFAULT now(),
  completed_at  timestamptz
);
```

## 3. Derived views (implement as SQL views or query helpers)

- `topic_board_v`: per enabled topic — hits in last 48h (`analysis_topics` join), status chip
  (`quiet` 0 hits / `active` 1–2 / `hot` ≥3), last recommendation time, distinct tickers recently named.
- `hit_rates_v`: per topic and per action — count, avg confidence, hit rate at 1d/3d/7d from `outcomes`.
- `pm_calibration_v`: per edge bucket — count, share where price moved toward estimate by 7d, resolution accuracy (from `pm_outcomes`).
- `spend_mtd_v`: `sum(cost_usd)` from `llm_calls` where `created_at` in current month (Asia/Bangkok month boundary).

## 4. Migration & seeding

- Prisma owns migrations (`prisma migrate dev` locally, `migrate deploy` in the web container entrypoint).
- Seed script (`web/prisma/seed.ts`) loads the seed config from `05-config-schema.md` §6 —
  sources, topics, mappings, settings — so acceptance test #2 works out of the box.
