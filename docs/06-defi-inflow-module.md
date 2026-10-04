# ETH & DeFi Inflow Radar — module spec (proposal, v0.1)

**Status:** PLAN — for discussion before build. Nothing in this doc is implemented yet.
**Companion to:** `01-prd.md` … `05-config-schema.md`. Reuses the existing worker/web/Postgres
split, the cycle state machine, the rules-engine discipline, and the Settings/secrets patterns.
**Author's premise (user):** expecting a strongly bullish crypto market in 2027; wants a daily
tool that flags **DeFi tokens on Ethereum, and ETH itself, that are receiving significant
investment inflow**, with a notification so nothing has to be watched manually.

---

## 0. What "significant inflow" means here (the thesis, made measurable)

A bull market shows up in **money arriving before price fully reprices**. The dashboard already
reads *news*; this module adds the *flow* side and cross-references the two. Inflow is never a
single number — it is a set of independent daily series, each turned into a z-score against its
own trailing 90-day history, then combined by deterministic rules.

| Target | Inflow proxy (daily series) | Why it matters | Source (free) |
|---|---|---|---|
| ETH | US spot ETH ETF **net flows** (USD m, by fund + total) | TradFi allocation; the single cleanest "new money" signal | **Bigdata.com** MCP: MT Newswires' daily "US-Traded Ether ETFs …" wire (SoSoValue figures, per-fund breakdown) — see §2b; Farside HTML page as fallback |
| L2 chains (Arbitrum, Base, Robinhood Chain) | **Chain TVL** 7d/30d Δ (USD and ETH-denominated), **stablecoin supply on the chain**, **DEX volume** 7d Δ, **bridged-in value** where DefiLlama exposes it | Capital moving *onto* an L2 is inflow to the Ethereum economy even when no token exists; Robinhood Chain has 10 % of its net revenue flowing to the Arbitrum treasury, so its growth is an ARB input too | DefiLlama `/v2/historicalChainTvl/{Arbitrum\|Base\|Robinhood}`, `stablecoincharts/{chain}`, `/overview/dexs/{chain}` (DefiLlama indexes Robinhood Chain — ~$0.9 B TVL, ~200 dApps by Sept 2026 per Bigdata.com wires); proxies: ARB token, COIN and HOOD equities |
| Token-only (QNT) | **Spot turnover** (volume ÷ market cap, z-scored), **price 7d/30d Δ**, **exchange listings & whale-transfer wires**, media attention | Non-DeFi ERC-20s have no TVL or fees, so inflow is read from spot demand + flow-of-news | CoinGecko Demo API; Bigdata.com entity-filtered search (Quant Network Ltd = `7D21F7`) and tearsheet |
| Both | **Media sentiment & attention** per asset (score, momentum, 1-mo / 1-qt attention z-scores) | Crowdedness check: inflow with *flat* attention is stealth; inflow with spiking attention is late | **Bigdata.com** `bigdata_sentiment_tearsheet` per resolved entity — see §2b |
| ETH | **Exchange net flow** (ETH leaving exchanges = accumulation) | Spot buyers withdrawing to custody / staking | Coin Metrics Community API, daily `FlowInExNtv` / `FlowOutExNtv` (verify metric names on community tier at build time) |
| ETH | **Stablecoin supply on Ethereum** (7d / 30d change) | Dry powder parked on-chain before deployment | DefiLlama `stablecoins.llama.fi/stablecoincharts/Ethereum` |
| ETH | **Ethereum chain TVL** in USD *and* in ETH terms | TVL/ETH-price strips the price effect; rising ETH-denominated TVL = real deposits | DefiLlama `api.llama.fi/v2/historicalChainTvl/Ethereum` + ETH price |
| ETH | Spot volume / market cap, 7d turnover | Participation confirmation | CoinGecko Demo API `/coins/ethereum` |
| DeFi token | **Protocol TVL change** 1d / 7d / 30d | Capital entering the protocol | DefiLlama `/protocols` (`change_1d`, `change_7d`, `change_1m`, `tvl`, `symbol`, `chains`, `category`) |
| DeFi token | **Fees & revenue** 7d change | Usage-driven, "real yield" inflow — harder to fake than TVL | DefiLlama `/overview/fees/ethereum` |
| DeFi token | **DEX volume** 7d change (DEX protocols only) | Activity confirmation | DefiLlama `/overview/dexs/ethereum` |
| DeFi token | **Token price, volume, market cap**; derived **MCap/TVL** | Spot demand + valuation vs. the capital it secures | CoinGecko Demo API `/coins/markets?category=decentralized-finance-defi` |
| Both | **News storylines** already analyzed by the dashboard | Catalyst attribution (upgrades, listings, treasury buys, regulation) | Existing pipeline — one new seeded watch topic; the seeded **Bigdata.com** MCP connector (enabled) adds premium crypto wires (MT Newswires Crypto, Benzinga, Crypto Wire, Crypto Briefing) the RSS seeds don't carry |

Signal classes the rules engine can emit (each with a full `rule_trace`, like `rules.py` and
`polymarket/scan.py`):

