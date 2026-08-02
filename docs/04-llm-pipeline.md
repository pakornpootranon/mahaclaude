# LLM Pipeline Spec — Mahachai Market Watch (codename `newswatch`, Claude API)

Two-tier news pipeline + digest synthesis + Polymarket estimation + ad-hoc mapping suggestions.
All calls via the official `anthropic` Python SDK from the worker (mapping suggestions are the one
web-triggered call — see §11). Every prompt is versioned (`triage-v1`, `analyze-v1`, `digest-v1`,
`pm-estimate-v1`, `suggest-mappings-v1`); version strings are stored with results so prompt
changes never corrupt idempotency.

---

## 1. Model tiers & defaults

| Tier | Purpose | Default model (configurable, FR-C6) | Default reasoning | Output |
|---|---|---|---|---|
| 1 — Triage | Relevance filter + storyline clustering, batched | `claude-haiku-latest`-class (cheapest current Haiku) | off | per-item relevant/irrelevant + story_key |
| 2 — Analysis | Deep impact analysis per storyline | `claude-sonnet-latest`-class (current Sonnet) | low | AnalysisResult JSON |
| 3 — Digest | Cycle synthesis | same Sonnet-class model | low | mood + paragraph + themes |
| 4 — PM estimate | Polymarket probability estimation (§9) | same Sonnet-class model | medium | PmEstimate JSON |

Model IDs are **settings values**, not hardcoded — Claude model names change over time; the
Settings → LLM page holds the exact IDs. `worker/llm/client.py` reads them per call.

