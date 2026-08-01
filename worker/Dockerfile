FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev

COPY . .

# Placeholder CMD: runs one cycle to completion and exits. Replaced by the
# APScheduler cron loop (docs/02-architecture.md §3) once a later phase has
# real ingest/LLM/rules work worth scheduling.
CMD ["uv", "run", "python", "-m", "newswatch_worker.main", "run-cycle"]