| Class | Rule sketch (defaults; all tunable in Settings) | Reads as |
|---|---|---|
| `ETH_INFLOW` | ≥ 2 of {ETF 5d sum z ≥ 1.5, exchange netflow 7d z ≤ −1.5, stablecoin 7d Δ ≥ +2 %, ETH-TVL 7d z ≥ 1.0} | Broad money flowing into ETH |
| `ETF_STREAK` | ≥ 5 consecutive positive ETF days **and** 5d sum ≥ configurable USD floor | Institutional bid is persistent |
| `PROTOCOL_INFLOW` | TVL 7d Δ ≥ +15 % **and** (fees 7d Δ ≥ +20 % **or** volume 7d Δ ≥ +30 %) **and** TVL ≥ floor | Capital + usage arriving together |
| `STEALTH_INFLOW` | TVL 7d Δ ≥ +15 % **and** token price 7d Δ ≤ +5 % **and** MCap/TVL below its own 90d median **and** (when available) media-attention 1-mo z ≤ 0.5 | Money entering before the token reprices *and before the press notices* — the "early" signal |
| `CROWDED` (informational, never notified) | Any inflow class fired **and** media-attention 1-mo z ≥ 1.5 **and** price 7d Δ ≥ +20 % | Inflow is real but late and widely covered — shown on the card as a caution, not a flag |
| `ROTATION` | Protocol's share of Ethereum DeFi TVL rises ≥ 1.0 pt in 7d | Capital rotating *within* DeFi toward this protocol |
| `L2_INFLOW` (kind = `chain`) | chain-TVL-in-ETH 7d z ≥ 1.0 **and** (stablecoin supply 7d Δ ≥ +3 % **or** DEX volume 7d Δ ≥ +30 %) | Money arriving on the L2; the card names the proxy instruments (ARB, COIN, HOOD) and, for Base/Robinhood, hands a `WATCH` hint to the existing equity pipeline via the seeded mappings |
| `TOKEN_ACCUMULATION` (kind = `token`, e.g. QNT) | turnover 7d z ≥ 2.0 **and** price 7d Δ ≥ +10 % **and** ≥ 1 storyline with `magnitude ≥ 0.6` mentioning the asset in the last 7d | Spot demand surging on a real catalyst — the QNT / Clearing House pattern of late Sept 2026 (price +227 % in a week, new addresses 55× baseline) |
| `TOKEN_QUIET_BID` (kind = `token`) | turnover 7d z ≥ 1.5 **and** price 7d Δ between −5 % and +10 % **and** media-attention 1-mo z ≤ 0.5 | Volume rising without price or press — accumulation before the headline |

**What the LLM does and does not do (same boundary as everywhere else in this repo):** the LLM
never decides whether a signal fires. After the rules fire, one `defi_brief` call per flagged
signal writes the human explanation: what the data shows, which news storylines (if any) explain
it, what would invalidate it. ~1–5 calls/day on the `analysis`-grade model — negligible cost.

**Honesty clause:** this measures inflow, it does not forecast 2027. The History tab (§7) scores
every flag against T+7 / T+30 price follow-through so the user can see whether these inflow
definitions actually led price in *this* cycle, and retune thresholds.

---

## 1. Scope

**In (v1 of this module):**
- Daily collection of the series in §0 into Postgres with 90-day backfill on first run.
- Deterministic signal rules → `defi_signals` rows with `rule_trace` and news provenance.
- `defi_brief` LLM narration per flagged signal (versioned prompt, golden fixtures, `make eval`).
- **One notification channel** (Telegram bot — see §8; this lifts the PRD §4 "no notifications"
  non-goal for this module only, by explicit user request).
- Dashboard: sixth view "DeFi Inflow" + Settings → DeFi page + History → DeFi tab.
- Follow-through outcomes (T+1/7/30 token price) via the existing nightly outcomes job.

