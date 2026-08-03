"""业务编排：缓存读取、翻译、格式化。"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import re
from pathlib import Path
from typing import Any

from astrbot.api import logger

from .api_client import HD2Client
from .awaiting_orders_renderer import AwaitingOrdersRenderer
from .cache import CacheService
from .campaign_trends import CampaignTrendStore
from .dashboard_renderer import DashboardRenderer
from .dss_renderer import DSSRenderer
from .dispatch_renderer import DispatchRenderer
from .global_event_renderer import GlobalEventRenderer
from .i18n import known_planet_names, lookup_planet_name
from .formatters import (
    WIKI_USAGE,
    format_dss_message,
    format_global_events_message,
    format_map_caption,
    format_news_message,
    format_order_message,
    format_personal_order_message,
    format_planet_candidates,
    format_planet_message,
    format_stats_message,
    format_steam_message,
    format_warfront_message,
    format_wiki_search_results,
    format_wiki_summary,
)
from .card_renderer import CardRenderer
from .card_specs import (
    build_dashboard_card,
    build_dss_card,
    build_global_events_card,
    build_news_card,
    build_order_card,
    build_personal_order_card,
    build_planet_candidates_card,
    build_planet_card,
    build_stats_card,
    build_warfront_card,
)
from .map_renderer import MapRenderer
from .major_order_renderer import MajorOrderRenderer
from .remote_image_cache import RemoteImageCache
from .stats_model import build_stats_view_model
from .stats_renderer import StatsRenderer
from .steam_parser import ParsedSteamContent, SteamBlock, parse_steam_content
from .text_utils import clean_game_text
from .steam_renderer import SteamRenderer
from .translator import TranslationCache, TranslationService
from .war_state import WarState, normalize_faction
from .warfront_renderer import WarfrontRenderer
from .wiki_client import WikiClient


class HelldiversService:
    """Helldivers 查询服务。"""

    CACHE_WAR_SUMMARY = "war_summary"
    CACHE_WAR_V1 = "war_v1"
    CACHE_WAR_STATUS = "war_status"
    CACHE_ORDERS = "major_orders"
    # Bump cache key so any previous Companion/Steam news cache is never reused.
    CACHE_DISPATCHES = "dispatches_api_v1"
    CACHE_STEAM = "steam_updates"
    CACHE_PLANETS = "planets"
    CACHE_CAMPAIGNS = "campaigns"
    CACHE_PLANET_EVENTS = "planet_events"
    CACHE_SPACE_STATIONS = "space_stations"
    CACHE_ASSIGNMENTS_V1 = "assignments_v1"
    CACHE_GLOBAL_EVENTS = "global_events"  # 旧磁盘缓存兼容
    CACHE_STEAM_METADATA = "steam_metadata"

    def __init__(
        self,
        client: HD2Client,
        cache: CacheService,
        translator: TranslationService,
        translation_cache: TranslationCache,
        *,
        steam_max_content_length: int = 2000,
        steam_balancing_limit: int = 800,
        steam_fixes_limit: int = 600,
        steam_issues_limit: int = 300,
        steam_max_sections: int = 3,
        steam_image_enabled: bool = True,
        rotation_dispatches: int = 300,
        rotation_orders: int = 600,
        rotation_steam: int = 900,
        enable_translation: bool = True,
        ui_language: str = "zh-CN",
        wiki_client: WikiClient | None = None,
        enable_wiki: bool = True,
        translate_wiki: bool = True,
        map_renderer: MapRenderer | None = None,
        enable_map: bool = True,
        personal_order_api_url: str = "",
        allow_private_personal_order_url: bool = False,
        card_renderer: CardRenderer | None = None,
        dashboard_renderer: DashboardRenderer | None = None,
        stats_renderer: StatsRenderer | None = None,
        dss_renderer: DSSRenderer | None = None,
        major_order_renderer: MajorOrderRenderer | None = None,
        awaiting_orders_renderer: AwaitingOrdersRenderer | None = None,
        dispatch_renderer: DispatchRenderer | None = None,
        warfront_renderer: WarfrontRenderer | None = None,
        global_event_renderer: GlobalEventRenderer | None = None,
        steam_renderer: SteamRenderer | None = None,
        remote_image_cache: RemoteImageCache | None = None,
        campaign_trends: CampaignTrendStore | None = None,
        dashboard_low_impact_threshold: int = 800,
    ) -> None:
        self.client = client
        self.cache = cache
        self.translator = translator
        self.translation_cache = translation_cache
        self.steam_max_content_length = steam_max_content_length
        self.steam_balancing_limit = steam_balancing_limit
        self.steam_fixes_limit = steam_fixes_limit
        self.steam_issues_limit = steam_issues_limit
        self.steam_max_sections = steam_max_sections
        self.steam_image_enabled = bool(steam_image_enabled)
        self.rotation_dispatches = max(60, int(rotation_dispatches))
        self.rotation_orders = max(60, int(rotation_orders))
        self.rotation_steam = max(60, int(rotation_steam))
        self.enable_translation = enable_translation
        self.ui_language = ui_language if ui_language == "zh-CN" else "zh-CN"
        self.wiki_client = wiki_client
        self.enable_wiki = enable_wiki
        self.translate_wiki = translate_wiki and enable_translation
        self.map_renderer = map_renderer
        self.enable_map = enable_map
        self.personal_order_api_url = personal_order_api_url or ""
        self.allow_private_personal_order_url = bool(
            allow_private_personal_order_url
        )
        self.card_renderer = card_renderer
        self.dashboard_renderer = dashboard_renderer
        self.stats_renderer = stats_renderer
        self.dss_renderer = dss_renderer
        self.major_order_renderer = major_order_renderer
        self.awaiting_orders_renderer = awaiting_orders_renderer
        self.dispatch_renderer = dispatch_renderer
        self.warfront_renderer = warfront_renderer
        self.global_event_renderer = global_event_renderer
        self.steam_renderer = steam_renderer
        self.remote_image_cache = remote_image_cache
        self.campaign_trends = campaign_trends
        self.dashboard_low_impact_threshold = max(
            0, int(dashboard_low_impact_threshold or 800)
        )

        self._rotation_tasks: list[asyncio.Task] = []
        self._trend_task: asyncio.Task | None = None
        self._warmup_task: asyncio.Task | None = None
        self._register_fetchers()

    async def _render_card(self, card) -> Path | None:
        if self.card_renderer is None or not self.card_renderer.available:
            return None
        return await asyncio.to_thread(self.card_renderer.render, card)

    def _register_fetchers(self) -> None:
        self.cache.register(self.CACHE_WAR_SUMMARY, self.client.fetch_war_summary)
        self.cache.register(self.CACHE_WAR_V1, self.client.fetch_war_v1)
        self.cache.register(self.CACHE_WAR_STATUS, self.client.fetch_war_status)
        self.cache.register(self.CACHE_ORDERS, self.client.fetch_major_orders)
        self.cache.register(self.CACHE_DISPATCHES, self.client.fetch_dispatches)
        self.cache.register(self.CACHE_STEAM, self.client.fetch_steam_updates)
        self.cache.register(self.CACHE_PLANETS, self.client.fetch_planets)
        self.cache.register(self.CACHE_CAMPAIGNS, self.client.fetch_campaigns)
        self.cache.register(self.CACHE_PLANET_EVENTS, self.client.fetch_planet_events)
        self.cache.register(self.CACHE_SPACE_STATIONS, self.client.fetch_space_stations)
        self.cache.register(self.CACHE_ASSIGNMENTS_V1, self.client.fetch_assignments_v1)

    async def start(self) -> None:
        await self.cache.start()
        # 顺序预热缺失缓存（不再并发，避免启动即 429）
        self._warmup_task = asyncio.create_task(
            self._warmup_cache(), name="hd2-cache-warmup"
        )
        if self.campaign_trends is not None:
            self._trend_task = asyncio.create_task(
                self._campaign_trend_loop(), name="hd2-campaign-trends"
            )
        if self.enable_translation:
            self._rotation_tasks = [
                asyncio.create_task(
                    self._rotation_loop("dispatches", self.rotation_dispatches),
                    name="hd2-tr-dispatches",
                ),
                asyncio.create_task(
                    self._rotation_loop("orders", self.rotation_orders),
                    name="hd2-tr-orders",
                ),
                asyncio.create_task(
                    self._rotation_loop("steam", self.rotation_steam),
                    name="hd2-tr-steam",
                ),
            ]
            logger.info("[HD2] translation rotation tasks started")

    async def _warmup_cache(self) -> None:
        """顺序预热：仅刷新磁盘/内存缺失的核心键。"""
        try:
            # 让后台 refresh_all 先起步一点，错开
            await asyncio.sleep(1.0)
            for name in (
                self.CACHE_WAR_SUMMARY,
                self.CACHE_WAR_STATUS,
                self.CACHE_ORDERS,
                self.CACHE_PLANETS,
                self.CACHE_CAMPAIGNS,
            ):
                # 已有缓存则跳过（soft_ttl 内）
                if await self.cache.get(name) is not None:
                    continue
                await self.cache.refresh_one(name, force=True)
                await asyncio.sleep(max(self.cache.request_delay, 2.0))
            logger.info("[HD2] cache warmup completed")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"[HD2] cache warmup failed: {e}")

    async def stop(self) -> None:
        if self._warmup_task and not self._warmup_task.done():
            self._warmup_task.cancel()
            await asyncio.gather(self._warmup_task, return_exceptions=True)
        self._warmup_task = None
        if self._trend_task and not self._trend_task.done():
            self._trend_task.cancel()
            await asyncio.gather(self._trend_task, return_exceptions=True)
        self._trend_task = None
        for task in self._rotation_tasks:
            if task and not task.done():
                task.cancel()
        if self._rotation_tasks:
            await asyncio.gather(*self._rotation_tasks, return_exceptions=True)
        self._rotation_tasks = []
        await self.cache.stop()
        if self.wiki_client is not None:
            try:
                await self.wiki_client.close()
            except Exception as e:
                logger.warning(f"[HD2] wiki client close error: {e}")
        if self.remote_image_cache is not None:
            try:
                await self.remote_image_cache.close()
            except Exception as e:
                logger.warning(f"[HD2] remote image cache close error: {e}")
        await self.translator.close()
        await self.client.close()
        self.translation_cache.save()

    async def _campaign_trend_loop(self) -> None:
        """定期记录缓存中的战役进度，不额外请求 API。"""
        await asyncio.sleep(8)
        while True:
            try:
                campaigns = await self.cache.get(self.CACHE_CAMPAIGNS)
                if isinstance(campaigns, list) and self.campaign_trends is not None:
                    state = WarState(campaigns=campaigns)
                    await asyncio.to_thread(
                        self.campaign_trends.record_rows, state.campaign_rows()
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[HD2] campaign trend sample failed: {e}")
            try:
                await asyncio.sleep(max(60, self.cache.update_interval))
            except asyncio.CancelledError:
                break

    async def _rotation_loop(self, kind: str, interval: int) -> None:
        # 稍等 API 缓存先填一轮
        await asyncio.sleep(min(10, interval // 10 or 1))
        while True:
            try:
                if kind == "dispatches":
                    await self.ensure_dispatches_translated()
                elif kind == "orders":
                    await self.ensure_orders_translated()
                elif kind == "steam":
                    await self.ensure_steam_translated()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception(f"[HD2] translation rotation ({kind}) error")
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

    # ---- stats ----

    @staticmethod
    def _subtitle() -> str:
        from datetime import datetime

        return datetime.now().strftime("更新 %m-%d %H:%M")

    async def get_stats_images(self) -> list[Path]:
        summary = await self.cache.get_or_refresh(self.CACHE_WAR_SUMMARY)
        war_v1 = await self.cache.get_or_refresh(self.CACHE_WAR_V1)
        planets = await self.cache.get_or_refresh(self.CACHE_PLANETS)
        war_status = await self.cache.get_or_refresh(self.CACHE_WAR_STATUS)
        if not summary and not war_v1:
            return []
        if self.stats_renderer is not None:
            model = build_stats_view_model(
                summary,
                planets=planets if isinstance(planets, list) else [],
                war=war_v1 if isinstance(war_v1, dict) else {},
                status=war_status if isinstance(war_status, dict) else {},
            )
            distribution = model.get("distribution")
            if isinstance(distribution, dict):
                top_planets = distribution.get("top_planets")
                if isinstance(top_planets, list):
                    await self._localize_planet_rows(
                        [item for item in top_planets if isinstance(item, dict)],
                        include_english=False,
                    )
            p = await asyncio.to_thread(self.stats_renderer.render, model)
            return [p] if p else []
        card = build_stats_card(summary, war_v1, subtitle=self._subtitle())
        p = await self._render_card(card)
        return [p] if p else []

    async def get_stats_message(self) -> str:
        summary = await self.cache.get_or_refresh(self.CACHE_WAR_SUMMARY)
        war_v1 = await self.cache.get_or_refresh(self.CACHE_WAR_V1)
        if not summary and not war_v1:
            return "❌ 暂时无法获取银河战争统计，数据可能正在同步，请稍后重试。"
        legacy_summary = (
            summary.get("galaxy_stats")
            if isinstance(summary, dict)
            and isinstance(summary.get("galaxy_stats"), dict)
            else summary
        )
        return format_stats_message(legacy_summary, war_v1)

    # ---- orders ----

    async def ensure_orders_translated(self) -> None:
        orders = await self.cache.get(self.CACHE_ORDERS)
        if not orders:
            return
        ids = [str(o.get("id", i)) for i, o in enumerate(orders)]
        await self.translation_cache.clear_outdated("orders", ids)
        for order in orders:
            await self._translate_order(order)
            await asyncio.sleep(0.1)

    async def _translate_order(self, order: dict[str, Any]) -> dict[str, str]:
        setting = order.get("setting") or {}
        item_id = str(order.get("id", 0))
        fields = {
            "title": str(setting.get("overrideTitle") or ""),
            "brief": str(setting.get("overrideBrief") or ""),
            "task": str(setting.get("taskDescription") or ""),
        }
        if not self.enable_translation:
            return fields

        result: dict[str, str] = {}
        for field, original in fields.items():
            result[field] = (
                await self._translate_cached_text(
                    "order_field", f"{item_id}:{field}", original
                )
                if original
                else ""
            )
        return result

    async def _load_orders(self) -> list[dict[str, Any]] | None:
        orders = await self.cache.get_or_refresh(self.CACHE_ORDERS)
        # 注意：API 可能返回空列表 []（当前无活跃最高命令），不能用 `not orders`
        if orders is None:
            orders = await self.cache.get_or_refresh(self.CACHE_ASSIGNMENTS_V1)
        if orders is None:
            return None
        if not isinstance(orders, list):
            return []
        return orders

    async def get_order_images(self) -> list[Path]:
        orders = await self._load_orders()
        if orders is None:
            return []
        if len(orders) == 0:
            if self.awaiting_orders_renderer is not None:
                p = await asyncio.to_thread(self.awaiting_orders_renderer.render)
                return [p] if p else []
            # 专用 renderer 不可用时才回退通用卡。
            from .card_renderer import Card, FACTION_COLORS

            card = Card(
                title="AW · 等待最高命令",
                accent=FACTION_COLORS["Humans"],
                emblem="super_earth",
                footer="",
            )
            card.text("等待超级地球最高指挥部的进一步指示")
            p = await self._render_card(card)
            return [p] if p else []
        paths: list[Path] = []
        for i, order in enumerate(orders, 1):
            fields = await self._translate_order(order)
            if self.major_order_renderer is not None:
                p = await asyncio.to_thread(
                    self.major_order_renderer.render,
                    order,
                    index=i,
                    title=fields["title"],
                    brief=fields["brief"],
                    task_desc=fields["task"],
                )
                if p:
                    paths.append(p)
                continue
            card = build_order_card(
                order,
                index=i,
                title=fields["title"],
                brief=fields["brief"],
                task_desc=fields["task"],
            )
            p = await self._render_card(card)
            if p:
                paths.append(p)
        return paths

    async def get_order_messages(self) -> list[str]:
        orders = await self._load_orders()
        if orders is None:
            return ["❌ 暂时无法获取最高命令，数据源请求失败，请稍后重试。"]
        if len(orders) == 0:
            return ["📋 当前没有活跃的最高命令"]

        messages: list[str] = []
        for i, order in enumerate(orders, 1):
            fields = await self._translate_order(order)
            messages.append(
                format_order_message(
                    order,
                    index=i,
                    title=fields["title"],
                    brief=fields["brief"],
                    task_desc=fields["task"],
                )
            )
        return messages

    # ---- news ----

    async def ensure_dispatches_translated(self) -> None:
        dispatches = await self.cache.get(self.CACHE_DISPATCHES)
        if not dispatches:
            return
        top = dispatches[:5]
        ids = [str(d.get("id", i)) for i, d in enumerate(top)]
        await self.translation_cache.clear_outdated("dispatches", ids)
        for d in top:
            await self._translate_dispatch(d)
            await asyncio.sleep(0.1)

    @staticmethod
    def _normalize_dispatch(dispatch: dict[str, Any]) -> dict[str, Any]:
        """Normalize community API dispatches the same way GWW does."""

        item = dict(dispatch)
        raw = str(item.get("message") or "")
        match = re.match(r"^<i=\d+>(.*?)</i>\s*", raw, re.DOTALL | re.IGNORECASE)
        title = ""
        body = raw
        if match:
            title = clean_game_text(match.group(1))
            body = raw[match.end() :]
        body = clean_game_text(body)
        item["title"] = str(item.get("title") or title or "超级地球快讯").strip()
        item["message"] = body or clean_game_text(raw)
        # Official dispatches never carry Steam CDN images.
        item.pop("image_url", None)
        item["source"] = "api.helldivers2.dev/api/v1/dispatches"
        return item

    async def _translate_dispatch(self, dispatch: dict[str, Any]) -> str:
        item = self._normalize_dispatch(dispatch)
        dispatch.update(item)
        item_id = str(item.get("id", 0))
        raw_message = str(item.get("message") or "")
        original, replacements = await self._dispatch_planet_placeholders(raw_message)
        if not original:
            return ""
        if not self.enable_translation:
            return self._restore_dispatch_planets(original, replacements)

        cached = await self.translation_cache.get("dispatches", item_id)
        if (
            cached
            and cached.get("original_text") == original
            and cached.get("translated_text")
        ):
            return self._restore_dispatch_planets(
                cached["translated_text"], replacements
            )

        translated = await self.translator.translate_text(original)
        if translated and translated != original:
            await self.translation_cache.store(
                "dispatches",
                item_id,
                original,
                translated,
                metadata={
                    "published": item.get("published"),
                    "type": item.get("type"),
                    "source": item.get("source"),
                },
            )
            return self._restore_dispatch_planets(translated, replacements)

        # 失败也缓存原文，降低重复请求
        await self.translation_cache.store(
            "dispatches",
            item_id,
            original,
            original,
            metadata={
                "published": item.get("published"),
                "type": item.get("type"),
                "source": item.get("source"),
                "fallback": True,
            },
        )
        return self._restore_dispatch_planets(original, replacements)

    async def _dispatch_planet_placeholders(
        self, text: str
    ) -> tuple[str, dict[str, str]]:
        """Protect current planet names from being translated as ``未知星球``."""

        candidates = set(known_planet_names())
        planets = await self.cache.get(self.CACHE_PLANETS)
        if isinstance(planets, list):
            for planet in planets:
                if not isinstance(planet, dict):
                    continue
                name = planet.get("name") or planet.get("planetName")
                if isinstance(name, str) and name.strip():
                    candidates.add(name.strip())
        replacements: dict[str, str] = {}
        result = text
        for candidate in sorted(candidates, key=len, reverse=True):
            pattern = re.compile(
                rf"(?<![A-Za-z0-9]){re.escape(candidate)}(?![A-Za-z0-9])",
                re.IGNORECASE,
            )
            match = pattern.search(result)
            if match is None:
                continue
            placeholder = f"__HD2PLANET{len(replacements)}__"
            replacements[placeholder] = await self._localize_planet_name(match.group(0))
            result = pattern.sub(placeholder, result)
        return result, replacements

    @staticmethod
    def _restore_dispatch_planets(text: str, replacements: dict[str, str]) -> str:
        result = str(text)
        for placeholder, name in replacements.items():
            result = re.sub(re.escape(placeholder), lambda _: name, result, flags=re.I)
        return result

    async def get_news_message(self, index: int = 1) -> str:
        if index < 1 or index > 5:
            return "❌ 快讯序号需在 1-5 之间，例如: /news 1"
        dispatches = await self.cache.get_or_refresh(self.CACHE_DISPATCHES)
        if dispatches is None:
            return "❌ 暂时无法获取游戏快讯，数据源请求失败，请稍后重试。"
        if not isinstance(dispatches, list) or len(dispatches) == 0:
            return "📰 当前没有可显示的快讯。"
        if index > len(dispatches):
            return f"❌ 当前仅有 {len(dispatches)} 条快讯，请使用 1-{len(dispatches)}"

        dispatch = self._normalize_dispatch(dispatches[index - 1])
        text = await self._translate_dispatch(dispatch)
        title = str(dispatch.get("title") or "")
        if self.enable_translation and title:
            dispatch["title"] = await self._translate_cached_text(
                "dispatch_title", str(dispatch.get("id", 0)), title
            )
        return format_news_message(dispatch, index=index, message_text=text)

    async def get_news_image(self, index: int = 1) -> tuple[str, list[Path]]:
        if index < 1 or index > 5:
            return "❌ 快讯序号需在 1-5 之间，例如：/news 1", []
        dispatches = await self.cache.get_or_refresh(self.CACHE_DISPATCHES)
        if dispatches is None:
            return "❌ 暂时无法获取游戏快讯，数据源请求失败，请稍后重试。", []
        if not isinstance(dispatches, list) or len(dispatches) == 0:
            return "📰 当前没有可显示的快讯。", []
        if index > len(dispatches):
            return (
                f"❌ 当前仅有 {len(dispatches)} 条快讯，请使用 1-{len(dispatches)}",
                [],
            )
        dispatch = self._normalize_dispatch(dispatches[index - 1])
        text = await self._translate_dispatch(dispatch)
        title = str(dispatch.get("title") or "")
        if self.enable_translation and title:
            dispatch["title"] = await self._translate_cached_text(
                "dispatch_title", str(dispatch.get("id", 0)), title
            )
        if self.dispatch_renderer is not None:
            paths = await asyncio.to_thread(
                self.dispatch_renderer.render,
                dispatch,
                index=index,
                message_text=text,
                hero_path=None,
            )
            return "", paths
        card = build_news_card(dispatch, index=index, message_text=text)
        p = await self._render_card(card)
        return "", [p] if p else []

    # ---- steam ----

    async def ensure_steam_translated(self) -> None:
        updates = await self.cache.get(self.CACHE_STEAM)
        if not updates:
            return
        latest = updates[:1]
        ids = [str(u.get("id", i)) for i, u in enumerate(latest)]
        await self.translation_cache.clear_outdated("steam", ids)
        for update in latest:
            if isinstance(update, dict):
                await self._prepare_steam_content(update)
            await asyncio.sleep(0.1)

    async def _translate_steam(self, update: dict[str, Any]) -> dict[str, str]:
        item_id = str(update.get("id", ""))
        original_title = update.get("title", "") or ""
        original_content = update.get("content", "") or ""
        original_text = (
            f"{original_title}\n{original_content}"
            if original_title and original_content
            else (original_title or original_content)
        )
        result = {"title": original_title, "content": original_content}

        if not self.enable_translation or not item_id:
            return result

        cached = await self.translation_cache.get("steam", item_id)
        if (
            cached
            and cached.get("original_text") == original_text
            and cached.get("metadata")
        ):
            meta = cached["metadata"]
            result["title"] = meta.get("translated_title") or original_title
            result["content"] = meta.get("translated_content") or original_content
            return result

        translated_title = (
            await self.translator.translate_text(original_title)
            if original_title
            else ""
        )
        translated_content = (
            await self.translator.translate_text(original_content)
            if original_content
            else ""
        )
        final_title = (
            translated_title
            if translated_title and translated_title != original_title
            else original_title
        )
        final_content = (
            translated_content
            if translated_content and translated_content != original_content
            else original_content
        )

        await self.translation_cache.store(
            "steam",
            item_id,
            original_text,
            f"{final_title}\n{final_content}",
            metadata={
                "publishedAt": update.get("publishedAt"),
                "author": update.get("author"),
                "url": update.get("url"),
                "translated_title": final_title
                if final_title != original_title
                else "",
                "translated_content": final_content
                if final_content != original_content
                else "",
                "original_title": original_title,
                "original_content": original_content,
            },
        )
        result["title"] = final_title
        result["content"] = final_content
        return result

    async def _prepare_steam_content(
        self, update: dict[str, Any]
    ) -> tuple[str, ParsedSteamContent]:
        item_id = str(update.get("id") or "steam")
        title = str(update.get("title") or "Steam Update")
        content = str(update.get("content") or update.get("contents") or "")
        parsed = parse_steam_content(content)
        display_title = await self._translate_cached_text(
            "steam_card", f"{item_id}:title", title
        )

        source_blocks = list(parsed.blocks[:28])
        translated_blocks: list[SteamBlock] = []
        remaining = max(0, self.steam_max_content_length)
        for index, block in enumerate(source_blocks):
            if block.kind == "list":
                source_items = tuple(block.items[:12])
                translated_items: list[str] = []
                for item_index, item in enumerate(source_items):
                    if remaining <= 0:
                        translated_items.append(item)
                        continue
                    translated = await self._translate_cached_text(
                        "steam_card",
                        f"{item_id}:block:{index}:item:{item_index}",
                        item[:remaining],
                    )
                    translated_items.append(translated)
                    remaining -= len(item)
                translated_blocks.append(
                    SteamBlock(
                        "list",
                        level=block.level,
                        items=tuple(translated_items) or source_items,
                        ordered=block.ordered,
                    )
                )
                continue
            if remaining <= 0:
                translated_blocks.append(block)
                continue
            source_text = block.text[:remaining]
            translated_text = await self._translate_cached_text(
                "steam_card", f"{item_id}:block:{index}", source_text
            )
            suffix = block.text[len(source_text) :]
            translated_blocks.append(
                SteamBlock(
                    block.kind,
                    text=translated_text + suffix,
                    level=block.level,
                )
            )
            remaining = max(0, remaining - len(source_text))
        return display_title, ParsedSteamContent(
            blocks=tuple(translated_blocks),
            image_candidates=parsed.image_candidates,
        )

    async def _steam_hero_path(
        self,
        parsed: ParsedSteamContent,
        metadata: dict[str, Any] | None,
    ) -> Path | None:
        if not self.steam_image_enabled or self.remote_image_cache is None:
            return None
        candidates = list(parsed.image_candidates)
        if isinstance(metadata, dict):
            for key in ("header_image", "capsule_image", "background"):
                value = metadata.get(key)
                if isinstance(value, str) and value.startswith("https://"):
                    candidates.append(value)
        for url in candidates[:6]:
            path = await self.remote_image_cache.get(url)
            if path is not None:
                return path
        return None

    async def get_steam_images(self) -> list[Path]:
        updates = await self.cache.get_or_refresh(self.CACHE_STEAM)
        if not isinstance(updates, list) or not updates:
            return []
        update = updates[0] if isinstance(updates[0], dict) else {}
        title, translated = await self._prepare_steam_content(update)
        metadata = await self.cache.get(self.CACHE_STEAM_METADATA)
        if metadata is None:
            metadata = await self.client.fetch_steam_metadata()
            if metadata is not None:
                await self.cache.set(self.CACHE_STEAM_METADATA, metadata)
        hero = await self._steam_hero_path(
            translated, metadata if isinstance(metadata, dict) else None
        )
        if self.steam_renderer is None:
            return []
        return await asyncio.to_thread(
            self.steam_renderer.render,
            update,
            title=title,
            translated_blocks=translated,
            hero_image=hero,
        )

    async def get_steam_message(self) -> str:
        updates = await self.cache.get_or_refresh(self.CACHE_STEAM)
        if not updates:
            return "❌ 暂时无法获取 Steam 更新日志，数据可能正在同步，请稍后重试。"
        update = updates[0]
        fields = await self._translate_steam(update)
        return format_steam_message(
            update,
            title=fields["title"],
            content=fields["content"],
            max_content_length=self.steam_max_content_length,
            balancing_limit=self.steam_balancing_limit,
            fixes_limit=self.steam_fixes_limit,
            issues_limit=self.steam_issues_limit,
            max_sections=self.steam_max_sections,
        )

    # ---- wiki ----

    async def _translate_wiki_extract(self, title: str, extract: str) -> str:
        if not extract or not self.translate_wiki:
            return extract
        item_id = title
        cached = await self.translation_cache.get("wiki", item_id)
        if (
            cached
            and cached.get("original_text") == extract
            and cached.get("translated_text")
        ):
            return str(cached["translated_text"])

        translated = await self.translator.translate_text(extract)
        final = translated if translated and translated != extract else extract
        await self.translation_cache.store(
            "wiki",
            item_id,
            extract,
            final,
            metadata={"title": title, "fallback": final == extract},
        )
        return final

    async def get_wiki_message(self, query: str) -> str:
        if not self.enable_wiki:
            return "❌ Wiki 查询已在配置中关闭（enable_wiki=false）。"
        if self.wiki_client is None:
            return "❌ Wiki 客户端未初始化。"

        query = (query or "").strip()
        if not query:
            return WIKI_USAGE

        try:
            # 先尝试把查询当标题直接取摘要（精确/接近）
            direct = await self.wiki_client.get_page_summary(query)
            if direct and direct.get("extract"):
                extract = await self._translate_wiki_extract(
                    str(direct.get("title") or query),
                    str(direct.get("extract") or ""),
                )
                return format_wiki_summary(
                    title=str(direct.get("title") or query),
                    extract=extract,
                    url=str(direct.get("url") or self.wiki_client.page_url(query)),
                )

            results = await self.wiki_client.search(query)
            if not results:
                return format_wiki_search_results(
                    query,
                    [],
                    search_url=self.wiki_client.search_url(query),
                )

            best = self.wiki_client.pick_best_title(query, results)
            if best:
                page = await self.wiki_client.get_page_summary(best)
                if page:
                    extract = await self._translate_wiki_extract(
                        str(page.get("title") or best),
                        str(page.get("extract") or ""),
                    )
                    return format_wiki_summary(
                        title=str(page.get("title") or best),
                        extract=extract,
                        url=str(page.get("url") or self.wiki_client.page_url(best)),
                    )

            # 多候选：列表展示
            return format_wiki_search_results(
                query,
                results,
                search_url=self.wiki_client.search_url(query),
            )
        except Exception as e:
            logger.exception(f"[HD2] wiki query error: {e}")
            return "❌ Wiki 查询失败，请稍后重试。"

    # ---- GWW-style war queries ----

    async def _build_war_state(self) -> WarState:
        planets = await self.cache.get_or_refresh(self.CACHE_PLANETS)
        campaigns = await self.cache.get_or_refresh(self.CACHE_CAMPAIGNS)
        events = await self.cache.get_or_refresh(self.CACHE_PLANET_EVENTS)
        stations = await self.cache.get_or_refresh(self.CACHE_SPACE_STATIONS)
        war = await self.cache.get_or_refresh(self.CACHE_WAR_V1)
        war_status = await self.cache.get_or_refresh(self.CACHE_WAR_STATUS)
        global_events = (
            war_status.get("globalEvents")
            if isinstance(war_status, dict)
            and isinstance(war_status.get("globalEvents"), list)
            else await self.cache.get(self.CACHE_GLOBAL_EVENTS)
        )
        return WarState(
            planets=planets if isinstance(planets, list) else [],
            campaigns=campaigns if isinstance(campaigns, list) else [],
            planet_events=events if isinstance(events, list) else [],
            space_stations=stations if isinstance(stations, list) else [],
            war=war if isinstance(war, dict) else {},
            global_events=global_events if isinstance(global_events, list) else [],
        )

    @staticmethod
    def _station_with_planet(state: WarState) -> dict[str, Any] | None:
        """Attach the canonical planet payload when the DSS API exposes only its index."""

        station = state.dss_station()
        if station is None:
            return None
        view = copy.deepcopy(station)
        planet = view.get("planet") if isinstance(view.get("planet"), dict) else {}
        if planet.get("name") or view.get("planetName"):
            return view
        index = planet.get("index") or planet.get("planetIndex") or view.get("planetIndex")
        for candidate in state.planets:
            candidate_index = candidate.get("index") or candidate.get("planetIndex")
            if str(candidate_index) == str(index):
                view["planet"] = copy.deepcopy(candidate)
                return view
        return view

    async def _translate_cached_text(
        self,
        namespace: str,
        item_id: str,
        text: str,
    ) -> str:
        if not self.enable_translation or len(text.strip()) < 3:
            return text
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
        cache_id = f"{item_id}:{digest}"
        cached = await self.translation_cache.get(namespace, cache_id)
        if cached and cached.get("original_text") == text:
            return str(cached.get("translated_text") or text)
        translated = await self.translator.translate_text(text)
        final = translated if translated and translated != text else text
        await self.translation_cache.store(namespace, cache_id, text, final)
        return final

    async def _localize_planet_name(
        self, value: Any, *, include_english: bool = True
    ) -> str:
        """Prefer an official name; otherwise retain English beside API translation."""

        original = " ".join(str(value or "").split())
        if not original:
            return "未知星球"
        official = lookup_planet_name(original)
        if official:
            return official
        if not self.enable_translation or re.search(r"[\u3400-\u9fff]", original):
            return original
        translated = await self._translate_cached_text(
            "planet_name", original.casefold(), original
        )
        translated = " ".join(str(translated or "").split())
        if translated and translated != original:
            return f"{original}（{translated}）" if include_english else translated
        return original

    async def _localize_planet_rows(
        self, rows: list[dict[str, Any]], *, include_english: bool = True
    ) -> None:
        """Localize the small set of names that a report can actually display."""

        localized: dict[str, str] = {}
        for row in rows:
            planet = row.get("planet") if isinstance(row.get("planet"), dict) else None
            containers = [row] + ([planet] if planet is not None else [])
            for container in containers:
                for key in ("name", "planet_name", "planetName"):
                    value = container.get(key)
                    if not isinstance(value, str) or not value.strip():
                        continue
                    token = value.casefold()
                    if token not in localized:
                        localized[token] = await self._localize_planet_name(
                            value, include_english=include_english
                        )
                    container[key] = localized[token]

    async def _prepare_dss_station(self, station: dict[str, Any] | None):
        if not station:
            return None
        view = copy.deepcopy(station)
        await self._localize_planet_rows([view])
        actions = view.get("tacticalActions") or view.get("tactical_actions") or []
        if not isinstance(actions, list):
            return view
        try:
            from .i18n import format_dss_action
        except ImportError:  # pragma: no cover - direct module execution
            from i18n import format_dss_action  # type: ignore

        for i, action in enumerate(actions[:6]):
            if not isinstance(action, dict):
                continue
            item_id = str(action.get("id32") or action.get("mediaId32") or i)
            for field, display_field in (
                ("name", "display_name"),
                ("description", "display_description"),
                ("strategicDescription", "display_strategic_description"),
            ):
                text = action.get(field)
                if isinstance(text, str):
                    action[display_field] = await self._translate_cached_text(
                        "dss_action", f"{item_id}:{field}", text
                    )
            if isinstance(action.get("name"), str):
                action["display_name"] = format_dss_action(
                    action["name"], action.get("display_name")
                )
                icon_by_name = {
                    "飞鹰风暴": "tactical/eagle_storm.png",
                    "轨道封锁": "tactical/orbital_blockade.png",
                    "重型军械分发": "tactical/heavy_ordnance.png",
                }
                icon_asset = icon_by_name.get(str(action["display_name"]))
                if icon_asset:
                    action["icon_asset"] = icon_asset
        return view

    async def get_dss_message(self) -> str:
        state = await self._build_war_state()
        station = await self._prepare_dss_station(self._station_with_planet(state))
        return format_dss_message(station)

    async def get_dss_image(self) -> list[Path]:
        state = await self._build_war_state()
        station = await self._prepare_dss_station(self._station_with_planet(state))
        if self.dss_renderer is not None:
            p = await asyncio.to_thread(self.dss_renderer.render, station)
            return [p] if p else []
        card = build_dss_card(station)
        p = await self._render_card(card)
        return [p] if p else []

    def _attach_trends_to_sections(self, sections: dict[str, Any]) -> None:
        if self.campaign_trends is None:
            return
        containers: list[list[dict[str, Any]]] = [
            sections.get("urgent") or [],
            sections.get("defending") or [],
        ]
        for block in (sections.get("attacking") or {}).values():
            if isinstance(block, dict):
                containers.extend([block.get("main") or [], block.get("low") or []])
        rows = [row for container in containers for row in container]
        enriched = self.campaign_trends.attach(rows)
        by_identity = {str(row.get("identity")): row for row in enriched}
        for container in containers:
            for index, row in enumerate(container):
                replacement = by_identity.get(str(row.get("identity")))
                if replacement is not None:
                    container[index] = replacement

    async def get_dashboard_image(self) -> list[Path]:
        state = await self._build_war_state()
        if not state.campaigns and not state.planets:
            return []
        sections = state.dashboard_sections(
            low_impact_threshold=self.dashboard_low_impact_threshold
        )
        report_rows: list[dict[str, Any]] = [
            row
            for key in ("urgent", "defending")
            for row in sections.get(key) or []
            if isinstance(row, dict)
        ]
        for block in (sections.get("attacking") or {}).values():
            if not isinstance(block, dict):
                continue
            for key in ("main", "low"):
                report_rows.extend(
                    row for row in block.get(key) or [] if isinstance(row, dict)
                )
        await self._localize_planet_rows(report_rows)
        self._attach_trends_to_sections(sections)
        sections["dss"] = await self._prepare_dss_station(self._station_with_planet(state))
        dss_planet = sections["dss"].get("planet") if isinstance(sections.get("dss"), dict) else None
        sections["dss_planet"] = dss_planet if isinstance(dss_planet, dict) else {}
        if self.dashboard_renderer is not None:
            p = await asyncio.to_thread(
                self.dashboard_renderer.render,
                sections,
                subtitle=self._subtitle(),
            )
            return [p] if p else []
        card = build_dashboard_card(
            sections,
            subtitle=self._subtitle(),
            low_impact_threshold=self.dashboard_low_impact_threshold,
        )
        p = await self._render_card(card)
        return [p] if p else []

    async def get_warfront_message(self, faction: str) -> str:
        faction = (faction or "").strip()
        if not faction:
            return (
                "❌ 用法: /warfront <阵营>\n"
                "可选: Terminids/Automaton/Illuminate（终结族/机器人/光能族）"
            )
        norm = normalize_faction(faction)
        if norm not in {"Terminids", "Automaton", "Illuminate"}:
            return (
                "❌ 未知阵营。可选: Terminids / Automaton / Illuminate\n"
                "中文: 终结族 / 机器人 / 光能族"
            )
        state = await self._build_war_state()
        if not state.campaigns and not state.planets:
            return "❌ 暂时无法获取战线数据，请稍后重试。"
        campaigns = state.campaigns_for_faction(norm)
        return format_warfront_message(norm, campaigns)

    async def get_warfront_image(self, faction: str) -> tuple[str, list[Path]]:
        faction = (faction or "").strip()
        if not faction:
            return (
                "❌ 用法: /warfront <阵营>\n"
                "可选: Terminids/Automaton/Illuminate（终结族/机器人/光能族）",
                [],
            )
        norm = normalize_faction(faction)
        if norm not in {"Terminids", "Automaton", "Illuminate"}:
            return (
                "❌ 未知阵营。可选: Terminids / Automaton / Illuminate\n中文: 终结族 / 机器人 / 光能族",
                [],
            )
        state = await self._build_war_state()
        if not state.campaigns and not state.planets:
            return "❌ 暂时无法获取战线数据，请稍后重试。", []
        rows = state.warfront_rows(norm)
        if self.campaign_trends is not None:
            rows = self.campaign_trends.attach(rows)
        await self._localize_planet_rows(rows)
        if self.warfront_renderer is not None:
            defense_count = sum(1 for row in rows if row.get("is_defense"))
            faction_label = {
                "Terminids": "终结族",
                "Automaton": "机器人",
                "Illuminate": "光能族",
                "Humans": "超级地球",
            }.get(norm, norm)
            p = await asyncio.to_thread(
                self.warfront_renderer.render,
                rows,
                faction=norm,
                title=f"{faction_label}战线",
                subtitle=f"玩家数与解放进度各 Top 10 · {self._subtitle()}",
                defense_summary=(
                    f"当前有 {defense_count} 条防御战线；结果按最近采样净进度估算"
                    if defense_count
                    else None
                ),
            )
            return "", [p] if p else []
        campaigns = state.campaigns_for_faction(norm)
        card = build_warfront_card(norm, campaigns)
        p = await self._render_card(card)
        return "", [p] if p else []

    async def get_planet_message(self, query: str) -> str:
        query = (query or "").strip()
        if not query:
            return "❌ 用法: /planet <星球名称或编号>\n例如: /planet Heeth  或  /planet 112"
        state = await self._build_war_state()
        if not state.planets:
            return "❌ 暂时无法获取星球数据，请稍后重试。"
        matches = state.find_planets(query, limit=8)
        if not matches:
            return format_planet_candidates(query, [])
        if len(matches) == 1:
            return format_planet_message(matches[0])
        # 精确名唯一
        ql = query.lower()
        exact = [
            p
            for p in matches
            if str(p.get("name") or "").lower() == ql
            or str(planet_index_safe(p)) == query
        ]
        if len(exact) == 1:
            return format_planet_message(exact[0])
        return format_planet_candidates(query, matches)

    async def get_planet_image(self, query: str) -> tuple[str, list[Path]]:
        query = (query or "").strip()
        if not query:
            return "❌ 用法: /planet <星球名称或编号>", []
        state = await self._build_war_state()
        if not state.planets:
            return "❌ 暂时无法获取星球数据，请稍后重试。", []
        matches = state.find_planets(query, limit=8)
        if not matches:
            card = build_planet_candidates_card(query, [])
            p = await self._render_card(card)
            return "", [p] if p else []
        if len(matches) == 1:
            card = build_planet_card(matches[0])
            p = await self._render_card(card)
            return "", [p] if p else []
        ql = query.lower()
        exact = [
            p
            for p in matches
            if str(p.get("name") or "").lower() == ql
            or str(planet_index_safe(p)) == query
        ]
        if len(exact) == 1:
            card = build_planet_card(exact[0])
            p = await self._render_card(card)
            return "", [p] if p else []
        card = build_planet_candidates_card(query, matches)
        p = await self._render_card(card)
        return "", [p] if p else []

    async def _prepare_global_events(
        self, events: list[dict[str, Any]], limit: int
    ) -> list[dict[str, Any]]:
        prepared: list[dict[str, Any]] = []
        for i, source in enumerate(events[:limit]):
            if not isinstance(source, dict):
                continue
            event = copy.deepcopy(source)
            item_id = str(event.get("eventId") or event.get("id32") or i)
            for field, display_field in (
                ("title", "display_title"),
                ("message", "display_message"),
            ):
                text = event.get(field)
                if isinstance(text, str):
                    cleaned = clean_game_text(text)
                    event[display_field] = await self._translate_cached_text(
                        "global_event", f"{item_id}:{field}", cleaned
                    )
            prepared.append(event)
        return prepared

    async def get_global_events_message(self) -> str:
        state = await self._build_war_state()
        events = await self._prepare_global_events(state.global_events(), 5)
        for event in events:
            event["title"] = event.get("display_title") or event.get("title")
            event["message"] = event.get("display_message") or event.get("message")
        return format_global_events_message(events)

    async def get_global_events_image(self) -> list[Path]:
        state = await self._build_war_state()
        events = await self._prepare_global_events(state.global_events(), 4)
        war_status = await self.cache.get_or_refresh(self.CACHE_WAR_STATUS)
        war_time = war_status.get("time") if isinstance(war_status, dict) else None
        if self.global_event_renderer is not None:
            paths: list[Path] = []
            for event in events:
                translated = {
                    "display_title": event.get("display_title"),
                    "display_message": event.get("display_message"),
                }
                p = await asyncio.to_thread(
                    self.global_event_renderer.render,
                    event,
                    war_time=war_time,
                    translated=translated,
                )
                if p:
                    paths.append(p)
            return paths
        legacy = []
        for event in events:
            item = dict(event)
            item["title"] = item.get("display_title") or item.get("title")
            item["message"] = item.get("display_message") or item.get("message")
            legacy.append(item)
        card = build_global_events_card(legacy)
        p = await self._render_card(card)
        return [p] if p else []

    async def get_personal_order_message(self) -> str:
        try:
            data = await self.client.fetch_personal_order(
                self.personal_order_api_url,
                allow_private=self.allow_private_personal_order_url,
            )
            if data and self.enable_translation and isinstance(data, (dict, list)):
                # 轻量翻译标题字段
                item = data[0] if isinstance(data, list) and data else data
                if isinstance(item, dict):
                    setting = (
                        item.get("setting")
                        if isinstance(item.get("setting"), dict)
                        else {}
                    )
                    for container in (setting, item):
                        if not isinstance(container, dict):
                            continue
                        for field in (
                            "overrideTitle",
                            "overrideBrief",
                            "taskDescription",
                            "title",
                            "brief",
                            "description",
                            "message",
                        ):
                            text = container.get(field)
                            if isinstance(text, str) and len(text.strip()) >= 3:
                                container[field] = await self.translator.translate_text(
                                    text
                                )
            return format_personal_order_message(data)
        except Exception as e:
            logger.exception(f"[HD2] personal order error: {e}")
            return format_personal_order_message(None)

    async def get_personal_order_image(self) -> list[Path]:
        try:
            data = await self.client.fetch_personal_order(
                self.personal_order_api_url,
                allow_private=self.allow_private_personal_order_url,
            )
            if data and self.enable_translation and isinstance(data, (dict, list)):
                item = data[0] if isinstance(data, list) and data else data
                if isinstance(item, dict):
                    setting = (
                        item.get("setting")
                        if isinstance(item.get("setting"), dict)
                        else {}
                    )
                    for container in (setting, item):
                        if not isinstance(container, dict):
                            continue
                        for field in (
                            "overrideTitle",
                            "overrideBrief",
                            "taskDescription",
                            "title",
                            "brief",
                            "description",
                            "message",
                        ):
                            text = container.get(field)
                            if isinstance(text, str) and len(text.strip()) >= 3:
                                container[field] = await self.translator.translate_text(
                                    text
                                )
            card = build_personal_order_card(data)
            p = await self._render_card(card)
            return [p] if p else []
        except Exception as e:
            logger.exception(f"[HD2] personal order error: {e}")
            card = build_personal_order_card(None)
            p = await self._render_card(card)
            return [p] if p else []

    async def get_map_result(self) -> tuple[str, Path | None]:
        """返回 (说明文字, 图片路径或 None)。"""
        if not self.enable_map:
            return "❌ 地图功能已在配置中关闭（enable_map=false）。", None
        state = await self._build_war_state()
        if not state.planets:
            return "❌ 暂时无法获取星球数据，无法生成地图。", None
        points = state.map_points()
        displayed_points = sorted(
            [
                point
                for point in points
                if point.get("active")
                or point.get("dss")
                or point.get("defense")
                or point.get("event")
            ],
            key=lambda point: (
                bool(point.get("dss")),
                bool(point.get("defense")),
                bool(point.get("event")),
                int(point.get("players") or 0),
            ),
            reverse=True,
        )[:15]
        await self._localize_planet_rows(displayed_points, include_english=False)
        caption = format_map_caption(
            active_campaigns=len(state.campaigns),
            planets=len(state.planets),
        )
        if self.map_renderer is None or not self.map_renderer.available:
            # 文本兜底：活跃战役 Top 列表
            lines = [caption, "（Pillow 未安装，以下为文本战线摘要）"]
            for c in state.campaigns[:15]:
                p = c.get("planet") if isinstance(c.get("planet"), dict) else {}
                name = p.get("name") or "?"
                players = (p.get("statistics") or {}).get("playerCount", 0)
                lines.append(f"▎{name}  在线:{players}")
            return "\n".join(lines), None
        from datetime import datetime

        subtitle = datetime.now().strftime("更新 %Y-%m-%d %H:%M")
        path = await asyncio.to_thread(
            self.map_renderer.render, points, subtitle=subtitle
        )
        if path is None:
            return caption + "\n❌ 地图绘制失败，请稍后重试。", None
        return caption, path


def planet_index_safe(planet: dict[str, Any]) -> int | None:
    from .war_state import planet_index

    return planet_index(planet)
