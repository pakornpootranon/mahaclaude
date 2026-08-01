FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev

COPY . .

# Long-running: scheduled cycles per settings['schedule'], manual-run and
# source_tests polling (docs/02-architecture.md §3, scheduler.py).
CMD ["uv", "run", "python", "-m", "newswatch_worker.main", "serve"]
