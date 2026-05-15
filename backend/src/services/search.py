"""混合搜索调度器，直接使用 Tavily 和 SerpApi。"""

from __future__ import annotations

import logging
import threading
from typing import Any

from config import Configuration
from utils import (
    deduplicate_and_format_sources,
    format_sources,
    get_config_value,
)

logger = logging.getLogger(__name__)

MAX_TOKENS_PER_SOURCE = 2000

_tavily_client = None
_search_lock = threading.Lock()


def _get_tavily_client(config: Configuration):
    """延迟初始化 Tavily 客户端（线程安全）。"""
    global _tavily_client
    if _tavily_client is None and config.tavily_api_key:
        with _search_lock:
            if _tavily_client is None:
                try:
                    from tavily import TavilyClient
                    _tavily_client = TavilyClient(api_key=config.tavily_api_key)
                except ImportError:
                    logger.warning("tavily-python 未安装，Tavily 搜索不可用")
    return _tavily_client


def _tavily_search(query: str, config: Configuration, max_results: int = 5) -> list[dict[str, Any]]:
    """使用 Tavily 执行搜索。"""
    client = _get_tavily_client(config)
    if client is None:
        return []
    try:
        response = client.search(
            query=query,
            max_results=max_results,
            include_raw_content=False,
        )
        results = []
        for item in response.get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
            })
        return results
    except Exception as exc:
        logger.warning("Tavily 搜索失败: %s", exc)
        return []


def _serpapi_search(query: str, config: Configuration, max_results: int = 5) -> list[dict[str, Any]]:
    """使用 SerpApi 执行搜索。"""
    if not config.serpapi_api_key:
        return []
    try:
        from serpapi import GoogleSearch
        search = GoogleSearch({
            "q": query,
            "api_key": config.serpapi_api_key,
            "num": max_results,
        })
        response = search.get_dict()
        results = []
        for item in response.get("organic_results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "content": item.get("snippet", ""),
            })
        return results
    except ImportError:
        logger.warning("google-search-results 未安装，SerpApi 搜索不可用")
        return []
    except Exception as exc:
        logger.warning("SerpApi 搜索失败: %s", exc)
        return []


def _hybrid_search(query: str, config: Configuration, max_results: int = 5) -> list[dict[str, Any]]:
    """混合搜索：同时调用 Tavily 和 SerpApi，合并去重。"""
    tavily_results = _tavily_search(query, config, max_results)
    serpapi_results = _serpapi_search(query, config, max_results)

    seen_urls: set[str] = set()
    merged: list[dict[str, Any]] = []
    for item in tavily_results + serpapi_results:
        url = item.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            merged.append(item)

    return merged[:max_results]


def dispatch_search(
    query: str,
    config: Configuration,
    loop_count: int,
) -> tuple[dict[str, Any] | None, list[str], str | None, str]:
    """
    执行配置的搜索后端并标准化响应负载。

    Returns:
        元组 (原始负载, 通知列表, 答案文本, 后端标签)。
    """
    search_api = get_config_value(config.search_api)
    notices: list[str] = []

    try:
        if search_api == "tavily":
            results = _tavily_search(query, config)
            backend_label = "tavily"
        elif search_api == "serpapi":
            results = _serpapi_search(query, config)
            backend_label = "serpapi"
        else:  # hybrid
            results = _hybrid_search(query, config)
            backend_label = "hybrid"
    except Exception as exc:
        logger.exception("Search backend %s failed: %s", search_api, exc)
        raise

    if not results:
        notices.append(f"搜索后端 {backend_label} 未返回结果")

    payload: dict[str, Any] = {
        "results": results,
        "backend": backend_label,
        "answer": None,
        "notices": notices,
    }

    logger.info(
        "Search backend=%s results=%s",
        backend_label,
        len(results),
    )

    return payload, notices, None, backend_label


def prepare_research_context(
    search_result: dict[str, Any] | None,
    config: Configuration,
) -> tuple[str, str]:
    """
    为下游代理构建结构化上下文和来源摘要。

    Returns:
        元组 (来源摘要列表, 详细上下文文本)。
    """
    sources_summary = format_sources(search_result)
    context = deduplicate_and_format_sources(
        search_result or {"results": []},
        max_tokens_per_source=MAX_TOKENS_PER_SOURCE,
        fetch_full_page=config.fetch_full_page,
    )

    return sources_summary, context
