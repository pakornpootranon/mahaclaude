-- sources.name needed a dedupe key for idempotent seeding / import-by-name
-- (docs/05 §5); the spec's docs/03 §2.1 didn't define one. See schema.prisma
-- header comment.
CREATE UNIQUE INDEX "sources_name_key" ON "sources"("name");
