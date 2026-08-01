.PHONY: setup reset dev-web serve dev-worker outcomes migrate seed test eval backup

# Local Postgres. Override by exporting DATABASE_URL before calling make.
# Exported so the Prisma CLI sees it: web/prisma.config.ts disables Prisma's
# own .env loading, so the variable has to come from the environment.
DATABASE_URL ?= postgresql://newswatch:newswatch@localhost:5432/newswatch
export DATABASE_URL

setup:
	./scripts/setup.sh

reset:
	./scripts/setup.sh --reset

dev-web:
	cd web && npm run dev

serve:
	cd worker && uv run newswatch serve

dev-worker:
	cd worker && uv run newswatch run-cycle

outcomes:
	cd worker && uv run newswatch run-outcomes

migrate:
	cd web && npx prisma migrate dev

seed:
	cd web && npx prisma db seed

test:
	cd web && npm test
	cd worker && uv run pytest

eval:
	cd worker && uv run newswatch eval

backup:
	mkdir -p backups
	pg_dump "$$DATABASE_URL" > backups/db-$$(date +%Y%m%d-%H%M%S).sql
	cd web && npx tsx prisma/export-config.ts > ../backups/config-$$(date +%Y%m%d-%H%M%S).json
