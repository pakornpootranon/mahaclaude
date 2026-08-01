.PHONY: up down dev-web dev-worker migrate seed test eval backup

up:
	docker compose up -d

down:
	docker compose down

dev-web:
	cd web && npm run dev

dev-worker:
	cd worker && uv run newswatch run-cycle

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
