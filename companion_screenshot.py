"""Screenshots for trusted Helldivers Companion routes."""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiohttp
from PIL import Image, UnidentifiedImageError

COMPANION_ORIGIN = "https://helldiverscompanion.com/"
COMPANION_HOST = "helldiverscompanion.com"

_NEWS_ROUTE_RE = re.compile(r"^hellpad/gww/news/(?P<id>\d{1,10})$")
_PLANET_ROUTE_RE = re.compile(
    r"^hellpad/planets/(?P<slug>[a-z0-9][a-z0-9_-]{0,63})$"
)
_PLANET_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

_CLEANUP_SCRIPT = r"""
(() => {
  const phrases = [
    "A NEW MESSAGE has been received",
    "A NEW MAJOR ORDER has been issued",
    "A NEW DISPATCH has been broadcast"
  ];
  const hideToasts = () => {
    const nodes = Array.from(document.querySelectorAll("div"));
    const items = nodes.filter((node) => {
      const text = (node.textContent || "").trim();
      return phrases.some((phrase) => text.startsWith(phrase));
    });
    for (const item of items) {
      const container = item.parentElement;
      if (container && container.getBoundingClientRect().width <= 420) {
        container.style.setProperty("display", "none", "important");
      }
    }
  };
  hideToasts();
  new MutationObserver(hideToasts).observe(document.documentElement, {
    childList: true,
    subtree: true
  });
  setInterval(hideToasts, 250);
})();
""".strip()

_PREPARE_CAPTURE_SCRIPT = r"""
({ kind, clip }) => {
  document.querySelectorAll("[data-hd2-capture-root]").forEach((node) => {
    node.removeAttribute("data-hd2-capture-root");
  });

  let root = null;
  if (kind === "news_latest") {
    root = Array.from(document.querySelectorAll("div.inline-block")).find((node) => {
      const text = (node.innerText || "").toUpperCase();
      return text.includes("PROVIDED BY THE MINISTRY OF TRUTH");
    });
  } else if (kind === "station") {
    const candidates = Array.from(document.querySelectorAll("div.flex.flex-col.gap-2"))
      .filter((node) => {
        const text = (node.innerText || "").toUpperCase();
        return text.includes("NEXT FTL JUMP") &&
               text.includes("ORBITAL BLOCKADE") &&
               text.includes("EAGLE STORM");
      });
    const details = candidates.sort((a, b) => {
      const ar = a.getBoundingClientRect();
      const br = b.getBoundingClientRect();
      return ar.width * ar.height - br.width * br.height;
    })[0] || null;
    root = details?.closest(".noselect.inner") || details;
  } else if (kind === "planet") {
    root = document.querySelector(".entire_page") ||
           document.querySelector(".page_wrapper");
  }
  root ||= document.body;
  root.setAttribute("data-hd2-capture-root", "true");

  const nodes = [];
  const unique = new Set();
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const viewportBottom = clip ? clip.y + clip.height : window.innerHeight;
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const parent = node.parentElement;
    const text = (node.nodeValue || "").trim();
    if (!parent || !text || text.length > 1400 || !/[A-Za-z]{3}/.test(text)) continue;
    const style = getComputedStyle(parent);
    const rect = parent.getBoundingClientRect();
    if (style.display === "none" || style.visibility === "hidden" || rect.width <= 0 || rect.height <= 0) continue;
    if ((kind === "planet" || kind === "station") &&
        (rect.bottom < clip.y || rect.top > viewportBottom)) continue;
    nodes.push(node);
    unique.add(text);
    if (unique.size >= 96) break;
  }
  window.__hd2TranslationNodes = nodes;
  return Array.from(unique);
}
""".strip()

_APPLY_TRANSLATIONS_SCRIPT = r"""
(translations) => {
  const nodes = window.__hd2TranslationNodes || [];
  for (const node of nodes) {
    const raw = node.nodeValue || "";
    const source = raw.trim();
    const translated = translations[source];
    if (!translated || translated === source) continue;
    const leading = raw.match(/^\s*/)?.[0] || "";
    const trailing = raw.match(/\s*$/)?.[0] || "";
    node.nodeValue = `${leading}${translated}${trailing}`;
  }
}
""".strip()

