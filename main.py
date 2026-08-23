"""astrbot_plugin_Helldivers — Helldivers 2 银河战争查询插件。

指令:
  /hd2stats /dashboard /order /hd2news /steam /wiki /hd2data
  /major_order /personal_order /map /dss
  /global_events /warfront /planet
/银河快报
/hd2 | /hd2help
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from collections.abc import AsyncGenerator, Callable
from functools import wraps
from pathlib import Path
from typing import Any, Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig

from .api_client import HD2Client
from .bilibili_monitor import (
    BilibiliAuthenticationError,
    BilibiliMonitor,
    BilibiliPost,
    BilibiliRiskControlError,
    GALAXY_NEWS_UID,
    LEGACY_GALAXY_NEWS_UID,
)
from .visual_assets import configure_asset_manifest
from .awaiting_orders_renderer import AwaitingOrdersRenderer
from .cache import CacheService, get_plugin_data_dir
from .campaign_trends import CampaignTrendStore
from .card_renderer import CardRenderer
from .companion_screenshot import (
    CompanionConfigurationError,
    CompanionPlaywrightClient,
    CompanionScreenshotClient,
    CompanionScreenshotError,
    CompanionTarget,
    CompanionTargetError,
    companion_dss_target,
    companion_homepage_target,
    companion_latest_news_target,
    parse_companion_planet_target,
)
from .companion_news_monitor import CompanionNewsMonitor
from .dashboard_renderer import DashboardRenderer
from .dss_renderer import DSSRenderer
from .dispatch_renderer import DispatchRenderer
from .global_event_renderer import GlobalEventRenderer
from .map_renderer import MapRenderer
from .major_order_renderer import MajorOrderRenderer
from .plugin_info import (
    PLUGIN_AUTHOR,
    PLUGIN_NAME,
    PLUGIN_VERSION,
    USER_AGENT,
)
from .remote_image_cache import RemoteImageCache
from .services import HelldiversService
from .stats_renderer import StatsRenderer
from .steam_renderer import SteamRenderer
from .translator import TranslationCache, TranslationService
from .warfront_renderer import WarfrontRenderer
from .arsenal_client import ArsenalClient
from .wiki_client import WikiCache, WikiClient

PLUGIN_DESC = (
    "Helldivers 2 银河战争图片情报：Dashboard、统计、DSS、星图、事件、Steam 与战线排行"
)

HELP_TEXT = """\
Helldivers 2 银河战争 {version}
━━━━━━━━━━━━━━━━━━━━
【战况 · 图片卡片】
/dashboard            银河战争总览（实时数据）
/hd2stats             银河战争详细统计（实时数据）
/major_order          主要任务（同 /order）
/personal_order       个人任务
/map                  战争地图（阵营领土）
/dss                  Companion 民主空间站图文
/global_events        全球事件
/hd2news              Companion 最新新闻
/hd2news订阅 / 退订   新闻更新自动推送
/companion            Companion 首页（截图+翻译）
/warfront <阵营>      战线战况
/planet <名称/编号>   星球详情
/steam                Steam 新闻图片
【文本】
/wiki <关键词>        Helldivers Wiki（-f 查看全文）
/hd2data <名称>       军需簿：武器/护甲/敌人
/银河快报             立即获取最新一期银河快报
/hd2help              全部指令说明
/hd2                  简短帮助
━━━━━━━━━━━━━━━━━━━━
阵营: Terminids / Automaton / Illuminate
     （终结族 / 机器人 / 光能者）
数据: api.helldivers2.dev · wiki.gg · HD2Tool
为了超级地球！🌍""".format(version=PLUGIN_VERSION)

HDHELP_TEXT = """\
绝地潜兵2情报助手 {version} · 全部指令
━━━━━━━━━━━━━━━━━━━━

【核心战况 · 实时数据】
/dashboard            银河战争总览（防御/解放/重点战线）
/hd2stats             在线人数、击杀、命中率等统计
/order                当前最高指令任务卡
/po                   当前个人指令

【Companion 截图 · 翻译】
/hd2news              最新新闻（截图+翻译）
/hd2news订阅 / 退订   新闻更新自动推送到本群
/companion            Companion 首页
/dss                  民主空间站面板+摘要
/planet <名称/编号>   星球详情（支持中文名和链接）
/hd2refresh           强制刷新截图缓存

【地图与战线】
/map                  银河战争地图
/warfront <阵营>      阵营战线 Top 10
/events               全球事件

【外部资讯】
/steam                Steam 更新公告
/wiki <关键词>        Wiki 查询（中文自动译名；加 -f 看全文）
/hd2data <名称>       军需簿：武器/护甲/敌人（俗称：电喷/泰坦）
/银河快报             最新一期快报
/银河快报订阅 / 退订   群推送开关

