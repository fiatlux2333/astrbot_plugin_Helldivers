"""astrbot_plugin_Helldivers — Helldivers 2 银河战争查询插件。

指令:
  /stats /hd2stats /dashboard /order /news /steam /wiki
  /major_order /personal_order /map /dss
  /global_events /dispatches /warfront /planet
  /hd2 | /help
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator, Callable
from functools import wraps
from pathlib import Path
from typing import Any, Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig

from .api_client import HD2Client
from .visual_assets import configure_asset_manifest
from .awaiting_orders_renderer import AwaitingOrdersRenderer
from .cache import CacheService, get_plugin_data_dir
from .campaign_trends import CampaignTrendStore
from .card_renderer import CardRenderer
from .dashboard_renderer import DashboardRenderer
from .dss_renderer import DSSRenderer
from .dispatch_renderer import DispatchRenderer
from .global_event_renderer import GlobalEventRenderer
from .map_renderer import MapRenderer
from .major_order_renderer import MajorOrderRenderer
from .remote_image_cache import RemoteImageCache
from .services import HelldiversService
from .stats_renderer import StatsRenderer
from .steam_renderer import SteamRenderer
from .translator import TranslationCache, TranslationService
from .warfront_renderer import WarfrontRenderer
from .wiki_client import WikiCache, WikiClient

PLUGIN_NAME = "astrbot_plugin_Helldivers"
PLUGIN_AUTHOR = "fiatlux2333"
PLUGIN_DESC = (
    "Helldivers 2 银河战争图片情报：Dashboard、统计、DSS、星图、事件、Steam 与战线排行"
)
PLUGIN_VERSION = "v1.6.0"

HELP_TEXT = """\
Helldivers 2 银河战争 {version}
━━━━━━━━━━━━━━━━━━━━
【战况 · 图片卡片】
/dashboard          银河战争总览（GWW 风格）
/stats /hd2stats    银河战争详细统计
/major_order        主要任务（同 /order）
/personal_order     个人任务
/map                战争地图（阵营领土）
/dss                民主空间站详情
/global_events      全球事件
/dispatches [1-5]   战报（同 /news）
/warfront <阵营>    战线战况
/planet <名称/编号> 星球详情
/steam              Steam 新闻图片
【文本】
/wiki <关键词>      Helldivers Wiki
/hd2 或 /help       本帮助
━━━━━━━━━━━━━━━━━━━━
阵营: Terminids/Automaton/Illuminate
     （终结族/机器人/光能族）
数据: api.helldivers2.dev · wiki.gg
为了超级地球！🌍""".format(version=PLUGIN_VERSION)


def _strip_cmd(text: str, names: set[str]) -> list[str]:
    parts = (text or "").strip().split()
    args: list[str] = []
    for p in parts:
        token = p.lstrip("/").lower()
        if token in names:
            continue
        args.append(p)
    return args


def _command_handler(
    func: Callable[..., AsyncGenerator[Any, None]],
) -> Callable[..., AsyncGenerator[Any, None]]:
    """兼容 AstrBot 4.26.x 热重载残留导致的重复实例绑定。

    正常调用是 ``handler(plugin, event)``；旧 handler 未清理时可能变成
    ``handler(old_plugin, new_plugin, event)``。包装器只保留最后一个插件实例
    与消息事件，不改变 AstrBot 的指令参数解析。
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> AsyncGenerator[Any, None]:
        plugin = next(
            (arg for arg in reversed(args) if isinstance(arg, Star)),
            None,
        )
        event = next(
            (arg for arg in reversed(args) if isinstance(arg, AstrMessageEvent)),
            None,
        )
        if plugin is None or event is None:
            raise TypeError("无法从 AstrBot handler 参数中识别插件实例和消息事件")
        result = func(plugin, event)
        if inspect.isasyncgen(result):
            async for item in result:
                yield item
        else:
            awaited = await result
            if awaited is not None:
                yield awaited

    return wrapper


class HelldiversPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        self.service: Optional[HelldiversService] = None

    def _cfg(self, key: str, default: Any = None) -> Any:
        if self.config is None:
            return default
        try:
            return self.config.get(key, default)
        except Exception:
            return default

    async def _yield_images(
        self,
        event: AstrMessageEvent,
        paths: list[Path],
        *,
        fallback: str = "❌ 生成图片失败，请稍后重试。",
    ) -> AsyncGenerator[Any, None]:
        if not paths:
            yield event.plain_result(fallback)
            return
        try:
            components: list[Any] = [Image.fromFileSystem(str(p)) for p in paths]
            yield event.chain_result(components)
        except Exception as e:
            logger.warning(f"[HD2] send images failed: {e}")
            yield event.plain_result(fallback)

    async def initialize(self) -> None:
        data_dir = get_plugin_data_dir(PLUGIN_NAME)

        client = HD2Client(
            base_url=str(self._cfg("api_base", "https://api.helldivers2.dev")),
            war_id=int(self._cfg("war_id", 801) or 801),
            client_name=str(self._cfg("api_client_name", "astrbot_plugin_Helldivers")),
            contact=str(self._cfg("api_contact", "") or ""),
            user_agent=str(
                self._cfg("api_user_agent", "astrbot_plugin_Helldivers/1.0")
            ),
            timeout=int(self._cfg("api_timeout", 30) or 30),
            proxy_url=str(self._cfg("proxy_url", "") or ""),
            retry_base_delay=float(self._cfg("retry_base_delay", 5.0) or 5.0),
            retry_max_delay=float(self._cfg("retry_max_delay", 45.0) or 45.0),
            retry_max_attempts=int(self._cfg("retry_max_attempts", 3) or 3),
            min_request_interval=float(self._cfg("min_request_interval", 1.5) or 1.5),
            steam_appid=int(self._cfg("steam_appid", 553850) or 553850),
            steam_news_count=int(self._cfg("steam_news_count", 10) or 10),
        )

        cache = CacheService(
            data_dir,
            update_interval=int(self._cfg("cache_update_interval", 180) or 180),
            request_delay=float(self._cfg("request_delay", 4) or 4),
            enable_background=bool(self._cfg("enable_background_refresh", True)),
        )

        ui_language = str(self._cfg("ui_language", "zh-CN") or "zh-CN")
        if ui_language != "zh-CN":
            logger.warning("[HD2] unsupported ui_language=%s; using zh-CN", ui_language)
            ui_language = "zh-CN"

        enable_translation = bool(self._cfg("enable_translation", True))
        translator = TranslationService(
            api_url=str(
                self._cfg(
                    "translation_api_url",
                    "https://uapis.cn/api/v1/ai/translate",
                )
            ),
            timeout=int(self._cfg("translation_timeout", 30) or 30),
            target_lang=str(self._cfg("translation_target_lang", "zh") or "zh"),
            user_agent=str(
                self._cfg("api_user_agent", "astrbot_plugin_Helldivers/1.0")
            ),
            proxy_url=str(self._cfg("proxy_url", "") or ""),
            enabled=enable_translation,
            mode=str(self._cfg("translation_mode", "auto") or "auto"),
            api_key=str(self._cfg("translation_api_key", "") or ""),
            model=str(self._cfg("translation_model", "gpt-4o-mini") or "gpt-4o-mini"),
            fallback_ttl=int(
                self._cfg("translation_retry_fallback_seconds", 900) or 900
            ),
        )
        logger.info("[HD2] translation provider: %s", translator.diagnostic())

        try:
            translator.bind_session(await client.get_session())
        except Exception as e:
            logger.warning(f"[HD2] bind translation session failed: {e}")

        translation_cache = TranslationCache(
            data_dir,
            provider_fingerprint=translator.provider_fingerprint(),
            fallback_ttl=int(
                self._cfg("translation_retry_fallback_seconds", 900) or 900
            ),
        )

        enable_wiki = bool(self._cfg("enable_wiki", True))
        wiki_client: WikiClient | None = None
        if enable_wiki:
            wiki_cache = WikiCache(
                data_dir,
                page_ttl=int(self._cfg("wiki_cache_ttl", 21600) or 21600),
                search_ttl=int(self._cfg("wiki_search_cache_ttl", 1800) or 1800),
            )
            wiki_client = WikiClient(
                base_url=str(self._cfg("wiki_base", "https://helldivers.wiki.gg")),
                api_path=str(self._cfg("wiki_api_path", "/api.php") or "/api.php"),
                user_agent=str(
                    self._cfg("api_user_agent", "astrbot_plugin_Helldivers/1.0")
                ),
                timeout=int(self._cfg("api_timeout", 30) or 30),
                proxy_url=str(self._cfg("proxy_url", "") or ""),
                search_limit=int(self._cfg("wiki_search_limit", 5) or 5),
                extract_chars=int(self._cfg("wiki_extract_chars", 900) or 900),
                prefer_hd2=bool(self._cfg("wiki_prefer_hd2", True)),
                retry_max_attempts=int(self._cfg("retry_max_attempts", 3) or 3),
                retry_base_delay=float(self._cfg("retry_base_delay", 2.0) or 2.0),
                cache=wiki_cache,
            )
            try:
                wiki_client.bind_session(await client.get_session())
            except Exception as e:
                logger.warning(f"[HD2] bind wiki session failed: {e}")

        manifest_path = str(self._cfg("asset_manifest_path", "") or "").strip()
        configure_asset_manifest(manifest_path or None)

        map_renderer = MapRenderer(
            data_dir / "maps",
            cache_ttl=int(self._cfg("map_cache_ttl", 600) or 600),
            label_top_n=int(self._cfg("map_label_top_n", 15) or 15),
            visual_mode=str(
                self._cfg("map_visual_mode", "uploaded_reference")
                or "uploaded_reference"
            ),
        )
        card_renderer = CardRenderer(data_dir / "cards")
        dashboard_renderer = DashboardRenderer(data_dir / "dashboard")
        stats_renderer = StatsRenderer(data_dir / "stats")
        dss_renderer = DSSRenderer(data_dir / "dss")
        major_order_renderer = MajorOrderRenderer(data_dir / "orders")
        awaiting_orders_renderer = AwaitingOrdersRenderer(data_dir / "cards")
        dispatch_renderer = DispatchRenderer(data_dir / "dispatches")
        warfront_renderer = WarfrontRenderer(data_dir / "warfront")
        global_event_renderer = GlobalEventRenderer(data_dir / "global_events")
        steam_renderer = SteamRenderer(data_dir / "steam")
        remote_image_cache = RemoteImageCache(
            data_dir / "remote_images",
            max_bytes=int(self._cfg("remote_image_max_bytes", 8388608) or 8388608),
            max_pixels=int(self._cfg("remote_image_max_pixels", 16000000) or 16000000),
            max_cache_bytes=int(self._cfg("image_cache_max_mb", 150) or 150)
            * 1024
            * 1024,
            user_agent=str(
                self._cfg("api_user_agent", "astrbot_plugin_Helldivers/1.5")
            ),
            proxy_url=str(self._cfg("proxy_url", "") or ""),
        )
        try:
            remote_image_cache.bind_session(await client.get_session())
        except Exception as e:
            logger.warning(f"[HD2] bind remote image cache session failed: {e}")
        campaign_trends = CampaignTrendStore(
            data_dir / "campaign_history.json",
            window_minutes=float(self._cfg("campaign_rate_window_minutes", 20) or 20),
            prune_hours=float(self._cfg("campaign_history_hours", 2) or 2),
        )

        self.service = HelldiversService(
            client,
            cache,
            translator,
            translation_cache,
            steam_max_content_length=int(
                self._cfg("steam_max_content_length", 2000) or 2000
            ),
            steam_balancing_limit=int(self._cfg("steam_balancing_limit", 800) or 800),
            steam_fixes_limit=int(self._cfg("steam_fixes_limit", 600) or 600),
            steam_issues_limit=int(self._cfg("steam_issues_limit", 300) or 300),
            steam_max_sections=int(self._cfg("steam_max_sections", 3) or 3),
            steam_image_enabled=bool(self._cfg("steam_image_enabled", True)),
            rotation_dispatches=int(self._cfg("rotation_dispatches", 300) or 300),
            rotation_orders=int(self._cfg("rotation_orders", 600) or 600),
            rotation_steam=int(self._cfg("rotation_steam", 900) or 900),
            enable_translation=enable_translation,
            ui_language=ui_language,
            wiki_client=wiki_client,
            enable_wiki=enable_wiki,
            translate_wiki=bool(self._cfg("translate_wiki", True)),
            map_renderer=map_renderer,
            enable_map=bool(self._cfg("enable_map", True)),
            personal_order_api_url=str(self._cfg("personal_order_api_url", "") or ""),
            card_renderer=card_renderer,
            dashboard_renderer=dashboard_renderer,
            stats_renderer=stats_renderer,
            dss_renderer=dss_renderer,
            major_order_renderer=major_order_renderer,
            awaiting_orders_renderer=awaiting_orders_renderer,
            dispatch_renderer=dispatch_renderer,
            warfront_renderer=warfront_renderer,
            global_event_renderer=global_event_renderer,
            steam_renderer=steam_renderer,
            remote_image_cache=remote_image_cache,
            campaign_trends=campaign_trends,
            dashboard_low_impact_threshold=int(
                self._cfg("dashboard_low_impact_threshold", 800) or 800
            ),
        )

        await self.service.start()

        contact = str(self._cfg("api_contact", "") or "").strip()
        if not contact:
            logger.warning(
                "[HD2] 建议在插件配置中填写 api_contact（联系邮箱），以遵守 Helldivers API 礼仪"
            )
        logger.info(f"[HD2] plugin initialized {PLUGIN_VERSION}, data_dir={data_dir}")

    async def terminate(self) -> None:
        if self.service is not None:
            try:
                await self.service.stop()
            except Exception as e:
                logger.warning(f"[HD2] service stop error: {e}")
            self.service = None
        logger.info("[HD2] plugin terminated")

    def _svc(self) -> HelldiversService:
        if self.service is None:
            raise RuntimeError("插件尚未初始化完成")
        return self.service

    # ---- help ----

    @filter.command("hd2", alias={"helldivers", "help"})
    @_command_handler
    async def cmd_help(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """Helldivers 2 插件帮助"""
        yield event.plain_result(HELP_TEXT)

    # ---- war cards (images) ----

    @filter.command("stats", alias={"hd2stats"})
    @_command_handler
    async def cmd_stats(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """查看当前银河战争实时统计（图片）"""
        try:
            paths = await self._svc().get_stats_images()
        except Exception as e:
            logger.exception(f"[HD2] /stats error: {e}")
            yield event.plain_result("❌ 获取银河战争统计失败，请稍后重试。")
            return
        async for r in self._yield_images(
            event, paths, fallback="❌ 获取银河战争统计失败，请稍后重试。"
        ):
            yield r

    @filter.command("order", alias={"major_order", "最高命令"})
    @_command_handler
    async def cmd_order(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """获取当前活跃的最高命令 / 主要任务（图片）"""
        try:
            paths = await self._svc().get_order_images()
        except Exception as e:
            logger.exception(f"[HD2] /order error: {e}")
            yield event.plain_result("❌ 获取最高命令失败，请稍后重试。")
            return
        async for r in self._yield_images(
            event, paths, fallback="❌ 获取最高命令失败，请稍后重试。"
        ):
            yield r

    @filter.command("news", alias={"dispatches", "战报", "快讯"})
    @_command_handler
    async def cmd_news(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """查看最新游戏快讯/战报（图片），用法: /news [1-5]"""
        index = 1
        try:
            args = _strip_cmd(
                event.message_str or "",
                {"news", "dispatches", "战报", "快讯"},
            )
            if args:
                index = int(args[0])
        except (ValueError, TypeError):
            yield event.plain_result("❌ 用法: /news [1-5]  或  /dispatches [1-5]")
            return

        try:
            err, paths = await self._svc().get_news_image(index)
        except Exception as e:
            logger.exception(f"[HD2] /news error: {e}")
            yield event.plain_result("❌ 获取游戏快讯失败，请稍后重试。")
            return
        if err:
            yield event.plain_result(err)
            return
        async for r in self._yield_images(
            event, paths, fallback="❌ 获取游戏快讯失败，请稍后重试。"
        ):
            yield r

    @filter.command("steam")
    @_command_handler
    async def cmd_steam(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """获取最新 Steam 新闻图片"""
        try:
            paths = await self._svc().get_steam_images()
        except Exception as e:
            logger.exception(f"[HD2] /steam image error: {e}")
            paths = []
        if paths:
            async for result in self._yield_images(
                event, paths, fallback="❌ Steam 新闻图片生成失败，请稍后重试。"
            ):
                yield result
            return
        # Pillow/远程图片不可用时回退现有文本输出。
        try:
            msg = await self._svc().get_steam_message()
        except Exception as e:
            logger.exception(f"[HD2] /steam fallback error: {e}")
            msg = "❌ 获取 Steam 更新日志失败，请稍后重试。"
        yield event.plain_result(msg)

    @filter.command("wiki", alias={"维基", "百科"})
    @_command_handler
    async def cmd_wiki(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """查询 Helldivers Wiki，用法: /wiki <关键词>"""
        args = _strip_cmd(event.message_str or "", {"wiki", "维基", "百科"})
        query = " ".join(args).strip()
        try:
            msg = await self._svc().get_wiki_message(query)
        except Exception as e:
            logger.exception(f"[HD2] /wiki error: {e}")
            msg = "❌ Wiki 查询失败，请稍后重试。"
        yield event.plain_result(msg)

    @filter.command("personal_order", alias={"个人任务", "po"})
    @_command_handler
    async def cmd_personal_order(
        self, event: AstrMessageEvent
    ) -> AsyncGenerator[Any, None]:
        """查看个人任务 Personal Order（图片）"""
        try:
            paths = await self._svc().get_personal_order_image()
        except Exception as e:
            logger.exception(f"[HD2] /personal_order error: {e}")
            yield event.plain_result("❌ 获取个人任务失败，请稍后重试。")
            return
        async for r in self._yield_images(
            event, paths, fallback="❌ 获取个人任务失败，请稍后重试。"
        ):
            yield r

    @filter.command("dss", alias={"空间站", "民主空间站"})
    @_command_handler
    async def cmd_dss(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """查看民主空间站 DSS 信息（图片）"""
        try:
            paths = await self._svc().get_dss_image()
        except Exception as e:
            logger.exception(f"[HD2] /dss error: {e}")
            yield event.plain_result("❌ 获取 DSS 信息失败，请稍后重试。")
            return
        async for r in self._yield_images(
            event, paths, fallback="❌ 获取 DSS 信息失败，请稍后重试。"
        ):
            yield r

    @filter.command("dashboard", alias={"总览", "战况总览"})
    @_command_handler
    async def cmd_dashboard(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """银河战争总览 Dashboard（图片）"""
        try:
            paths = await self._svc().get_dashboard_image()
        except Exception as e:
            logger.exception(f"[HD2] /dashboard error: {e}")
            yield event.plain_result("❌ 获取战争总览失败，请稍后重试。")
            return
        async for r in self._yield_images(
            event, paths, fallback="❌ 获取战争总览失败，请稍后重试。"
        ):
            yield r

    @filter.command("global_events", alias={"全球事件", "events"})
    @_command_handler
    async def cmd_global_events(
        self, event: AstrMessageEvent
    ) -> AsyncGenerator[Any, None]:
        """查看全球事件（图片）"""
        try:
            paths = await self._svc().get_global_events_image()
        except Exception as e:
            logger.exception(f"[HD2] /global_events error: {e}")
            yield event.plain_result("❌ 获取全球事件失败，请稍后重试。")
            return
        async for r in self._yield_images(
            event, paths, fallback="❌ 获取全球事件失败，请稍后重试。"
        ):
            yield r

    @filter.command("warfront", alias={"战线"})
    @_command_handler
    async def cmd_warfront(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """查看特定阵营战线（图片），用法: /warfront Terminids"""
        args = _strip_cmd(event.message_str or "", {"warfront", "战线"})
        faction = " ".join(args).strip()
        try:
            err, paths = await self._svc().get_warfront_image(faction)
        except Exception as e:
            logger.exception(f"[HD2] /warfront error: {e}")
            yield event.plain_result("❌ 获取战线信息失败，请稍后重试。")
            return
        if err:
            yield event.plain_result(err)
            return
        async for r in self._yield_images(
            event, paths, fallback="❌ 获取战线信息失败，请稍后重试。"
        ):
            yield r

    @filter.command("planet", alias={"星球"})
    @_command_handler
    async def cmd_planet(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """查询星球详情（图片），用法: /planet Heeth"""
        args = _strip_cmd(event.message_str or "", {"planet", "星球"})
        query = " ".join(args).strip()
        try:
            err, paths = await self._svc().get_planet_image(query)
        except Exception as e:
            logger.exception(f"[HD2] /planet error: {e}")
            yield event.plain_result("❌ 获取星球信息失败，请稍后重试。")
            return
        if err:
            yield event.plain_result(err)
            return
        async for r in self._yield_images(
            event, paths, fallback="❌ 获取星球信息失败，请稍后重试。"
        ):
            yield r

    @filter.command("map", alias={"地图"})
    @_command_handler
    async def cmd_map(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """生成当前银河战争地图图片"""
        try:
            caption, path = await self._svc().get_map_result()
        except Exception as e:
            logger.exception(f"[HD2] /map error: {e}")
            yield event.plain_result("❌ 生成地图失败，请稍后重试。")
            return

        if path is not None:
            try:
                yield event.chain_result(
                    [
                        Plain(caption + "\n"),
                        Image.fromFileSystem(str(path)),
                    ]
                )
                return
            except Exception as e:
                logger.warning(f"[HD2] send map image failed: {e}")
                yield event.plain_result(caption + f"\n（图片发送失败: {path}）")
                return
        yield event.plain_result(caption)