class CompanionScreenshotError(RuntimeError):
    """Base exception for Companion screenshot failures."""


class CompanionConfigurationError(CompanionScreenshotError):
    """Raised when the Browserless endpoint is unavailable or invalid."""


class CompanionTargetError(CompanionScreenshotError, ValueError):
    """Raised when a command target is not an allowed Companion route."""


@dataclass(frozen=True, slots=True)
class CompanionTarget:
    kind: Literal["news", "news_latest", "planet", "station"]
    value: str
    url: str
    label: str
    viewport: tuple[int, int]
    clip: tuple[int, int, int, int]

    @property
    def cache_name(self) -> str:
        return f"companion_{self.kind}_{self.value}.png"


TranslationCallback = Callable[
    [CompanionTarget, list[str]], Awaitable["CompanionTranslationResult"]
]


@dataclass(frozen=True, slots=True)
class CompanionTranslationResult:
    translations: dict[str, str]
    cacheable: bool = True


def _fragment_from_value(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        return raw.removeprefix("#").strip("/")

    parsed = urlsplit(raw)
    try:
        port = parsed.port
    except ValueError as exc:
        raise CompanionTargetError("Companion 链接端口格式无效") from exc
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != COMPANION_HOST
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise CompanionTargetError("只允许 helldiverscompanion.com 的 HTTPS 链接")
    return parsed.fragment.strip("/")


def parse_companion_news_target(value: str) -> CompanionTarget:
    fragment = _fragment_from_value(value)
    if fragment is None:
        raise CompanionTargetError("请提供新闻编号或 Companion 新闻链接")
    if fragment.isdigit():
        if _NEWS_ROUTE_RE.fullmatch(f"hellpad/gww/news/{fragment}") is None:
            raise CompanionTargetError("新闻链接格式应为 #hellpad/gww/news/<编号>")
        news_id = fragment
    else:
        match = _NEWS_ROUTE_RE.fullmatch(fragment.casefold())
        if match is None:
            raise CompanionTargetError("新闻链接格式应为 #hellpad/gww/news/<编号>")
        news_id = match.group("id")
    return CompanionTarget(
        kind="news",
        value=news_id,
        url=f"{COMPANION_ORIGIN}#hellpad/gww/news/{news_id}",
        label=f"Helldivers Companion 新闻 #{news_id}",
        viewport=(800, 1000),
        clip=(15, 87, 770, 841),
    )


def companion_latest_news_target() -> CompanionTarget:
    return CompanionTarget(
        kind="news_latest",
        value="latest",
        url=f"{COMPANION_ORIGIN}#news",
        label="Helldivers Companion 最新新闻",
        viewport=(1280, 900),
        clip=(268, 154, 744, 644),
    )


def companion_dss_target() -> CompanionTarget:
    return CompanionTarget(
        kind="station",
        value="dss",
        url=f"{COMPANION_ORIGIN}#hellpad/stations",
        label="Helldivers Companion 民主空间站",
        viewport=(1280, 900),
        clip=(209, 82, 862, 734),
    )


def parse_companion_planet_target(value: str) -> CompanionTarget:
    fragment = _fragment_from_value(value)
    if fragment is None:
        raise CompanionTargetError("请提供星球 slug 或 Companion 星球链接")
    match = _PLANET_ROUTE_RE.fullmatch(fragment.casefold())
    if match is not None:
        slug = match.group("slug")
    else:
        slug = re.sub(r"\s+", "_", fragment.casefold().strip())
        if _PLANET_SLUG_RE.fullmatch(slug) is None:
            raise CompanionTargetError(
                "星球参数仅支持英文 slug，例如 meissa 或 super_earth"
            )
    return CompanionTarget(
        kind="planet",
        value=slug,
        url=f"{COMPANION_ORIGIN}#hellpad/planets/{slug}",
        label=f"Helldivers Companion 星球：{slug.upper()}",
        viewport=(2560, 1440),
        clip=(0, 0, 2560, 1440),
    )


def build_browserless_endpoint(endpoint_url: str, token: str = "") -> str:
    raw = str(endpoint_url or "").strip()
    if not raw:
        raise CompanionConfigurationError("尚未配置 Browserless 截图服务地址")
    parsed = urlsplit(raw)
    try:
        parsed.port
    except ValueError as exc:
        raise CompanionConfigurationError("Browserless 地址端口格式无效") from exc
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise CompanionConfigurationError("Browserless 地址必须是有效的 HTTP(S) URL")
    path = parsed.path.rstrip("/")
    if not path.endswith("/screenshot"):
        path += "/screenshot"
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if token:
        query["token"] = token
    return urlunsplit(
        (parsed.scheme, parsed.netloc, path, urlencode(query), "")
    )


def build_browserless_payload(
    target: CompanionTarget,
    *,
    timeout_ms: int,
    wait_ms: int,
) -> dict:
    width, height = target.viewport
    x, y, clip_width, clip_height = target.clip
    return {
        "url": target.url,
        "gotoOptions": {
            "waitUntil": "networkidle2",
            "timeout": max(10_000, int(timeout_ms)),
        },
        "viewport": {
            "width": width,
            "height": height,
            "deviceScaleFactor": 1,
        },
        "waitForTimeout": max(0, int(wait_ms)),
        "addScriptTag": [{"content": _CLEANUP_SCRIPT}],
        "options": {
            "type": "png",
            "fullPage": False,
            "captureBeyondViewport": False,
            "clip": {
                "x": x,
                "y": y,
                "width": clip_width,
                "height": clip_height,
            },
        },
    }


def _browserless_connection_error(endpoint: str, exc: BaseException) -> str:
    if isinstance(exc, aiohttp.ClientConnectorDNSError):
        host = urlsplit(endpoint).hostname or "配置的主机"
        return (
            f"无法解析 Browserless 主机 {host}。如果使用 http://browserless:3000，"
            "请确认 AstrBot 与 Browserless 在同一个 Docker 网络；如果 AstrBot 在"
            "宿主机/Windows 运行，请将 Browserless 映射到本机端口，并把 "
            "companion_browserless_url 改为 http://127.0.0.1:3000。"
        )
    return f"连接 Browserless 失败 ({type(exc).__name__})"


class CompanionScreenshotClient:
    def __init__(
        self,
        output_dir: Path,
        *,
        endpoint_url: str,
        token: str = "",
        proxy_url: str = "",
        timeout: int = 90,
        wait_ms: int = 5_000,
        cache_ttl: int = 300,
        max_bytes: int = 12 * 1024 * 1024,
        max_pixels: int = 20_000_000,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.endpoint = build_browserless_endpoint(endpoint_url, token)
        self.proxy_url = str(proxy_url or "").strip()
        self.timeout = max(15, int(timeout))
        self.wait_ms = max(0, min(30_000, int(wait_ms)))
        self.cache_ttl = max(0, int(cache_ttl))
        self.max_bytes = max(1024, int(max_bytes))
        self.max_pixels = max(1_000_000, int(max_pixels))
        self._locks: dict[str, asyncio.Lock] = {}
        self._lock_refs: dict[str, int] = {}

    async def capture(self, target: CompanionTarget, *, force: bool = False) -> Path:
        output = self.output_dir / target.cache_name
        if not force and self._cache_is_fresh(output):
            return output
        key = target.cache_name
        lock = self._locks.setdefault(key, asyncio.Lock())
        self._lock_refs[key] = self._lock_refs.get(key, 0) + 1
        try:
            async with lock:
                if not force and self._cache_is_fresh(output):
                    return output
                await self._capture_uncached(target, output)
                self._cleanup()
                return output
        finally:
            remaining = self._lock_refs.get(key, 1) - 1
            if remaining <= 0:
                self._lock_refs.pop(key, None)
                if self._locks.get(key) is lock and not lock.locked():
                    self._locks.pop(key, None)
            else:
                self._lock_refs[key] = remaining

    def _cache_is_fresh(self, path: Path) -> bool:
        try:
            return (
                self.cache_ttl > 0
                and path.is_file()
                and time.time() - path.stat().st_mtime <= self.cache_ttl
            )
        except OSError:
            return False

    async def _capture_uncached(self, target: CompanionTarget, output: Path) -> None:
        timeout_ms = self.timeout * 1000
        payload = build_browserless_payload(
            target,
            timeout_ms=timeout_ms,
            wait_ms=self.wait_ms,
        )
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
        try:
            async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
                async with session.post(
                    self.endpoint,
                    json=payload,
                    proxy=self.proxy_url or None,
                ) as response:
                    if response.status != 200:
                        detail = (await response.content.read(1024)).decode(
                            "utf-8", errors="replace"
                        )
                        raise CompanionScreenshotError(
                            f"Browserless 返回 HTTP {response.status}: {detail[:300]}"
                        )
                    content_type = response.headers.get("Content-Type", "").split(
                        ";", 1
                    )[0].casefold()
                    if content_type not in {
                        "image/png",
                        "image/jpeg",
                        "image/webp",
                        "application/octet-stream",
                    }:
                        raise CompanionScreenshotError(
                            f"Browserless 返回了非图片内容: {content_type or 'unknown'}"
                        )
                    total = 0
                    with temporary.open("wb") as handle:
                        async for chunk in response.content.iter_chunked(64 * 1024):
                            total += len(chunk)
                            if total > self.max_bytes:
                                raise CompanionScreenshotError("网页截图超过允许的文件大小")
                            handle.write(chunk)
            self._validate_image(temporary)
            temporary.replace(output)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise CompanionScreenshotError(
                _browserless_connection_error(self.endpoint, exc)
            ) from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _validate_image(self, path: Path) -> None:
        try:
            with Image.open(path) as image:
                if image.width * image.height > self.max_pixels:
                    raise CompanionScreenshotError("网页截图像素数量超过安全限制")
                if image.format not in {"PNG", "JPEG", "WEBP"}:
                    raise CompanionScreenshotError("Browserless 返回了不支持的图片格式")
                image.verify()
        except (OSError, UnidentifiedImageError) as exc:
            raise CompanionScreenshotError("Browserless 返回的图片无法解码") from exc

    def _cleanup(self, max_age: int = 86_400) -> None:
        cutoff = time.time() - max(3600, int(max_age))
        try:
            for path in self.output_dir.glob("companion_*.png"):
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
        except OSError:
            pass


class CompanionPlaywrightClient:
    """Render Companion pages with Chromium inside the AstrBot container."""

    def __init__(
        self,
        output_dir: Path,
        *,
        timeout: int = 90,
        wait_ms: int = 5_000,
        cache_ttl: int = 300,
        max_bytes: int = 12 * 1024 * 1024,
        max_pixels: int = 20_000_000,
        concurrency: int = 2,
        translate_callback: TranslationCallback | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = max(15, int(timeout))
        self.wait_ms = max(0, min(30_000, int(wait_ms)))
        self.cache_ttl = max(0, int(cache_ttl))
        self.max_bytes = max(1024, int(max_bytes))
        self.max_pixels = max(1_000_000, int(max_pixels))
        self.translate_callback = translate_callback
        self._cache_namespace = "source"
        self._playwright = None
        self._browser = None
        self._start_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max(1, min(4, int(concurrency))))
        self._locks: dict[str, asyncio.Lock] = {}
        self._lock_refs: dict[str, int] = {}

    def set_translate_callback(
        self,
        callback: TranslationCallback | None,
        *,
        cache_namespace: str = "",
    ) -> None:
        self.translate_callback = callback
        if callback is None:
            self._cache_namespace = "source"
            return
        fingerprint = str(cache_namespace or "translated")
        digest = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:10]
        self._cache_namespace = f"translated_{digest}"

    async def start(self) -> None:
        if self._browser is not None and self._browser.is_connected():
            return
        async with self._start_lock:
            if self._browser is not None and self._browser.is_connected():
                return
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise CompanionConfigurationError(
                    "未安装 Playwright，请在 AstrBot 容器中安装 playwright"
                ) from exc
            try:
                playwright = await async_playwright().start()
                browser = await playwright.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
            except Exception as exc:
                try:
                    await playwright.stop()  # type: ignore[possibly-undefined]
                except Exception:
                    pass
                raise CompanionConfigurationError(
                    f"本地 Chromium 启动失败: {type(exc).__name__}: {exc}"
                ) from exc
            self._playwright = playwright
            self._browser = browser

    async def close(self) -> None:
        browser = self._browser
        playwright = self._playwright
        self._browser = None
        self._playwright = None
        if browser is not None:
            await browser.close()
        if playwright is not None:
            await playwright.stop()

    async def capture(self, target: CompanionTarget, *, force: bool = False) -> Path:
        output = self.output_dir / (
            f"playwright_v9_{self._cache_namespace}_{target.cache_name}"
        )
        if not force and self._cache_is_fresh(output):
            return output
        try:
            async with asyncio.timeout(self.timeout):
                return await self._capture_within_timeout(target, output, force=force)
        except TimeoutError as exc:
            raise CompanionScreenshotError(
                f"Companion 截图总耗时超过 {self.timeout} 秒"
            ) from exc

    async def _capture_within_timeout(
        self,
        target: CompanionTarget,
        output: Path,
        *,
        force: bool,
    ) -> Path:
        await self.start()
        key = target.cache_name
        lock = self._locks.setdefault(key, asyncio.Lock())
        self._lock_refs[key] = self._lock_refs.get(key, 0) + 1
        try:
            async with lock:
                if not force and self._cache_is_fresh(output):
                    return output
                async with self._semaphore:
                    captured = await self._capture_uncached(target, output)
                self._cleanup()
                return captured
        finally:
            remaining = self._lock_refs.get(key, 1) - 1
            if remaining <= 0:
                self._lock_refs.pop(key, None)
                if self._locks.get(key) is lock and not lock.locked():
                    self._locks.pop(key, None)
            else:
                self._lock_refs[key] = remaining

    async def _capture_uncached(self, target: CompanionTarget, output: Path) -> Path:
        browser = self._browser
        if browser is None or not browser.is_connected():
            raise CompanionScreenshotError("本地 Chromium 尚未启动")
        width, height = target.viewport
        x, y, clip_width, clip_height = target.clip
        temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
        context = None
        failed_requests: list[str] = []
        cacheable = True
        try:
            context = await browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=1,
                locale="en-US",
                ignore_https_errors=True,
            )
            page = await context.new_page()
            page.on(
                "requestfailed",
                lambda request: failed_requests.append(
                    f"{request.url} ({request.failure or 'failed'})"
                ),
            )
            await page.goto(
                target.url,
                wait_until="commit",
                timeout=min(30_000, self.timeout * 1000),
            )
            try:
                await page.wait_for_function(
                    """
                    ({ kind, expected }) => {
                      const text = (document.body?.innerText || "").toUpperCase();
                      if (text.length <= 200 ||
                          text.includes("PLEASE WAIT DEMOCRATICALLY")) {
                        return false;
                      }
                      if (kind === "news_latest") {
                        return text.includes("REVIEW MESSAGE FROM SUPER EARTH") &&
                               text.includes("PROVIDED BY THE MINISTRY OF TRUTH");
                      }
                      if (kind === "news") {
                        return text.includes(`ID ${expected}`) ||
                               (text.includes("STROHMANN") && text.includes("NEWS"));
                      }
                      if (kind === "station") {
                        return text.includes("NEXT FTL JUMP") &&
                               (text.includes("ORBITAL BLOCKADE") ||
                                text.includes("EAGLE STORM") ||
                                text.includes("HEAVY ORDNANCE DISTRIBUTION"));
                      }
                      return text.includes(expected);
                    }
                    """,
                    arg={
                        "kind": target.kind,
                        "expected": target.value.replace("_", " ").upper(),
                    },
                    timeout=self.timeout * 1000,
                )
            except Exception as exc:
                details = "; ".join(failed_requests[-5:])
                suffix = f"；失败请求：{details}" if details else ""
                raise CompanionScreenshotError(
                    f"Companion 页面数据加载超时{suffix}"
                ) from exc
            await page.add_script_tag(content=_CLEANUP_SCRIPT)
            await page.wait_for_timeout(self.wait_ms)
            translations_source = await page.evaluate(
                _PREPARE_CAPTURE_SCRIPT,
                {
                    "kind": target.kind,
                    "clip": {
                        "x": x,
                        "y": y,
                        "width": clip_width,
                        "height": clip_height,
                    },
                },
            )
            if self.translate_callback is not None and isinstance(
                translations_source, list
            ):
                source_texts = [
                    str(value).strip()
                    for value in translations_source
                    if isinstance(value, str) and value.strip()
                ]
                outcome = await self.translate_callback(target, source_texts)
                cacheable = outcome.cacheable
                if outcome.translations:
                    await page.evaluate(
                        _APPLY_TRANSLATIONS_SCRIPT,
                        outcome.translations,
                    )
                    await page.wait_for_timeout(500)

            if target.kind in {"news_latest", "station"}:
                await page.locator('[data-hd2-capture-root="true"]').screenshot(
                    path=str(temporary),
                    type="png",
                    animations="disabled",
                )
            else:
                await page.screenshot(
                    path=str(temporary),
                    type="png",
                    animations="disabled",
                    clip={
                        "x": x,
                        "y": y,
                        "width": clip_width,
                        "height": clip_height,
                    },
                )
            self._validate_image(temporary)
            destination = output
            if not cacheable:
                destination = output.with_name(
                    f"playwright_uncached_{uuid.uuid4().hex}_{target.cache_name}"
                )
            temporary.replace(destination)
            return destination
        except CompanionScreenshotError:
            raise
        except Exception as exc:
            raise CompanionScreenshotError(
                f"本地 Playwright 截图失败 ({type(exc).__name__}): {exc}"
            ) from exc
        finally:
            if context is not None:
                await context.close()
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _cache_is_fresh(self, path: Path) -> bool:
        try:
            return (
                self.cache_ttl > 0
                and path.is_file()
                and time.time() - path.stat().st_mtime <= self.cache_ttl
            )
        except OSError:
            return False

    def _validate_image(self, path: Path) -> None:
        try:
            if path.stat().st_size > self.max_bytes:
                raise CompanionScreenshotError("网页截图超过允许的文件大小")
            with Image.open(path) as image:
                if image.width * image.height > self.max_pixels:
                    raise CompanionScreenshotError("网页截图像素数量超过安全限制")
                if image.format != "PNG":
                    raise CompanionScreenshotError("本地浏览器返回了非 PNG 图片")
                image.verify()
        except (OSError, UnidentifiedImageError) as exc:
            raise CompanionScreenshotError("本地浏览器返回的图片无法解码") from exc

    def _cleanup(self, max_age: int = 86_400) -> None:
        cutoff = time.time() - max(3600, int(max_age))
        try:
            for path in self.output_dir.glob("playwright_*companion_*.png"):
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
        except OSError:
            pass


__all__ = [
    "COMPANION_ORIGIN",
    "CompanionConfigurationError",
    "CompanionPlaywrightClient",
    "CompanionScreenshotClient",
    "CompanionScreenshotError",
    "CompanionTarget",
    "CompanionTargetError",
    "CompanionTranslationResult",
    "TranslationCallback",
    "build_browserless_endpoint",
    "build_browserless_payload",
    "companion_dss_target",
    "companion_latest_news_target",
    "parse_companion_news_target",
    "parse_companion_planet_target",
]
