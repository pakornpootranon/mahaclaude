"""Tier 1 — Triage (docs/04-llm-pipeline.md §3): batched relevance filter +
storyline clustering. Cheap Haiku-class model, reasoning off by default.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.engine import Connection

from newswatch_worker.db import table
from newswatch_worker.llm import client
from newswatch_worker.llm.watch_context import WatchTopic, build_watch_context, short_id_map

logger = logging.getLogger(__name__)

PROMPT_VERSION = "triage-v1"
BATCH_SIZE = 40

SYSTEM_PROMPT_TEMPLATE = """You are a financial news triage assistant for a personal market-monitoring dashboard.
The user watches specific topics (listed below). Your job for EACH numbered item:
1. relevant: true if the item plausibly relates to any watch topic OR is clearly major
   market-moving news (central bank surprise, war, major default, systemic event) even if
   no topic matches. Minor corporate PR, listicles, opinion pieces, and routine price
   recaps are NOT relevant.
2. matched_topic_ids: watch topic ids matched (empty if relevant only as "major unconfigured news").
3. story_key: cluster near-duplicate storylines. Reuse an existing story_key from the
   "already assigned" list when the item covers the same underlying event; otherwise mint a new
   short slug like "fed-cut-signal-0731". Same event ≠ same topic — cluster by event.
Be strict: when in doubt on relevance, mark irrelevant. Output JSON only.

{watch_context}

