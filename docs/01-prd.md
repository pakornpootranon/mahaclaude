# PRD — News-to-Action Monitoring Dashboard

**Product name:** Mahachai Market Watch (codename `newswatch`)
**Version:** 1.1 (v1 spec — rev adds LLM/API-key settings, MCP connectors, dashboard topic quick-add & sector scoping, Polymarket opportunities)
**Owner:** Single user (personal tool)
**Status:** Approved for build via Claude Code

---

## 1. Problem statement

Market-moving news breaks continuously across US, Thai (SET), and global markets. The user
currently has no single place that (a) watches configurable themes across many news sources,
(b) interprets each item's likely impact on specific sectors and tickers, and (c) converts that
into a clear, reasoned, advisory recommendation (buy / sell / watch) they can act on manually.

## 2. Product summary

A locally-run, single-user web dashboard that ingests news a few times a day, uses the Claude API
to classify each item's sector impact and direction, and surfaces **advisory recommendations**
with confidence and reasoning. Everything about *what* is monitored — sources, topics, keyword
sensitivity, sector→ticker mappings, and trigger thresholds — is configurable in the UI.

**The system never places trades.** It is an advisory research tool only. Every recommendation
screen must carry a "not financial advice / advisory only" note.

## 3. Goals

- G1: Never miss a configured theme. If a watched topic appears in an enabled source, it must show up in the next digest cycle.
- G2: Every actionable item explains itself — headline → theme matched → sector impact → direction → suggested action → reasoning, all visible in ≤ 2 clicks.
- G3: Full user control of the monitoring surface without code changes (sources, topics, mappings, thresholds).
- G4: Honest self-assessment — track what prices did after each recommendation so the user can judge signal quality.
- G5: Cheap to run — batch digest cycles (default 3×/day), tiered LLM usage, free data sources by default.

## 4. Non-goals (v1)

- No order execution or broker integration (architecture must not preclude it later). Likewise no Polymarket bet placement — opportunity flagging only.
- No push/LINE/email/Telegram notifications (v2 candidate).
- No multi-user accounts, no authentication (localhost-only binding by default).
- No real-time (<5 min) streaming ingestion.
- No portfolio management / position sizing.
- No mobile app (responsive web is enough).

## 5. Users & context

One user, based in Bangkok (Asia/Bangkok, UTC+7), trading on daily horizons across:

| Market | Instruments | Notes |
|---|---|---|
| US | NYSE/NASDAQ stocks, sector ETFs (XLE, XLF, XLK, SMH, …) | US session = night in Bangkok |
| Thailand | SET/mai stocks, SET sector indices | Local session daytime |
| Global | Region-aware themes (EU, China, Japan, commodities, FX-sensitive sectors) | Mapped to tradable US/TH proxies |

All dashboard times display in Asia/Bangkok. Digest cycles default to **07:00** (post-US-close
wrap), **12:30** (SET midday), **20:30** (pre-US-open) — editable in settings.

## 6. Core concepts (ubiquitous language)

| Term | Definition |
|---|---|
| **Source** | A configured news input: RSS feed, API (Finnhub/NewsAPI/…), Bigdata.com, or social adapter. Enable/disable per source. |
| **News item** | One deduplicated article/post ingested from a source. |
| **Watch topic** | A user-defined theme (name + description + keywords + sensitivity) e.g. "Fed rate decisions", "chip export controls", "oil supply shocks". |
| **Mapping** | A watch topic's impact table: which sectors/tickers/ETFs it affects, per market, with default direction polarity (e.g. oil price ↑ → energy producers bullish, airlines bearish). |
| **Analysis** | The LLM's structured judgment on a news item: topics matched, sectors impacted, direction, magnitude, confidence, reasoning. |
| **Recommendation** | An actionable output derived from one or more analyses that passed the trigger rules: `BUY` / `SELL` / `WATCH` on specific tickers/sectors, with confidence and reasoning. |
| **Trigger rules** | User-set thresholds deciding when an analysis becomes a recommendation (min confidence, min magnitude, dedup window, per-topic sensitivity). |
| **Digest cycle** | One scheduled run: ingest → analyze → recommend → summarize. Produces a Digest. |
| **Digest** | Per-cycle rollup: market mood, top themes, the cycle's recommendations. |
| **Outcome** | Post-hoc price tracking of a recommendation (T+1d, T+3d, T+7d returns) to score signal quality. |
| **MCP connector** | A configured Model Context Protocol server (e.g. Bigdata.com remote MCP) the worker can call as a data/news source. Enable/disable per connector in Settings. |
| **Narrative** | Synonym for watch topic in the UI — user-defined themes are labeled "Topics & narratives". |
| **Sector scope** | User controls that narrow which sectors/tickers may appear in recommendations: per-mapping-row enable toggles plus a global sector allowlist/blocklist. |
| **PM opportunity** | A Polymarket prediction market flagged because the LLM's estimated probability diverges from the market-implied price by ≥ the configured edge threshold (with liquidity and confidence floors). Advisory only — the system never places bets. |

