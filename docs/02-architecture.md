# Architecture — News-to-Action Monitoring Dashboard ("Mahachai Market Watch", codename `newswatch`)

Companion to `01-prd.md`. Target: local single-user deployment on macOS via docker-compose.

---

## 1. System overview

```
                        ┌────────────────────────────────────────────┐
                        │                docker-compose               │
                        │                                            │
  RSS feeds ──────┐     │  ┌──────────────┐      ┌────────────────┐  │
  Finnhub API ────┤     │  │  worker (py)  │      │  web (Next.js) │  │
  NewsAPI ────────┼──►  │  │  ingestion    │      │  dashboard UI  │  │
  Reddit RSS ─────┤     │  │  mcp client   │      │  + API routes  │  │
  MCP connectors ─┤     │  │  llm pipeline │      │  (read + config│  │
  (Bigdata.com…)  │     │  │  rules engine │      │   write)       │  │
  Polymarket API ─┤     │  │  polymarket   │      │                │  │
  (pluggable:     │     │  │  outcomes job │      │                │  │
   X, Benzinga…)  │     │  └──────┬───────┘      └───────┬────────┘  │
                        │         │                      │           │
  Claude API ◄──────────┼─────────┤                      │           │
  yfinance ◄────────────┼─────────┤                      │           │
                        │         ▼                      ▼           │
                        │  ┌──────────────────────────────────────┐  │
                        │  │            Postgres 16               │  │
                        │  └──────────────────────────────────────┘  │
                        └────────────────────────────────────────────┘
                                          ▲
                               http://localhost:3000 (user)
```

Two applications, one database, one compose file:

| Service | Tech | Responsibility |
|---|---|---|
| `web` | Next.js 14+ (App Router, TypeScript, Tailwind, shadcn/ui) | All five dashboard views, Settings UI, REST API routes for config CRUD and manual cycle trigger. Reads/writes Postgres via Prisma. |
| `worker` | Python 3.12 (uv-managed), APScheduler, httpx, anthropic SDK, `mcp` SDK (client), yfinance, SQLAlchemy | Digest cycles: ingest (incl. MCP connectors) → triage → analyze → rules → **polymarket scan/match** → digest. Nightly outcomes job (prices + PM tracking). |
| `db` | Postgres 16 (official image, volume-persisted) | Single source of truth. Schema owned by Prisma migrations; worker uses SQLAlchemy reflecting the same tables. |

**Why this split** (approved decision): the UI benefits from React polish; the pipeline benefits
from Python's data/LLM ecosystem. They share nothing but the database — no message queue needed
at 3 cycles/day.

## 2. Repo layout

```
newswatch/
├── docker-compose.yml
├── .env.example              # ANTHROPIC_API_KEY, FINNHUB_KEY, NEWSAPI_KEY, DATABASE_URL
├── CLAUDE.md                 # from 00-CLAUDE.md in this spec pack
├── docs/                     # this spec pack, verbatim
├── web/                      # Next.js app
│   ├── app/
│   │   ├── page.tsx                  # Action feed (default view)
│   │   ├── digests/[cycleId]/page.tsx
│   │   ├── topics/page.tsx           # Topic/sector board
│   │   ├── history/page.tsx          # History & outcomes
│   │   ├── settings/...              # sources | topics | mappings | rules | schedule | llm
│   │   └── api/...                   # route handlers, see §6
│   ├── prisma/schema.prisma          # canonical schema (03-data-model.md)
│   └── lib/
└── worker/
    ├── pyproject.toml
    ├── newswatch_worker/
    │   ├── main.py                   # APScheduler entrypoint + run-once CLI
    │   ├── cycle.py                  # orchestrates one digest cycle (state machine)
    │   ├── sources/                  # adapter per source type
    │   │   ├── base.py               # SourceAdapter protocol
    │   │   ├── rss.py
    │   │   ├── finnhub.py
    │   │   ├── newsapi.py
    │   │   ├── reddit_rss.py
    │   │   └── mcp_connector.py      # generic MCP-client adapter (Bigdata.com etc.), see §4b
    │   ├── dedupe.py
    │   ├── llm/
    │   │   ├── client.py             # anthropic wrapper: key resolution, retries, budget guard,
    │   │   │                         #   spend ledger, extended-thinking budgets per tier
    │   │   ├── triage.py             # tier-1 prompt + parsing
    │   │   ├── analyze.py            # tier-2 prompt + parsing
    │   │   ├── pm_estimate.py        # Polymarket probability-estimation prompt (04 §9)
    │   │   └── digest.py             # synthesis prompt
    │   ├── rules.py                  # analysis → recommendation (deterministic, incl. sector scope)
    │   ├── polymarket/
    │   │   ├── client.py             # Polymarket Gamma API client (markets, prices, volume)
    │   │   ├── match.py              # storyline → market matching (news-driven discovery)
    │   │   └── scan.py               # top-active-markets sweep + edge rules (deterministic)
    │   ├── outcomes.py               # yfinance T+1/3/7 backfill + PM price/resolution tracking
    │   └── db.py
    └── tests/
```