## Already assigned story keys this cycle
{already_assigned}"""


class TriageItemResult(BaseModel):
    idx: int
    relevant: bool
    matched_topic_ids: list[str] = Field(default_factory=list)
    story_key: str


class TriageResult(BaseModel):
    items: list[TriageItemResult]


@dataclass(frozen=True)
class TriageInputItem:
    id: str
    source_name: str
    title: str
    summary: str | None
    published_at: str | None
    provider_tags: dict | None


def _truncate_summary(summary: str | None) -> str:
    if not summary:
        return ""
    return summary[:300]


def render_batch(items: list[TriageInputItem]) -> str:
    lines = ["## Items"]
    for idx, item in enumerate(items):
        lines.append(f"### Item {idx}")
        lines.append(f"source: {item.source_name}")
        lines.append(f"title: {item.title}")
        lines.append(f"summary: {_truncate_summary(item.summary)}")
        lines.append(f"published_at: {item.published_at or 'unknown'}")
        if item.provider_tags:
            lines.append(f"provider_tags (hints from the news provider, not ground truth): {item.provider_tags}")
    return "\n".join(lines)


def render_already_assigned(story_titles: dict[str, str]) -> str:
    if not story_titles:
        return "(none yet)"
    return "\n".join(f"{key}: {title}" for key, title in story_titles.items())


def _keyword_hint_topic(item: TriageInputItem, topics: list[WatchTopic]) -> str | None:
    """Cheap, non-authoritative match against each topic's `keywords` hint
    phrases (docs/03 §2.4: "hint phrases for triage") - used only to bucket
    items for the round-robin fairness pass below, never to decide
    relevance itself (that's still entirely the triage LLM call's job).
    Returns the first topic whose keyword appears in the item's
    title/summary, or None (the shared "no hint" bucket, which still gets
    its own fair round-robin turn so major unconfigured news isn't
    starved either).
    """
    haystack = f"{item.title} {item.summary or ''}".lower()
    for topic in topics:
        for keyword in topic.keywords:
            if keyword and keyword.lower() in haystack:
                return topic.id
    return None


def _round_robin_by_topic_hint(items: list[TriageInputItem], topics: list[WatchTopic]) -> list[TriageInputItem]:
    """Reorders newest-first `items` so the max_items_per_cycle cap below
    takes one item per topic-hint bucket before taking a second from any
    bucket. Without this, a single high-volume topic's news can fill the
    entire per-cycle cap and starve every other topic's coverage for the
    whole cycle - the plain newest-first order has no topic fairness at
    all. Bucket order (and each bucket's internal order) is otherwise
    unchanged, so with no topics configured this is a no-op.
    """
    buckets: dict[str | None, list[TriageInputItem]] = {}
    bucket_order: list[str | None] = []
    for item in items:
        key = _keyword_hint_topic(item, topics)
        if key not in buckets:
            buckets[key] = []
            bucket_order.append(key)
        buckets[key].append(item)

    ordered: list[TriageInputItem] = []
    while any(buckets[key] for key in bucket_order):
        for key in bucket_order:
            if buckets[key]:
                ordered.append(buckets[key].pop(0))
    return ordered


def select_items_for_cycle(
    conn: Connection, *, max_items_per_cycle: int, topics: list[WatchTopic] | None = None
) -> tuple[list[TriageInputItem], int]:
    """Pending items, round-robined across topic-hint buckets (see
    `_round_robin_by_topic_hint`) and capped at max_items_per_cycle
    (docs/04 §1). Overflow is marked triage_status='skipped_budget'
    immediately so it's excluded from every subsequent cycle's selection
    too, and returns (selected, skipped_count). `topics` defaults to none
    configured, which collapses the round-robin to a single bucket -
    i.e. plain newest-first, same as before topic fairness existed.
    """
    news_items_t = table("news_items")
    sources_t = table("sources")

    rows = conn.execute(
        select(
            news_items_t.c.id,
            news_items_t.c.title,
            news_items_t.c.summary,
            news_items_t.c.published_at,
            news_items_t.c.fetched_at,
            news_items_t.c.analysis_hints,
            sources_t.c.name.label("source_name"),
        )
        .select_from(news_items_t.join(sources_t, sources_t.c.id == news_items_t.c.source_id))
        .where(news_items_t.c.triage_status == "pending")
        .order_by(news_items_t.c.published_at.desc().nulls_last(), news_items_t.c.fetched_at.desc())
    ).all()

    candidates = [
        TriageInputItem(
            id=str(row.id),
            source_name=row.source_name,
            title=row.title,
            summary=row.summary,
            published_at=row.published_at.isoformat() if row.published_at else None,
            provider_tags=row.analysis_hints,
        )
        for row in rows
    ]
    ordered = _round_robin_by_topic_hint(candidates, topics or [])

    selected = ordered[:max_items_per_cycle]
    overflow = ordered[max_items_per_cycle:]

    if overflow:
        conn.execute(
            news_items_t.update()
            .where(news_items_t.c.id.in_([item.id for item in overflow]))
            .values(triage_status="skipped_budget")
        )

    return selected, len(overflow)


def _batches(items: list[TriageInputItem], size: int) -> list[list[TriageInputItem]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def run_triage(conn: Connection, *, cycle_id: str) -> dict:
    """Runs Tier 1 triage over this cycle's pending items and writes
    triage_status/story_key/matched_topic_ids back to news_items.

    Sequential batches (not parallel) so each batch's "already assigned story
    keys" list reflects every earlier batch in the same run (docs/04 §3),
    keeping clustering consistent across a single triage pass. Known
    limitation: if the process crashes mid-run and TRIAGING resumes in a
    later invocation, `already_assigned` restarts empty (there's no schema
    field recording which cycle a story_key was minted in) — a resumed
    batch could mint a fresh story_key for an item that should have
    clustered with one triaged just before the crash. Self-heals into two
    analyses instead of one; doesn't affect correctness or idempotency.
    """
    llm_settings = client.get_llm_settings(conn)
    # Reasoning should be the lowest of the four tiers (docs/04 §1 default:
    # "off"). This stage is a cheap, high-volume, largely mechanical pass -
    # binary relevant/irrelevant + reusing/minting a story_key - run over
    # every ingested item every cycle. Extended thinking buys little here
    # and multiplies cost across the whole item volume; save the reasoning
    # budget for analysis/digest, which run far fewer times per cycle but
    # each need to weigh nuance.
    model, reasoning = llm_settings.tier("triage")

    watch_context, topics = build_watch_context(conn)
    id_map = short_id_map(topics)

    selected, skipped_budget = select_items_for_cycle(
        conn, max_items_per_cycle=llm_settings.max_items_per_cycle, topics=topics
    )

    stats = {
        "triage_items_selected": len(selected),
        "triage_items_skipped_budget": skipped_budget,
        "triage_batches": 0,
        "triage_relevant": 0,
        "triage_irrelevant": 0,
        "triage_failed_batches": 0,
        "budget_hit": False,
    }

    news_items_t = table("news_items")
    already_assigned: dict[str, str] = {}
    batches = _batches(selected, BATCH_SIZE)

    for batch_idx, batch in enumerate(batches):
        stats["triage_batches"] += 1
        system = SYSTEM_PROMPT_TEMPLATE.format(
            watch_context=watch_context,
            already_assigned=render_already_assigned(already_assigned),
        )
        user_content = render_batch(batch)

        try:
            result = client.call_structured(
                conn,
                cycle_id=cycle_id,
                purpose="triage",
                model=model,
                reasoning=reasoning,
                output_model=TriageResult,
                system=system,
                user_content=user_content,
                temperature=0.0,
            )
        except client.BudgetExceededError:
            # docs/04 §8 / docs/02 §8: stop LLM calls, remaining items
            # skipped_budget, cycle continues to DONE with budget_hit=true
            # (set on cycles by the TRIAGING/ANALYZING step handler).
            remaining_ids = [item.id for later_batch in batches[batch_idx:] for item in later_batch]
            conn.execute(
                news_items_t.update()
                .where(news_items_t.c.id.in_(remaining_ids))
                .values(triage_status="skipped_budget")
            )
            stats["triage_items_skipped_budget"] += len(remaining_ids)
            stats["budget_hit"] = True
            logger.warning("cycle=%s budget exhausted mid-triage; %d items marked skipped_budget", cycle_id, len(remaining_ids))
            break

        if result is None:
            stats["triage_failed_batches"] += 1
            logger.error("cycle=%s triage batch failed after repair retry; leaving %d items pending", cycle_id, len(batch))
            continue

        for item_result in result.parsed.items:
            if item_result.idx < 0 or item_result.idx >= len(batch):
                logger.warning("cycle=%s triage returned out-of-range idx=%s, skipping", cycle_id, item_result.idx)
                continue
            source_item = batch[item_result.idx]
            resolved_topic_ids = [
                id_map[short] for short in item_result.matched_topic_ids if short in id_map
            ]
            conn.execute(
                news_items_t.update()
                .where(news_items_t.c.id == source_item.id)
                .values(
                    triage_status="relevant" if item_result.relevant else "irrelevant",
                    story_key=item_result.story_key if item_result.relevant else None,
                    matched_topic_ids=resolved_topic_ids,
                )
            )
            if item_result.relevant:
                stats["triage_relevant"] += 1
                already_assigned.setdefault(item_result.story_key, source_item.title)
            else:
                stats["triage_irrelevant"] += 1

    return stats
