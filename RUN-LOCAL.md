# Running Mahachai Market Watch locally on macOS

> New here? [`GET-STARTED.md`](GET-STARTED.md) is the short version of
> this file. Once it's running, [`docs/manual-th.html`](docs/manual-th.html)
> is the Thai-language usage manual for the dashboard itself.

Everything here runs directly on your Mac. **No Docker, no Compose, no
containers anywhere.** Three things run: a Postgres you install with
Homebrew, a Next.js dashboard, and (optionally) a Python worker.

---

## 0. Shortcut: hand this to Claude Code

If you are running Claude Code in your Mac terminal, `cd` into a directory
where you keep code and paste this:

> Clone `https://github.com/pakornpootranon/mahaclaude.git`, check out the
> branch `claude/newswatch-app-setup-il5v55`, then follow `RUN-LOCAL.md` in
> the repo root to get the dashboard running on http://localhost:3000.
> Do not use Docker — this repo runs natively. Install any missing
> prerequisites with Homebrew, run `make setup`, then `make dev-web`.
> Verify by curling localhost:3000 for the string "Mahachai Market Watch"
> and confirming the database has 9 sources and 5 topics. Tell me when it's
> up, and paste the exact error if anything fails.

If you already have the clone, drop the first clause and point it at your
existing directory.

---

## 1. The repository

| | |
|---|---|
| **Repo** | `pakornpootranon/mahaclaude` |
| **HTTPS URL** | `https://github.com/pakornpootranon/mahaclaude.git` |
| **SSH URL** | `git@github.com:pakornpootranon/mahaclaude.git` |
| **Branch to use** | `claude/newswatch-app-setup-il5v55` |
| **Default branch** | `main` |

**Use the branch, not `main`.** The Docker removal and the native setup
script live on `claude/newswatch-app-setup-il5v55`. As of this writing `main`
still contains `docker-compose.yml` and a `.env.example` pointing at the
container hostname `db`, which cannot resolve on your Mac.

### If you do not have a clone yet

```bash
cd ~/Projects                     # or wherever you keep code
git clone https://github.com/pakornpootranon/mahaclaude.git
cd mahaclaude
git checkout claude/newswatch-app-setup-il5v55
```

### If you already have a clone

```bash
cd ~/path/to/mahaclaude
git fetch origin claude/newswatch-app-setup-il5v55
git checkout claude/newswatch-app-setup-il5v55
git pull origin claude/newswatch-app-setup-il5v55
```

Confirm you are in the right place. Both must be true:

```bash
git branch --show-current       # -> claude/newswatch-app-setup-il5v55
ls docker-compose.yml           # -> "No such file or directory"  (correct!)
```

If `docker-compose.yml` still exists, you are on the wrong branch or the pull
did not land.

---

## 2. Prerequisites

Install what is missing. Check each first — you may already have them.

```bash
node -v          # need v20 or newer
psql --version   # need PostgreSQL 16
uv --version     # only needed for the worker
```

```bash
# Homebrew itself, if you don't have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install node
brew install postgresql@16
brew services start postgresql@16        # starts Postgres now and at login

# Optional - only for the worker (scheduled cycles, outcomes job, tests)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

If `psql` is not found after installing, Homebrew keeps version-pinned
formulae off the PATH. Add it:

```bash
echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

(On an Intel Mac the prefix is `/usr/local` instead of `/opt/homebrew`.)

Verify Postgres is actually accepting connections before continuing:

```bash
psql -d postgres -c 'select version();'
```

---

## 3. Environment variables

```bash
cp .env.example .env
```

Then edit `.env`. Only one key matters to get running:

