"""Bounded, on-demand capture of Jerry's Chinese galaxy map."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, ImageStat

from ..core.diagnostics import HEALTH


MAP_URL = "https://jerry114514.github.io/HD2-Galatic_war-Map/galaxy-map-v2.html"
DATA_PATH = "/HD2-Galatic_war-Map/data.json"
FONT_URL = "https://jerry114514.github.io/HD2_Wiki/assets/fonts/SourceHanSansCN-Medium.otf"
LOCAL_FONT_SCRIPT = """(() => {
    window.__hd2LocalFontReady = new FontFace(
        'SourceHanSans',
        'local("Noto Sans CJK SC"), local("Noto Sans SC"), local("Microsoft YaHei"), local("PingFang SC"), local("WenQuanYi Zen Hei")'
    ).load().then(font => {
        document.fonts.add(font);
        return true;
    }).catch(() => false);
})();"""


def snapshot_time(value: str, *, now: float | None = None) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Map snapshot has no timestamp")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Map snapshot has no timezone")
    age = (time.time() if now is None else now) - stamp.timestamp()
    if not -60 <= age <= 1800:
        raise ValueError("Map snapshot is stale or has an invalid clock")
    return stamp


def validate_image(data: bytes) -> None:
    if not 10_000 <= len(data) <= 12 * 1024 * 1024:
        raise ValueError("Invalid map image size")
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "PNG" or image.size != (2560, 1440):
            raise ValueError("Invalid map image dimensions")
        image.load()
        # Exclude the header: a loaded title over an empty canvas is not a map.
        sample = image.crop((200, 200, 2360, 1240)).convert("RGB").resize((320, 160))
        if max(ImageStat.Stat(sample).stddev) < 8:
            raise ValueError("Map canvas is blank")


class JerryMapClient:
    def __init__(
        self, output_dir: Path, *, cache_ttl: int = 300,
        timeout: float = 45, proxy_url: str = "",
    ) -> None:
        self.output_dir = Path(output_dir)
        self.cache_ttl = max(0, int(cache_ttl))
        self.timeout = max(1, float(timeout))
        self.proxy_url = proxy_url
        self._playwright = None
        self._browser = None
        self._task: asyncio.Task | None = None
        self._waiters = 0
        self._capture_lock = asyncio.Lock()
        self._closed = False
        self._retry_after = 0.0
        self.capture_stage = "idle"
        self.capture_detail = "not started"
        self.font_source = "remote"

    def _cached(self) -> tuple[str, Path] | None:
        path = self.output_dir / "galaxy.png"
        try:
            meta = json.loads((self.output_dir / "galaxy.json").read_text("utf-8"))
            if not 0 <= time.time() - float(meta["captured_at"]) < self.cache_ttl:
                return None
            snapshot_time(meta["fetched_at"])
            image = path.read_bytes()
            if hashlib.sha256(image).hexdigest() != meta["sha256"]:
                return None
            validate_image(image)
            return meta["fetched_at"], path
        except (OSError, ValueError, KeyError, TypeError):
            return None

    async def capture(self) -> tuple[str, Path]:
        if self._closed:
            raise RuntimeError("Map client is closed")
        async with asyncio.timeout(self.timeout):
            cached = self._cached()
            if cached:
                self.capture_stage = "cache"
                return cached
            if self._task is None:
                if time.monotonic() < self._retry_after:
                    raise RuntimeError("Map capture temporarily unavailable")
                self._task = asyncio.create_task(self._capture_bounded())
            task = self._task
            self._waiters += 1
            try:
                return await asyncio.shield(task)
            finally:
                self._waiters -= 1
                if self._waiters == 0:
                    if self._task is task:
                        self._task = None
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    async def _start(self) -> None:
        if self._browser is not None and self._browser.is_connected():
            return
        await self._stop_browser()
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        kwargs = {"headless": True, "args": [
            "--no-sandbox", "--disable-dev-shm-usage",
            # Avoid stalled multiplexed downloads on affected GitHub Pages routes.
            "--disable-http2", "--disable-quic",
        ]}
        if self.proxy_url:
            kwargs["proxy"] = {"server": self.proxy_url}
        self._browser = await self._playwright.chromium.launch(**kwargs)

    async def _stop_browser(self) -> None:
        browser, runtime = self._browser, self._playwright
        self._browser = self._playwright = None
        try:
            if browser is not None:
                await browser.close()
        finally:
            if runtime is not None:
                await runtime.stop()

    async def close(self) -> None:
        self._closed = True
        task = self._task
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with self._capture_lock:
            await self._stop_browser()

    async def _capture_bounded(self) -> tuple[str, Path]:
        async with self._capture_lock:
            if self._closed:
                raise RuntimeError("Map client is closed")
            try:
                async with asyncio.timeout(self.timeout):
                    result = await self._capture_page()
                    HEALTH.record_ok("screenshot", detail="Jerry 中文星图")
                    return result
            except BaseException as exc:
                if not isinstance(exc, asyncio.CancelledError):
                    HEALTH.record_fail("screenshot", detail=f"Jerry: {type(exc).__name__}")
                    self._retry_after = time.monotonic() + 60
                await self._stop_browser()
                raise

    async def _route_font(self, route) -> None:
        try:
            local_ready = await route.request.frame.evaluate(
                "() => window.__hd2LocalFontReady || false"
            )
        except Exception:
            local_ready = False
        if local_ready:
            # Abort only this redundant download after a real CJK face has loaded.
            self.font_source = "local"
            await route.abort()
        else:
            await route.continue_()

    async def _capture_page(self) -> tuple[str, Path]:
        started = time.monotonic()
        self.capture_stage = "browser startup"
        self.capture_detail = "not started"
        self.font_source = "remote"
        await self._start()
        context = await self._browser.new_context(
            viewport={"width": 2560, "height": 1440},
            device_scale_factor=1, locale="zh-CN",
        )
        pending_requests: dict[int, str] = {}
        failed_requests: list[str] = []
        script_errors = 0

        def request_started(request) -> None:
            url = urlsplit(request.url)
            if url.hostname != "jerry114514.github.io":
                return
            pending_requests[id(request)] = url.path[:180]
            if url.path == DATA_PATH and self.capture_stage in {"navigation", "page scripts"}:
                self.capture_stage = "war data response"

        def request_finished(request) -> None:
            pending_requests.pop(id(request), None)

        def request_failed(request) -> None:
            path = pending_requests.pop(id(request), None)
            skipped_font = urlsplit(request.url).path == urlsplit(FONT_URL).path and self.font_source == "local"
            if path and not skipped_font:
                failed_requests.append(path)
                del failed_requests[:-3]

        def script_failed(_error) -> None:
            nonlocal script_errors
            script_errors += 1

        try:
            timeout_ms = int(self.timeout * 1000)
            context.set_default_timeout(timeout_ms)
            await context.add_init_script(LOCAL_FONT_SCRIPT)
            await context.route(FONT_URL, self._route_font)
            context.on("request", request_started)
            context.on("requestfinished", request_finished)
            context.on("requestfailed", request_failed)
            page = await context.new_page()
            page.on("pageerror", script_failed)
            self.capture_stage = "navigation"
            async with page.expect_response(
                lambda r: urlsplit(r.url).hostname == "jerry114514.github.io"
                and urlsplit(r.url).path == DATA_PATH,
                timeout=timeout_ms,
            ) as pending:
                # Readiness below, rather than DOMContentLoaded, decides capture.
                document = await page.goto(
                    MAP_URL, wait_until="commit", timeout=timeout_ms,
                )
                if document is None or document.status != 200:
                    raise ValueError("Map document request failed")
                if self.capture_stage == "navigation":
                    self.capture_stage = "page scripts"
            if urlsplit(page.url)._replace(query="", fragment="") != urlsplit(MAP_URL):
                raise ValueError("Map page redirected outside the fixed target")
            response = await pending.value
            if response.status != 200:
                raise ValueError("Map data request failed")
            self.capture_stage = "war data body"
            data = await response.json()
            if not isinstance(data, dict) or not isinstance(data.get("planets"), list) or not data["planets"]:
                raise ValueError("Map data is incomplete")
            fetched_at = data.get("fetchedAt")
            snapshot_time(fetched_at)
            self.capture_stage = "Chinese fonts"
            await page.evaluate("() => document.fonts.ready")
            self.capture_stage = "map layers and fonts"
            await page.wait_for_function("""() => {
                const m = window.__map;
                const boot = document.getElementById('boot');
                return m && m.isStyleLoaded() && m.areTilesLoaded()
                    && m.getLayer('planet-core') && m.getLayer('planet-label')
                    && m.getSource('planets')
                    && [...document.fonts].some(
                        f => f.family.replace(/['"]/g, '') === 'SourceHanSans'
                            && f.status === 'loaded')
                    && (!boot || getComputedStyle(boot).display === 'none'
                        || getComputedStyle(boot).visibility === 'hidden'
                        || getComputedStyle(boot).opacity === '0');
            }""")
            # Detect upstream DOM/data changes instead of capturing an error screen.
            await page.wait_for_function(
                """stamp => typeof DATA !== 'undefined' && DATA.fetchedAt === stamp
                    && window.__map.querySourceFeatures('planets').length > 0""",
                arg=fetched_at,
            )
            await page.add_style_tag(content="""
                body.aside-collapsed aside { display: none !important; }
                #aside-rail, #aside-backdrop, #tip, #sector-card,
                #aside-toggle, .maplibregl-ctrl { display: none !important; }
            """)
            await page.evaluate("""async () => {
                document.body.classList.add('aside-collapsed');
                window.__map.resize();
                await new Promise(resolve => requestAnimationFrame(
                    () => requestAnimationFrame(resolve)));
            }""")
            await page.wait_for_function(
                "() => window.__map.isStyleLoaded() && window.__map.areTilesLoaded()"
            )
            self.capture_stage = "screenshot"
            image = await page.screenshot(type="png", full_page=False)
            validate_image(image)
            snapshot_time(fetched_at)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            path = self.output_dir / "galaxy.png"
            temporary = self.output_dir / "galaxy.tmp.png"
            meta_tmp = self.output_dir / "galaxy.tmp.json"
            try:
                temporary.write_bytes(image)
                meta_tmp.write_text(json.dumps({
                    "fetched_at": fetched_at, "captured_at": time.time(),
                    "sha256": hashlib.sha256(image).hexdigest(),
                }), encoding="utf-8")
                os.replace(temporary, path)
                os.replace(meta_tmp, self.output_dir / "galaxy.json")
            finally:
                temporary.unlink(missing_ok=True)
                meta_tmp.unlink(missing_ok=True)
            return fetched_at, path
        finally:
            # Snapshot before context.close() turns unfinished requests into failures.
            self.capture_detail = (
                f"elapsed={time.monotonic() - started:.1f}s; budget={self.timeout:g}s; "
                f"font={self.font_source}; "
                f"pending={','.join(sorted(set(pending_requests.values()))[:4]) or 'none'}; "
                f"failed={','.join(failed_requests) or 'none'}; script_errors={script_errors}"
            )
            await context.close()
