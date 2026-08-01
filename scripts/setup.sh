#!/usr/bin/env bash
# One-time local setup: Postgres role + database, npm install, migrations, seed.
# No Docker. Requires Node 20+, npm, and a running local Postgres 16.
#
#   ./scripts/setup.sh           # create anything missing, keep existing data
#   ./scripts/setup.sh --reset   # drop the database first (destroys all data)

set -euo pipefail

cd "$(dirname "$0")/.."

DB_NAME="${DB_NAME:-newswatch}"
DB_USER="${DB_USER:-newswatch}"
DB_PASS="${DB_PASS:-newswatch}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DATABASE_URL="postgresql://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}"

RESET=0
[ "${1:-}" = "--reset" ] && RESET=1

say() { printf "\n\033[1m==> %s\033[0m\n" "$1"; }
die() { printf "\n\033[31mERROR: %s\033[0m\n" "$1" >&2; exit 1; }

say "Checking prerequisites"
command -v node >/dev/null || die "node not found. macOS: brew install node"
command -v psql >/dev/null || die "psql not found. macOS: brew install postgresql@16"
echo "node $(node -v), $(psql --version)"

# Homebrew Postgres makes your own account the superuser; other installs use
# a dedicated 'postgres' role. Try both before giving up.
if psql -d postgres -c '\q' >/dev/null 2>&1; then
  SU="psql -d postgres"
elif psql -U postgres -d postgres -c '\q' >/dev/null 2>&1; then
  SU="psql -U postgres -d postgres"
else
  die "Cannot connect to Postgres. macOS: brew services start postgresql@16"
fi

if [ "$RESET" = "1" ]; then
  say "Dropping database '$DB_NAME' (all data will be lost)"
  # Postgres refuses to drop a database with open connections, so evict them
  # first: a running dev server, the worker, or a GUI client all count.
  $SU -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
          WHERE datname='${DB_NAME}' AND pid <> pg_backend_pid();" >/dev/null 2>&1 || true
  # WITH (FORCE) needs Postgres 13+; fall back for older servers.
  $SU -c "DROP DATABASE IF EXISTS ${DB_NAME} WITH (FORCE);" >/dev/null 2>&1 \
    || $SU -c "DROP DATABASE IF EXISTS ${DB_NAME};" >/dev/null
fi

say "Ensuring role and database exist"
$SU -tc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1 \
  || $SU -c "CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASS}';" >/dev/null
$SU -tc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 \
  || $SU -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};" >/dev/null
echo "role '${DB_USER}' and database '${DB_NAME}' ready"

say "Writing web/.env"
if [ -f web/.env ] && grep -q "^DATABASE_URL=" web/.env; then
  echo "web/.env already sets DATABASE_URL - leaving it alone"
else
  printf 'DATABASE_URL=%s\n' "$DATABASE_URL" >> web/.env
  echo "DATABASE_URL=${DATABASE_URL}"
fi

say "Installing web dependencies"
(cd web && npm install)

# This repo ships web/prisma.config.ts, and its presence makes the Prisma CLI
# skip loading .env. Without this export, migrate/seed fail with
# "Environment variable not found: DATABASE_URL" despite a correct .env file.
export DATABASE_URL

say "Applying migrations"
(cd web && npx prisma migrate deploy)

say "Seeding starter config"
(cd web && npx prisma db seed)

say "Verifying"
PGPASSWORD="${DB_PASS}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -t \
  -c "SELECT 'sources: '||count(*) FROM sources;" \
  -c "SELECT 'topics:  '||count(*) FROM topics;"
echo "Expected on a fresh seed: sources 9, topics 5"

cat <<'EOF'

Setup complete. Start the dashboard with:

    make dev-web        # http://localhost:3000

And, in a second terminal, the scheduler (optional - needed for cycles):

    make serve

EOF