| Variable | Required? | Notes |
|---|---|---|
| `DATABASE_URL` | Already correct | `postgresql://newswatch:newswatch@localhost:5432/newswatch` |
| `ANTHROPIC_API_KEY` | For cycles only | Get one at [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys). You can also set it later in the UI under Settings → LLM, which takes priority over `.env`. |
| `FINNHUB_KEY` | Optional | Free tier, [finnhub.io/register](https://finnhub.io/register). Without it that source shows `failing` in the health strip — harmless. Can also be set later in Settings → Sources ("Provider API keys"), which takes priority over `.env`. |
| `NEWSAPI_KEY` | Optional | Free tier, [newsapi.org/register](https://newsapi.org/register). Can also be set later in Settings → Sources ("Provider API keys"), which takes priority over `.env`. |
| `BIGDATA_API_KEY` | Optional | Only if you enable the Bigdata.com MCP connector, which ships disabled. Can also be set later per-connector in Settings → MCP Connectors ("Auth token"), which takes priority over `.env`. |

Every key above can be entered later through the Settings UI instead of (or in addition to)
`.env` — the DB value always wins if both are set, so `.env` just becomes the fallback.

**The dashboard runs fine with no API keys at all.** You just cannot run a
cycle, so the Action feed stays empty.

---

## 4. Set up the database and dependencies

One command. It creates the Postgres role and database, runs `npm install`,
applies all migrations, and seeds the starter config.

```bash
make setup
```

Expected tail of the output:

```
==> Verifying
 sources: 9
 topics:  5
Expected on a fresh seed: sources 9, topics 5
```

`make setup` is safe to re-run — it creates only what is missing and the seed
upserts, so your data survives.

To **wipe the database and start clean** (this is what removes any old data
from a previous install):

```bash
make reset
```

---

## 5. Start the server

```bash
make dev-web
```

Leave it running. Open **<http://localhost:3000>**.

You should see the header **Mahachai Market Watch** with a mascot logo, and
nav tabs: Action feed, Digests, Topics, Polymarket, History, Settings. The
health strip reads `Last cycle: none yet`, `Sources: all healthy`.

The Action feed will say *"No recommendations match these filters yet."*
**This is correct on a fresh install**, not an error. Recommendations appear
only after a cycle runs.

### Optional: the worker

Only needed for cycles on a schedule and the nightly outcomes job. Open a
**second terminal**:

```bash
cd ~/path/to/mahaclaude
make serve
```

To run a single cycle immediately instead of waiting for a schedule, either
click **Run cycle now** in the dashboard header, or:

```bash
make dev-worker
```

Both require an Anthropic API key. A cycle costs real money against your
Anthropic account — the default monthly cap is $15, editable in
Settings → LLM.

---

## 6. Stopping it

`Ctrl+C` in each terminal. To stop Postgres entirely:

```bash
brew services stop postgresql@16
```

---

## 7. Every command

```
make setup         # create db role/database, npm install, migrate, seed
make reset         # same, but drop the database first (destroys all data)
make dev-web       # the dashboard on http://localhost:3000 (hot reload)
make serve         # worker scheduler loop (cycles + nightly outcomes)
make dev-worker    # run one cycle now and exit
make outcomes      # run the nightly outcomes job once
make migrate       # prisma migrate dev (only when changing the schema)
make seed          # re-seed (idempotent)
make test          # web unit tests + worker pytest
make eval          # golden-fixture LLM eval (costs API money)
make backup        # pg_dump + config export -> ./backups/
```

All targets default `DATABASE_URL` to
`postgresql://newswatch:newswatch@localhost:5432/newswatch`. Export your own
before calling `make` to point somewhere else.

---

## 8. Troubleshooting

### `Environment variable not found: DATABASE_URL`

Running `npx prisma migrate deploy` or `npx prisma db seed` **by hand** fails
even though `web/.env` is correct. This repo ships `web/prisma.config.ts`,
and its mere presence makes the Prisma CLI skip loading `.env` entirely.

```bash
export DATABASE_URL=postgresql://newswatch:newswatch@localhost:5432/newswatch
```

The Makefile exports this for you, so `make setup` never hits it. The Next.js
dev server reads `.env` normally — only the `npx prisma` commands are
affected, which is what makes this confusing: the app starts fine and only
the database commands fail.

### `database "newswatch" is being accessed by other users`

`DROP DATABASE` refuses while anything holds a connection — a running
`make dev-web`, `make serve`, an open `psql`, or a GUI client like Postico or
TablePlus. Stop them and retry. `make reset` already handles this by
terminating open backends first.

### `Cannot connect to Postgres`

```bash
brew services list                    # is postgresql@16 "started"?
brew services start postgresql@16
tail -50 $(brew --prefix)/var/log/postgresql@16.log
```

### Port 3000 already in use

Something else is on 3000 — very likely a previous install of this app.

```bash
lsof -nP -iTCP:3000 -sTCP:LISTEN      # note the PID in column 2
kill <PID>                            # or: kill -9 <PID>
```

Or run the dashboard on a different port:

```bash
cd web && npm run dev -- -p 3100
```

### The browser shows an old version of the dashboard

Almost always a stale checkout, not a caching problem. Verify:

```bash
git branch --show-current    # claude/newswatch-app-setup-il5v55
git log --oneline -1
ls docker-compose.yml        # must NOT exist
```

If the header says "newswatch · advisory" instead of "Mahachai Market Watch",
you are running code from before the rebrand. Pull again.

### `make: command not found`

```bash
xcode-select --install
```

---

## 9. What success looks like

```bash
curl -s http://localhost:3000 | grep -o "Mahachai Market Watch"
```

prints `Mahachai Market Watch`, and:

```bash
PGPASSWORD=newswatch psql -h localhost -U newswatch -d newswatch \
  -c "select count(*) from sources;" -c "select count(*) from topics;"
```

prints `9` and `5`.

---

## 10. Notes

- All times in the UI render in **Asia/Bangkok (ICT)**.
- The dashboard binds `127.0.0.1` only. It is not reachable from other
  machines on your network, and there is no authentication by design.
- Every recommendation is **advisory**. Nothing is ever traded or bet
  automatically.
- The Claude API key is the only secret that can live in the database
  (set via Settings → LLM). It is always masked, never logged, and excluded
  from config exports. Every other key stays in `.env`.
