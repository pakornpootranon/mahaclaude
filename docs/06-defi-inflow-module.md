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
| ETH | US spot ETH ETF **net flows** (USD m, by fund + total) | TradFi allocation; the single cleanest "new money" signal | Farside Investors page (HTML table) / SoSoValue as fallback |
| ETH | **Exchange net flow** (ETH leaving exchanges = accumulation) | Spot buyers withdrawing to custody / staking | Coin Metrics Community API, daily `FlowInExNtv` / `FlowOutExNtv` (verify metric names on community tier at build time) |
| ETH | **Stablecoin supply on Ethereum** (7d / 30d change) | Dry powder parked on-chain before deployment | DefiLlama `stablecoins.llama.fi/stablecoincharts/Ethereum` |
| ETH | **Ethereum chain TVL** in USD *and* in ETH terms | TVL/ETH-price strips the price effect; rising ETH-denominated TVL = real deposits | DefiLlama `api.llama.fi/v2/historicalChainTvl/Ethereum` + ETH price |
| ETH | Spot volume / market cap, 7d turnover | Participation confirmation | CoinGecko Demo API `/coins/ethereum` |
| DeFi token | **Protocol TVL change** 1d / 7d / 30d | Capital entering the protocol | DefiLlama `/protocols` (`change_1d`, `change_7d`, `change_1m`, `tvl`, `symbol`, `chains`, `category`) |
| DeFi token | **Fees & revenue** 7d change | Usage-driven, "real yield" inflow — harder to fake than TVL | DefiLlama `/overview/fees/ethereum` |
| DeFi token | **DEX volume** 7d change (DEX protocols only) | Activity confirmation | DefiLlama `/overview/dexs/ethereum` |
| DeFi token | **Token price, volume, market cap**; derived **MCap/TVL** | Spot demand + valuation vs. the capital it secures | CoinGecko Demo API `/coins/markets?category=decentralized-finance-defi` |
| Both | **News storylines** already analyzed by the dashboard | Catalyst attribution (upgrades, listings, treasury buys, regulation) | Existing pipeline — one new seeded watch topic |

Signal classes the rules engine can emit (each with a full `rule_trace`, like `rules.py` and
`polymarket/scan.py`):

| Class | Rule sketch (defaults; all tunable in Settings) | Reads as |
|---|---|---|
| `ETH_INFLOW` | ≥ 2 of {ETF 5d sum z ≥ 1.5, exchange netflow 7d z ≤ −1.5, stablecoin 7d Δ ≥ +2 %, ETH-TVL 7d z ≥ 1.0} | Broad money flowing into ETH |
| `ETF_STREAK` | ≥ 5 consecutive positive ETF days **and** 5d sum ≥ configurable USD floor | Institutional bid is persistent |
| `PROTOCOL_INFLOW` | TVL 7d Δ ≥ +15 % **and** (fees 7d Δ ≥ +20 % **or** volume 7d Δ ≥ +30 %) **and** TVL ≥ floor | Capital + usage arriving together |
| `STEALTH_INFLOW` | TVL 7d Δ ≥ +15 % **and** token price 7d Δ ≤ +5 % **and** MCap/TVL below its own 90d median | Money entering before the token reprices — the "early" signal |
| `ROTATION` | Protocol's share of Ethereum DeFi TVL rises ≥ 1.0 pt in 7d | Capital rotating *within* DeFi toward this protocol |

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

**Out (unchanged non-goals):** no trading, no wallet connection, no on-chain transactions, no
real-time (<1 h) alerts, no multi-chain beyond Ethereum mainnet by default (`include_l2` toggle
is designed-for, off), no paid data APIs.

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
│   │   └── etf_flows.py   # Farside HTML table parser (+ SoSoValue fallback)
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

---

## 3. Data model additions (03 — new §2.16–§2.20, Prisma owns migrations)

