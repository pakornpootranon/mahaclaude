-- "On 401, mark key invalid in health strip" (docs/04 §1) needs somewhere
-- to persist that state; not in docs/03 §2.12. See schema.prisma header
-- comment (fourth deviation).
ALTER TABLE "secrets" ADD COLUMN "status" TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE "secrets" ADD COLUMN "last_checked_at" TIMESTAMPTZ;
