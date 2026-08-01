"""Canonical-URL dedupe, exact/URL layer (docs/02-architecture.md §5).

dedupe_key = sha256(canonical_url) where canonical_url strips tracking
params (utm_*, fbclid, ...), lowercases host, removes fragments. The
story-cluster layer (triage-time near-duplicate storyline detection) is
Phase 3 territory (docs/04-llm-pipeline.md §4) — this module is the code
layer only.
"""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_EXACT = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "igshid"}


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING_PREFIXES) and k.lower() not in _TRACKING_EXACT
    ]
    query = urlencode(sorted(query_pairs))
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), host, path, query, ""))


def dedupe_key(url: str) -> str:
    return hashlib.sha256(canonicalize_url(url).encode("utf-8")).hexdigest()


def recommendation_dedupe_key(
    *, topic_id: str | None, sector: str, tickers: list[str], action: str, window_bucket: int
) -> str:
    """docs/03's recommendations.dedupe_key is `sha256(topic_id|ticker_or_sector|action|window_bucket)`.

    docs/05 §1 describes the window as "same topic+ticker+action", but a
    recommendation row bundles a whole sector's tickers (one row per rules.py
    impact-row evaluation, docs/04 §6), so there's no single per-row
    "ticker" to key on when a row covers several. ticker_or_sector resolves
    that: the sorted, joined ticker list when present, else the sector name
    for sector-only rows (FR-A4) and the "unconfigured but significant"
    WATCH branch (which never carries tickers, docs/04 §6).
    """
    ticker_or_sector = ",".join(sorted(tickers)) if tickers else sector
    raw = f"{topic_id or 'unconfigured'}|{ticker_or_sector}|{action}|{window_bucket}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def pm_opportunity_dedupe_key(*, market_id: str, side: str, window_bucket: int) -> str:
    """docs/03 §2.14: pm_opportunities.dedupe_key = sha256(market_id|side|window_bucket)."""
    raw = f"{market_id}|{side}|{window_bucket}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