```sql
-- 2.16 watch universe (auto-resolved + user-curated)
CREATE TABLE defi_assets (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind            text NOT NULL CHECK (kind IN ('eth','protocol')),
  slug            text NOT NULL UNIQUE,         -- 'ethereum' | DefiLlama protocol slug ('aave','lido',...)
  symbol          text NOT NULL,                -- 'ETH','AAVE','LDO',...
  name            text NOT NULL,
  category        text,                         -- DefiLlama category: Lending, Dexes, Liquid Staking, ...
  coingecko_id    text,                         -- for price series
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
                                 -- 'mcap_usd','etf_netflow_usd','exchange_netflow_eth','stablecoin_supply_usd',
                                 -- 'chain_tvl_share_pct'
  day         date NOT NULL,     -- UTC day the point describes
  value       numeric NOT NULL,
  source      text NOT NULL,     -- 'defillama','coingecko','coinmetrics','farside'
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
    "min_tvl_usd": 100000000,
    "require_token": true,
    "include_l2": false,
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
    "rotation":         { "share_7d_pts": 1.0 }
  },
  "dedup_window_hours": { "default": 72, "ETF_STREAK": 24 },
  "max_signals_per_day": 8,
  "brief_enabled": true
}
```

- `anchor_cycle_id` only labels which scheduled cycle is *expected* to find new data (for the
  health strip); every cycle still runs the stage (§2).
- `universe.mode`: `"auto"` = all DefiLlama protocols with `Ethereum` in `chains`, a real token
  `symbol`, TVL ≥ `min_tvl_usd`, category not excluded, capped at `max_assets` by TVL — plus
  anything `pinned`, minus anything `excluded`. `"curated"` = `pinned` rows only.
- `settings['llm'].tiers` gains `"defi_brief": { "model": "<sonnet id>", "reasoning": "low" }`.
- `settings['notifications']` (new key, 05 §3d):

