"""第三方翻译 API + 本地翻译缓存。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

import aiohttp
from astrbot.api import logger

from .plugin_info import USER_AGENT


class TranslationService:
    """调用外部翻译接口，失败回退原文。"""

    def __init__(
        self,
        *,
        api_url: str,
        timeout: int = 30,
        target_lang: str = "zh",
        user_agent: str = USER_AGENT,
        proxy_url: str = "",
        enabled: bool = True,
        session: aiohttp.ClientSession | None = None,
        mode: str = "builtin",
        api_key: str = "",
        model: str = "gpt-4o-mini",
        fallback_ttl: int = 900,
    ) -> None:
        self.api_url = (api_url or "").strip()
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.target_lang = target_lang or "zh"
        self.user_agent = user_agent
        self.proxy_url = proxy_url or None
        self.enabled = enabled
        self._session = session
        self._own_session = False
        requested_mode = (mode or "auto").strip().lower()
        if requested_mode not in {"builtin", "openai", "auto"}:
            logger.warning(
                "[HD2] unknown translation_mode=%s; using auto mode", requested_mode
            )
            requested_mode = "auto"
        self.requested_mode = requested_mode
        self.api_key = (api_key or "").strip()
        self.model = (model or "gpt-4o-mini").strip()
        self.fallback_ttl = max(60, int(fallback_ttl))
        self.mode = self._resolve_mode()

    def _resolve_mode(self) -> str:
        if self.requested_mode != "auto":
            return self.requested_mode
        path = urlsplit(self.api_url).path.lower()
        if self.api_key and (
            path.endswith("/chat/completions")
            or path.endswith("/v1")
            or "/openai" in path
            or "/oneapi" in path
            or path in {"", "/"}
        ):
            return "openai"
        return "builtin"

    def provider_fingerprint(self) -> str:
        parts = (
            "translation-protocol-v2",
            self.mode,
            urlsplit(self.api_url).scheme.lower(),
            urlsplit(self.api_url).netloc.lower(),
            urlsplit(self.api_url).path.rstrip("/").lower(),
            self.model if self.mode == "openai" else "",
            self.target_lang,
        )
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]

    def diagnostic(self) -> dict[str, Any]:
        parsed = urlsplit(self.api_url)
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "requested_mode": self.requested_mode,
            "url": f"{parsed.scheme}://{parsed.netloc}{parsed.path}" if parsed.netloc else "unset",
            "model": self.model,
            "key_present": bool(self.api_key),
            "target_lang": self.target_lang,
        }

    def bind_session(self, session: aiohttp.ClientSession | None) -> None:
        self._session = session
        self._own_session = False

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is not None and not self._session.closed:
            return self._session
        self._session = aiohttp.ClientSession(timeout=self.timeout)
        self._own_session = True
        return self._session

    async def close(self) -> None:
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()
        if self._own_session:
            self._session = None
            self._own_session = False

    def _chat_url(self) -> str:
        """openai 模式：允许填 base 或完整 chat 地址。"""
        url = self.api_url.rstrip("/")
        if url.endswith("/chat/completions"):
            return url
        if url.endswith("/v1"):
            return url + "/chat/completions"
        # 裸域名/base：补全
        return url + "/v1/chat/completions"

    async def translate_text(self, text: str, to_lang: str | None = None) -> str:
        if not text or not text.strip() or len(text.strip()) < 3:
            return text or ""
        if not self.enabled or not self.api_url:
            return text
        if self.mode == "openai":
            return await self._translate_openai(text, to_lang)
        return await self._translate_builtin(text, to_lang)

    @staticmethod
    def _extract_builtin_translation(data: dict[str, Any]) -> str:
        """Accept the documented endpoint plus common proxy response envelopes."""
        candidates: list[Any] = [
            data.get("translatedText"),
            data.get("translated_text"),
            data.get("translation"),
            data.get("result"),
        ]
        nested = data.get("data")
        if isinstance(nested, dict):
            candidates.extend(
                nested.get(key)
                for key in ("translatedText", "translated_text", "translation", "result")
            )
        for value in candidates:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _uapi_target_lang(value: str) -> str:
        language = str(value or "zh").strip()
        if language.casefold() in {"zh-cn", "zh-hans", "zh-sg"}:
            return "zh"
        return language

    def _builtin_request(
        self, text: str, to_lang: str | None
    ) -> tuple[dict[str, Any], dict[str, str], dict[str, str] | None]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        path = urlsplit(self.api_url).path.rstrip("/").lower()
        if path.endswith("/ai/translate"):
            payload = {
                "text": text.strip(),
                "style": "professional",
                "context": "entertainment",
                "preserve_format": True,
            }
            params = {
                "target_lang": self._uapi_target_lang(
                    to_lang or self.target_lang
                )
            }
            return payload, headers, params
        payload = {
            "text": text.strip(),
            "sourceLanguage": "auto",
            "targetLanguage": to_lang or self.target_lang,
        }
        return payload, headers, None

    async def _translate_builtin(self, text: str, to_lang: str | None) -> str:
        payload, headers, params = self._builtin_request(text, to_lang)
        try:
            session = await self._ensure_session()
            async with session.post(
                self.api_url,
                params=params,
                json=payload,
                headers=headers,
                proxy=self.proxy_url,
                timeout=self.timeout,
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        f"[HD2] translation API status={resp.status} for text={text[:40]!r}"
                    )
                    return text
                data = await resp.json(content_type=None)
                if not isinstance(data, dict):
                    return text
                translated = self._extract_builtin_translation(data)
                if translated and translated != text.strip():
                    return translated
                nested = data.get("data")
                logger.warning(
                    "[HD2] translation response missing translated text; keys=%s data_keys=%s",
                    sorted(str(key) for key in data.keys())[:12],
                    sorted(str(key) for key in nested.keys())[:12]
                    if isinstance(nested, dict)
                    else [],
                )
                return text
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"[HD2] translation failed: {e}")
            return text

    async def _translate_openai(self, text: str, to_lang: str | None) -> str:
        if not self.api_key:
            logger.warning("[HD2] openai 翻译模式缺少 api_key，返回原文")
            return text
        lang = to_lang or self.target_lang or "zh"
        lang_name = "简体中文" if lang.startswith("zh") else lang
        system = (
            f"你是 Helldivers 2（绝地潜兵2）游戏本地化助手。"
            f"将用户提供的英文游戏文本翻译为{lang_name}，"
            f"保留阵营/专有名词/星球名的习惯译法，语气贴合游戏。"
            f"只返回译文，不要解释、不要引号。"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text.strip()},
            ],
            "temperature": 0.3,
            "stream": False,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        try:
            session = await self._ensure_session()
            async with session.post(
                self._chat_url(),
                json=payload,
                headers=headers,
                proxy=self.proxy_url,
                timeout=self.timeout,
            ) as resp:
                if resp.status != 200:
                    body = ""
                    try:
                        body = (await resp.text())[:160]
                    except Exception:
                        pass
                    logger.warning(
                        f"[HD2] openai 翻译 status={resp.status} body={body}"
                    )
                    return text
                data = await resp.json(content_type=None)
                choices = (data or {}).get("choices") or []
                if not choices:
                    return text
                content = (
                    (choices[0].get("message") or {}).get("content") or ""
                ).strip()
                # 去掉可能的包裹引号
                content = content.strip().strip('"').strip("“”").strip()
                if content and content != text.strip():
                    return content
                return text
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"[HD2] openai 翻译失败: {e}")
            return text


class TranslationCache:
    """翻译结果内存 + 磁盘缓存。"""

    def __init__(
        self,
        data_dir: Path,
        *,
        provider_fingerprint: str = "",
        fallback_ttl: int = 900,
    ) -> None:
        self.path = data_dir / "translations.json"
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self.provider_fingerprint = provider_fingerprint
        self.fallback_ttl = max(60, int(fallback_ttl))
        self.load()

    @staticmethod
    def _key(content_type: str, item_id: str) -> str:
        return f"{content_type}:{item_id}"

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = raw
        except Exception as e:
            logger.warning(f"[HD2] load translation cache failed: {e}")
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
            logger.warning(f"[HD2] save translation cache failed: {e}")
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass

    async def get(self, content_type: str, item_id: str) -> Optional[dict[str, Any]]:
        async with self._lock:
            entry = self._data.get(self._key(content_type, item_id))
            if not isinstance(entry, dict):
                return None
            now = time.time()
            entry_fingerprint = str(entry.get("provider_fingerprint") or "")
            success = bool(entry.get("success", entry.get("translated_text") != entry.get("original_text")))
            if self.provider_fingerprint and entry_fingerprint != self.provider_fingerprint:
                return None
            if not success and now - float(entry.get("updated_at") or 0) > self.fallback_ttl:
                return None
            return entry

    async def store(
        self,
        content_type: str,
        item_id: str,
        original_text: str,
        translated_text: str,
        metadata: dict[str, Any] | None = None,
        success: bool | None = None,
        fallback_reason: str = "",
    ) -> None:
        is_success = (
            bool(success)
            if success is not None
            else bool(translated_text.strip() and translated_text.strip() != original_text.strip())
        )
        entry = {
            "original_text": original_text,
            "translated_text": translated_text,
            "metadata": metadata or {},
            "content_type": content_type,
            "item_id": item_id,
            "updated_at": time.time(),
            "success": is_success,
            "fallback_reason": fallback_reason if not is_success else "",
            "provider_fingerprint": self.provider_fingerprint,
        }
        async with self._lock:
            self._data[self._key(content_type, item_id)] = entry
            self.save()

    async def clear_outdated(self, content_type: str, keep_ids: list[str]) -> None:
        keep = set(keep_ids)
        prefix = f"{content_type}:"
        async with self._lock:
            remove_keys = [
                k
                for k in self._data
                if k.startswith(prefix) and k[len(prefix) :] not in keep
            ]
            for k in remove_keys:
                self._data.pop(k, None)
            if remove_keys:
                self.save()
