"""SourceAdapter contract (docs/02-architecture.md §4).

`fetch`/`test` take extra kwargs beyond the spec's illustrative signature
(`fetch(self, source, since)`):

- `topics`: only the MCP connector adapter uses it — args_template's
  `{topic_keywords}` substitution needs the enabled watch topics (§4b: "one
  call per topic"), and every other adapter type has no per-topic concept.
- `secret`: the caller (ingest.py / source_tests.py) resolves the source's
  credential DB-first-then-env (`secrets.resolve_source_secret`, docs/02 §9
  override) and passes the final value in; rss/reddit_rss ignore it (no
  auth), finnhub/newsapi/mcp use it in place of reading their env var
  directly.

Extending the shared signature (rather than giving each adapter type a
bespoke one) keeps the ingestion orchestrator's adapter loop uniform.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass
class RawItem:
    title: str
    url: str
    summary: str | None = None
    body_excerpt: str | None = None  # <= 2000 chars
    published_at: datetime | None = None
    language: str = "en"
    author: str | None = None
    analysis_hints: dict[str, Any] | None = None


@dataclass
class TestResult:
    ok: bool
    item_count: int = 0
    sample_titles: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class SourceConfig:
    """The subset of a `sources` row an adapter needs."""

    id: str
    name: str
    source_type: str
    config: dict[str, Any]
    language: str = "en"


class SourceAdapter(Protocol):
    source_type: str

    def fetch(
        self,
        source: SourceConfig,
        since: datetime,
        *,
        topics: list[dict[str, Any]] | None = None,
        secret: str | None = None,
    ) -> list[RawItem]: ...

    def test(self, source: SourceConfig, *, secret: str | None = None) -> TestResult: ...