## 7. Functional requirements

### 7.1 Ingestion (FR-I)

- FR-I1: Poll all enabled sources at each digest cycle; per-source override cadence allowed.
- FR-I2: Source types in v1: **RSS** (generic), **Finnhub news API**, **NewsAPI.org**, **Reddit (subreddit RSS)**, and **MCP connector** (generic MCP-client adapter; Bigdata.com is the reference implementation). Benzinga-class paid feeds and X/Twitter remain pluggable later without schema changes.
- FR-I6: MCP connectors are first-class configurable sources: add/remove connectors (server URL, transport, auth env var, tool mapping), enable/disable per connector, health tracked like any source. A disabled connector is never called.
- FR-I3: Deduplicate by URL canonicalization + title similarity (see architecture doc §5).
- FR-I4: Keep raw title/summary/body-extract, source, published-at, fetched-at, language.
- FR-I5: Ingestion failures degrade gracefully: a dead source is flagged in the UI, never blocks the cycle.

### 7.2 Analysis & recommendation (FR-A)

- FR-A1: Two-tier LLM pipeline (spec: `04-llm-pipeline.md`): cheap triage pass filters irrelevant items; deep pass produces structured analysis for survivors.
- FR-A2: Analysis references the user's watch topics and mappings — the LLM is told what the user cares about; it may also flag "unconfigured but significant" items.
- FR-A3: Trigger rules convert analyses to recommendations deterministically in code (not by the LLM): confidence ≥ topic threshold, magnitude ≥ global floor, not a duplicate of a still-open recommendation within the dedup window.
- FR-A4: A recommendation names ≥1 concrete instrument (ticker or ETF) per impacted market where a mapping exists; sector-only when no mapping exists.
- FR-A5: Every recommendation stores full provenance: news item(s), analysis JSON, prompt version, model, rule evaluation trace.

### 7.3 Configuration (FR-C)

All of the following editable in the dashboard Settings UI, persisted to Postgres, applied on the next cycle (no restart):

- FR-C1: Sources — add/remove/enable/disable; URL/API key; per-source poll cadence; test-fetch button.
- FR-C2: Watch topics — CRUD; name, description, keywords/phrases, per-topic sensitivity (min confidence to trigger), enabled flag.
- FR-C3: Mappings — per topic: list of (market, sector, tickers[], polarity) rows; editable inline.
- FR-C4: Trigger rules — global confidence floor, magnitude floor, dedup window (hours), max recommendations per cycle, quiet-list of tickers to never recommend.
- FR-C5: Schedule — digest cycle times (Asia/Bangkok), enable/disable individual cycles.
- FR-C6: LLM settings — **Claude API key entered/rotated in the UI** (stored in DB, always displayed masked, `.env` value as fallback), per-tier model selection (triage/analysis/digest/polymarket) from an editable model list, and per-tier **reasoning level** (extended thinking: off / low / medium / high → thinking-token budgets), max items per cycle, monthly budget cap in USD with hard stop.
- FR-C7: Config export/import as a single JSON file (backup + seeding). Export NEVER includes the API key or any secret.
- FR-C8: MCP connectors page — CRUD connectors, enable/disable toggle, test-call button, per-connector tool configuration (which MCP tool to call and how to map results to news items).

### 7.4 Dashboard views (FR-V) — all five are v1 must-haves

