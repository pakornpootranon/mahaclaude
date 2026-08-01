# Mahachai Market Watch — Get started (for followers)

This is a public, do-it-yourself financial news-monitoring dashboard. It
runs entirely **on your own Mac**, with **your own Anthropic API key** —
nothing here talks to any account of mine, and I never see your data or
your key. You run your own private copy.

**Full Thai-language usage manual (with screenshots-style walkthroughs of
every screen):** [`docs/manual-th.html`](docs/manual-th.html) — open it in
a browser after cloning (see below), or ask Claude Code to open it for you.

---

## The fastest way: hand this to Claude Code

Install [Claude Code](https://claude.com/product/claude-code) if you don't
have it, open a terminal, `cd` into a folder where you keep code, and paste
this whole block as your prompt:

> Clone `https://github.com/pakornpootranon/mahaclaude.git`, check out the
> branch `claude/newswatch-app-setup-il5v55`, then follow `RUN-LOCAL.md` in
> the repo root to get the dashboard running on http://localhost:3000.
> Do not use Docker — this repo runs natively. Install any missing
> prerequisites with Homebrew, run `make setup`, then `make dev-web`.
> Verify by curling localhost:3000 for the string "Mahachai Market Watch"
> and confirming the database has 9 sources and at least 5 topics. Tell me
> when it's up, and paste the exact error if anything fails.

Claude Code will clone the repo, install Postgres/Node/etc. via Homebrew if
you don't already have them, set up the database, and start the dashboard
for you. It'll ask before anything destructive or before installing
software — that's normal, just approve the steps.

`RUN-LOCAL.md` (in the repo root) is the detailed step-by-step runbook this
points to — read it directly if you'd rather do the steps yourself instead
of delegating to Claude Code, or if something above fails and you need the
full troubleshooting section.

---

## Before you start: what you'll need

| Requirement | Notes |
|---|---|
| A Mac | Setup as written targets macOS (Homebrew). |
| [Claude Code](https://claude.com/product/claude-code) *(optional but recommended)* | Lets you just paste the block above instead of typing every command by hand. |
| **Your own Anthropic API key** | Get one at [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys). Required only to actually run a news cycle — the dashboard itself works with no key at all. |
| ~15 minutes | Mostly Homebrew installing Postgres/Node if you don't have them already. |

**This is not shared infrastructure.** Every follower who does this gets
their own local Postgres database, their own dashboard on their own
machine, and pays for their own Claude API usage (a monthly spend cap is
built in — Settings → LLM, default $15). There is no server of mine
involved anywhere in this flow.

---

## After it's running

1. Open <http://localhost:3000> — you should see the **Mahachai Market
   Watch** header and six tabs: Action feed, Digests, Topics, Polymarket,
   History, Settings.
2. Read **[`docs/manual-th.html`](docs/manual-th.html)** for a full guided
   tour of every tab, in Thai, with real examples from the app.
3. Add your Anthropic API key under **Settings → LLM** (or in `.env`), then
   click **Run cycle now** in the header to see it work end to end.

---

## Important to know

- **Not financial advice.** Every recommendation is advisory only, for your
  own further research. You are solely responsible for any investment
  decisions you make. Nothing in this app ever places a trade or a bet.
- **Runs on your machine only.** The dashboard binds to `127.0.0.1` and has
  no login — it is not reachable from your network, and it isn't meant to
  be exposed to the internet.
- **Cycles cost real money** against your own Anthropic account once you
  add your API key. The default monthly cap is $15, editable in
  Settings → LLM.
- Questions about the app itself, not the setup? Open an issue on
  [the GitHub repo](https://github.com/pakornpootranon/mahaclaude).
