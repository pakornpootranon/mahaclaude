# Build Plan — Mahachai Market Watch (codename `newswatch`)

Derived from the spec pack (`CLAUDE.md` + `docs/01`–`05`). Each phase is completed, verified
against its checklist, and committed before the next begins. Ordering follows the dependency
chain: data layer → ingestion → LLM/rules → read UI → settings UI → Polymarket → outcomes →
hardening.

## Phase 1 — Skeleton & data layer
**Goal:** runnable monorepo with the canonical schema and a walkable (no-op) cycle state machine.

- Repo layout per `docs/02` §2: `web/` (Next.js 14+ App Router, TS, Tailwind, shadcn/ui, Prisma),
  `worker/` (Python 3.12, uv, APScheduler, SQLAlchemy), `scripts/setup.sh` (native Postgres + npm),
  Makefile, `.env.example`.
- Prisma schema implementing `docs/03` exactly (sources, cycles, news_items, topics, mappings,
  analyses, recommendations, outcomes, digests, settings, secrets, llm_calls, source_tests,
  pm_markets, pm_opportunities, pm_outcomes, views).
- Seed script with the full seed config from `docs/05` §6 (verify feed URLs are live; substitute
  and log dead ones).
- Worker connects via SQLAlchemy reflection; `newswatch run-cycle --dry` creates a cycle row and
  walks PENDING → … → DONE with no-op steps.
- **Verify:** `make up && make seed` → psql shows seeded sources/topics/mappings/settings;
  dry cycle reaches DONE.

## Phase 2 — Ingestion
**Goal:** real news items in the DB, idempotently, from every v1 source type.

- `SourceAdapter` protocol + rss / finnhub / newsapi / reddit_rss adapters; canonical-URL dedupe
  (`sha256(canonical_url)` upsert); politeness rules (Retry-After, 1 req/s/host, 20 s timeout,
  jittered retries); health tracking (3 consecutive failures → `failing`).
- Generic MCP connector adapter (`docs/02` §4b): mcp SDK client, list_tools sanity check,
  args template + result mapping, per-connector call cap; seeded Bigdata.com config (disabled).
- `source_tests` async test-fetch handshake (web inserts request, worker answers) covering MCP.
- **Verify:** run-cycle ingests from ≥3 live seed sources; re-run yields zero duplicates;
  kill-mid-ingest then re-run is clean; disabled MCP connector provably never dialed.

## Phase 3 — LLM pipeline & rules engine
**Goal:** end-to-end cycle producing analyses, recommendations, and a digest with full provenance.

- `llm/client.py`: DB→env API-key resolution (re-read every call), monthly budget guard, spend
  ledger in `llm_calls` (thinking tokens counted), per-tier model + reasoning-level →
  thinking-budget mapping, structured-output enforcement + one repair retry.
- Triage (`triage-v1`, batched, story clustering) → storyline selection (one tier-2 call per
  storyline) → analysis (`analyze-v1`) — prompts verbatim from `docs/04`, versioned.
- Deterministic rules engine (`rules.py`, `docs/04` §6) incl. mapping `enabled` + `sector_scope`
  checks, `rule_trace` on every evaluation; digest synthesis (`digest-v1`); budget-hit
  degradation path (rule-only digest + banner flag).
- Golden fixtures (15+) + `make eval` drift report (`docs/04` §10).
- **Verify:** full live cycle produces analyses + recommendations with complete provenance chain;
  re-run idempotent; `monthly_budget_usd=0.01` yields graceful budget-hit digest.

## Phase 4 — Dashboard read views
**Goal:** the four news-side views usable end-to-end (Polymarket view comes in 5b).

- API route handlers per `docs/02` §6, then: Action feed (default page, filters, detail with
  provenance), Digest summary + cycle history nav, Topic/sector board with quick-add topic dialog
  (incl. LLM-suggested mappings via `suggest-mappings-v1`, never auto-applied) and inline
  per-mapping enable toggles, health strip, "Run cycle now" button.
- All times Asia/Bangkok; advisory disclaimer on feed + detail.
- **Verify:** PRD acceptance #1, #2, #9; intentional empty states; feed pagination past 50 items.

## Phase 5 — Settings UI
**Goal:** full no-code configurability — this is the product; don't rush it.

- Pages per `docs/05` §7: Sources, MCP connectors, Topics + mappings, Rules (with "what would
  have triggered" preview), Schedule, LLM (masked API-key rotate flow, per-tier model + reasoning
  selects with cost delta), Polymarket; source/connector Test buttons.
- Config export/import with diff preview (API key never exported); schedule changes picked up
  without restart.
- **Verify:** PRD acceptance #3, #7, #8; UI-added topic triggers next cycle;
  import(export(x)) is a no-op; bogus key surfaces 401 in health strip.

## Phase 5b — Polymarket module
**Goal:** PM opportunities flowing through the same cycle, advisory-only.

- `polymarket/` client (Gamma API — endpoints verified at implementation time), news-driven
  matching + top-volume scan, pre-filters (liquidity, days-to-end, price band),
  `pm-estimate-v1` prompt, deterministic edge rules with `rule_trace`, `PM_SCANNING` cycle
  stage, PM opportunities view + digest strip; PM estimate fixtures in `make eval`.
- **Verify:** PRD acceptance #10; disabling `polymarket.enabled` skips the stage entirely;
  every flagged card links to the live market.

## Phase 6 — Outcomes & history
**Goal:** honest self-assessment loop.

- Nightly outcomes job (07:30 ICT, yfinance, 3-attempt cap → `unavailable`): T+1/3/7 returns,
  direction-adjusted hit flags; PM price-drift + resolution tracking into `pm_outcomes`.
- History & outcomes page: filterable table, hit-rate aggregates per topic/action
  (`hit_rates_v`), Polymarket tab (`pm_calibration_v`).
- **Verify:** backdated recommendation gets returns + hit flags; bogus ticker marks
  `unavailable` after 3 attempts; backdated PM opportunity gets `price_1d`.

## Phase 7 — Hardening & polish
**Goal:** v1 done per PRD §8, one criterion at a time.

- Crash-resume test matrix (kill at each cycle state), structured JSON logging, `make backup`
  (pg_dump + config export), README (zero-to-running incl. free API key signup links),
  responsive pass, Lighthouse sanity.
- **Verify:** full PRD §8 acceptance list checked off in README.

## Standing rules (all phases)

- Idempotency everywhere: every write path upserts on the dedupe keys in `docs/03`; test re-runs
  constantly.
- The LLM never decides triggers — `rules.py` and `polymarket/scan.py` do.
- Claude API key is the only DB-stored secret (masked, never exported/logged); all other secrets
  are env-only.
- Prompt change ⇒ bump version string ⇒ `make eval`.
- Look up current Claude model IDs/prices and verify Gamma API + Bigdata.com MCP tool shapes at
  implementation time — they are settings values, not hardcoded.
- Boring code: two apps + one database; no queues, no Redis, no microservices.
- Commit per phase with verification evidence in the commit message.
