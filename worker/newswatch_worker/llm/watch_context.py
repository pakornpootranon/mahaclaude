"""Shared WATCH_CONTEXT block for the triage and analysis prompts (docs/04 §2).

Mapping rows are deliberately NOT included here — the spec keeps them
analysis-only ("Mappings are given only to the analysis tier (topic-filtered,
to keep tokens down)"), so `analyze.py` appends its own topic-filtered
mapping block after this one.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.engine import Connection

from newswatch_worker.db import table

MARKETS_IN_SCOPE = (
    "## Markets in scope\n"
    "US (NYSE/NASDAQ, sector ETFs), TH (SET/mai, \".BK\" tickers), "
    "GLOBAL (map to US/TH tradable proxies)."
)


@dataclass(frozen=True)
class WatchTopic:
    id: str
    name: str
    description: str
    keywords: list[str]
    sensitivity: float
    enabled: bool

    @property
    def short_id(self) -> str:
        return self.id.replace("-", "")[:8]


def load_enabled_topics(conn: Connection) -> list[WatchTopic]:
    topics_t = table("topics")
    rows = conn.execute(
        select(
            topics_t.c.id,
            topics_t.c.name,
            topics_t.c.description,
            topics_t.c.keywords,
            topics_t.c.sensitivity,
            topics_t.c.enabled,
        )
        .where(topics_t.c.enabled.is_(True))
        .order_by(topics_t.c.name)
    ).all()
    return [
        WatchTopic(
            id=str(row.id),
            name=row.name,
            description=row.description,
            keywords=list(row.keywords or []),
            sensitivity=float(row.sensitivity),
            enabled=row.enabled,
        )
        for row in rows
    ]


def short_id_map(topics: list[WatchTopic]) -> dict[str, str]:
    """short_id (as shown to the LLM) -> full topic UUID."""
    return {t.short_id: t.id for t in topics}


def render_watch_topics(topics: list[WatchTopic]) -> str:
    if not topics:
        return "## Watch topics (user-configured)\n(none configured)"
    lines = ["## Watch topics (user-configured)"]
    for i, t in enumerate(topics, start=1):
        keywords = ", ".join(t.keywords) if t.keywords else "(none)"
        lines.append(f'{i}. id={t.short_id} "{t.name}" — {t.description}. Keywords: {keywords}')
    return "\n".join(lines)


def build_watch_context(conn: Connection) -> tuple[str, list[WatchTopic]]:
    """Returns (rendered WATCH_CONTEXT block, the topics used to render it)."""
    topics = load_enabled_topics(conn)
    block = f"{render_watch_topics(topics)}\n\n{MARKETS_IN_SCOPE}"
    return block, topics
