---
type: home
project: DeFi Inflow Radar
updated: 2026-10-04
---
# DeFi Inflow Radar — vault home

This folder is an **Obsidian vault** written by the daily *DeFi Inflow Radar* Routine (see
`docs/06-defi-inflow-module.md` §8/§12 in the repo). Open `vault/defi-radar/` as a vault, or pull
the `radar-vault` branch with Obsidian Git.

## How it is organised
- `Daily/YYYY-MM-DD.md` — one note per run: ETH strip, fired signals, watch list, run log. The
  Routine reads yesterday's note first to establish the baseline and to say what changed.
- `Assets/<SYMBOL>.md` — one living note per asset (ETH, AAVE, LDO, ARB, QNT, …): frontmatter holds
  the latest metrics; the body keeps a dated signal history and the evolving thesis/invalidation.
- `Signals/YYYY-MM-DD <CLASS> <SYMBOL>.md` — one note per fired signal with the full rule trace,
  catalyst, invalidation and sources. Linked from the daily note and the asset note.
- `Templates/` — the note shapes the Routine must follow so notes stay Dataview-queryable.

## Dataview starters
```dataview
TABLE class, score, inflow_type, crowded FROM "vault/defi-radar/Signals" SORT file.name DESC LIMIT 20
```
```dataview
TABLE last_signal, tvl_7d_pct, price_7d_pct, attention_z1m FROM "vault/defi-radar/Assets" SORT last_signal DESC
```

## Rules of the vault
- The Routine only **adds** daily and signal notes and **updates** asset notes. It never deletes.
- Every number carries its data day. Every claim carries a source line.
- A day with no signals still gets a daily note (short). Silence must be distinguishable from a dead run.
