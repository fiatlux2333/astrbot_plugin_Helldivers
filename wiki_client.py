"""Helldivers Wiki (MediaWiki) 客户端：搜索 + 词条摘要。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlencode

import aiohttp
from astrbot.api import logger

from .plugin_info import USER_AGENT


def _strip_html_snippet(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"<[^>]+>", "", text)
    cleaned = cleaned.replace("&quot;", '"').replace("&amp;", "&")
    cleaned = cleaned.replace("&lt;", "<").replace("&gt;", ">")
    cleaned = cleaned.replace("&#039;", "'").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def _is_hd1_title(title: str) -> bool:
    t = (title or "").strip().lower()
    return t.startswith("helldivers 1:") or t.startswith("helldivers1:")


class WikiCache:
    """Wiki 搜索/词条本地缓存（内存 + JSON）。"""

    def __init__(
        self, data_dir: Path, *, page_ttl: int = 21600, search_ttl: int = 1800
    ) -> None:
        self.path = data_dir / "wiki_cache.json"
        self.page_ttl = max(60, int(page_ttl))
        self.search_ttl = max(60, int(search_ttl))
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = raw
        except Exception as e:
            logger.warning(f"[HD2] load wiki cache failed: {e}")
            self._data = {}

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(self._data, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(tmp, self.path)
        except Exception as e:
            logger.warning(f"[HD2] save wiki cache failed: {e}")
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._data.get(key)
            if not entry:
                return None
            expires_at = float(entry.get("expires_at") or 0)
            if expires_at and time.time() > expires_at:
                self._data.pop(key, None)
                return None
            return entry.get("data")

    async def set(self, key: str, data: Any, ttl: int) -> None:
        async with self._lock:
            self._data[key] = {
                "data": data,
                "expires_at": time.time() + max(1, int(ttl)),
                "updated_at": time.time(),
            }
            self.save()


class WikiClient:
    """helldivers.wiki.gg MediaWiki API 封装。"""

    def __init__(
        self,
        *,
        base_url: str = "https://helldivers.wiki.gg",
        api_path: str = "/api.php",
        user_agent: str = USER_AGENT,
        timeout: int = 30,
        proxy_url: str = "",
        search_limit: int = 5,
        extract_chars: int = 900,
        prefer_hd2: bool = True,
        retry_max_attempts: int = 3,
        retry_base_delay: float = 2.0,
        session: aiohttp.ClientSession | None = None,
        cache: WikiCache | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_path = api_path if api_path.startswith("/") else f"/{api_path}"
        self.user_agent = user_agent
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.proxy_url = proxy_url or None
        self.search_limit = max(1, min(10, int(search_limit)))
        self.extract_chars = max(200, min(2000, int(extract_chars)))
        self.prefer_hd2 = prefer_hd2
        self.retry_max_attempts = max(1, int(retry_max_attempts))
        self.retry_base_delay = float(retry_base_delay)
        self._session = session
        self._own_session = False
        self.cache = cache

    @property
    def api_url(self) -> str:
        return f"{self.base_url}{self.api_path}"

    def bind_session(self, session: aiohttp.ClientSession | None) -> None:
        self._session = session
        self._own_session = False

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is not None and not self._session.closed:
            return self._session
        self._session = aiohttp.ClientSession(
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
            timeout=self.timeout,
        )
        self._own_session = True
        return self._session

    async def close(self) -> None:
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()
        if self._own_session:
            self._session = None
            self._own_session = False
        if self.cache:
            self.cache.save()

    def page_url(self, title: str) -> str:
        return f"{self.base_url}/wiki/{quote(title.replace(' ', '_'), safe=':/')}"

    def search_url(self, query: str) -> str:
        return f"{self.base_url}/index.php?{urlencode({'search': query, 'title': 'Special:Search'})}"

    async def _get_api(self, params: dict[str, Any]) -> Any | None:
        params = dict(params)
        params.setdefault("format", "json")
        params.setdefault("formatversion", "2")
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(1, self.retry_max_attempts + 1):
            try:
                session = await self._ensure_session()
                async with session.get(
                    self.api_url,
                    params=params,
                    headers=headers,
                    proxy=self.proxy_url,
                    timeout=self.timeout,
                ) as resp:
                    if resp.status == 200:
                        return await resp.json(content_type=None)
                    if (
                        resp.status in {429, 500, 502, 503, 504}
                        and attempt < self.retry_max_attempts
                    ):
                        delay = self.retry_base_delay * attempt
                        logger.warning(
                            f"[HD2] wiki API status={resp.status}, retry {attempt} after {delay:.1f}s"
                        )
                        await asyncio.sleep(delay)
                        continue
                    logger.error(
                        f"[HD2] wiki API failed status={resp.status} params={params}"
                    )
                    return None
            except asyncio.CancelledError:
                raise
            except Exception as e:
                last_error = e
                if attempt < self.retry_max_attempts:
                    delay = self.retry_base_delay * attempt
                    logger.warning(f"[HD2] wiki API error={e}, retry {attempt}")
                    await asyncio.sleep(delay)
                    continue
                logger.error(f"[HD2] wiki API final error: {e}")
                return None
        if last_error:
            logger.error(f"[HD2] wiki API exhausted retries: {last_error}")
        return None

    def _filter_results(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.prefer_hd2:
            return results
        hd2 = [r for r in results if not _is_hd1_title(str(r.get("title", "")))]
        # 若过滤后为空，回退全部结果，避免中文/冷门词完全无结果
        return hd2 or results

    async def search(
        self, query: str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []
        limit = max(1, min(10, int(limit or self.search_limit)))
        cache_key = f"search:{limit}:{hashlib.sha1(query.lower().encode()).hexdigest()}"
        if self.cache:
            cached = await self.cache.get(cache_key)
            if isinstance(cached, list):
                return cached

        # 多取一些再过滤 HD1
        fetch_limit = min(20, limit * 3 if self.prefer_hd2 else limit)
        data = await self._get_api(
            {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": fetch_limit,
                "srnamespace": 0,
                "srprop": "snippet|titlesnippet",
            }
        )
        results: list[dict[str, Any]] = []
        if isinstance(data, dict):
            hits = ((data.get("query") or {}).get("search")) or []
            for hit in hits:
                title = hit.get("title") or ""
                if not title:
                    continue
                results.append(
                    {
                        "title": title,
                        "pageid": hit.get("pageid"),
                        "snippet": _strip_html_snippet(hit.get("snippet") or ""),
                    }
                )

        # opensearch 兜底：list=search 为空时
        if not results:
            open_data = await self._get_api(
                {
                    "action": "opensearch",
                    "search": query,
                    "limit": fetch_limit,
                    "namespace": 0,
                    "redirects": "resolve",
                }
            )
            if isinstance(open_data, list) and len(open_data) >= 2:
                titles = open_data[1] or []
                urls = open_data[3] if len(open_data) > 3 else []
                for i, title in enumerate(titles):
                    results.append(
                        {
                            "title": title,
                            "pageid": None,
                            "snippet": "",
                            "url": urls[i] if i < len(urls) else self.page_url(title),
                        }
                    )

        results = self._filter_results(results)[:limit]
        if self.cache:
            await self.cache.set(cache_key, results, self.cache.search_ttl)
        return results

    async def get_page_summary(self, title: str) -> Optional[dict[str, Any]]:
        title = (title or "").strip()
        if not title:
            return None
        cache_key = f"page:{title}"
        if self.cache:
            cached = await self.cache.get(cache_key)
            if isinstance(cached, dict) and cached.get("title"):
                return cached

        data = await self._get_api(
            {
                "action": "query",
                "prop": "extracts|info",
                "exintro": 1,
                "explaintext": 1,
                "exchars": self.extract_chars,
                "inprop": "url",
                "titles": title,
                "redirects": 1,
            }
        )
        page = self._first_page(data)
        if not page or page.get("missing"):
            return None

        extract = (page.get("extract") or "").strip()
        if not extract:
            extract = await self._fallback_wikitext_extract(page.get("title") or title)

        result = {
            "title": page.get("title") or title,
            "pageid": page.get("pageid"),
            "extract": extract or "",
            "url": page.get("fullurl") or self.page_url(page.get("title") or title),
        }
        if self.cache:
            await self.cache.set(cache_key, result, self.cache.page_ttl)
        return result

    async def _fallback_wikitext_extract(self, title: str) -> str:
        data = await self._get_api(
            {
                "action": "query",
                "prop": "revisions",
                "rvprop": "content",
                "rvslots": "main",
                "titles": title,
                "redirects": 1,
            }
        )
        page = self._first_page(data)
        if not page:
            return ""
        revisions = page.get("revisions") or []
        if not revisions:
            return ""
        rev = revisions[0]
        # formatversion=2 可能直接 content；旧结构在 slots.main
        content = rev.get("content")
        if content is None:
            slots = rev.get("slots") or {}
            main = slots.get("main") or {}
            content = main.get("content") or main.get("*") or ""
        text = str(content or "")
        # 粗清理 wikitext
        text = re.sub(r"\{\{[^}]*\}\}", " ", text)
        text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)
        text = re.sub(r"'{2,}", "", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > self.extract_chars:
            text = text[: self.extract_chars - 3] + "..."
        return text

    @staticmethod
    def _first_page(data: Any) -> dict[str, Any] | None:
        if not isinstance(data, dict):
            return None
        query = data.get("query") or {}
        pages = query.get("pages")
        if isinstance(pages, list) and pages:
            return pages[0] if isinstance(pages[0], dict) else None
        if isinstance(pages, dict) and pages:
            first = next(iter(pages.values()))
            return first if isinstance(first, dict) else None
        return None

    def pick_best_title(self, query: str, results: list[dict[str, Any]]) -> str | None:
        """唯一高置信匹配时返回标题，否则 None。"""
        if not results:
            return None
        q = query.strip().lower()
        exact = [r for r in results if str(r.get("title", "")).lower() == q]
        if len(exact) == 1:
            return str(exact[0]["title"])
        if len(results) == 1:
            return str(results[0]["title"])
        # 标题大小写不敏感唯一
        titles_lower = {str(r.get("title", "")).lower() for r in results}
        if len(titles_lower) == 1:
            return str(results[0]["title"])
        return None