**Why these levels differ per tier**: reasoning scales with how much per-call judgment a tier
needs, and inversely with how many times it runs per cycle. Triage is a mechanical
relevant/irrelevant classification run over every ingested item, so `off` is right — extended
thinking would multiply cost across the highest call volume in the pipeline for little quality
gain. Analysis and digest both make a genuine judgment call (impact direction/magnitude, or
which storylines are worth surfacing) but run only a handful of times per cycle each, so the
reasoning spend is affordable — hence both above `off`. PM estimate is genuine independent
forecasting (arguably harder than analysis's structured impact scoring), but it can run once per
*candidate market* — up to `scan_top_n` (default 20) plus every news-matched market — so it's
capped at `medium` rather than `high` to avoid multiplying a high reasoning budget across that
many calls in one cycle.

**Reasoning level** (FR-C6): each tier has a user-configurable extended-thinking level mapped by
`client.py` to a thinking-token budget: `off` = extended thinking disabled, `low` = 2,048,
`medium` = 8,192, `high` = 16,384 thinking tokens. Thinking tokens are billed as output tokens —
the spend ledger must count them, and the Settings UI shows an estimated per-cycle cost delta when
the user raises a level. If the selected model doesn't support extended thinking, `client.py`
silently degrades to `off` and flags it in the health strip. Temperature constraints below apply
only when thinking is off (the API requires default temperature with extended thinking).

**API key resolution** (arch §9): `client.py` reads the key from the `secrets` table on every
call, falling back to `ANTHROPIC_API_KEY` env — rotation in Settings needs no restart. On 401,
mark key invalid in health strip; never log the key.

Cost-control invariants (enforced in `client.py`, not in prompts):

- Hard monthly budget cap (settings `llm.monthly_budget_usd`) — checked before every call (arch §8).
- `llm.max_items_per_cycle` cap applied before triage, newest-first **within** a topic-hint
  bucket but round-robined **across** topic-hint buckets first (`triage.py`'s
  `_round_robin_by_topic_hint`, keyed off each topic's `keywords` as a cheap pre-triage hint —
  not authoritative relevance) so one high-volume topic can't consume the whole per-cycle item
  cap and starve every other topic's coverage; overflow items marked `triage_status='skipped_budget'`.
- Max 4096 output tokens per call; temperature 0 for triage/analysis, 0.3 for digest.
- Use structured outputs / tool-use JSON schema enforcement where the SDK supports it; otherwise parse with strict JSON extraction + one repair retry.

## 2. Shared context block

Both triage and analysis prompts receive a rendered `WATCH_CONTEXT` built from the DB each cycle:

```
## Watch topics (user-configured)
1. id=<uuid8> "Fed rate decisions" — <description>. Keywords: rate cut, FOMC, dot plot, Powell…
2. id=<uuid8> "Chip export controls" — <description>. Keywords: …
...

## Markets in scope
US (NYSE/NASDAQ, sector ETFs), TH (SET/mai, ".BK" tickers), GLOBAL (map to US/TH tradable proxies).
```

Mappings are given **only** to the analysis tier (topic-filtered, to keep tokens down).

## 3. Tier 1 — Triage (`triage-v1`)

Batched: up to 40 items per call, fields per item: `idx, source, title, summary (≤300 chars), published_at`,
plus `provider_tags` when the item carries `analysis_hints` (e.g. Bigdata.com entity/sector tags) —
the prompt notes these are hints from the news provider, not ground truth.

### System prompt

```
You are a financial news triage assistant for a personal market-monitoring dashboard.
The user watches specific topics (listed below). Your job for EACH numbered item:
1. relevant: true if the item plausibly relates to any watch topic OR is clearly major
   market-moving news (central bank surprise, war, major default, systemic event) even if
   no topic matches. Minor corporate PR, listicles, opinion pieces, and routine price
   recaps are NOT relevant.
2. matched_topic_ids: watch topic ids matched (empty if relevant only as "major unconfigured news").
3. story_key: cluster near-duplicate storylines. Reuse an existing story_key from the
   "already assigned" list when the item covers the same underlying event; otherwise mint a new
   short slug like "fed-cut-signal-0731". Same event ≠ same topic — cluster by event.
Be strict: when in doubt on relevance, mark irrelevant. Output JSON only.

<WATCH_CONTEXT>

## Already assigned story keys this cycle
<story_key>: <representative title>
...
```

### Output schema (enforced)

```json
{ "items": [ { "idx": 0, "relevant": true, "matched_topic_ids": ["a1b2c3d4"],
               "story_key": "fed-cut-signal-0731" } ] }
```

Post-processing (code): write `triage_status` + `story_key` to `news_items`; items with
`relevant=false` are kept (for audit) but never analyzed.

## 4. Storyline selection for tier 2

Per `story_key` with ≥1 relevant item: pick primary item (longest body_excerpt, else earliest),
attach up to 4 additional titles/sources as corroboration. **One tier-2 call per storyline**, not
per item — this is the main cost lever and prevents duplicate-storyline signal inflation (PRD risk table).

Storylines are then round-robined by matched topic (`analyze.py`'s `_round_robin_by_topic`)
before the ANALYZING loop runs them: one storyline per matched topic first, then a second pass,
etc. Storylines matching no topic ("unconfigured but significant") get their own fair turn too.
Without this, DB scan order could let one topic's storylines exhaust a budget/item cap mid-cycle
before every watched topic got even one analysis.

## 5. Tier 2 — Analysis (`analyze-v1`)

### 5.1 System prompt

```
You are a market impact analyst for a personal advisory dashboard (NOT financial advice;
the user reviews everything manually). Analyze ONE news storyline and output structured JSON.

Rules:
- Ground every judgment in the provided text. Do not invent facts, numbers, or tickers.
- event_polarity: +1 if the event pushes the matched topic's framing "positive" direction,
  -1 if negative, 0 if unclear. (Each topic's mapping table defines what +1 means per sector;
  you only judge the EVENT direction relative to the topic, e.g. for "Oil supply shocks",
  a supply disruption = +1.)
- magnitude 0–1: how market-moving for the affected sectors. 0.2 = routine, 0.5 = notable,
  0.8 = major, 1.0 = historic. Most news is ≤0.4.
- confidence 0–1: your confidence in the direction call, NOT in the news being true.
  Calibrate honestly: single-source rumors cap at 0.5; official announcements can reach 0.9+.
- impacts: use ONLY sectors/tickers present in the provided mapping rows. If a genuinely
  impacted sector has no mapping row, put it in unmapped_sectors instead with a note.
- horizon: 'days' | 'weeks' | 'months' — over what horizon the impact likely plays out.
- reasoning: 2-4 sentences, plain language, mention the mechanism (why this news moves
  these sectors). This text is shown to the user verbatim.

<WATCH_CONTEXT>

## Mapping rows for matched topics
topic="Oil supply shocks": [US/Energy +1: XLE,CVX,XOM] [US/Airlines -1: JETS,DAL] [TH/Energy +1: PTT.BK,TOP.BK] ...
```

### 5.2 Output schema — `AnalysisResult` (stored verbatim in `analyses.result`)

```json
{
  "story_key": "opec-cut-0731",
  "matched_topics": [ { "topic_id": "a1b2c3d4", "match_strength": 0.9 } ],
  "event_polarity": 1,
  "magnitude": 0.55,
  "confidence": 0.75,
  "horizon": "weeks",
  "impacts": [
    { "market": "US", "sector": "Energy", "direction": "bullish",
      "tickers": ["XLE", "CVX"], "strength": 0.6 },
    { "market": "US", "sector": "Airlines", "direction": "bearish",
      "tickers": ["JETS"], "strength": 0.4 },
    { "market": "TH", "sector": "Energy", "direction": "bullish",
      "tickers": ["PTT.BK", "TOP.BK"], "strength": 0.5 }
  ],
  "unmapped_sectors": [ { "sector": "Shipping", "note": "bunker fuel costs rise" } ],
  "reasoning": "OPEC+ announced a deeper-than-expected production cut...",
  "caveats": "Single-day announcement; compliance historically partial."
}
```

Top-level `event_polarity`, `magnitude`, `confidence` are copied to columns for indexing/rules.

## 6. Rules engine (deterministic code — NOT the LLM) (`worker/rules.py`)

For each impact row of each analysis:

```
effective_confidence = confidence × strength
action:
  direction == 'bullish' → BUY
  direction == 'bearish' → SELL
  (downgrade to WATCH when magnitude < rules.watch_floor OR horizon == 'months')
trigger iff ALL:
  topic.enabled
  mapping row for (topic, market, sector) has enabled = true   # FR-V3b per-row scoping
  sector passes rules.sector_scope (allowlist empty = all; blocklist always wins)
  effective_confidence ≥ max(topic.sensitivity, rules.global_confidence_floor)
  magnitude ≥ rules.global_magnitude_floor
  ticker ∉ rules.quiet_tickers
  dedupe_key not already present (window bucket = rules.dedup_window_hours)
  cycle recommendation count < rules.max_recommendations_per_cycle (highest effective_confidence first)
"Unconfigured but significant" analyses (no matched topic): trigger only as WATCH, and only if
  magnitude ≥ rules.unconfigured_magnitude_floor (default 0.7).
```

Every evaluation writes `rule_trace` JSON (each condition → pass/fail + values) for provenance (FR-A5).

## 7. Tier 3 — Digest synthesis (`digest-v1`)

Input: cycle stats, all triggered recommendations (compact), top storylines including relevant-
but-not-triggered ones. Output schema:

```json
{ "market_mood": "mixed",
  "synthesis": "One paragraph, ≤120 words, plain language...",
  "top_themes": [ { "theme": "Fed pivot odds rising", "why": "...", "item_count": 6 } ] }
```

Prompt instruction highlights: mention triggered actions explicitly; note anything big that did
NOT trigger and why (e.g., below confidence floor) — this keeps the user aware of borderline calls.
If `cycle.budget_hit`, digest is generated without this call: mood `mixed`, synthesis =
templated "LLM budget reached; N storylines unanalyzed", top_themes from topic-match counts.

## 8. Failure handling

| Failure | Behavior |
|---|---|
| JSON parse failure | One repair retry ("Your last output was invalid JSON: <err>. Re-emit valid JSON only."); then mark storyline `analysis_failed`, continue cycle |
| API 429/5xx | Exponential backoff ×3 (SDK default), then skip item/storyline, count in `cycles.stats.errors` |
| Budget exceeded mid-cycle | Stop LLM calls; remaining items `skipped_budget`; digest per §7; `cycles.budget_hit = true` |
| Hallucinated ticker (not in mapping rows) | Code strips it; if impact row has no valid tickers left, becomes sector-only (FR-A4) |

## 9. Tier 4 — Polymarket probability estimation (`pm-estimate-v1`)

Runs in the `PM_SCANNING` cycle stage (arch §3). Candidate markets come from two deterministic
discovery paths (code, `worker/polymarket/`):

- **News-driven** (`match.py`): for each storyline analyzed this cycle, keyword/entity match
  against active `pm_markets` questions (token overlap + category heuristics); matched pairs
  carry the storyline's AnalysisResult into the prompt.
- **Scan** (`scan.py`): top N active markets by 24h volume (settings `polymarket.scan_top_n`,
  default 20) not already estimated within `polymarket.reestimate_hours` (default 24).

Pre-filter before any LLM call (code): `liquidity_usd ≥ min_liquidity`, not resolving within
`min_days_to_end` (default 2 days — avoids near-certain markets), YES price within
`[price_floor, price_ceiling]` (default 0.05–0.95).

### System prompt

```
You are a forecaster estimating the true probability of a prediction-market question for a
personal advisory dashboard (NOT betting advice; nothing is executed automatically).

Rules:
- Estimate P(YES) as a decimal 0–1 based ONLY on: the question text and resolution criteria,
  today's date, the provided recent news storylines (if any), and well-established base rates.
- Do NOT anchor on the current market price; you will be shown it only as "market_price" and
  must form your estimate before comparing.
- confidence 0–1: how well-informed your estimate is. Cap at 0.5 when the question hinges on
  information you plausibly lack (private polls, insider process, very recent events not in
  the provided news). Questions with ambiguous resolution criteria: set skip=true.
- reasoning: 2–4 sentences citing the decisive factors. Shown to the user verbatim.

## Today
<date, Asia/Bangkok>

## Related news storylines from this cycle (may be empty)
<compact AnalysisResult summaries>
```

### Output schema — `PmEstimate`

```json
{ "market_id": "0x...", "skip": false, "skip_reason": null,
  "est_probability": 0.62, "confidence": 0.55,
  "reasoning": "Polls have tightened 4 points since...", "key_uncertainties": "..." }
```

### Deterministic edge rules (code, `scan.py` — NOT the LLM)

```
edge_points = |est_probability − market_price| × 100
side        = est_probability > market_price ? 'YES' : 'NO'   # which side looks cheap
flag iff ALL:
  skip == false
  edge_points ≥ polymarket.min_edge_points          (default 10)
  confidence  ≥ polymarket.min_confidence           (default 0.55)
  liquidity_usd ≥ polymarket.min_liquidity_usd      (default 10_000)
  dedupe_key not present (window bucket = polymarket.dedup_window_hours, default 48)
  cycle PM flag count < polymarket.max_opportunities_per_cycle (default 5, highest edge first)
```

Every evaluation writes `rule_trace`. All PM calls go through the same budget guard and spend
ledger (`purpose='pm_estimate'`); budget-hit skips PM_SCANNING the same way it skips analysis.

## 10. Evaluation hooks (build with the pipeline, not after)

- `worker/tests/fixtures/` — 15+ frozen news fixtures with expected triage/analysis outcomes
  (golden tests, tolerant on numeric fields ±0.15, strict on direction and topic matching).
- `make eval` runs fixtures against live API, prints a drift report. Run before changing any prompt;
  bump prompt version on any change. Include ≥5 PM-estimate fixtures (strict on skip/side, ±0.15 on probability).

## 11. Ad-hoc call — mapping suggestions (`suggest-mappings-v1`, FR-V3a)

Triggered from the topic quick-add dialog via `POST /api/topics/suggest-mappings` (the one LLM
call initiated by `web` — implement in a small route handler using the same key resolution and
ledger table, `purpose='suggest_mappings'`). Input: draft topic name/description/keywords + the
markets-in-scope block. Output: proposed mapping rows in exactly the `mappings` shape
(`[{market, sector, tickers[], polarity, note}]`, ≤8 rows, only liquid/well-known tickers,
`.BK` suffix for SET). **Never auto-applied** — the dialog renders them as editable checked rows;
only user-accepted rows are saved (with `suggested_by='llm'`).
