"""Database access for the worker.

The worker never runs migrations or owns schema — Prisma does (web/prisma).
This module connects via SQLAlchemy and reflects whatever tables/views exist,
per docs/02-architecture.md §1 ("worker uses SQLAlchemy reflecting the same
tables").
"""

from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy import MetaData, Table, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


def database_url() -> str:
    """DATABASE_URL is shared with Prisma (web/), which expects a plain
    postgresql:// scheme. SQLAlchemy needs the driver named explicitly to
    pick psycopg (v3) over the legacy psycopg2 default, so normalize here
    rather than changing the shared env var's format.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(database_url(), pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_metadata() -> MetaData:
    metadata = MetaData()
    # views=True: docs/03-data-model.md §3 defines topic_board_v, hit_rates_v,
    # pm_calibration_v, spend_mtd_v as SQL views (not tables) — SQLAlchemy's
    # reflect() omits views unless asked, so without this the budget guard's
    # `table("spend_mtd_v")` lookup silently raises KeyError.
    metadata.reflect(bind=get_engine(), views=True)
    return metadata


def table(name: str) -> Table:
    return get_metadata().tables[name]


def get_session() -> Session:
    return Session(get_engine())
