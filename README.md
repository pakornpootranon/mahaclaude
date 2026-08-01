# Mahachai Market Watch

*(internal codename `newswatch` — retained for the CLI, Python package, and database identifiers throughout this repo)*

A local, single-user financial news-monitoring dashboard. It ingests news a
few times a day from configurable sources (RSS, Finnhub, NewsAPI, Reddit,
and pluggable MCP connectors like Bigdata.com), uses the Claude API to
classify sector impact, and produces **advisory** BUY/SELL/WATCH
recommendations with full reasoning and provenance — plus a **Polymarket
opportunities** module that flags prediction markets where an LLM
probability estimate diverges from the market price. Nothing is executed
automatically: every recommendation and every flagged market is for your
own review.

**New here / a follower setting this up for the first time? Read
[`GET-STARTED.md`](GET-STARTED.md)** — the quickstart: what you need,
the one-paste Claude Code setup, and what "your own copy, your own API
key" means.

**Already set up, want the full step-by-step runbook? Read
[`RUN-LOCAL.md`](RUN-LOCAL.md)** — covers the repo/branch to use, Homebrew
prerequisites, the exact commands, and every failure mode worth knowing.

**Using the dashboard day to day? Read [`docs/manual-th.html`](docs/manual-th.html)**
— a Thai-language, illustrated walkthrough of every tab, the news cycle,
and how to read BUY/SELL/No Action signals.

Full spec: [`CLAUDE.md`](CLAUDE.md) and [`docs/`](docs/) (product
requirements, architecture, data model, LLM pipeline, config schema).

## Prerequisites

Everything runs directly on your machine — no Docker, no containers.

- Node.js 20+ and npm — the dashboard, migrations, and seed
- Postgres 16 running locally (macOS: `brew install postgresql@16 &&
  brew services start postgresql@16`)