```json
{
  "telegram": { "enabled": false, "chat_id": "", "quiet_hours_bangkok": ["23:00", "07:00"] },
  "send": { "defi_signals": true, "recommendations": false, "digest_summary": false }
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
| Farside ETH ETF page | 1 | HTML parse; brittle by nature — see §9 risks |

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
table, rule_trace, and up to 5 storyline summaries from `analyses` whose `analysis_topics` match
the seeded "Ethereum & DeFi" topic or whose `result.tickers` mention the asset symbol (reuse
`polymarket/match.py`'s matching approach). Output JSON (structured-output enforced, repair retry,
budget guard — all via the existing `llm/client.py`):

```json
{
  "summary": "2–3 sentences: what the inflow data shows, in plain language",
  "catalysts": [{"story_key": "...", "relevance": "high|medium|low", "note": "..."}],
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
Lido, EigenLayer, stablecoin bill, GENIUS Act, tokenization, BitMine, SharpLink`.

| Market | Sector | Tickers | Polarity |
|---|---|---|---|
| GLOBAL | Ether spot | ETH-USD | +1 |
| US | Spot ETH ETF | ETHA, FETH | +1 |
| US | Crypto equities | COIN, BMNR | +1 |

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

## 8. Notifications (lifting a v1 non-goal, narrowly)

The user's ask is explicitly "be notified." The architecture already left the hook (arch §11:
"a notifier service tails the table"). Proposal: **Telegram bot**, because it is free, phone-
native, needs one HTTPS call (`sendMessage`), and the setup is ~2 minutes (create bot with
@BotFather, send it a message, read `chat_id`). LINE Notify would have been the Thai-local
choice but was discontinued in 2025; the LINE Messaging API replacement needs a channel + webhook
and is heavier than a daily digest deserves. Email is the fallback option if Telegram is
unwanted.

Mechanics: at the end of `DEFI_SCANNING` (and optionally after `TRIGGERING` for stock
recommendations, off by default) the notifier selects rows with `notified_at IS NULL`, formats one
message per signal (asset · class · score · one-line summary · dashboard deep link), respects
quiet hours by deferring, writes a `notifications` row, then sets `notified_at`. UNIQUE on the
ledger guarantees at-most-once even if the cycle re-runs. Worker-side only; `web` never sends.

---

## 9. Risks & honest caveats

| Risk | Mitigation |
|---|---|
| **Farside is an HTML page, not an API** — layout changes break the parser | Parser is one function with a fixture test; on parse failure the ETF series is marked stale and `ETH_INFLOW` rules run without it (recorded in `rule_trace.missing_inputs`); SoSoValue scrape as fallback; manual CSV import as last resort |
| Coin Metrics community tier may not expose the exact exchange-flow metric names | Verify at build start; fallback is to drop exchange flow from v1 and keep the other three ETH inputs |
| TVL inflow from incentive programs (points, emissions) looks like real inflow | `STEALTH_INFLOW` requires MCap/TVL below median; brief classifies `incentive_driven`; History tab will show whether those flags underperform so the user can raise thresholds |
| 90-day z-scores in a trending market fire constantly | `max_signals_per_day` cap, 72 h dedupe window, and the preview tool to tune before enabling notifications |
| CoinGecko Demo key quota | ~5 calls/day ≈ 150/month of a 10,000 cap — fine; fail closed if 429 |
| This repo's sandbox cannot reach these APIs | All endpoint shapes above were confirmed from documentation/search only; the build must start with a `make defi-probe` that hits each endpoint from the user's machine and prints the field names |

---

## 10. Build phases (each committed with verification evidence, per CLAUDE.md)

### Phase D1 — Data layer & collectors
- Prisma migration for §3 tables; `settings['defi']` + `settings['notifications']` seeds; seeded
  "Ethereum & DeFi" topic + mappings; `defi_brief` tier added to `settings['llm']`.
- `defi/universe.py`, four collectors, `features.py`; CLI `newswatch defi-collect [--backfill]`
  and `newswatch defi-probe`.
- ✅ Verify: probe prints live field names from each source on the user's machine; backfill
  populates ≥ 30 days for every metric for ETH and ≥ 20 protocols; re-running collect inserts 0 new
  rows (`SELECT count(*)` unchanged); killing mid-collect then re-running is clean.

### Phase D2 — Rules engine & cycle stage
- `defi/rules.py` + `defi/scan.py`; `DEFI_SCANNING` state wired into `cycle.py` and `--dry`;
  `dedupe.py` gains `defi_signal_dedupe_key`.
- Unit tests per rule on synthetic series; "what would have fired" runner over the backfilled 90 d.
- ✅ Verify: a full cycle produces `defi_signals` rows with complete `rule_trace`; disabling
  `settings['defi'].enabled` skips the stage; two cycles on the same data day produce no new rows.

### Phase D3 — LLM brief, news linkage, Telegram
- `llm/defi_brief.py` (`defi-brief-v1`), fixtures, `make eval` extended; signal ↔ analysis
  matching; `notify/telegram.py` + `notifications` ledger + secrets wiring.
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

## 11. Decisions needed from the user before D1

1. **Notification channel:** Telegram (recommended, §8) — or email / LINE Messaging API?
2. **Universe:** auto from DefiLlama with pins/excludes (recommended) — or a hand-curated list?
   If curated, which tokens to start with (e.g. AAVE, UNI, LDO, MKR/SKY, EIGEN, ENA, PENDLE, CRV)?
3. **Include ETH L2 ecosystem tokens** (ARB, OP) now, or keep strictly Ethereum mainnet (default)?
4. **Also notify on stock recommendations** from the existing pipeline, or DeFi signals only
   (default: DeFi only)?
5. **Paid data later?** If the free ETF-flow scrape proves too brittle, CoinGlass or a Dune query
   are the paid upgrades; agree now that v1 stays free-only.