【帮助】
/hd2                  简短帮助
/hd2help              本说明
━━━━━━━━━━━━━━━━━━━━
阵营: 终结族 / 机器人 / 光能者
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
        event.stop_event()
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
        self.bilibili_monitor: BilibiliMonitor | None = None
        self.bilibili_auto_enabled = False
        self.companion_enabled = False
        self.companion_backend = "playwright"
        self.companion_playwright: CompanionPlaywrightClient | None = None
        self.companion_screenshots: CompanionScreenshotClient | None = None
        self._companion_warmup_task: asyncio.Task | None = None
        self.companion_news_monitor: CompanionNewsMonitor | None = None
        self._companion_news_push_enabled = False

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

        self.companion_enabled = bool(
            self._cfg("enable_companion_screenshots", False)
        )
        self.companion_backend = str(
            self._cfg("companion_render_backend", "playwright") or "playwright"
        ).strip().casefold()
        if self.companion_backend not in {"local", "playwright", "browserless"}:
            logger.warning(
                "[HD2] Invalid companion_render_backend=%s; using playwright",
                self.companion_backend,
            )
            self.companion_backend = "playwright"
        self.companion_playwright = None
        self.companion_screenshots = None
        if self.companion_enabled and self.companion_backend == "playwright":
            try:
                self.companion_playwright = CompanionPlaywrightClient(
                    data_dir / "companion_screenshots",
                    timeout=int(self._cfg("companion_screenshot_timeout", 60) or 60),
                    wait_ms=int(
                        self._cfg("companion_screenshot_wait_ms", 5000) or 5000
                    ),
                    cache_ttl=int(
                        self._cfg("companion_screenshot_cache_ttl", 300) or 300
                    ),
                    max_bytes=int(
                        self._cfg(
                            "companion_screenshot_max_bytes", 12 * 1024 * 1024
                        )
                        or 12 * 1024 * 1024
                    ),
                    max_pixels=int(
                        self._cfg("companion_screenshot_max_pixels", 20_000_000)
                        or 20_000_000
                    ),
                    page_load_timeout=float(
                        self._cfg("companion_page_load_timeout", 20.0) or 20.0
                    ),
                    translation_timeout=float(
                        self._cfg("companion_translation_timeout", 60.0) or 60.0
                    ),
                    show_inactive=bool(
                        self._cfg("companion_show_inactive", False)
                    ),
                )
                await self.companion_playwright.start()
            except (CompanionConfigurationError, TypeError, ValueError) as e:
                logger.warning(f"[HD2] Local Playwright disabled: {e}")
                self.companion_playwright = None
        elif self.companion_enabled and self.companion_backend == "browserless":
            try:
                self.companion_screenshots = CompanionScreenshotClient(
                    data_dir / "companion_screenshots",
                    endpoint_url=str(
                        self._cfg("companion_browserless_url", "") or ""
                    ),
                    token=str(self._cfg("companion_browserless_token", "") or ""),
                    proxy_url=str(
                        self._cfg("companion_browserless_proxy_url", "") or ""
                    ),
                    timeout=int(
                        self._cfg("companion_screenshot_timeout", 60) or 60
                    ),
                    wait_ms=int(
                        self._cfg("companion_screenshot_wait_ms", 5000) or 5000
                    ),
                    cache_ttl=int(
                        self._cfg("companion_screenshot_cache_ttl", 300) or 300
                    ),
                    max_bytes=int(
                        self._cfg(
                            "companion_screenshot_max_bytes", 12 * 1024 * 1024
                        )
                        or 12 * 1024 * 1024
                    ),
                    max_pixels=int(
                        self._cfg("companion_screenshot_max_pixels", 20_000_000)
                        or 20_000_000
                    ),
                )
            except (CompanionConfigurationError, TypeError, ValueError) as e:
                logger.warning(f"[HD2] Companion screenshot disabled: {e}")

        client = HD2Client(
            base_url=str(self._cfg("api_base", "https://api.helldivers2.dev")),
            war_id=int(self._cfg("war_id", 801) or 801),
            client_name=str(self._cfg("api_client_name", "astrbot_plugin_Helldivers")),
            contact=str(self._cfg("api_contact", "") or ""),
            user_agent=str(
                self._cfg("api_user_agent", USER_AGENT)
            ),
            timeout=int(self._cfg("api_timeout", 20) or 20),
            proxy_url=str(self._cfg("proxy_url", "") or ""),
            retry_base_delay=float(self._cfg("retry_base_delay", 3.0) or 3.0),
            retry_max_delay=float(self._cfg("retry_max_delay", 15.0) or 15.0),
            retry_max_attempts=int(self._cfg("retry_max_attempts", 2) or 2),
            min_request_interval=float(self._cfg("min_request_interval", 3.0) or 3.0),
            steam_appid=int(self._cfg("steam_appid", 553850) or 553850),
            steam_news_count=int(self._cfg("steam_news_count", 10) or 10),
        )

        cache = CacheService(
            data_dir,
            update_interval=int(self._cfg("cache_update_interval", 300) or 300),
            request_delay=float(self._cfg("request_delay", 6) or 6),
            enable_background=bool(self._cfg("enable_background_refresh", True)),
        )

        enable_translation = bool(self._cfg("enable_translation", True))
        translator = TranslationService(
            api_url=str(
                self._cfg(
                    "translation_api_url",
                    "https://uapis.cn/api/v1/ai/translate",
                )
            ),
            timeout=int(self._cfg("translation_timeout", 20) or 20),
            target_lang=str(self._cfg("translation_target_lang", "zh") or "zh"),
            user_agent=str(
                self._cfg("api_user_agent", USER_AGENT)
            ),
            proxy_url=str(self._cfg("proxy_url", "") or ""),
            enabled=enable_translation,
            mode=str(self._cfg("translation_mode", "auto") or "auto"),
            api_key=str(self._cfg("translation_api_key", "") or ""),
            model=str(self._cfg("translation_model", "gpt-4o-mini") or "gpt-4o-mini"),
            stream=bool(self._cfg("translation_stream", False)),
            fallback_ttl=int(
                self._cfg("translation_retry_fallback_seconds", 180) or 180
            ),
            error_cooldown=int(
                self._cfg("translation_error_cooldown_seconds", 120) or 120
            ),
            max_tokens=int(
                self._cfg("translation_max_tokens", 1200) or 0
            ),
        )
        logger.info("[HD2] translation provider: %s", translator.diagnostic())

        translation_cache = TranslationCache(
            data_dir,
            provider_fingerprint=translator.provider_fingerprint(),
            fallback_ttl=int(
                self._cfg("translation_retry_fallback_seconds", 180) or 180
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
                    self._cfg("api_user_agent", USER_AGENT)
                ),
                timeout=int(self._cfg("api_timeout", 30) or 30),
                proxy_url=str(self._cfg("proxy_url", "") or ""),
                search_limit=int(self._cfg("wiki_search_limit", 5) or 5),
                extract_chars=int(self._cfg("wiki_extract_chars", 900) or 900),
                full_extract_chars=int(
                    self._cfg("wiki_full_extract_chars", 3000) or 3000
                ),
                prefer_hd2=bool(self._cfg("wiki_prefer_hd2", True)),
                retry_max_attempts=int(self._cfg("retry_max_attempts", 3) or 3),
                retry_base_delay=float(self._cfg("retry_base_delay", 2.0) or 2.0),
                cache=wiki_cache,
            )
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
                self._cfg("api_user_agent", USER_AGENT)
            ),
            proxy_url=str(self._cfg("proxy_url", "") or ""),
        )
        campaign_trends = CampaignTrendStore(
            data_dir / "campaign_history.json",
            window_minutes=max(1.0, float(self._cfg("campaign_rate_window_minutes", 20) or 20)),
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
            wiki_client=wiki_client,
            enable_wiki=enable_wiki,
            translate_wiki=bool(self._cfg("translate_wiki", True)),
            map_renderer=map_renderer,
            enable_map=bool(self._cfg("enable_map", True)),
            personal_order_api_url=str(self._cfg("personal_order_api_url", "") or ""),
            allow_private_personal_order_url=bool(
                self._cfg("allow_private_personal_order_url", False)
            ),
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
            drop_untranslated_content=bool(
                self._cfg("drop_untranslated_content", True)
            ),
            companion_translation_batch_timeout=float(
                self._cfg("companion_translation_batch_timeout", 20.0) or 20.0
            ),
            companion_translation_budget=float(
                self._cfg("companion_translation_timeout", 60.0) or 60.0
            ),
            arsenal_client=ArsenalClient(
                data_dir / "arsenal",
                proxy_url=str(self._cfg("proxy_url", "") or ""),
                timeout=int(self._cfg("api_timeout", 30) or 30),
                user_agent=str(self._cfg("api_user_agent", USER_AGENT)),
            )
            if bool(self._cfg("enable_arsenal", True))
            else None,
        )

        if self.companion_playwright is not None and enable_translation:
            self.companion_playwright.set_translate_callback(
                self.service.translate_companion_fragments,
                cache_namespace=self.service.translation_cache.provider_fingerprint,
            )

        await self.service.start()

        configured_bilibili_uid = str(
            self._cfg("bilibili_uid", GALAXY_NEWS_UID) or GALAXY_NEWS_UID
        ).strip()
        if configured_bilibili_uid == LEGACY_GALAXY_NEWS_UID:
            logger.warning(
                "[HD2] 已自动修正银河快报旧 UID：%s -> %s",
                LEGACY_GALAXY_NEWS_UID,
                GALAXY_NEWS_UID,
            )
            configured_bilibili_uid = GALAXY_NEWS_UID
        self.bilibili_monitor = BilibiliMonitor(
            data_dir / "bilibili_galaxy_news",
            uid=configured_bilibili_uid,
            keyword=str(self._cfg("bilibili_keyword", "银河快报") or "银河快报"),
            interval=int(self._cfg("bilibili_poll_interval", 300) or 300),
            cookie=str(self._cfg("bilibili_cookie", "") or ""),
            proxy_url=str(self._cfg("proxy_url", "") or ""),
            timeout=int(self._cfg("api_timeout", 30) or 30),
            max_image_bytes=int(
                self._cfg("bilibili_image_max_bytes", 12 * 1024 * 1024)
                or 12 * 1024 * 1024
            ),
            send_post=self._send_bilibili_post,
            log_info=logger.info,
            log_warning=logger.warning,
            image_cache=RemoteImageCache(
                data_dir / "bilibili_galaxy_news" / "secure_images_v3",
                allowed_hosts=frozenset(
                    {
                        "i0.hdslb.com",
                        "i1.hdslb.com",
                        "i2.hdslb.com",
                        "archive.biliimg.com",
                        "album.biliimg.com",
                    }
                ),
                max_bytes=int(
                    self._cfg("bilibili_image_max_bytes", 12 * 1024 * 1024)
                    or 12 * 1024 * 1024
                ),
                max_pixels=int(
                    self._cfg("bilibili_image_max_pixels", 32000000)
                    or 32000000
                ),
                max_cache_bytes=int(self._cfg("image_cache_max_mb", 150) or 150)
                * 1024
                * 1024,
                user_agent=str(
                    self._cfg(
                        "api_user_agent",
                        USER_AGENT,
                    )
                ),
                proxy_url=str(self._cfg("proxy_url", "") or ""),
                negative_ttl=60,
                request_headers={
                    "Referer": "https://www.bilibili.com/",
                },
            ),
        )
        self.bilibili_auto_enabled = bool(
            self._cfg("enable_bilibili_galaxy_news", False)
        )
        if self.bilibili_auto_enabled:
            if not self.bilibili_monitor.has_login_cookie:
                logger.warning(
                    "[HD2] 银河快报后台监听未启动：bilibili_cookie 缺少 SESSDATA。"
                    "请填写浏览器登录后的完整 B站 Cookie 并重载插件。"
                )
            else:
                await self.bilibili_monitor.start()
                logger.info(
                    "[HD2] Bilibili galaxy news enabled: uid=%s keyword=%s sessions=%s",
                    self.bilibili_monitor.uid,
                    self.bilibili_monitor.keyword,
                    len(self.bilibili_monitor.sessions),
                )

        contact = str(self._cfg("api_contact", "") or "").strip()
        if not contact:
            logger.warning(
                "[HD2] 建议在插件配置中填写 api_contact（联系邮箱），以遵守 Helldivers API 礼仪"
            )
        logger.info(f"[HD2] plugin initialized {PLUGIN_VERSION}, data_dir={data_dir}")
        self.companion_news_monitor = CompanionNewsMonitor(
            data_dir / "companion_news"
        )
        self._companion_news_push_enabled = bool(
            self._cfg("companion_news_push_enabled", False)
        )
        self._start_companion_warmup()

    def _start_companion_warmup(self) -> None:
        """Launch the background Companion screenshot warmup loop.

        The warmup loop periodically captures Companion pages (news, DSS, …)
        in the background so that translation results are pre-populated in the
        disk cache.  When a user actually runs ``/hd2news``, the screenshot is
        already cached and returned instantly — the translation API latency is
        absorbed in the background instead of blocking the user.
        """

        if self._companion_warmup_task is not None:
            return
        if self.companion_playwright is None:
            return
        if not bool(self._cfg("companion_warmup_enabled", True)):
            return
        self._companion_warmup_task = asyncio.create_task(
            self._companion_warmup_loop(), name="hd2-companion-warmup"
        )
        logger.info("[HD2] Companion 截图后台预热已启动")

    async def _companion_warmup_loop(self) -> None:
        """Periodically pre-capture Companion pages in the background.

        Each capture follows the exact same path as a user request (page load
        → DOM text extraction → translate_callback → screenshot → cache file).
        Translation is not time-pressured here: the foreground budget and
        batch timeouts still apply, but failures are swallowed — the disk
        translation cache gradually fills with fragments, and ``stale-while-
        revalidate`` means a partially-warmed cache still serves a usable
        screenshot on the next user request.
        """

        interval = max(60, int(self._cfg("companion_warmup_interval", 300) or 300))
        kinds_raw = str(
            self._cfg("companion_warmup_kinds", "news_latest,station")
            or "news_latest,station"
        ).strip()
        kind_map = {
            "news_latest": companion_latest_news_target,
            "station": companion_dss_target,
            "homepage": companion_homepage_target,
        }
        targets: list[CompanionTarget] = []
        for token in kinds_raw.split(","):
            kind = token.strip().casefold()
            factory = kind_map.get(kind)
            if factory is not None:
                targets.append(factory())
        if not targets:
            return
        # Give the rest of the plugin a moment to settle before the first run.
        await asyncio.sleep(15)
        while True:
            for target in targets:
                try:
                    # When news push is enabled, force a fresh capture for
                    # news_latest so text extraction always runs (the TTL
                    # cache would otherwise skip the page load and leave
                    # capture_texts stale, preventing change detection).
                    force = (
                        target.kind == "news_latest"
                        and self._companion_news_push_enabled
                        and self.companion_news_monitor is not None
                    )
                    path = await self.companion_playwright.capture(  # type: ignore[union-attr]
                        target, force=force
                    )
                    logger.info(
                        "[HD2] Companion 预热完成: %s", target.kind
                    )
                    if target.kind == "news_latest":
                        await self._check_companion_news_change(path)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - background warmup
                    # news_latest 失败会影响订阅推送的及时性，用 WARNING 留痕；
                    # 其余页面预热失败属正常降级，保持 DEBUG。
                    log = (
                        logger.warning
                        if target.kind == "news_latest"
                        else logger.debug
                    )
                    log("[HD2] Companion 预热失败 %s: %s", target.kind, exc)
                # Small spacing between captures to avoid bursting.
                await asyncio.sleep(5)
            await asyncio.sleep(interval)

    async def _check_companion_news_change(self, path: Path) -> None:
        """Detect news content changes via fingerprint and push to subscribers.

        Called from the warmup loop after each ``news_latest`` capture with
        the screenshot path already in hand — no second capture needed.
        The fingerprint is only committed after a successful push (or an
        intentional skip), so a transient delivery failure doesn't
        permanently consume a news update — the next warmup cycle
        re-detects and re-pushes.
        """
        monitor = self.companion_news_monitor
        if monitor is None:
            return
        client = self.companion_playwright
        if client is None:
            return
        texts = client.capture_texts("news_latest")
        if not texts:
            return
        fingerprint = hashlib.sha1("\n".join(texts).encode("utf-8")).hexdigest()
        if not monitor.check_fingerprint(fingerprint):
            return
        if not monitor.sessions:
            logger.info(
                "[HD2] Companion 新闻已更新，但无订阅群，跳过推送"
            )
            monitor.commit_fingerprint(fingerprint)
            return
        if not self._companion_news_push_enabled:
            logger.info(
                "[HD2] Companion 新闻已更新，但推送总开关未启用，跳过推送"
            )
            monitor.commit_fingerprint(fingerprint)
            return
        # 翻译未完成时 capture 会返回旧缓存截图（stale-while-revalidate），
        # 而文本指纹已是新内容——此时推送的是过期图片。跳过推送且不提交
        # 指纹，等下一轮预热拿到带新内容的截图再推。
        if self._served_companion_stale("news_latest"):
            logger.info(
                "[HD2] Companion 新闻已更新，但截图为旧缓存（翻译未完成），"
                "本轮跳过推送，下一轮重试"
            )
            return
        delivered = await self._push_companion_news(path, list(monitor.sessions))
        if delivered > 0:
            monitor.commit_fingerprint(fingerprint)
        else:
            logger.warning(
                "[HD2] Companion 新闻推送全部失败（delivered=0/%d），"
                "不提交指纹，下一轮预热将重试推送",
                len(monitor.sessions),
            )

    async def _push_companion_news(
        self, path: Path, sessions: list[str]
    ) -> int:
        """Send a news-update screenshot to all subscribed sessions.

        Returns the number of sessions the message was delivered to.
        """
        if not path or not path.is_file():
            logger.warning(
                "[HD2] Companion news push image missing: %s", path
            )
            return 0
        try:
            image_bytes = path.read_bytes()
        except OSError as exc:
            logger.warning(
                "[HD2] Companion news push image unreadable: %s error=%s",
                path,
                exc,
            )
            return 0
        delivered = 0
        for unified_msg_origin in sessions:
            try:
                chain = MessageChain().message("📰 Companion 新闻更新")
                chain.chain.append(Image.fromBytes(image_bytes))
                await self.context.send_message(unified_msg_origin, chain)
                delivered += 1
            except Exception as e:
                logger.warning(
                    "[HD2] Companion news push failed: session=%s error=%s",
                    unified_msg_origin,
                    e,
                )
        if delivered:
            logger.info(
                "[HD2] Companion 新闻推送完成: delivered=%d/%d",
                delivered,
                len(sessions),
            )
        return delivered

    async def terminate(self) -> None:
        if self._companion_warmup_task is not None:
            self._companion_warmup_task.cancel()
            try:
                await self._companion_warmup_task
            except (asyncio.CancelledError, Exception):
                pass
            self._companion_warmup_task = None
        if self.bilibili_monitor is not None:
            try:
                await self.bilibili_monitor.stop()
            except Exception as e:
                logger.warning(f"[HD2] Bilibili monitor stop error: {e}")
            self.bilibili_monitor = None
        self.bilibili_auto_enabled = False
        if self.companion_playwright is not None:
            try:
                await self.companion_playwright.close()
            except Exception as e:
                logger.warning(f"[HD2] Local Playwright stop error: {e}")
        self.companion_playwright = None
        self.companion_enabled = False
        self.companion_screenshots = None
        if self.service is not None:
            try:
                await self.service.stop()
            except Exception as e:
                logger.warning(f"[HD2] service stop error: {e}")
            self.service = None
        logger.info("[HD2] plugin terminated")

    async def _send_bilibili_post(
        self,
        post: BilibiliPost,
        image_paths: list[Path],
        sessions: list[str],
    ) -> None:
        if not sessions:
            logger.info(
                "[HD2] matched Bilibili dynamic %s, but no QQ group subscribed",
                post.dynamic_id,
            )
            return
        text = post.text or "（该动态没有文字内容）"
        # 预读图片字节：AstrBot 容器与 NapCat 宿主机分离部署时，
        # file:/// 路径跨进程不可读，直接内嵌 base64 绕过文件系统。
        image_bytes: list[bytes] = []
        for path in image_paths:
            try:
                image_bytes.append(path.read_bytes())
            except OSError as exc:
                logger.warning(
                    "[HD2] Bilibili image unreadable: path=%s error=%s",
                    path,
                    exc,
                )
        delivered = 0
        for unified_msg_origin in sessions:
            try:
                chain = MessageChain().message(f"【{post.author}】\n{text}")
                for data in image_bytes:
                    chain.chain.append(Image.fromBytes(data))
                chain.message(f"\n原动态：{post.url}")
                await self.context.send_message(
                    unified_msg_origin,
                    chain,
                )
                delivered += 1
            except Exception as e:
                logger.warning(
                    "[HD2] Bilibili push failed: session=%s dynamic=%s error=%s",
                    unified_msg_origin,
                    post.dynamic_id,
                    e,
                )
        if delivered == 0:
            raise RuntimeError(
                f"Bilibili dynamic {post.dynamic_id} failed for all subscribed groups"
            )

    def _svc(self) -> HelldiversService:
        if self.service is None:
            raise RuntimeError("插件尚未初始化完成")
        return self.service

    # ---- help ----

    @filter.command("银河快报", alias=["银河快报推送", "galaxy_news"])
    @_command_handler
    async def cmd_galaxy_news(
        self, event: AstrMessageEvent
    ) -> AsyncGenerator[Any, None]:
        """立即获取并发送最新一期 B站银河快报。"""
        monitor = self.bilibili_monitor
        if monitor is None:
            yield event.plain_result("❌ 银河快报服务尚未初始化完成。")
            return
        try:
            posts = await monitor.fetch_posts()
            post = monitor.latest_matching(posts)
            if post is None:
                previews = [
                    f"{item.dynamic_id}:{item.text[:40]!r}" for item in posts[:5]
                ]
                logger.warning(
                    "[HD2] no Bilibili keyword match: keyword=%r posts=%s previews=%s",
                    monitor.keyword,
                    len(posts),
                    previews,
                )
                if posts and not any(item.text for item in posts):
                    yield event.plain_result(
                        "❌ B站返回了动态，但正文结构暂时无法识别，请查看日志中的动态 ID。"
                    )
                    return
                yield event.plain_result(
                    f"ℹ️ 最近的动态中没有找到关键字“{monitor.keyword}”。"
                )
                return
            paths = await monitor.download_images(post)
            components: list[Any] = [Plain(f"【{post.author}】\n{post.text}")]
            for path in paths:
                try:
                    components.append(Image.fromBytes(path.read_bytes()))
                except OSError as exc:
                    logger.warning(
                        f"[HD2] galaxy news image unreadable: {path} error={exc}"
                    )
            components.append(Plain(f"\n原动态：{post.url}"))
            yield event.chain_result(components)
        except (BilibiliAuthenticationError, BilibiliRiskControlError) as e:
            logger.warning(f"[HD2] manual Bilibili galaxy news blocked: {e}")
            yield event.plain_result(f"❌ {e}")
        except Exception as e:
            logger.warning(f"[HD2] manual Bilibili galaxy news error: {e}")
            yield event.plain_result("❌ 获取银河快报失败，请查看 AstrBot 日志。")

    @filter.command("银河快报订阅", alias=["galaxy_news_subscribe"])
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @_command_handler
    async def cmd_galaxy_news_subscribe(
        self, event: AstrMessageEvent
    ) -> AsyncGenerator[Any, None]:
        """在当前群订阅 B站“银河快报”动态推送。"""
        if self.bilibili_monitor is None or not self.bilibili_auto_enabled:
            yield event.plain_result(
                "❌ 银河快报监听未启用，请先在插件配置中开启。"
            )
            return
        if not self.bilibili_monitor.has_login_cookie:
            yield event.plain_result(
                "❌ 银河快报监听缺少有效 B站登录 Cookie（必须包含 SESSDATA），"
                "请在插件配置中填写后重载插件。"
            )
            return
        origin = str(getattr(event, "unified_msg_origin", "") or "").strip()
        if not origin:
            yield event.plain_result("❌ 无法获取当前群会话标识，请检查适配器。")
            return
        if self.bilibili_monitor.subscribe(origin):
            yield event.plain_result("✅ 已订阅银河快报，新动态将自动同步到本群。")
        else:
            yield event.plain_result("ℹ️ 本群已经订阅银河快报。")

    @filter.command("银河快报退订", alias=["galaxy_news_unsubscribe"])
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @_command_handler
    async def cmd_galaxy_news_unsubscribe(
        self, event: AstrMessageEvent
    ) -> AsyncGenerator[Any, None]:
        """取消当前群的 B站“银河快报”动态推送。"""
        if self.bilibili_monitor is None:
            yield event.plain_result("ℹ️ 银河快报监听当前未启用。")
            return
        origin = str(getattr(event, "unified_msg_origin", "") or "").strip()
        if origin and self.bilibili_monitor.unsubscribe(origin):
            yield event.plain_result("✅ 已取消本群的银河快报订阅。")
        else:
            yield event.plain_result("ℹ️ 本群尚未订阅银河快报。")

    @filter.command("hd2", alias={"helldivers"})
    @_command_handler
    async def cmd_help(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """Helldivers 2 插件帮助"""
        yield event.plain_result(HELP_TEXT)

    @filter.command("hd2help", alias={"hdhelp"})
    @_command_handler
    async def cmd_hdhelp(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """Helldivers 2 插件全部指令说明"""
        yield event.plain_result(HDHELP_TEXT)

    async def _capture_companion_page(
        self, target: CompanionTarget, *, force: bool = False
    ) -> Path:
        if not self.companion_enabled:
            raise CompanionConfigurationError(
                "Companion 网页截图尚未启用"
            )
        if self.companion_backend == "local":
            raise CompanionConfigurationError("当前配置为 Pillow 本地渲染后端")

        if self.companion_backend == "playwright":
            client = self.companion_playwright
            if client is None:
                raise CompanionConfigurationError(
                    "本地 Playwright 尚未启用，请检查容器中的 Chromium 和插件日志"
                )
            return await client.capture(target, force=force)

        client = self.companion_screenshots
        if client is None:
            raise CompanionConfigurationError(
                "Browserless 网页截图尚未启用"
            )
        if self._svc().enable_translation:
            raise CompanionConfigurationError(
                "Browserless /screenshot 后端无法调用插件翻译器，无法生成中文 Companion 截图"
            )
        return await client.capture(target, force=force)

    def _served_companion_stale(self, kind: str) -> bool:
        """Whether the last capture for *kind* served a stale cache."""
        client = self.companion_playwright
        if client is None:
            return False
        return kind in client._served_stale

    def _stale_fallback_path(self, target: CompanionTarget) -> Path | None:
        """Return a stale cached screenshot path if one exists, else None."""
        client = self.companion_playwright
        if client is None:
            return None
        output = client.output_dir / (
            f"playwright_v9_{client._cache_namespace}_{client._cache_key(target)}"
        )
        if output.is_file():
            return output
        return None

    # ---- war cards (images) ----

    @filter.command("hd2stats")
    @_command_handler
    async def cmd_stats(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """查看当前银河战争实时统计（图片，直调社区 API）"""
        try:
            paths = await self._svc().get_stats_images(realtime=True)
        except Exception as e:
            logger.exception(f"[HD2] /hd2stats error: {e}")
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

    @filter.command("hd2news")
    @_command_handler
    async def cmd_news(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """截图 Companion 最新新闻。"""
        target = companion_latest_news_target()
        try:
            path = await self._capture_companion_page(target)
            components: list[Any] = []
            if self._served_companion_stale(target.kind):
                components.append(
                    Plain("📰 翻译快照（内容稍旧），后台正在刷新，稍后重试可获取最新翻译。\n")
                )
            components.append(Image.fromFileSystem(str(path)))
            yield event.chain_result(components)
            return
        except Exception as e:
            logger.exception(f"[HD2] /hd2news Companion capture failed: {e}")
            try:
                _, paths = await self._svc().get_news_image(1)
            except Exception as fallback_error:
                logger.warning(f"[HD2] /hd2news local fallback failed: {fallback_error}")
                paths = []
            if paths:
                yield event.plain_result(
                    "⚠️ Companion 翻译暂时繁忙，已为你展示基础新闻卡片，"
                    "稍后重试可获取完整翻译截图。"
                )
                yield event.chain_result([Image.fromFileSystem(str(paths[0]))])
            else:
                yield event.plain_result("❌ Companion 最新新闻暂时不可用，请稍后重试。")
            return

    @filter.command("hd2news订阅", alias={"news_subscribe"})
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @_command_handler
    async def cmd_news_subscribe(
        self, event: AstrMessageEvent
    ) -> AsyncGenerator[Any, None]:
        """在当前群订阅 Companion 新闻推送。"""
        monitor = self.companion_news_monitor
        if monitor is None:
            yield event.plain_result(
                "❌ Companion 新闻推送尚未初始化。"
            )
            return
        if not self.companion_enabled or self.companion_backend != "playwright":
            yield event.plain_result(
                "❌ 需先启用 Companion Playwright 截图（配置 enable_companion_screenshots "
                "并选择 playwright 后端），才能订阅新闻推送。"
            )
            return
        if not self._companion_news_push_enabled:
            yield event.plain_result(
                "❌ 新闻推送总开关未启用，请在插件配置中开启 "
                "companion_news_push_enabled 后重载插件。"
            )
            return
        if not bool(self._cfg("companion_warmup_enabled", True)):
            yield event.plain_result(
                "❌ Companion 后台预热未启用，新闻推送依赖预热循环检测变更。"
                "请在配置中开启 companion_warmup_enabled。"
            )
            return
        origin = str(getattr(event, "unified_msg_origin", "") or "").strip()
        if not origin:
            yield event.plain_result("❌ 无法获取当前群会话标识，请检查适配器。")
            return
        if monitor.subscribe(origin):
            yield event.plain_result(
                "✅ 已订阅 Companion 新闻推送，有新新闻时将自动同步到本群。"
            )
        else:
            yield event.plain_result("ℹ️ 本群已经订阅 Companion 新闻推送。")

    @filter.command("hd2news退订", alias={"news_unsubscribe"})
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @_command_handler
    async def cmd_news_unsubscribe(
        self, event: AstrMessageEvent
    ) -> AsyncGenerator[Any, None]:
        """取消当前群的 Companion 新闻推送。"""
        monitor = self.companion_news_monitor
        if monitor is None:
            yield event.plain_result("ℹ️ Companion 新闻推送当前未启用。")
            return
        origin = str(getattr(event, "unified_msg_origin", "") or "").strip()
        if origin and monitor.unsubscribe(origin):
            yield event.plain_result("✅ 已取消本群的 Companion 新闻推送。")
        else:
            yield event.plain_result("ℹ️ 本群尚未订阅 Companion 新闻推送。")

    @filter.command("companion", alias={"首页", "companion_home"})
    @_command_handler
    async def cmd_companion(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """截图 Helldivers Companion 首页并翻译。"""
        target = companion_homepage_target()
        try:
            path = await self._capture_companion_page(target)
            yield event.chain_result([Image.fromFileSystem(str(path))])
            return
        except Exception as e:
            logger.exception(f"[HD2] /companion Companion capture failed: {e}")
            stale = self._stale_fallback_path(target)
            if stale:
                yield event.plain_result("⚠️ Companion 首页暂时加载失败，返回上次缓存截图。")
                yield event.chain_result([Image.fromFileSystem(str(stale))])
            else:
                yield event.plain_result("❌ Companion 首页截图失败，请稍后重试。")
            return

    @filter.command("hd2refresh", alias={"刷新缓存", "hd2clear"})
    @_command_handler
    async def cmd_refresh(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """强制刷新 Companion 截图缓存（跳过缓存重新截图+翻译）。"""
        if not self.companion_enabled or self.companion_backend != "playwright":
            yield event.plain_result("❌ 当前未启用 Playwright Companion 截图，无需刷新。")
            return
        targets = [
            companion_latest_news_target(),
            companion_dss_target(),
        ]
        if self.companion_playwright is not None:
            targets.append(companion_homepage_target())
        yield event.plain_result("🔄 正在强制刷新 Companion 截图缓存，请稍候…")
        results: list[str] = []
        for target in targets:
            try:
                await self._capture_companion_page(target, force=True)
                results.append(f"✅ {target.label}")
            except Exception as e:
                logger.warning(f"[HD2] /hd2refresh {target.kind} failed: {e}")
                results.append(f"❌ {target.label}（{e}）")
        yield event.plain_result("Companion 缓存刷新完成：\n" + "\n".join(results))

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
        """查询 Helldivers Wiki，用法: /wiki <关键词> [-f 全文]"""
        args = _strip_cmd(event.message_str or "", {"wiki", "维基", "百科"})
        # -f / --full 开关：返回全文而不是摘要
        full = False
        if "-f" in args or "--full" in args:
            full = True
            args = [a for a in args if a not in ("-f", "--full")]
        query = " ".join(args).strip()
        try:
            msg = await self._svc().get_wiki_message(query, full=full)
        except Exception as e:
            logger.exception(f"[HD2] /wiki error: {e}")
            msg = "❌ Wiki 查询失败，请稍后重试。"
        yield event.plain_result(msg)

    @filter.command("hd2data", alias={"军需簿", "数据库", "装备", "武器库"})
    @_command_handler
    async def cmd_arsenal_data(
        self, event: AstrMessageEvent
    ) -> AsyncGenerator[Any, None]:
        """军需簿查询：/hd2data <名称>，武器/战备/护甲（HD2Tool）+ 敌人（wiki.gg）"""
        args = _strip_cmd(event.message_str or "", {"hd2data", "军需簿", "数据库", "装备", "武器库"})
        query = " ".join(args).strip()
        if not query:
            yield event.plain_result(
                "用法: /hd2data <名称>（武器/战备/护甲/敌人）\n"
                "例如: /hd2data 磁轨炮 · /hd2data 电喷 · /hd2data 泰坦"
            )
            return
        try:
            result = await self._svc().get_arsenal_image(query)
            if isinstance(result, str):
                yield event.plain_result(result)
                return
            async for r in self._yield_images(event, result, fallback="❌ 军需簿查询失败。"):
                yield r
        except Exception as e:
            logger.exception(f"[HD2] /hd2data error: {e}")
            yield event.plain_result("❌ 军需簿查询失败，请稍后重试。")

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
        """截图 Companion DSS 页面并附中文情报。"""
        target = companion_dss_target()
        try:
            path = await self._capture_companion_page(target)
        except Exception as e:
            logger.exception(f"[HD2] /dss Companion capture failed: {e}")
            stale = self._stale_fallback_path(target)
            if stale:
                path = stale
            else:
                yield event.plain_result("❌ Companion DSS 截图失败，请稍后重试。")
                return

        try:
            message = await self._svc().get_dss_message()
        except Exception as e:
            logger.warning(f"[HD2] /dss translated text failed: {e}")
            message = "民主空间站中文情报暂时不可用。"
        yield event.chain_result(
            [
                Plain(message),
                Image.fromFileSystem(str(path)),
            ]
        )

    @filter.command("dashboard", alias={"总览", "战况总览"})
    @_command_handler
    async def cmd_dashboard(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """银河战争总览 Dashboard（图片，直调社区 API）"""
        try:
            paths = await self._svc().get_dashboard_image(realtime=True)
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
        """截图 Companion 星球页。"""
        args = _strip_cmd(event.message_str or "", {"planet", "星球"})
        query = " ".join(args).strip()
        if not query:
            yield event.plain_result(
                "❌ 用法: /planet <星球名称、编号、slug 或 Companion 链接>"
            )
            return

        try:
            if "://" in query or query.lstrip("#/").casefold().startswith(
                "hellpad/planets/"
            ):
                target = parse_companion_planet_target(query)
                fallback_query = target.value.replace("_", " ")
            else:
                err, canonical_name, slug = await self._svc().resolve_companion_planet(
                    query
                )
                if err or not canonical_name or not slug:
                    if query.isdigit():
                        yield event.plain_result(err or "❌ 无法解析该星球。")
                        return
                    try:
                        target = parse_companion_planet_target(query)
                    except CompanionTargetError:
                        yield event.plain_result(err or "❌ 无法解析该星球。")
                        return
                    fallback_query = target.value.replace("_", " ")
                else:
                    target = parse_companion_planet_target(slug)
                    fallback_query = canonical_name
        except CompanionTargetError as e:
            yield event.plain_result(f"❌ {e}")
            return
        except Exception as e:
            logger.exception(f"[HD2] /planet resolve error: {e}")
            yield event.plain_result("❌ 解析星球失败，请稍后重试。")
            return

        try:
            path = await self._capture_companion_page(target)
            try:
                message = await self._svc().get_planet_message(fallback_query)
            except Exception as message_error:
                logger.warning(f"[HD2] /planet translated text failed: {message_error}")
                message = ""
            components: list[Any] = []
            if message:
                components.append(Plain(message))
            components.append(Image.fromFileSystem(str(path)))
            yield event.chain_result(
                components
            )
            return
        except Exception as e:
            logger.exception(f"[HD2] /planet Companion capture failed: {e}")
            stale = self._stale_fallback_path(target)
            if stale:
                yield event.plain_result("⚠️ Companion 星球页暂时加载失败，返回上次缓存截图。")
                yield event.chain_result([Image.fromFileSystem(str(stale))])
            else:
                yield event.plain_result("❌ Companion 星球截图失败，请稍后重试。")
            return

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
