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