**Universe (decided 2026-10-04):**
- **ETH** itself.
- **Ethereum-mainnet DeFi protocols with a token**, auto-resolved from DefiLlama.
- **Pinned non-DeFi ERC-20s** the user names — **QNT (Quant Network)** first.
- **Ethereum L2s as chains**: **Arbitrum** (token ARB), **Base** (no token; proxy COIN equity),
  **Robinhood Chain** (no token; launched 2026-07-01 on Arbitrum Orbit; proxies HOOD equity and
  ARB, which receives 10 % of the chain's net revenue). L2-native DeFi protocols join the
  protocol universe when `universe.l2_chains` lists their chain.
- Not in: other L1s, Solana, BNB Chain, non-Ethereum ecosystems.

**Out (unchanged non-goals):** no trading, no wallet connection, no on-chain transactions, no
real-time (<1 h) alerts, no paid data APIs.

---

## 2. Where it sits in the architecture (02 §1–§3)

Same two apps + database. Additions only:

```
worker/newswatch_worker/
├── defi/
│   ├── universe.py        # resolve watch universe (auto from DefiLlama + user pins/excludes)
│   ├── collectors/
│   │   ├── defillama.py   # protocols, chain TVL, stablecoins, fees, dex volumes
│   │   ├── coingecko.py   # prices / volume / mcap for ETH + universe tokens
│   │   ├── coinmetrics.py # ETH exchange flows (community API)
│   │   ├── bigdata.py     # MCP client (reuses sources/mcp_connector.py session code):
│   │   │                  #   ETF-flow wire extraction + sentiment/attention tearsheets + entity resolution
│   │   └── etf_flows.py   # Farside HTML table parser — FALLBACK only when bigdata.py has no wire for a day
│   ├── features.py        # z-scores, deltas, MCap/TVL, TVL-in-ETH, share-of-chain
│   ├── rules.py           # deterministic signal rules → rule_trace (NO LLM)
│   └── scan.py            # DEFI_SCANNING stage orchestrator
├── llm/defi_brief.py      # `defi-brief-v1` prompt + parsing
└── notify/telegram.py     # tails defi_signals (and optionally recommendations), idempotent
```

**Cycle state machine** gains one stage:

```
PENDING → INGESTING → TRIAGING → ANALYZING → TRIGGERING → PM_SCANNING → DEFI_SCANNING → SUMMARIZING → DONE
```

`DEFI_SCANNING` is skipped entirely when `settings['defi'].enabled = false` (mirrors
`PM_SCANNING`). It is **daily by data, not by clock**: every cycle runs the stage, but the stage
only collects and scores when a UTC date exists in the sources that has no `defi_metrics_daily`
row yet. Three cycles a day therefore cost one collection, and a crashed cycle re-runs it
idempotently. Default anchor: the **12:30 Asia/Bangkok** cycle is the one that normally finds
new data (DefiLlama daily points close at 00:00 UTC = 07:00 Bangkok and land a few hours later;
US ETF flows post after the US close ≈ 04:00–06:00 Bangkok). The 07:00 cycle may see the
previous day's partial point and skip; that is the intended behavior, not a bug.

Why a stage and not a separate APScheduler job: it keeps "run cycle now" meaningful for this
module too, keeps the digest able to carry a DeFi strip, and reuses crash-resume for free.

## 2b. Bigdata.com integration (verified live in the planning session, 2026-10-04)

The repo already ships a generic MCP connector adapter (arch §4b) and a seeded, disabled
[Bigdata.com](https://bigdata.com) source. This module uses the same server for **four** jobs, all
through the one connector token (`secrets["mcp_connector_token:{source_id}"]`), so enabling the
connector in Settings → MCP Connectors turns all four on. Each job is also individually
switchable in `settings['defi'].bigdata` (§4) because every call consumes Bigdata.com credits.

| Job | Tool | What was verified | Role in this module |
|---|---|---|---|
| **B1 — ETF flow series** | `bigdata_search` (fast mode: `keyword.any_of=["Ether ETFs"]` in HEADLINE, `category=news`, 14-day timestamp window) | Returned one **MT Newswires – Crypto** wire per US trading day, e.g. *"US-Traded Ether ETFs Post $55 Million in Net Outflows on Thursday"*, body: *"combined net outflows of $55.4 million on Thursday, according to … SoSoValue. Fidelity Ethereum Fund (FETH) led the outflows with $23.5 million, followed by …"*. 10 consecutive trading days came back in one call. | **Primary source** for `etf_netflow_usd` (total) and per-fund rows (`etf_netflow_usd:ETHA`, `:FETH`, `:ETHE`, …). Extraction is **regex-first** (`combined net (in|out)flows of \$([\d.]+) (million|billion)` + the `TICKER) … with $X million` pattern), with a `haiku`-tier structured-output call only when the regex fails on a wire. The published wire date is "yesterday's" US session: the day is taken from the body ("on Thursday") relative to the wire timestamp, not from the timestamp itself. Farside parser runs only for days with no wire. |
| **B2 — Entity resolution** | `find_securities` / `find_entities` | `Aave` → **`C49D02`** (Aave Sagl, owner of the AAVE token — resolved by the smart-search audit); `Quant Network` → **`7D21F7`** (Quant Network Ltd., owner of the QNT token); Robinhood → **`BB036E`**, Coinbase → **`D69946`** (both resolved by smart-search audits — the equity proxies for Robinhood Chain and Base); `ETHA` → **`S67GK5`** (iShares Ethereum Trust ETF); `Uniswap` resolves to its European ETPs (`6V01KF`, `PWOWL1`), not to Uniswap Labs; `Ethereum` does **not** resolve as a `product` entity. | `defi_assets.bigdata_entity_id` (nullable). Resolved once at universe-build time, user-overridable in Settings. Assets without an entity fall back to keyword filters on `symbol` + `name`. |
| **B3 — Sentiment & media attention** | `bigdata_sentiment_tearsheet(rp_entity_id)` | For `C49D02`: `sentiment {current 0.06, baseline −0.08, momentum 0.14, zscore_1mo 0.51, zscore_1qt 0.69}`, `media_attention {momentum_pct −14.0, zscore_1mo 0.02, zscore_1qt 0.94}`, `document_count 83`, plus a cited narrative. | Daily metrics `media_sentiment`, `media_sentiment_z1m`, `media_attention_z1m`, `media_attention_z1q` → the `STEALTH_INFLOW` attention gate and the `CROWDED` caution (§0). Called only for assets with an entity **and** in the top `bigdata.tearsheet_top_n` (default 15) by provisional inflow score, so cost scales with signal, not universe size. |
| **B4 — Narrative evidence for `defi_brief`** | `bigdata_search` (fast mode: `entity.any_of=[id]` or keyword fallback, `category=news`, 7-day window, `max_chunks 8`) | Aave query returned dated, sourced chunks: V4 deposits crossing $1 B, TVL +13.7 % to $27.4 B, the DAO buyback, the MiCA yield-ban dispute, a third-party adapter exploit — i.e. exactly the catalyst *and* invalidation material the brief needs. | Chunks are passed to `defi-brief-v1` alongside the dashboard's own storylines; each cited chunk is stored in `defi_signals.brief.evidence[]` with `source`, `timestamp`, `url` so the card can link out. Only for flagged signals (1–5/day). |

Also available but **not** used in v1: `bigdata_events_calendar` (earnings dates for COIN /
BMNR as catalyst context — fits a later "catalyst calendar" strip), `bigdata_screen_companies`
(no crypto-token universe), and the open-web lane (not needed; indexed news covers it).

**Cost envelope** (from the live calls' `metadata.usage`): a 10-chunk search ≈ 1–2 k
`premium_news_tokens`; a tearsheet is a single call. Daily: 1 search (B1) + ≤ 15 tearsheets (B3) +
≤ 5 searches (B4) + the connector's own `max_calls_per_cycle` news pulls. Each job's daily cap
lives in settings and the stage records `bigdata_calls` / `bigdata_tokens` in `cycles.stats` so
the health strip shows spend.

**Why this is better than scraping for B1:** a wire service with a fixed sentence template is far
more stable than a web page's HTML, carries the per-fund breakdown, is dated, and comes through
the connector the repo already has. The remaining fragility is template drift in the MT Newswires
copy, which the regex-then-LLM fallback absorbs; the Farside parser remains as a second fallback.

---

## 3. Data model additions (03 — new §2.16–§2.20, Prisma owns migrations)

```sql
-- 2.16 watch universe (auto-resolved + user-curated)
CREATE TABLE defi_assets (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind            text NOT NULL CHECK (kind IN ('eth','protocol','token','chain')),
                                                -- 'token' = ERC-20 w/o TVL (QNT); 'chain' = L2 (Arbitrum, Base, Robinhood)
  slug            text NOT NULL UNIQUE,         -- 'ethereum' | DefiLlama protocol slug | 'qnt' | DefiLlama chain name
  proxy_tickers   text[] NOT NULL DEFAULT '{}', -- instruments to show/notify for a chain: Arbitrum {ARB}, Base {COIN}, Robinhood {HOOD, ARB}
  contract_address text,                        -- ERC-20 address (QNT: 0x4a220e6096b25eadb88358cb44068a3248254675)
  symbol          text NOT NULL,                -- 'ETH','AAVE','LDO',...
  name            text NOT NULL,
  category        text,                         -- DefiLlama category: Lending, Dexes, Liquid Staking, ...
  coingecko_id    text,                         -- for price series
  bigdata_entity_id text,                       -- RavenPack rp_entity_id (§2b B2), NULL = keyword fallback
  yfinance_symbol text,                         -- 'ETH-USD','AAVE-USD' — reuses outcomes job (arch §7)
  chains          text[] NOT NULL DEFAULT '{}',
  pinned          boolean NOT NULL DEFAULT false,   -- user said "always track"
  excluded        boolean NOT NULL DEFAULT false,   -- user said "never flag"
  auto            boolean NOT NULL DEFAULT true,    -- came from the DefiLlama auto-universe
  last_seen_at    timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now()
);

-- 2.17 one row per asset per metric per UTC day; the only write path for collectors
CREATE TABLE defi_metrics_daily (
  asset_id    uuid NOT NULL REFERENCES defi_assets(id) ON DELETE CASCADE,
  metric      text NOT NULL,     -- 'tvl_usd','tvl_eth','fees_usd','dex_volume_usd','price_usd','volume_usd',
                                 -- 'mcap_usd','etf_netflow_usd','etf_netflow_usd:<FUND>','exchange_netflow_eth',
                                 -- 'stablecoin_supply_usd','chain_tvl_share_pct',
                                 -- 'media_sentiment','media_sentiment_z1m','media_attention_z1m','media_attention_z1q'
  day         date NOT NULL,     -- UTC day the point describes
  value       numeric NOT NULL,
  source      text NOT NULL,     -- 'defillama','coingecko','coinmetrics','bigdata','farside'
  fetched_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (asset_id, metric, day)             -- the dedupe key; collectors upsert on it
);
CREATE INDEX ON defi_metrics_daily (metric, day DESC);

-- 2.18 flagged signals (the module's "recommendations")
CREATE TABLE defi_signals (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cycle_id        uuid NOT NULL REFERENCES cycles(id),
  asset_id        uuid NOT NULL REFERENCES defi_assets(id),
  signal_class    text NOT NULL,   -- ETH_INFLOW | ETF_STREAK | PROTOCOL_INFLOW | STEALTH_INFLOW | ROTATION
  as_of_day       date NOT NULL,   -- the UTC day of data that fired it
  score           numeric NOT NULL,            -- composite inflow score (rules.py)
  features        jsonb NOT NULL,              -- every input value + z-score used
  rule_trace      jsonb NOT NULL,              -- each check: pass/fail/value/threshold (04 §6 style)
  brief           jsonb,                       -- defi_brief output: summary, catalysts[], invalidation, confidence
  prompt_version  text,
  model           text,
  dedupe_key      text NOT NULL UNIQUE,        -- sha256(asset_id | signal_class | window_bucket)
  notified_at     timestamptz,                 -- notifier bookkeeping; NULL = not yet sent
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON defi_signals (created_at DESC);

CREATE TABLE defi_signal_analyses (            -- news provenance, same shape as pm_opportunity_analyses
  signal_id    uuid REFERENCES defi_signals(id) ON DELETE CASCADE,
  analysis_id  uuid REFERENCES analyses(id)    ON DELETE CASCADE,
  PRIMARY KEY (signal_id, analysis_id)
);

-- 2.19 follow-through, filled by the nightly outcomes job
CREATE TABLE defi_outcomes (
  signal_id     uuid PRIMARY KEY REFERENCES defi_signals(id) ON DELETE CASCADE,
  entry_price   numeric,
  ret_1d numeric, ret_7d numeric, ret_30d numeric,
  tvl_7d_after_pct numeric,                    -- did the inflow persist?
  status        text NOT NULL DEFAULT 'pending', -- pending|partial|complete|unavailable
  attempts      int NOT NULL DEFAULT 0,
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- 2.20 notification ledger (one row per send attempt; makes "did it reach me" debuggable)
CREATE TABLE notifications (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  channel     text NOT NULL,                   -- 'telegram'
  ref_table   text NOT NULL,                   -- 'defi_signals' | 'recommendations'
  ref_id      uuid NOT NULL,
  status      text NOT NULL,                   -- sent|failed
  error       text,
  sent_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (channel, ref_table, ref_id)          -- never double-send
);
```

Derived view `defi_hit_rates_v`: per `signal_class` and per `category`, share of signals with
`ret_7d > 0` / `ret_30d > 0`, median return, count — same idea as `hit_rates_v`.

**Dedupe windows:** `window_bucket` = `floor(epoch / (dedup_window_hours*3600))`, default 72 h for
protocol classes, 24 h for `ETF_STREAK` (a streak is news every day it extends, but only once per
day). Re-running a cycle can never double-insert (UNIQUE `dedupe_key`), same guarantee as
`pm_opportunities`.

**Secrets (arch §9 pattern, no schema change):** `secrets.telegram_bot_token`,
`secrets.coingecko_api_key` (Demo key — free, required by CoinGecko even on the free tier). Both
settable in the UI, masked, env fallback `TELEGRAM_BOT_TOKEN` / `COINGECKO_API_KEY`, excluded
from export.

---

## 4. `settings['defi']` (05 — new §3c)

```json
{
  "enabled": true,
  "anchor_cycle_id": "midday",
  "universe": {
    "mode": "auto",
    "pinned_tokens": [
      { "slug": "qnt", "symbol": "QNT", "name": "Quant", "coingecko_id": "quant-network",
        "contract_address": "0x4a220e6096b25eadb88358cb44068a3248254675", "bigdata_entity_id": "7D21F7" }
    ],
    "min_tvl_usd": 100000000,
    "require_token": true,
    "l2_chains": [
      { "slug": "Arbitrum",  "proxy_tickers": ["ARB"],         "token_coingecko_id": "arbitrum" },
      { "slug": "Base",      "proxy_tickers": ["COIN"],        "token_coingecko_id": null },
      { "slug": "Robinhood", "proxy_tickers": ["HOOD", "ARB"], "token_coingecko_id": null }
    ],
    "include_l2_protocols": true,
    "categories_exclude": ["CEX", "Bridge", "Chain"],
    "max_assets": 60
  },
  "lookback_days": 90,
  "backfill_days": 90,
  "thresholds": {
    "eth_inflow":       { "min_confirming": 2, "etf_5d_z": 1.5, "exch_netflow_7d_z": -1.5, "stable_7d_pct": 2.0, "tvl_eth_7d_z": 1.0 },
    "etf_streak":       { "min_days": 5, "min_5d_sum_usd": 500000000 },
    "protocol_inflow":  { "tvl_7d_pct": 15, "fees_7d_pct": 20, "volume_7d_pct": 30 },
    "stealth_inflow":   { "tvl_7d_pct": 15, "max_price_7d_pct": 5, "mcap_tvl_below_median": true },
    "rotation":         { "share_7d_pts": 1.0 },
    "l2_inflow":        { "tvl_eth_7d_z": 1.0, "stable_7d_pct": 3.0, "volume_7d_pct": 30 },
    "token_accumulation": { "turnover_7d_z": 2.0, "price_7d_pct": 10, "min_story_magnitude": 0.6 },
    "token_quiet_bid":    { "turnover_7d_z": 1.5, "price_7d_pct_min": -5, "price_7d_pct_max": 10, "attention_z1m_max": 0.5 }
  },
  "dedup_window_hours": { "default": 72, "ETF_STREAK": 24 },
  "max_signals_per_day": 8,
  "brief_enabled": true,
  "bigdata": {
    "etf_flows": true,
    "entity_resolution": true,
    "tearsheets": true,
    "tearsheet_top_n": 15,
    "brief_evidence": true,
    "max_calls_per_day": 30
  }
}
```

- `anchor_cycle_id` only labels which scheduled cycle is *expected* to find new data (for the
  health strip); every cycle still runs the stage (§2).
- `universe.mode`: `"auto"` = all DefiLlama protocols with `Ethereum` in `chains`, a real token
  `symbol`, TVL ≥ `min_tvl_usd`, category not excluded, capped at `max_assets` by TVL — plus
  anything `pinned`, minus anything `excluded`. `"curated"` = `pinned` rows only.
- `universe.l2_chains`: each becomes a `kind='chain'` asset scored by `L2_INFLOW` only. The
  DefiLlama chain `slug` must match its `/v2/chains` name exactly (**builder: confirm the
  Robinhood Chain slug in `defi-probe`** — it is indexed, but the exact name was not verifiable
  from this sandbox). With `include_l2_protocols = true`, protocols whose `chains` include a listed
  L2 also enter the protocol universe (so Base-native or Robinhood-native DeFi tokens are covered).
- `universe.pinned_tokens`: non-DeFi ERC-20s tracked as `kind='token'`. They skip every
  TVL/fee rule and are scored only by the two token classes (§0). Seeded with QNT; more are added
  from Settings → DeFi by symbol (resolved against CoinGecko + Bigdata.com, contract address shown
  for confirmation so a look-alike ticker can't slip in).
- `bigdata.*`: each §2b job is independently switchable; all four are no-ops when the seeded
  Bigdata.com connector row is disabled or has no token (never dialed — same FR-I6 guarantee as
  ingestion). `max_calls_per_day` is a hard cap across all four jobs.
- `settings['llm'].tiers` gains `"defi_brief": { "model": "<sonnet id>", "reasoning": "low" }`
  and `"defi_extract": { "model": "<haiku id>", "reasoning": "off" }` (B1 regex fallback only).
- `settings['notifications']` (new key, 05 §3d):

```json
{
  "channel": "routine",
  "telegram": { "enabled": false, "chat_id": "", "quiet_hours_bangkok": ["23:00", "07:00"],
                "daily_heartbeat": true },
  "email":    { "enabled": false, "to": "" },
  "send": { "defi_signals": true, "recommendations": true, "recommendations_min_confidence": 0.6,
            "digest_summary": false }
}
```

---

## 5. Collection & features (worker)

**Politeness:** same rules as sources (arch §4): 1 req/s/host, 20 s timeout, 2 retries with
jittered backoff, `Retry-After` honored. Collector failure never fails the cycle; it marks the
collector `failing` in a `defi_collector_health` entry inside `cycles.stats` and the stage scores
with whatever series are fresh (rule_trace records `missing_inputs`).

**Call budget per day (why this is free-tier safe):**

| Collector | Calls/day | Notes |
|---|---|---|
| DefiLlama `/protocols` | 1 | one payload covers the whole universe's TVL + changes |
| DefiLlama `/v2/historicalChainTvl/Ethereum` | 1 | |
| DefiLlama `stablecoincharts/Ethereum` | 1 | |
| DefiLlama `/overview/fees/ethereum`, `/overview/dexs/ethereum` | 2 | per-protocol `change_7d` included |
| CoinGecko `/coins/markets?category=…` + `/coins/ethereum` | 2–4 | Demo tier: 10k/month, 100/min |
| Coin Metrics community `asset-metrics` (eth, daily) | 1 | 1,000 req / 10 min per IP |
| Bigdata.com B1 ETF-flow wire search | 1 | one 14-day-window call returns every trading day's wire |
| Bigdata.com B3 tearsheets | ≤ 15 | top-N by provisional score only |
| Bigdata.com B4 brief evidence | ≤ 5 | flagged signals only |
| Farside ETH ETF page | 0–1 | fallback only for a day with no wire — see §9 risks |

**Backfill:** first run pulls `backfill_days` of history where the source offers it (DefiLlama
chain TVL / stablecoins / `protocol/{slug}` history, Coin Metrics daily, CoinGecko
`market_chart?days=90`, Farside full table). Without history there are no z-scores, so the stage
refuses to score until ≥ 30 days exist per metric (`rule_trace.insufficient_history`).

**features.py** (pure functions, unit-tested on fixtures): `pct_change(series, n)`,
`zscore(series, lookback)`, `tvl_in_eth = tvl_usd / price_usd`, `mcap_tvl = mcap_usd / tvl_usd`,
`chain_share_pct = protocol_tvl / eth_chain_tvl`, `streak_len(etf_netflow)`.

---

## 6. LLM: `defi-brief-v1` (04 — new §12)

Called **only** for signals that already passed the rules. Input: asset, signal class, features
table, rule_trace, up to 5 storyline summaries from `analyses` whose `analysis_topics` match
the seeded "Ethereum & DeFi" topic or whose `result.tickers` mention the asset symbol (reuse
`polymarket/match.py`'s matching approach), and up to 8 dated Bigdata.com evidence chunks
(§2b B4) when the connector is enabled. Output JSON (structured-output enforced, repair retry,
budget guard — all via the existing `llm/client.py`):

```json
{
  "summary": "2–3 sentences: what the inflow data shows, in plain language",
  "catalysts": [{"story_key": "...", "relevance": "high|medium|low", "note": "..."}],
  "evidence": [{"source": "MT Newswires - Crypto", "timestamp": "...", "url": "...", "quote": "..."}],
  "inflow_type": "institutional|onchain_organic|incentive_driven|unclear",
  "invalidation": "what would make this a false positive (e.g. TVL from a points program ending)",
  "confidence": 0.0
}
```

`inflow_type = incentive_driven` is advisory color only — it does not un-flag the signal, but the
card shows it prominently because mercenary-capital TVL spikes are the classic false positive.
Golden fixtures: 6 (one per class + one `incentive_driven` case) in `worker/tests/fixtures/defi/`.

**Seeded watch topic (05 §6.2 addition) — "Ethereum & DeFi"**, sensitivity 0.65, keywords:
`Ethereum, ETH ETF, staking ETF, Pectra, Fusaka, Glamsterdam, L2, restaking, DeFi, Aave, Uniswap,
Lido, EigenLayer, stablecoin bill, GENIUS Act, tokenization, BitMine, SharpLink, Quant Network,
QNT, Overledger, tokenized deposits, The Clearing House`.

| Market | Sector | Tickers | Polarity |
|---|---|---|---|
| GLOBAL | Ether spot | ETH-USD | +1 |
| GLOBAL | L2 tokens | ARB-USD | +1 |
| US | Spot ETH ETF | ETHA, FETH | +1 |
| US | Crypto equities / L2 operators | COIN, HOOD, BMNR | +1 |

Keywords also gain `Arbitrum, Base chain, Robinhood Chain, tokenized stocks, Orbit`. Because
COIN and HOOD sit in the mappings, Base and Robinhood Chain news already yields equity
recommendations through the existing rules engine — and, per decision 4 (§11), those are now
notified too.

This makes ETH news flow through the *existing* triage → analysis → rules path today, so the
module's news provenance works from day one and the existing outcomes job already handles
`ETH-USD` (yfinance).

---

## 7. Dashboard (web)

**New view `/defi` — "DeFi Inflow"** (FR-V6):
1. **ETH strip** at top: four stat tiles (ETF 5d net, exchange netflow 7d, stablecoin supply 7d Δ,
   TVL-in-ETH 7d Δ) each with its z-score and a 90-day sparkline; "last data day" badge.
2. **Signals feed**: cards for the latest flagged signals — asset, class chip, score, the brief's
   summary, `inflow_type` badge, catalysts linking to the news items, "why it fired" expander that
   renders `rule_trace` row by row, outbound links to DefiLlama and CoinGecko pages.
3. **Leaderboard**: the whole universe sorted by composite inflow score, columns TVL, 7d TVL Δ,
   7d fees Δ, 7d price Δ, MCap/TVL, share Δ; row click → asset detail drawer with 90-day charts.
4. Advisory disclaimer, as on every view.

**Settings → DeFi**: enable toggle, universe mode + floors, pin/exclude asset picker (search by
symbol, resolves against DefiLlama slug + CoinGecko id), threshold editors per signal class with
**"what would have fired in the last 90 days"** preview (runs `rules.py` over stored metrics —
the same preview pattern the Rules page already has), CoinGecko key (masked), collector Test
buttons via `source_tests`.

**Settings → Notifications**: Telegram bot token (masked), chat id, "Send test message", quiet
hours, which event types to send.

**History → DeFi tab**: `defi_hit_rates_v` table per class/category, scatter of score vs ret_30d,
and per-signal rows with follow-through.

**Digest page**: a "DeFi inflow" strip (count of new signals, top asset) like the Polymarket strip.

API routes: `GET /api/defi/overview`, `GET /api/defi/signals?class=&asset=&cursor=`,
`GET /api/defi/signals/:id`, `GET /api/defi/universe`, `PATCH /api/defi/assets/:id`
(pin/exclude), `POST /api/defi/preview` (threshold dry-run), CRUD `/api/config/defi`,
`/api/config/notifications`, `POST /api/config/notifications/test`.

---

## 8. Notifications — scheduled Claude Routine first, Telegram deferred (revised 2026-10-04)

The user's ask is explicitly "be notified daily." Telegram was the first choice but BotFather
failed to create the bot, so the channel for now is a **Claude Code Routine**: a scheduled cloud
session that runs the daily scan and delivers the result into the Claude app, with a push
notification and an email on completion (the same pattern as the user's existing BMNR weekly,
macro-watch and chip-screener Routines).

**Live today (created 2026-10-04):** Routine *"DeFi Inflow Radar daily"*, cron
`CRON_TZ=Asia/Bangkok 24 12 * * *` (12:24 Bangkok, just after the DefiLlama UTC-day close and the
US ETF-flow wires land), fresh session per fire, Bigdata.com connector attached, push + email on.
Until Phases D1–D4 exist, the Routine *is* the module: Claude performs the §0 collection and
applies the §0 thresholds by hand each day, using the Bigdata.com jobs in §2b (ETF-flow wire
extraction, entity news, sentiment tearsheets) plus DefiLlama/CoinGecko where the cloud
environment's network policy allows them. Its prompt mirrors §0–§2b and this doc is its source
of truth; when thresholds change here, update the Routine's prompt (`update_trigger`).

**Network note for the Routine:** the cloud environment currently denies `api.llama.fi`,
`stablecoins.llama.fi`, `api.coingecko.com` and `farside.co.uk`. The Routine falls back to
Bigdata.com wires and web search for those figures and says so in its run log. Allowing those
hosts in the environment's Network access settings (Custom → Allowed domains) upgrades the daily
numbers from quoted-in-news to first-party.

**Memory: an Obsidian vault, not the knowledge graph (user decision 2026-10-04).** The user's
Neo4j graph is reserved for the semiconductor work and must not be mixed with crypto. The Routine
keeps all state in `vault/defi-radar/` — an Obsidian vault committed to the repo on the
`radar-vault` branch (one daily note, one note per fired signal, one living note per asset; see
`vault/defi-radar/Radar Home.md` and `Templates/`). Each run starts by reading yesterday's daily
note so it can say what changed, and ends with a commit + push of the new notes. The user opens
the folder in Obsidian or pulls the branch with Obsidian Git. When the worker exists (D1+),
`defi_signals` becomes the source of truth and a small exporter writes the same vault notes from
Postgres, so the vault keeps working as the human-readable history either way.

**Once the worker exists (D3):** the in-repo notifier becomes the primary channel and the Routine
is reduced to a reader of `defi_signals` (or retired). Channel options the notifier will support,
in order of preference:

1. **Telegram bot** — retry BotFather later (`/newbot` from the official @BotFather account; the
   error was most likely a transient or a username collision, as usernames must end in `bot` and
   be globally unique). Setup: paste the token into Settings → Notifications (stored in
   `secrets.telegram_bot_token`, masked, env fallback `TELEGRAM_BOT_TOKEN`), message the bot once,
   click "Detect chat id", click "Send test message".
2. **Email** via the user's Gmail connector / SMTP — zero setup, already proven by the other
   Routines.
3. **Claude Routine** as above — always available as the fallback.

**Message content** (identical across channels, one message per signal, sent at the end of
`DEFI_SCANNING`):

```
🟢 STEALTH_INFLOW · AAVE (Aave) · score 2.4
TVL +18% 7d ($27.4B) · fees +22% · price +3% · MCap/TVL 0.09 (below median)
Attention z 0.0 — not yet in the press.
Brief: Aave V4 deposits crossed $1B in September; buyback program ongoing;
MiCA yield-ban dispute is the stated invalidation.
Data day 2026-10-03 · defillama.com/protocol/aave · open in dashboard →
```

Stock recommendations from the existing pipeline (decision 4) are sent by the same notifier after
`TRIGGERING`, one message per BUY/SELL with `confidence ≥ recommendations_min_confidence`
(WATCH rows are batched into one line), formatted `📈 BUY · PTT.BK · conf 0.72 · topic: Oil
supply shocks · <one-line reasoning> · open →`. Same ledger, same at-most-once guarantee.

Message rules: emoji by class (🟢 inflow classes, 🔵 ETH classes, 🟣 token classes, 🟠 L2 classes,
📈/📉 stock BUY/SELL, ⚠️ when the `CROWDED` caution applies), max 8 messages/day
(`max_signals_per_day`), a daily "no signals today" heartbeat at the anchor cycle so silence is
distinguishable from a dead worker (toggle), quiet hours respected by deferring to the next cycle,
Telegram's 4096-char limit enforced by truncating the brief, `disable_web_page_preview=true` so
links don't bloat the chat.

## 9. Risks & honest caveats

| Risk | Mitigation |
|---|---|
| **ETF-flow wire template drift** (MT Newswires rewords the daily item) | Regex-first, `haiku` structured extraction second, Farside HTML parser third; a day with no value from any path is recorded as missing and `ETH_INFLOW` runs on the other inputs (`rule_trace.missing_inputs`) |
| **Bigdata.com credits / connector disabled** | Every B1–B4 job is optional; the module degrades to DefiLlama + CoinGecko + Coin Metrics + Farside with attention gates skipped (trace says so). Daily call cap in settings; spend shown in the health strip |
| **QNT has no TVL** — the DeFi rules are blind to it | Separate `token` kind with its own two classes (§0) built on turnover, price and attention; the Bigdata.com entity (`7D21F7`) is rich (Clearing House selection, UK tokenised-deposit pilots, whale transfers, listings), so news linkage is strong even though on-chain depth is thin. Honest limit: the Sept 2026 move would have fired `TOKEN_ACCUMULATION` on the *day after* the Clearing House news, not before it |
| **Entity gaps** (Ethereum has no product entity; Uniswap resolves to ETPs, not the protocol) | `bigdata_entity_id` is nullable and user-editable; keyword fallback on symbol + name for search; tearsheets simply unavailable for unresolved assets |
| Coin Metrics community tier may not expose the exact exchange-flow metric names | Verify at build start; fallback is to drop exchange flow from v1 and keep the other three ETH inputs |
| TVL inflow from incentive programs (points, emissions) looks like real inflow | `STEALTH_INFLOW` requires MCap/TVL below median; brief classifies `incentive_driven`; History tab will show whether those flags underperform so the user can raise thresholds |
| 90-day z-scores in a trending market fire constantly | `max_signals_per_day` cap, 72 h dedupe window, and the preview tool to tune before enabling notifications |
| CoinGecko Demo key quota | ~5 calls/day ≈ 150/month of a 10,000 cap — fine; fail closed if 429 |
| This repo's sandbox cannot reach the REST APIs | DefiLlama / CoinGecko / Coin Metrics shapes were confirmed from documentation only; **Bigdata.com was exercised live** (§2b). The build must start with a `make defi-probe` that hits each REST endpoint from the user's machine and prints the field names |

---

## 10. Build phases (each committed with verification evidence, per CLAUDE.md)

### Phase D1 — Data layer & collectors
- Prisma migration for §3 tables; `settings['defi']` + `settings['notifications']` seeds; seeded
  "Ethereum & DeFi" topic + mappings; `defi_brief` tier added to `settings['llm']`.
- `defi/universe.py`, five collectors (incl. `bigdata.py` B1 + B2), `features.py`; CLI
  `newswatch defi-collect [--backfill]` and `newswatch defi-probe`; enable the seeded Bigdata.com
  connector with the user's token.
- ✅ Verify: probe prints live field names from each source on the user's machine; backfill
  populates ≥ 30 days for every metric for ETH and ≥ 20 protocols; B1 wire extraction reproduces
  the 10 known September 2026 daily totals from §2b (fixture test) and the extracted series
  matches Farside's totals for the overlap days within rounding; re-running collect inserts 0 new
  rows (`SELECT count(*)` unchanged); killing mid-collect then re-running is clean; with the
  connector disabled, zero Bigdata.com calls appear in logs.

### Phase D2 — Rules engine & cycle stage
- `defi/rules.py` + `defi/scan.py`; `DEFI_SCANNING` state wired into `cycle.py` and `--dry`;
  `dedupe.py` gains `defi_signal_dedupe_key`; B3 tearsheets collected for the provisional top-N
  before the attention-gated rules run.
- Unit tests per rule on synthetic series; "what would have fired" runner over the backfilled 90 d.
- ✅ Verify: a full cycle produces `defi_signals` rows with complete `rule_trace`; disabling
  `settings['defi'].enabled` skips the stage; two cycles on the same data day produce no new rows.

### Phase D3 — LLM brief, news linkage, Telegram
- `llm/defi_brief.py` (`defi-brief-v1`), fixtures, `make eval` extended; signal ↔ analysis
  matching plus B4 Bigdata.com evidence chunks; `notify/telegram.py` + `notifications` ledger +
  secrets wiring.
- ✅ Verify: a flagged signal arrives on the phone within the cycle with a working deep link;
  re-running the cycle sends nothing twice; bogus bot token surfaces in the health strip; set
  `monthly_budget_usd=0.01` → signals still fire, cards show "brief unavailable (budget)".

### Phase D4 — Dashboard & settings
- `/defi` view, Settings → DeFi and → Notifications, History → DeFi tab, digest strip, API routes.
- ✅ Verify: pin a protocol in Settings → next cycle scores it; threshold preview matches what the
  stage actually fires; export/import round-trip is a no-op and contains no tokens; all times
  Asia/Bangkok; disclaimer present.

### Phase D5 — Outcomes & calibration
- `defi_outcomes` filled by the nightly job (CoinGecko or yfinance `-USD` symbols); hit-rate view.
- Optional: extend backfill to 365 d and run the rules over 2025–2026 to pick thresholds with
  evidence before 2027.
- ✅ Verify: backdated signal gets `ret_7d` populated; bogus symbol → `unavailable` after 3
  attempts; History tab shows hit rates per class.

Rough effort: D1 and D2 are the substance (one focused session each); D3–D5 one session each.

---

## 11. Decisions

**Decided 2026-10-04:**

1. ✅ **Notification channel: a daily Claude Routine for now** (BotFather failed on 2026-10-04); Telegram
   or email become the worker-side channel in D3 (§8).
2. ✅ **Universe: Ethereum ecosystem** — ETH + auto-resolved Ethereum DeFi protocols + pinned
   non-DeFi ERC-20s starting with **QNT**.
3. ✅ **L2s included as chains: Arbitrum (ARB), Base (proxy COIN), Robinhood Chain (proxies HOOD,
   ARB)**, plus their native DeFi protocols. Other L1s stay out.
4. ✅ **Notify on both** DeFi signals and the existing stock recommendations (BUY/SELL above a
   confidence floor; WATCH batched).
5. ✅ **Bigdata.com on from day one**, all four jobs (§2b), under the daily call cap.

**Still open (defaults apply if unanswered before D1):**

6. **Bigdata.com token**: the seeded connector needs the user's own Bigdata.com API token entered
   in Settings → MCP Connectors (or `BIGDATA_API_KEY`), and the public MCP endpoint URL must be
   confirmed against Bigdata.com's docs during D1 (this session reaches Bigdata.com through an
   internal connector, not the URL an external worker would dial).
7. **Paid data beyond that?** CoinGlass or a Dune query are the upgrades for exchange-flow depth;
   agree now that v1 adds no paid source beyond the Bigdata.com credits already in hand.