## 3. Digest cycle state machine

A cycle is a DB row (`cycles` table) moving through states; every step is idempotent so a crashed
cycle can be re-run safely (PRD acceptance #4).

```
PENDING → INGESTING → TRIAGING → ANALYZING → TRIGGERING → PM_SCANNING → SUMMARIZING → DONE
                                                                      ↘ FAILED (with error, partial results kept)
```

`PM_SCANNING` (skipped entirely when `settings['polymarket'].enabled = false`): refresh active
markets from the Polymarket API, run news-driven matching + top-volume scan, LLM probability
estimates, deterministic edge rules → `pm_opportunities` rows.

Idempotency rules:

- Ingestion upserts on `news_items.dedupe_key` — re-running never duplicates items.
- Triage/analysis write results keyed by `news_item_id` + `prompt_version` — already-analyzed items are skipped.
- Rules engine upserts recommendations on a deterministic `dedupe_key` (topic + ticker + direction + window bucket).
- A cycle re-run reuses the same `cycle_id` if the previous attempt didn't reach DONE.

Scheduling: APScheduler cron jobs in `Asia/Bangkok`, times read from `settings` at startup **and**
re-read on a settings-changed flag each minute (FR-C5, no restart). Manual runs: `web` sets
`cycles.requested_manual = true` row; worker polls for it every 15 s (no queue needed).

## 4. Source adapter contract

```python
class SourceAdapter(Protocol):
    source_type: str                       # "rss" | "finnhub" | "newsapi" | "reddit_rss" | ...
    def fetch(self, source: SourceConfig, since: datetime) -> list[RawItem]: ...
    def test(self, source: SourceConfig) -> TestResult: ...   # for Settings "test fetch" button
```

`RawItem`: `title, url, summary, body_excerpt (≤2000 chars), published_at, language, author,
analysis_hints (optional jsonb — provider-supplied entity/sector tags, e.g. from Bigdata.com)`.
Adding Bigdata.com / X / Benzinga later = one new file implementing this protocol + a
`source_type` enum value. **No schema changes.**

Per-source politeness: honor `Retry-After`, cap 1 req/s/host, 20 s timeout, 2 retries with
jittered backoff. A source failing 3 consecutive cycles → `sources.health = 'failing'` (health strip).

## 4b. MCP connector adapter (`sources/mcp_connector.py`)

A generic `SourceAdapter` that speaks MCP as a client (official `mcp` Python SDK, streamable-HTTP
transport). Each configured connector is a `sources` row with `source_type='mcp'`; its `config`
(schema in `05-config-schema.md` §4) names the server URL, the MCP tool to call, a template for
the tool arguments (may reference enabled watch-topic names/keywords), and a JSONPath-style result
mapping into `RawItem` fields. Auth tokens come from a per-connector env var, never the DB.

- **Enable/disable** is the standard `sources.enabled` flag — a disabled connector is never
  dialed (FR-I6). The Settings → MCP connectors page is a filtered view of sources with
  connector-specific fields plus a Test button (same `source_tests` handshake).
- Connection lifecycle: connect → list_tools sanity check (configured tool must exist, else
  health='failing' with a clear error) → call tool per enabled topic batch → map results → close.
  20 s per call, one connector at a time.
- **Bigdata.com reference config** ships in the seed (disabled by default until the user adds
  `BIGDATA_API_KEY`): calls its news-search tool with watch-topic queries; entity/sector tags
  returned by Bigdata.com are stored in `RawItem`-mapped `analysis_hints` to pre-seed triage.
- Cost note: connector calls may consume the provider's own credits — the per-connector
  `max_calls_per_cycle` config field caps this.

## 5. Deduplication

Two layers:

1. **Exact/URL layer (code):** `dedupe_key = sha256(canonical_url)` where canonical_url strips
   tracking params (`utm_*`, `fbclid`, …), lowercases host, removes fragments. Upsert on conflict.
2. **Story-cluster layer (cheap model, at triage):** triage batches carry titles of items already
   accepted this cycle; the model tags near-duplicate storylines with a shared `story_key` so the
   analysis tier processes each storyline once but cites all sources (see `04-llm-pipeline.md` §4).

## 6. Web API surface (Next.js route handlers)

All under `/api`, JSON, no auth (localhost). The worker never calls these — it talks to Postgres directly.

| Method & path | Purpose |
|---|---|
| `GET  /api/recommendations?market=&action=&topic=&minConfidence=&from=&to=&cursor=` | Action feed (paginated) |
| `GET  /api/recommendations/:id` | Full detail + provenance |
| `GET  /api/cycles?cursor=` / `GET /api/cycles/:id` | Digest list / digest detail |
| `POST /api/cycles/run` | Manual "run cycle now" (sets requested_manual) |
| `GET  /api/topics/board` | Topic board aggregate (status chips, recent hits, mapping rows with toggles) |
| `POST /api/topics/quick-add` | Board quick-add: create topic (+optionally accepted suggested mappings) in one call (FR-V3a) |
| `POST /api/topics/suggest-mappings` | LLM-proposed mapping rows for a draft topic — returns suggestions, applies nothing |
| `PATCH /api/mappings/:id` | Toggle/edit a mapping row inline (FR-V3b) |
| `GET  /api/polymarket/opportunities?edge=&category=&mode=&cursor=` | PM opportunities view (FR-V5) |
| `GET  /api/polymarket/opportunities/:id` | PM opportunity detail + provenance |
| `GET  /api/history?filters…` | Outcomes table + hit-rate aggregates |
| CRUD `/api/config/sources` `/topics` `/mappings` `/rules` `/schedule` `/llm` `/mcp-connectors` `/polymarket` | Settings (FR-C1..C8) — `/llm` accepts the API key write-only and returns it masked |
| `POST /api/config/sources/:id/test` | Test-fetch a source (proxies a one-shot worker script or reimplements adapter fetch in TS for RSS only; simpler: worker exposes result via `source_tests` table — web inserts request row, polls result ≤10 s) |
| `GET  /api/config/export` / `POST /api/config/import` | FR-C7 |
| `GET  /api/health` | Health strip payload |

## 7. Outcomes job

Nightly at 07:30 Asia/Bangkok (after US close): for every recommendation with missing return
fields and enough elapsed trading days, fetch adjusted closes via yfinance (`AAPL`, `PTT.BK`, …)
and store T+1/T+3/T+7 returns relative to first close at-or-after recommendation time. Direction-
adjusted "hit" = sign(return) matches recommendation direction (SELL hits on negative return).
Missing tickers (delisted/bad symbol) → `outcome_status = 'unavailable'`, never retried more
than 3 times.

Same job also tracks Polymarket opportunities: refresh current market price at T+1/T+3/T+7
(did price move toward the LLM estimate?) and, once a market resolves, record the resolution
so the PM outcomes tab can score calibration (estimate vs actual). Data in `pm_outcomes` (03 §2.14).

## 8. Budget guard & observability

- Every Claude call logs to `llm_calls` (model, tokens in/out, computed USD cost, cycle_id, purpose).
- Before each call: if month-to-date spend ≥ cap → raise `BudgetExceeded`; cycle skips remaining
  analysis, digest is generated rule-only with a "budget reached" banner flag (PRD acceptance #6).
- Worker logs: structured JSON lines to stdout (docker logs); errors also land in `cycles.error`.

## 9. Configuration & secrets

- **Claude API key is the one deliberate exception to env-only secrets** (approved decision,
  FR-C6): stored in the `secrets` table (03 §2.12), entered/rotated via Settings → LLM, always
  rendered masked (`sk-ant-…••••` last 4 chars), excluded from config export and logs. Key
  resolution order in `llm/client.py`: DB row → `ANTHROPIC_API_KEY` env fallback. Re-read on
  every call, so rotation needs no restart (PRD acceptance #7).
- All other secrets (Finnhub, NewsAPI, MCP connector tokens like `BIGDATA_API_KEY`) remain in
  `.env` only — never in the DB, never rendered back to the UI (Settings shows `set/unset`
  status). All behavioral config lives in Postgres (FR-C).
- `docker-compose.yml` mounts a named volume for Postgres data; `make backup` dumps DB +
  config-export JSON to `./backups/`.

## 10. Security posture

Localhost-only tool: `web` binds `127.0.0.1:3000`, Postgres not published to host network
(compose-internal only, except a commented-out port mapping for debugging). No auth by design
(approved). If the user ever exposes it, adding basic-auth middleware in Next.js is the v2 path.

## 11. Deferred-but-designed-for (explicit non-goals with hooks)

| Future need | Hook already in place |
|---|---|
| Broker integration | Recommendations carry structured `instrument`, `action`, `direction` — an executor service would consume the same table |
| Notifications (LINE/Telegram) | Rules engine emits a `recommendation_created` row; a notifier service tails the table |
| Paid/low-latency feeds | SourceAdapter protocol §4 |
| Additional MCP providers | Generic MCP adapter §4b — new connector = a config row, no code |
| Polymarket bet placement | `pm_opportunities` carries structured market id/side/edge — an executor would consume the same table (explicit non-goal now) |
| Multi-user | All tables single-tenant now; would need `user_id` columns + auth — accepted rework |