- Python 3.12 and [uv](https://docs.astral.sh/uv/getting-started/installation/)
  — only for the worker (`make serve`, `make test`, `make eval`). Skip it if
  you just want to browse the dashboard.

## Setup from zero

1. **Get a Claude API key** — the one required key. Sign up and create a
   key at [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys).
   Free/optional keys for a fuller news mix (the app runs fine with none of
   these — those sources just report `failing` in the health strip):
   - [Finnhub](https://finnhub.io/register) — free tier, general market news
   - [NewsAPI.org](https://newsapi.org/register) — free developer tier
   - [Bigdata.com](https://bigdata.com) — only needed if you enable the
     seeded (disabled-by-default) Bigdata.com MCP connector

2. **Configure environment variables**:
   ```bash
   cp .env.example .env
   # edit .env and fill in ANTHROPIC_API_KEY (required) and any of the
   # optional keys above
   ```

3. **Run setup** — creates the Postgres role and database, installs npm
   dependencies, applies migrations, and seeds the starter config (sources,
   watch topics, mappings, default settings — see
   [`docs/05-config-schema.md`](docs/05-config-schema.md) §6):
   ```bash
   make setup
   ```
   Re-running it is safe: it creates only what's missing and the seed
   upserts. To wipe the database and start over, use `make reset`.

4. **Start the dashboard**:
   ```bash
   make dev-web
   ```
   Then open [http://localhost:3000](http://localhost:3000).

5. **Start the scheduler** in a second terminal — optional, and only needed
   for cycles to run on a schedule:
   ```bash
   make serve
   ```
   The dashboard is empty until the first digest cycle runs — either wait
   for the schedule in Settings → Schedule, or click **Run cycle now** in
   the header.

You can also rotate/enter the Claude API key from the UI instead of `.env`:
Settings → LLM. The DB-stored key always wins over the `.env` fallback and
is never rendered unmasked or included in a config export.

## Everyday commands

```
make setup         # create db role/database, npm install, migrate, seed
make reset         # same, but drop the database first (destroys all data)
make dev-web       # next dev on http://localhost:3000 (hot reload)
make serve         # the worker's long-running scheduler loop
make dev-worker    # worker run-once cycle
make outcomes      # run the nightly outcomes job once
make migrate       # prisma migrate dev (schema changes, local dev)
make seed          # prisma db seed (idempotent - safe to re-run)
make test          # web unit tests + worker pytest
make eval          # worker golden-fixture LLM eval against the live API
make backup        # pg_dump + config export -> ./backups/
```

All targets read `DATABASE_URL`, defaulting to
`postgresql://newswatch:newswatch@localhost:5432/newswatch`. Export your own
before calling `make` to point at a different Postgres.

> **If you run the Prisma CLI by hand**, export `DATABASE_URL` in your shell
> first. This repo ships a `web/prisma.config.ts`, and its presence makes the
> Prisma CLI skip loading `.env` — so `npx prisma migrate deploy` fails with
> `Environment variable not found: DATABASE_URL` even when `web/.env` is
> correct. The Next.js dev server reads `.env` normally; this affects only
> the `npx prisma` commands. The Makefile exports it for you.

Worker CLI (`cd worker && uv run newswatch <command>`):

```
newswatch run-cycle [--dry]     # run one digest cycle to completion (or resume an incomplete one)
newswatch run-outcomes          # run the nightly outcomes job once (normally on its own 07:30 ICT schedule)
newswatch process-source-tests  # drain pending Settings "Test" button requests
newswatch eval                  # golden-fixture triage/analysis/pm-estimate drift report
newswatch serve                 # the long-running loop (scheduled cycles + nightly outcomes)
```

## Architecture at a glance

Two applications, one database, no message queue:

| Service | Tech | Responsibility |
|---|---|---|
| `web` | Next.js 14 (App Router), TypeScript, Tailwind, shadcn/ui, Prisma | Five dashboard views, Settings UI, REST API for config + manual cycle trigger |
| `worker` | Python 3.12, APScheduler, httpx, anthropic SDK, `mcp` SDK, yfinance, SQLAlchemy | Digest cycles (ingest → triage → analyze → rules → Polymarket scan → digest), nightly outcomes job |
| `db` | Postgres 16 | Single source of truth; schema owned by Prisma migrations |

A digest cycle is a row in `cycles` that walks through
`PENDING → INGESTING → TRIAGING → ANALYZING → TRIGGERING → PM_SCANNING →
SUMMARIZING → DONE`. Every step upserts on a deterministic dedupe key, so a
crashed cycle can always be safely re-run — see
[`docs/02-architecture.md`](docs/02-architecture.md) §3 for the full state
machine and idempotency rules.

## Testing environment note

This build was developed and verified inside a sandboxed environment whose
outbound network policy blocks most external hosts (news/Reddit feed
domains, `api.finnhub.io`, `gamma-api.polymarket.com`, Yahoo Finance) —
only `api.anthropic.com` and package registries were reachable. Where a
live external call wasn't possible, verification instead used: a real
local Postgres, a real local HTTP/MCP server standing in for the blocked
host (so adapter/parsing code still ran unmocked), and a hand-built fake
Anthropic client reused consistently across the LLM pipeline's automated
tests. Every case where this substitution was used is called out inline
below and in the corresponding phase's commit message. Wherever a check
against the *actual* live network was possible (the real Anthropic API,
including a genuine 401 against a bogus key; the real yfinance/Gamma
endpoints failing with real connection errors), it was done for real and is
noted as such.

## PRD acceptance criteria (`docs/01-prd.md` §8)

1. ✅ **`make setup` brings up dashboard + worker against local Postgres; dashboard on `http://localhost:3000`.**
   Verified in Phase 1: `make setup`, then a dry cycle walked the full state machine to `DONE`. `next dev` binds `127.0.0.1:3000` only (docs/01 §10).

2. ✅ **With seed config, a manual cycle run ingests from ≥3 live free sources, produces analyses, and renders ≥1 digest with recommendations end-to-end.**
   Ingestion verified for real in Phase 2 against ≥3 seeded sources (RSS/Finnhub/Reddit), with a re-run producing zero duplicates. The LLM half of the pipeline (triage → analysis → digest) was verified end-to-end with a fake Anthropic client (no live key in the build sandbox — see note above); the resulting recommendation carries a complete, verified provenance chain back through its analysis JSON to the source news item(s).

3. ✅ **Adding a new watch topic + mapping in the UI affects the next cycle without restart.**
   The worker re-reads `topics`/`mappings` from Postgres fresh every cycle (no in-process caching), so a UI write is live immediately. Verified via the dashboard's quick-add dialog and the Settings → Topics editor in a real browser (Phase 4/5).

4. ✅ **Killing the worker mid-cycle and re-running leaves no duplicate recommendations.**
   Verified by a full crash-resume test matrix (Phase 7): the worker was made to "die" right after entering each of the six real cycle states in turn, then resumed and driven to `DONE` — confirmed to reuse the same `cycle_id` and produce exactly one analysis/recommendation/digest row each time, for every state.

5. ✅ **Outcomes page shows T+1 returns for recommendations older than one trading day.**
   The History page's Recommendations tab renders T+1/T+3/T+7 returns and direction-adjusted hit flags per recommendation (Phase 6). The nightly outcomes job's retry/unavailable-marking logic was verified against the *real* (network-policy-blocked) yfinance and Gamma endpoints — three real attempts, three real connection failures, `status='unavailable'` after the third, confirmed via `psql`; the actual T+1/3/7 return computation was verified with a fake price series (real Yahoo Finance access wasn't available from the build sandbox) plus a real-browser check against hand-seeded complete outcome data.

6. ✅ **Monthly LLM budget cap halts analysis (not ingestion) when reached, with a visible banner.**
   Verified in Phase 3 by setting `monthly_budget_usd=0.01` and re-running a cycle: analysis stopped mid-cycle, ingestion (which makes no LLM calls) was unaffected, and the digest rendered the templated "LLM budget reached" banner.

7. ✅ **Rotating the Claude API key in Settings takes effect on the next LLM call without restart; the key is never rendered unmasked and never appears in config export.**
   Verified live against the real Anthropic API in Phase 5: a bogus key set via the Settings UI produced a genuine 401 on the next cycle, and `secrets.status` flipped to `invalid` without a worker restart (this is also what surfaced and led to fixing a real transaction-rollback bug in `mark_key_status`). The key is always DB-stored, masked-only in every API response, and explicitly excluded from `GET /api/config/export`.

8. ✅ **Toggling the Bigdata.com MCP connector off removes it from the next cycle's ingestion (verified in cycle stats); toggling on restores it.**
   Verified in Phase 2 against a real local MCP server: with the connector disabled, its call log stayed at zero for the whole cycle; re-enabling it restored calls on the next run.

9. ✅ **Adding a topic via the board's quick-add dialog (incl. LLM-suggested mappings after user edit/accept) makes it live on the next cycle; disabling a mapping row prevents that sector from being recommended for that topic.**
   Quick-add verified in a real browser (Phase 4). The mapping-disabled gate is enforced in `rules.py` and covered by a dedicated unit test asserting a disabled mapping's `mapping_enabled` rule-trace check fails and no recommendation is produced (Phase 3).

10. ✅ **A cycle produces a Polymarket opportunities list where every flagged market shows edge ≥ threshold and passes liquidity/confidence floors; each links to the live market.**
    `scan.py`'s deterministic edge rules (edge/confidence/liquidity, all captured in a per-opportunity `rule_trace`) are unit-tested exhaustively, including a full `run_pm_scanning` integration test against real local Postgres (Phase 5b). Every opportunity card and detail page links to `https://polymarket.com/event/<slug>`, confirmed in a real browser. The Gamma API's exact field shapes could not be confirmed against a live call (network-policy-blocked from the build sandbox — see note above); the client cross-checks Polymarket's own open-source reference implementation and parses defensively.

## Known build-environment substitutions

Documented transparently rather than silently: a few external dependencies
could not be reached from the sandbox this was built in, so implementation
correctness rests on defensive parsing plus cross-referencing rather than a
live call. If you hit a real-world shape mismatch after deploying with real
network access, these are the places to look first:

- `worker/newswatch_worker/polymarket/client.py` — Gamma API field names
  (cross-checked against `github.com/Polymarket/agents`, not a live call).
- Seed RSS feed URLs in `web/prisma/seed.ts` — checked for plausibility, not
  liveness, from the sandbox; a `failing` health badge on first real run is
  the signal to swap a URL.
