from newswatch_worker.sources.base import RawItem, SourceAdapter, SourceConfig, TestResult
from newswatch_worker.sources.finnhub import FinnhubAdapter
from newswatch_worker.sources.mcp_connector import McpConnectorAdapter
from newswatch_worker.sources.newsapi import NewsApiAdapter
from newswatch_worker.sources.reddit_rss import RedditRssAdapter
from newswatch_worker.sources.rss import RssAdapter

ADAPTERS: dict[str, SourceAdapter] = {
    "rss": RssAdapter(),
    "finnhub": FinnhubAdapter(),
    "newsapi": NewsApiAdapter(),
    "reddit_rss": RedditRssAdapter(),
    "mcp": McpConnectorAdapter(),
}

__all__ = [
    "ADAPTERS",
    "RawItem",
    "SourceAdapter",
    "SourceConfig",
    "TestResult",
]
