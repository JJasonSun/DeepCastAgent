"""混合搜索调度器，直接使用 Tavily 和 SerpApi。"""

from __future__ import annotations

import logging
import threading
from typing import Any

from openai import OpenAI

from config import Configuration
from prompts import search_result_filter_instructions
from services.llm import call_llm_json, run_with_retry
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
        response = run_with_retry(
            lambda: client.search(
                query=query,
                max_results=max_results,
                include_raw_content=config.include_raw_source_content,
            ),
            operation_name="Tavily search",
            max_retries=config.search_max_retries,
            retry_base_delay=config.llm_retry_base_delay,
        )
        results = []
        for item in response.get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
                "raw_content": item.get("raw_content", ""),
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
        response = run_with_retry(
            search.get_dict,
            operation_name="SerpApi search",
            max_retries=config.search_max_retries,
            retry_base_delay=config.llm_retry_base_delay,
        )
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
) -> tuple[dict[str, Any] | None, list[str], str]:
    """
    执行配置的搜索后端并标准化响应负载。

    Returns:
        元组 (原始负载, 通知列表, 后端标签)。
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

    return payload, notices, backend_label


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
        include_raw_source_content=config.include_raw_source_content,
    )

    return sources_summary, context


# 搜索结果过滤输出的 JSON Schema
FILTER_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "useful": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["index", "useful", "reason"],
            },
        }
    },
    "required": ["results"],
}


def filter_search_results(
    results: list[dict[str, Any]],
    research_topic: str,
    client: OpenAI,
    config: Configuration,
) -> list[dict[str, Any]]:
    """使用 LLM 评估搜索结果质量，过滤掉低价值内容。

    Args:
        results: 原始搜索结果列表。
        research_topic: 研究主题。
        client: OpenAI 客户端。
        config: 配置对象。

    Returns:
        过滤后的高质量搜索结果列表。
    """
    if not results or len(results) <= 1:
        return results

    # 构建结果摘要供 LLM 评估
    results_text = []
    for idx, item in enumerate(results):
        title = item.get("title", "")
        content = item.get("content", "")[:200]
        url = item.get("url", "")
        results_text.append(f"[{idx}] 标题: {title}\n    摘要: {content}\n    URL: {url}")

    prompt = search_result_filter_instructions.format(
        research_topic=research_topic,
        search_results="\n\n".join(results_text),
    )
    extra_body = config.build_thinking_body(enable=False)

    filter_result = call_llm_json(
        client=client,
        system_prompt="你是一名信息筛选专家。",
        user_prompt=prompt,
        model=config.active_llm_model(),
        json_schema=FILTER_JSON_SCHEMA,
        schema_name="search_filter",
        extra_body=extra_body,
        max_retries=config.llm_max_retries,
        retry_base_delay=config.llm_retry_base_delay,
    )

    if not filter_result or not isinstance(filter_result, dict):
        logger.warning("Search filter returned no result, keeping all results")
        return results

    # 根据评估结果过滤
    judgments = filter_result.get("results", [])
    useful_indices = set()
    for judgment in judgments:
        if isinstance(judgment, dict) and judgment.get("useful", False):
            idx = judgment.get("index")
            if isinstance(idx, int) and 0 <= idx < len(results):
                useful_indices.add(idx)

    if not useful_indices:
        logger.info("Search filter: all %d results filtered out, keeping all", len(results))
        return results

    filtered = [results[i] for i in sorted(useful_indices)]
    removed_count = len(results) - len(filtered)
    if removed_count > 0:
        logger.info("Search filter: removed %d low-quality results, kept %d", removed_count, len(filtered))

    return filtered


# ── 信息源可信度分层 ──────────────────────────────────────────

# 域名权威性白名单（高 → 中 → 低）
DOMAIN_AUTHORITY: dict[str, int] = {
    # 权威学术/官方来源（10 分）
    "arxiv.org": 10, "nature.com": 10, "science.org": 10,
    "ieee.org": 10, "acm.org": 10, "springer.com": 10,
    "wiley.com": 10, "cell.com": 10, "thelancet.com": 10,
    "gov.cn": 10, ".gov": 10, "who.int": 10,
    "worldbank.org": 10, "imf.org": 10, "oecd.org": 10,
    # 头部媒体/科技媒体（8 分）
    "reuters.com": 8, "bbc.com": 8, "nytimes.com": 8,
    "washingtonpost.com": 8, "ft.com": 8, "economist.com": 8,
    "techcrunch.com": 8, "wired.com": 8, "theverge.com": 8,
    "ars-technica.com": 8, "engadget.com": 8,
    "36kr.com": 8, "jiemian.com": 8, "caixin.com": 8,
    # 行业分析/技术社区（6 分）
    "medium.com": 6, "github.com": 6, "stackoverflow.com": 6,
    "huggingface.co": 6, "openai.com": 6, "anthropic.com": 6,
    "zhihu.com": 6, "infoq.cn": 6,
    # 一般技术博客（5 分）
    "csdn.net": 5, "juejin.cn": 5, "cnblogs.com": 5,
    "segmentfault.com": 5, "jianshu.com": 5,
}


def score_source_authority(url: str) -> int:
    """根据域名返回权威性评分（1-10）。

    评分规则：
    - 学术期刊、政府机构、国际组织：10 分
    - 头部媒体、科技媒体：8 分
    - 行业分析、技术社区：6 分
    - 一般技术博客：5 分
    - 未知来源：3 分（默认）
    """
    if not url:
        return 3
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.lower()
    except Exception:
        return 3

    for known_domain, score in DOMAIN_AUTHORITY.items():
        if known_domain in domain:
            return score
    return 3


def sort_by_authority(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按权威性评分降序排列搜索结果。

    高权威来源排在前面，确保在上下文拼接时优先被 LLM 参考。
    """
    for r in results:
        r["authority_score"] = score_source_authority(r.get("url", ""))
    results.sort(key=lambda x: x.get("authority_score", 0), reverse=True)
    return results