- FR-V1 **Action feed**: reverse-chronological stream of recommendations. Card: action badge (BUY/SELL/WATCH), tickers, sector, market flag, confidence, one-line reasoning, source headline links, timestamp. Filters: market, action, topic, confidence, date range. Click → full detail with provenance.
- FR-V2 **Digest summary**: one page per cycle: market mood (bullish/bearish/mixed + one-paragraph LLM synthesis), top 3–5 themes, recommendations table, stats (items ingested / triaged in / analyzed / triggered). Navigable cycle history.
- FR-V3 **Topic/sector board**: grid of watch topics/narratives: status chip (quiet / active / hot based on hits in last 48h), recent matched headlines, impacted tickers, last-triggered time. Click-through to topic config. **Plus, directly on the board (not buried in Settings):**
  - FR-V3a **Quick-add topic/narrative**: an always-visible "+ Add topic" card opens an inline dialog (name, description, keywords, sensitivity) with an optional "Suggest mappings" button that asks the LLM to propose sector/ticker mapping rows for the user to review, edit, and accept — never auto-applied. New topic is live next cycle.
  - FR-V3b **Sector scoping inline**: each topic card exposes its mapping rows with per-row enable/disable toggles, so the user can narrow which sectors/tickers a topic may recommend without deleting the mapping. A global sector allowlist/blocklist (rules setting) further constrains all recommendations.
- FR-V4 **History & outcomes**: table of past recommendations with T+1/T+3/T+7 price returns of the named tickers, hit-rate summary per topic and per action type, filterable. Price data via yfinance (US and `.BK` Thai tickers). Includes a Polymarket tab: past PM opportunities with subsequent market-price movement and resolution status.
- FR-V5 **Polymarket opportunities**: a dedicated view (plus a strip on the digest page) listing flagged prediction markets. Card: market question, current YES price, LLM estimated probability, edge (points), direction (YES/NO looks cheap), liquidity/volume, confidence, reasoning, link to the market on polymarket.com, related news storylines when news-driven. Discovery is both **news-driven** (markets matched to analyzed storylines) and a per-cycle **scan** of top active markets by volume. Filters: edge size, category, liquidity, discovery mode. Advisory only — clearly labeled, no bet placement.

### 7.5 System (FR-S)

- FR-S1: "Run cycle now" manual button.
- FR-S2: Health strip: last cycle time/status, per-source last success, LLM spend month-to-date vs cap.
- FR-S3: All persistent state in Postgres; app is stateless and restart-safe; mid-cycle crash must not corrupt data (cycle is resumable or cleanly re-runnable).

## 8. Acceptance criteria (v1 done means)

1. `docker compose up` on the user's Mac brings up dashboard + worker + Postgres; dashboard on `http://localhost:3000`.
2. With seed config (see `05-config-schema.md`), a manual cycle run ingests from ≥3 live free sources, produces analyses, and renders ≥1 digest with recommendations end-to-end.
3. Adding a new watch topic + mapping in the UI affects the next cycle without restart.
4. Killing the worker mid-cycle and re-running leaves no duplicate recommendations.
5. Outcomes page shows T+1 returns for recommendations older than one trading day.
6. Monthly LLM budget cap halts analysis (not ingestion) when reached, with a visible banner.
7. Rotating the Claude API key in Settings takes effect on the next LLM call without restart; the key is never rendered unmasked and never appears in config export.
8. Toggling the Bigdata.com MCP connector off removes it from the next cycle's ingestion (verified in cycle stats); toggling on restores it.
9. Adding a topic via the board's quick-add dialog (including LLM-suggested mappings after user edit/accept) makes it live on the next cycle; disabling a mapping row prevents that sector from being recommended for that topic.
10. A cycle produces a Polymarket opportunities list where every flagged market shows edge ≥ threshold and passes liquidity/confidence floors; each links to the live market.

## 9. Success metrics (post-launch, user-judged)

- ≥80% of recommendations rated "reasonable given the news" by the user in the first month.
- Zero missed occurrences of configured topics present in enabled sources (spot-checked).
- LLM spend within configured cap.

## 10. Open risks

| Risk | Mitigation |
|---|---|
| Free news APIs rate-limit or rot | Adapter isolation + health strip + easy source swap in UI |
| LLM overconfident on thin news | Confidence calibration guidance in prompts; outcomes page keeps the user honest |
| Thai-language news quality | v1 ingests English-language Thai sources (Bangkok Post, Nation); Thai NLP is v2 |
| Duplicate storylines across sources inflate signal | Cross-source story clustering at triage (see LLM spec §4) |
| LLM probability estimates on Polymarket are systematically miscalibrated | High default edge threshold (10 pts), liquidity floor, PM outcomes tab tracks estimate-vs-resolution so the user can judge calibration; thin/ambiguous markets excluded by prompt rules |
| Polymarket API shape changes | Isolated `polymarket/` client module; Gamma API endpoints verified at implementation time |

---
*Companion docs: `00-CLAUDE.md` (build plan), `02-architecture.md`, `03-data-model.md`, `04-llm-pipeline.md`, `05-config-schema.md`.*
