"""Helldivers 2 社区 API 客户端。"""

from __future__ import annotations

import asyncio
import random
import re
from datetime import datetime, timezone
from typing import Any, Optional

import aiohttp
from astrbot.api import logger


class HD2Client:
    """统一的 HD2 API 访问层，带有限次重试 + 全局限流。"""

    RETRY_STATUSES = {429, 500, 502, 503, 504}
    COMPANION_NEWS_URL = "https://helldiverscompanion.com/api/steam-api/news"

    def __init__(
        self,
        *,
        base_url: str = "https://api.helldivers2.dev",
        war_id: int = 801,
        client_name: str = "astrbot_plugin_Helldivers",
        contact: str = "",
        user_agent: str = "astrbot_plugin_Helldivers/1.0",
        timeout: int = 30,
        proxy_url: str = "",
        retry_base_delay: float = 5.0,
        retry_max_delay: float = 45.0,
        retry_max_attempts: int = 3,
        min_request_interval: float = 1.5,
        steam_appid: int = 553850,
        steam_news_count: int = 10,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.war_id = war_id
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.proxy_url = proxy_url or None
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        self.retry_max_attempts = max(1, retry_max_attempts)
        self.min_request_interval = max(0.0, float(min_request_interval))
        self.steam_appid = max(1, int(steam_appid))
        self.steam_news_count = max(1, min(50, int(steam_news_count)))
        self.headers = {
            "X-Super-Client": client_name or "astrbot_plugin_Helldivers",
            "X-Super-Contact": contact or "noreply@example.com",
            "User-Agent": user_agent or "astrbot_plugin_Helldivers/1.0",
            "Accept": "application/json",
        }
        self._session: aiohttp.ClientSession | None = None
        self._rate_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._cooldown_until = 0.0  # 429 后全局冷却

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers=self.headers,
                timeout=self.timeout,
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}{path if path.startswith('/') else '/' + path}"

    async def _throttle(self) -> None:
        """全局限流：请求间隔 + 429 冷却。"""
        async with self._rate_lock:
            now = asyncio.get_running_loop().time()
            wait_cd = self._cooldown_until - now
            wait_gap = self.min_request_interval - (now - self._last_request_at)
            wait = max(0.0, wait_cd, wait_gap)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = asyncio.get_running_loop().time()

    def _note_rate_limit(self, retry_after: float | None = None) -> None:
        # 默认至少冷却 20s，尊重 Retry-After
        cool = max(20.0, float(retry_after or 0.0))
        cool = min(cool, 120.0)
        now = asyncio.get_running_loop().time()
        self._cooldown_until = max(self._cooldown_until, now + cool)

    @staticmethod
    def _parse_retry_after(resp: aiohttp.ClientResponse) -> float | None:
        raw = resp.headers.get("Retry-After")
        if not raw:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        url = self._url(path)
        headers = dict(self.headers)
        if extra_headers:
            headers.update(extra_headers)

        last_error: Exception | None = None
        for attempt in range(1, self.retry_max_attempts + 1):
            try:
                await self._throttle()
                session = await self.get_session()
                async with session.request(
                    method,
                    url,
                    json=json_body,
                    headers=headers,
                    proxy=self.proxy_url,
                ) as resp:
                    if resp.status == 200:
                        return await resp.json(content_type=None)

                    body_preview = ""
                    try:
                        body_preview = (await resp.text())[:200]
                    except Exception:
                        pass

                    if (
                        resp.status in self.RETRY_STATUSES
                        and attempt < self.retry_max_attempts
                    ):
                        retry_after = self._parse_retry_after(resp)
                        if resp.status == 429:
                            self._note_rate_limit(retry_after)
                            # 429 用更长退避
                            delay = retry_after or min(
                                max(self.retry_base_delay * 2 * attempt, 10.0),
                                self.retry_max_delay,
                            )
                        else:
                            delay = min(
                                self.retry_base_delay * attempt,
                                self.retry_max_delay,
                            )
                        delay *= 1 + random.uniform(0, 0.15)
                        logger.warning(
                            f"HD2 API {method} {url} status={resp.status}, "
                            f"retry {attempt}/{self.retry_max_attempts} after {delay:.1f}s"
                        )
                        await asyncio.sleep(delay)
                        continue

                    if resp.status == 429:
                        self._note_rate_limit(self._parse_retry_after(resp))
                    logger.error(
                        f"HD2 API {method} {url} failed status={resp.status} body={body_preview}"
                    )
                    return None
            except asyncio.CancelledError:
                raise
            except Exception as e:
                last_error = e
                err_s = str(e).lower()
                # DNS / 主机不存在：重试无意义，快速失败
                non_retryable = (
                    "name or service not known" in err_s
                    or "nodename nor servname" in err_s
                    or "getaddrinfo failed" in err_s
                    or "name resolution" in err_s
                )
                if non_retryable:
                    logger.warning(f"HD2 API {method} {url} non-retryable error: {e}")
                    return None
                if attempt < self.retry_max_attempts:
                    delay = min(
                        self.retry_base_delay * attempt,
                        self.retry_max_delay,
                    )
                    logger.warning(
                        f"HD2 API {method} {url} error={e}, "
                        f"retry {attempt}/{self.retry_max_attempts} after {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error(f"HD2 API {method} {url} final error: {e}")
                return None

        if last_error:
            logger.error(f"HD2 API {method} {url} exhausted retries: {last_error}")
        return None

    async def get_json(self, path: str) -> Any:
        return await self.request_json("GET", path)

    async def post_json(self, path: str, body: dict[str, Any]) -> Any:
        return await self.request_json("POST", path, json_body=body)

    # ---- domain endpoints ----

    async def fetch_war_summary(self) -> Optional[dict[str, Any]]:
        """获取战争统计，保留 galaxy_stats 与 planets_stats 完整结构。"""
        data = await self.get_json(f"/raw/api/Stats/war/{self.war_id}/summary")
        return data if isinstance(data, dict) else None

    async def fetch_war_status(self) -> Optional[dict[str, Any]]:
        """获取完整 raw WarStatus，供战争日、事件和地图共用。"""
        data = await self.get_json(f"/raw/api/WarSeason/{self.war_id}/Status")
        return data if isinstance(data, dict) else None

    async def fetch_war_status_events(self) -> Optional[list[dict[str, Any]]]:
        """兼容旧缓存键：从完整 WarStatus 提取全球事件。"""
        data = await self.fetch_war_status()
        if data is None:
            return None
        events = data.get("globalEvents")
        return events if isinstance(events, list) else []

    async def fetch_steam_app_details(
        self, appid: int | None = None
    ) -> Optional[dict[str, Any]]:
        """获取 Steam 商店元数据，用于新闻无配图时的官方横幅。"""
        appid = self.steam_appid if appid is None else max(1, int(appid))
        url = (
            "https://store.steampowered.com/api/appdetails"
            f"?appids={appid}&l=schinese&cc=cn"
        )
        data = await self.get_json(url)
        if not isinstance(data, dict):
            return None
        item = data.get(str(appid))
        if not isinstance(item, dict) or not item.get("success"):
            return None
        details = item.get("data")
        return details if isinstance(details, dict) else None

    async def fetch_steam_updates_official(
        self, appid: int | None = None, count: int | None = None
    ) -> Optional[list[dict[str, Any]]]:
        """直接读取 Steam 官方公告接口（无需 Web API Key）。"""
        appid = self.steam_appid if appid is None else max(1, int(appid))
        count = self.steam_news_count if count is None else max(1, min(50, int(count)))
        url = (
            "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
            f"?appid={appid}&count={count}"
            "&maxlength=0&feeds=steam_community_announcements&format=json"
        )
        data = await self.get_json(url)
        if not isinstance(data, dict):
            return None
        appnews = data.get("appnews")
        if not isinstance(appnews, dict):
            return None
        items = appnews.get("newsitems")
        if not isinstance(items, list):
            return None
        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("feedname") not in (None, "steam_community_announcements"):
                continue
            normalized.append(
                {
                    "id": str(item.get("gid") or ""),
                    "title": str(item.get("title") or ""),
                    "url": str(item.get("url") or ""),
                    "author": str(item.get("author") or ""),
                    "content": str(item.get("contents") or ""),
                    "publishedAt": item.get("date"),
                    "feedname": item.get("feedname"),
                    "feedLabel": item.get("feedlabel"),
                    "tags": item.get("tags")
                    if isinstance(item.get("tags"), list)
                    else [],
                    "isExternalUrl": bool(item.get("is_external_url")),
                    "source": "steam",
                }
            )
        normalized.sort(key=lambda x: int(x.get("publishedAt") or 0), reverse=True)
        return normalized

    async def fetch_steam_updates_community(self) -> Optional[list[dict[str, Any]]]:
        """社区 API Steam 新闻回退源。"""
        data = await self.get_json("/api/v1/steam")
        if not isinstance(data, list):
            return None
        return sorted(data, key=lambda x: x.get("publishedAt", ""), reverse=True)

    async def fetch_steam_updates(self) -> Optional[list[dict[str, Any]]]:
        """Steam 官方源优先，失败时回退社区 API。"""
        official = await self.fetch_steam_updates_official()
        if official is not None:
            return official
        return await self.fetch_steam_updates_community()

    async def fetch_steam_metadata(self) -> Optional[dict[str, Any]]:
        return await self.fetch_steam_app_details()

    async def fetch_war_v1(self) -> Optional[dict[str, Any]]:
        data = await self.get_json("/api/v1/war")
        return data if isinstance(data, dict) else None

    @staticmethod
    def _looks_like_assignment(data: dict[str, Any]) -> bool:
        return bool(
            data.get("id") is not None
            or isinstance(data.get("setting"), dict)
            or data.get("expiresIn") is not None
        )

    async def fetch_major_orders(self) -> Optional[list[dict[str, Any]]]:
        data = await self.get_json(f"/raw/api/v2/Assignment/War/{self.war_id}")
        if data is None:
            return None
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict) and item]
        if isinstance(data, dict):
            for key in ("assignments", "data", "orders"):
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict) and item]
                if isinstance(value, dict):
                    return [value] if self._looks_like_assignment(value) else []
            return [data] if self._looks_like_assignment(data) else []
        return None

    async def fetch_dispatches(self) -> Optional[list[dict[str, Any]]]:
        """Fetch Super Earth High Command dispatches (not Steam patch notes).

        Same community endpoint family used by Galactic Wide Web style bots:
        ``https://api.helldivers2.dev/api/v1/dispatches``.
        """
        data = await self.get_json("/api/v1/dispatches")
        if not isinstance(data, list):
            return None
        records = [item for item in data if isinstance(item, dict)]
        return sorted(records, key=lambda x: x.get("published", ""), reverse=True)

    async def fetch_companion_news(self) -> Optional[list[dict[str, Any]]]:
        """Fetch latest news displayed by Helldivers Companion's public news page."""

        data = await self.request_json("GET", self.COMPANION_NEWS_URL)
        appnews = data.get("appnews") if isinstance(data, dict) else None
        items = appnews.get("newsitems") if isinstance(appnews, dict) else None
        if not isinstance(items, list):
            return await self.fetch_dispatches()
        records: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            contents = str(item.get("contents") or "")
            image_url = self._companion_image_url(contents)
            try:
                published = datetime.fromtimestamp(
                    int(item.get("date") or 0), timezone.utc
                ).isoformat().replace("+00:00", "Z")
            except (TypeError, ValueError, OSError, OverflowError):
                published = ""
            records.append(
                {
                    "id": str(item.get("gid") or ""),
                    "title": str(item.get("title") or "银河战报"),
                    "message": contents,
                    "published": published,
                    "type": 0,
                    "image_url": image_url,
                    "source": "helldiverscompanion",
                }
            )
        return sorted(records, key=lambda item: item.get("published", ""), reverse=True)

    @staticmethod
    def _companion_image_url(contents: str) -> str | None:
        """Extract the first Steam CDN image without accepting arbitrary hosts."""

        match = re.search(r"\[img\s+src=[\"']([^\"']+)[\"']\s*\]", contents, re.I)
        if match is None:
            match = re.search(r"\[img\](https://[^\[\s]+)\[/img\]", contents, re.I)
        if match is None:
            return None
        url = match.group(1).replace(
            "{STEAM_CLAN_IMAGE}", "https://clan.akamai.steamstatic.com"
        )
        return url if url.startswith("https://clan.akamai.steamstatic.com/") else None

    async def fetch_steam_updates_legacy(self) -> Optional[list[dict[str, Any]]]:
        """旧名称保留给外部引用；内部已改用官方源优先。"""
        return await self.fetch_steam_updates()

    async def fetch_planets(self) -> Optional[list[dict[str, Any]]]:
        data = await self.get_json("/api/v1/planets")
        return data if isinstance(data, list) else None

    async def fetch_campaigns(self) -> Optional[list[dict[str, Any]]]:
        data = await self.get_json("/api/v1/campaigns")
        return data if isinstance(data, list) else None

    async def fetch_planet_events(self) -> Optional[list[dict[str, Any]]]:
        data = await self.get_json("/api/v1/planet-events")
        return data if isinstance(data, list) else None

    async def fetch_assignments_v1(self) -> Optional[list[dict[str, Any]]]:
        data = await self.get_json("/api/v1/assignments")
        return data if isinstance(data, list) else None

    async def fetch_space_stations(self) -> Optional[list[dict[str, Any]]]:
        # v2 优先，失败回退 v1
        data = await self.get_json("/api/v2/space-stations")
        if isinstance(data, list):
            return data
        data = await self.get_json("/api/v1/space-stations")
        return data if isinstance(data, list) else None

    async def fetch_global_events(self) -> Optional[list[dict[str, Any]]]:
        """兼容旧调用：从 raw WarStatus 提取 globalEvents。"""
        return await self.fetch_war_status_events()

    async def fetch_personal_order(
        self, api_url: str | None = None
    ) -> Optional[dict[str, Any] | list[Any]]:
        """个人任务：仅使用用户配置的 URL（公开社区 API 通常不提供 PO）。

        说明：
        - diveharder 等第三方代理经常 DNS/服务不可用，默认不再硬编码探测，
          避免每次 /personal_order 卡 10+ 秒重试。
        - 需要时在配置 personal_order_api_url 填入可用 JSON 源。
        """
        url = (api_url or "").strip()
        if not url:
            return None
        # 可选源：失败快速返回，不占用默认 3 次长退避
        old_attempts = self.retry_max_attempts
        old_timeout = self.timeout
        try:
            self.retry_max_attempts = 1
            self.timeout = aiohttp.ClientTimeout(
                total=min(10, int(old_timeout.total or 10))
            )
            data = await self.get_json(url)
            # 空列表也算“有响应”：表示当前无个人任务
            if data is not None:
                return data
            return None
        finally:
            self.retry_max_attempts = old_attempts
            self.timeout = old_timeout
