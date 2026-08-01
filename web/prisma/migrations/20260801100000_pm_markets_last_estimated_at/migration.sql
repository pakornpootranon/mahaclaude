-- Deviation from docs/03-data-model.md §2.13 (documented per CLAUDE.md's
-- "if the spec is wrong/impossible, say so and propose the fix"): docs/04
-- §9's scan.py rule "not already estimated within reestimate_hours" has no
-- column to key off in the literal spec schema. pm_opportunities only
-- records markets that PASSED the edge-rule flag, so a market that was
-- estimated but didn't clear the edge threshold would otherwise be
-- re-estimated (and re-billed) every single cycle. This column tracks every
-- LLM estimate attempt regardless of outcome.
ALTER TABLE "pm_markets" ADD COLUMN "last_estimated_at" TIMESTAMPTZ;
