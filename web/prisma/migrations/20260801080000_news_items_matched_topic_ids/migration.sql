-- Carries triage's per-item matched_topic_ids from TRIAGING to ANALYZING so
-- the analysis-tier prompt's mapping-rows block (docs/04 §5.1) survives a
-- crash-resume without re-running triage. Not in docs/03 §2.3; see
-- schema.prisma header comment (third deviation).
ALTER TABLE "news_items" ADD COLUMN "matched_topic_ids" TEXT[] NOT NULL DEFAULT '{}';
