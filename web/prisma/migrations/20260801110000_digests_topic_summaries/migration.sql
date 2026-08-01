-- Deviation from docs/03-data-model.md §2.9 (documented per CLAUDE.md's "if
-- the spec is wrong/impossible, say so and propose the fix"): user request
-- for a Thai-language summary of every configured watch topic on each
-- cycle's digest, including topics with zero hits that cycle - the literal
-- spec's digests schema has no field for per-topic output, only the
-- cycle-wide synthesis/top_themes. Array of {topic_id, topic_name, summary},
-- one entry per topic that existed when the cycle's digest was generated.
ALTER TABLE "digests" ADD COLUMN "topic_summaries" JSONB NOT NULL DEFAULT '[]';
