"""Tools: web search, page fetch, RAG storage."""

import os
import re
from html import unescape
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

SEARCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ResearchAgent/1.0; +https://localhost/health)"
    ),
}


async def web_search(query: str, max_results: int = 5) -> list[dict]:
    """
    Search the web. Primary provider from SEARCH_PROVIDER (ddg|tavily|serper).
    If DuckDuckGo is empty/fails, try Tavily then Serper when API keys are set.
    """
    provider = (os.getenv("SEARCH_PROVIDER") or "ddg").strip().lower()
    if provider not in {"ddg", "tavily", "serper"}:
        provider = "ddg"

    try:
        results = await _search_with_provider(provider, query, max_results)
    except Exception:
        results = []

    if results:
        return results

    # Fallback chain when primary is ddg (or primary failed/empty)
    fallbacks: list[str] = []
    if provider == "ddg":
        if os.getenv("TAVILY_API_KEY"):
            fallbacks.append("tavily")
        if os.getenv("SERPER_API_KEY"):
            fallbacks.append("serper")
    else:
        fallbacks.append("ddg")
        if provider != "tavily" and os.getenv("TAVILY_API_KEY"):
            fallbacks.append("tavily")
        if provider != "serper" and os.getenv("SERPER_API_KEY"):
            fallbacks.append("serper")

    for fb in fallbacks:
        try:
            results = await _search_with_provider(fb, query, max_results)
            if results:
                return results
        except Exception:
            continue

    return []


async def _search_with_provider(
    provider: str, query: str, max_results: int
) -> list[dict]:
    if provider == "tavily":
        return await _search_tavily(query, max_results)
    if provider == "serper":
        return await _search_serper(query, max_results)
    return await _search_ddg(query, max_results)


async def _search_ddg(query: str, max_results: int = 5) -> list[dict]:
    """Search via DuckDuckGo HTML (no API key required)."""
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    async with httpx.AsyncClient(
        timeout=20.0, follow_redirects=True, headers=SEARCH_HEADERS
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        html = response.text

    results: list[dict] = []
    blocks = re.findall(
        r'<a rel="nofollow" class="result__a" href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'<a class="result__snippet"[^>]*>(.*?)</a>',
        html,
        re.DOTALL,
    )

    for href, title_raw, snippet_raw in blocks:
        if len(results) >= max_results:
            break
        link = _resolve_ddg_redirect(href)
        if not link.startswith("http"):
            continue
        title = _strip_tags(unescape(title_raw))
        snippet = _strip_tags(unescape(snippet_raw))
        results.append(
            {
                "query": query,
                "url": link,
                "title": title,
                "snippet": snippet,
            }
        )

    return results


async def _search_tavily(query: str, max_results: int = 5) -> list[dict]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not set")

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "include_answer": False,
            },
        )
        response.raise_for_status()
        data = response.json()

    results: list[dict] = []
    for item in data.get("results") or []:
        url = item.get("url") or ""
        if not url.startswith("http"):
            continue
        results.append(
            {
                "query": query,
                "url": url,
                "title": item.get("title") or "",
                "snippet": item.get("content") or "",
            }
        )
        if len(results) >= max_results:
            break
    return results


async def _search_serper(query: str, max_results: int = 5) -> list[dict]:
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        raise RuntimeError("SERPER_API_KEY is not set")

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": max_results},
        )
        response.raise_for_status()
        data = response.json()

    results: list[dict] = []
    for item in data.get("organic") or []:
        url = item.get("link") or ""
        if not url.startswith("http"):
            continue
        results.append(
            {
                "query": query,
                "url": url,
                "title": item.get("title") or "",
                "snippet": item.get("snippet") or "",
            }
        )
        if len(results) >= max_results:
            break
    return results


def _resolve_ddg_redirect(href: str) -> str:
    """DuckDuckGo wraps links in //duckduckgo.com/l/?uddg=..."""
    if "uddg=" in href:
        parsed = urlparse(href)
        params = parse_qs(parsed.query)
        uddg = params.get("uddg", [""])[0]
        return unquote(uddg)
    if href.startswith("//"):
        return "https:" + href
    return href


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


async def fetch_page(url: str, max_chars: int = 12000) -> str:
    """Fetch a URL and return plain text (truncated)."""
    async with httpx.AsyncClient(
        timeout=25.0, follow_redirects=True, headers=SEARCH_HEADERS
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "text" not in content_type and "html" not in content_type:
            return ""
        html = response.text

    text = _html_to_text(html)
    return text[:max_chars]


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<noscript.*?>.*?</noscript>", " ", html)
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


async def store_to_rag(
    session_id: str,
    topic: str,
    report: str,
    sources: list[dict],
) -> None:
    """Persist final report and source metadata to ChromaDB."""
    from app.rag.store import upsert_research_session

    await upsert_research_session(
        session_id=session_id,
        topic=topic,
        report=report,
        sources=sources,
    )
