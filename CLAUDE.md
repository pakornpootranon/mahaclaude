# CLAUDE.md — Build Guide for "Mahachai Market Watch" (codename `newswatch`)

> Copy this file to the repo root as `CLAUDE.md` and the rest of the spec pack into `docs/`.
> This file tells Claude Code what to build, in what order, and how to verify each phase.

## What this project is

A local, single-user news-monitoring dashboard: ingest financial news a few times a day from
configurable sources (RSS/APIs/**MCP connectors** like Bigdata.com) → Claude API classifies
sector impact → deterministic rules produce **advisory** BUY/SELL/WATCH recommendations with
reasoning → plus a **Polymarket opportunities** module flagging prediction markets where the
LLM's probability estimate diverges from market odds. Five dashboard views + rich Settings
(including in-UI Claude API key rotation, per-tier model + reasoning-level selection, and MCP
connector toggles). No trading or bet placement, no auth, no notifications in v1. Markets: US,
Thai SET, global. User timezone: Asia/Bangkok.

**Read the spec pack in `docs/` before writing code:**

| Doc | Contents |
|---|---|
| `docs/01-prd.md` | Requirements, acceptance criteria — the contract |
| `docs/02-architecture.md` | Services, repo layout, cycle state machine, adapter contract |
| `docs/03-data-model.md` | Canonical Postgres schema (Prisma owns migrations) |
| `docs/04-llm-pipeline.md` | Exact prompts, JSON schemas, rules engine, cost controls |
| `docs/05-config-schema.md` | Settings JSON schemas + full seed config |
| `docs/06-defi-inflow-module.md` | **Proposal (not built):** ETH & DeFi Inflow Radar — daily on-chain/ETF inflow signals + Telegram notify |

When spec and convenience conflict, follow the spec; if the spec is wrong/impossible, say so and
propose the fix in the PR/commit message rather than silently diverging.

## Tech constraints (decided — do not relitigate)

- `web/`: Next.js 14+ App Router, TypeScript, Tailwind, shadcn/ui, Prisma → Postgres.
- `worker/`: Python 3.12, uv, APScheduler, httpx, anthropic SDK, `mcp` SDK (client), SQLAlchemy (reflect Prisma's tables), yfinance, feedparser.
- Postgres 16 running natively on the host (no containers); web binds 127.0.0.1:3000.
- `DATABASE_URL` stays `.env`-only (needed before the DB exists to even hold a `secrets` row).
  Every other credential (`ANTHROPIC_API_KEY`, `FINNHUB_KEY`, `NEWSAPI_KEY`, MCP connector tokens
  like `BIGDATA_API_KEY`) is settable via a Settings UI into the `secrets` table (docs/02 §9,
  revised 2026-08-02 — originally the Claude key was the sole DB-backed exception); DB value
  wins over the matching `.env` var, masked display only, excluded from export/logs.
- Look up **current** Claude model IDs, prices, and extended-thinking support when implementing `settings['llm']` defaults; verify the Polymarket Gamma API endpoints and the Bigdata.com MCP tool shape at implementation time.

## Commands (implement via Makefile early in Phase 1)

```
make setup         # create db role/database, npm install, migrate, seed
make dev-web       # next dev against local Postgres
make dev-worker    # worker run-once cycle against local Postgres (worker CLI: `newswatch run-cycle`)
make migrate       # prisma migrate dev
make seed          # prisma db seed (docs/05 §6)
make test          # web unit tests + worker pytest
make eval          # worker golden-fixture LLM eval (docs/04 §10)
make backup        # pg_dump + config export → ./backups/
```

## Build phases — complete, verify, and commit each phase before the next

### Phase 1 — Skeleton & data layer
- Repo layout per `docs/02-architecture.md` §2; `scripts/setup.sh` (native Postgres + npm); Makefile; `.env.example`.
- Prisma schema implementing `docs/03-data-model.md` exactly; migrations; seed script with the full
  seed config from `docs/05-config-schema.md` §6 (verify feed URLs live; substitute dead ones and log it).
- Worker connects via SQLAlchemy reflection; `newswatch run-cycle --dry` creates a cycle row and walks
  states with no-op steps.
- ✅ Verify: `make up && make seed` then `psql` shows seeded sources/topics/mappings/settings; dry cycle reaches DONE.

### Phase 2 — Ingestion
- SourceAdapter protocol + rss/finnhub/newsapi/reddit_rss adapters; canonical-URL dedupe;
  politeness rules (arch §4); health tracking (consecutive_failures → 'failing').
- Generic MCP connector adapter (arch §4b) incl. enable/disable semantics and the seeded
  (disabled) Bigdata.com config; `source_tests` async handshake covers MCP too.
- ✅ Verify: run-cycle ingests real items from ≥3 seed sources; re-run produces zero duplicates
  (`SELECT count(*), count(DISTINCT dedupe_key)` equal); killing worker mid-ingest then re-running
  is clean; a disabled MCP connector is provably never dialed (assert zero calls in logs).

### Phase 3 — LLM pipeline & rules
- `llm/client.py` (DB→env key resolution, budget guard, spend ledger incl. thinking tokens,
  per-tier reasoning-level → thinking-budget mapping, structured-output enforcement, repair retry)
  then triage → storyline selection → analysis, prompts verbatim from `docs/04` (versioned).
- Rules engine per `docs/04` §6 (incl. mapping `enabled` + `sector_scope` checks) with full
  `rule_trace`; digest synthesis; budget-hit degradation path.
- Golden fixtures + `make eval` (docs/04 §10).
- ✅ Verify: full cycle end-to-end on live news produces analyses + ≥0 recommendations with complete
  provenance chain (recommendation → analysis JSON → news items); re-run idempotent; set
  `monthly_budget_usd=0.01` and confirm graceful budget-hit digest.

### Phase 4 — Dashboard read views
- API routes (arch §6) then: Action feed (default page, filters, detail w/ provenance),
  Digest summary + history nav, Topic/sector board **with quick-add topic dialog (incl.
  LLM-suggested mappings, docs/04 §11) and inline per-mapping enable toggles**, health strip,
  "Run cycle now".
- All times rendered Asia/Bangkok. Advisory disclaimer visible on feed + detail.
- ✅ Verify: PRD acceptance #1–2 and #9 pass; empty states look intentional; feed pagination works past 50 items.

### Phase 5 — Settings UI (configurability is the product — don't rush this)
- Sources / MCP connectors / Topics+Mappings / Rules / Schedule / LLM / Polymarket pages per
  `docs/05` §7, incl. masked API-key rotate flow, per-tier model + reasoning selects with cost
  delta, rules "what would have triggered" preview, and source/connector Test buttons; config
  export/import with diff preview (key never exported).
- Schedule changes picked up without restart (arch §3).
- ✅ Verify: PRD acceptance #3, #7, #8; add a topic in UI → next manual cycle can trigger on it;
  import(export(x)) is a no-op; rotating to a bogus key surfaces the 401 in the health strip.

### Phase 5b — Polymarket module
- `polymarket/` client (Gamma API), news-driven matching + top-volume scan, `pm-estimate-v1`
  prompt, deterministic edge rules, `PM_SCANNING` cycle stage, PM opportunities view + digest strip.
- ✅ Verify: PRD acceptance #10; disabling `settings['polymarket'].enabled` skips the stage
  entirely; every flagged card links to the live market; PM estimate fixtures pass `make eval`.

### Phase 6 — Outcomes & history
- Nightly outcomes job (arch §7, yfinance, retry cap); History & outcomes page with hit-rate
  aggregates per topic/action (`hit_rates_v`) plus the Polymarket tab (price drift toward
  estimate, resolution accuracy, `pm_calibration_v`).
- ✅ Verify: backdate a fake recommendation, run outcomes job, returns + hit flags populate; unavailable
  ticker path (bogus symbol) marks 'unavailable' after 3 attempts; a backdated PM opportunity gets
  price_1d populated.

### Phase 8 (proposed, not approved yet) — ETH & DeFi Inflow Radar
- Spec and phase breakdown (D1–D5) in `docs/06-defi-inflow-module.md`; build only after the
  §11 decisions there are answered.

### Phase 7 — Hardening & polish
- Crash-resume test matrix (kill at each cycle state), structured logging, `make backup`,
  README (setup from zero incl. free API key signup links), responsive pass, Lighthouse sanity.
- ✅ Verify: full PRD §8 acceptance list, one item at a time, checked off in README.

## Working rules for Claude Code

- Idempotency is a feature, not an optimization — every write path upserts on the dedupe keys
  defined in `docs/03`. Test re-runs constantly.
- The LLM never decides triggers; `rules.py` (docs/04 §6) and `polymarket/scan.py` (docs/04 §9)
  do. Keep that boundary clean.
- The Claude API key is the only DB-stored secret (masked always, never exported/logged); every
  other secret stays env-only and is never echoed to the UI.
- Prompt changes ⇒ bump prompt version string ⇒ run `make eval`.
- Prefer boring code; no message queues, no Redis, no microservices — two apps and a database.
- Commit per phase with the phase's verification evidence in the commit message.
