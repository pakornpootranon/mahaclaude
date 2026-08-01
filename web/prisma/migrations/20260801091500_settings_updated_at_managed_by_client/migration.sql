-- settings.updated_at moves from a DB-side INSERT-only default to Prisma's
-- @updatedAt (set by the client on every write). scheduler.py's
-- settings-changed poll (docs/02 §3, FR-C5) depends on this column
-- actually bumping on UPDATE, which @default(now()) never did.
ALTER TABLE "settings" ALTER COLUMN "updated_at" DROP DEFAULT;
